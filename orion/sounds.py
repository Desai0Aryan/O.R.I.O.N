"""Orion's interface sounds, synthesised from scratch (no audio files): a boot sweep, a listening blip,
a thinking tick, a chime for reminders. Soft, short and quiet by default."""
import math
import os
import threading

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
NOTE = {"C5": 523.25, "E5": 659.25, "G5": 783.99, "B5": 987.77, "C6": 1046.5, "E6": 1318.5, "G6": 1568.0, "A4": 440.0}


def _env(n, attack=0.01, release=0.2, sr=44100):
    a, r = max(1, int(attack * sr)), max(1, int(release * sr))
    e = np.ones(n, np.float32)
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, min(r, n)) ** 2
    return e


def _tone(f0, dur, sr, f1=None, vol=1.0, harm=(1.0, 0.35, 0.12), attack=0.008, release=0.25):
    n = int(dur * sr)
    f = np.linspace(f0, f1 if f1 else f0, n)
    ph = np.cumsum(2 * math.pi * f / sr)
    y = sum(h * np.sin(ph * (i + 1)) for i, h in enumerate(harm))
    return (y / sum(harm) * _env(n, attack, release, sr) * vol).astype(np.float32)


def _echo(y, sr, delays=(0.13, 0.27), gains=(0.35, 0.18)):
    out = np.zeros(len(y) + int(max(delays) * sr) + 1, np.float32)
    out[:len(y)] += y
    for d, g in zip(delays, gains):
        o = int(d * sr)
        out[o:o + len(y)] += y * g
    return out


def render(name, sr=44100):
    """-> mono float32 samples in -1..1"""
    if name == "boot":
        n = int(1.3 * sr)
        sweep = _tone(160, 1.3, sr, 900, 0.5, (1, 0.5, 0.25), attack=0.4, release=0.5)
        shim = _tone(640, 1.3, sr, 1900, 0.18, (1, 0.2), attack=0.6, release=0.5)
        y = sweep[:n] + shim[:n]
        chime = np.zeros(int(1.0 * sr), np.float32)
        for i, nt in enumerate(("E5", "B5", "E6")):
            t = _tone(NOTE[nt], 0.6, sr, vol=0.5, release=0.5)
            o = int(i * 0.13 * sr)
            chime[o:o + len(t)] += t[:len(chime) - o]
        y = np.concatenate([y, _echo(chime, sr)])
    elif name == "wake":
        y = _echo(_tone(880, 0.09, sr, 1320, 0.7, release=0.06), sr, (0.07,), (0.25,))
    elif name == "think":
        t = _tone(330, 0.045, sr, 300, 0.55, release=0.03)
        y = np.concatenate([t, np.zeros(int(0.06 * sr), np.float32), t * 0.7])
    elif name == "done":
        y = _echo(_tone(1320, 0.11, sr, 880, 0.55, release=0.08), sr, (0.08,), (0.22,))
    elif name == "alert":
        seq = np.zeros(int(1.9 * sr), np.float32)
        for rep in range(2):
            for i, nt in enumerate(("C6", "E6", "G6")):
                t = _tone(NOTE[nt], 0.5, sr, vol=0.55, release=0.4)
                o = int((rep * 0.85 + i * 0.14) * sr)
                seq[o:o + len(t)] += t[:len(seq) - o]
        y = _echo(seq, sr)
    elif name == "error":
        y = _tone(196, 0.28, sr, 150, 0.6, (1, 0.6, 0.4), release=0.2)
    else:
        raise KeyError(name)
    peak = float(np.abs(y).max()) or 1.0
    return (y / max(1.0, peak * 1.05)).astype(np.float32)


class Sounds:
    def __init__(self, enabled=True, volume=0.35):
        self.enabled = bool(enabled)
        self.volume = max(0.0, min(1.0, float(volume)))
        self._cache = {}
        self._lock = threading.Lock()

    def play(self, name):
        if not self.enabled or self.volume <= 0:
            return
        threading.Thread(target=self._play, args=(name,), daemon=True).start()

    def _play(self, name):
        try:
            import pygame
            with self._lock:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                sr, _fmt, ch = pygame.mixer.get_init()
                snd = self._cache.get((name, sr, ch))
                if snd is None:
                    y = (np.clip(render(name, sr), -1, 1) * 32767).astype(np.int16)
                    if ch > 1:
                        y = np.repeat(y[:, None], ch, 1)
                    snd = pygame.mixer.Sound(buffer=np.ascontiguousarray(y).tobytes())
                    self._cache[(name, sr, ch)] = snd
            snd.set_volume(self.volume)
            snd.play()
        except Exception:
            self.enabled = False                 # no audio device: quietly stay silent
