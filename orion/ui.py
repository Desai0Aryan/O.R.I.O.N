"""Orion's on-screen presence: a holographic core floating in the corner of your screen, live captions,
and a HUD-style chat panel with a + menu for files, photos, screenshots, browser tabs and open apps.
Built with PySide6 (Qt)."""
import math
import random
import sys
import threading
import time
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QCursor, QBrush, QColor, QConicalGradient, QDesktopServices, QFont, QFontMetrics, QIcon,
                           QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget, QCompleter)

from . import attachments as att
from . import sources
from .hologram import THEMES, Hologram
from .mood import EMOTIONS
from .platform_tweaks import Hotkey, mac_menubar_app, show_on_all_spaces
from .sounds import Sounds
from .uikit import cpen, hud_font, lerp, rgba
from .ui_views import MindView, StatusView, WeatherCard

EXT_DIR = Path(__file__).resolve().parents[1] / "extension"
BASE = QColor("#3d8bff")
VIOLET = QColor("#8a5cff")
ICE = QColor(190, 225, 255)
GREY = QColor("#6b7280")


class UiBridge(QObject):
    """Lets the engine's threads talk to the UI thread safely."""
    event = Signal(str, dict)

    def emit_event(self, kind, **kw):
        self.event.emit(kind, kw)


# =====================================================================================================
#  The holographic core (a real 3D particle hologram, see hologram.py)
# =====================================================================================================
class OrbWidget(QWidget):
    clicked = Signal()
    dragStart = Signal(QPoint)
    dragTo = Signal(QPoint)
    dropped = Signal(QPoint)

    def __init__(self, size, accent, quality=1.25):
        super().__init__()
        self.base_size = size
        self.S = size
        self.quality = max(1.0, min(2.0, float(quality)))
        self.detail = 1.0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.state, self.emotion = "idle", "neutral"
        self.level = self.target_level = 0.0
        self.bands = None
        self._pulse = 0.0
        self._last_level = 0.0
        self._ms, self._frames = 0.0, 0
        self.theme = "arc"
        self._booted = False
        self._resize()
        self._build_holo()
        self.last = time.monotonic()
        self._press = None
        self._moved = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def _resize(self):
        self.setFixedSize(int(self.S * 2.1), int(self.S * 2.4))

    def _build_holo(self):
        q = self.quality
        self.holo = Hologram(int(self.width() * q), int(self.height() * q), self.S * q * 0.30, detail=self.detail)
        self.holo.set_theme(self.theme)
        self.holo.set_tint(self._tint())
        if self._booted:
            self.holo.boot = 1.0                 # only the very first build plays the assemble animation
        self._booted = True
        self._img = None

    def set_theme(self, name):
        self.theme = name
        self.holo.set_theme(name)

    def _tint(self):
        c = QColor(EMOTIONS[self.emotion][2])
        return (c.redF(), c.greenF(), c.blueF())

    def set_scale(self, k):
        self.S = self.base_size * k
        self._resize()
        self._build_holo()

    # ----- control -----
    def set_state(self, state):
        self.state = state

    def set_emotion(self, emotion):
        if emotion in EMOTIONS:
            self.emotion = emotion
            self.holo.set_tint(self._tint())

    def set_level(self, v, bands=None):
        self.target_level = max(0.0, min(1.0, v))
        self.bands = bands
        self._last_level = time.monotonic()

    def hear(self):
        self._pulse = 1.0

    def _tick(self):
        now = time.monotonic()
        dt = now - self.last
        self.last = now
        fresh = now - self._last_level < 0.25
        if not fresh:
            self.target_level *= 0.75
            self.bands = None
        if self.state == "speaking" and now - self._last_level > 0.3:       # built-in voice: synthetic rhythm
            self.target_level = 0.35 + 0.3 * abs(math.sin(now * 7.0))
        self.level = self.target_level
        self.holo.update(dt, self.state, self.level, self.bands if fresh else None, self._pulse)
        self._pulse = 0.0
        self.update()

    # ----- mouse: click toggles the panel, drag moves the orb -----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._moved = False
            self.dragStart.emit(self._press)

    def mouseMoveEvent(self, e):
        if self._press is not None:
            gp = e.globalPosition().toPoint()
            if (gp - self._press).manhattanLength() > 6:
                self._moved = True
            if self._moved:
                self.dragTo.emit(gp)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press is not None:
            if self._moved:
                self.dropped.emit(e.globalPosition().toPoint())
            else:
                self.clicked.emit()
            self._press = None

    # ----- paint: the hologram is rendered to one image per frame -----
    def paintEvent(self, _):
        t0 = time.perf_counter()
        arr = self.holo.render()
        h, w = arr.shape[:2]
        img = QImage(arr.data, w, h, w * 4, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(self.rect(), img)
        p.end()
        self._ms = self._ms * 0.9 + (time.perf_counter() - t0) * 1000 * 0.1
        self._frames += 1
        if self._frames % 60 == 0 and self._ms > 30:            # a slow computer: trade detail for smoothness
            if self.quality > 1.0:
                self.quality = 1.0
                self._build_holo()
            elif self.detail > 0.6:
                self.detail = 0.6
                self._build_holo()
            self._ms = 0.0


# =====================================================================================================
#  HUD widgets
# =====================================================================================================
class SignalBars(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(46, 30)
        self.level = 0.0
        self.shown = 0.0

    def set_level(self, v):
        self.level = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.shown += (self.level - self.shown) * 0.5
        lit = 2 + int(round(self.shown * 3))
        for i in range(5):
            h = 8 + i * 4.5
            on = i < lit
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(80, 170, 255, 255 if on else 55))
            p.drawRect(QRectF(i * 9 + 1, self.height() - h, 6, h))
        p.end()
        self.level *= 0.9


class HudFrame(QFrame):
    CUT = 20
    ACCENT = QColor("#5aa8ff")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, c = self.width() - 1.5, self.height() - 1.5, self.CUT
        path = QPainterPath()
        path.moveTo(c, 0.75)
        path.lineTo(w, 0.75)
        path.lineTo(w, h - c)
        path.lineTo(w - c, h)
        path.lineTo(0.75, h)
        path.lineTo(0.75, c)
        path.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(7, 14, 34, 242))
        g.setColorAt(1, QColor(4, 9, 24, 246))
        p.fillPath(path, g)
        p.setPen(QPen(rgba(self.ACCENT, 55), 6))
        p.drawPath(path)
        p.setPen(QPen(rgba(self.ACCENT, 215), 1.3))
        p.drawPath(path)
        p.setPen(QPen(self.ACCENT.lighter(150), 2.6))
        for (x1, y1, x2, y2) in ((0.75, c, 0.75, c + 30), (c, 0.75, c + 30, 0.75), (w, h - c, w, h - c - 30),
                                 (w - c, h, w - c - 30, h), (w, 0.75, w - 22, 0.75), (w, 0.75, w, 22),
                                 (0.75, h, 22, h), (0.75, h, 0.75, h - 22)):
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        p.end()


class PasteLineEdit(QLineEdit):
    pasteSpecial = Signal(object)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(False)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):
            md = QApplication.clipboard().mimeData()
            if md is not None and (md.hasImage() or md.hasUrls()):
                self.pasteSpecial.emit(md)
                return
        super().keyPressEvent(e)


def hud_label(text, px, spacing=0.0, color="#cfe3ff", weight=QFont.Normal, italic=False):
    lab = QLabel(text)
    lab.setFont(hud_font(px, spacing, weight, italic))
    lab.setStyleSheet(f"color: {color}; background: transparent;")
    return lab


STYLE = """
QPushButton#chip { background: rgba(70,150,255,34); color: #bcd8ff; border: 1px solid rgba(90,170,255,90);
                   border-radius: 4px; padding: 3px 10px; font-size: 11px; }
QPushButton#chip:hover { background: rgba(90,170,255,80); color: white; }
QPushButton#chip:checked { background: rgba(255,110,110,90); color: white; }
QPushButton#plus { background: rgba(70,150,255,30); color: #9fd0ff; border: 1px solid rgba(90,170,255,140);
                   border-radius: 17px; font-size: 20px; font-weight: 300; padding: 0 0 2px 0; }
QPushButton#plus:hover { background: rgba(90,170,255,90); color: white; }
QPushButton#send { background: #4a9bff; color: #04112b; border: none; border-radius: 4px; padding: 8px 16px;
                   font-weight: 700; letter-spacing: 1px; }
QPushButton#send:hover { background: white; }
QPushButton#tab { background: transparent; color: #7f9cc8; border: none; border-bottom: 2px solid transparent;
                  padding: 4px 10px; font-size: 10px; letter-spacing: 2px; }
QPushButton#tab:hover { color: white; }
QPushButton#tab:checked { color: #dff0ff; border-bottom: 2px solid #5aa8ff; }
QPushButton#x { background: transparent; color: #9fb4d8; border: none; font-size: 13px; padding: 0 2px; }
QPushButton#x:hover { color: #ff9a9a; }
QLineEdit { background: rgba(70,150,255,22); color: #f2f7ff; border: 1px solid rgba(90,170,255,100);
            border-radius: 4px; padding: 8px 12px; font-size: 13px; selection-background-color: #4a9bff; }
QLineEdit:focus { border: 1px solid #6fb4ff; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: rgba(110,180,255,80); border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 5px; }
QScrollBar::handle:horizontal { background: rgba(110,180,255,80); border-radius: 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""

MENU_QSS = """
QMenu { background: #09132b; color: #d3e5ff; border: 1px solid #2f6fd0; padding: 6px; }
QMenu::item { padding: 8px 26px 8px 16px; border-radius: 4px; }
QMenu::item:selected { background: rgba(80,160,255,80); color: white; }
QMenu::item:disabled { color: #6f84aa; }
QMenu::separator { height: 1px; background: rgba(120,180,255,60); margin: 6px 8px; }
"""

STATE_TEXT = {"idle": "READY.", "listening": "LISTENING...", "thinking": "PROCESSING...", "speaking": "SPEAKING...",
              "muted": "MIC MUTED."}


def trunc(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def bubble_width(font, text, max_w):
    fm = QFontMetrics(font)
    widest = max((fm.horizontalAdvance(line) for line in text.split("\n")), default=40)
    return max(48, min(max_w, widest + 34))


# =====================================================================================================
#  Chat panel
# =====================================================================================================
class ChatPanel(HudFrame):
    sendMessage = Signal(str, list)
    micToggled = Signal(bool)
    stopSpeech = Signal()
    closeRequested = Signal()
    attachReady = Signal(object)
    notice = Signal(str)

    def __init__(self, name, accent, listening, host, user_name=""):
        super().__init__()
        self.host = host
        self.accent = accent
        self.name = name
        self.pending = []
        self._empty = None
        self.setFixedSize(380, 520)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(9)

        head = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(hud_label(" ".join(name.upper()), 21, 5, "#7fc8ff", QFont.Light))
        left.addWidget(hud_label("AI ASSISTANT ONLINE", 9, 2.2, "#6f9cd8"))
        head.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(0)
        right.addWidget(hud_label("SYSTEM STATUS:", 8, 1.6, "#6f9cd8"), 0, Qt.AlignRight)
        self.sys_label = hud_label("OPERATIONAL", 11, 1.6, "#9fe0ff", QFont.DemiBold)
        right.addWidget(self.sys_label, 0, Qt.AlignRight)
        head.addLayout(right)
        self.bars = SignalBars()
        head.addWidget(self.bars)
        root.addLayout(head)

        row2 = QHBoxLayout()
        self.state_label = hud_label("> READY.", 10, 1.2, "#7fc8ff")
        row2.addWidget(self.state_label, 1)
        if listening:
            self.mic = QPushButton("Mic off")
            self.mic.setObjectName("chip")
            self.mic.setCheckable(True)
            self.mic.toggled.connect(self._mic)
            row2.addWidget(self.mic)
        for label, sig in (("Stop", self.stopSpeech), ("Hide", self.closeRequested)):
            b = QPushButton(label)
            b.setObjectName("chip")
            b.clicked.connect(sig)
            row2.addWidget(b)
        root.addLayout(row2)

        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.tab = 0
        self.tab_btns = []
        for i, label in enumerate(("CHAT", "MIND", "STATUS")):
            tb = QPushButton(label)
            tb.setObjectName("tab")
            tb.setCheckable(True)
            tb.clicked.connect(partial(self.set_tab, i))
            tabs.addWidget(tb)
            self.tab_btns.append(tb)
        tabs.addStretch(1)
        root.addLayout(tabs)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        inner = QWidget()
        inner.setAutoFillBackground(False)
        self.v = QVBoxLayout(inner)
        self.v.setContentsMargins(0, 0, 4, 0)
        self.v.setSpacing(8)
        self.v.addStretch(1)
        self.scroll.setWidget(inner)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.scroll)
        self.mind = MindView(host.core, accent)
        self.status = StatusView(host.core, accent)
        self.stack.addWidget(self.mind)
        self.stack.addWidget(self.status)
        root.addWidget(self.stack, 1)
        self.tab_btns[0].setChecked(True)
        who = f", {user_name.upper()}" if user_name else ""
        self._empty = hud_label(f"HOW CAN I HELP YOU{who}?", 12, 2.0, "#5e86c0")
        self._empty.setAlignment(Qt.AlignCenter)
        self.v.insertWidget(0, self._empty)

        self.chipbar = QScrollArea()
        self.chipbar.setFixedHeight(44)
        self.chipbar.setWidgetResizable(True)
        self.chipbar.setFrameShape(QFrame.NoFrame)
        self.chipbar.viewport().setStyleSheet("background: transparent;")
        self.chipbar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chipbar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cw = QWidget()
        self.chips = QHBoxLayout(cw)
        self.chips.setContentsMargins(0, 2, 0, 2)
        self.chips.setSpacing(6)
        self.chips.addStretch(1)
        self.chipbar.setWidget(cw)
        self.chipbar.hide()
        root.addWidget(self.chipbar)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.plus = QPushButton("+")
        self.plus.setObjectName("plus")
        self.plus.setFixedSize(34, 34)
        self.plus.setToolTip("Add files, photos, a screenshot, browser tabs or open apps")
        self.plus.clicked.connect(self._open_plus)
        self.input = PasteLineEdit()
        self.input.setPlaceholderText(f"Message {name}...")
        self.input.returnPressed.connect(self._send)
        self.input.pasteSpecial.connect(lambda md: self.add_items(att.from_mime(md)))
        send = QPushButton("SEND")
        send.setObjectName("send")
        send.clicked.connect(self._send)
        row.addWidget(self.plus)
        row.addWidget(self.input, 1)
        row.addWidget(send)
        self.rowW = QWidget()
        row.setContentsMargins(0, 0, 0, 0)
        self.rowW.setLayout(row)
        root.addWidget(self.rowW)
        self.completer = QCompleter(["/brief", "/timer ", "/remind ", "/study ", "/theme ", "/mind", "/status", "/memory",
                                     "/profile", "/journal", "/forget ", "/token", "/help"], self.input)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.popup().setStyleSheet(MENU_QSS)
        self.input.setCompleter(self.completer)

        self.attachReady.connect(lambda a: self.add_items([a]))
        self.notice.connect(lambda t: self.add_message("system", t))

    # ----- tabs, theme, cards -----
    def set_tab(self, i):
        self.tab = i
        self.stack.setCurrentIndex(i)
        for k, b in enumerate(self.tab_btns):
            b.setChecked(k == i)
        self.chipbar.setVisible(i == 0 and bool(self.pending))
        self.rowW.setVisible(i == 0)
        self.host.refit()

    def set_accent(self, hex_):
        self.accent = hex_
        self.ACCENT = QColor(hex_)
        self.setStyleSheet(STYLE.replace("#5aa8ff", hex_).replace("#4a9bff", hex_))
        self.mind.set_accent(hex_)
        self.status.set_accent(hex_)
        self.update()

    def add_card(self, widget):
        if self._empty is not None:
            self._empty.deleteLater()
            self._empty = None
        self.v.insertWidget(self.v.count() - 1, widget, 0, Qt.AlignLeft)
        QTimer.singleShot(60, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    # ----- header state -----
    def set_state(self, state, mood=""):
        txt = "> " + STATE_TEXT.get(state, state.upper())
        if mood:
            txt += f"   [{mood.upper()}]"
        self.state_label.setText(txt)

    def set_system(self, text, ok=True):
        self.sys_label.setText(text)
        self.sys_label.setStyleSheet(f"color: {'#9fe0ff' if ok else '#ff9a9a'}; background: transparent;")

    def _mic(self, off):
        self.mic.setText("Mic off" if off else "Mic on")
        self.micToggled.emit(off)

    # ----- attachments -----
    def add_items(self, items):
        for a in items:
            if len(self.pending) >= 10:
                self.add_message("system", "That's the limit of 10 attachments per message.")
                break
            self.pending.append(a)
        self._rebuild_chips()

    def _rebuild_chips(self):
        while self.chips.count() > 1:
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, a in enumerate(self.pending):
            chip = QFrame()
            chip.setStyleSheet("QFrame { background: rgba(70,150,255,34); border: 1px solid rgba(90,170,255,110); "
                               "border-radius: 4px; } QLabel { background: transparent; border: none; color: #d3e5ff; }")
            h = QHBoxLayout(chip)
            h.setContentsMargins(5, 3, 3, 3)
            h.setSpacing(5)
            if a.get("thumb"):
                pm = QPixmap()
                pm.loadFromData(a["thumb"])
                th = QLabel()
                th.setPixmap(pm.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                h.addWidget(th)
            lab = QLabel(trunc(a["name"], 22))
            lab.setFont(hud_font(11))
            lab.setToolTip(a["name"] + (f"  ({a['note']})" if a.get("note") else ""))
            h.addWidget(lab)
            x = QPushButton("✕")
            x.setObjectName("x")
            x.clicked.connect(partial(self._remove, i))
            h.addWidget(x)
            self.chips.insertWidget(self.chips.count() - 1, chip)
        self.chipbar.setVisible(bool(self.pending) and self.tab == 0)
        self.host.refit()

    def _remove(self, i):
        if 0 <= i < len(self.pending):
            self.pending.pop(i)
            self._rebuild_chips()

    def _send(self):
        text = self.input.text().strip()
        if not text and not self.pending:
            return
        atts, self.pending = list(self.pending), []
        self.input.clear()
        self._rebuild_chips()
        self.sendMessage.emit(text, atts)

    # ----- the + menu -----
    def _open_plus(self):
        m = QMenu(self)
        m.setStyleSheet(MENU_QSS)
        m.addAction("Add files or photos...", self.pick_files)
        m.addAction("Add a folder...", self.pick_folder)
        m.addAction("Take a screenshot", self.host.take_screenshot)
        m.addAction("Paste from clipboard", self.paste_clipboard)
        m.addSeparator()
        tabs = m.addMenu("Browser tabs")
        tabs.aboutToShow.connect(lambda: self._fill_tabs(tabs))
        wins = m.addMenu("Open apps and windows")
        wins.aboutToShow.connect(lambda: self._fill_windows(wins))
        m.exec(self.plus.mapToGlobal(QPoint(0, -m.sizeHint().height() - 6)))

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files or photos", "", "All files (*)")
        self.add_items([att.from_path(p) for p in paths])

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add a folder")
        if d:
            self.add_items([att.folder_listing(d)])

    def paste_clipboard(self):
        md = QApplication.clipboard().mimeData()
        items = att.from_mime(md)
        if not items and md is not None and md.hasText() and md.text().strip():
            items = [att.from_text("clipboard.txt", md.text())]
        if items:
            self.add_items(items)
        else:
            self.add_message("system", "The clipboard is empty.")

    def _fill_tabs(self, menu):
        menu.clear()
        core, tabs, via = self.host.core, [], "ext"
        if core.bridge and core.bridge.connected():
            tabs = core.bridge.tabs()
        elif sys.platform == "darwin":
            tabs, via = sources.mac_tabs(), "mac"
        if tabs:
            for t in tabs[:40]:
                label = ("● " if t.get("active") else "    ") + trunc(t["title"] or t["url"], 58)
                a = menu.addAction(label)
                a.setToolTip(t["url"])
                a.triggered.connect(partial(self.attach_tab, t, via))
        else:
            menu.addAction("No tabs yet. Connect the browser extension...").triggered.connect(self.show_extension_help)
            menu.addAction("Copy the extension token").triggered.connect(self.copy_token)
            menu.addAction("Open the extension folder").triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(EXT_DIR))))

    def attach_tab(self, t, via):
        title = t.get("title") or t.get("url")
        self.add_message("system", f"Reading “{trunc(title, 40)}”...")
        bridge = self.host.core.bridge

        def work():
            if via == "ext":
                text, err = bridge.request_text(t["browser"], t["id"])
            else:
                text, err = sources.fetch_url_text(t["url"])
            if err:
                self.notice.emit(err)
            elif not text.strip():
                self.notice.emit("That tab has no readable text. Try a screenshot instead.")
            self.attachReady.emit(att.from_text(trunc(title, 40), f"Page title: {title}\nURL: {t['url']}\n\n{text}",
                                                kind="webpage"))
        threading.Thread(target=work, daemon=True).start()

    def _fill_windows(self, menu):
        menu.clear()
        wins = sources.list_windows()
        if not wins:
            a = menu.addAction("I can't list windows on this system")
            a.setEnabled(False)
            return
        for w in wins[:40]:
            label = f"{w['app']}  –  {trunc(w['title'], 46)}" if w["app"] and w["title"] else (w["title"] or w["app"])
            menu.addAction(label).triggered.connect(partial(self.attach_window, w))

    def attach_window(self, w):
        self.add_items([att.from_text(trunc(w["title"] or w["app"], 40),
                                      f"The user is pointing at an open window. App: {w['app'] or 'unknown'}. "
                                      f"Window title: {w['title'] or '(none)'}. Only the title is known, not what "
                                      "is inside it; a screenshot would show the contents.", kind="window")])

    def show_extension_help(self):
        self.add_message("system", "To see your browser tabs: open chrome://extensions (or edge://extensions), turn on "
                         "Developer mode, choose Load unpacked, and pick Orion's 'extension' folder. Then click its "
                         "icon and paste the token. Type /token in the chat to see the token.")

    def copy_token(self):
        b = self.host.core.bridge
        if b:
            QApplication.clipboard().setText(b.token)
            self.add_message("system", "Token copied. Paste it into the extension's popup.")

    # ----- messages -----
    def add_message(self, role, text, attachments=None):
        if self._empty is not None:
            self._empty.deleteLater()
            self._empty = None
        row = QWidget()
        col = QVBoxLayout(row)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        align = Qt.AlignRight if role == "user" else Qt.AlignLeft
        for a in attachments or []:
            if a.get("thumb"):
                pm = QPixmap()
                pm.loadFromData(a["thumb"])
                th = QLabel()
                th.setPixmap(pm.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                th.setStyleSheet("border: 1px solid rgba(90,170,255,110); border-radius: 4px; background: transparent;")
                col.addWidget(th, 0, align)
        files = [a["name"] for a in attachments or [] if not a.get("thumb")]
        if files:
            text = (text + "\n" if text else "") + "• " + "\n• ".join(trunc(f, 40) for f in files)
        if text:
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            font = hud_font(11 if role == "system" else 13, italic=role == "system")
            lab.setFont(font)
            style = {"user": f"background: {self.accent}; color: #06122e; border-radius: 6px; padding: 8px 12px;",
                     "system": "background: transparent; color: #7f9cc8; padding: 2px 8px;"
                     }.get(role, "background: rgba(70,150,255,40); color: #eaf3ff; border: 1px solid "
                                 "rgba(90,170,255,70); border-radius: 6px; padding: 8px 12px;")
            lab.setStyleSheet(style)
            w = bubble_width(font, text, 270 if role != "system" else 310)
            lab.setFixedWidth(w)
            pad_x, pad_y = (16, 4) if role == "system" else (26, 18)
            th = QFontMetrics(font).boundingRect(0, 0, w - pad_x, 100000, Qt.TextWordWrap, text).height()
            lab.setFixedHeight(th + pad_y + 4)
            col.addWidget(lab, 0, Qt.AlignHCenter if role == "system" else align)
        self.v.insertWidget(self.v.count() - 1, row)
        QTimer.singleShot(60, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))


def orb_icon(color="#3d8bff"):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    g = QRadialGradient(QPointF(32, 32), 30)
    g.setColorAt(0, rgba(c, 130))
    g.setColorAt(1, rgba(c, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(32, 32), 30, 30)
    p.setBrush(QColor(8, 18, 50))
    p.setPen(QPen(c.lighter(160), 3))
    p.drawEllipse(QPointF(32, 32), 18, 18)
    pts = [QPointF(32 + math.cos(math.radians(k * 45)) * (17 if k % 2 == 0 else 3.5),
                   32 + math.sin(math.radians(k * 45)) * (17 if k % 2 == 0 else 3.5)) for k in range(8)]
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(235, 247, 255))
    p.drawPolygon(QPolygonF(pts))
    p.end()
    return QIcon(pm)


# =====================================================================================================
#  The overlay window
# =====================================================================================================
class Overlay(QWidget):
    CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")

    def __init__(self, cfg, core, ubridge):
        super().__init__()
        u = cfg.get("ui", {})
        self.cfg, self.core, self.ubridge = cfg, core, ubridge
        self.name = cfg.get("assistant_name", "Orion")
        self.accent = u.get("accent", "#5aa8ff")
        self.captions_on = bool(u.get("captions", True))
        self.margin = int(u.get("margin", 24))
        self.corner = u.get("corner", "bottom-right") if u.get("corner") in self.CORNERS else "bottom-right"
        self._emotion, self._state, self._mood_text = "neutral", "idle", ""

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        try:
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        except Exception:
            pass
        self.setWindowOpacity(float(u.get("opacity", 0.98)))
        self.setWindowTitle(self.name)

        self.sounds = Sounds(u.get("sounds", True), u.get("sound_volume", 0.35))
        self.theme = core.mem.jget("ui_theme", None) or u.get("theme", "arc")
        if self.theme not in THEMES:
            self.theme = "arc"
        self.orb = OrbWidget(int(u.get("orb_size", 150)), self.accent, u.get("quality", 1.25))
        self.orb.theme = self.theme
        self.orb.holo.set_theme(self.theme)
        self.accent = THEMES[self.theme][3]
        self._last_active = time.monotonic()
        self._weather_line = ""
        self._boot_text, self._boot_i = "", 0
        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        self.caption.hide()
        self.panel = ChatPanel(self.name, self.accent, core.listen_enabled, self, cfg.get("user_name", ""))
        self.panel.hide()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 14, 14, 14)
        self.lay.setSpacing(6)
        self._relayout()

        self.cap_timer = QTimer(self)
        self.cap_timer.setSingleShot(True)
        self.cap_timer.timeout.connect(self._hide_caption)

        self.orb.clicked.connect(self.toggle_panel)
        self.orb.dragStart.connect(self._drag_start)
        self.orb.dragTo.connect(self._drag_to)
        self.orb.dropped.connect(self._dropped)
        self.panel.sendMessage.connect(core.submit_text)
        self.panel.stopSpeech.connect(core.stop_speaking)
        self.panel.micToggled.connect(core.set_mic_muted)
        self.panel.closeRequested.connect(self.toggle_panel)
        self.orb.setContextMenuPolicy(Qt.CustomContextMenu)
        self.orb.customContextMenuRequested.connect(self._menu)
        ubridge.event.connect(self.on_event)
        self.panel.set_accent(self.accent)

        self.look_timer = QTimer(self)                       # he follows your cursor with his gaze, and gets sleepy when idle
        self.look_timer.timeout.connect(self._look_tick)
        self.look_timer.start(60)
        self.boot_timer = QTimer(self)
        self.boot_timer.timeout.connect(self._boot_step)
        self.hotkey = None
        combo = u.get("hotkey", "<ctrl>+<alt>+o")
        if combo:
            self.hotkey = Hotkey(combo, lambda: ubridge.emit_event("hotkey"))
        QTimer.singleShot(600, lambda: show_on_all_spaces(self))

        self._tray()
        self._fit()
        if u.get("start_expanded", False):
            self.toggle_panel()

    # ----- theme, gaze, boot -----
    def apply_theme(self, name, save=True):
        if name not in THEMES:
            return False
        self.theme = name
        self.accent = THEMES[name][3]
        self.orb.set_theme(name)
        self.panel.set_accent(self.accent)
        if save:
            self.core.mem.jset("ui_theme", name)
        return True

    def _look_tick(self):
        now = time.monotonic()
        scr = self._screen().geometry()
        cur = QCursor.pos()
        c = self.orb.mapToGlobal(self.orb.rect().center())
        dx = (cur.x() - c.x()) / (scr.width() * 0.35)
        dy = (cur.y() - c.y()) / (scr.height() * 0.35)
        if (cur - getattr(self, "_last_cur", cur)).manhattanLength() > 2:
            self._last_active = now
        self._last_cur = cur
        idle = now - self._last_active
        if idle > 25:                                        # nobody around: a slow, curious glance
            dx, dy = 0.5 * math.sin(now * 0.21), 0.3 * math.sin(now * 0.17 + 1)
        self.orb.holo.set_look(dx, -dy)
        hour = time.localtime().tm_hour
        e = 0.62 if (hour >= 23 or hour < 6) else 1.0
        if idle > 600:
            e = min(e, 0.58)                                 # drifts into a dim, slow sleep
        self.orb.holo.energy += (e - self.orb.holo.energy) * 0.02

    def show_boot(self):
        try:
            st = self.core.status()
            m = st["memory"]
            lines = [f"> {self.name.upper()} CORE ONLINE", f"> MEMORY  {m.get('facts', 0)} FACTS  {m.get('notes', 0)} NOTES",
                     f"> BRAIN   {str(st.get('brain', '?')).upper()}", f"> VOICE   {'READY' if st.get('voice') else 'TEXT ONLY'}",
                     f"> MIC     {'LISTENING' if st.get('listening') else 'OFF'}", "> ALL SYSTEMS NOMINAL"]
        except Exception:
            lines = [f"> {self.name.upper()} CORE ONLINE"]
        self._boot_text, self._boot_i = "\n".join(lines), 0
        self.boot_timer.start(22)

    def _boot_step(self):
        self._boot_i += 2
        txt = self._boot_text[:self._boot_i]
        if not self.panel.isVisible():
            font = hud_font(11, 1.2, mono=True)
            self.caption.setFont(font)
            self.caption.setStyleSheet("background: rgba(4,10,26,225); border: 1px solid " + self.accent +
                                       "; border-radius: 4px; padding: 8px 12px; color: #9fe0ff;")
            self.caption.setText(txt + ("█" if self._boot_i < len(self._boot_text) else ""))
            self.caption.setFixedWidth(270)
            fm = QFontMetrics(font)
            self.caption.setFixedHeight(fm.lineSpacing() * (txt.count("\n") + 1) + 22)
            self.caption.show()
            self._fit()
        if self._boot_i >= len(self._boot_text):
            self.boot_timer.stop()
            self.cap_timer.start(3500)

    # ----- layout and position -----
    def _relayout(self):
        for w in (self.panel, self.caption, self.orb):
            self.lay.removeWidget(w)
        order = [self.panel, self.caption, self.orb] if self.corner.startswith("bottom") else \
                [self.orb, self.caption, self.panel]
        align = Qt.AlignRight if self.corner.endswith("right") else Qt.AlignLeft
        for w in order:
            self.lay.addWidget(w, 0, align)

    def _fit(self):
        self.lay.activate()
        self.adjustSize()
        self._place()

    def refit(self):
        self._fit()

    def _screen(self):
        return (QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen())

    def _place(self):
        scr = self._screen().availableGeometry()
        w, h, m = self.width(), self.height(), self.margin
        x = scr.right() - w - m + 1 if self.corner.endswith("right") else scr.left() + m
        y = scr.bottom() - h - m + 1 if self.corner.startswith("bottom") else scr.top() + m
        self.move(x, y)

    def toggle_panel(self):
        show = not self.panel.isVisible()
        if show:
            self._hide_caption()
            avail = self._screen().availableGeometry().height()
            self.orb.set_scale(0.55)                                  # the core shrinks to make room
            self.panel.setFixedHeight(int(max(360, min(560, avail - self.orb.height() - 90))))
        else:
            self.orb.set_scale(1.0)
        self.panel.setVisible(show)
        if show:
            self.panel.input.setFocus()
        self._fit()

    def _drag_start(self, gp):
        self._off = gp - self.frameGeometry().topLeft()

    def _drag_to(self, gp):
        self.move(gp - self._off)

    def _dropped(self, gp):
        scr = (QApplication.screenAt(gp) or QApplication.primaryScreen()).availableGeometry()
        c = scr.center()
        self.corner = f"{'top' if gp.y() < c.y() else 'bottom'}-{'left' if gp.x() < c.x() else 'right'}"
        self._relayout()
        self._fit()

    # ----- drag and drop files onto Orion -----
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or md.hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        items = att.from_mime(e.mimeData())
        if items:
            if not self.panel.isVisible():
                self.toggle_panel()
            self.panel.add_items(items)
            e.acceptProposedAction()

    # ----- screenshots -----
    def take_screenshot(self):
        scr = self._screen()
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(350, lambda: self._grab(scr))

    def _grab(self, scr):
        img = scr.grabWindow(0).toImage()
        self.show()
        self._place()
        stamp = time.strftime("%H-%M-%S")
        self.panel.add_items([att.from_qimage(img, f"screenshot {stamp}.png")])

    # ----- captions -----
    def show_caption(self, text, muted=False):
        if not self.captions_on or self.panel.isVisible() or not text:
            return
        shown = text if len(text) <= 220 else text[:217] + "..."
        font = hud_font(13, italic=muted)
        self.caption.setFont(font)
        self.caption.setStyleSheet(
            "background: rgba(6,13,32,232); border: 1px solid rgba(80,165,255,140); border-radius: 5px; "
            f"padding: 9px 14px; color: {'#9aa6c4' if muted else '#eaf3ff'};")
        self.caption.setText(shown)
        fm = QFontMetrics(font)
        w = max(120, min(330, fm.horizontalAdvance(shown) + 40))
        self.caption.setFixedWidth(w)
        self.caption.setFixedHeight(fm.boundingRect(0, 0, w - 30, 100000, Qt.TextWordWrap, shown).height() + 24)
        self.caption.show()
        self._fit()
        self.cap_timer.start(max(3000, min(14000, len(text) * 70)))

    def _hide_caption(self):
        if self.caption.isVisible():
            self.caption.hide()
            self._fit()

    # ----- events from the engine -----
    def on_event(self, kind, d):
        if kind == "ready":
            self.sounds.play("boot")
            QTimer.singleShot(500, self.show_boot)
        elif kind == "state":
            if d["state"] != self._state:
                self._last_active = time.monotonic()
                if d["state"] == "listening":
                    self.sounds.play("wake")
                elif d["state"] == "thinking":
                    self.sounds.play("think")
            self._state = d["state"]
            self.orb.set_state(self._state)
            self.panel.set_state(self._state, self._mood_text or self._emotion)
        elif kind == "level":
            self.orb.set_level(d["value"], d.get("bands"))
            self.panel.bars.set_level(d["value"])
        elif kind == "hearing":
            self.orb.hear()
            self.orb.holo.shockwave(1)
        elif kind == "mood":
            self._emotion = d["emotion"]
            self._mood_text = d.get("mood", "")
            self.orb.set_emotion(self._emotion)
            self.panel.set_state(self._state, self._mood_text or self._emotion)
        elif kind == "user":
            self.panel.add_message("user", d["text"], d.get("attachments"))
            if d.get("source") == "voice":
                self.show_caption("“" + d["text"] + "”", muted=True)
        elif kind == "assistant":
            self.panel.set_system("OPERATIONAL")
            text = d.get("display") or d.get("speech")
            if text:
                self.panel.add_message("bot", text)
            if d.get("speech"):
                self.show_caption(d["speech"])
        elif kind == "tool":
            self._on_tool(d)
        elif kind == "reminder":
            self.sounds.play("alert")
            self.orb.holo.shockwave(3)
            self.orb.hear()
            if not self.panel.isVisible():
                self.show_caption(d.get("text", ""))
        elif kind == "command":
            self._command(d.get("name"), d.get("arg", ""))
        elif kind == "hotkey":
            self.toggle_panel()
            self.raise_()
            self.activateWindow()
        elif kind == "system":
            self.panel.add_message("system", d.get("text", ""))
            if d.get("level") == "error":
                self.sounds.play("error")
                self.panel.set_system("ATTENTION", ok=False)
                self.show_caption(d.get("text", ""), muted=True)
        elif kind == "confirm":
            ans = QMessageBox.question(self, self.name, d["question"])
            d["result"]["ok"] = ans == QMessageBox.Yes
            d["done"].set()
        elif kind == "quit":
            QApplication.quit()

    TOOL_VERB = {"web_search": "Searching the web", "read_page": "Reading a page", "wikipedia": "Checking Wikipedia",
                 "weather": "Checking the weather", "news": "Reading the news", "arxiv": "Searching papers",
                 "define": "Looking up a word", "exchange": "Converting currency", "calculate": "Calculating",
                 "study": "Studying", "set_timer": "Setting a timer", "set_reminder": "Setting a reminder",
                 "list_reminders": "Checking reminders", "cancel_reminder": "Cancelling a reminder",
                 "briefing": "Gathering your briefing", "remember": "Remembering that", "recall": "Recalling",
                 "forget": "Forgetting", "learn": "Learning from that", "save_note": "Saving a note",
                 "get_time": "Checking the time"}

    def _on_tool(self, d):
        name, args = d.get("name", ""), d.get("args") or {}
        verb = self.TOOL_VERB.get(name, name.replace("_", " ").capitalize())
        detail = next((str(v) for v in args.values() if isinstance(v, str) and v), "")
        line = f"◈ {verb}" + (f": {trunc(detail, 38)}" if detail else "") + (" (failed)" if d.get("error") else "")
        self.panel.add_message("system", line)
        if not self.panel.isVisible():
            self.show_caption(verb + "...", muted=True)
        res = d.get("result")
        if name == "weather" and isinstance(res, dict) and res.get("now"):
            self.panel.add_card(WeatherCard(res, self.accent))
            self._weather_line = f"{res['place'].split(',')[0]}  {res['now']['temperature']}  {res['now']['conditions']}"
            self.panel.status.set_weather(self._weather_line)

    def _command(self, name, arg):
        if name == "theme":
            if not arg:
                self.panel.add_message("system", "Themes: " + ", ".join(THEMES) + f". Now: {self.theme}. Try /theme ember")
            elif self.apply_theme(arg.lower().strip()):
                self.panel.add_message("system", f"Theme set to {self.theme}.")
            else:
                self.panel.add_message("system", "I don't know that theme. Choose from: " + ", ".join(THEMES))
        elif name in ("mind", "status"):
            if not self.panel.isVisible():
                self.toggle_panel()
            self.panel.set_tab(1 if name == "mind" else 2)

    # ----- tray and menu -----
    def _tray(self):
        self.tray = QSystemTrayIcon(orb_icon(), self)
        self.tray.setToolTip(self.name)
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(lambda r: self.toggle_panel() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _build_menu(self):
        m = QMenu()
        m.setStyleSheet(MENU_QSS)
        m.addAction("Show / hide chat", self.toggle_panel)
        m.addAction("Stop talking", self.core.stop_speaking)
        if self.core.listen_enabled:
            act = QAction("Mute microphone", m, checkable=True)
            act.toggled.connect(self.core.set_mic_muted)
            m.addAction(act)
        themes = m.addMenu("Theme")
        for t in THEMES:
            themes.addAction(t.capitalize(), lambda t=t: self.apply_theme(t))
        m.addAction("Mind (memory star-map)", lambda: self._command("mind", ""))
        m.addAction("Status", lambda: self._command("status", ""))
        corner = m.addMenu("Move to corner")
        for c in self.CORNERS:
            corner.addAction(c.replace("-", " "), lambda c=c: self._set_corner(c))
        m.addSeparator()
        m.addAction("Quit (saves what I learned)", self.quit_app)
        return m

    def _menu(self, pos):
        self._ctx = self._build_menu()
        self._ctx.exec(self.orb.mapToGlobal(pos))

    def _set_corner(self, c):
        self.corner = c
        self._relayout()
        self._fit()

    def quit_app(self):
        self.show_caption("Saving what I learned...", muted=True)
        QTimer.singleShot(45000, QApplication.quit)            # never hang on exit
        self.core.shutdown_async(done=lambda: self.ubridge.emit_event("quit"))


def run_ui(cfg):
    from .core import Core
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(cfg.get("assistant_name", "Orion"))
    mac_menubar_app()
    ubridge = UiBridge()

    def confirm(question):
        done, result = threading.Event(), {"ok": False}
        ubridge.emit_event("confirm", question=question, done=done, result=result)
        done.wait(120)
        return result["ok"]

    core = Core(cfg, ubridge.emit_event, confirm=confirm)
    overlay = Overlay(cfg, core, ubridge)
    overlay.show()
    core.start()
    code = app.exec()
    core.shutdown()
    return code
