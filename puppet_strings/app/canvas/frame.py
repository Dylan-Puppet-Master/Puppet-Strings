"""A group on the canvas: a frame its cards sit in, with the group's name across the top.

A frame is where a card is dropped to move it to that group, and where a new request for
the group is started — with the button in its header, or a double-click anywhere in it.

Close up, the name is in the header with the rest. Further out it would be too small to
read at the header's size, so the name and its count are drawn larger, as a tab: the same
drawing, scaled up from where the header has it, so nothing jumps as the header goes.
It grows upward, out over the frame's top edge into the gap above, which keeps it clear
of the cards while they can still be read; only once the gap is used up, about when the
cards become blocks of colour, does it grow down over them.
"""

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem

from puppet_strings.app import palette
from puppet_strings.app.canvas.card import FULL_DETAIL, _font
from puppet_strings.app.canvas.layout import FRAME_GAP, HEADER, PAD
from puppet_strings.app.groups import UNGROUPED

RADIUS = 18.0
TITLE_FONT = _font(20, QFont.DemiBold)
NOTE_FONT = _font(11.5)
COUNT_FONT = _font(11, QFont.DemiBold)
BUTTON_FONT = _font(12, QFont.DemiBold)
BUTTON = QSizeF(132, 32)
NAME = QRectF(0, 12, 0, 30)  # the header's strip for the name and its count, but for width
# From further out the name grows a little on screen as it goes, to hold its own against
# the frames shrinking round it: by this power of how much further out than FULL_DETAIL.
GROWTH = 1.1
LEAST_PIXELS = 11  # it shrinks to fit a narrow frame, but no smaller than this on screen
MOST_SCALE = 12.0
CEILING = -(FRAME_GAP - 16)  # as far up into the gap as it goes, clear of the frame above


class GroupFrame(QGraphicsObject):
    """One group's frame. `group` is the group's name, or `UNGROUPED`."""

    def __init__(self, group: str) -> None:
        super().__init__()
        self.group = group
        self.size = QSizeF(0, 0)
        self.shown = 0  # cards in it the filters let through
        self.total = 0  # requests in the group at all
        self.note = ""  # under the title: what scope new requests here take
        self.target = False  # a dragged card would land here
        self.empty = True  # no card in it, so it says how to put one there
        self.over_button = False
        self.movable = False  # far enough out that dragging it moves the whole group
        self.setZValue(-10)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.far_title = FarTitle(self)

    def set_size(self, size: QSizeF) -> None:
        """Grow or shrink to hold its cards."""
        self.prepareGeometryChange()
        self.size = QSizeF(size)
        self.far_title.resize()
        self.update()

    def set_counts(self, shown: int, total: int, note: str) -> None:
        """What the header says about the group."""
        if (shown, total, note) != (self.shown, self.total, self.note):
            self.shown, self.total, self.note = shown, total, note
            self.update()
            self.far_title.update()

    def itemChange(self, change, value):  # noqa: N802
        """Take the far title along: into the scene, out of it, and wherever it moves."""
        if change == QGraphicsItem.ItemSceneChange:
            if self.scene() is not None:
                self.scene().removeItem(self.far_title)
            if value is not None:
                value.addItem(self.far_title)
                self.far_title.setPos(self.pos())
        elif change == QGraphicsItem.ItemPositionHasChanged:
            self.far_title.setPos(self.pos())
        return super().itemChange(change, value)

    def set_target(self, target: bool) -> None:
        """Light up as where a dragged card would go, or stop."""
        if target != self.target:
            self.target = target
            self.update()

    def rect(self) -> QRectF:
        """The frame in its own coordinates."""
        return QRectF(0, 0, self.size.width(), self.size.height())

    def boundingRect(self) -> QRectF:  # noqa: N802
        """The frame, and room for its edge."""
        return self.rect().adjusted(-3, -3, 3, 3)

    def button_rect(self) -> QRectF:
        """The header's New request button."""
        return QRectF(
            self.size.width() - PAD - BUTTON.width(),
            (HEADER - BUTTON.height()) / 2,
            BUTTON.width(),
            BUTTON.height(),
        )

    def on_button(self, point) -> bool:
        """Whether a point, in the frame's coordinates, is on the New request button."""
        return self.button_rect().contains(point)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        """Light the button under the pointer; from far off, offer the frame as a handle."""
        over = self.on_button(event.pos()) and not self.movable
        if over:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.OpenHandCursor if self.movable else Qt.ArrowCursor)
        if over != self.over_button:
            self.over_button = over
            self.update()

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        """Stop lighting it."""
        self.over_button = False
        self.unsetCursor()
        self.update()

    @property
    def title(self) -> str:
        """The group's name as the header writes it."""
        return "Ungrouped" if self.group == UNGROUPED else self.group

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """The frame, and close up its title, its counts and its button."""
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        rect = self.rect()
        fill = QColor(palette.HIGHLIGHT if self.target else palette.WINDOW)
        fill.setAlpha(40 if self.target else 170)
        edge = QColor(palette.HIGHLIGHT).lighter(130) if self.target else QColor(palette.LINE)
        pen = QPen(edge, (2.0 if self.target else 1.0) / max(lod, 0.2))
        if self.group == UNGROUPED and not self.target:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
        if lod < FULL_DETAIL:
            return  # the far title has the name
        self._paint_header(painter)
        if self.empty:
            painter.setFont(NOTE_FONT)
            painter.setPen(QColor(palette.QUIET))
            hint = "Double-click to add a request, or drop cards here"
            if self.total:
                hint = f"{self.total} hidden by the filters\n{hint}"
            painter.drawText(
                rect.adjusted(PAD, HEADER, -PAD, -PAD), Qt.AlignCenter | Qt.TextWordWrap, hint
            )

    def _paint_header(self, painter: QPainter) -> None:
        """The title and its count on the left, the note under them, the button on the right.

        The title gives way to the count and the button, not the other way round: in a
        frame one card wide there is not room for a long name and all the rest.
        """
        button = self.button_rect()
        self.paint_name(painter, button.left() - 12 - PAD)
        painter.setFont(NOTE_FONT)
        painter.setPen(QColor(palette.QUIET))
        room = button.left() - 12 - PAD
        note = QFontMetricsF(NOTE_FONT).elidedText(self.note, Qt.ElideRight, room)
        painter.drawText(QRectF(PAD, 42, room, 18), Qt.AlignVCenter, note)
        fill = QColor(palette.HIGHLIGHT)
        fill.setAlpha(255 if self.over_button else 190)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(button, 8, 8)
        painter.setFont(BUTTON_FONT)
        painter.setPen(QColor(palette.ON_HIGHLIGHT))
        painter.drawText(button, Qt.AlignCenter, "+  New request")

    @property
    def count(self) -> str:
        """What the pill after the name says."""
        return str(self.shown) if self.shown == self.total else f"{self.shown} of {self.total}"

    def name_width(self) -> float:
        """How wide the name and its count are, in full, at the header's size."""
        pill_w = QFontMetricsF(COUNT_FONT).horizontalAdvance(self.count) + 16
        return QFontMetricsF(TITLE_FONT).horizontalAdvance(self.title) + 10 + pill_w

    def paint_name(self, painter: QPainter, room: float, back: QColor | None = None) -> QRectF:
        """The name and its count from PAD across in the header's name strip, within `room`.

        The far title draws this too, scaled. `back` is a tab to draw them on. Returns
        where they went.
        """
        count = self.count
        pill_w = QFontMetricsF(COUNT_FONT).horizontalAdvance(count) + 16
        title = QFontMetricsF(TITLE_FONT).elidedText(self.title, Qt.ElideRight, room - pill_w - 10)
        wide = QFontMetricsF(TITLE_FONT).horizontalAdvance(title)
        box = QRectF(PAD, NAME.top(), wide + 10 + pill_w, NAME.height())
        if back is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(back)
            painter.drawRoundedRect(box.adjusted(-10, -2, 10, 2), 10, 10)
        painter.setFont(TITLE_FONT)
        painter.setPen(QColor(palette.INK if self.group != UNGROUPED else palette.QUIET))
        drawn = painter.drawText(
            QRectF(PAD, NAME.top(), wide + 20, NAME.height()),
            Qt.AlignVCenter | Qt.TextDontClip,
            title,
        )
        wide = drawn.width()  # as drawn, which at some zooms is not what the metrics say
        painter.setFont(COUNT_FONT)
        pill = QRectF(PAD + wide + 10, NAME.top() + 5, pill_w, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(palette.LINE))
        painter.drawRoundedRect(pill, 10, 10)
        painter.setPen(QColor(palette.TEXT))
        painter.drawText(pill, Qt.AlignCenter, count)
        return box


class FarTitle(QGraphicsItem):
    """A frame's name and count from too far out for its header: the header's, scaled up.

    An item of its own rather than part of the frame, to be drawn over the cards once it
    grows down onto them; the frame keeps it where it is.
    """

    def __init__(self, frame: GroupFrame) -> None:
        super().__init__()
        self.frame = frame
        self.drawn = QRectF()  # where it was last drawn, in the frame's coordinates
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(4)  # over the cards, under the form

    def resize(self) -> None:
        """Follow the frame's width."""
        self.prepareGeometryChange()

    def boundingRect(self) -> QRectF:  # noqa: N802
        """As far as it can reach: up into the gap, and down over the cards."""
        return QRectF(0, CEILING - 4, self.frame.size.width(), NAME.height() * MOST_SCALE + 8)

    def scale_at(self, lod: float) -> float:
        """How many times the header's size it is drawn at, from this far out.

        The header's size at FULL_DETAIL, growing from there; shrinking to fit a narrow
        frame's width, but never to less than LEAST_PIXELS on screen, nor below the
        header's size.
        """
        grow = (FULL_DETAIL / lod) ** GROWTH
        fit = (self.frame.size.width() - 2 * PAD) / self.frame.name_width()
        least = LEAST_PIXELS / (TITLE_FONT.pixelSize() * lod)
        return min(grow, max(fit, least, 1.0), MOST_SCALE)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """Scaled from the bottom of the header's name strip, until the gap is used up."""
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        if lod >= FULL_DETAIL:
            self.drawn = QRectF()
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        scale = self.scale_at(lod)
        top = max(NAME.bottom() - NAME.height() * scale, CEILING)
        # The tab fades in on the way out: at FULL_DETAIL it is the header, with none.
        back = QColor(palette.WINDOW)
        back.setAlpha(170)
        tab = _over(back, QColor(palette.CANVAS))
        tab.setAlpha(round(255 * min(1.0, (FULL_DETAIL - lod) / (0.3 * FULL_DETAIL))))
        painter.translate(PAD, top)
        painter.scale(scale, scale)
        painter.translate(-PAD, -NAME.top())
        room = (self.frame.size.width() - 2 * PAD) / scale
        box = self.frame.paint_name(painter, room, tab)
        corner = QPointF(PAD + (box.left() - PAD) * scale, top)
        self.drawn = QRectF(corner, box.size() * scale)


def _over(fill: QColor, under: QColor) -> QColor:
    """A see-through colour as it looks laid over an opaque one."""
    a = fill.alphaF()
    return QColor.fromRgbF(
        *(f * a + u * (1 - a) for f, u in zip(fill.getRgbF()[:3], under.getRgbF()[:3], strict=True))
    )
