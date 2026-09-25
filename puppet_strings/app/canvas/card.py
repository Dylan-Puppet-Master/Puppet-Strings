"""A request as a card on the canvas: painted when looked at, a live form when clicked.

A season holds hundreds of requests, and a real widget per field per card is thousands of
widgets redrawn at every step of a zoom. So a card is painted — its text, its Skedge in
colour, its tags and status — and only the card being edited carries widgets: the one
`CardEditor` there is moves onto whichever card is clicked, with its fields where the
painted ones were, so clicking a card is the same as starting to type on it.

How much of a card is painted depends on how far away it is. Close up it is everything
the editor shows; further out, the id and the description written large enough to read;
from far away, a block of its priority's colour, which is enough to see the shape of a
group and find the one wanted.
"""

from dataclasses import dataclass
from math import acos, degrees, sqrt

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QTextCursor,
    QTextDocument,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QGraphicsItem,
    QGraphicsObject,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app import palette
from puppet_strings.app.canvas.layout import CARD_WIDTH
from puppet_strings.app.editor import RequestEditor, SkedgeHighlighter
from puppet_strings.model import Priority, Request
from puppet_strings.requests_db import describe

INSET = 16.0  # between a card's edge and what is written on it
RADIUS = 12.0
STRIPE = 4.0  # the priority's colour down the left-hand edge
INNER = CARD_WIDTH - 2 * INSET
CODE_PAD = 10.0  # between the Skedge block's edge and the Skedge
LABEL_WIDTH = 82.0  # the SCOPE / REQUESTER / CREATED column

# what each priority is painted in: the stripe, the chip, the block seen from far away
PRIORITY_COLOURS = {
    Priority.MUST_HAPPEN: palette.BAD,
    Priority.CLINIC: palette.NUMBER,
    Priority.STABILITY: palette.GOOD,
    Priority.HIGH: palette.STRING,
    Priority.MEDIUM: palette.KEYWORD,
    Priority.LOW: palette.QUIET,
}
PRIORITY_NAMES = {
    Priority.MUST_HAPPEN: "MUST HAPPEN",
    Priority.CLINIC: "CLINIC",
    Priority.STABILITY: "STABILITY",
    Priority.HIGH: "HIGH",
    Priority.MEDIUM: "MEDIUM",
    Priority.LOW: "LOW",
}

WARN = palette.STRING
CARD = QColor(palette.SURFACE)
CODE = QColor(palette.SUNKEN)
EDGE = QColor(palette.LINE)
SELECTED = QColor(palette.HIGHLIGHT).lighter(135)

# How near a card has to be, in screen pixels per canvas unit (the zoom: 0.7 is 70%), to
# be painted in full; and nearer than what to be painted as more than a block of colour.
# Between the two it is the middle distance: its priority and description, written large.
# A group's frame shows its full header from FULL_DETAIL in too.
FULL_DETAIL = 0.7
SUMMARY = 0.2

# the states a card's status line can be in, and the colour of its dot
OK, BAD, WARNING, NOTE, UNSAVED = "ok", "bad", "warning", "note", "unsaved"
STATUS_COLOURS = {
    OK: palette.GOOD,
    BAD: palette.BAD,
    WARNING: WARN,
    NOTE: palette.QUIET,
    UNSAVED: WARN,
}


def _font(pixels: float, weight=QFont.Normal, mono: bool = False, spacing: float = 0) -> QFont:
    font = QFont("monospace") if mono else QFont()
    if mono:
        font.setStyleHint(QFont.Monospace)
    font.setPixelSize(round(pixels))
    font.setHintingPreference(QFont.PreferNoHinting)  # so text keeps its width at any zoom
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


ID_FONT = _font(11, mono=True)
CHIP_FONT = _font(10, QFont.Bold, spacing=0.6)
TITLE_FONT = _font(15, QFont.DemiBold)
CODE_FONT = _font(12, mono=True)
TAG_FONT = _font(11)
LABEL_FONT = _font(9.5, QFont.DemiBold, spacing=0.9)
VALUE_FONT = _font(12)
STATUS_FONT = _font(11)

# The middle distance writes its words this many times their size close up, and at that
# size on the card whatever the zoom; see `CardItem._paint_summary`.
SUMMARY_SCALE = 2.5
SUMMARY_CHIP_FONT = _font(10 * SUMMARY_SCALE, QFont.Bold, spacing=0.6 * SUMMARY_SCALE)
SUMMARY_TITLE_FONT = _font(14 * SUMMARY_SCALE, QFont.DemiBold)


@dataclass(frozen=True)
class Status:
    """What a card's bottom line says, and how it says it."""

    kind: str
    text: str


def priority_colour(priority: Priority) -> QColor:
    """The colour a priority is painted in."""
    return QColor(PRIORITY_COLOURS.get(priority, palette.QUIET))


def _block_colour(priority: Priority, picked: bool) -> QColor:
    colour = priority_colour(priority)
    colour.setAlpha(150 if picked else 95)
    return colour


# made once rather than for each card at each frame, as hundreds are painted from far out
BLOCK_COLOURS = {(p, picked): _block_colour(p, picked) for p in Priority for picked in (0, 1)}
DOT_COLOURS = {kind: QColor(colour) for kind, colour in STATUS_COLOURS.items()}


def _fitted(text: str, font: QFont, width: float, height: float) -> str:
    """As much of a paragraph as fits in whole lines, wrapped to a width, ending in "…" if cut.

    A line cut through the middle by the bottom of the card reads worse than one fewer.
    """
    metrics = QFontMetricsF(font)
    room = max(int(height // metrics.lineSpacing()), 1)
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WordWrap)
    layout.setTextOption(option)
    starts = []
    layout.beginLayout()
    while (line := layout.createLine()).isValid():
        line.setLineWidth(width)
        starts.append(line.textStart())
    layout.endLayout()
    if len(starts) <= room:
        return text
    start = starts[room - 1]
    return text[:start] + metrics.elidedText(text[start:], Qt.ElideRight, width)


def _wrapped(text: str, font: QFont, width: float, lines: int | None = None) -> float:
    """How tall a paragraph is, wrapped to a width, at most `lines` lines of it."""
    metrics = QFontMetricsF(font)
    height = metrics.boundingRect(QRectF(0, 0, width, 1e6), Qt.TextWordWrap, text).height()
    return min(height, lines * metrics.lineSpacing()) if lines else height


class CardItem(QGraphicsObject):
    """One request on the canvas.

    `request` is the request as saved; `draft` is what the card has been changed to and not
    yet saved, if anything, and is what the card shows. A new card has no request yet, only
    a draft, and a key of its own until saving gives it an id.
    """

    def __init__(self, key: str, request: Request | None, draft: Request | None = None) -> None:
        super().__init__()
        self.key = key
        self.request = request
        self.draft = draft
        self.status = Status(NOTE, "")
        self.editing = False
        self.hovered = False
        self.placed = False  # put in its spot yet, so later moves glide rather than jump
        # Made here, on the canvas: the how-manyeth, which is where it stays in its frame,
        # saved or not, until the canvas lets it go (see `Canvas.relayout`). None otherwise.
        self.kept: int | None = None
        self.editor_height = 0.0  # while editing, how tall the form on the card is
        self.regions: dict[str, QRectF] = {}  # where each field is painted, for a click to find
        self.code = QTextDocument()
        self.code.setDefaultFont(CODE_FONT)
        self.code.setDocumentMargin(0)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.code.setDefaultTextOption(option)
        self.highlighter = SkedgeHighlighter(self.code)
        self.height = 0.0
        self.face = self.bounds = QRectF()
        self.summary = ""  # the description as the middle distance shows it; see `measure`
        self.stripe = QPainterPath()
        self.stripe_for = None  # the height `stripe` was built for
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.measure()

    @property
    def shown(self) -> Request:
        """What the card shows: its unsaved changes if there are any, else the request."""
        return self.draft or self.request

    @property
    def request_id(self) -> str | None:
        """The id of the request as saved, or None for a card never saved."""
        return self.request.id if self.request else None

    def set_request(self, request: Request) -> None:
        """Show the request as it now stands in the store."""
        if request != self.request:
            self.request = request
            self.measure()

    def set_draft(self, draft: Request | None) -> None:
        """Keep unsaved changes on the card, or drop them."""
        self.draft = None if draft == self.request else draft
        self.measure()

    def set_status(self, status: Status) -> None:
        """Say how the request stands: valid, broken, clashing, or unsaved."""
        if status != self.status:
            self.status = status
            self.measure()

    def set_editing(self, editing: bool, height: float = 0.0) -> None:
        """Make room for the form while it is on this card, or paint the fields again."""
        self.editing = editing
        self.editor_height = height
        self.measure()

    # -- the shape of the card ----------------------------------------------------------

    def measure(self) -> None:
        """Work out where each field goes, and so how tall the card is."""
        self.prepareGeometryChange()
        if self.editing:
            self._set_height(self.editor_height + 2 * INSET)
            return
        request = self.shown
        regions = {}
        y = INSET
        regions["header"] = QRectF(INSET, y, INNER, 20)
        y += 28
        title = request.description or "Untitled request"
        high = _wrapped(title, TITLE_FONT, INNER)
        regions["description"] = QRectF(INSET, y, INNER, high)
        y += high + 10
        self.code.setPlainText(request.skedge or "No Skedge yet")
        self.code.setTextWidth(INNER - 2 * CODE_PAD)
        high = self.code.size().height() + 2 * CODE_PAD
        regions["skedge"] = QRectF(INSET, y, INNER, high)
        y += high + 12
        if request.tags:
            rows = self._tag_rows(request.tags)
            high = len(rows) * 26 - 6
            regions["tags"] = QRectF(INSET, y, INNER, high)
            y += high + 12
        for field in ("scope", "requester", "created"):
            regions[field] = QRectF(INSET, y, INNER, 18)
            y += 22
        y += 6
        regions["rule"] = QRectF(INSET, y, INNER, 1)
        y += 10
        high = _wrapped(self.status.text or " ", STATUS_FONT, INNER - 16, lines=3)
        regions["status"] = QRectF(INSET, y, INNER, high)
        y += high + INSET
        self.regions = regions
        self._set_height(y)
        self.summary = _fitted(
            request.description or request.id or "Untitled request",
            SUMMARY_TITLE_FONT,
            INNER,
            self._summary_body().height(),
        )

    def _set_height(self, height: float) -> None:
        """Take a new height, and the rectangles that go with it, kept for painting.

        Qt asks for the bounding rectangle several times a frame, for every card on
        screen; from far out that is hundreds, so they are made here rather than there.
        """
        self.height = height
        self.face = QRectF(0, 0, CARD_WIDTH, height)
        self.bounds = self.face.adjusted(-3, -3, 3, 3)
        self.update()

    def _tag_rows(self, tags: tuple[str, ...]) -> list[list[tuple[str, float]]]:
        """The tags as pills, flowed into rows as wide as the card."""
        metrics = QFontMetricsF(TAG_FONT)
        rows: list[list[tuple[str, float]]] = [[]]
        used = 0.0
        for tag in tags:
            wide = min(metrics.horizontalAdvance(tag) + 18, INNER)
            if rows[-1] and used + wide > INNER:
                rows.append([])
                used = 0.0
            rows[-1].append((tag, wide))
            used += wide + 6
        return rows

    def card_rect(self) -> QRectF:
        """The card itself, without the edge drawn round it."""
        return self.face

    def boundingRect(self) -> QRectF:  # noqa: N802
        """The card, and room for its edge when picked, which is drawn thicker."""
        return self.bounds

    def shape(self) -> QPainterPath:
        """Clicks land on the card's rounded shape, not in its corners."""
        path = QPainterPath()
        path.addRoundedRect(self.card_rect(), RADIUS, RADIUS)
        return path

    def region_at(self, point) -> str | None:
        """Which field is painted at a point on the card."""
        return next((name for name, rect in self.regions.items() if rect.contains(point)), None)

    # -- painting -----------------------------------------------------------------------

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        """Lighten the card's face and edge a little under the pointer."""
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        """Put it back."""
        self.hovered = False
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """The card, in as much detail as its distance allows."""
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        rect = self.face
        if lod < SUMMARY:
            # Corners of a pixel or two look no different smoothed, and cost more.
            painter.setRenderHint(QPainter.Antialiasing, RADIUS * lod >= 2)
            self._paint_block(painter, rect)
            return
        colour = priority_colour(self.shown.priority)
        self._paint_body(painter, rect, colour, lod)
        if self.editing:
            return  # the form draws the fields
        if lod < FULL_DETAIL:
            self._paint_summary(painter, rect, colour)
            return
        self._paint_header(painter, colour)
        self._paint_title(painter)
        self._paint_code(painter)
        self._paint_tags(painter)
        self._paint_meta(painter)
        self._paint_status(painter)

    def _paint_block(self, painter: QPainter, rect: QRectF) -> None:
        """From far off: the card as a block of its priority's colour."""
        picked = self.isSelected() or self.editing
        painter.setPen(Qt.NoPen)
        painter.setBrush(BLOCK_COLOURS[self.shown.priority, picked])
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
        if self.status.kind in (BAD, WARNING, UNSAVED):
            painter.setBrush(DOT_COLOURS[self.status.kind])
            painter.drawEllipse(QRectF(rect.right() - 40, 16, 24, 24))

    def _paint_body(self, painter: QPainter, rect: QRectF, colour: QColor, lod: float) -> None:
        """The card's face, edge and stripe."""
        face = QColor(CARD).lighter(112) if self.hovered and not self.editing else CARD
        painter.setBrush(face)
        if self.isSelected() or self.editing:
            painter.setPen(QPen(SELECTED, 2.0 / max(lod, 0.35)))
        else:
            painter.setPen(QPen(EDGE.lighter(125) if self.hovered else EDGE, 1.0))
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawPath(self._stripe())

    def _stripe(self) -> QPainterPath:
        """The card's left edge as far in as the stripe goes, following its rounded corners.

        Built as a shape rather than painted through a clip, which cost more than the rest
        of the card's face put together. Kept until the card changes height.
        """
        if self.stripe_for == self.height:
            return self.stripe
        # where the corners' curve crosses the stripe's inner edge, in Qt's degrees
        turn = degrees(acos((STRIPE - RADIUS) / RADIUS))
        corner = QSizeF(2 * RADIUS, 2 * RADIUS)
        path = QPainterPath()
        path.moveTo(STRIPE, RADIUS - sqrt(RADIUS**2 - (RADIUS - STRIPE) ** 2))
        path.arcTo(QRectF(QPointF(0, 0), corner), turn, 180 - turn)
        path.lineTo(0, self.height - RADIUS)
        path.arcTo(QRectF(QPointF(0, self.height - 2 * RADIUS), corner), 180, 180 - turn)
        path.closeSubpath()
        self.stripe, self.stripe_for = path, self.height
        return path

    def _summary_body(self) -> QRectF:
        """Where the description goes on a card seen from the middle distance."""
        top = INSET + 16 * SUMMARY_SCALE + 8
        return QRectF(INSET, top, INNER, self.height - top - INSET)

    def _paint_summary(self, painter: QPainter, rect: QRectF, colour: QColor) -> None:
        """Middle distance: the priority, and the description written large enough to read.

        Written at one size on the card, whatever the zoom, so that the words grow and
        shrink with the card as if they were printed on it, rather than being set again
        in a new size, and wrapped anew, at every step of a zoom.
        """
        painter.setFont(SUMMARY_CHIP_FONT)
        painter.setPen(colour)
        top = QRectF(INSET, INSET, INNER, 16 * SUMMARY_SCALE)
        painter.drawText(top, Qt.AlignLeft | Qt.AlignVCenter, PRIORITY_NAMES[self.shown.priority])
        if self.status.kind in (BAD, WARNING, UNSAVED):
            painter.setPen(Qt.NoPen)
            painter.setBrush(DOT_COLOURS[self.status.kind])
            size = 8 * SUMMARY_SCALE
            painter.drawEllipse(QRectF(rect.right() - INSET - size, INSET + 4, size, size))
        painter.setFont(SUMMARY_TITLE_FONT)
        painter.setPen(QColor(palette.INK))
        painter.drawText(
            self._summary_body(), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self.summary
        )

    def _paint_header(self, painter: QPainter, colour: QColor) -> None:
        """The id on the left; the weight and the priority chip on the right."""
        request = self.shown
        area = self.regions["header"]
        painter.setFont(CHIP_FONT)
        name = PRIORITY_NAMES[request.priority]
        wide = QFontMetricsF(CHIP_FONT).horizontalAdvance(name) + 18
        chip = QRectF(area.right() - wide, area.top(), wide, area.height())
        fill = QColor(colour)
        fill.setAlpha(40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(chip, chip.height() / 2, chip.height() / 2)
        painter.setPen(colour)
        painter.drawText(chip, Qt.AlignCenter, name)
        right = chip.left() - 8
        if not request.priority.hard and request.weight != 1:
            painter.setFont(VALUE_FONT)
            painter.setPen(QColor(palette.QUIET))
            weight = f"×{request.weight:g}"
            wide = QFontMetricsF(VALUE_FONT).horizontalAdvance(weight)
            painter.drawText(
                QRectF(right - wide, area.top(), wide, area.height()), Qt.AlignVCenter, weight
            )
            right -= wide + 10
        painter.setFont(ID_FONT)
        painter.setPen(QColor(palette.QUIET))
        written = request.id or "new request"
        room = right - area.left()
        text = QFontMetricsF(ID_FONT).elidedText(written, Qt.ElideMiddle, room)
        where = QRectF(area.left(), area.top(), room, area.height())
        painter.drawText(where, Qt.AlignVCenter, text)

    def _paint_title(self, painter: QPainter) -> None:
        request = self.shown
        painter.setFont(TITLE_FONT)
        painter.setPen(QColor(palette.INK if request.description else palette.QUIET))
        painter.drawText(
            self.regions["description"],
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            request.description or "Untitled request",
        )

    def _paint_code(self, painter: QPainter) -> None:
        """The Skedge, coloured as the editor colours it, on a sunken block."""
        area = self.regions["skedge"]
        painter.setPen(QPen(EDGE, 1))
        painter.setBrush(CODE)
        painter.drawRoundedRect(area, 8, 8)
        painter.save()
        painter.translate(area.left() + CODE_PAD, area.top() + CODE_PAD)
        context = QAbstractTextDocumentLayout.PaintContext()
        writing = palette.TEXT if self.shown.skedge else palette.QUIET
        context.palette.setColor(QPalette.Text, QColor(writing))
        self.code.documentLayout().draw(painter, context)
        painter.restore()

    def _paint_tags(self, painter: QPainter) -> None:
        if "tags" not in self.regions:
            return
        area = self.regions["tags"]
        painter.setFont(TAG_FONT)
        metrics = QFontMetricsF(TAG_FONT)
        y = area.top()
        for row in self._tag_rows(self.shown.tags):
            x = area.left()
            for tag, wide in row:
                pill = QRectF(x, y, wide, 20)
                painter.setPen(Qt.NoPen)
                painter.setBrush(EDGE)
                painter.drawRoundedRect(pill, 10, 10)
                painter.setPen(QColor(palette.TEXT))
                text = metrics.elidedText(tag, Qt.ElideRight, wide - 18)
                painter.drawText(pill, Qt.AlignCenter, text)
                x += wide + 6
            y += 26

    def _paint_meta(self, painter: QPainter) -> None:
        """Scope, requester and created, each with its label, as the editor lays them out."""
        request = self.shown
        values = {
            "scope": describe(request.scope) if request.scope else "set on save",
            "requester": request.requester or "—",
            "created": request.created.isoformat() if request.created else "—",
        }
        for field, value in values.items():
            area = self.regions[field]
            painter.setFont(LABEL_FONT)
            painter.setPen(QColor(palette.QUIET))
            label = QRectF(area.left(), area.top(), LABEL_WIDTH, area.height())
            painter.drawText(label, Qt.AlignVCenter, field.upper())
            painter.setFont(VALUE_FONT)
            painter.setPen(QColor(palette.TEXT))
            rest = QRectF(label.right(), area.top(), area.width() - LABEL_WIDTH, area.height())
            text = QFontMetricsF(VALUE_FONT).elidedText(value, Qt.ElideRight, rest.width())
            painter.drawText(rest, Qt.AlignVCenter, text)

    def _paint_status(self, painter: QPainter) -> None:
        """A dot of the status's colour, and what it says."""
        rule = self.regions["rule"]
        painter.fillRect(rule, EDGE)
        area = self.regions["status"]
        colour = QColor(STATUS_COLOURS[self.status.kind])
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QRectF(area.left(), area.top() + 4, 8, 8))
        painter.setFont(STATUS_FONT)
        painter.setPen(colour if self.status.kind != NOTE else QColor(palette.QUIET))
        painter.drawText(
            area.adjusted(16, 0, 0, 0),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            self.status.text,
        )


class WrappingLine(QPlainTextEdit):
    """A one-paragraph text box that wraps and grows, as the card's description does.

    It answers to what the request editor asks of its QLineEdit — `text`, `setText`,
    `end` — so the editor's own code drives it unchanged. Enter goes on to the Skedge
    rather than starting a new line: a description is one paragraph.
    """

    next_field = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)

    def text(self) -> str:
        """The description, as one line."""
        return " ".join(self.toPlainText().split("\n"))

    def setText(self, text: str) -> None:  # noqa: N802
        """Show a description."""
        self.setPlainText(text)

    def end(self, mark: bool) -> None:
        """Put the cursor after the last word."""
        self.moveCursor(QTextCursor.End)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Enter moves on to the Skedge."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.next_field.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        """Paste as one line."""
        self.insertPlainText(" ".join(source.text().split()))

    def _fit(self, *_) -> None:
        lines = max(int(self.document().documentLayout().documentSize().height()), 1)
        margins = self.contentsMargins()
        spacing = self.fontMetrics().lineSpacing()
        margin = self.document().documentMargin()
        self.setFixedHeight(round(lines * spacing + 2 * margin + margins.top() + margins.bottom()))


class SuggestionKeys(QObject):
    """Handles the keys typed while a suggestion list is open, in place of QCompleter.

    With the list open, the keys go to the list, and QCompleter passes them on to the box
    being typed in — then closes the list if that box does not have the focus. A box on a
    card never reports having it while the list is open: the list is a window of its own,
    and the canvas's scene counts as inactive while it is up. So the list closed on one
    key and opened again on the next. The keys are handled here instead, first: typing
    goes to the box, Enter and Tab take the suggestion picked, Escape closes the list,
    and only moving through the list is left to the list.
    """

    MOVES = (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown)

    def __init__(self, completer: QCompleter, box: QWidget) -> None:
        super().__init__(box)
        self.completer = completer
        self.box = box
        completer.popup().installEventFilter(self)  # after QCompleter's, so it runs first

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Take the key before QCompleter does."""
        if event.type() != QEvent.KeyPress:
            return False
        key = event.key()
        popup = self.completer.popup()
        if key in self.MOVES:
            return False
        picked = popup.currentIndex()
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab) and picked.isValid():
            popup.hide()
            self.completer.activated.emit(picked.data())
            return True
        if key in (Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab):
            popup.hide()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            popup.hide()  # nothing picked: Enter is the box's own, a new line
        QApplication.sendEvent(self.box, event)
        return True


class CardEditor(RequestEditor):
    """The request editor, laid out as a card: what a card turns into when it is clicked.

    Everything the request editor does it does — the completion, the colouring, the check
    as you type — with the fields where the painted card has them, and no New button: a
    new card comes from the frame it goes in. Delete asks for the card to go and nothing
    more; which card is up next is the canvas's business.
    """

    grown = Signal()  # the form changed height, so the card under it must too

    STYLE = f"""
    CardEditor {{ background: transparent; }}
    QLineEdit, QComboBox, QDoubleSpinBox {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 2px 6px;
    }}
    QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover {{ border-color: {palette.LINE}; }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
        border-color: {palette.HIGHLIGHT};
        background: {palette.SUNKEN};
    }}
    QPlainTextEdit#description {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 0px 2px;
        font-size: 15px;
        font-weight: 600;
        color: {palette.INK};
    }}
    QPlainTextEdit#description:hover {{ border-color: {palette.LINE}; }}
    QPlainTextEdit#description:focus {{
        border-color: {palette.HIGHLIGHT};
        background: {palette.SUNKEN};
    }}
    QPlainTextEdit#skedge {{
        background: {palette.SUNKEN};
        border: 1px solid {palette.LINE};
        border-radius: 8px;
        padding: 4px 4px;
    }}
    QPlainTextEdit#skedge:focus {{ border-color: {palette.HIGHLIGHT}; }}
    QLabel#field {{ color: {palette.QUIET}; font-size: 9.5px; font-weight: 600; }}
    QLabel#id {{ color: {palette.QUIET}; }}
    QPushButton {{ border-radius: 6px; padding: 3px 12px; }}
    QPushButton#save {{
        background: {palette.HIGHLIGHT};
        border-color: {palette.HIGHLIGHT};
        color: {palette.ON_HIGHLIGHT};
    }}
    QPushButton#save:disabled {{
        background: {palette.SURFACE};
        border-color: {palette.LINE};
        color: {palette.QUIET};
    }}
    """

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(self.STYLE)
        self.setFixedWidth(round(INNER))
        self.id_label.setObjectName("id")
        self.id_label.setFont(ID_FONT)
        self.save_button.setObjectName("save")
        self.skedge_edit.setObjectName("skedge")
        self.skedge_edit.setFont(CODE_FONT)
        self.skedge_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.skedge_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.skedge_edit.setLineWrapMode(self.skedge_edit.LineWrapMode.WidgetWidth)
        self.skedge_edit.setPlaceholderText("REQUEST …")
        self.skedge_edit.document().setDocumentMargin(6)
        self.skedge_edit.document().documentLayout().documentSizeChanged.connect(self._fit)
        self.tags_edit.setPlaceholderText("tags, comma-separated")
        self.status.setFont(STATUS_FONT)
        self.suggestion_keys = (
            SuggestionKeys(self.skedge_edit.completer, self.skedge_edit),
            SuggestionKeys(self.requester_completer, self.requester_edit),
        )
        self._fit()

    def _lay_out(self) -> None:
        """The card's order: id and priority, description, Skedge, tags, the rest, status."""
        self.description_edit = WrappingLine()
        self.description_edit.setObjectName("description")
        self.description_edit.setPlaceholderText("What this request is for")
        self.description_edit.next_field.connect(lambda: self.skedge_edit.setFocus())
        self.description_edit.textChanged.connect(self._fit)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.id_label, stretch=1)
        header.addWidget(self.weight_box)
        header.addWidget(self.priority_box)
        self.weight_box.setToolTip("weight")
        self.weight_box.setFixedWidth(82)
        details = QGridLayout()
        details.setHorizontalSpacing(4)
        details.setVerticalSpacing(2)
        details.setColumnMinimumWidth(0, round(LABEL_WIDTH) - 6)
        for row, (name, widget) in enumerate(
            (
                ("SCOPE", self.scope_box),
                ("REQUESTER", self.requester_edit),
                ("CREATED", self.created_label),
            )
        ):
            label = QLabel(name)
            label.setObjectName("field")
            details.addWidget(label, row, 0)
            details.addWidget(widget, row, 1)
        self.created_label.setContentsMargins(7, 0, 0, 0)
        footer = QHBoxLayout()
        footer.addWidget(self.status, stretch=1)
        footer.addWidget(self.delete_button)
        footer.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.description_edit)
        layout.addWidget(self.skedge_edit)
        layout.addWidget(self.tags_edit)
        layout.addLayout(details)
        layout.addLayout(footer)

    def _fit(self, *_) -> None:
        """Grow the Skedge box to hold all of it, rather than scroll, and say so."""
        edit = self.skedge_edit
        lines = max(int(edit.document().documentLayout().documentSize().height()), 3)
        margins = edit.contentsMargins()
        spacing = edit.fontMetrics().lineSpacing()
        margin = edit.document().documentMargin()
        edit.setFixedHeight(round(lines * spacing + 2 * margin + margins.top() + margins.bottom()))
        self.adjustSize()
        self.grown.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """A wrap can change the line count without the text changing."""
        super().resizeEvent(event)
        self.grown.emit()

    def sizeHint(self):  # noqa: N802
        """As tall as the fields need, and the card's width."""
        hint = super().sizeHint()
        return QSizeF(INNER, hint.height()).toSize()

    def _delete(self) -> None:
        """Ask for this card's request to go; the canvas decides what is shown next."""
        self.deleted.emit(self.original_id or "")

    def focus_field(self, field: str | None, point=None) -> None:
        """Put the cursor in the field that was clicked, at the place it was clicked."""
        widgets = {
            "description": self.description_edit,
            "skedge": self.skedge_edit,
            "tags": self.tags_edit,
            "scope": self.scope_box,
            "requester": self.requester_edit,
            "header": self.description_edit,
        }
        widget = widgets.get(field, self.description_edit)
        widget.setFocus(Qt.MouseFocusReason)
        if widget is self.skedge_edit and point is not None:
            inside = widget.viewport().mapFrom(self, point.toPoint())
            widget.setTextCursor(widget.cursorForPosition(inside))
        elif widget is not self.skedge_edit and hasattr(widget, "end"):
            widget.end(False)
