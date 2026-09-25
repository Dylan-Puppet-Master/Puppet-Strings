"""The colours the window uses, in one place, as plain strings.

The window is a dark one, and `apply` below is what makes it so: it dresses the whole
application in the colours named here rather than leaving the chrome to whatever theme the
machine happens to run. That is what lets every colour below be chosen once, against one
known background, instead of having to read well on a light desktop and a dark one both.

Three of them carry meaning rather than decoration and are used in more than one pane:
`GOOD` for a request that is valid or saved, `BAD` for one that is broken or contradicted,
and `QUIET` for a note beside either. Keeping them here is what makes the red under the
editor and the red in the conflicts pane the same red.
"""

from itertools import product

from PySide6.QtCore import QPointF, Qt, QTemporaryDir
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPolygonF
from PySide6.QtWidgets import QApplication

# The chrome: three depths of near-black, with the panes sitting a shade above the window
# and anything you can type into sitting a shade below it.
WINDOW = "#1e2126"  # the window and its docks
SURFACE = "#252a31"  # a pane, a list, a tree, a table
SUNKEN = "#181b1f"  # an editor, a text field, a drop-down
ROW = "#22262c"  # the every-other row of a table
LINE = "#343b44"  # a grid line, a border, the edge between two panes
TEXT = "#e4e7eb"  # ordinary writing
HIGHLIGHT = "#3d6fb5"  # the selected row, and what is written on it
ON_HIGHLIGHT = "#ffffff"

# Anything painted on one of the shadings below must be painted with INK as well. Qt takes
# the text colour from the palette otherwise, which is right for a pane but not for a cell
# that has been given a colour of its own.
INK = "#f2f4f7"  # what to write on any of the shadings

GOOD = "#5fd08a"  # valid, saved, a camp day
BAD = "#ff7b86"  # an error, a contradiction
QUIET = "#98a2b0"  # a note, a reason, anything said in passing

# A span shades every day between its ends, so this is a large block of colour rather than
# a sprinkle: a lift out of the surface reads as a camp day without shouting, and the clash
# is the same lift carrying a red in it.
CAMP_DAY = "#33424f"  # the calendar's shading for a day the Calendar sheet covers
CLASH = "#4a2d34"  # the conflicts pane's shading for one collision

# the Skedge editor's highlighting, which is decoration rather than meaning
KEYWORD = "#7aa7ec"
NAME = GOOD
STRING = "#e0a065"
NUMBER = "#c79bea"
COMMENT = "#7e8794"


def apply(app: QApplication) -> None:
    """Dress the application in the colours above.

    Fusion is the one style that takes a palette whole; a native style paints some of its
    chrome from the desktop theme whatever the palette says, which is how a light strip
    ends up across a dark window.
    """
    app.setStyle("Fusion")
    colours = QPalette()
    for group, dim in (
        (QPalette.Active, False),
        (QPalette.Inactive, False),
        (QPalette.Disabled, True),
    ):
        writing = QColor(QUIET) if dim else QColor(TEXT)
        colours.setColor(group, QPalette.Window, QColor(WINDOW))
        # Base is what every view paints itself with. It is set by the palette rather than
        # by the sheet below because a stylesheet background on a view overrides the
        # colours single cells are given, which is how the calendar loses its camp days.
        colours.setColor(group, QPalette.Base, QColor(SURFACE))
        colours.setColor(group, QPalette.AlternateBase, QColor(ROW))
        colours.setColor(group, QPalette.Button, QColor(SURFACE))
        colours.setColor(group, QPalette.ToolTipBase, QColor(SURFACE))
        colours.setColor(group, QPalette.WindowText, writing)
        colours.setColor(group, QPalette.Text, writing)
        colours.setColor(group, QPalette.ButtonText, writing)
        colours.setColor(group, QPalette.ToolTipText, QColor(TEXT))
        colours.setColor(group, QPalette.PlaceholderText, QColor(QUIET))
        colours.setColor(group, QPalette.BrightText, QColor(BAD))
        colours.setColor(group, QPalette.Link, QColor(KEYWORD))
        colours.setColor(group, QPalette.Highlight, QColor(LINE if dim else HIGHLIGHT))
        colours.setColor(group, QPalette.HighlightedText, QColor(ON_HIGHLIGHT))
        colours.setColor(group, QPalette.Mid, QColor(LINE))
    app.setPalette(colours)
    app.setStyleSheet(SHEET + _arrows_sheet())


# Where the spin boxes' arrows are drawn to, kept for as long as the application runs.
_ARROW_DIR: QTemporaryDir | None = None


def _arrows_sheet() -> str:
    """The up and down arrows of every spin box, drawn in TEXT, and in QUIET at either end.

    A sheet that gives a spin box a border takes over its buttons as well, and Fusion then
    paints their arrows near-black on near-black. A sheet can only give an arrow back as an
    image, so the two are drawn here, once, rather than shipped as files.
    """
    global _ARROW_DIR
    if _ARROW_DIR is None:
        _ARROW_DIR = QTemporaryDir()
    folder = _ARROW_DIR.path()
    shapes = (("up", ((0, 4), (8, 4), (4, 0))), ("down", ((0, 0), (8, 0), (4, 4))))
    for (name, points), (colour, dim) in product(shapes, ((TEXT, ""), (QUIET, "-off"))):
        for scale, suffix in ((1, ""), (2, "@2x")):
            image = QImage(9 * scale, 5 * scale, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colour))
            painter.drawPolygon(
                QPolygonF([QPointF((x + 0.5) * scale, (y + 0.5) * scale) for x, y in points])
            )
            painter.end()
            image.save(f"{folder}/{name}{dim}{suffix}.png")
    return f"""
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    background: {SURFACE};
    border-left: 1px solid {LINE};
    width: 16px;
}}
QAbstractSpinBox::up-button {{ border-top-right-radius: 3px; }}
QAbstractSpinBox::down-button {{ border-bottom-right-radius: 3px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {LINE}; }}
QAbstractSpinBox::up-arrow {{ image: url({folder}/up.png); }}
QAbstractSpinBox::down-arrow {{ image: url({folder}/down.png); }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{
    image: url({folder}/up-off.png);
}}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{
    image: url({folder}/down-off.png);
}}
"""


# What the palette alone does not reach: the borders and paddings, the splitter and dock
# edges, and the calendar's navigation bar, which Qt builds out of a tool button and two
# spin boxes of its own and leaves untouched by the palette. Nothing here sets the
# background of a view; see Base above for why.
SHEET = f"""
QAbstractItemView {{ outline: none; }}
QHeaderView::section {{
    background: {WINDOW};
    color: {QUIET};
    border: none;
    border-bottom: 1px solid {LINE};
    padding: 4px 6px;
}}
QTableView QTableCornerButton::section {{ background: {WINDOW}; border: none; }}
QTreeView::item, QListView::item {{ padding: 2px 0; }}
QSplitter::handle {{ background: {LINE}; }}
QDockWidget::title {{
    background: {WINDOW};
    color: {QUIET};
    border-bottom: 1px solid {LINE};
    padding: 5px 8px;
}}
/* The tabs over docks that share a place (Errors and Messages): flat, with the one
   picked underlined, and no line along the bar, which Fusion breaks under that tab. */
QMainWindow > QTabBar {{ background: {WINDOW}; qproperty-drawBase: 0; }}
QMainWindow > QTabBar::tab {{
    background: {WINDOW};
    color: {QUIET};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 5px 12px;
}}
QMainWindow > QTabBar::tab:hover {{ color: {TEXT}; }}
QMainWindow > QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {HIGHLIGHT}; }}
QToolBar {{ background: {WINDOW}; border-bottom: 1px solid {LINE}; spacing: 4px; }}
QToolBar QToolButton:hover, QPushButton:hover {{ background: {LINE}; }}
QPushButton {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 3px;
    padding: 4px 12px;
}}
QPushButton:disabled {{ color: {QUIET}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background: {SUNKEN};
    border: 1px solid {LINE};
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: {HIGHLIGHT};
}}
QComboBox QAbstractItemView {{ background: {SUNKEN}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {WINDOW};
    border-bottom: 1px solid {LINE};
}}
QCalendarWidget QToolButton {{
    background: transparent;
    color: {TEXT};
    border: none;
    padding: 4px 8px;
}}
QCalendarWidget QToolButton:hover {{ background: {LINE}; border-radius: 3px; }}
QCalendarWidget QMenu {{ background: {SURFACE}; }}
QCalendarWidget QSpinBox {{ background: {SUNKEN}; color: {TEXT}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {LINE}; }}
"""
