"""The extra screens of the panel: the memory star-map (MIND), live system status (STATUS) and the weather card."""
import math
import os
import re
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .uikit import CATEGORY_COLORS, cpen, hud_font, rgba


def force_layout(n, edges, iters=160, seed=3):
    """A small spring layout: linked memories pull together, all of them push apart. -> (n,2) in about -1..1."""
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-1, 1, (n, 2))
    if n < 2:
        return pos * 0.0
    for it in range(iters):
        d = pos[:, None, :] - pos[None, :, :]
        dist2 = (d ** 2).sum(-1) + 0.02
        force = (d / dist2[..., None]).sum(1) * 0.012                # repulsion
        for i, j, w in edges:
            v = pos[j] - pos[i]
            dist = math.sqrt((v ** 2).sum()) + 1e-6
            pull = (dist - 0.28) * 0.03 * min(3, w)
            force[i] += v / dist * pull
            force[j] -= v / dist * pull
        force -= pos * 0.02                                          # keep them near the middle
        pos += np.clip(force, -0.08, 0.08) * (1 - it / iters * 0.7)
    mx = np.abs(pos).max(axis=0)
    mx[mx < 1e-6] = 1.0
    return pos / mx                                                  # fill the whole area, each axis on its own


class MindView(QWidget):
    """His memory drawn as a night sky: every fact is a star, linked ones form constellations."""

    def __init__(self, core, accent="#5aa8ff"):
        super().__init__()
        self.core, self.accent = core, QColor(accent)
        self.nodes, self.edges, self.pos = [], [], np.zeros((0, 2))
        self.hover = -1
        self.t0 = time.monotonic()
        self.setMouseTracking(True)
        rng = np.random.default_rng(11)
        self.dust = rng.uniform(0, 1, (70, 3))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.last_load = 0.0

    def showEvent(self, e):
        self.refresh()
        self.timer.start(50)

    def hideEvent(self, e):
        self.timer.stop()

    def set_accent(self, hex_):
        self.accent = QColor(hex_)

    def refresh(self):
        try:
            g = self.core.mind_graph()
        except Exception:
            g = {"nodes": [], "edges": []}
        old = {n["label"]: self.pos[i] for i, n in enumerate(self.nodes)} if len(self.pos) == len(self.nodes) else {}
        self.nodes, self.edges = g["nodes"], g["edges"]
        self.born = {n["label"]: self.born.get(n["label"], time.monotonic()) for n in self.nodes} \
            if hasattr(self, "born") else {n["label"]: self.t0 - 10 for n in self.nodes}
        self.pos = force_layout(len(self.nodes), self.edges)
        self.last_load = time.monotonic()

    def _xy(self, i, now):
        w, h = self.width(), self.height()
        x, y = self.pos[i]
        t = now - self.t0
        return QPointF(w / 2 + x * (w / 2 - 26) + 3 * math.sin(t * 0.5 + i), h / 2 - 8 + y * (h / 2 - 40) + 3 * math.cos(t * 0.4 + i * 1.7))

    def mouseMoveEvent(self, e):
        now, best, bd = time.monotonic(), -1, 14 ** 2
        for i in range(len(self.nodes)):
            p = self._xy(i, now)
            d = (p.x() - e.position().x()) ** 2 + (p.y() - e.position().y()) ** 2
            if d < bd:
                best, bd = i, d
        self.hover = best

    def leaveEvent(self, e):
        self.hover = -1

    def paintEvent(self, _):
        if time.monotonic() - self.last_load > 25:
            self.refresh()
        now = time.monotonic()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        for x, y, ph in self.dust:                                    # far-away stars
            a = 40 + 40 * math.sin(now * 0.8 + ph * 20)
            p.setPen(cpen(QColor(170, 205, 255, int(a)), 1.2))
            p.drawPoint(QPointF(x * w, y * h))
        if not self.nodes:
            p.setPen(QColor("#5e86c0"))
            p.setFont(hud_font(12, 2.0))
            p.drawText(self.rect(), Qt.AlignCenter, "NO MEMORIES YET\nTALK TO ME AND I WILL LEARN")
            p.end()
            return
        pts = [self._xy(i, now) for i in range(len(self.nodes))]
        for i, j, wgt in self.edges:                                  # constellation lines
            hot = self.hover in (i, j)
            c = QColor(CATEGORY_COLORS.get(self.nodes[i]["cat"], "#8a9bb8"))
            p.setPen(cpen(rgba(c, 170 if hot else 85), 1.6 if hot else 1.1))
            p.drawLine(pts[i], pts[j])
        for i, n in enumerate(self.nodes):
            c = QColor(CATEGORY_COLORS.get(n["cat"], "#8a9bb8"))
            tw = 0.75 + 0.25 * math.sin(now * (1.2 + (i % 5) * 0.3) + i)
            age = now - self.born.get(n["label"], 0)
            pop = 1.0 + max(0.0, 1.5 - age) * 1.6                       # a new memory flares up when it is born
            r = (2.6 + n["imp"] * 1.1) * tw * pop * (1.6 if i == self.hover else 1.0)
            g = QRadialGradient(pts[i], r * 4.2)
            g.setColorAt(0, rgba(c, 190 * tw))
            g.setColorAt(1, rgba(c, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(pts[i], r * 4.2, r * 4.2)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(pts[i], r * 0.55, r * 0.55)
            if n["imp"] >= 5 or i == self.hover:                         # four-point sparkle on the important ones
                p.setPen(cpen(rgba(c, 210), 1.0))
                p.drawLine(QPointF(pts[i].x() - r * 2.2, pts[i].y()), QPointF(pts[i].x() + r * 2.2, pts[i].y()))
                p.drawLine(QPointF(pts[i].x(), pts[i].y() - r * 2.2), QPointF(pts[i].x(), pts[i].y() + r * 2.2))
        p.setFont(hud_font(9, 0.6))
        for i, n in enumerate(self.nodes):                            # name the brightest stars
            if n["imp"] >= 5 and i != self.hover:
                p.setPen(rgba("#cfe3ff", 150))
                p.drawText(QPointF(pts[i].x() + 9, pts[i].y() + 3), n["label"][:16] + ("…" if len(n["label"]) > 16 else ""))
        # legend + hovered memory
        cats = sorted({n["cat"] for n in self.nodes})
        x = 8
        p.setFont(hud_font(9, 0.5))
        for cat in cats[:6]:
            c = QColor(CATEGORY_COLORS.get(cat, "#8a9bb8"))
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x + 3, h - 11), 3, 3)
            p.setPen(QColor("#7f9cc8"))
            p.drawText(QPointF(x + 10, h - 8), cat.upper()[:7])
            x += 16 + QFontMetrics(hud_font(9, 0.5)).horizontalAdvance(cat.upper()[:7])
        if self.hover >= 0:
            txt = self.nodes[self.hover]["label"]
            p.setFont(hud_font(11))
            fm = QFontMetrics(hud_font(11))
            box = QRectF(6, 4, w - 12, 46)
            p.setPen(cpen(rgba(self.accent, 140), 1))
            p.setBrush(QColor(6, 13, 32, 235))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor("#eaf3ff"))
            p.drawText(box.adjusted(8, 4, -8, -4), Qt.TextWordWrap | Qt.AlignVCenter, fm.elidedText(txt, Qt.ElideRight, int((w - 28) * 2.2)))
        p.end()


def _cpu_ram_batt():
    cpu = ram = batt = None
    try:
        import psutil
        cpu = psutil.cpu_percent(None)
        ram = psutil.virtual_memory().percent
        b = psutil.sensors_battery()
        batt = (b.percent, b.power_plugged) if b else None
    except Exception:
        try:
            cpu = min(100.0, os.getloadavg()[0] / (os.cpu_count() or 1) * 100)
        except Exception:
            pass
    return cpu, ram, batt


class StatusView(QWidget):
    """A live instrument panel: clock, how he is doing, how the computer is doing, countdowns."""

    def __init__(self, core, accent="#5aa8ff"):
        super().__init__()
        self.core, self.accent = core, QColor(accent)
        self.weather = None
        self.stats = (None, None, None)
        self._stat_t = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

    def showEvent(self, e):
        self.timer.start(250)

    def hideEvent(self, e):
        self.timer.stop()

    def set_accent(self, hex_):
        self.accent = QColor(hex_)

    def set_weather(self, w):
        self.weather = w

    def _gauge(self, p, cx, cy, r, frac, label, value):
        p.setPen(QPen(QColor(90, 150, 230, 50), 5))
        p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 225 * 16, -270 * 16)
        if frac is not None:
            p.setPen(QPen(self.accent, 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 225 * 16, int(-270 * 16 * max(0.0, min(1.0, frac))))
        p.setPen(QColor("#eaf3ff"))
        p.setFont(hud_font(13, 0.5, 600))
        p.drawText(QRectF(cx - r, cy - 9, 2 * r, 18), Qt.AlignCenter, value)
        p.setPen(QColor("#6f9cd8"))
        p.setFont(hud_font(8, 1.5))
        p.drawText(QRectF(cx - r - 6, cy + r - 6, 2 * r + 12, 14), Qt.AlignCenter, label)

    def paintEvent(self, _):
        try:
            st = self.core.status()
        except Exception:
            st = {"brain": "?", "memory": {}, "timers": [], "listening": False, "voice": False, "state": "idle", "tools": 0}
        if time.monotonic() - self._stat_t > 2:
            self.stats = _cpu_ram_batt()
            self._stat_t = time.monotonic()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        now = time.localtime()
        p.setPen(QColor("#dff0ff"))
        p.setFont(hud_font(40, 3, 300))
        p.drawText(QRectF(0, 0, w, 52), Qt.AlignHCenter | Qt.AlignVCenter, time.strftime("%H:%M", now))
        p.setPen(QColor("#6f9cd8"))
        p.setFont(hud_font(10, 2.5))
        p.drawText(QRectF(0, 50, w, 16), Qt.AlignHCenter, time.strftime("%A  %B %d", now).upper())
        if self.weather:
            p.setPen(QColor("#9fd0ff"))
            p.setFont(hud_font(11, 1))
            p.drawText(QRectF(0, 68, w, 16), Qt.AlignHCenter, self.weather)
        cpu, ram, batt = self.stats
        y = 118
        for i, (frac, label, val) in enumerate((
                (None if cpu is None else cpu / 100, "CPU", "--" if cpu is None else f"{cpu:.0f}%"),
                (None if ram is None else ram / 100, "MEMORY", "--" if ram is None else f"{ram:.0f}%"),
                (None if batt is None else batt[0] / 100, "POWER", "AC" if batt is None else f"{batt[0]:.0f}%"))):
            self._gauge(p, w * (0.2 + 0.3 * i), y, 30, frac, label, val)
        # his own numbers
        m = st["memory"]
        y2 = 176
        cells = (("FACTS", m.get("facts", 0)), ("LESSONS", m.get("lessons", 0)), ("NOTES", m.get("notes", 0)),
                 ("DAYS", m.get("days", 0)))
        for i, (label, v) in enumerate(cells):
            cx = w * (0.125 + 0.25 * i)
            p.setPen(QColor("#eaf3ff"))
            p.setFont(hud_font(20, 0, 300))
            p.drawText(QRectF(cx - 40, y2, 80, 26), Qt.AlignCenter, str(v))
            p.setPen(QColor("#6f9cd8"))
            p.setFont(hud_font(8, 1.5))
            p.drawText(QRectF(cx - 40, y2 + 24, 80, 12), Qt.AlignCenter, label)
        p.setPen(QColor("#7f9cc8"))
        p.setFont(hud_font(9, 1.2, mono=True))
        brain = str(st.get("brain", "?")).upper()
        line = f"BRAIN {brain}   MIC {'ON' if st.get('listening') else 'OFF'}   VOICE {'ON' if st.get('voice') else 'OFF'}   TOOLS {st.get('tools', 0)}"
        p.drawText(QRectF(0, y2 + 46, w, 14), Qt.AlignHCenter, line)
        # countdowns
        y3 = y2 + 76
        p.setPen(QColor("#6f9cd8"))
        p.setFont(hud_font(9, 2.0))
        p.drawText(QPointF(14, y3), "TIMERS AND REMINDERS")
        items = st["timers"][:4]
        if not items:
            p.setPen(QColor("#4f6c99"))
            p.setFont(hud_font(11, 0, italic=True))
            p.drawText(QRectF(0, y3 + 10, w, 20), Qt.AlignHCenter, "none. try:  /timer 10m tea")
        for k, it in enumerate(items):
            top = y3 + 12 + k * 38
            total = max(1.0, it["at"] - it.get("start", it["at"] - 1))
            left = max(0.0, it["at"] - time.time())
            frac = left / total
            p.setPen(QPen(QColor(90, 150, 230, 50), 3))
            p.drawArc(QRectF(16, top + 2, 24, 24), 0, 360 * 16)
            p.setPen(QPen(self.accent, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(16, top + 2, 24, 24), 90 * 16, int(-360 * 16 * frac))
            p.setPen(QColor("#eaf3ff"))
            p.setFont(hud_font(12))
            p.drawText(QRectF(50, top, w - 130, 28), Qt.AlignVCenter, it["text"][:34])
            s = int(left)
            tl = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
            p.setFont(hud_font(14, 1, 300, mono=True))
            p.setPen(QColor("#9fe0ff"))
            p.drawText(QRectF(w - 100, top, 86, 28), Qt.AlignVCenter | Qt.AlignRight, tl)
        p.end()


def _deg(text):
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(text))
    return f"{round(float(m.group(1)))}°" if m else str(text)


class WeatherCard(QFrame):
    """A small instrument-style card shown in the chat when he checks the weather."""

    def __init__(self, data, accent="#5aa8ff"):
        super().__init__()
        self.d, self.accent = data, QColor(accent)
        self.setFixedSize(270, 118)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(cpen(rgba(self.accent, 120), 1))
        p.setBrush(QColor(8, 20, 46, 220))
        p.drawRoundedRect(r, 7, 7)
        now = self.d.get("now", {})
        p.setPen(QColor("#6f9cd8"))
        p.setFont(hud_font(9, 2))
        p.drawText(QPointF(14, 20), str(self.d.get("place", "")).upper()[:34])
        p.setPen(QColor("#f2f8ff"))
        p.setFont(hud_font(34, 0, 300))
        p.drawText(QRectF(12, 24, 130, 44), Qt.AlignLeft | Qt.AlignVCenter, _deg(now.get("temperature", "")))
        p.setPen(QColor("#bfe0ff"))
        p.setFont(hud_font(12))
        p.drawText(QRectF(130, 30, 130, 20), Qt.AlignLeft, str(now.get("conditions", "")).capitalize())
        p.setPen(QColor("#7f9cc8"))
        p.setFont(hud_font(10))
        p.drawText(QRectF(130, 50, 135, 16), Qt.AlignLeft, f"feels {now.get('feels_like', '')}  wind {now.get('wind', '')}")
        days = self.d.get("next_days", [])[:3]
        for i, dd in enumerate(days):
            x = 14 + i * 84
            p.setPen(QColor("#6f9cd8"))
            p.setFont(hud_font(9, 1))
            try:
                nm = time.strftime("%a", time.strptime(dd["date"], "%Y-%m-%d")).upper()
            except Exception:
                nm = ""
            p.drawText(QPointF(x, 84), nm)
            p.setPen(QColor("#eaf3ff"))
            p.setFont(hud_font(11))
            p.drawText(QPointF(x, 100), f"{_deg(dd['high'])} / {_deg(dd['low'])}")
            p.setPen(QColor("#7fc8ff"))
            p.setFont(hud_font(9))
            p.drawText(QPointF(x, 112), f"rain {dd['chance_of_rain']}")
        p.end()
