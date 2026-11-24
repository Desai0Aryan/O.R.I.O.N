"""Small drawing helpers shared by the UI modules."""
from PySide6.QtGui import QColor, QFont, QPen

HUD_FONTS = ["Bahnschrift", "Segoe UI", "SF Pro Display", "Helvetica Neue", "Arial"]
MONO_FONTS = ["SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "Courier New"]


def rgba(c, a):
    q = QColor(c)
    q.setAlpha(max(0, min(255, int(a))))
    return q


def lerp(a, b, k):
    return QColor(int(a.red() + (b.red() - a.red()) * k), int(a.green() + (b.green() - a.green()) * k),
                  int(a.blue() + (b.blue() - a.blue()) * k))


def cpen(color, width):
    p = QPen(color, width)
    p.setCosmetic(True)
    return p


def hud_font(px, spacing=0.0, weight=QFont.Normal, italic=False, mono=False):
    f = QFont()
    f.setFamilies(MONO_FONTS if mono else HUD_FONTS)
    f.setPixelSize(px)
    if isinstance(weight, int) and not isinstance(weight, QFont.Weight):      # 300 / 600 style numbers
        weight = QFont.Light if weight < 400 else QFont.DemiBold if weight >= 600 else QFont.Normal
    f.setWeight(weight)
    f.setItalic(italic)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


# the colour of each kind of memory in the star map
CATEGORY_COLORS = {"identity": "#ffd479", "work": "#6fb4ff", "people": "#ff8fcf", "preference": "#7dffb0",
                   "goal": "#b58cff", "routine": "#5ee6e0", "interest": "#ffa05c", "learned": "#e6f2ff",
                   "other": "#8a9bb8", "general": "#8a9bb8"}
