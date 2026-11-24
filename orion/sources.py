"""What is open on your computer right now: apps/windows (best effort per OS) and browser tabs."""
import subprocess
import sys

MY_TITLES = {"orion"}
JUNK_TITLES = {"program manager", "default ime", "msctfime ui", "windows input experience", "settings", ""}


def _run(cmd, timeout=4):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _osa(script, timeout=6):
    return _run(["osascript", "-e", script], timeout)


# ---------------- windows / apps ----------------
def parse_rows(text, cols=2):
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= cols and any(p.strip() for p in parts):
            rows.append([p.strip() for p in parts])
    return rows


def _windows_win32():
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    dwm = ctypes.windll.dwmapi
    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def app_of(hwnd):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        k32.CloseHandle(h)
        return buf.value.replace("\\", "/").split("/")[-1].removesuffix(".exe") if ok else ""

    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd):
            return True
        cloaked = ctypes.c_int(0)
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        if cloaked.value:
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        out.append({"app": app_of(hwnd), "title": buf.value})
        return True
    u32.EnumWindows(proto(cb), 0)
    return out


def _windows_mac():
    script = '''set out to ""
tell application "System Events"
  repeat with p in (every application process whose background only is false)
    set pn to name of p
    set got to false
    try
      repeat with w in (every window of p)
        set out to out & pn & tab & (name of w) & linefeed
        set got to true
      end repeat
    end try
    if got is false then set out to out & pn & tab & "" & linefeed
  end repeat
end tell
return out'''
    rows = parse_rows(_osa(script), 1)
    return [{"app": r[0], "title": r[1] if len(r) > 1 else ""} for r in rows]


def _windows_linux():
    out = []
    for line in _run(["wmctrl", "-lp"]).splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 5:
            pid, title = parts[2], parts[4]
            app = ""
            try:
                app = open(f"/proc/{pid}/comm").read().strip()
            except OSError:
                pass
            out.append({"app": app, "title": title})
    return out


def list_windows():
    """[{'app','title'}] of visible windows. Empty when the OS gives us nothing."""
    try:
        if sys.platform.startswith("win"):
            rows = _windows_win32()
        elif sys.platform == "darwin":
            rows = _windows_mac()
        else:
            rows = _windows_linux()
    except Exception:
        rows = []
    seen, out = set(), []
    for r in rows:
        t = r["title"].lower()
        key = (r["app"].lower(), t)
        if t in MY_TITLES:
            continue
        if t in JUNK_TITLES and not (sys.platform == "darwin" and r["app"]):   # macOS lists apps with no window title
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:60]


# ---------------- browser tabs (macOS, no extension needed) ----------------
MAC_CHROMIUM = ["Google Chrome", "Brave Browser", "Microsoft Edge", "Arc", "Vivaldi", "Chromium"]


def _mac_running():
    names = _osa('tell application "System Events" to get name of every application process whose background only is false')
    return [n.strip() for n in names.split(",")]


def _mac_tabs_script(app):
    if app == "Safari":
        return f'''set out to ""
tell application "Safari"
  repeat with w in windows
    set i to 0
    repeat with t in tabs of w
      set i to i + 1
      set out to out & "Safari" & tab & (name of t) & tab & (URL of t) & tab & ((t is current tab of w) as text) & linefeed
    end repeat
  end repeat
end tell
return out'''
    return f'''set out to ""
tell application "{app}"
  repeat with w in windows
    set i to 0
    repeat with t in tabs of w
      set i to i + 1
      set out to out & "{app}" & tab & (title of t) & tab & (URL of t) & tab & ((i = (active tab index of w)) as text) & linefeed
    end repeat
  end repeat
end tell
return out'''


def parse_tab_rows(text):
    tabs = []
    for r in parse_rows(text, 3):
        tabs.append({"browser": r[0], "title": r[1], "url": r[2], "active": len(r) > 3 and r[3] == "true",
                     "source": "applescript"})
    return tabs


def mac_tabs():
    if sys.platform != "darwin":
        return []
    running = set(_mac_running())
    tabs = []
    for app in MAC_CHROMIUM + ["Safari"]:
        if app in running:
            tabs += parse_tab_rows(_osa(_mac_tabs_script(app)))
    return tabs


def mac_tab_text(app, url):
    """Readable text of a tab on macOS needs the browser's 'allow JavaScript from Apple Events' setting, so we
    fetch the public page instead. Pages behind a login should be attached as a screenshot."""
    return fetch_url_text(url)


# ---------------- reading a web page ----------------
def fetch_url_text(url, limit=60000):
    import re
    import requests
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Orion assistant)"})
        r.raise_for_status()
    except Exception as e:
        return "", f"Couldn't fetch that page ({type(e).__name__}). If it needs a login, attach a screenshot."
    html = r.text
    html = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    import html as _h
    text = _h.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:limit], ""
