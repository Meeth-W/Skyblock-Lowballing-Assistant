"""Design tokens and the stylesheet built from them.

A near-black canvas with off-white text and no colour of its own. Every
saturated pixel on screen therefore means something: rarity on an item name,
green or red on a figure that moved. Nothing is tinted for decoration.

The interface is still a workbench rather than a dashboard. The user is
standing on their island with a customer waiting, glancing at this window for
two seconds to read one number out loud, so density and legibility come first
and the chrome stays out of the way.

Structure comes from one-step background shifts and 1px hairlines. No cards, no
shadows, no gradients. Radius is 4px and only on controls.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"

# ---- palette ---------------------------------------------------------------

CANVAS = "#09090B"
SURFACE = "#111113"
SURFACE_HIGH = "#1A1A1E"
SURFACE_RAISED = "#232329"
HAIRLINE = "#27272A"
HAIRLINE_STRONG = "#3F3F46"
INK = "#FAFAFA"
INK_DIM = "#A1A1AA"
INK_FAINT = "#71717A"

#: The one interactive accent, and it is simply light. Selection, focus and
#: the primary action read as brightness rather than as a hue, which keeps
#: colour meaning what it means everywhere else.
ACCENT = "#FAFAFA"
ACCENT_MUTED = "#52525B"

GAIN = "#4ADE80"
LOSS = "#F87171"
WARN = "#FBBF24"

#: Semantic colour comes from SkyBlock's own rarity system, which the user
#: already reads instinctively. This is the one place the design borrows from
#: the game, and it earns the borrow: it encodes real information faster than
#: text does.
RARITY_COLOURS: dict[str, str] = {
    "COMMON": "#D4D4D8",
    "UNCOMMON": "#4ADE80",
    "RARE": "#60A5FA",
    "EPIC": "#C084FC",
    "LEGENDARY": "#FBBF24",
    "MYTHIC": "#F472B6",
    "DIVINE": "#67E8F9",
    "SPECIAL": "#FB7185",
    "VERY SPECIAL": "#FB7185",
}


def rarity_colour(rarity: str | None) -> str:
    return RARITY_COLOURS.get((rarity or "").upper(), INK_DIM)


def qcolor(value: str) -> QColor:
    return QColor(value)


# ---- type ------------------------------------------------------------------

UI_FAMILY_PREFERENCE = (
    "Inter",
    "Instrument Sans",
    "SF Pro Text",
    "Segoe UI Variable",
    "Segoe UI",
    "sans-serif",
)

#: Numerals, and only where digits must line up: the offer ladder, the ledger
#: tables, the statistics figures. Never on labels, headings or prose.
NUM_FAMILY_PREFERENCE = (
    "JetBrains Mono",
    "Recursive Mono Linear Static",
    "SF Mono",
    "Cascadia Mono",
    "Consolas",
    "monospace",
)

SIZE_MICRO = 11
SIZE_BODY = 13
SIZE_EMPHASIS = 15
SIZE_SECTION = 19
SIZE_FIGURE = 40

WEIGHT_BODY = QFont.Weight.Normal
WEIGHT_EMPHASIS = QFont.Weight.Medium
WEIGHT_FIGURE = QFont.Weight.DemiBold

#: Spacing is on a 4px grid throughout.
GRID = 4

RADIUS = 4

#: Motion happens only in response to a user action.
MOTION_MS = 140


_loaded: dict[str, str] = {}


def _first_available(preference: tuple[str, ...], fallback: str) -> str:
    families = set(QFontDatabase.families())
    for family in preference:
        if family in families:
            return family
    return fallback


def load_fonts() -> dict[str, str]:
    """Register bundled fonts and resolve the family names to use.

    Any .ttf dropped into ``ui/assets/fonts`` is picked up. Without them the
    app falls back to a system stack rather than refusing to start, which
    matters more than the typography does.
    """
    global _loaded
    if _loaded:
        return _loaded

    if FONT_DIR.is_dir():
        for path in sorted(FONT_DIR.glob("*.tt[fc]")) + sorted(FONT_DIR.glob("*.otf")):
            QFontDatabase.addApplicationFont(str(path))

    _loaded = {
        "ui": _first_available(UI_FAMILY_PREFERENCE, "sans-serif"),
        "num": _first_available(NUM_FAMILY_PREFERENCE, "monospace"),
    }
    return _loaded


def ui_font(size: int = SIZE_BODY, weight: QFont.Weight = WEIGHT_BODY) -> QFont:
    font = QFont(load_fonts()["ui"], size)
    font.setWeight(weight)
    return font


def numeric_font(size: int = SIZE_BODY, weight: QFont.Weight = WEIGHT_BODY) -> QFont:
    """Tabular figures, so columns of coins line up digit for digit."""
    font = QFont(load_fonts()["num"], size)
    font.setWeight(weight)
    font.setStyleHint(QFont.StyleHint.Monospace)
    # Older Qt has no font-feature API; a monospace fallback is already
    # tabular, so there is nothing to lose when this is unavailable.
    with contextlib.suppress(AttributeError, ValueError, TypeError):
        font.setFeature(QFont.Tag("tnum"), 1)
    return font




def stylesheet() -> str:
    """The application stylesheet, built from the tokens above."""
    families = load_fonts()
    return _BASE.format(**_tokens(families)) + _CONTROLS.format(**_tokens(families))


def _tokens(families: dict[str, str]) -> dict[str, object]:
    return {
        "canvas": CANVAS,
        "surface": SURFACE,
        "surface_high": SURFACE_HIGH,
        "surface_raised": SURFACE_RAISED,
        "hairline": HAIRLINE,
        "hairline_strong": HAIRLINE_STRONG,
        "ink": INK,
        "ink_dim": INK_DIM,
        "ink_faint": INK_FAINT,
        "accent": ACCENT,
        "accent_muted": ACCENT_MUTED,
        "gain": GAIN,
        "loss": LOSS,
        "radius": RADIUS,
        "micro": SIZE_MICRO,
        "body": SIZE_BODY,
        "figure": SIZE_FIGURE,
        "ui": families["ui"],
        "num": families["num"],
    }


_BASE = """
QWidget {{
    background: {canvas};
    color: {ink};
    font-family: "{ui}";
    font-size: {body}px;
}}
QMainWindow, QDialog {{ background: {canvas}; }}

QFrame#panel {{ background: {surface}; border: none; }}
QFrame#hairline {{ background: {hairline}; border: none; max-height: 1px; }}
QFrame#vhairline {{ background: {hairline}; border: none; max-width: 1px; }}

QLabel {{ background: transparent; }}
QLabel#sectionLabel {{ color: {ink_faint}; font-size: {micro}px; font-weight: 500; }}
QLabel#dim {{ color: {ink_dim}; }}
QLabel#faint {{ color: {ink_faint}; }}
QLabel#figure {{
    color: {ink};
    font-family: "{num}";
    font-size: {figure}px;
    font-weight: 600;
}}
QLabel#figureLowConfidence {{
    color: {ink_dim};
    font-family: "{num}";
    font-size: {figure}px;
    font-weight: 600;
}}
QLabel#numeric {{ font-family: "{num}"; }}
QLabel#gain {{ color: {gain}; font-family: "{num}"; }}
QLabel#loss {{ color: {loss}; font-family: "{num}"; }}

QTableView, QTreeView, QListView {{
    background: {surface};
    alternate-background-color: {surface};
    gridline-color: {hairline};
    border: none;
    selection-background-color: {surface_raised};
    selection-color: {ink};
    outline: none;
}}
QTableView::item, QTreeView::item {{ padding: 6px 10px; border: none; }}
QHeaderView::section {{
    background: {canvas};
    color: {ink_faint};
    border: none;
    border-bottom: 1px solid {hairline};
    padding: 8px 10px;
    font-size: {micro}px;
    font-weight: 500;
}}
QTableCornerButton::section {{ background: {canvas}; border: none; }}
"""


_CONTROLS = """
QPushButton {{
    background: {surface_high};
    color: {ink};
    border: 1px solid {hairline};
    border-radius: {radius}px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {surface_raised}; border-color: {hairline_strong}; }}
QPushButton:pressed {{ background: {surface}; }}
QPushButton:disabled {{ color: {ink_faint}; background: {surface}; }}
QPushButton#primary {{
    background: {accent};
    color: {canvas};
    border: 1px solid {accent};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: #FFFFFF; }}
QPushButton#primary:disabled {{ background: {accent_muted}; border-color: {accent_muted}; }}
QPushButton#danger {{ color: {loss}; }}
QPushButton#ghost {{ background: transparent; border-color: transparent; color: {ink_dim}; }}
QPushButton#ghost:hover {{ background: {surface_high}; color: {ink}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {surface_high};
    border: 1px solid {hairline};
    border-radius: {radius}px;
    padding: 6px 9px;
    selection-background-color: {accent};
    selection-color: {canvas};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {hairline_strong}; }}
QLineEdit#numericInput, QPlainTextEdit#code {{ font-family: "{num}"; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {surface_high};
    border: 1px solid {hairline};
    selection-background-color: {surface_raised};
    outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {hairline_strong};
    border-radius: 3px;
    background: {surface_high};
}}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {hairline}; }}
QTabBar::tab {{
    background: transparent;
    color: {ink_faint};
    padding: 10px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:selected {{ color: {ink}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover:!selected {{ color: {ink_dim}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {hairline_strong}; min-height: 28px; border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{ background: {ink_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {hairline_strong}; min-width: 28px; border-radius: 5px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {surface_raised};
    color: {ink};
    border: 1px solid {hairline_strong};
    padding: 6px 8px;
}}
QSplitter::handle {{ background: {hairline}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {canvas}; border-top: 1px solid {hairline}; }}
QStatusBar::item {{ border: none; }}
"""
