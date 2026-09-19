"""The colours the printed clinic schedule is painted with.

Two rows of colours, both light enough to read black text on, and both meant to be
edited. Change a string here and the next publish uses it; nothing else needs touching.

`BLOCK_COLOURS` tells the clinic blocks apart: the first clinic column of the day takes
the first colour, the second the second, and so on, wrapping round if a day ever has more
clinic blocks than there are colours. `CATEGORY_COLOURS` does the same for the activity
categories on Clinic_Data, in the order that sheet lists them, so a category keeps one
colour down the whole left-hand column.
"""

BLOCK_COLOURS = (
    "#e8f0fe",  # blue
    "#e6f4ea",  # green
    "#fef7e0",  # yellow
    "#fce8e6",  # red
    "#f3e8fd",  # purple
    "#e4f7fb",  # cyan
)

CATEGORY_COLOURS = (
    "#cfe2ff",  # blue
    "#cdeeda",  # green
    "#ffeab3",  # amber
    "#f9d2cd",  # coral
    "#e3d5f7",  # violet
    "#c9e9f2",  # teal
    "#e7dfd0",  # sand
    "#dedede",  # grey
)


def colour(palette: tuple[str, ...], index: int) -> str:
    """The index'th colour of a palette, wrapping round when it runs out."""
    return palette[index % len(palette)]
