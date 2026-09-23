"""The request table, and what a row looks like while it is being dragged.

Qt's own drag picture is a snapshot of every row picked up, held with the pointer in the
middle of it — a slab of table that covers the very group it is being dragged onto. A
file manager carries a small token instead: one label beside the pointer, with the others
stacked behind it and a count on the corner. That is what a drag here carries too.
"""

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QTableView

from puppet_strings.app import palette
from puppet_strings.app.requests_model import request_ids

WIDEST = 220  # past this a request's id is elided rather than the token grown
PAD = 10  # between the token's edge and its writing
STACK = 4  # how far each card behind the first sits down and to the right
BESIDE = QPoint(-14, -18)  # the token sits below and right of the pointer, not under it


def drag_token(ids: list[str], font: QFont, ratio: float = 1.0) -> QPixmap:
    """The small card a drag of these requests is shown as.

    The first request is named; any more show as cards stacked behind it, with a badge on
    the corner saying how many there are in all, so the token stays the same size however
    many are carried.
    """
    metrics = QFontMetrics(font)
    text = metrics.elidedText(ids[0], Qt.ElideRight, WIDEST)
    card_w, card_h = metrics.horizontalAdvance(text) + 2 * PAD, metrics.height() + PAD
    behind = min(len(ids) - 1, 2)  # at most two cards show behind the first
    badge = metrics.height() + 4 if len(ids) > 1 else 0
    width = card_w + behind * STACK + badge // 2 + 1
    height = card_h + behind * STACK + badge // 2 + 1

    pixmap = QPixmap(round(width * ratio), round(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setFont(font)
    top = badge // 2  # the badge overhangs the card's top edge
    for depth in range(behind, -1, -1):  # the farthest card first, so the nearest is on top
        card = QRectF(depth * STACK + 0.5, top + depth * STACK + 0.5, card_w, card_h)
        fill = QColor(palette.HIGHLIGHT if depth == 0 else palette.SURFACE)
        fill.setAlpha(235)
        painter.setPen(QColor(palette.QUIET if depth else palette.HIGHLIGHT).lighter(130))
        painter.setBrush(fill)
        painter.drawRoundedRect(card, 5, 5)
    painter.setPen(QColor(palette.ON_HIGHLIGHT))
    painter.drawText(QRectF(0, top, card_w, card_h), Qt.AlignCenter, text)
    if badge:
        count = str(len(ids))
        badge_w = max(badge, metrics.horizontalAdvance(count) + 8)
        spot = QRectF(card_w - badge_w / 2, 0.5, badge_w, badge)
        path = QPainterPath()
        path.addRoundedRect(spot, badge / 2, badge / 2)
        painter.fillPath(path, QColor(palette.BAD))
        painter.setPen(QColor(palette.INK))
        painter.drawText(spot, Qt.AlignCenter, count)
    painter.end()
    return pixmap


class RequestTable(QTableView):
    """The table of requests, whose rows are dragged onto a group to move them there.

    Delete (or Backspace) asks for the selected rows to be deleted; the window asks first.
    """

    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setDragEnabled(True)
        self.setDragDropMode(QTableView.DragOnly)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Delete or Backspace on a selection asks for it to be deleted."""
        if (
            event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
            and self.selectionModel().hasSelection()
        ):
            self.delete_requested.emit()
            return
        super().keyPressEvent(event)

    def startDrag(self, supported) -> None:  # noqa: N802
        """Carry the rows picked up as a small token beside the pointer.

        Nothing is removed from the table when the drag lands, as Qt's own would try to:
        a request moved to another group is changed in the store, not taken out of it.
        """
        indexes = [i for i in self.selectedIndexes() if i.flags() & Qt.ItemIsDragEnabled]
        if not indexes:
            return
        data = self.model().mimeData(indexes)
        if data is None:
            return
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(drag_token(request_ids(data), self.font(), self.devicePixelRatioF()))
        drag.setHotSpot(BESIDE)
        drag.exec(supported, Qt.MoveAction)
