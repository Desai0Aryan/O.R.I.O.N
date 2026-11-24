"""Orion's emotional state: a valence/energy pair that reacts, drifts and decays over time."""
import time
from datetime import datetime

# emotion: (valence -1..1, energy 0..1, UI colour)
EMOTIONS = {
    "neutral":    (0.15, 0.40, "#6ea8ff"),
    "calm":       (0.25, 0.20, "#5fd1c4"),
    "happy":      (0.70, 0.60, "#ffd36e"),
    "excited":    (0.85, 0.90, "#ff9d5c"),
    "curious":    (0.45, 0.60, "#8f8bff"),
    "thoughtful": (0.10, 0.30, "#7b9bff"),
    "amused":     (0.60, 0.60, "#ffb36e"),
    "playful":    (0.70, 0.75, "#ff8fd0"),
    "empathetic": (0.20, 0.30, "#9fb8ff"),
    "concerned":  (-0.30, 0.50, "#c39bff"),
    "apologetic": (-0.20, 0.30, "#a0b0c8"),
    "proud":      (0.75, 0.50, "#ffd88a"),
    "tired":      (-0.10, 0.10, "#8090a8"),
}


def nearest_emotion(v, e):
    return min(EMOTIONS, key=lambda k: (EMOTIONS[k][0] - v) ** 2 + (EMOTIONS[k][1] - e) ** 2)


def part_of_day(dt=None):
    h = (dt or datetime.now()).hour
    if h < 5:
        return "late night"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    if h < 22:
        return "evening"
    return "night"


def humanize_gap(seconds):
    if seconds < 90:
        return "just a moment ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        h = int(seconds // 3600)
        return f"about {h} hour{'s' if h != 1 else ''} ago"
    d = int(seconds // 86400)
    if d == 1:
        return "yesterday"
    if d < 14:
        return f"{d} days ago"
    return f"about {d // 7} weeks ago"


class Mood:
    """Mood moves toward whatever Orion expresses, then relaxes toward a time-of-day baseline."""
    HALF_LIFE = 1200.0   # seconds for a mood to fade halfway back to baseline

    def __init__(self, memory):
        self.mem = memory
        self.v = float(memory.get("mood_v", "0.3") or 0.3)
        self.e = float(memory.get("mood_e", "0.4") or 0.4)
        self.t = float(memory.get("mood_t", "0") or 0) or time.time()
        self._decay()

    @staticmethod
    def _baseline():
        h = datetime.now().hour
        return 0.3, (0.2 if (h < 7 or h >= 23) else 0.45)

    def _decay(self):
        now = time.time()
        k = 0.5 ** (max(0.0, now - self.t) / self.HALF_LIFE)
        bv, be = self._baseline()
        self.v = bv + (self.v - bv) * k
        self.e = be + (self.e - be) * k
        self.t = now

    def nudge(self, emotion, strength=0.6):
        if emotion not in EMOTIONS:
            return
        self._decay()
        tv, te, _ = EMOTIONS[emotion]
        self.v += (tv - self.v) * strength
        self.e += (te - self.e) * strength
        self.mem.set("mood_v", f"{self.v:.3f}")
        self.mem.set("mood_e", f"{self.e:.3f}")
        self.mem.set("mood_t", f"{self.t:.0f}")

    def emotion(self):
        self._decay()
        return nearest_emotion(self.v, self.e)

    def energy_word(self):
        return "low" if self.e < 0.28 else "high" if self.e > 0.65 else "moderate"
