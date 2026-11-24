"""Finding his name in a speech transcript, even when the recogniser spells it oddly."""
import re
from difflib import SequenceMatcher

# how speech recognisers tend to write "Orion", "Oh-ee-on" and friends
TARGETS = ["orion", "oreon", "oeon", "oheeon", "oreeon", "oryon", "orrion", "ohrion"]
_NOT = {"oreo", "orient", "origin", "oregon", "organ", "ohio", "only", "open", "over", "oneon", "ohone", "orson"}
_TOKEN = re.compile(r"[A-Za-z']+")
_LEAD = re.compile(r"^(?:hey|hi|hello|ok|okay|yo)?[\s,.!?:;-]*", re.I)


def _norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


def _score(joined):
    return max(SequenceMatcher(None, joined, t).ratio() for t in TARGETS)


def find_wake(text, aliases=(), threshold=0.78):
    """Return (start, end) character span of the name in text, or None."""
    toks = [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    al = {_norm(a) for a in aliases if _norm(a)}
    best = None                                           # (score, words, span)
    for n in (1, 2, 3):                                   # "orion", "o e on", "oh ee on"
        for i in range(len(toks) - n + 1):
            grp = toks[i:i + n]
            joined = _norm("".join(t[0] for t in grp))
            if n > 1 and any(len(_norm(t[0])) > 4 for t in grp):
                continue
            if joined in al and n == 1:
                sc = 1.0
            elif len(joined) >= 4 and joined[0] == "o" and joined not in _NOT:
                sc = _score(joined)
                if sc < threshold:
                    continue
            else:
                continue
            if best is None or (sc, n) > (best[0], best[1]):
                best = (sc, n, (grp[0][1], grp[-1][2]))
    return best[2] if best else None


def strip_wake(text, span):
    """Remove the name (and a greeting before it) from the transcript."""
    s, e = span
    head, tail = text[:s], text[e:]
    head = re.sub(r"(?:\b(?:hey|hi|hello|ok|okay|yo)\b[\s,.!?:;-]*)$", "", head, flags=re.I)
    out = (head + " " + tail).strip()
    return re.sub(r"^[\s,.!?:;-]+", "", out).strip()
