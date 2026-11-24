"""Orion's long-term memory (SQLite in ./data). Thread-safe and self-migrating."""
import json
import sqlite3
import threading
import time
from pathlib import Path

from .retrieval import tokens, top_k

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Memory:
    def __init__(self, path=None):
        path = Path(path) if path else DATA / "orion_memory.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        old = ROOT / "orion_memory.db"              # migrate the very first location
        if path == DATA / "orion_memory.db" and old.exists() and not path.exists():
            old.replace(path)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.session = int(time.time())
        self._schema()
        self.prev_seen = float(self.get("last_seen", "0") or 0)
        if not self.get("first_seen"):
            self.set("first_seen", str(time.time()))

    # ---------- plumbing ----------
    def _x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def _cols(self, table, cols):
        have = {r[1] for r in self._q(f"PRAGMA table_info({table})")}
        for name, ddl in cols.items():
            if name not in have:
                self._x(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _schema(self):
        for sql in (
            "CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, fact TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)",
            "CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY, kind TEXT, text TEXT UNIQUE, ts REAL)",
            "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, topic TEXT, text TEXT, source TEXT, ts REAL)",
            "CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY, role TEXT, text TEXT, ts REAL)",
            "CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, ts REAL, summary TEXT, topics TEXT)",
            "CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, ts REAL, entry TEXT)",
        ):
            self._x(sql)
        # migrations from earlier versions
        self._cols("facts", {"category": "TEXT DEFAULT 'general'", "importance": "INTEGER DEFAULT 3",
                             "created": "REAL DEFAULT 0", "last_used": "REAL DEFAULT 0",
                             "uses": "INTEGER DEFAULT 0"})
        self._cols("lessons", {"weight": "INTEGER DEFAULT 1"})
        self._cols("log", {"session": "INTEGER DEFAULT 0"})

    # ---------- key/value ----------
    def get(self, k, default=""):
        rows = self._q("SELECT v FROM kv WHERE k=?", (k,))
        return rows[0][0] if rows else default

    def set(self, k, v):
        self._x("INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)", (k, str(v)))

    def jget(self, k, default=None):
        try:
            return json.loads(self.get(k, "")) if self.get(k, "") else default
        except json.JSONDecodeError:
            return default

    def jset(self, k, obj):
        self.set(k, json.dumps(obj, ensure_ascii=False))

    def incr(self, k, n=1):
        v = int(float(self.get(k, "0") or 0)) + n
        self.set(k, v)
        return v

    # ---------- facts about the user ----------
    def _near_dup(self, fact):
        ft = set(tokens(fact))
        if not ft:
            return None
        for fid, text in self._q("SELECT id, fact FROM facts"):
            ot = set(tokens(text))
            if ot and len(ft & ot) / len(ft | ot) >= 0.75:
                return fid, text
        return None

    def remember(self, fact, category="general", importance=3):
        fact = (fact or "").strip()
        if not fact:
            return
        try:
            importance = max(1, min(5, int(importance)))
        except (TypeError, ValueError):
            importance = 3
        dup = self._near_dup(fact)
        if dup:
            fid, old = dup
            newer = fact if len(fact) >= len(old) else old
            try:
                self._x("UPDATE facts SET fact=?, importance=MAX(importance, ?) WHERE id=?",
                        (newer, importance, fid))
            except sqlite3.IntegrityError:
                self._x("UPDATE facts SET importance=MAX(importance, ?) WHERE id=?", (importance, fid))
            return
        self._x("INSERT OR IGNORE INTO facts(fact, category, importance, created) VALUES (?,?,?,?)",
                (fact, (category or "general")[:20], importance, time.time()))

    def forget(self, fragment):
        self._x("DELETE FROM facts WHERE fact LIKE ?", (f"%{fragment}%",))

    def fact_rows(self):
        rows = self._q("SELECT id, fact, category, importance, created, uses FROM facts ORDER BY id DESC")
        return [dict(id=r[0], fact=r[1], category=r[2], importance=r[3], created=r[4], uses=r[5])
                for r in rows]

    def facts(self, limit=60):
        return [r["fact"] for r in self.fact_rows()[:limit]]

    def count_facts(self):
        return self._q("SELECT COUNT(*) FROM facts")[0][0]

    def replace_facts(self, items):
        """items: list of str or dict(text, category, importance)."""
        old = {r["fact"]: r for r in self.fact_rows()}
        with self.lock:
            self.db.execute("DELETE FROM facts")
            self.db.commit()
        for it in items:
            if isinstance(it, str):
                self.remember(it)
            elif isinstance(it, dict):
                self.remember(it.get("text", ""), it.get("category", "general"), it.get("importance", 3))
        return old

    # ---------- lessons ----------
    def add_lesson(self, kind, text):
        text = (text or "").strip()
        if not text:
            return
        with self.lock:
            cur = self.db.execute("UPDATE lessons SET weight=weight+1, ts=? WHERE text=?", (time.time(), text))
            if cur.rowcount == 0:
                self.db.execute("INSERT INTO lessons(kind, text, ts, weight) VALUES (?,?,?,1)",
                                (kind or "lesson", text, time.time()))
            self.db.commit()

    def lesson_rows(self):
        return [dict(text=r[0], weight=r[1]) for r in
                self._q("SELECT text, weight FROM lessons ORDER BY weight DESC, id DESC")]

    def lessons(self, limit=25):
        return [r["text"] for r in self.lesson_rows()[:limit]]

    # ---------- notes (knowledge from the world) ----------
    def add_note(self, topic, text, source=""):
        self._x("INSERT INTO notes(topic, text, source, ts) VALUES (?,?,?,?)",
                ((topic or "").strip(), (text or "").strip(), source, time.time()))

    def note_rows(self):
        return [(r[0], r[1], r[2]) for r in self._q("SELECT topic, text, source FROM notes ORDER BY id DESC")]

    # ---------- conversation log ----------
    def log(self, role, text):
        self._x("INSERT INTO log(role, text, ts, session) VALUES (?,?,?,?)",
                (role, text, time.time(), self.session))
        self.set("last_seen", f"{time.time():.0f}")

    def log_since(self, last_id):
        return self._q("SELECT id, role, text FROM log WHERE id > ? ORDER BY id", (last_id,))

    def session_rows(self):
        return self._q("SELECT role, text FROM log WHERE session=? ORDER BY id", (self.session,))

    # ---------- episodes and journal ----------
    def add_episode(self, summary, topics=()):
        self._x("INSERT INTO episodes(ts, summary, topics) VALUES (?,?,?)",
                (time.time(), summary.strip(), ", ".join(topics)))

    def episode_rows(self):
        return self._q("SELECT ts, summary, topics FROM episodes ORDER BY id DESC")

    def add_journal(self, entry):
        self._x("INSERT INTO journal(ts, entry) VALUES (?,?)", (time.time(), entry.strip()))

    def journal_rows(self, limit=5):
        return self._q("SELECT ts, entry FROM journal ORDER BY id DESC LIMIT ?", (limit,))

    # ---------- retrieval: what is relevant right now ----------
    def retrieve(self, query, k_facts=8, k_notes=4, k_eps=3, k_lessons=6):
        facts = self.fact_rows()
        chosen, seen = [], set()

        def take(row):
            if row["id"] not in seen:
                seen.add(row["id"])
                chosen.append(row)

        for r in sorted([f for f in facts if f["importance"] >= 4],
                        key=lambda f: (-f["importance"], -f["id"]))[:12]:
            take(r)
        for i in top_k([f["fact"] for f in facts], query, k_facts):
            take(facts[i])
        for r in facts[:max(0, 6 - len(chosen))]:     # a few recent ones if memory is thin
            take(r)
        if chosen:
            ids = ",".join(str(r["id"]) for r in chosen)
            self._x(f"UPDATE facts SET uses=uses+1, last_used=? WHERE id IN ({ids})", (time.time(),))

        lrows = self.lesson_rows()
        lessons = [r["text"] for r in lrows[:k_lessons]]
        for i in top_k([r["text"] for r in lrows], query, 3):
            if lrows[i]["text"] not in lessons:
                lessons.append(lrows[i]["text"])

        notes = self.note_rows()
        nsel = [notes[i] for i in top_k([f"{t} {x}" for t, x, _ in notes], query, k_notes)]

        eps = self.episode_rows()
        esel = [eps[i][1] for i in top_k([e[1] + " " + e[2] for e in eps], query, k_eps)]
        return {"facts": [r["fact"] for r in chosen], "lessons": lessons, "notes": nsel, "episodes": esel}

    # ---------- relationship stats ----------
    def bond_info(self):
        first = float(self.get("first_seen", str(time.time())) or time.time())
        return {"turns": int(float(self.get("turns_total", "0") or 0)),
                "days": int((time.time() - first) // 86400)}

    def stats(self):
        b = self.bond_info()
        return {"facts": self.count_facts(), "lessons": len(self.lesson_rows()),
                "notes": len(self.note_rows()), "episodes": len(self.episode_rows()), **b}
