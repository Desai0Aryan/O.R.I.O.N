"""Timers, reminders and the daily briefing. They survive restarts (stored in his memory)."""
import re
import time
import uuid
from datetime import datetime, timedelta

_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text):
    """'10m', '1h30m', '90 seconds', 'in 2 hours' -> seconds (None if it is not a duration)."""
    t = str(text).lower().replace("in ", " ").replace("and", " ")
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)(?![a-z])", t)
    return sum(float(n) * _UNIT[u[0]] for n, u in parts) if parts else None


def parse_when(text, now=None):
    """'2026-11-20 09:30', '09:30', 'tomorrow 9am', 'in 20 minutes' -> epoch seconds."""
    now = now or datetime.now()
    s = str(text).strip().lower()
    secs = None
    if s.startswith("in ") or (re.fullmatch(r"[\d.]+\s*[a-z]+(\s*[\d.]+\s*[a-z]+)*", s) and not re.search(r"am|pm", s)):
        secs = parse_duration(s)
    if secs:
        return (now + timedelta(seconds=secs)).timestamp()
    day = now.date()
    if "tomorrow" in s:
        day += timedelta(days=1)
        s = s.replace("tomorrow", "").strip()
    elif "today" in s or "tonight" in s:
        s = s.replace("today", "").replace("tonight", "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        day = datetime(int(m[1]), int(m[2]), int(m[3])).date()
        s = s.replace(m[0], "").strip()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        raise ValueError(f"I could not understand the time '{text}'")
    h, mi, ap = int(m[1]), int(m[2] or 0), m[3]
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        raise ValueError(f"I could not understand the time '{text}'")
    at = datetime(day.year, day.month, day.day, h, mi)
    if at <= now and "tomorrow" not in str(text).lower() and not re.search(r"\d{4}-", str(text)):
        at += timedelta(days=1)
    return at.timestamp()


def fmt_left(secs):
    secs = max(0, int(secs))
    if secs >= 3600:
        return f"{secs // 3600}h {secs % 3600 // 60:02d}m"
    if secs >= 60:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs}s"


class Clock:
    """The list of things he has to remind you of."""
    KEY = "reminders"

    def __init__(self, mem):
        self.mem = mem

    def all(self):
        return self.mem.jget(self.KEY, []) or []

    def _save(self, items):
        self.mem.jset(self.KEY, items[-60:])

    def add(self, kind, at, text, started=None):
        items = self.all()
        it = {"id": uuid.uuid4().hex[:6], "kind": kind, "at": at, "text": text, "start": started or time.time()}
        items.append(it)
        self._save(items)
        return it

    def pending(self):
        return sorted((i for i in self.all() if not i.get("fired")), key=lambda i: i["at"])

    def due(self, now=None):
        """Mark due items as fired and return them."""
        now = now or time.time()
        items, out = self.all(), []
        for i in items:
            if not i.get("fired") and i["at"] <= now:
                i["fired"] = True
                out.append(i)
        if out:
            self._save(items)
        return out

    def cancel(self, key):
        key = str(key).lower().strip()
        items, n = self.all(), 0
        for i in items:
            if not i.get("fired") and (i["id"] == key or key in i["text"].lower()):
                i["fired"] = True
                i["cancelled"] = True
                n += 1
        self._save(items)
        return n


def register(agent):
    clock = Clock(agent.mem)
    agent.clock = clock

    def set_timer(duration, label=""):
        secs = parse_duration(duration)
        if not secs or secs <= 0 or secs > 7 * 86400:
            return {"error": f"I could not understand the duration '{duration}'. Try '10 minutes' or '1h30m'."}
        it = clock.add("timer", time.time() + secs, label or "timer")
        return {"ok": True, "id": it["id"], "rings_in": fmt_left(secs), "label": it["text"]}

    def set_reminder(when, text):
        try:
            at = parse_when(when)
        except ValueError as e:
            return {"error": str(e)}
        it = clock.add("reminder", at, text)
        return {"ok": True, "id": it["id"], "at": datetime.fromtimestamp(at).strftime("%A %B %d, %I:%M %p"), "text": text}

    def list_reminders():
        return {"pending": [{"id": i["id"], "kind": i["kind"], "text": i["text"],
                             "in": fmt_left(i["at"] - time.time()),
                             "at": datetime.fromtimestamp(i["at"]).strftime("%a %I:%M %p")} for i in clock.pending()]}

    def cancel_reminder(which):
        n = clock.cancel(which)
        return {"cancelled": n} if n else {"error": f"nothing matched '{which}'"}

    def briefing():
        out = {"now": datetime.now().strftime("%A %B %d, %I:%M %p"), "reminders": list_reminders()["pending"][:5]}
        for name, call in (("weather", lambda: agent.tools["weather"][0]("")),
                           ("headlines", lambda: agent.tools["news"][0]("", 4))):
            try:
                out[name] = call()
            except Exception as e:
                out[name] = {"unavailable": str(e)[:100]}
        out["recently_studied"] = [x.get("topic") for x in (agent.mem.jget("recent_study", []) or [])[-3:]]
        return out

    agent.register("set_timer", set_timer, "set_timer(duration: str, label: str='') - a countdown such as '10 minutes'; he speaks when it rings")
    agent.register("set_reminder", set_reminder,
                   "set_reminder(when: str, text: str) - remind the user at a time: 'in 2 hours', '17:30', 'tomorrow 9am' or 'YYYY-MM-DD HH:MM' (local time)")
    agent.register("list_reminders", list_reminders, "list_reminders() - timers and reminders that are still pending")
    agent.register("cancel_reminder", cancel_reminder, "cancel_reminder(which: str) - cancel by id or by words in its text")
    agent.register("briefing", briefing,
                   "briefing() - the user's day at a glance: time, weather at home, top headlines, reminders. Use for 'brief me' / 'catch me up', then summarise warmly in a few sentences")
