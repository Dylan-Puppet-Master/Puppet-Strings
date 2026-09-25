"""The canvas: its layout, and the requests edited, made, moved and deleted as cards."""

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from puppet_strings.app.canvas.card import BAD, SUMMARY, UNSAVED  # noqa: E402
from puppet_strings.app.canvas.layout import (  # noqa: E402
    ASIDE_GAP,
    CARD_WIDTH,
    arrange,
    columns,
)
from puppet_strings.app.groups import UNGROUPED  # noqa: E402
from puppet_strings.app.main import MainWindow  # noqa: E402
from puppet_strings.app.requests_model import REQUEST_IDS  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.settings import CANVAS, TABLE, load_settings  # noqa: E402
from puppet_strings.sheets.source import CsvSource  # noqa: E402
from tests.conftest import saved_requests  # noqa: E402

DAILY = "Special daily requests"
WEEKLY = "Special weekly requests"


def overlaps(a, b) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_frames_and_cards_never_overlap():
    groups = [
        ("a", [(f"a{i}", 100 + 37 * (i % 5)) for i in range(25)]),
        ("b", [("b0", 180)]),
        ("c", []),
        ("d", [(f"d{i}", 150) for i in range(7)]),
    ]
    laid = arrange(groups)
    boxes = list(laid.frames.values())
    assert not any(overlaps(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    heights = dict(card for _, cards in groups for card in cards)
    for name, cards in groups:
        frame = laid.frames[name]
        for key, _ in cards:
            x, y = laid.cards[key]
            assert frame.contains(x, y) and frame.contains(x + CARD_WIDTH, y + heights[key])
    cards = [(k, *laid.cards[k]) for k in heights]
    for i, (k1, x1, y1) in enumerate(cards):
        for k2, x2, y2 in cards[i + 1 :]:
            one = type(boxes[0])(x1, y1, CARD_WIDTH, heights[k1])
            other = type(boxes[0])(x2, y2, CARD_WIDTH, heights[k2])
            assert not overlaps(one, other), (k1, k2)


def test_a_bigger_group_gets_more_columns():
    assert columns(0) == columns(1) == 1
    assert columns(4) == 2
    assert columns(25) == 4
    assert columns(10_000) == 10


def test_the_requests_on_no_group_stand_apart_to_the_left():
    groups = [("a", [("a0", 100)]), ("none", [("n0", 100)]), ("b", [("b0", 100)])]
    laid = arrange(groups, aside="none")
    rest = [laid.frames["a"], laid.frames["b"]]
    apart = laid.frames["none"]
    assert apart.y == 0 and apart.x + apart.w + ASIDE_GAP <= min(b.x for b in rest)
    assert list(laid.frames) == ["a", "none", "b"]  # still in the order given
    assert laid.cards["n0"][0] > apart.x
    moved = arrange(groups, {"none": (-500.0, 40.0)}, aside="none")
    assert (moved.frames["none"].x, moved.frames["none"].y) == (-500.0, 40.0)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


OPEN_WINDOWS = []


@pytest.fixture
def window(app, fixtures_copy):
    window = MainWindow(RequestStore(CsvSource(fixtures_copy), Config(tier_seconds_limit=10)))
    OPEN_WINDOWS.append(window)
    window.resize(1500, 900)
    window.show()
    window.wait_for_calendar()
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.reload()
    window.wait_for_load()
    window.show_view(CANVAS)
    settle()
    return window


@pytest.fixture(autouse=True)
def informed(monkeypatch):
    """What information popups said, recorded instead of shown: a real one waits for a click."""
    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda _w, _t, text, *a: said.append(text))
    return said


def settle(ms: int = 450) -> None:
    """Let the refresh run and the cards glide to where they are going."""
    QApplication.processEvents()
    QTest.qWait(ms)


def at(canvas, item, dx=0.5, dy=0.3) -> QPoint:
    """A point on the view over part of an item: by default, across its middle near the top."""
    rect = item.sceneBoundingRect()
    return canvas.mapFromScene(rect.left() + rect.width() * dx, rect.top() + rect.height() * dy)


def show_card(canvas, key: str):
    """Bring a card up to full size in the middle of the view, and return it."""
    card = canvas.cards[key]
    canvas.look(card.sceneBoundingRect().center(), 1.0)
    settle(50)
    return card


def far_off(canvas) -> None:
    """Everything in view, from far enough off that a drag moves whole groups."""
    canvas.fit(animate=False)
    canvas.look(canvas.center(), min(canvas.zoom, SUMMARY * 0.9))
    settle(50)


def empty_spot(canvas) -> QPoint:
    """A point on the view with nothing under it."""
    for x in range(10, canvas.viewport().width(), 40):
        for y in range(10, canvas.viewport().height(), 40):
            point = QPoint(x, y)
            if canvas._hit(point)[0] is None and canvas.childAt(point) is canvas.viewport():
                return point
    raise AssertionError("nowhere empty")


def test_every_request_the_filters_let_through_is_a_card_in_its_groups_frame(window):
    canvas = window.canvas
    assert set(canvas.cards) == {r.id for r in window.store.every if window.proxy.passes(r)}
    assert {UNGROUPED, DAILY, WEEKLY} <= set(canvas.frames)
    frame = canvas.frames[DAILY].sceneBoundingRect()
    assert frame.contains(canvas.cards["breaks"].sceneBoundingRect())
    window.text_filter.setText("counselor")
    settle()
    assert "counselor-hours" in canvas.cards and "cabin-acts" not in canvas.cards


def test_the_view_chosen_is_remembered(window):
    window.canvas_action.trigger()
    assert load_settings().view == CANVAS
    window.table_action.trigger()
    assert not window.on_canvas and load_settings().view == TABLE
    assert window.filter_bar.parent() is window.table.parent()


def test_clicking_a_card_and_typing_edits_it_and_clicking_away_saves_it(window, fixtures_copy):
    canvas = window.canvas
    card = show_card(canvas, "breaks")
    QTest.mouseClick(canvas.viewport(), Qt.LeftButton, pos=at(canvas, card, dy=0.12))
    assert canvas.active is card and canvas.proxy.isVisible()
    canvas.editor.description_edit.setText("Everybody gets their breaks")
    QTest.mouseClick(canvas.viewport(), Qt.LeftButton, pos=empty_spot(canvas))
    assert canvas.active is None
    assert saved_requests(fixtures_copy)["breaks"].description == "Everybody gets their breaks"
    assert canvas.cards["breaks"].draft is None


def test_a_card_that_will_not_validate_keeps_its_changes_unsaved(window, fixtures_copy):
    canvas = window.canvas
    card = show_card(canvas, "breaks")
    before = saved_requests(fixtures_copy)["breaks"]
    canvas.activate(card, "skedge")
    canvas.editor.skedge_edit.setPlainText("REQUEST nobody.at_all DO")
    canvas.deactivate()
    assert saved_requests(fixtures_copy)["breaks"] == before
    assert card.draft is not None and card.status.kind == UNSAVED
    canvas.activate(card)  # it comes back as it was left
    assert canvas.editor.skedge_edit.toPlainText() == "REQUEST nobody.at_all DO"
    QTest.keyClick(canvas.viewport(), Qt.Key_Escape)  # and Escape puts it back as saved
    assert canvas.active is None and card.draft is None
    assert card.shown == before


def test_ctrl_s_saves_without_leaving_the_card(window, fixtures_copy):
    canvas = window.canvas
    card = show_card(canvas, "breaks")
    canvas.activate(card, "description")
    canvas.editor.description_edit.setText("Breaks, saved with Ctrl+S")
    QTest.keyClick(canvas.editor.description_edit, Qt.Key_S, Qt.ControlModifier)
    assert canvas.active is card
    assert saved_requests(fixtures_copy)["breaks"].description == "Breaks, saved with Ctrl+S"
    assert canvas.editor.status.text().startswith("✓ Saved breaks")


def test_n_starts_a_request_in_the_nearest_group_and_it_is_saved_there(window, fixtures_copy):
    canvas = window.canvas
    show_card(canvas, "breaks")
    QTest.keyClick(canvas.viewport(), Qt.Key_N)
    card = canvas.active
    assert card is not None and card.request is None
    canvas.editor.description_edit.setText("Dylan off ropes")
    canvas.editor.skedge_edit.setPlainText(
        "REQUEST staff.dylan NOT DO ANY activities.clinics.ropes ON 2026-09-16"
    )
    canvas.deactivate()
    made = [r for r in saved_requests(fixtures_copy).values() if r.description == "Dylan off ropes"]
    assert len(made) == 1 and made[0].group == DAILY
    assert canvas.cards[made[0].id] is card and not any(
        k.startswith("draft:") for k in canvas.cards
    )


def test_a_frames_button_starts_a_request_and_an_empty_one_just_goes(window, fixtures_copy):
    canvas = window.canvas
    frame = canvas.frames[WEEKLY]
    canvas.look(frame.sceneBoundingRect().center(), 0.8)
    settle(50)
    button = frame.mapRectToScene(frame.button_rect()).center()
    QTest.mouseClick(canvas.viewport(), Qt.LeftButton, pos=canvas.mapFromScene(button))
    assert canvas.active is not None and canvas.active.shown.group == WEEKLY
    count = len(saved_requests(fixtures_copy))
    QTest.keyClick(canvas.viewport(), Qt.Key_Escape)
    assert canvas.active is None and not any(k.startswith("draft:") for k in canvas.cards)
    assert len(saved_requests(fixtures_copy)) == count


def test_dragging_a_card_onto_another_frame_moves_it_to_that_group(window, fixtures_copy):
    canvas = window.canvas
    card = show_card(canvas, "breaks")
    weekly = canvas.frames[WEEKLY].sceneBoundingRect()
    middle = (card.sceneBoundingRect().center() + weekly.center()) / 2
    canvas.look(middle, 0.22)  # near enough to make cards out, so a drag moves a card
    settle(50)
    assert not canvas.far
    start = at(canvas, card)
    target = at(canvas, canvas.frames[WEEKLY], dy=0.1)
    assert canvas.viewport().rect().contains(target)
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    for step in range(1, 11):
        QTest.mouseMove(canvas.viewport(), start + (target - start) * step / 10)
    assert canvas.frames[WEEKLY].target
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=target)
    settle()
    assert saved_requests(fixtures_copy)["breaks"].group == WEEKLY
    frame = canvas.frames[WEEKLY].sceneBoundingRect()
    assert frame.contains(canvas.cards["breaks"].sceneBoundingRect())
    assert canvas.active is None  # a drag is not a click


def test_dragging_the_canvas_pans_it(window):
    canvas = window.canvas
    canvas.look(canvas.arrangement_bounds().center(), 0.5)
    spot = empty_spot(canvas)
    before = canvas.center()
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=spot)
    QTest.mouseMove(canvas.viewport(), spot + QPoint(30, 0))
    QTest.mouseMove(canvas.viewport(), spot + QPoint(100, 0))
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=spot + QPoint(100, 0))
    assert canvas.center().x() == pytest.approx(before.x() - 100 / 0.5, abs=3)


def test_delete_asks_then_deletes_the_cards_picked(window, fixtures_copy, monkeypatch):
    canvas = window.canvas
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    canvas.cards["breaks"].setSelected(True)
    canvas.cards["playstation-availability"].setSelected(True)
    canvas.setFocus()
    QTest.keyClick(canvas.viewport(), Qt.Key_Delete)
    settle()
    left = saved_requests(fixtures_copy)
    assert "breaks" not in left and "playstation-availability" not in left
    assert "breaks" not in canvas.cards


def test_a_request_picked_in_the_errors_pane_is_opened_on_the_canvas(window):
    canvas = window.canvas
    window.text_filter.setText("zzz nothing matches")
    settle()
    assert "breaks" not in canvas.cards
    window.show_request("breaks")
    assert canvas.active is canvas.cards["breaks"]


def test_names_go_into_the_card_being_edited(window):
    canvas = window.canvas
    canvas.activate(show_card(canvas, "breaks"), "skedge")
    canvas.editor.skedge_edit.setPlainText("")
    window.insert_name("staff.dylan")
    assert canvas.editor.skedge_edit.toPlainText() == "staff.dylan"


def test_a_broken_request_says_so_on_its_card(window):
    canvas = window.canvas
    breaks = canvas.cards["breaks"].request
    window.store.save(replace(breaks, skedge="REQUEST staff.nobody FREE"), "breaks")
    window._requests_changed()
    assert canvas.cards["breaks"].status.kind == BAD


def test_suggestions_open_under_the_text_cursor_on_the_card(window):
    canvas = window.canvas
    card = show_card(canvas, "breaks")
    canvas.look(card.sceneBoundingRect().center(), 1.4)
    canvas.activate(card, "skedge")
    edit = canvas.editor.skedge_edit
    edit.moveCursor(QTextCursor.End)
    QTest.keyClicks(edit, " dyl")
    popup = edit.completer.popup()
    assert popup.isVisible()
    cursor = edit.viewport().mapTo(canvas.editor, edit.cursorRect().bottomLeft())
    under = canvas.viewport().mapToGlobal(
        canvas.mapFromScene(canvas.proxy.mapToScene(QPointF(cursor)))
    )
    assert (popup.pos() - under).manhattanLength() <= 4
    popup.hide()


def type_keys(box, text):
    """Type into a box as a person does: each key to whatever has the keyboard just then."""
    for key in text:
        QTest.keyClicks(QApplication.activePopupWidget() or box, key)


def test_the_suggestions_stay_open_while_typing_and_enter_takes_one(window):
    canvas = window.canvas
    canvas.activate(show_card(canvas, "breaks"), "skedge")
    edit = canvas.editor.skedge_edit
    edit.setPlainText("REQUEST ")
    edit.moveCursor(QTextCursor.End)
    popup = edit.completer.popup()
    shown = []
    for key in "dylan":
        type_keys(edit, key)
        shown.append(popup.isVisible())
    assert shown == [False, True, True, True, True]  # from two letters on, and every key
    QTest.keyClick(popup, Qt.Key_Return)  # the first is picked already
    assert edit.toPlainText() == "REQUEST staff.dylan" and not popup.isVisible()


class Dropped:
    """Stands in for QDrag: rather than wait on the platform, drops at once on one spot."""

    def __init__(self, source):
        self.data = None

    def setMimeData(self, data):  # noqa: N802
        self.data = data

    def setPixmap(self, pixmap):  # noqa: N802
        pass

    def setHotSpot(self, point):  # noqa: N802
        pass

    def exec(self, *actions):
        widget, point = Dropped.onto
        drop(widget, point, self.data)
        return Qt.MoveAction


def drop(widget, point, data) -> bool:
    """Drag data in over a point of a widget and let go, as the platform would."""
    args = (point, Qt.MoveAction, data, Qt.LeftButton, Qt.NoModifier)
    for event in (QDragEnterEvent(*args), QDragMoveEvent(*args)):
        QApplication.sendEvent(widget, event)
    let_go = QDropEvent(QPointF(point), *args[1:])
    QApplication.sendEvent(widget, let_go)
    return let_go.isAccepted()


def test_a_card_dragged_off_the_canvas_onto_the_groups_pane_moves_to_that_group(
    window, fixtures_copy, monkeypatch
):
    canvas = window.canvas
    groups = window.groups.list
    row = next(
        groups.item(i) for i in range(groups.count()) if groups.item(i).data(Qt.UserRole) == WEEKLY
    )
    Dropped.onto = (groups.viewport(), groups.visualItemRect(row).center())
    monkeypatch.setattr("puppet_strings.app.canvas.view.QDrag", Dropped)
    card = show_card(canvas, "breaks")
    start = at(canvas, card)
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), start + QPoint(20, 0))
    QTest.mouseMove(canvas.viewport(), QPoint(-30, start.y()))  # past the canvas's left edge
    settle()
    assert saved_requests(fixtures_copy)["breaks"].group == WEEKLY
    assert canvas.frames[WEEKLY].sceneBoundingRect().contains(canvas.cards["breaks"].pos())
    assert canvas.press is None and not canvas.dragging


def test_a_request_dragged_in_lands_in_the_frame_it_is_dropped_on(window, fixtures_copy):
    canvas = window.canvas
    canvas.fit(animate=False)
    settle(50)
    data = QMimeData()
    data.setData(REQUEST_IDS, b"breaks")
    assert drop(canvas.viewport(), at(canvas, canvas.frames[WEEKLY], dy=0.6), data)
    settle()
    assert saved_requests(fixtures_copy)["breaks"].group == WEEKLY


def drag(canvas, start: QPoint, end: QPoint) -> None:
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    for step in range(1, 11):
        QTest.mouseMove(canvas.viewport(), start + (end - start) * step / 10)
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    settle()


def test_from_far_off_a_drag_moves_the_whole_group_and_it_stays_moved(window, fixtures_copy):
    canvas = window.canvas
    far_off(canvas)
    assert canvas.far
    frame = canvas.frames[DAILY]
    card = canvas.cards["breaks"]
    frame_was, card_was = QPointF(frame.pos()), QPointF(card.pos())
    start = at(canvas, card)
    drag(canvas, start, start + QPoint(0, 60))  # picked up by a card, but the group moves
    moved = QPointF(0, 60 / canvas.zoom)
    assert (frame.pos() - (frame_was + moved)).manhattanLength() < 2
    assert (card.pos() - (card_was + moved)).manhattanLength() < 2
    assert saved_requests(fixtures_copy)["breaks"].group == DAILY  # no card changed group
    assert load_settings().frames[DAILY] == pytest.approx((frame.pos().x(), frame.pos().y()))
    assert canvas.zoom_bar.reset_button.isVisibleTo(canvas.zoom_bar)

    canvas.relayout(animate=False)  # it stays put however often the canvas lays out
    assert (frame.pos() - (frame_was + moved)).manhattanLength() < 2

    canvas.zoom_bar.reset_button.click()
    settle()
    assert (frame.pos() - frame_was).manhattanLength() < 2
    assert load_settings().frames == {}
    assert not canvas.zoom_bar.reset_button.isVisibleTo(canvas.zoom_bar)


def test_from_far_off_clicking_a_card_still_opens_it(window):
    canvas = window.canvas
    far_off(canvas)
    card = canvas.cards["breaks"]
    QTest.mouseClick(canvas.viewport(), Qt.LeftButton, pos=at(canvas, card))
    assert canvas.active is card


def test_close_up_a_drag_on_a_frame_pans_rather_than_moving_the_group(window):
    canvas = window.canvas
    frame = canvas.frames[DAILY]
    canvas.look(frame.sceneBoundingRect().center(), 0.8)
    settle(50)
    was = QPointF(frame.pos())
    spot = next(
        QPoint(x, y)
        for x in range(10, canvas.viewport().width(), 20)
        for y in range(10, canvas.viewport().height(), 20)
        if canvas._hit(QPoint(x, y)) == ("frame", frame)
    )
    before = canvas.center()
    drag(canvas, spot, spot + QPoint(0, 80))
    assert frame.pos() == was
    assert canvas.center().y() < before.y()


def test_the_camera_shows_everything_until_it_is_moved(window):
    canvas = window.canvas
    middle = canvas.arrangement_bounds().center()
    assert (canvas.center() - middle).manhattanLength() < 10
    window.text_filter.setText("counselor")  # what there is to show changes
    settle()
    assert (canvas.center() - canvas.arrangement_bounds().center()).manhattanLength() < 10
    canvas.zoom_by(2.0)
    moved = canvas.center()
    window.text_filter.setText("")
    settle()
    assert canvas.center() == moved  # moved by hand, it stays put
    canvas.fit(animate=False)
    assert canvas.following


def test_the_minimap_opens_out_under_the_pointer(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    minimap = window.canvas.minimap
    corner = minimap.geometry().bottomRight()
    assert minimap.size() == minimap.SMALL
    minimap.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    settle(300)
    assert minimap.size() == minimap.LARGE
    assert minimap.geometry().bottomRight() == corner  # grown from its corner
    minimap.leaveEvent(None)
    settle(300)
    assert minimap.size() == minimap.SMALL
