"""The canvas: every request as a card, in its group's frame, on a surface to zoom and pan.

It is the table and the editor at once. The filters decide which cards are out; a card is
edited by clicking it and typing, and saved when you click away (or press Ctrl+S). A card
that will not validate is not lost when you click away: it keeps its changes, says it is
unsaved, and waits. Escape puts a card back the way it was saved.

Getting about:

*   scroll to zoom, at the pointer; drag the empty canvas (or with the middle button, or
    with Space held) to pan; the minimap in the corner goes wherever it is clicked
*   F shows everything, Ctrl+1 is actual size, + and − zoom
*   drag a card onto another group's frame, or onto the groups pane, to move it there;
    Shift-click or Shift-drag a box to pick several, and Delete to delete them
*   drag a frame by its title to put the group somewhere else; Reset layout, beside the
    zoom, puts every group back
*   N, a frame's New request button, or a double-click inside a frame starts a request

The window talks to it much as it talks to the request editor: `saved` goes out as the
editor's does, and `saved_as` and `not_saved` come back.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from itertools import count
from math import floor, log

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSizeF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QDrag, QPainter, QTransform
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
)

from puppet_strings.app import palette
from puppet_strings.app.canvas.card import (
    BAD,
    INSET,
    NOTE,
    OK,
    SUMMARY,
    UNSAVED,
    WARNING,
    CardEditor,
    CardItem,
    Status,
)
from puppet_strings.app.canvas.frame import GroupFrame
from puppet_strings.app.canvas.layout import CARD_WIDTH, Arrangement, arrange
from puppet_strings.app.canvas.overlays import Minimap, NewButton, ZoomBar
from puppet_strings.app.facets import resolve_request
from puppet_strings.app.groups import ALL, UNGROUPED, clean, same_group
from puppet_strings.app.request_table import BESIDE, drag_token
from puppet_strings.app.requests_model import REQUEST_IDS, request_ids
from puppet_strings.model import Dataset, Priority, Request
from puppet_strings.settings import load_settings, save_settings

LEAST, MOST = 0.04, 2.5  # how far out and in the canvas zooms
STEP = 1.2  # one click of + or −
DRAG = 5  # pixels the pointer moves before a press is a drag rather than a click
EDIT_ZOOM = 1.0  # a card clicked from further out than this is brought up to it
BACKGROUND = QColor("#15181c")
DOT = QColor("#2c323a")
RANKS = {p: i for i, p in enumerate(Priority)}


class Canvas(QGraphicsView):
    """The requests as cards in frames. See the module docstring for what it does."""

    saved = Signal(object, object)  # request, original id: as RequestEditor.saved
    deleted = Signal(str)  # the card being edited asked to be deleted
    delete_requested = Signal(list)  # the ids of the cards picked, with Delete pressed
    moved = Signal(list, str)  # ids dropped on a group's frame, and the group

    def __init__(self, store, shown: Callable[[Request], bool]) -> None:
        self.canvas_scene = QGraphicsScene()
        super().__init__(self.canvas_scene)
        self.store = store
        self.shown = shown  # whether the filters let a request through
        self.dataset: Dataset | None = None
        self.cards: dict[str, CardItem] = {}
        self.frames: dict[str, GroupFrame] = {}
        self.arrangement = Arrangement({}, {})
        self.placed = dict(load_settings().frames)  # groups dragged somewhere of their own
        self.frame_drag = None
        self.group_keys: dict[str, str] = {}  # each group's name as compared, to its name
        self.problems: dict[str, Status] = {}  # what the errors pane says about each request
        self.active: CardItem | None = None  # the card the form is on
        self.saving: CardItem | None = None  # the card whose save the window is handling
        self.stale = True  # the store changed while the canvas was not on screen
        self.fitted = False  # the camera has been put somewhere sensible
        self.zoom = 1.0
        self.press = None  # what the mouse went down on, and where
        self.dragging: list[CardItem] = []
        self.drag_from: dict[str, QPointF] = {}
        self.panning = False
        self.space = False
        self.drafts = count(1)
        self.motion: QParallelAnimationGroup | None = None
        self.camera: QVariantAnimation | None = None

        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setBackgroundBrush(BACKGROUND)
        self.canvas_scene.setSceneRect(-60000, -60000, 120000, 120000)

        self.editor = CardEditor()
        self.editor.saved.connect(self._editor_saved)
        self.editor.deleted.connect(self._editor_deleted)
        self.editor.grown.connect(self._editor_grown)
        # The suggestions under the Skedge and the requester are windows of their own, which
        # Qt puts where it thinks the box is; on a card on a zoomed canvas, it is not there.
        self.suggestions = {
            self.editor.skedge_edit.completer.popup(): self._under_skedge_cursor,
            self.editor.requester_completer.popup(): self._under_requester,
        }
        for popup in self.suggestions:
            popup.installEventFilter(self)
        self.proxy = QGraphicsProxyWidget()
        self.proxy.setWidget(self.editor)
        self.proxy.setZValue(5)
        self.proxy.hide()
        self.canvas_scene.addItem(self.proxy)
        self.regrow = QTimer(self)  # lays the cards out again once a card stops growing
        self.regrow.setSingleShot(True)
        self.regrow.setInterval(120)
        self.regrow.timeout.connect(lambda: self.relayout(animate=True))

        self.zoom_bar = ZoomBar(self)
        self.zoom_bar.zoom_in.connect(lambda: self.zoom_by(STEP))
        self.zoom_bar.zoom_out.connect(lambda: self.zoom_by(1 / STEP))
        self.zoom_bar.actual_size.connect(lambda: self.fly_to(self.center(), 1.0))
        self.zoom_bar.fit.connect(self.fit)
        self.zoom_bar.reset.connect(self.reset_layout)
        self.zoom_bar.show_reset(bool(self.placed))
        self.minimap = Minimap(self, self)
        self.new_button = NewButton(self)
        self.new_button.clicked.connect(lambda: self.new_card(self.nearest_group()))
        self.hint = QLabel(
            "Scroll to zoom · drag to pan · click a card to edit · N for a new request",
            self,
        )
        self.hint.setStyleSheet(
            f"color: {palette.QUIET}; background: {palette.SURFACE};"
            f"border: 1px solid {palette.LINE}; border-radius: 10px; padding: 6px 10px;"
        )
        self.hinted = False  # the hint goes once the canvas has been moved about
        # On the view, not its viewport: scrolling the viewport would carry them off with it.
        for overlay in (self.zoom_bar, self.minimap, self.new_button, self.hint):
            overlay.raise_()
        self.zoom_bar.moved_sideways.connect(self._place_overlays)
        self.horizontalScrollBar().valueChanged.connect(self.minimap.update)
        self.verticalScrollBar().valueChanged.connect(self.minimap.update)

    # -- what the window tells it ---------------------------------------------------------

    def set_dataset(self, dataset: Dataset | None, groups: list[str]) -> None:
        """Validate against this day, and offer its names."""
        self.dataset = dataset
        self.editor.set_dataset(dataset, groups)

    def show_problems(self, conflicts, errors) -> None:
        """Take what the errors pane found, to show on each card it is about."""
        clashes: dict[str, set[str]] = {}
        for conflict in conflicts:
            for request_id in conflict.requests:
                clashes.setdefault(request_id, set()).update(conflict.requests)
        problems: dict[str, list[str]] = {}
        for error in errors:
            problems.setdefault(error.request, []).append(error.message)
        self.problems = {}
        for request_id, others in clashes.items():
            others = others - {request_id}
            self.problems[request_id] = Status(
                BAD, f"Conflicts with {', '.join(sorted(others))}" if others else "In a conflict"
            )
        for request_id, messages in problems.items():
            more = f" (and {len(messages) - 1} more)" if len(messages) > 1 else ""
            self.problems.setdefault(request_id, Status(WARNING, messages[0] + more))
        for card in self.cards.values():
            card.set_status(self.status_of(card))

    def refresh(self) -> None:
        """Catch up with the store and the filters: add, update and drop cards, then lay out.

        Nothing is done while the canvas is off screen; it catches up when it is shown.
        """
        if not self.isVisible():
            self.stale = True
            return
        self.stale = False
        wanted = {r.id: r for r in self.store.every if self.shown(r)}
        for card in [c for c in self.cards.values() if c.request_id]:
            request = self._stored(card.request_id)
            if card is self.active or card.draft is not None:
                if request is None and card is not self.active:
                    self._drop(card)
                elif request is not None:
                    self._follow(card, request)
                continue
            if card.request_id not in wanted:
                self._drop(card)
        for request_id, request in wanted.items():
            card = self.cards.get(request_id)
            if card is None:
                card = CardItem(request_id, request)
                self._add(card)
            else:
                card.set_request(request)
        for card in self.cards.values():
            card.set_status(self.status_of(card))
        self.relayout(animate=self.fitted)
        if not self.fitted and self.cards:
            self.fit(animate=False)

    def _stored(self, request_id: str) -> Request | None:
        return next((r for r in self.store.every if r.id == request_id), None)

    def _follow(self, card: CardItem, request: Request) -> None:
        """A card being edited, or holding changes, whose request changed underneath it.

        Only the group can change that way — by a drag onto another frame — so the group
        is what is carried over onto the card's changes and into the form.
        """
        card.set_request(request)
        if card.draft is not None:
            card.set_draft(replace(card.draft, group=request.group))
        if card is self.active:
            self.editor.show_group(request.group)

    def showEvent(self, event) -> None:  # noqa: N802
        """Catch up with whatever changed while the table was being shown."""
        super().showEvent(event)
        if self.stale:
            QTimer.singleShot(0, self.refresh)

    def settle(self, saved: Request) -> None:
        """The card whose save is under way was written as `saved`: file it under its id."""
        card = self.saving
        if card is None:
            return
        self.cards.pop(card.key, None)
        card.key = saved.id
        self.cards[saved.id] = card
        card.request = saved
        card.set_draft(None)

    def saved_as(self, request: Request, note: str = "") -> None:
        """The save went through: say so on the card, as the editor says it."""
        card, self.saving = self.saving, None
        if card is not None and card is self.active:
            self.editor.saved_as(request, note)
        elif card is not None:
            stamp = f"Saved at {datetime.now():%H:%M:%S}{note}"
            card.set_status(Status(WARNING if note else OK, stamp))

    def not_saved(self, why: str) -> None:
        """The save was called off: the card keeps its changes, marked unsaved."""
        card, self.saving = self.saving, None
        if card is not None and card is self.active:
            self.editor.not_saved(why)
        elif card is not None:
            card.set_status(self.status_of(card))

    def insert_name(self, text: str) -> None:
        """Put a name into the Skedge of the card being edited, if there is one."""
        if self.active is not None:
            self.editor.insert_name(text)

    def reveal(self, request_id: str) -> bool:
        """Open a request's card for editing, bringing it on even if the filters hide it."""
        card = self.cards.get(request_id)
        if card is None:
            request = self._stored(request_id)
            if request is None:
                return False
            card = CardItem(request_id, request)
            card.set_status(self.status_of(card))
            self._add(card)
            self.relayout(animate=False)
        self.scene().clearSelection()
        card.setSelected(True)
        self.activate(card)
        return True

    def focus_group(self, group: str) -> None:
        """Show one group's frame, or everything for `All requests`."""
        if group == ALL:
            self.fit()
            return
        frame = next((f for key, f in self.frames.items() if same_group(key, group)), None)
        if frame is not None:
            self.fly_to_rect(frame.sceneBoundingRect())

    # -- cards ----------------------------------------------------------------------------

    def _add(self, card: CardItem, fade: bool = True) -> None:
        self.cards[card.key] = card
        if self.far:
            card.setCursor(Qt.OpenHandCursor)
        self.canvas_scene.addItem(card)
        if not fade:
            return
        card.setOpacity(0.0)
        fade = QPropertyAnimation(card, b"opacity", self)
        fade.setDuration(220)
        fade.setEndValue(1.0)
        fade.start(QPropertyAnimation.DeleteWhenStopped)

    def _drop(self, card: CardItem) -> None:
        """Take a card off the canvas, fading it out."""
        self.cards.pop(card.key, None)
        if card is self.active:
            self._detach()
        card.setSelected(False)
        card.setEnabled(False)
        fade = QPropertyAnimation(card, b"opacity", self)
        fade.setDuration(180)
        fade.setEndValue(0.0)
        fade.finished.connect(lambda: card.scene() and self.canvas_scene.removeItem(card))
        fade.start(QPropertyAnimation.DeleteWhenStopped)

    def status_of(self, card: CardItem) -> Status:
        """What a card's bottom line should say."""
        if card.draft is not None:
            error = self._error_in(card.draft)
            return Status(UNSAVED, f"Unsaved: {error}" if error else "Unsaved changes")
        request = card.request
        if self.dataset is None:
            return Status(NOTE, "Load a date to check this request")
        facet = self.store.facet(request)
        if not facet.valid:
            return Status(BAD, facet.error)
        if request.id in self.problems:
            return self.problems[request.id]
        target = self.dataset.target
        if (request.scope and not request.scope.covers(target)) or not facet.covers(target):
            return Status(NOTE, f"Valid; nothing to do on {target:%a %b} {target.day}")
        return Status(OK, "Valid")

    def _error_in(self, request: Request) -> str | None:
        if self.dataset is None:
            return None
        return resolve_request(request, self.dataset)[0].error

    def group_of(self, card: CardItem) -> str:
        """The key of the frame a card belongs in."""
        return self.group_of_request(card.shown)

    # -- laying out -----------------------------------------------------------------------

    def group_order(self) -> list[str]:
        """The frames, in the groups pane's order; a group only a card knows of goes last."""
        groups = self.store.groups  # worked out from every request, so asked once here
        self.group_keys = {clean(g).lower(): g for g in groups}
        order = [UNGROUPED, *groups]
        for card in self.cards.values():
            if self.group_of(card) not in order:
                order.append(self.group_of(card))
        return order

    def relayout(self, animate: bool = True) -> None:
        """Put every frame and card where the arrangement says, gliding there if asked."""
        order = self.group_order()
        members: dict[str, list[CardItem]] = {g: [] for g in order}
        for card in self.cards.values():
            if card not in self.dragging:
                members[self.group_of(card)].append(card)
        for cards in members.values():
            cards.sort(key=_card_order)
        placed = {
            g: corner
            for g in order
            for name, corner in self.placed.items()
            if same_group(name, g) or name == g
        }
        self.arrangement = arrange(
            [(g, [(c.key, c.height) for c in members[g]]) for g in order], placed
        )
        if self.motion is not None:
            self.motion.stop()
        self.motion = QParallelAnimationGroup(self)
        totals = {g: 0 for g in order}
        for request in self.store.every:
            key = self.group_of_request(request)
            if key in totals:
                totals[key] += 1
        for group in [g for g in self.frames if g not in self.arrangement.frames]:
            self.canvas_scene.removeItem(self.frames.pop(group))
        for group, box in self.arrangement.frames.items():
            frame = self.frames.get(group)
            if frame is None:
                frame = self.frames[group] = GroupFrame(group)
                frame.movable = self.far
                self.canvas_scene.addItem(frame)
                frame.setPos(box.x, box.y)
                frame.set_size(QSizeF(box.w, box.h))
            else:
                self._glide(frame, QPointF(box.x, box.y), animate)
                self._grow(frame, QSizeF(box.w, box.h), animate)
            kind = self.store.group_scopes.of(group) if group != UNGROUPED else ""
            note = f"New requests are scoped to the {kind}" if kind else ""
            if group == UNGROUPED:
                note = "Requests on no group"
            saved = sum(1 for c in members[group] if c.request is not None)
            frame.set_counts(saved, totals.get(group, 0), note)
            frame.empty = not members[group]
        for card in self.cards.values():
            spot = self.arrangement.cards.get(card.key)
            if spot is None:
                continue
            target = QPointF(*spot)
            if not card.placed:
                card.placed = True
                card.setPos(target)  # new: appears where it goes, rather than flying there
            else:
                self._glide(card, target, animate)
        if animate:
            self.motion.start()
        self._place_proxy()
        self.minimap.update()

    def group_of_request(self, request: Request) -> str:
        """The key of the frame a request belongs in."""
        if not request.group:
            return UNGROUPED
        return self.group_keys.get(clean(request.group).lower(), request.group)

    def _glide(self, item, target: QPointF, animate: bool) -> None:
        if not animate or item.pos() == target:
            item.setPos(target)
            return
        move = QPropertyAnimation(item, b"pos")
        move.setDuration(320)
        move.setEasingCurve(QEasingCurve.OutCubic)
        move.setEndValue(target)
        self.motion.addAnimation(move)

    def _grow(self, frame: GroupFrame, size: QSizeF, animate: bool) -> None:
        if not animate or frame.size == size:
            frame.set_size(size)
            return
        grow = QVariantAnimation()
        grow.setDuration(320)
        grow.setEasingCurve(QEasingCurve.OutCubic)
        grow.setStartValue(QSizeF(frame.size))
        grow.setEndValue(size)
        grow.valueChanged.connect(frame.set_size)
        self.motion.addAnimation(grow)

    def arrangement_bounds(self) -> QRectF:
        """Everything laid out, for the minimap and for Fit."""
        box = self.arrangement.bounds
        return QRectF(box.x, box.y, box.w, box.h)

    def minimap_items(self) -> tuple[list[QRectF], list[tuple[QRectF, Priority]]]:
        """The frames and the cards as the arrangement has them, for the minimap."""
        frames = [QRectF(b.x, b.y, b.w, b.h) for b in self.arrangement.frames.values()]
        cards = []
        for key, (x, y) in self.arrangement.cards.items():
            card = self.cards.get(key)
            if card is not None:
                cards.append((QRectF(x, y, CARD_WIDTH, card.height), card.shown.priority))
        return frames, cards

    # -- editing --------------------------------------------------------------------------

    def activate(self, card: CardItem, field: str | None = None, point=None) -> None:
        """Put the form on a card, saving the one it was on, and bring the card into view."""
        if card is not self.active:
            if self.active is not None:
                self.deactivate()
            if card.key not in self.cards:
                return  # it went while the last one was being saved
            self.active = card
            self.editor.show_request(card.shown)
            if card.request is None:
                self.editor.original_id = None
                self.editor.id_label.setText("(assigned on save)")
                self.editor.delete_button.setEnabled(True)
            self.proxy.setParentItem(card)
            self.proxy.setPos(INSET, INSET)
            self.proxy.show()
            card.setZValue(2)
            self.editor.adjustSize()
            card.set_editing(True, self.editor.height())
            self.relayout(animate=True)
            self._bring_into_view(card)
        self.setFocus()
        inside = None
        if point is not None:
            inside = point - QPointF(INSET, INSET)
        self.editor.focus_field(field, inside)

    def deactivate(self, commit: bool = True) -> None:
        """Take the form off the card it is on, saving the card's changes if it has any.

        A card that will not validate keeps its changes and says it is unsaved; Escape
        (`commit` False) throws the changes away instead. A new card with nothing written
        on it just goes.
        """
        card = self.active
        if card is None:
            return
        self.editor.timer.stop()
        draft = self.editor.current()
        if card.request is not None:
            draft = replace(draft, id=card.request.id)
        empty = not (draft.description or draft.skedge.strip() or draft.tags)
        if card.request is None and (empty or not commit):
            self._detach()
            self._drop(card)
            self.relayout(animate=True)
            return
        changed = card.request is None or draft != card.request
        if changed and commit:
            card.set_draft(draft)
            if self.editor.validate():
                self.editor._save()  # the window saves it, and calls back before this returns
        elif not commit:
            card.set_draft(None)
        if self.active is card:
            self._detach()
        card.set_status(self.status_of(card))
        self.relayout(animate=True)

    def _detach(self) -> None:
        """Lift the form off its card, which goes back to being painted."""
        card, self.active = self.active, None
        self.proxy.hide()
        self.proxy.setParentItem(None)
        if card is not None:
            card.setZValue(0)
            card.set_editing(False)
        self.setFocus()

    def _editor_saved(self, request: Request, original_id) -> None:
        """Ctrl+S or Save on the card: hand the request to the window, as the editor would."""
        card = self.active
        if card is None:
            return
        self.saving = card
        if card.request is None:
            original_id = None
        card.set_draft(request)
        self.saved.emit(request, original_id)
        if self.saving is card:  # the window said neither yes nor no
            self.saving = None

    def _editor_deleted(self, request_id: str) -> None:
        """Delete on the card: a new one just goes; a saved one is the window's to delete."""
        card = self.active
        if card is None:
            return
        if card.request is None:
            self.deactivate(commit=False)
            return
        self.deactivate(commit=False)
        self.deleted.emit(card.request.id)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Keep the suggestion lists under the text they suggest for, wherever Qt puts them."""
        place = self.suggestions.get(watched) if hasattr(self, "suggestions") else None
        if place is not None and event.type() in (QEvent.Show, QEvent.Move):
            spot = self._to_screen(place())
            if watched.pos() != spot:
                watched.move(spot)
        return super().eventFilter(watched, event)

    def _under_skedge_cursor(self) -> QPoint:
        """Just under the text cursor in the Skedge, in the form's coordinates."""
        edit = self.editor.skedge_edit
        return edit.viewport().mapTo(self.editor, edit.cursorRect().bottomLeft())

    def _under_requester(self) -> QPoint:
        """Just under the requester box, in the form's coordinates."""
        edit = self.editor.requester_edit
        return edit.mapTo(self.editor, edit.rect().bottomLeft())

    def _to_screen(self, point: QPoint) -> QPoint:
        """A point on the form, as a point on the screen: through the card and the zoom."""
        scene = self.proxy.mapToScene(QPointF(point))
        return self.viewport().mapToGlobal(self.mapFromScene(scene)) + QPoint(0, 3)

    def _editor_grown(self) -> None:
        """The form changed height: so does the card, and the cards below it move."""
        card = self.active
        if card is None:
            return
        height = self.editor.height()
        if abs(card.editor_height - height) > 0.5:
            card.set_editing(True, height)
            self.regrow.start()

    def _place_proxy(self) -> None:
        if self.active is not None:
            self.proxy.setPos(INSET, INSET)

    def new_card(self, group: str) -> None:
        """Start a new request in a group's frame, with the group's own scope."""
        if self.active is not None:
            self.deactivate()
        group = "" if group in (UNGROUPED, ALL) else group
        self.editor.clear(group, self.store.group_scopes.of(group) if group else "")
        draft = self.editor.current()
        card = CardItem(f"draft:{next(self.drafts)}", None, draft)
        card.set_status(Status(UNSAVED, "New request"))
        self._add(card, fade=False)  # there at once: it is what was just asked for
        self.scene().clearSelection()
        card.setSelected(True)
        self.activate(card, "description")

    def nearest_group(self) -> str:
        """The group whose frame is nearest the middle of the view."""
        middle = self.center()
        best, distance = UNGROUPED, float("inf")
        for group, frame in self.frames.items():
            rect = frame.sceneBoundingRect()
            dx = max(rect.left() - middle.x(), 0, middle.x() - rect.right())
            dy = max(rect.top() - middle.y(), 0, middle.y() - rect.bottom())
            if dx * dx + dy * dy < distance:
                best, distance = group, dx * dx + dy * dy
        return best

    # -- the camera -----------------------------------------------------------------------

    def center(self) -> QPointF:
        """The point on the canvas in the middle of the view."""
        return self.mapToScene(self.viewport().rect().center())

    def visible_rect(self) -> QRectF:
        """The part of the canvas on screen."""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def look(self, center: QPointF, zoom: float) -> None:
        """Put the camera over a point, at a zoom."""
        if self.fitted and not self.hinted and self.isVisible():
            self.hinted = True
            self.hint.hide()
        was_far = self.far
        self.zoom = min(max(zoom, LEAST), MOST)
        if self.far != was_far:
            self._show_handles()
        self.setTransform(QTransform.fromScale(self.zoom, self.zoom))
        self.centerOn(center)
        self.zoom_bar.show_zoom(self.zoom)
        self.minimap.update()

    @property
    def far(self) -> bool:
        """Whether cards are only blocks from here, so a drag moves groups, not cards."""
        return self.zoom < SUMMARY

    def _show_handles(self) -> None:
        """Say with the pointer what a drag would pick up: a card, or its whole group."""
        far = self.far
        for card in self.cards.values():
            card.setCursor(Qt.OpenHandCursor if far else Qt.PointingHandCursor)
        for frame in self.frames.values():
            frame.movable = far

    def look_at(self, point: QPointF) -> None:
        """Move straight to a point, at the zoom there is."""
        self._stop_camera()
        self.look(point, self.zoom)

    def zoom_by(self, factor: float, at=None) -> None:
        """Zoom by a factor, keeping the canvas under `at` (a view point) where it is."""
        self._stop_camera()
        at = at if at is not None else QPointF(self.viewport().rect().center())
        anchor = self.mapToScene(at.toPoint())
        new = min(max(self.zoom * factor, LEAST), MOST)
        center = self.center()
        ratio = self.zoom / new
        self.look(anchor + (center - anchor) * ratio, new)

    def fly_to(self, center: QPointF, zoom: float, animate: bool = True) -> None:
        """Glide the camera to a point and a zoom."""
        self._stop_camera()
        if not animate or not self.isVisible():
            self.look(center, zoom)
            return
        start_center, start_zoom = self.center(), self.zoom
        zoom = min(max(zoom, LEAST), MOST)
        self.camera = QVariantAnimation(self)
        self.camera.setDuration(300)
        self.camera.setEasingCurve(QEasingCurve.InOutCubic)
        self.camera.setStartValue(0.0)
        self.camera.setEndValue(1.0)

        def step(t: float) -> None:
            level = start_zoom * (zoom / start_zoom) ** t
            self.look(start_center + (center - start_center) * t, level)

        self.camera.valueChanged.connect(step)
        self.camera.start()

    def fly_to_rect(self, rect: QRectF, animate: bool = True, most: float = 1.0) -> None:
        """Glide until a part of the canvas fills the view, but no nearer than `most`."""
        view = self.viewport().rect()
        margin = 48
        zoom = min(
            (view.width() - 2 * margin) / max(rect.width(), 1),
            (view.height() - 2 * margin) / max(rect.height(), 1),
            most,
        )
        self.fly_to(rect.center(), zoom, animate)

    def fit(self, animate: bool = True) -> None:
        """Show everything."""
        if self.arrangement.frames:
            self.fitted = True
            self.fly_to_rect(self.arrangement_bounds(), animate)

    def _stop_camera(self) -> None:
        if self.camera is not None:
            self.camera.stop()
            self.camera = None

    def _bring_into_view(self, card: CardItem) -> None:
        """Bring a card clicked from far off up to a size to type on; else just on screen."""
        spot = self.arrangement.cards.get(card.key)
        top_left = QPointF(*spot) if spot else card.pos()
        rect = QRectF(top_left, QSizeF(CARD_WIDTH, card.height))
        zoom = self.zoom if self.zoom >= EDIT_ZOOM * 0.8 else EDIT_ZOOM
        view = self.viewport().rect()
        half_w, half_h = view.width() / 2 / zoom, view.height() / 2 / zoom
        visible = QRectF(self.center() - QPointF(half_w, half_h), QSizeF(2 * half_w, 2 * half_h))
        if zoom == self.zoom and visible.adjusted(20, 20, -20, -20).contains(rect):
            return
        center = QPointF(rect.center())
        if rect.height() > 2 * half_h - 80:  # taller than the view: its top, not its middle
            center.setY(rect.top() - 40 + half_h)
        self.fly_to(center, zoom)

    # -- the mouse and the keyboard -------------------------------------------------------

    def _in_editor(self, item) -> bool:
        """Whether an item is the form, or one of its drop-downs."""
        while item is not None:
            if item is self.proxy:
                return True
            item = item.parentItem()
        return False

    def _hit(self, pos):
        """What is under a point of the view, and what it is.

        One of "editor", "card", "button" (a frame's New request), "group" (a group to
        move: from far enough out that cards are blocks, a press anywhere on a frame or its
        cards picks the whole group up), "frame", or None for the bare canvas.
        """
        far = self.far
        for item in self.items(pos):
            if self._in_editor(item):
                return "editor", self.proxy
            if isinstance(item, CardItem):
                if far:
                    frame = self.frames.get(self.group_of(item))
                    return ("group", frame) if frame is not None else ("card", item)
                return "card", item
            if isinstance(item, GroupFrame):
                inside = item.mapFromScene(self.mapToScene(pos))
                if item.on_button(inside) and not far:
                    return "button", item
                return ("group" if far else "frame"), item
        return None, None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Decide what a press is: typing on the form, a card, a button, or the canvas."""
        pos = event.position().toPoint()
        kind, item = self._hit(pos)
        self._stop_camera()
        pan = event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self.space)
        if kind == "editor" and not pan:
            super().mousePressEvent(event)
            return
        self.setFocus()
        self.press = {"pos": pos, "kind": kind, "item": item, "moved": False, "pan": pan}
        if kind == "group":  # a click, rather than a drag, still opens the card it was on
            self.press["card"] = next((i for i in self.items(pos) if isinstance(i, CardItem)), None)
        if pan:
            self.panning = True
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton:
            self.press = None
            return
        if kind in (None, "frame") and event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
            self.press = None
            self.setDragMode(QGraphicsView.RubberBandDrag)
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """Pan, drag cards, or pass the move on."""
        press = self.press
        if press is None:
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint()
        delta = pos - press["pos"]
        if not press["moved"] and delta.manhattanLength() < DRAG:
            return
        first = not press["moved"]
        press["moved"] = True
        if press["pan"] or press["kind"] in (None, "frame"):
            if first:
                self.viewport().setCursor(Qt.ClosedHandCursor)
            last = press.get("last", press["pos"])
            step = pos - last
            press["last"] = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - step.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - step.y())
            return
        if press["kind"] == "group":
            if first:
                self._lift_frame(press["item"])
            self._carry_frame(pos)
            return
        if press["kind"] == "card":
            if first:
                self._lift(press["item"])
            if self.viewport().rect().contains(pos):
                self._carry(pos)
            else:
                self._drag_out()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """Finish whatever the press started."""
        if self.dragMode() == QGraphicsView.RubberBandDrag:
            super().mouseReleaseEvent(event)
            self.setDragMode(QGraphicsView.NoDrag)
            return
        press, self.press = self.press, None
        self.panning = False
        self.viewport().unsetCursor()
        if press is None:
            super().mouseReleaseEvent(event)
            return
        if press["pan"]:
            return
        kind, item = press["kind"], press["item"]
        if kind == "group" and press["moved"]:
            self._set_frame_down(item)
            return
        if self.dragging:
            self._set_down(event.position().toPoint())
            return
        if press["moved"]:
            return
        if kind == "button":
            self.new_card(item.group)
        elif kind == "card":
            self._click_card(item, event)
        elif kind == "group" and press.get("card") is not None:
            self._click_card(press["card"], event)
        elif kind in (None, "frame", "group"):
            self.deactivate()
            self.scene().clearSelection()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Double-click in a frame for a new request there; on the bare canvas, see it all."""
        pos = event.position().toPoint()
        kind, item = self._hit(pos)
        if kind == "frame":
            self.new_card(item.group)
        elif kind == "group":
            self.fly_to_rect(item.sceneBoundingRect())
        elif kind is None:
            self.fit()
        else:
            super().mouseDoubleClickEvent(event)

    def _click_card(self, card: CardItem, event) -> None:
        if event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
            card.setSelected(not card.isSelected())
            return
        if card is self.active:
            return  # its edge, around the form
        self.scene().clearSelection()
        card.setSelected(True)
        point = card.mapFromScene(self.mapToScene(event.position().toPoint()))
        self.activate(card, card.region_at(point), point)

    # -- moving whole groups ---------------------------------------------------------------

    def _members(self, group: str) -> list[CardItem]:
        return [c for c in self.cards.values() if self.group_of(c) == group]

    def _lift_frame(self, frame: GroupFrame) -> None:
        """Pick a group up by its title: the frame, and every card in it."""
        if self.motion is not None:
            self.motion.stop()
        self.frame_drag = {
            "anchor": self.mapToScene(self.press["pos"]),
            "frame": QPointF(frame.pos()),
            "cards": {c: QPointF(c.pos()) for c in self._members(frame.group)},
        }
        frame.setZValue(-5)
        for card in self.frame_drag["cards"]:
            card.setZValue(card.zValue() + 20)
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _carry_frame(self, pos) -> None:
        offset = self.mapToScene(pos) - self.frame_drag["anchor"]
        self.press["item"].setPos(self.frame_drag["frame"] + offset)
        for card, start in self.frame_drag["cards"].items():
            card.setPos(start + offset)
        self.minimap.update()

    def _set_frame_down(self, frame: GroupFrame) -> None:
        """Leave the group where it was put, and remember it there."""
        frame.setZValue(-10)
        for card in self.frame_drag["cards"]:
            card.setZValue(card.zValue() - 20)
        self.frame_drag = None
        self.placed = {g: p for g, p in self.placed.items() if not same_group(g, frame.group)}
        self.placed[frame.group] = (frame.pos().x(), frame.pos().y())
        self._save_placed()
        self.relayout(animate=True)

    def reset_layout(self) -> None:
        """Put every group back where the canvas would lay it out, and forget where they were."""
        self.placed = {}
        self._save_placed()
        self.relayout(animate=True)

    def _save_placed(self) -> None:
        save_settings(replace(load_settings(), frames=dict(self.placed)))
        self.zoom_bar.show_reset(bool(self.placed))

    def _lift(self, card: CardItem) -> None:
        """Pick up a card — and the rest of the selection, if it is part of one."""
        if not card.isSelected():
            self.scene().clearSelection()
            card.setSelected(True)
        self.dragging = [c for c in self.cards.values() if c.isSelected()] or [card]
        self.drag_from = {c.key: QPointF(c.pos()) for c in self.dragging}
        self.drag_anchor = self.mapToScene(self.press["pos"])
        if self.motion is not None:
            self.motion.stop()
        for depth, lifted in enumerate(self.dragging):
            lifted.lifted = True
            lifted.setZValue(10 + depth)
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _carry(self, pos) -> None:
        """Move the cards picked up with the pointer, fanned a little, and light the frame."""
        offset = self.mapToScene(pos) - self.drag_anchor
        lead = self.drag_from[self.dragging[0].key]
        for depth, card in enumerate(self.dragging):
            card.setPos(lead + offset + QPointF(depth * 12, depth * 12))
        under = self._frame_at(self.mapToScene(pos))
        for frame in self.frames.values():
            frame.set_target(frame is under)

    def _frame_at(self, point: QPointF) -> GroupFrame | None:
        found = (f for f in self.frames.values() if f.sceneBoundingRect().contains(point))
        return next(found, None)

    def _put_down(self) -> list[CardItem]:
        """Stop carrying the cards picked up, and return them."""
        cards, self.dragging = self.dragging, []
        for frame in self.frames.values():
            frame.set_target(False)
        for card in cards:
            card.lifted = False
            card.setZValue(2 if card is self.active else 0)
        return cards

    def _set_down(self, pos) -> None:
        """Drop the cards carried: onto another group's frame moves them there."""
        frame = self._frame_at(self.mapToScene(pos))
        cards = self._put_down()
        if frame is not None:
            self._move_to(cards, frame.group)
        self.relayout(animate=True)

    def _move_to(self, cards: list[CardItem], group: str) -> None:
        """Put cards in a group: the saved ones by the window, a new one on the card itself."""
        into = "" if group == UNGROUPED else group
        moving = [c for c in cards if not same_group(c.shown.group, into)]
        for card in [c for c in moving if c.request is None]:
            card.set_draft(replace(card.shown, group=into))
            if card is self.active:
                self.editor.show_group(into)
        saved = [c.request_id for c in moving if c.request is not None]
        if saved:
            self.moved.emit(saved, group)  # the window's refresh lays them out

    def _drag_out(self) -> None:
        """The cards were carried off the canvas: hand them on as a drag the groups pane takes.

        Inside the canvas a card is moved by hand, which is what lets it glide and the
        frames light up; past its edge, the rest of the window only understands a drag.
        So the cards go back to their places and a drag of their ids carries on from the
        pointer: the same drag a table row makes, dropped on a group the same way. A card
        never saved has no id for a drag to carry, and just goes back.
        """
        cards = self._put_down()
        self.press = None
        self.relayout(animate=True)
        ids = [c.request_id for c in cards if c.request is not None]
        if not ids:
            return
        data = QMimeData()
        data.setData(REQUEST_IDS, "\n".join(ids).encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(drag_token(ids, self.font(), self.devicePixelRatioF()))
        drag.setHotSpot(BESIDE)
        drag.exec(Qt.MoveAction)
        self.viewport().unsetCursor()

    # A drag coming in — cards brought back from outside, or table rows — lands on a frame.

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        """Take a drag of requests."""
        if event.mimeData().hasFormat(REQUEST_IDS):
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        """Light the frame a drop would land in; refuse anywhere else."""
        under = self._frame_at(self.mapToScene(event.position().toPoint()))
        for frame in self.frames.values():
            frame.set_target(frame is under)
        if under is None:
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        """Nothing is aimed at any more."""
        for frame in self.frames.values():
            frame.set_target(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        """Move the requests dropped into the frame they were let go over."""
        frame = self._frame_at(self.mapToScene(event.position().toPoint()))
        self.dragLeaveEvent(event)
        if frame is None:
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()
        ids = request_ids(event.mimeData())
        cards = [c for c in self.cards.values() if c.request_id in ids]
        known = {c.request_id for c in cards}
        self._move_to(cards, frame.group)
        others = [i for i in ids if i not in known]  # rows the filters keep off the canvas
        if others:
            self.moved.emit(others, frame.group)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Scroll to zoom at the pointer; a sideways scroll pans."""
        angle = event.angleDelta()
        if angle.x() and not angle.y():
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - angle.x())
            return
        self.zoom_by(1.0015 ** angle.y(), event.position())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """The canvas's keys, or the form's while a card is being edited."""
        key = event.key()
        focus = self.scene().focusItem()
        if self.active is not None and focus is not None and self._in_editor(focus):
            popup = self.editor.skedge_edit.completer.popup()
            if key == Qt.Key_Escape and focus is self.proxy and not popup.isVisible():
                self.deactivate(commit=False)
                return
            super().keyPressEvent(event)
            return
        control = event.modifiers() & Qt.ControlModifier
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self.space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif key == Qt.Key_Escape:
            self.deactivate(commit=False)
            self.scene().clearSelection()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            picked = [c.request_id for c in self.cards.values() if c.isSelected() and c.request]
            if picked:
                self.delete_requested.emit(picked)
        elif key == Qt.Key_N and not control:
            self.new_card(self.nearest_group())
        elif key == Qt.Key_F or (control and key == Qt.Key_0):
            self.fit()
        elif control and key == Qt.Key_1:
            self.fly_to(self.center(), 1.0)
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(STEP)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_by(1 / STEP)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            picked = [c for c in self.cards.values() if c.isSelected()]
            if len(picked) == 1:
                self.activate(picked[0])
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        """Letting go of Space stops panning."""
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.space = False
            self.viewport().unsetCursor()
            return
        super().keyReleaseEvent(event)

    # -- painting and placing -------------------------------------------------------------

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        """A dotted surface, its dots spaced for the zoom so they never turn to a haze."""
        painter.fillRect(rect, BACKGROUND)
        spacing = 32.0
        if spacing * self.zoom < 14:
            spacing *= 4 ** max(0, floor(log(14 / (spacing * self.zoom), 4)) + 1)
        left = floor(rect.left() / spacing) * spacing
        top = floor(rect.top() / spacing) * spacing
        dot = QColor(DOT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot)
        radius = 1.3 / self.zoom
        y = top
        while y < rect.bottom():
            x = left
            while x < rect.right():
                painter.drawEllipse(QPointF(x, y), radius, radius)
                x += spacing
            y += spacing

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Keep the controls in their corners."""
        super().resizeEvent(event)
        self._place_overlays()

    def _place_overlays(self) -> None:
        """The controls along the bottom, clear of the frames' own headers at the top."""
        view = self.viewport().rect()
        margin = 16
        self.zoom_bar.adjustSize()
        self.zoom_bar.move(margin, view.height() - self.zoom_bar.height() - margin)
        middle = self.zoom_bar.geometry().center().y()
        self.new_button.adjustSize()
        self.new_button.move(
            self.zoom_bar.geometry().right() + 10, middle - self.new_button.height() // 2
        )
        self.hint.adjustSize()
        self.hint.move(self.new_button.geometry().right() + 14, middle - self.hint.height() // 2)
        self.minimap.move(
            view.width() - self.minimap.width() - margin,
            view.height() - self.minimap.height() - margin,
        )
        room = self.hint.geometry().right() < self.minimap.x() - 10
        self.hint.setVisible(room and not self.hinted)


def _card_order(card: CardItem) -> tuple:
    """New cards first, then by priority, then by id."""
    request = card.shown
    return (card.request is not None, RANKS.get(request.priority, 99), request.id or "")
