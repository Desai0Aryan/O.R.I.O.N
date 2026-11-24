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

from .humanize import clean_for_speech, edge_prosody, eleven_settings, maybe_filler, pronounce, split_sentences

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
HALLUCINATIONS = {"you", "thank you", "thanks for watching", "thanks", "bye", "okay", "uh", "um", "hmm"}


class Voice:
    """cb(kind, **data) receives: speaking_start, speaking_end, level, hearing, error."""

    def __init__(self, cfg, cb):
        self.cfg = cfg.get("voice", {})
        self.name = cfg.get("assistant_name", "Orion")
        self.user = cfg.get("user_name", "")
        self.say_as = self.cfg.get("say_name_as", "Oh-ee-on")
        self.cb = cb
        self.speak_enabled = bool(self.cfg.get("speak", True))
        self.q = queue.Queue()                  # (future|None, sentence, emotion, generation), in speaking order
        self._pending = 0
        self._plock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._gen = 0
        self._speaking = False
        self._spoke_at = 0.0
        self._pool = ThreadPoolExecutor(max_workers=2)     # sentences are synthesised ahead of playback
        self._fails = 0
        self._degraded_until = 0.0
        self._warned = set()
        self._tts = None
        self._whisper = None
        self._whisper_lock = threading.Lock()
        self._noise = None
        self._mic = None
        self._mic_sr = 16000
        self._mq = None
        self._pre = deque(maxlen=12)            # ~0.36 s of audio before speech starts
        self._last_listen = 0.0
        self.vocab = []                         # names and terms that help the recogniser
        threading.Thread(target=self._worker, daemon=True).start()

    # ================= speaking =================
    def speak(self, text, emotion="neutral"):
        """Queue text. Every sentence is synthesised in the background while the previous one plays,
        so he can start talking after the first sentence and never pauses between them."""
        if not self.speak_enabled:
            return
        text = pronounce(clean_for_speech(text), self.name, self.say_as)
        if not text:
            return
        sentences = split_sentences(text)
        if not sentences:
            return
        if not self._speaking and self._pending == 0:
            sentences[0] = maybe_filler(sentences[0], emotion, self.cfg.get("fillers", True))
        gen = self._gen
        engine = self.cfg.get("tts", "edge")
        for sentence in sentences:
            with self._plock:
                self._pending += 1
                self._idle.clear()
            fut = None if engine == "pyttsx3" else self._pool.submit(self._synth, sentence, emotion)
            self.q.put((fut, sentence, emotion, gen))

    def is_speaking(self):
        return self._pending > 0

    def wait_done(self, timeout=180):
        self._idle.wait(timeout)

    def stop_speaking(self):
        self._gen += 1                      # invalidates everything queued or playing
        try:
            while True:
                fut, *_ = self.q.get_nowait()
                if fut is not None:
                    fut.cancel()
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
            fut, sentence, emotion, gen = self.q.get()
            try:
                if gen == self._gen:
                    if not self._speaking:
                        self._speaking = True
                        self.cb("speaking_start")
                    path = None
                    if fut is not None:
                        try:
                            path = fut.result(timeout=90)
                        except Exception:
                            path = None
                    if gen == self._gen:
                        if path:
                            self._play(path, gen)
                        else:
                            self._say_builtin(sentence, gen)
                        if not self.q.empty() and gen == self._gen:
                            time.sleep(random.uniform(0.02, 0.09))      # a natural breath between sentences
                elif fut is not None:
                    fut.cancel()
            except Exception as e:
                self._warn("worker", f"Speech problem: {type(e).__name__}: {e}")
            finally:
                self._job_done()
                if self._pending == 0 and self._speaking:
                    self._speaking = False
                    self._spoke_at = time.monotonic()
                    self.cb("speaking_end")

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
    def _ensure_mic(self):
        """One microphone stream stays open for the whole session, so no word is ever missed between listens."""
        if self._mic is not None:
            return
        import sounddevice as sd
        dev = self.cfg.get("input_device")
        if isinstance(dev, str) and dev.strip().isdigit():
            dev = int(dev)
        dev = dev or None
        self._mq = queue.Queue(maxsize=600)

        def on_audio(indata, frames, t, status):
            try:
                self._mq.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        last = None
        for sr in (16000, None):                # 16 kHz if the device allows it, else its native rate
            try:
                rate = sr or int(sd.query_devices(dev, "input")["default_samplerate"])
                self._mic = sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=dev,
                                           blocksize=int(rate * 0.03), callback=on_audio)
                self._mic.start()
                self._mic_sr = rate
                return
            except Exception as e:
                last = e
                self._mic = None
        raise RuntimeError(f"cannot open the microphone ({last})")

    def _drain_mic(self):
        try:
            while True:
                self._mq.get_nowait()
        except queue.Empty:
            pass
        self._pre.clear()

    def preload(self):
        """Open the microphone and load the speech model now, so the first thing you say is not slow."""
        self._ensure_mic()
        self._load_whisper()

    def listen(self, max_wait=5.0):
        """Wait up to max_wait seconds for speech; return the transcript ('' if none)."""
        import numpy as np
        self._ensure_mic()
        now = time.monotonic()
        hush = self._spoke_at + 0.45 - now                  # never hear his own voice fading out of the speakers
        if hush > 0:
            time.sleep(hush)
        if self.is_speaking() or time.monotonic() - self._last_listen > 0.4 or self._spoke_at > self._last_listen:
            self._drain_mic()
        step = 0.03
        floor = float(self.cfg.get("silence_threshold", 0.012))
        end_sil = float(self.cfg.get("end_silence", 0.6))
        min_voiced = int(float(self.cfg.get("min_speech", 0.25)) / step)
        if self._noise is None:
            self._noise = floor / 3
        a_hp = 0.97                                         # high-pass at ~75 Hz: cuts rumble, fans, desk thumps
        px = py = 0.0
        frames, started, hot, voiced, silent, waited, total = [], False, 0, 0, 0.0, 0.0, 0.0
        try:
            while True:
                try:
                    raw = self._mq.get(timeout=0.5)
                except queue.Empty:
                    waited += 0.5
                    if (waited >= max_wait and not started) or (started and waited >= 2.0 + max_wait):
                        if not started:
                            return ""
                        break                                  # the stream stalled: use what we have
                    continue
                x = raw.tolist()
                y = []
                for v in x:                                  # one-pole high-pass filter, state carried across blocks
                    py = a_hp * (py + v - px)
                    px = v
                    y.append(py)
                block = np.asarray(y, dtype="float32")
                rms = float(np.sqrt(np.mean(block * block)))
                thresh = max(floor, self._noise * 2.8)
                self.cb("level", source="mic", value=min(1.0, rms / (thresh * 4)))
                if not started:
                    self._pre.append(block)
                    if rms > thresh:
                        hot += 1
                        if hot >= 2:                          # two loud blocks in a row = speech, not a click
                            started, frames, voiced = True, list(self._pre), hot
                            self._pre.clear()
                            self.cb("hearing")
                    else:
                        hot = 0
                        self._noise = min(floor * 4, 0.95 * self._noise + 0.05 * rms)   # learn the room's hum
                        waited += step
                        if waited >= max_wait:
                            return ""
                else:
                    frames.append(block)
                    total += step
                    if rms > thresh * 0.8:
                        voiced += 1
                        silent = 0.0
                    else:
                        silent += step
                    if silent >= end_sil or total >= 25:
                        break
        finally:
            self._last_listen = time.monotonic()
        if voiced < min_voiced:
            return ""
        keep = len(frames) - max(0, int((silent - 0.25) / step))      # trim the trailing silence
        audio = np.concatenate(frames[:max(1, keep)]).flatten()
        if self._mic_sr != 16000:
            n = int(len(audio) * 16000 / self._mic_sr)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")
        peak = float(np.abs(audio).max()) or 1e-4
        gain = min(30.0, 0.8 / peak)                          # quiet talkers get boosted for the recogniser
        if gain > 1.0:
            audio = audio * gain
        return self._transcribe(audio)

    def _load_whisper(self):
        with self._whisper_lock:
            if self._whisper is None:
                from faster_whisper import WhisperModel
                cuda = False
                try:
                    import ctranslate2
                    cuda = ctranslate2.get_cuda_device_count() > 0
                except Exception:
                    pass
                self._whisper = WhisperModel(self.cfg.get("stt_model", "small.en"), device="cuda" if cuda else "cpu",
                                             compute_type="float16" if cuda else "int8",
                                             cpu_threads=min(8, os.cpu_count() or 4))
        return self._whisper

    def _transcribe(self, audio):
        model = self._load_whisper()
        prompt = f"A conversation with a personal assistant named {self.name}." + (f" The user is {self.user}." if self.user else "")
        if self.vocab:
            prompt += " Names and terms that may come up: " + ", ".join(self.vocab[:25]) + "."
        segments, _ = model.transcribe(audio, language=self.cfg.get("stt_language", "en"),
                                       beam_size=int(self.cfg.get("stt_beam", 2)), vad_filter=True,
                                       vad_parameters={"min_silence_duration_ms": 350},
                                       condition_on_previous_text=False, temperature=0.0,
                                       no_speech_threshold=0.6, initial_prompt=prompt)
        parts = []
        for sg in segments:
            if getattr(sg, "no_speech_prob", 0.0) > 0.6 and getattr(sg, "avg_logprob", 0.0) < -0.8:
                continue                                      # the model itself says this is not speech
            if getattr(sg, "avg_logprob", 0.0) < -1.4:
                continue
            parts.append(sg.text)
        text = " ".join(parts).strip()
        return "" if text.lower().strip(" .!?,") in HALLUCINATIONS else text
