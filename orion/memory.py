"""Long-term memory in SQLite. Lives in ./data so it survives restarts and updates."""
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Memory:
    def __init__(self, path=None):
        DATA.mkdir(exist_ok=True)
        path = Path(path) if path else DATA / "orion_memory.db"
        old = ROOT / "orion_memory.db"          # migrate the Part 1 location
        if old.exists() and not path.exists():
            old.replace(path)
        self.db = sqlite3.connect(path)
        for sql in (
            "CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, fact TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)",
            "CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY, kind TEXT, text TEXT UNIQUE, ts REAL)",
            "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, topic TEXT, text TEXT, source TEXT, ts REAL)",
            "CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY, role TEXT, text TEXT, ts REAL)",
        ):
            self.db.execute(sql)
        self.db.commit()

    # ----- facts about the user -----
    def remember(self, fact):
        self.db.execute("INSERT OR IGNORE INTO facts(fact) VALUES (?)", (fact.strip(),))
        self.db.commit()

    def forget(self, fragment):
        self.db.execute("DELETE FROM facts WHERE fact LIKE ?", (f"%{fragment}%",))
        self.db.commit()

    def facts(self, limit=60):
        rows = self.db.execute("SELECT fact FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in rows]

    def count_facts(self):
        return self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def replace_facts(self, facts):
        self.db.execute("DELETE FROM facts")
        self.db.executemany("INSERT OR IGNORE INTO facts(fact) VALUES (?)",
                            [(f.strip(),) for f in facts if f.strip()])
        self.db.commit()

    # ----- lessons: how to behave better with this user -----
    def add_lesson(self, kind, text):
        self.db.execute("INSERT OR IGNORE INTO lessons(kind, text, ts) VALUES (?,?,?)",
                        (kind, text.strip(), time.time()))
        self.db.commit()

    def lessons(self, limit=25):
        rows = self.db.execute("SELECT text FROM lessons ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in rows]

    # ----- notes: things learned from the world (internet, files, research) -----
    def add_note(self, topic, text, source=""):
        self.db.execute("INSERT INTO notes(topic, text, source, ts) VALUES (?,?,?,?)",
                        (topic.strip(), text.strip(), source, time.time()))
        self.db.commit()

    def search_notes(self, words, limit=5):
        if not words:
            return []
        clause = " OR ".join(["topic LIKE ? OR text LIKE ?"] * len(words))
        args = [x for w in words for x in (f"%{w}%", f"%{w}%")]
        rows = self.db.execute(
            f"SELECT topic, text, source FROM notes WHERE {clause} ORDER BY id DESC LIMIT ?",
            args + [limit]).fetchall()
        return rows

    # ----- conversation log -----
    def log(self, role, text):
        self.db.execute("INSERT INTO log(role, text, ts) VALUES (?,?,?)", (role, text, time.time()))
        self.db.commit()

    def log_since(self, last_id):
        return self.db.execute("SELECT id, role, text FROM log WHERE id > ? ORDER BY id",
                               (last_id,)).fetchall()

    # ----- misc key/value (mood, bookmarks) -----
    def get(self, k, default=""):
        row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row[0] if row else default

    def set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)", (k, v))
        self.db.commit()
