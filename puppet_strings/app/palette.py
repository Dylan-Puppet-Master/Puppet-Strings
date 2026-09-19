"""The colours the window uses, in one place, as plain strings.

Three of them carry meaning rather than decoration and are used in more than one pane:
`GOOD` for a request that is valid or saved, `BAD` for one that is broken or contradicted,
and `QUIET` for a note beside either. Keeping them here is what makes the red under the
editor and the red in the conflicts pane the same red.
"""

GOOD = "#1b6f3b"  # valid, saved, a camp day
BAD = "#b00020"  # an error, a contradiction
QUIET = "#6b6b6b"  # a note, a reason, anything said in passing

# A span shades every day between its ends, so this is a large block of colour rather than
# a sprinkle: neutral grey stays out of the way where a tint of green did not.
CAMP_DAY = "#e8eaed"  # the calendar's shading for a day the Calendar sheet covers
CLASH = "#fdeef0"  # the conflicts pane's shading for one collision

# the Skedge editor's highlighting, which is decoration rather than meaning
KEYWORD = "#1f4e9c"
NAME = GOOD
STRING = "#8a4b08"
NUMBER = "#6a2c8f"
COMMENT = "#808080"
