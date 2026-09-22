"""How the trainer looks: light, warm and roomy, where the request manager is dark and dense.

The request manager is a tool used every day by somebody who knows it, and packs a lot in.
The trainer is the first thing a new Puppet Master sees of Skedge, so it takes the other
approach: one thing at a time, big type, soft colours and a lot of air.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

PAPER = "#fbf6ee"  # the window: warm off-white, like a camp notebook
CARD = "#ffffff"
SUNKEN = "#fffdf8"  # the editor
LINE = "#eadfcd"
INK = "#2d3142"
SOFT = "#6b7080"
ACCENT = "#2a9d8f"  # lake teal: the thing to press
ACCENT_DARK = "#1f7a6f"
SUN = "#f4a261"  # a try, a hint
BERRY = "#d1495b"  # not quite
LEAF = "#40916c"  # solved
LEAF_BG = "#e3f4ea"
SUN_BG = "#fff1e0"
BERRY_BG = "#fde8ea"
SKY = "#e8f3f6"  # the camp's speech bubble
CAMP_DAY = "#d9efe9"
HIGHLIGHT = "#bfe3dc"

# Skedge colouring on a light page
KEYWORD = "#1d6f66"
NAME = "#6a4c93"
STRING = "#c0572f"
NUMBER = "#9c6644"
COMMENT = "#9a9a9a"


def apply(app: QApplication) -> None:
    """Dress the application in the trainer's colours, whatever the desktop theme."""
    app.setStyle("Fusion")
    colours = QPalette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        writing = QColor(SOFT if group == QPalette.Disabled else INK)
        colours.setColor(group, QPalette.Window, QColor(PAPER))
        colours.setColor(group, QPalette.Base, QColor(CARD))
        colours.setColor(group, QPalette.AlternateBase, QColor(PAPER))
        colours.setColor(group, QPalette.Button, QColor(CARD))
        colours.setColor(group, QPalette.ToolTipBase, QColor(CARD))
        colours.setColor(group, QPalette.ToolTipText, QColor(INK))
        colours.setColor(group, QPalette.WindowText, writing)
        colours.setColor(group, QPalette.Text, writing)
        colours.setColor(group, QPalette.ButtonText, writing)
        colours.setColor(group, QPalette.PlaceholderText, QColor(SOFT))
        colours.setColor(group, QPalette.Highlight, QColor(HIGHLIGHT))
        colours.setColor(group, QPalette.HighlightedText, QColor(INK))
        colours.setColor(group, QPalette.Link, QColor(ACCENT_DARK))
    app.setPalette(colours)
    font = QFont(app.font())
    font.setPointSizeF(max(font.pointSizeF(), 10.5))
    app.setFont(font)
    app.setStyleSheet(SHEET)


SHEET = f"""
QMainWindow, QDialog {{ background: {PAPER}; }}
QLabel {{ color: {INK}; }}
QLabel[role="soft"] {{ color: {SOFT}; }}
QLabel[role="title"] {{ font-size: 20pt; font-weight: 600; }}
QLabel[role="level"] {{ color: {ACCENT_DARK}; font-weight: 600; letter-spacing: 1px; }}
QLabel[role="chip"] {{
    background: {PAPER}; border: 1px solid {LINE}; border-radius: 10px;
    padding: 2px 10px; color: {SOFT};
}}
QLabel[role="bubble"] {{
    background: {SKY}; border-radius: 14px; padding: 14px 18px; font-size: 13pt;
}}
QFrame[role="card"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 16px; }}
QFrame[role="good"] {{ background: {LEAF_BG}; border: 1px solid {LEAF}; border-radius: 14px; }}
QFrame[role="hint"] {{ background: {SUN_BG}; border: 1px solid {SUN}; border-radius: 14px; }}
QFrame[role="bad"] {{ background: {BERRY_BG}; border: 1px solid {BERRY}; border-radius: 14px; }}
QFrame[role="sheet"] {{ background: {PAPER}; border: 1px dashed {LINE}; border-radius: 12px; }}
QPushButton {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 16px;
    padding: 7px 18px; color: {INK};
}}
QPushButton:hover {{ background: {PAPER}; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {SOFT}; background: {PAPER}; }}
QPushButton[role="primary"] {{
    background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 8px 24px;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_DARK}; }}
QPushButton[role="primary"]:disabled {{ background: {HIGHLIGHT}; color: white; }}
QPushButton[role="link"] {{ border: none; background: transparent; color: {ACCENT_DARK}; }}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}
QPlainTextEdit {{
    background: {SUNKEN}; border: 2px solid {LINE}; border-radius: 12px; padding: 8px;
    font-size: 12pt; selection-background-color: {HIGHLIGHT};
}}
QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: 5px 10px;
}}
QTreeWidget, QTableWidget {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; outline: none;
}}
QTreeWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected {{ background: {HIGHLIGHT}; color: {INK}; border-radius: 0; }}
QHeaderView::section {{
    background: {PAPER}; color: {SOFT}; border: none; border-bottom: 1px solid {LINE};
    padding: 4px 6px;
}}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {SOFT}; padding: 6px 14px; border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ACCENT}; }}
QProgressBar {{
    background: {LINE}; border: none; border-radius: 5px; height: 10px; text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {LEAF}; border-radius: 5px; }}
QSplitter::handle {{ background: {PAPER}; }}
QScrollArea {{ border: none; background: {PAPER}; }}
QScrollArea > QWidget > QWidget {{ background: {PAPER}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {CARD}; }}
QCalendarWidget QToolButton {{
    color: {INK}; background: transparent; border: none; padding: 4px 8px;
}}
QCalendarWidget QToolButton:hover {{ background: {PAPER}; border-radius: 6px; }}
QToolTip {{ background: {CARD}; color: {INK}; border: 1px solid {LINE}; }}
"""
