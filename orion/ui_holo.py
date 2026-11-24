"""The two windows that make Orion look projected onto your desktop instead of sitting in an app:
HoloWindow (the hologram, no frame, no background, only the glowing shape catches the mouse) and
HoloCaption (his words, floating as glowing text with no box around them)."""
import sys

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from .uikit import cpen, hud_font, rgba


def _floating_flags(extra=0):
    return Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | extra


class HoloWindow(QWidget):
    """Holds only the hologram. Fully transparent; on a Mac the clear parts of it let every click through."""

    def __init__(self, ctrl, orb):
        super().__init__()
        self.ctrl, self.orb = ctrl, orb
        self.setWindowFlags(_floating_flags())
        for a in ("WA_TranslucentBackground", "WA_NoSystemBackground", "WA_ShowWithoutActivating", "WA_MacAlwaysShowToolWindow"):
            try:
                self.setAttribute(getattr(Qt, a))
            except Exception:
                pass
        self.setAcceptDrops(True)
        self.setWindowTitle(ctrl.name)
        orb.setParent(self)
        orb.move(0, 0)
        self.setFixedSize(orb.size())
        self.dragging = False
        self._native_ignore = None
        self._mac = sys.platform == "darwin"
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll_input)
        self.poll.start(40)
        self.refresh_shape()

    # the part of the window that is "him": a disc around the core plus the projector base
    def hit_region(self, k=1.0):
        s = self.orb
        r = s.S * 0.30
        cx, cy = s.width() / 2, s.height() * 0.47
        disc = QRegion(QRect(int(cx - 2.15 * r * k), int(cy - 2.15 * r * k), int(4.3 * r * k), int(4.3 * r * k)), QRegion.Ellipse)
        base = QRegion(QRect(int(cx - 1.75 * r * k), int(cy + 1.45 * r), int(3.5 * r * k), int(1.4 * r)), QRegion.Ellipse)
        return disc.united(base)

    def refresh_shape(self):
        self.setFixedSize(self.orb.size())
        if not self._mac:
            self.setMask(self.hit_region(1.25))             # Windows / Linux: clicks outside the glow reach the desktop

    def _poll_input(self):
        """macOS: the window ignores the mouse except while the pointer is over the glowing shape."""
        if not self._mac or self.dragging:
            return
        try:
            from .platform_tweaks import set_click_through
            from PySide6.QtGui import QCursor
            inside = self.hit_region().contains(self.mapFromGlobal(QCursor.pos()))
            if self._native_ignore is None or self._native_ignore == inside:
                if set_click_through(self, not inside):
                    self._native_ignore = not inside
        except Exception:
            self._mac = False

    def dragEnterEvent(self, e):
        self.ctrl.dragEnterEvent(e)

    def dropEvent(self, e):
        self.ctrl.dropEvent(e)

    def wheelEvent(self, e):                                 # Ctrl/Cmd + scroll over him resizes him
        if e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            self.ctrl.resize_orb(1.08 if e.angleDelta().y() > 0 else 1 / 1.08)
            e.accept()


class HoloCaption(QWidget):
    """His words as glowing text floating on the desktop: a thin accent line, a soft dark halo so it reads on
    any wallpaper, typed out as he speaks, then fading away."""
    MAXW = 360

    def __init__(self, accent="#5aa8ff"):
        super().__init__()
        self.setWindowFlags(_floating_flags(Qt.WindowTransparentForInput))
        for a in ("WA_TranslucentBackground", "WA_NoSystemBackground", "WA_ShowWithoutActivating", "WA_MacAlwaysShowToolWindow",
                  "WA_TransparentForMouseEvents"):
            try:
                self.setAttribute(getattr(Qt, a))
            except Exception:
                pass
        self.accent = QColor(accent)
        self.lines, self.font_, self.muted, self.mono = [], hud_font(14), False, False
        self.cps, self.shown, self.alpha, self.target = 80.0, 0.0, 0.0, 0.0
        self.total = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.hold = QTimer(self)
        self.hold.setSingleShot(True)
        self.hold.timeout.connect(self.fade_out)

    def set_accent(self, hex_):
        self.accent = QColor(hex_)
        self.update()

    def _wrap(self, text, fm, maxw):
        out = []
        for para in text.split("\n"):
            cur = ""
            for word in para.split(" "):
                trial = (cur + " " + word).strip()
                if cur and fm.horizontalAdvance(trial) > maxw:
                    out.append(cur)
                    cur = word
                else:
                    cur = trial
            out.append(cur)
        return out

    def show_text(self, text, muted=False, mono=False, cps=80.0, hold_ms=None):
        if not text:
            return
        text = text if len(text) <= 240 else text[:237] + "..."
        self.muted, self.mono, self.cps = muted, mono, cps
        self.font_ = hud_font(12 if mono else 15, 1.0 if mono else 0.2, italic=muted and not mono, mono=mono)
        fm = QFontMetrics(self.font_)
        self.lines = self._wrap(text, fm, self.MAXW - 40)
        self.total = sum(len(x) for x in self.lines)
        self.lh = fm.lineSpacing() + 2
        w = max(120, min(self.MAXW, max(fm.horizontalAdvance(x) for x in self.lines) + 44))
        self.setFixedSize(w, self.lh * len(self.lines) + 34)
        self.shown = 0.0
        self.target = 1.0
        self.hold.stop()
        self.show()
        self.timer.start(33)
        self.hold_ms = hold_ms if hold_ms else max(3200, min(14000, len(text) * 70))
        self._hold_armed = False
        self.update()

    def fade_out(self):
        self.target = 0.0
        self.timer.start(33)

    def hide_text(self):
        self.hold.stop()
        self.target = 0.0
        self.alpha = 0.0
        self.timer.stop()
        self.hide()

    def _step(self):
        self.shown += self.cps * 0.033
        self.alpha += (self.target - self.alpha) * 0.32
        if self.target > 0 and self.shown >= self.total and not self._hold_armed:
            self._hold_armed = True
            self.hold.start(int(self.hold_ms))
        if self.target == 0 and self.alpha < 0.03:
            self.hide_text()
            return
        self.update()

    def place_near(self, orb_geo, corner, scr):
        w, h = self.width(), self.height()
        above = corner.startswith("bottom")
        y = orb_geo.top() - h + 28 if above else orb_geo.bottom() - 28
        x = orb_geo.right() - w - 6 if corner.endswith("right") else orb_geo.left() + 6
        x = max(scr.left() + 6, min(scr.right() - w - 6, x))
        y = max(scr.top() + 6, min(scr.bottom() - h - 6, y))
        self.move(QPoint(int(x), int(y)))

    def paintEvent(self, _):
        if not self.lines:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self.alpha)))
        h = self.height()
        a = self.accent
        # the thin projected line on the left, with a bright tick
        p.setPen(cpen(rgba(a, 70), 5))
        p.drawLine(7, 10, 7, h - 10)
        p.setPen(cpen(rgba(a, 230), 1.6))
        p.drawLine(7, 10, 7, h - 10)
        p.setPen(cpen(QColor(255, 255, 255, 230), 2.4))
        p.drawLine(7, 10, 7, 24)
        p.setPen(cpen(rgba(a, 200), 1.2))
        p.drawLine(7, 10, 16, 10)
        remaining = int(self.shown)
        base = QColor("#9aa6c4") if self.muted else QColor("#f2f8ff")
        y = 14
        fm = QFontMetrics(self.font_)
        for line in self.lines:
            if remaining <= 0:
                break
            part = line[:remaining]
            remaining -= len(line)
            y += self.lh
            path = QPainterPath()
            path.addText(22, y - 6, self.font_, part)
            p.setPen(QPen(QColor(0, 6, 20, 120), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))   # dark halo: readable on any wallpaper
            p.drawPath(path)
            p.setPen(QPen(rgba(a, 60), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))           # the glow
            p.drawPath(path)
            p.fillPath(path, base)
            if remaining <= 0 and self.shown < self.total and self.mono:
                p.fillRect(int(22 + fm.horizontalAdvance(part)) + 2, y - fm.ascent() - 2, 8, fm.height(), rgba(a, 220))
        p.end()
