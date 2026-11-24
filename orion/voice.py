"""Voice: expressive speech out (sentence-streamed, audio-reactive) and smart listening in."""
import asyncio
import os
import queue
import random
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import requests

from .humanize import clean_for_speech, edge_prosody, eleven_settings, maybe_filler, split_sentences

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
HALLUCINATIONS = {"you", "thank you", "thanks for watching", "thanks", "bye", "okay", "uh", "um", "hmm"}


class Voice:
    """cb(kind, **data) receives: speaking_start, speaking_end, level, hearing, error."""

    def __init__(self, cfg, cb):
        self.cfg = cfg.get("voice", {})
        self.name = cfg.get("assistant_name", "Orion")
        self.user = cfg.get("user_name", "")
        self.cb = cb
        self.speak_enabled = bool(self.cfg.get("speak", True))
        self.q = queue.Queue()
        self._pending = 0
        self._plock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._gen = 0
        self._speaking = False
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._fails = 0
        self._degraded_until = 0.0
        self._warned = set()
        self._tts = None
        self._whisper = None
        self._noise = None
        threading.Thread(target=self._worker, daemon=True).start()

    # ================= speaking =================
    def speak(self, text, emotion="neutral"):
        if not self.speak_enabled:
            return
        text = clean_for_speech(text)
        if not text:
            return
        with self._plock:
            self._pending += 1
            self._idle.clear()
        self.q.put((text, emotion, self._gen))

    def is_speaking(self):
        return self._pending > 0

    def wait_done(self, timeout=180):
        self._idle.wait(timeout)

    def stop_speaking(self):
        self._gen += 1                      # invalidates everything queued or playing
        try:
            while True:
                self.q.get_nowait()
                self._job_done()
        except queue.Empty:
            pass

    def _job_done(self):
        with self._plock:
            self._pending = max(0, self._pending - 1)
            if self._pending == 0:
                self._idle.set()

    def _warn(self, key, text):
        if key not in self._warned:
            self._warned.add(key)
            self.cb("error", text=text)

    def _worker(self):
        while True:
            text, emotion, gen = self.q.get()
            try:
                if gen == self._gen:
                    self._speak_job(text, emotion, gen)
            except Exception as e:
                self._warn("worker", f"Speech problem: {type(e).__name__}: {e}")
            finally:
                self._job_done()
                if self._pending == 0 and self._speaking:
                    self._speaking = False
                    self.cb("speaking_end")

    def _speak_job(self, text, emotion, gen):
        sentences = split_sentences(text)
        if not sentences:
            return
        sentences[0] = maybe_filler(sentences[0], emotion, self.cfg.get("fillers", True))
        if not self._speaking:
            self._speaking = True
            self.cb("speaking_start")
        fut = self._pool.submit(self._synth, sentences[0], emotion)
        for i, sentence in enumerate(sentences):
            path = fut.result()
            fut = self._pool.submit(self._synth, sentences[i + 1], emotion) if i + 1 < len(sentences) else None
            if gen != self._gen:
                break
            if path:
                self._play(path, gen)
            else:
                self._say_builtin(sentence, gen)
            if i + 1 < len(sentences) and gen == self._gen:
                time.sleep(random.uniform(0.05, 0.16))      # a natural breath between sentences

    # ----- synthesis -----
    def _synth(self, text, emotion):
        engine = self.cfg.get("tts", "edge")
        if engine == "pyttsx3" or time.time() < self._degraded_until:
            return None
        try:
            expressive = self.cfg.get("expressive", True)
            if engine == "elevenlabs":
                path = self._eleven(text, emotion, expressive)
            elif engine == "piper":
                path = self._piper(text)
            else:
                path = self._edge(text, emotion, expressive)
            self._fails = 0
            return path
        except Exception as e:
            self._fails += 1
            if self._fails >= 3:
                self._degraded_until = time.time() + 300
            self._warn(f"synth-{engine}", f"{engine} voice failed ({type(e).__name__}: {e}). "
                       "Using the built-in voice for now.")
            return None

    def _tmp(self, ext):
        return os.path.join(tempfile.gettempdir(), f"orion_{uuid.uuid4().hex}.{ext}")

    def _edge(self, text, emotion, expressive):
        import edge_tts
        path = self._tmp("mp3")
        pr = edge_prosody(emotion, expressive)

        async def go():
            await edge_tts.Communicate(text, self.cfg.get("edge_voice", "en-GB-RyanNeural"),
                                       rate=pr["rate"], pitch=pr["pitch"], volume=pr["volume"]).save(path)
        asyncio.run(go())
        return path

    def _eleven(self, text, emotion, expressive):
        key = os.getenv("ELEVENLABS_API_KEY")
        vid = self.cfg.get("elevenlabs_voice_id")
        if not key or not vid:
            raise RuntimeError("ELEVENLABS_API_KEY or elevenlabs_voice_id missing")
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                          headers={"xi-api-key": key, "accept": "audio/mpeg"},
                          json={"text": text, "model_id": self.cfg.get("elevenlabs_model", "eleven_multilingual_v2"),
                                "voice_settings": eleven_settings(emotion, expressive)}, timeout=60)
        r.raise_for_status()
        path = self._tmp("mp3")
        with open(path, "wb") as f:
            f.write(r.content)
        return path

    def _piper(self, text):
        model = self.cfg.get("piper_model")
        if not model:
            raise RuntimeError("piper_model is not set in config.yaml")
        path = self._tmp("wav")
        subprocess.run([self.cfg.get("piper_bin", "piper"), "--model", model, "--output_file", path],
                       input=text.encode("utf-8"), check=True, capture_output=True, timeout=60)
        return path

    def _say_builtin(self, text, gen):
        try:
            import pyttsx3
            if self._tts is None:
                self._tts = pyttsx3.init()
            self._tts.say(text)
            if gen == self._gen:
                self._tts.runAndWait()
        except Exception as e:
            self._warn("pyttsx3", f"No voice available ({type(e).__name__}: {e}). Showing text only.")

    # ----- playback with a real audio envelope for the orb -----
    @staticmethod
    def _envelope(snd):
        """Per-40ms loudness plus bass/mid/high energy of the clip, so the hologram follows his actual voice."""
        try:
            import pygame
            from .hologram import envelope_from_samples
            arr = pygame.sndarray.array(snd).astype("float32")
            if arr.ndim > 1:
                arr = arr.mean(axis=1)
            return envelope_from_samples(arr, pygame.mixer.get_init()[0])
        except Exception:
            return None

    def _play(self, path, gen):
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        snd = pygame.mixer.Sound(path)
        env = self._envelope(snd)
        ch = snd.play()
        t0 = time.monotonic()
        while ch is not None and ch.get_busy():
            if gen != self._gen:
                ch.stop()
                break
            idx = int((time.monotonic() - t0) / 0.04)
            if env is not None:
                row = env[min(idx, len(env) - 1)]
                self.cb("level", source="voice", value=float(row[0]), bands=(float(row[1]), float(row[2]), float(row[3])))
            else:
                self.cb("level", source="voice", value=0.35 + 0.3 * random.random())
            time.sleep(0.03)
        try:
            os.remove(path)
        except OSError:
            pass

    # ================= listening =================
    def listen(self, max_wait=5.0):
        """Wait up to max_wait seconds for speech; return the transcript ('' if none)."""
        import numpy as np
        import sounddevice as sd
        sr, step = 16000, 0.05
        block = int(sr * step)
        floor = float(self.cfg.get("silence_threshold", 0.015))
        if self._noise is None:
            self._noise = floor / 3
        pre = deque(maxlen=7)
        frames, started, silent, waited, total = [], False, 0.0, 0.0, 0.0
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=block) as stream:
            while True:
                data, _ = stream.read(block)
                rms = float(np.sqrt((data ** 2).mean()))
                thresh = max(floor, self._noise * 3.0)
                self.cb("level", source="mic", value=min(1.0, rms / (thresh * 4)))
                if not started:
                    pre.append(data)
                    if rms > thresh:
                        started, frames = True, list(pre)
                        self.cb("hearing")
                    else:
                        self._noise = 0.97 * self._noise + 0.03 * rms      # adapt to the room
                        waited += step
                        if waited >= max_wait:
                            return ""
                else:
                    frames.append(data)
                    total += step
                    silent = 0.0 if rms > thresh else silent + step
                    if silent >= 0.9 or total >= 30:
                        break
        audio = np.concatenate(frames).flatten()
        if len(audio) < sr * 0.35:
            return ""
        return self._transcribe(audio)

    def _transcribe(self, audio):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(self.cfg.get("stt_model", "base.en"), compute_type="int8")
        prompt = f"A conversation with a personal assistant named {self.name}." + (f" The user is {self.user}." if self.user else "")
        segments, _ = self._whisper.transcribe(audio, language=self.cfg.get("stt_language", "en"), beam_size=1,
                                               vad_filter=True, condition_on_previous_text=False,
                                               initial_prompt=prompt)
        text = " ".join(s.text for s in segments).strip()
        return "" if text.lower().strip(" .!?,") in HALLUCINATIONS else text
