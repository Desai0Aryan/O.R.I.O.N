"""Lightweight relevance search (BM25) so Orion recalls what matters, not just what's recent."""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9']+")
STOP = set("""a an the and or but if then of to in on at for with about as by from is are was were be
been am it its this that these those i you he she we they me my your our their do does did have has
had not no so than too very can will just what when where which who how why would could should
there here into out up down over again also really""".split())


def _stem(t):
    t = t.strip("'")
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if len(t) > 3 and t.endswith("e"):
        t = t[:-1]
    return t


def tokens(text):
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


def top_k(docs, query, k, min_score=0.0):
    """Indices of the k docs most relevant to the query (BM25), best first."""
    q = set(tokens(query))
    if not q or not docs:
        return []
    toks = [tokens(d) for d in docs]
    n = len(docs)
    avg = (sum(len(t) for t in toks) / n) or 1.0
    df = Counter()
    for t in toks:
        df.update(set(t))
    scored = []
    for i, t in enumerate(toks):
        tf = Counter(t)
        length = len(t)
        s = 0.0
        for w in q:
            f = tf.get(w, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * length / avg))
        if s > min_score:
            scored.append((s, i))
    scored.sort(reverse=True)
    return [i for _, i in scored[:k]]
