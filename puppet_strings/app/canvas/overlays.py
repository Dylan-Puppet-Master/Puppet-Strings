"""What floats over the canvas: the zoom controls, the minimap and the New request button."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QToolButton, QWidget

from puppet_strings.app import palette
from puppet_strings.app.canvas.card import priority_colour

PANEL = f"""
QFrame#panel {{
    background: {palette.SURFACE};
    border: 1px solid {palette.LINE};
    border-radius: 10px;
}}
QToolButton {{
    background: transparent;
    color: {palette.TEXT};
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
}}
QToolButton:hover {{ background: {palette.LINE}; }}
"""


class ZoomBar(QFrame):
    """Zoom out, the zoom as a percentage (click for 100%), zoom in, and fit everything."""

    zoom_out = Signal()
    zoom_in = Signal()
    actual_size = Signal()
    fit = Signal()
    reset = Signal()  # put every group back where the canvas lays it out
    moved_sideways = Signal()  # it changed width, so what sits beside it must move

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(PANEL)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.level = QToolButton()
        self.level.setMinimumWidth(56)
        self.level.setToolTip("Actual size (Ctrl+1)")
        for text, tip, signal in (
            ("−", "Zoom out (−)", self.zoom_out),
            (None, None, self.actual_size),
            ("+", "Zoom in (+)", self.zoom_in),
            ("Fit", "Show everything (F)", self.fit),
        ):
            button = self.level if text is None else QToolButton()
            if text is not None:
                button.setText(text)
                button.setToolTip(tip)
            button.clicked.connect(signal.emit)
            button.setFocusPolicy(Qt.NoFocus)
            layout.addWidget(button)
        self.reset_button = QToolButton()
        self.reset_button.setText("Reset layout")
        self.reset_button.setToolTip("Put every group back where the canvas lays it out")
        self.reset_button.setFocusPolicy(Qt.NoFocus)
        self.reset_button.clicked.connect(self.reset.emit)
        layout.addWidget(self.reset_button)
        self.show_zoom(1.0)

    def show_reset(self, moved: bool) -> None:
        """Offer Reset layout only once a group has been moved."""
        self.reset_button.setVisible(moved)
        self.adjustSize()
        self.moved_sideways.emit()

    def show_zoom(self, zoom: float) -> None:
        """Say how far in the canvas is."""
        self.level.setText(f"{round(zoom * 100)}%")


class NewButton(QPushButton):
    """The New request button, beside the zoom controls."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__("+  New request", parent)
        self.setToolTip("A new request in the group nearest the middle of the view (N)")
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {palette.HIGHLIGHT};
                color: {palette.ON_HIGHLIGHT};
                border: 1px solid {palette.HIGHLIGHT};
                border-radius: 10px;
                padding: 8px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {QColor(palette.HIGHLIGHT).lighter(115).name()}; }}
            """
        )


class Minimap(QWidget):
    """The whole canvas, small, with the part on screen outlined. Click or drag to go there.

    `canvas` is asked for `arrangement_bounds()`, `minimap_items()` (frames and cards as
    rectangles) and `visible_rect()`, and told `look_at(point)`.
    """

    WIDTH, HEIGHT = 220, 150
    MARGIN = 10

    def __init__(self, canvas, parent: QWidget) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click or drag to move around")

    def _mapping(self) -> tuple[QRectF, float, QPointF]:
        """The canvas area shown, the scale it is drawn at, and where its corner goes."""
        bounds = self.canvas.arrangement_bounds().adjusted(-60, -60, 60, 60)
        room = QRectF(self.rect()).adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        scale = min(room.width() / max(bounds.width(), 1), room.height() / max(bounds.height(), 1))
        offset = QPointF(
            room.left() + (room.width() - bounds.width() * scale) / 2,
            room.top() + (room.height() - bounds.height() * scale) / 2,
        )
        return bounds, scale, offset

    def _to_map(self, rect: QRectF, bounds, scale, offset) -> QRectF:
        return QRectF(
            offset.x() + (rect.left() - bounds.left()) * scale,
            offset.y() + (rect.top() - bounds.top()) * scale,
            rect.width() * scale,
            rect.height() * scale,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        """The frames, the cards in their priorities' colours, and the view."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        back = QColor(palette.SURFACE)
        painter.setPen(QPen(QColor(palette.LINE), 1))
        painter.setBrush(back)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        bounds, scale, offset = self._mapping()
        frames, cards = self.canvas.minimap_items()
        painter.setPen(QPen(QColor(palette.LINE), 1))
        painter.setBrush(QColor(palette.WINDOW))
        for rect in frames:
            painter.drawRoundedRect(self._to_map(rect, bounds, scale, offset), 2, 2)
        painter.setPen(Qt.NoPen)
        for rect, priority in cards:
            colour = priority_colour(priority)
            colour.setAlpha(170)
            painter.setBrush(colour)
            painter.drawRect(self._to_map(rect, bounds, scale, offset))
        view = self._to_map(self.canvas.visible_rect(), bounds, scale, offset)
        view = view.intersected(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        fill = QColor(palette.HIGHLIGHT)
        fill.setAlpha(40)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(palette.HIGHLIGHT).lighter(140), 1.5))
        painter.drawRoundedRect(view, 3, 3)
        painter.end()

    def _go(self, event) -> None:
        bounds, scale, offset = self._mapping()
        point = event.position()
        self.canvas.look_at(
            QPointF(
                bounds.left() + (point.x() - offset.x()) / scale,
                bounds.top() + (point.y() - offset.y()) / scale,
            )
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Go to the point clicked."""
        self._go(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """Follow a drag."""
        if event.buttons() & Qt.LeftButton:
            self._go(event)
