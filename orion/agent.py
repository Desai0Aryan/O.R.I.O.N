"""The agent loop: think -> speak -> act -> observe -> repeat. Plus learning."""
import datetime
import json
import re

from .brain import Brain
from .memory import Memory
from .personality import build_system_prompt

MAX_STEPS = 6

CURATOR = """You maintain a personal assistant's long-term memory. Read the conversation
and return ONE JSON object: {"facts": [...], "lessons": [...]}
- facts: lasting, specific things learned about the USER (preferences, people, projects,
  routines, goals, opinions). Short sentences.
- lessons: how the assistant should behave better with this user (corrections, tone or
  format preferences, mistakes to avoid), written as instructions to the assistant.
Only include things clearly stated or demonstrated. Do not repeat known facts. Empty lists are fine.
KNOWN FACTS: KNOWN_HERE
"""

STOPWORDS = {"what", "when", "where", "which", "about", "would", "could", "should", "there",
             "their", "have", "with", "that", "this", "from", "your", "tell", "please"}


def parse_reply(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"speech": raw.strip(), "actions": []}


class Agent:
    def __init__(self, cfg, speak, confirm):
        self.cfg = cfg
        self.learning = cfg.get("learning", {})
        self.speak = speak          # speak(text)
        self.confirm = confirm      # confirm(question) -> bool
        self.brain = Brain(cfg)
        self.memory = Memory()
        self.history = []
        self.turns = 0
        self.tools = {}             # name -> (function, doc)
        self._register_builtin()
        try:                        # later parts drop tools into orion/tools/
            from .tools import load_all
            load_all(self)
        except ImportError:
            pass
        self.consolidate()

    # ---------- tools ----------
    def register(self, name, fn, doc):
        self.tools[name] = (fn, doc)

    def _register_builtin(self):
        self.register("remember", lambda fact: (self.memory.remember(fact), "saved")[1],
                      "remember(fact: str) - save a lasting fact about the user")
        self.register("forget", lambda fragment: (self.memory.forget(fragment), "forgotten")[1],
                      "forget(fragment: str) - delete saved facts containing this text")
        self.register("learn", lambda text, kind="lesson": (self.memory.add_lesson(kind, text), "learned")[1],
                      "learn(text: str, kind: str='lesson') - record a correction or preference about how to work with the user")
        self.register("save_note",
                      lambda topic, text, source="": (self.memory.add_note(topic, text, source), "noted")[1],
                      "save_note(topic: str, text: str, source: str='') - store knowledge learned from the world")
        self.register("get_time", lambda: datetime.datetime.now().strftime("%A %B %d %Y, %I:%M %p"),
                      "get_time() - current local date and time")

    def _run_tool(self, action):
        name, args = action.get("tool"), action.get("args", {}) or {}
        if name not in self.tools:
            return {"tool": name, "error": "unknown tool"}
        try:
            return {"tool": name, "result": self.tools[name][0](**args)}
        except Exception as e:
            return {"tool": name, "error": f"{type(e).__name__}: {e}"}

    # ---------- prompt ----------
    def _system(self, user_text=""):
        docs = "\n".join(f"  - {d}" for _, d in self.tools.values())
        words = [w for w in re.findall(r"[a-zA-Z]{4,}", user_text.lower()) if w not in STOPWORDS][:6]
        return build_system_prompt(
            self.cfg, docs, self.memory.facts(), self.memory.get("mood", "calm and curious"),
            self.memory.lessons(), self.memory.search_notes(words))

    def _window(self):
        msgs = self.history[-30:]
        while msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        return msgs

    # ---------- conversation ----------
    def handle(self, user_text):
        self.memory.log("user", user_text)
        self.history.append({"role": "user", "content": user_text})
        for _ in range(MAX_STEPS):
            raw = self.brain.chat(self._system(user_text), self._window())
            self.history.append({"role": "assistant", "content": raw})
            data = parse_reply(raw)
            if data.get("mood"):
                self.memory.set("mood", str(data["mood"])[:60])
            if data.get("speech"):
                self.memory.log("assistant", str(data["speech"]))
                self.speak(data["speech"])
            actions = data.get("actions") or []
            if not actions:
                break
            results = [self._run_tool(a) for a in actions]
            self.history.append({"role": "user",
                                 "content": "TOOL_RESULTS: " + json.dumps(results, default=str)[:6000]})
        else:
            self.speak("I went around in circles on that one. Want to rephrase it?")
        self.turns += 1
        every = int(self.learning.get("reflect_every", 8))
        if every and self.turns % every == 0:
            self.reflect()

    # ---------- growth ----------
    def reflect(self):
        """Review new conversation and keep what is worth remembering."""
        last = int(self.memory.get("last_reflected", "0") or 0)
        rows = self.memory.log_since(last)
        if len(rows) < 2:
            return
        transcript = "\n".join(f"{r[1].upper()}: {r[2]}" for r in rows)[-6000:]
        prompt = (CURATOR.replace("KNOWN_HERE", "; ".join(self.memory.facts(60)) or "none")
                  + "\nCONVERSATION:\n" + transcript)
        try:
            raw = self.brain.chat("You are a careful memory curator. Reply with JSON only.",
                                  [{"role": "user", "content": prompt}])
        except Exception:
            return          # try again next time; nothing is lost, the log is kept
        data = parse_reply(raw)
        for f in data.get("facts") or []:
            if isinstance(f, str) and f.strip():
                self.memory.remember(f)
        for l in data.get("lessons") or []:
            if isinstance(l, str) and l.strip():
                self.memory.add_lesson("lesson", l)
        self.memory.set("last_reflected", str(rows[-1][0]))

    def consolidate(self):
        """Keep memory tidy: merge facts when there are too many."""
        limit = int(self.learning.get("consolidate_above", 120))
        if self.memory.count_facts() <= limit:
            return
        facts = self.memory.facts(500)
        prompt = ('Merge and tidy these facts about one person into at most 60 short, non-duplicate '
                  'facts, keeping everything important. Reply JSON only: {"facts": [...]}\n'
                  + "\n".join(facts))
        try:
            data = parse_reply(self.brain.chat("You are a careful memory curator.",
                                               [{"role": "user", "content": prompt}]))
            merged = [f for f in data.get("facts", []) if isinstance(f, str)]
            if len(merged) >= 10:
                self.memory.replace_facts(merged)
        except Exception:
            pass
