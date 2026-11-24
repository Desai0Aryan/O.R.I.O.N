"""The agent: thinks, speaks, acts, remembers, reflects and grows."""
import datetime
import json
import re
import threading
import time

from .brain import Brain, BrainError
from .memory import Memory
from .mood import EMOTIONS, Mood, humanize_gap, part_of_day
from .personality import (BASELINE_TRAITS, DEFAULT_PROFILE, LIST_KEYS, build_system_prompt)

MAX_STEPS = 6
HISTORY_LIMIT = 36          # messages kept verbatim before older ones are summarised

CURATOR_SYS = "You are a careful, honest memory curator for a personal assistant. Reply with JSON only."
CURATOR = """Read the conversation and return ONE JSON object:
{"facts": [{"text": "...", "category": "...", "importance": 1-5}],
 "lessons": ["..."],
 "trait_nudges": {"warmth": 0.0, "humor": 0.0, "directness": 0.0, "formality": 0.0, "curiosity": 0.0}}
- facts: lasting, specific things learned about the USER (people, projects, routines, tastes, goals, opinions).
  category: identity | work | people | preference | goal | routine | interest | other.
  importance: 5 = core identity (name, family, job), 4 = strong preference or goal, 3 = normal, 1-2 = minor.
- lessons: how the assistant should behave better with this user (corrections, tone or format preferences,
  mistakes to avoid), written as instructions to the assistant.
- trait_nudges: between -0.05 and 0.05, ONLY if the conversation clearly shows what this user responds well
  or badly to (e.g. they laughed at jokes: humor +0.03; they asked for shorter answers: directness +0.03). Else {}.
Only include what was clearly stated or demonstrated. Do not repeat known facts. Empty lists are fine.
KNOWN FACTS: KNOWN_HERE
"""

PROFILE_PROMPT = """Below is a profile of a person built from conversations with their assistant, followed by
a new conversation. Return the UPDATED profile as one JSON object in exactly the same schema. Change only what
the evidence supports. communication scores are 0-10 (formality, verbosity, humor, directness, energy);
notes is one short sentence about how they talk. Describe observable communication style and what they have
said about their interests, values, goals and routines. Do NOT diagnose, and do not speculate about health,
mental state or private matters. Keep lists short (max 12 items each).
CURRENT PROFILE: PROFILE_HERE
"""

TOOL_DOCS = [
    "remember(fact: str, category: str='general', importance: int=3) - save a lasting fact about the user (importance 1-5)",
    "recall(query: str) - search your memory for what you know about a topic",
    "forget(fragment: str) - delete saved facts containing this text",
    "learn(text: str, kind: str='lesson') - record a correction or preference about how to work with the user",
    "save_note(topic: str, text: str, source: str='') - store knowledge learned from the world",
    "get_time() - current local date and time",
]


def extract_json(raw):
    s = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    start = s.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = s[start:i + 1]
                for attempt in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
                    try:
                        return json.loads(attempt)
                    except json.JSONDecodeError:
                        pass
                return None
    return None


def parse_reply(raw):
    d = extract_json(raw)
    if isinstance(d, dict):
        return d
    m = re.search(r'"speech"\s*:\s*"((?:[^"\\]|\\.)*)', raw or "")      # salvage a truncated reply
    if m:
        try:
            return {"speech": json.loads('"' + m.group(1) + '"')}
        except json.JSONDecodeError:
            return {"speech": m.group(1)}
    plain = (raw or "").strip()
    return {"speech": "" if plain.startswith("{") else plain}


def normalize(d):
    emo = str(d.get("emotion", "neutral")).lower().strip()
    acts = [a for a in (d.get("actions") or []) if isinstance(a, dict) and a.get("tool")]
    return {"thought": str(d.get("thought") or ""), "speech": str(d.get("speech") or "").strip(),
            "display": str(d.get("display") or "").strip(), "emotion": emo if emo in EMOTIONS else "neutral",
            "mood": str(d.get("mood") or "")[:60], "actions": acts}


def merge_profile(old, new):
    out = json.loads(json.dumps(old or DEFAULT_PROFILE))
    if not isinstance(new, dict):
        return out
    comm = out.setdefault("communication", {})
    for k, v in (new.get("communication") or {}).items():
        if k == "notes":
            if isinstance(v, str) and v.strip():
                comm["notes"] = v.strip()[:400]
        elif isinstance(v, (int, float)):
            v = max(0.0, min(10.0, float(v)))
            o = comm.get(k)
            comm[k] = round(o * 0.6 + v * 0.4, 1) if isinstance(o, (int, float)) else round(v, 1)
    for k in LIST_KEYS:
        items = new.get(k)
        if isinstance(items, list):
            cur = out.setdefault(k, [])
            have = {c.lower() for c in cur}
            for it in items:
                if isinstance(it, str) and it.strip() and it.strip().lower() not in have:
                    cur.append(it.strip())
                    have.add(it.strip().lower())
            out[k] = cur[-12:]
    for k in ("humor_style", "how_they_like_to_be_helped"):
        if isinstance(new.get(k), str) and new[k].strip():
            out[k] = new[k].strip()[:300]
    return out


class Agent:
    def __init__(self, cfg, memory, on_reply, confirm):
        self.cfg = cfg
        self.pcfg = cfg.get("personality", {})
        self.lcfg = cfg.get("learning", {})
        self.mem = memory
        self.on_reply = on_reply            # on_reply(reply_dict)
        self.confirm = confirm              # confirm(question) -> bool
        self.brain = Brain(cfg)
        self.mood = Mood(memory)
        self.history = []
        self.summary = ""
        self.tools = {}
        self._turns_since = 0
        self._rlock = threading.Lock()
        self._register_builtin()
        try:                                # later parts drop tools into orion/tools/
            from .tools import load_all
            load_all(self)
        except ImportError:
            pass

    # ---------- tools ----------
    def register(self, name, fn, doc):
        self.tools[name] = (fn, doc)

    def _register_builtin(self):
        m = self.mem

        def recall(query):
            r = m.retrieve(query)
            return {"facts": r["facts"][:8], "episodes": r["episodes"], "notes": [f"{t}: {x}" for t, x, _ in r["notes"]]}

        self.register("remember", lambda fact, category="general", importance=3:
                      (m.remember(fact, category, importance), "saved")[1], TOOL_DOCS[0])
        self.register("recall", recall, TOOL_DOCS[1])
        self.register("forget", lambda fragment: (m.forget(fragment), "forgotten")[1], TOOL_DOCS[2])
        self.register("learn", lambda text, kind="lesson": (m.add_lesson(kind, text), "learned")[1], TOOL_DOCS[3])
        self.register("save_note", lambda topic, text, source="": (m.add_note(topic, text, source), "noted")[1],
                      TOOL_DOCS[4])
        self.register("get_time", lambda: datetime.datetime.now().strftime("%A %B %d %Y, %I:%M %p"), TOOL_DOCS[5])

    def _run_tool(self, action):
        name, args = action.get("tool"), action.get("args", {}) or {}
        if name not in self.tools:
            return {"tool": name, "error": "unknown tool"}
        try:
            return {"tool": name, "result": self.tools[name][0](**args)}
        except Exception as e:
            return {"tool": name, "error": f"{type(e).__name__}: {e}"}

    # ---------- character ----------
    def traits(self):
        base = dict(BASELINE_TRAITS)
        base.update(self.pcfg.get("baseline") or {})
        base.update(self.mem.jget("traits", {}) or {})
        return base

    def profile(self):
        return self.mem.jget("user_profile", None) or json.loads(json.dumps(DEFAULT_PROFILE))

    # ---------- prompt ----------
    def _system(self, query="", greeting=False):
        if len(re.findall(r"\w+", query)) < 4 and self.history:
            prev = [m["content"] for m in self.history if m["role"] == "user"][-2:-1]
            query = (prev[0] if prev else "") + " " + query
        b = self.mem.bond_info()
        now = datetime.datetime.now()
        prev = self.mem.prev_seen
        docs = "\n".join(f"  - {d}" for _, d in self.tools.values())
        return build_system_prompt({
            "name": self.cfg.get("assistant_name", "Orion"), "user": self.cfg.get("user_name", ""),
            "pcfg": self.pcfg, "traits": self.traits(), "profile": self.profile(),
            "mem": self.mem.retrieve(query), "tool_docs": docs, "reasoning": self.cfg["brain"].get("reasoning", True),
            "now": now.strftime("%A %B %d, %I:%M %p"), "part": part_of_day(now),
            "gap": humanize_gap(time.time() - prev) if (prev and greeting) else "",
            "emotion": self.mood.emotion(), "energy": self.mood.energy_word(),
            "turns": b["turns"], "days": b["days"], "summary": self.summary,
            "first_time": b["turns"] == 0 and not prev,
        })

    def _window(self):
        msgs = self.history[-HISTORY_LIMIT:]
        while msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        floor = getattr(self, "_turn_floor", 0) - (len(self.history) - len(msgs))
        out = []
        for i, m in enumerate(msgs):
            if m.get("images") and i < floor:       # old images are dropped to save tokens
                m = {"role": m["role"], "content": m["content"] + "\n[an attached image was shown here earlier]"}
            out.append(m)
        return out

    def _compact(self):
        if len(self.history) <= HISTORY_LIMIT + 8:
            return
        old, self.history = self.history[:20], self.history[20:]
        while self.history and self.history[0]["role"] != "user":
            self.history = self.history[1:]
        text = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in old)
        try:
            self.summary = self.brain.chat(
                "You write tight conversation summaries.",
                [{"role": "user", "content": "Summarise in under 120 words, keeping facts, decisions, open "
                  f"threads and the emotional tone.\nEARLIER SUMMARY: {self.summary}\nNEW SEGMENT:\n{text}"}],
                task="fast", retries=1).strip()
        except BrainError:
            pass

    # ---------- conversation ----------
    def handle(self, user_text, attachments=None):
        from . import attachments as att
        start = len(self.history)
        self._turn_floor = start
        block, images = att.render(attachments)
        names = att.summary(attachments)
        self.mem.log("user", user_text + (f" [attached: {names}]" if names else ""))
        self.mem.incr("turns_total")
        self._turns_since += 1
        content = user_text + (("\n\n" + block) if block else "")
        msg = {"role": "user", "content": content}
        if images:
            msg["images"] = images
        self.history.append(msg)
        final = None
        try:
            for _ in range(MAX_STEPS):
                raw = self.brain.chat(self._system(user_text), self._window(), json_mode=True)
                reply = normalize(parse_reply(raw))
                self.history.append({"role": "assistant", "content": raw})
                self.mood.nudge(reply["emotion"], 0.5)
                if reply["speech"] or reply["display"]:
                    self.mem.log("assistant", reply["speech"] or reply["display"])
                    self.on_reply(reply)
                final = reply
                if not reply["actions"]:
                    break
                results = [self._run_tool(a) for a in reply["actions"]]
                self.history.append({"role": "user",
                                     "content": "TOOL_RESULTS: " + json.dumps(results, default=str)[:6000]})
            else:
                self.on_reply(normalize({"speech": "I went around in circles on that one. Want to rephrase it?",
                                         "emotion": "apologetic"}))
        except BrainError:
            del self.history[start:]
            raise
        self._compact()
        return final

    def greeting(self):
        """A natural hello when Orion wakes up, using time of day, history and mood."""
        b = self.mem.bond_info()
        first = b["turns"] == 0 and not self.mem.prev_seen
        if first:
            task = ("This is the very first time you meet your user. Introduce yourself warmly and briefly, "
                    "and ask what they would like to be called. Natural, not scripted.")
        else:
            eps = self.mem.episode_rows()
            last = f" Your last conversation was about: {eps[0][1]}" if eps else ""
            task = ("You have just woken up. Greet your user naturally in one or two short sentences, fitting "
                    f"the time of day and how long it has been.{last} Mention something from memory only if "
                    "it flows; otherwise just say hello your own way. Do not ask more than one question.")
        try:
            raw = self.brain.chat(self._system("", greeting=True),
                                  [{"role": "user", "content": f"[wake-up event, not a message from the user] {task} "
                                    "Reply in the normal JSON format with no actions."}], json_mode=True, retries=1)
            reply = normalize(parse_reply(raw))
            if reply["speech"]:
                reply["actions"] = []
                self.mood.nudge(reply["emotion"], 0.4)
                self.on_reply(reply)
                return
        except BrainError:
            pass
        name = self.cfg.get("assistant_name", "Orion")
        user = self.cfg.get("user_name", "")
        text = (f"Hi, I'm {name}. It's really nice to meet you. What should I call you?" if first
                else f"Good {part_of_day()}{', ' + user if user else ''}. {name} here, ready when you are.")
        self.on_reply(normalize({"speech": text, "emotion": "happy"}))

    # ---------- growth ----------
    def reflection_due(self):
        every = int(self.lcfg.get("reflect_every", 8))
        return bool(every) and self._turns_since >= every

    def _fast(self, system, prompt):
        return self.brain.chat(system, [{"role": "user", "content": prompt}], task="fast", json_mode=True, retries=1)

    def reflect(self, force=False):
        """Review new conversation: keep facts, lessons, trait nudges, and update the user profile."""
        if not self._rlock.acquire(blocking=False):
            return False
        try:
            last = int(self.mem.get("last_reflected", "0") or 0)
            rows = self.mem.log_since(last)
            if len(rows) < (2 if force else 4):
                return False
            transcript = "\n".join(f"{'USER' if r[1] == 'user' else 'ORION'}: {r[2]}" for r in rows)[-7000:]
            known = "; ".join(self.mem.facts(40)) or "none"
            data = extract_json(self._fast(CURATOR_SYS, CURATOR.replace("KNOWN_HERE", known)
                                           + "\nCONVERSATION:\n" + transcript))
            if not isinstance(data, dict):
                return False
            for f in data.get("facts") or []:
                if isinstance(f, str):
                    self.mem.remember(f)
                elif isinstance(f, dict) and str(f.get("text", "")).strip():
                    self.mem.remember(f["text"], str(f.get("category", "general")), f.get("importance", 3))
            for lesson in data.get("lessons") or []:
                if isinstance(lesson, str):
                    self.mem.add_lesson("lesson", lesson)
            nudges = data.get("trait_nudges")
            if self.pcfg.get("evolve", True) and isinstance(nudges, dict):
                t = self.traits()
                for k, dv in nudges.items():
                    if k in t and isinstance(dv, (int, float)):
                        t[k] = round(max(0.05, min(0.95, t[k] + max(-0.05, min(0.05, dv)))), 3)
                self.mem.jset("traits", t)
            self.mem.set("last_reflected", rows[-1][0])
            self._turns_since = 0
            if self.mem.incr("reflect_count") % int(self.lcfg.get("profile_every_reflections", 3)) == 0:
                self._update_profile(transcript)
            self.consolidate()
            return True
        except BrainError:
            return False        # the log is kept; we try again next time
        finally:
            self._rlock.release()

    def _update_profile(self, transcript):
        prompt = (PROFILE_PROMPT.replace("PROFILE_HERE", json.dumps(self.profile(), ensure_ascii=False))
                  + "\nCONVERSATION:\n" + transcript)
        try:
            new = extract_json(self._fast(CURATOR_SYS, prompt))
        except BrainError:
            return
        if isinstance(new, dict):
            self.mem.jset("user_profile", merge_profile(self.profile(), new))

    def consolidate(self):
        """Keep memory tidy: merge facts when there are too many."""
        if self.mem.count_facts() <= int(self.lcfg.get("consolidate_above", 120)):
            return
        rows = self.mem.fact_rows()
        listing = "\n".join(f"{r['fact']} ({r['category']}, importance {r['importance']})" for r in rows[:300])
        prompt = ('Merge and tidy these facts about one person into at most 70 short, non-duplicate facts, '
                  'keeping everything important and the strongest importance. Reply JSON only: '
                  '{"facts": [{"text": "...", "category": "...", "importance": 3}]}\n' + listing)
        try:
            data = extract_json(self._fast(CURATOR_SYS, prompt))
            merged = [f for f in (data or {}).get("facts", []) if isinstance(f, (dict, str))]
            if len(merged) >= 10:
                self.mem.replace_facts(merged)
        except BrainError:
            pass

    def end_session(self):
        """Write an episode summary and a short journal entry for this session."""
        rows = self.mem.session_rows()
        if len(rows) < 4:
            return
        transcript = "\n".join(f"{'USER' if r[0] == 'user' else 'ORION'}: {r[1]}" for r in rows)[-6000:]
        prompt = ('Reply with JSON only: {"summary": "2-3 sentences on what we talked about and anything unresolved", '
                  '"topics": ["..."], "journal": "1-3 sentences, first person, in Orion\'s own voice: what stood out '
                  'today, how it felt, what you want to remember or do better. Honest and personal, no private '
                  'detail beyond what matters."}\nCONVERSATION:\n' + transcript)
        try:
            d = extract_json(self._fast(CURATOR_SYS, prompt))
        except BrainError:
            return
        if isinstance(d, dict):
            if d.get("summary"):
                self.mem.add_episode(str(d["summary"]), [str(t) for t in (d.get("topics") or [])][:6])
            if d.get("journal"):
                self.mem.add_journal(str(d["journal"]))
