"""The core: wires brain, memory, voice and the screen together, and owns the threads."""
import concurrent.futures
import json
import re
import threading
import time

from . import attachments as att
from .agent import Agent
from .brain import BrainError
from .bridge import Bridge
from .memory import Memory
from .memory import DATA

HELP = ("Commands: /memory (what I know about you), /profile (how I understand you), "
        "/journal (my recent reflections), /forget <text> (delete memories containing that text), "
        "/token (connect the browser extension), /help")


class Core:
    def __init__(self, cfg, emit, confirm=None):
        self.cfg = cfg
        self._emit = emit
        self.confirm_handler = confirm
        vc = cfg.get("voice", {})
        self.name = cfg.get("assistant_name", "Orion")
        self.listen_enabled = bool(vc.get("listen", False))
        self.speak_enabled = bool(vc.get("speak", True))
        self.window = float(vc.get("conversation_window", 25))
        self.wake_words = [w.lower() for w in (vc.get("wake_aliases") or [vc.get("wake_word", "orion")])]
        self.mic_muted = False
        self.mem = Memory()
        self.bridge = None
        bc = cfg.get("bridge", {})
        if bc.get("enabled", True):
            self.bridge = Bridge(DATA, bc.get("port", 8765))
            if not self.bridge.start():
                self.emit("system", level="warn", text=f"Browser link is off: {self.bridge.error}")
        self.voice = None
        if self.speak_enabled or self.listen_enabled:
            try:
                from .voice import Voice
                self.voice = Voice(cfg, self._voice_event)
            except Exception as e:
                self.emit("system", level="warn", text=f"Voice unavailable: {e}")
        self.agent = Agent(cfg, self.mem, self._on_reply, self.confirm)
        self._stop = threading.Event()
        self._proc_lock = threading.Lock()
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._thinking = self._speaking = self._hearing = False
        self._state = "idle"
        self.active_until = 0.0
        self._shut = False

    # ---------- plumbing ----------
    def emit(self, kind, **kw):
        try:
            self._emit(kind, **kw)
        except Exception:
            pass

    def confirm(self, question):
        return bool(self.confirm_handler(question)) if self.confirm_handler else False

    def _update_state(self):
        s = ("thinking" if self._thinking else "speaking" if self._speaking else
             "listening" if self._hearing else "muted" if (self.listen_enabled and self.mic_muted) else "idle")
        if s != self._state:
            self._state = s
            self.emit("state", state=s)

    def _voice_event(self, kind, **kw):
        if kind == "speaking_start":
            self._speaking = True
        elif kind == "speaking_end":
            self._speaking = False
            self.active_until = time.time() + self.window
        elif kind == "hearing":
            self._hearing = True
            self.emit("hearing")
        elif kind == "level":
            self.emit("level", **kw)
            return
        elif kind == "error":
            self.emit("system", level="warn", text=kw.get("text", "Voice problem"))
        self._update_state()

    def _on_reply(self, reply):
        self.emit("assistant", speech=reply["speech"], display=reply["display"], emotion=reply["emotion"],
                  mood=reply["mood"])
        self.emit("mood", emotion=reply["emotion"], mood=reply["mood"])
        if self.voice and self.speak_enabled and reply["speech"]:
            self.voice.speak(reply["speech"], reply["emotion"])

    # ---------- lifecycle ----------
    def start(self):
        self.emit("ready", brain=self.agent.brain.provider, listening=self.listen_enabled)
        if self.listen_enabled and self.voice:
            threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._greet, daemon=True).start()
        self._update_state()

    def _greet(self):
        try:
            self._thinking = True
            self._update_state()
            if self.cfg.get("personality", {}).get("greet_with_brain", True):
                self.agent.greeting()
            else:
                self._on_reply({"speech": f"{self.name} is online.", "display": "", "emotion": "calm", "mood": ""})
        except Exception as e:
            self.emit("system", level="error", text=f"Could not reach my brain: {e}")
        finally:
            self._thinking = False
            self._update_state()

    def shutdown(self):
        if self._shut:
            return
        self._shut = True
        self._stop.set()
        if self.bridge:
            self.bridge.stop()
        if self.voice:
            self.voice.stop_speaking()
        try:
            if self.cfg.get("learning", {}).get("reflect_on_exit", True):
                self.agent.reflect(force=True)
            self.agent.end_session()
        except Exception:
            pass

    def shutdown_async(self, done=None):
        def run():
            try:
                self.shutdown()
            finally:
                if done:
                    done()
        threading.Thread(target=run, daemon=True).start()

    # ---------- user controls ----------
    def set_mic_muted(self, muted):
        self.mic_muted = bool(muted)
        self._update_state()

    def stop_speaking(self):
        if self.voice:
            self.voice.stop_speaking()

    def submit_text(self, text, attachments=None):
        """Typed input from the UI (queued, in order)."""
        self.stop_speaking()
        self._pool.submit(self.process, text, "typed", attachments)

    # ---------- listening ----------
    def _listen_loop(self):
        while not self._stop.is_set():
            if self.mic_muted or self._thinking or (self.voice and self.voice.is_speaking()):
                time.sleep(0.2)
                continue
            try:
                heard = self.voice.listen(max_wait=5.0)
            except Exception as e:
                self.emit("system", level="error", text=f"Microphone problem: {e}. Mic muted.")
                self.set_mic_muted(True)
                continue
            self._hearing = False
            if not heard:
                self._update_state()
                continue
            text = self._gate(heard)
            if text is None:
                self._update_state()
                continue
            self.process(text, "voice")

    def _gate(self, heard):
        """Wake word, or a follow-up inside the conversation window."""
        low = heard.lower()
        hit = next((w for w in self.wake_words if w in low), None)
        if hit:
            cleaned = re.sub(rf"\b(hey|hi|ok|okay)?[, ]*{re.escape(hit)}\b[,.!?]*", "", heard, flags=re.I).strip()
            return cleaned or "(The user just said your name to get your attention.)"
        return heard if time.time() < self.active_until else None

    # ---------- one turn ----------
    def process(self, text, source="typed", attachments=None):
        with self._proc_lock:
            if text.startswith("/") and not attachments:
                return self._command(text)
            if attachments and not text.strip():
                text = "(I attached something. Please take a look.)"
            self._hearing = False
            self._thinking = True
            self.emit("user", text=text, source=source, attachments=att.public_view(attachments))
            self._update_state()
            try:
                self.agent.handle(text, attachments)
            except BrainError as e:
                self.emit("system", level="error", text=f"My brain is unreachable right now ({e}).")
                if self.voice and self.speak_enabled:
                    self.voice.speak("Sorry, I can't reach my brain right now. Check my connection or my settings.",
                                     "apologetic")
            except Exception as e:
                self.emit("system", level="error", text=f"Something went wrong: {type(e).__name__}: {e}")
            finally:
                self._thinking = False
                self._update_state()
            if self.voice:
                self.voice.wait_done()
            self.active_until = time.time() + self.window
            if self.agent.reflection_due():
                threading.Thread(target=self.agent.reflect, daemon=True).start()

    def _command(self, text):
        cmd, _, arg = text[1:].partition(" ")
        cmd = cmd.lower()
        self.emit("user", text=text, source="typed")
        if cmd == "memory":
            s = self.mem.stats()
            rows = self.mem.fact_rows()[:40]
            msg = (f"I know {s['facts']} facts, {s['lessons']} lessons, {s['notes']} notes and have {s['episodes']} "
                   f"conversation summaries ({s['turns']} turns over {s['days']} days).\n\n"
                   + ("\n".join(f"- {r['fact']}" for r in rows) or "Nothing saved yet."))
        elif cmd == "profile":
            p = self.agent.profile()
            t = self.agent.traits()
            msg = ("How I understand you:\n" + json.dumps(p, indent=2, ensure_ascii=False)
                   + "\n\nMy own tuning: " + ", ".join(f"{k} {v:.2f}" for k, v in t.items()))
        elif cmd == "journal":
            rows = self.mem.journal_rows()
            msg = "\n\n".join(f"{time.strftime('%b %d', time.localtime(ts))}: {e}" for ts, e in rows) \
                or "I haven't written anything yet."
        elif cmd == "token":
            if self.bridge:
                msg = (f"To let me see your browser tabs: load the 'extension' folder in Chrome or Edge "
                       f"(open chrome://extensions, turn on Developer mode, choose Load unpacked), click the Orion "
                       f"icon, and paste this token. Port {self.bridge.port}.\n\n{self.bridge.token}")
            else:
                msg = "The browser link is turned off (bridge.enabled in config.yaml)."
        elif cmd == "forget" and arg.strip():
            self.mem.forget(arg.strip())
            msg = f"Done. I've forgotten anything mentioning \"{arg.strip()}\"."
        else:
            msg = HELP
        self.emit("assistant", speech="", display=msg, emotion="neutral", mood="")
