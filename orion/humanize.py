"""Turns text into something that sounds spoken, and picks prosody for each emotion."""
import random
import re

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`([^`]*)`")
_BOLD = re.compile(r"(\*\*|__)(.*?)\1")
_ITAL = re.compile(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)")
_HEAD = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*[-*•]\s+", re.M)
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")

_SPOKEN = [("e.g.", "for example"), ("i.e.", "that is"), (" vs. ", " versus "), (" vs ", " versus "),
           ("&", " and "), ("%", " percent"), (" — ", ", "), ("—", ", "), ("–", " to "),
           (" w/ ", " with ")]


def clean_for_speech(text):
    t = text or ""
    t = _FENCE.sub(" I've put the code in the chat. ", t)
    t = _URL.sub("the link", t)
    t = _INLINE.sub(r"\1", t)
    t = _BOLD.sub(r"\2", t)
    t = _ITAL.sub(r"\1", t)
    t = _HEAD.sub("", t)
    t = _BULLET.sub("", t)
    t = _EMOJI.sub("", t)
    for a, b in _SPOKEN:
        t = t.replace(a, b)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([,.!?;:])", r"\1", t)


def split_sentences(text, max_len=220):
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    merged = []
    for p in parts:
        if merged and len(merged[-1]) < 28:
            merged[-1] += " " + p
        else:
            merged.append(p)
    out = []
    for p in merged:
        while len(p) > max_len:
            cut = max(p.rfind(", ", 0, max_len), p.rfind("; ", 0, max_len))
            if cut < 40:
                cut = p.rfind(" ", 0, max_len)
            if cut <= 0:
                cut = max_len
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out


FILLERS = {"thoughtful": ["Hmm. ", "Well, "], "curious": ["Ooh, ", "Hm, "], "amused": ["Ha. ", "Heh, "],
           "playful": ["Ha, "], "empathetic": ["Oh, "], "concerned": ["Oh no, "], "excited": ["Oh! "]}
_STARTS = re.compile(r"^(hm+|well|oh|ha|heh|ooh|so|okay|ok|yeah|sure|yes|no)\b", re.I)


def maybe_filler(sentence, emotion, enabled=True, p=0.15):
    if not enabled or not sentence or emotion not in FILLERS or random.random() > p or _STARTS.match(sentence):
        return sentence
    f = random.choice(FILLERS[emotion])
    if f.endswith(", ") and sentence[:2] not in ("I ", "I'") and sentence[0].isupper():
        sentence = sentence[0].lower() + sentence[1:]
    return f + sentence


# emotion: (rate %, pitch Hz, volume %)
PROSODY = {"neutral": (0, 0, 0), "calm": (-6, -2, -3), "happy": (4, 3, 3), "excited": (9, 5, 6),
           "curious": (2, 3, 0), "thoughtful": (-8, -2, -4), "amused": (3, 2, 2), "playful": (5, 3, 3),
           "empathetic": (-7, -1, -4), "concerned": (-3, 1, -2), "apologetic": (-6, -2, -5),
           "proud": (1, 2, 3), "tired": (-12, -4, -6)}


def edge_prosody(emotion, expressive=True):
    r, p, v = PROSODY.get(emotion, (0, 0, 0)) if expressive else (0, 0, 0)
    return {"rate": f"{r:+d}%", "pitch": f"{p:+d}Hz", "volume": f"{v:+d}%"}


_ELEVEN = {"excited": (0.30, 0.55), "happy": (0.38, 0.45), "playful": (0.35, 0.50), "amused": (0.38, 0.45),
           "curious": (0.42, 0.35), "thoughtful": (0.60, 0.15), "calm": (0.65, 0.10),
           "empathetic": (0.55, 0.25), "concerned": (0.50, 0.25), "apologetic": (0.55, 0.20),
           "tired": (0.70, 0.05), "proud": (0.40, 0.40)}


def eleven_settings(emotion, expressive=True):
    stab, style = _ELEVEN.get(emotion, (0.50, 0.25)) if expressive else (0.50, 0.25)
    return {"stability": stab, "similarity_boost": 0.8, "style": style, "use_speaker_boost": True}
