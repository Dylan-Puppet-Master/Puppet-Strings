"""Where everything on the canvas goes: each group a frame, each request a card inside it.

No Qt here. The canvas hands over each group's cards as `(key, height)` and gets back where
the frames and the cards sit, which is what lets the arrangement be tested without a window.

A frame's cards are laid out in columns, each card going to whichever column is shortest so
far, the way a pinboard fills: cards differ in height with the length of their Skedge, and
a grid of rows would leave a gap under every short one. How many columns a frame gets grows
with how many cards it holds, so a big group is roughly square rather than a tall strip.
The frames themselves are set in rows, left to right, in the order the groups pane lists
them, wrapping once a row is about as wide as the whole arrangement is tall; the frame of
requests on no group stands apart, off to the right. A frame that
has been dragged somewhere else stays where it was put, with its cards; the rest keep the
places they would have had anyway, so moving one group never shuffles the others.
"""

from dataclasses import dataclass
from math import ceil, sqrt

CARD_WIDTH = 360.0
GAP = 18.0  # between two cards
PAD = 26.0  # between a frame's edge and its cards
HEADER = 70.0  # a frame's title strip
EMPTY = 110.0  # the room an empty frame keeps for its hint
FRAME_GAP = 90.0  # between two frames
ASIDE_GAP = 4 * FRAME_GAP  # between the frames and the one kept apart
MOST_COLUMNS = 10


@dataclass(frozen=True)
class Box:
    """A rectangle in canvas units."""

    x: float
    y: float
    w: float
    h: float

    def contains(self, x: float, y: float) -> bool:
        """Whether a point is inside it."""
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h


@dataclass(frozen=True)
class Arrangement:
    """The frames by group, and the top-left corner of each card by its key."""

    frames: dict[str, Box]
    cards: dict[str, tuple[float, float]]

    @property
    def bounds(self) -> Box:
        """The smallest box around every frame."""
        if not self.frames:
            return Box(0, 0, 0, 0)
        left = min(b.x for b in self.frames.values())
        top = min(b.y for b in self.frames.values())
        right = max(b.x + b.w for b in self.frames.values())
        bottom = max(b.y + b.h for b in self.frames.values())
        return Box(left, top, right - left, bottom - top)


def columns(count: int) -> int:
    """How many columns a frame of this many cards is laid out in."""
    return max(1, min(ceil(sqrt(count / 1.6)), MOST_COLUMNS)) if count else 1


def frame_width(count: int) -> float:
    """How wide a frame of this many cards is."""
    wide = columns(count)
    return 2 * PAD + wide * CARD_WIDTH + (wide - 1) * GAP


def arrange_frame(cards: list[tuple[str, float]]) -> tuple[float, float, dict]:
    """One frame's width and height, and each card's corner relative to the frame's."""
    wide = columns(len(cards))
    heights = [0.0] * wide
    spots = {}
    for key, height in cards:
        shortest = heights.index(min(heights))
        spots[key] = (PAD + shortest * (CARD_WIDTH + GAP), HEADER + heights[shortest])
        heights[shortest] += height + GAP
    inner = max(heights) - GAP if cards else EMPTY
    return frame_width(len(cards)), HEADER + inner + PAD, spots


def arrange(
    groups: list[tuple[str, list[tuple[str, float]]]],
    placed: dict[str, tuple[float, float]] | None = None,
    aside: str | None = None,
) -> Arrangement:
    """Every frame and card, the groups in the order given.

    `placed` is where frames have been moved to by hand, by group: each one's top-left
    corner, which its cards move with. `aside` is a group kept apart, to the right of the
    rest with a wide gap between: the requests on no group, which would otherwise break
    up the rows of the groups that are sorted.
    """
    measured = [(name, *arrange_frame(cards)) for name, cards in groups]
    rows = [m for m in measured if m[0] != aside]
    area = sum(w * h for _, w, h, _ in rows)
    row_width = max([sqrt(area) * 1.5, *(w for _, w, _, _ in rows)], default=0)
    frames: dict[str, Box] = {}
    cards: dict[str, tuple[float, float]] = {}
    x = y = row_height = right = 0.0
    placed = placed or {}

    def put(name: str, left: float, top: float, w: float, h: float, spots: dict) -> None:
        left, top = placed.get(name, (left, top))
        frames[name] = Box(left, top, w, h)
        for key, (cx, cy) in spots.items():
            cards[key] = (left + cx, top + cy)

    for name, w, h, spots in rows:
        if x and x + w > row_width:
            x, y, row_height = 0.0, y + row_height + FRAME_GAP, 0.0
        put(name, x, y, w, h, spots)
        right = max(right, x + w)
        x += w + FRAME_GAP
        row_height = max(row_height, h)
    for name, w, h, spots in measured:
        if name == aside:
            put(name, right + ASIDE_GAP if rows else 0.0, 0.0, w, h, spots)
    return Arrangement({name: frames[name] for name, *_ in measured}, cards)
