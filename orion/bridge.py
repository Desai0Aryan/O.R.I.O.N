"""A tiny local server that a browser extension talks to, so Orion can see your open tabs and read a tab you choose.

Safety: binds to 127.0.0.1 only, needs a secret token, rejects odd Host headers (DNS-rebinding), sends no CORS
headers (web pages cannot read it), and only returns a page's text when YOU pick that tab in the + menu."""
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STALE_AFTER = 25.0      # seconds without an update before we treat the browser as disconnected
LONG_POLL = 20.0


class Bridge:
    def __init__(self, data_dir, port=8765):
        self.port = int(port)
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        tf = self.dir / "bridge_token.txt"
        if tf.exists() and tf.read_text().strip():
            self.token = tf.read_text().strip()
        else:
            self.token = secrets.token_hex(16)
            tf.write_text(self.token)
            try:
                tf.chmod(0o600)
            except OSError:
                pass
        self.cv = threading.Condition()
        self.browsers = {}          # browser name -> {"ts": float, "tabs": [..]}
        self.requests = []          # pending page-text requests for the extension
        self.results = {}           # id -> {"text":..., "error":...}
        self.server = None
        self.error = ""

    # ---------- lifecycle ----------
    def start(self):
        bridge = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _ok_host(self):
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{bridge.port}", f"localhost:{bridge.port}")

            def _auth(self):
                if not self._ok_host():
                    self._send(403, {"error": "bad host"})
                    return False
                if not secrets.compare_digest(self.headers.get("X-Orion-Token", ""), bridge.token):
                    self._send(401, {"error": "bad token"})
                    return False
                return True

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                n = int(self.headers.get("Content-Length", "0") or 0)
                if n > 2_000_000:
                    return None
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except json.JSONDecodeError:
                    return None

            def do_POST(self):
                if not self._auth():
                    return
                data = self._body()
                if not isinstance(data, dict):
                    return self._send(400, {"error": "bad json"})
                if self.path == "/tabs":
                    bridge._set_tabs(str(data.get("browser", "browser"))[:30], data.get("tabs") or [])
                    return self._send(200, {"ok": True})
                if self.path == "/result":
                    bridge._set_result(str(data.get("id", "")), str(data.get("text", ""))[:120_000],
                                       str(data.get("error", ""))[:300])
                    return self._send(200, {"ok": True})
                self._send(404, {"error": "unknown"})

            def do_GET(self):
                if not self._auth():
                    return
                if self.path.startswith("/poll"):
                    return self._send(200, {"requests": bridge._take_requests(LONG_POLL)})
                if self.path == "/ping":
                    return self._send(200, {"ok": True, "app": "orion"})
                self._send(404, {"error": "unknown"})

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        except OSError as e:
            self.error = f"port {self.port} is busy ({e})"
            return False
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return True

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass

    # ---------- internal ----------
    def _set_tabs(self, browser, tabs):
        clean = []
        for t in tabs[:300]:
            if isinstance(t, dict) and t.get("url"):
                clean.append({"id": t.get("id"), "window": t.get("windowId"), "title": str(t.get("title", ""))[:200],
                              "url": str(t.get("url", ""))[:600], "active": bool(t.get("active"))})
        with self.cv:
            self.browsers[browser] = {"ts": time.time(), "tabs": clean}

    def _take_requests(self, wait):
        end = time.time() + wait
        with self.cv:
            while not self.requests and time.time() < end:
                self.cv.wait(min(1.0, end - time.time()))
            out, self.requests = self.requests, []
            return out

    def _set_result(self, rid, text, error):
        with self.cv:
            self.results[rid] = {"text": text, "error": error}
            self.cv.notify_all()

    # ---------- used by Orion ----------
    def connected(self):
        with self.cv:
            return any(time.time() - b["ts"] < STALE_AFTER for b in self.browsers.values())

    def tabs(self):
        """Fresh tabs from every connected browser."""
        out = []
        with self.cv:
            for name, b in self.browsers.items():
                if time.time() - b["ts"] < STALE_AFTER:
                    for t in b["tabs"]:
                        out.append({**t, "browser": name})
        return out

    def request_text(self, browser, tab_id, timeout=10.0):
        """Ask the extension for a tab's readable text. -> (text, error)."""
        rid = uuid.uuid4().hex
        with self.cv:
            self.requests.append({"id": rid, "tabId": tab_id, "browser": browser})
            self.cv.notify_all()
            end = time.time() + timeout
            while rid not in self.results and time.time() < end:
                self.cv.wait(min(0.5, end - time.time()))
            res = self.results.pop(rid, None)
            if res is None:
                self.requests = [r for r in self.requests if r["id"] != rid]
        if res is None:
            return "", "The browser didn't answer in time. Is it open, and is the extension connected?"
        return res["text"], res["error"]
