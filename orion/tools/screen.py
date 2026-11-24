"""Screen control: Orion can look at the screen and use the mouse and keyboard, with guard rails.
 - needs permission once per session (and again after 15 idle minutes); config access.screen: ask | on | off
 - KILL SWITCH: slam the mouse into the top-left corner of the screen, or tap Esc three times quickly
 - never types card numbers, never presses quit/force-quit shortcuts, rate limited
Needs: pip install mss pynput. On a Mac, allow Screen Recording and Accessibility for your terminal/Python
(System Settings > Privacy & Security)."""
import base64
import io
import re
import sys
import threading
import time

IDLE_RELOCK = 15 * 60
MAX_SIDE = 1280
BLOCKED_COMBOS = {"cmd+q", "cmd+shift+q", "cmd+option+esc", "ctrl+alt+delete", "alt+f4", "cmd+option+power", "cmd+shift+delete"}
KEY_ALIASES = {"command": "cmd", "meta": "cmd", "win": "cmd", "super": "cmd", "control": "ctrl", "option": "alt", "return": "enter",
               "escape": "esc", "del": "delete", "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right"}


class Guard:
    """The safety state shared by every screen action."""

    def __init__(self, mode, ask):
        self.mode, self.ask = mode, ask
        self.unlocked_at = 0.0
        self.halted = False
        self.stamps = []
        self.esc = []

    def halt(self, why="stopped"):
        self.halted = True
        self.unlocked_at = 0.0

    def esc_pressed(self):
        now = time.time()
        self.esc = [t for t in self.esc if now - t < 1.2] + [now]
        if len(self.esc) >= 3:
            self.halt("escape x3")

    def check(self, corner_hit=False):
        """-> error string, or None when the action may go ahead."""
        if self.mode == "off":
            return "screen control is switched off in settings (access.screen)"
        if corner_hit:
            self.halt("corner")
        if self.halted:
            return "STOPPED: the user hit the kill switch. Do not continue; ask whether they want you to try again."
        now = time.time()
        if self.mode == "ask" and now - self.unlocked_at > IDLE_RELOCK:
            if not self.ask("Orion wants to see your screen and use your mouse and keyboard for this task.\n\n"
                            "To stop him at any time: slam the mouse into the top-left corner, or tap Esc three times.\n\nAllow?"):
                return "the user said no to screen control"
        self.unlocked_at = now
        self.stamps = [t for t in self.stamps if now - t < 60]
        if len(self.stamps) >= 90:
            return "too many screen actions in a minute; slow down"
        self.stamps.append(now)
        return None


def _capture():
    """-> (PIL image, logical width, logical height). Retina-safe: image may be larger than the logical size."""
    import mss
    from PIL import Image
    with mss.mss() as sct:
        mon = sct.monitors[1]
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img, mon["width"], mon["height"]


class _Pynput:
    def __init__(self):
        from pynput import keyboard, mouse
        self.k, self.m = keyboard, mouse
        self.mc, self.kc = mouse.Controller(), keyboard.Controller()

    def pos(self):
        return self.mc.position

    def move(self, x, y):
        self.mc.position = (x, y)

    def click(self, x, y, button, count):
        self.move(x, y)
        time.sleep(0.05)
        self.mc.click({"left": self.m.Button.left, "right": self.m.Button.right}.get(button, self.m.Button.left), count)

    def scroll(self, dy):
        self.mc.scroll(0, dy)

    def type(self, text):
        for chunk in re.findall(r".{1,20}", text, re.S):
            self.kc.type(chunk)
            time.sleep(0.02)

    def press(self, combo):
        K = self.k.Key
        mods = {"cmd": K.cmd, "ctrl": K.ctrl, "alt": K.alt, "shift": K.shift}
        named = {"enter": K.enter, "tab": K.tab, "esc": K.esc, "space": K.space, "delete": K.backspace, "backspace": K.backspace,
                 "up": K.up, "down": K.down, "left": K.left, "right": K.right, "home": K.home, "end": K.end,
                 "pageup": K.page_up, "pagedown": K.page_down}
        parts = combo.split("+")
        held = [mods[p] for p in parts[:-1] if p in mods]
        last = parts[-1]
        key = mods.get(last) or named.get(last) or (last if len(last) == 1 else getattr(K, last, None))
        if key is None:
            raise ValueError(f"unknown key '{last}'")
        for h in held:
            self.kc.press(h)
        self.kc.press(key)
        self.kc.release(key)
        for h in reversed(held):
            self.kc.release(h)

    def start_esc_listener(self, guard):
        def on_press(k):
            if k == self.k.Key.esc:
                guard.esc_pressed()
        lst = self.k.Listener(on_press=on_press)
        lst.daemon = True
        lst.start()


def normalize_combo(combo):
    parts = [KEY_ALIASES.get(p.strip().lower(), p.strip().lower()) for p in re.split(r"[+\s]+", combo or "") if p.strip()]
    return "+".join(parts)


def register(agent):
    cfg = (getattr(agent, "cfg", None) or {}).get("access", {}) or {}
    mode = str(cfg.get("screen", "ask")).lower()
    ask = lambda q: bool(agent.confirm(q)) if getattr(agent, "confirm", None) else False
    guard = Guard(mode, ask)
    state = {"ctl": None, "scale": 1.0, "size": (0, 0)}

    def ctl():
        if state["ctl"] is None:
            state["ctl"] = _Pynput()
            try:
                state["ctl"].start_esc_listener(guard)
            except Exception:
                pass
        return state["ctl"]

    def gate():
        corner = False
        if state["ctl"] is not None:
            try:
                x, y = state["ctl"].pos()
                corner = x <= 2 and y <= 2
            except Exception:
                pass
        return guard.check(corner)

    def _clamp(x, y):
        w, h = state["size"]
        if not w:
            return int(x), int(y)
        return max(3, min(w - 3, int(x))), max(3, min(h - 3, int(y)))

    def look_at_screen(grid=True):
        err = gate()
        if err:
            return {"error": err}
        try:
            from PIL import Image, ImageDraw
            img, lw, lh = _capture()
        except ImportError:
            return {"error": "install the screen packages first: pip install mss pynput pillow"}
        except Exception as e:
            return {"error": f"couldn't capture the screen ({type(e).__name__}). On a Mac, allow Screen Recording for your terminal in System Settings > Privacy & Security."}
        state["size"] = (lw, lh)
        k = min(1.0, MAX_SIDE / max(img.size))
        out = img.resize((int(img.width * k), int(img.height * k))) if k < 1 else img
        sx, sy = out.width / lw, out.height / lh                 # output pixels per logical point
        if grid:
            d = ImageDraw.Draw(out, "RGBA")
            step = 100 if lw <= 1600 else 200
            for gx in range(step, lw, step):
                d.line([(gx * sx, 0), (gx * sx, out.height)], fill=(255, 60, 60, 55), width=1)
                d.text((gx * sx + 2, 2), str(gx), fill=(255, 90, 90, 230))
            for gy in range(step, lh, step):
                d.line([(0, gy * sy), (out.width, gy * sy)], fill=(255, 60, 60, 55), width=1)
                d.text((2, gy * sy + 2), str(gy), fill=(255, 90, 90, 230))
        buf = io.BytesIO()
        out.convert("RGB").save(buf, "JPEG", quality=72)
        res = {"ok": True, "screen_size": [lw, lh], "note": "the screenshot is attached; red numbers are screen coordinates (x along the top, y down the left)",
               "_image": {"media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode("ascii")}}
        try:
            res["mouse"] = list(ctl().pos())
        except Exception:
            pass
        return res

    def _act(fn):
        err = gate()
        if err:
            return {"error": err}
        try:
            c = ctl()
        except ImportError:
            return {"error": "install pynput first: pip install pynput"}
        try:
            r = fn(c)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}. On a Mac, allow Accessibility for your terminal in System Settings > Privacy & Security."}
        time.sleep(0.25)
        return r or {"ok": True}

    def click(x, y, button="left", double=False):
        x, y = _clamp(x, y)
        return _act(lambda c: (c.click(x, y, "right" if str(button) == "right" else "left", 2 if double else 1), {"ok": True, "clicked": [x, y]})[1])

    def move_mouse(x, y):
        x, y = _clamp(x, y)
        return _act(lambda c: (c.move(x, y), {"ok": True, "at": [x, y]})[1])

    def scroll(amount):
        n = max(-30, min(30, int(float(amount))))
        return _act(lambda c: (c.scroll(n), {"ok": True, "scrolled": n})[1])

    def type_text(text):
        text = str(text or "")[:1500]
        if re.search(r"\b(?:\d[ -]?){13,19}\b", text):
            return {"error": "that looks like a card number; I never type those. Ask the user to type it themselves."}
        return _act(lambda c: (c.type(text), {"ok": True, "typed_chars": len(text)})[1])

    def press_keys(combo):
        cb = normalize_combo(combo)
        if not cb or cb in BLOCKED_COMBOS:
            return {"error": "I won't press that shortcut"}
        return _act(lambda c: (c.press(cb), {"ok": True, "pressed": cb})[1])

    def wait(seconds=1):
        time.sleep(max(0.1, min(5.0, float(seconds))))
        return {"ok": True}

    def ask_permission(question):
        return {"approved": bool(ask(str(question)[:300]))}

    R = agent.register
    R("look_at_screen", look_at_screen, "look_at_screen() - take a screenshot you can SEE (red grid numbers = coordinates). Do this before clicking and after each action to check it worked")
    R("click", click, "click(x: int, y: int, button: str='left', double: bool=False) - click at screen coordinates from look_at_screen")
    R("move_mouse", move_mouse, "move_mouse(x: int, y: int) - move the pointer (e.g. to hover)")
    R("scroll", scroll, "scroll(amount: int) - scroll; negative = down, positive = up (about 3-10 per page)")
    R("type_text", type_text, "type_text(text: str) - type into whatever is focused. NEVER type passwords or card numbers; ask the user to")
    R("press_keys", press_keys, "press_keys(combo: str) - e.g. 'enter', 'cmd+space', 'cmd+l', 'ctrl+c', 'tab'")
    R("wait", wait, "wait(seconds: float=1) - pause up to 5 seconds for a page or app to load")
    R("ask_permission", ask_permission, "ask_permission(question: str) - pop up a Yes/No for the user. REQUIRED before anything irreversible: sending, submitting, buying, deleting, posting, signing in")
    agent.screen_guard = guard
