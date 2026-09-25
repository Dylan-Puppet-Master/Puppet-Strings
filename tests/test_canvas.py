"""The canvas: its layout, and the requests edited, made, moved and deleted as cards."""

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from puppet_strings.app.canvas.card import BAD, UNSAVED  # noqa: E402
from puppet_strings.app.canvas.layout import CARD_WIDTH, arrange, columns  # noqa: E402
from puppet_strings.app.groups import UNGROUPED  # noqa: E402
from puppet_strings.app.main import MainWindow  # noqa: E402
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
    canvas.look(canvas.arrangement_bounds().center(), 0.3)
    settle(50)
    start = at(canvas, card)
    target = at(canvas, canvas.frames[WEEKLY], dy=0.5)
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
