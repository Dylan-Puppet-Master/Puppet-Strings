"""A group on the canvas: a frame its cards sit in, with the group's name across the top.

A frame is where a card is dropped to move it to that group, and where a new request for
the group is started — with the button in its header, or a double-click anywhere in it.
"""

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsObject, QStyleOptionGraphicsItem

from puppet_strings.app import palette
from puppet_strings.app.canvas.card import FULL_DETAIL, _font
from puppet_strings.app.canvas.layout import HEADER, PAD
from puppet_strings.app.groups import UNGROUPED

RADIUS = 18.0
TITLE_FONT = _font(20, QFont.DemiBold)
NOTE_FONT = _font(11.5)
COUNT_FONT = _font(11, QFont.DemiBold)
BUTTON_FONT = _font(12, QFont.DemiBold)
BUTTON = QSizeF(132, 32)


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

    def set_size(self, size: QSizeF) -> None:
        """Grow or shrink to hold its cards."""
        self.prepareGeometryChange()
        self.size = QSizeF(size)
        self.update()

    def set_counts(self, shown: int, total: int, note: str) -> None:
        """What the header says about the group."""
        if (shown, total, note) != (self.shown, self.total, self.note):
            self.shown, self.total, self.note = shown, total, note
            self.update()

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
        """The frame, its title, its counts and its button; the title alone from far away."""
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
            self._paint_far(painter, lod)
            return
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
        count = str(self.shown) if self.shown == self.total else f"{self.shown} of {self.total}"
        pill_w = QFontMetricsF(COUNT_FONT).horizontalAdvance(count) + 16
        room = button.left() - 12 - pill_w - 10 - PAD
        painter.setFont(TITLE_FONT)
        painter.setPen(QColor(palette.INK if self.group != UNGROUPED else palette.QUIET))
        title = QFontMetricsF(TITLE_FONT).elidedText(self.title, Qt.ElideRight, room)
        drawn = painter.drawText(
            QRectF(PAD, 12, room, 30), Qt.AlignVCenter | Qt.TextDontClip, title
        )
        wide = drawn.width()  # as drawn, which at some zooms is not what the metrics say
        painter.setFont(COUNT_FONT)
        pill = QRectF(PAD + wide + 10, 17, pill_w, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(palette.LINE))
        painter.drawRoundedRect(pill, 10, 10)
        painter.setPen(QColor(palette.TEXT))
        painter.drawText(pill, Qt.AlignCenter, count)
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

    def _paint_far(self, painter: QPainter, lod: float) -> None:
        """From far off, the title written large enough to find the group by."""
        text = f"{self.title}  ·  {self.shown}"
        room = self.size.width() - 2 * PAD
        wanted = 16 / lod  # about 16 pixels on screen
        natural = QFontMetricsF(_font(100, QFont.DemiBold)).horizontalAdvance(text) / 100
        pixels = max(min(wanted, room / natural, 20 * 12), 20)
        scale = pixels / 20
        font = _font(pixels, QFont.DemiBold)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text = metrics.elidedText(text, Qt.ElideRight, room)
        box = QRectF(PAD, PAD * 0.6, metrics.horizontalAdvance(text) + 8 * scale, metrics.height())
        back = QColor(palette.WINDOW)
        back.setAlpha(215)
        painter.setPen(Qt.NoPen)
        painter.setBrush(back)
        painter.drawRoundedRect(box.adjusted(-8 * scale, 0, 0, 0), 8 * scale, 8 * scale)
        painter.setPen(QColor(palette.INK))
        painter.drawText(box, Qt.AlignVCenter, text)
