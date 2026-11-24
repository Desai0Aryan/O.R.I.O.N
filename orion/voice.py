"""Voice: speech-to-text (faster-whisper) and text-to-speech (edge-tts or pyttsx3)."""
import asyncio
import os
import tempfile


class Voice:
    def __init__(self, cfg):
        self.cfg = cfg["voice"]
        self._whisper = None
        self._engine = None

    # ---------- speaking ----------
    def say(self, text):
        if not text:
            return
        print(f"\n{self.cfg.get('name', 'Orion')}: {text}")
        try:
            if self.cfg.get("tts") == "edge":
                self._say_edge(text)
            else:
                self._say_pyttsx3(text)
        except Exception as e:
            print(f"[voice output failed: {e}]")

    def _say_edge(self, text):
        import edge_tts
        import pygame
        path = os.path.join(tempfile.gettempdir(), "orion_tts.mp3")

        async def synth():
            await edge_tts.Communicate(text, self.cfg["tts_voice"]).save(path)

        asyncio.run(synth())
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(50)
        pygame.mixer.music.unload()

    def _say_pyttsx3(self, text):
        import pyttsx3
        if self._engine is None:
            self._engine = pyttsx3.init()
        self._engine.say(text)
        self._engine.runAndWait()

    # ---------- listening ----------
    def listen(self, max_seconds=15, sr=16000):
        """Record one utterance (stops after silence) and return transcribed text or ''."""
        import numpy as np
        import sounddevice as sd
        thresh = self.cfg.get("silence_threshold", 0.015)
        block = int(sr * 0.1)
        frames, started, silent = [], False, 0.0
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32") as stream:
            for _ in range(int(max_seconds / 0.1)):
                data, _ = stream.read(block)
                loud = float(np.sqrt((data ** 2).mean())) > thresh
                if loud:
                    started, silent = True, 0.0
                    frames.append(data)
                elif started:
                    frames.append(data)
                    silent += 0.1
                    if silent >= 1.0:
                        break
        if not frames:
            return ""
        audio = np.concatenate(frames).flatten()
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(self.cfg.get("stt_model", "base.en"), compute_type="int8")
        segments, _ = self._whisper.transcribe(audio, language="en")
        return " ".join(s.text for s in segments).strip()
