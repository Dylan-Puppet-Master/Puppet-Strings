"""The namespaces a Skedge name may begin with.

They are plural because each one is a collection of names, and a namespace or branch
written on its own is the whole collection: `staff` is everyone at camp, `blocks` every
block and `dates.session_4` every date of session 4. `activities` nests: a clinic is
`activities.clinics.archery_1_2` and a cabin act is `activities.cabin_acts.at_cabin_act.p4`,
so what kind of thing a name stands for is part of the name rather than something to
remember.
"""

STAFF = "staff"
ACTIVITIES = "activities"
BLOCKS = "blocks"
DATES = "dates"
ROLES = "roles"
MAPPINGS = "mappings"

NAMESPACES = (STAFF, ACTIVITIES, BLOCKS, DATES, ROLES, MAPPINGS)

WHOLE = ""  # the name of a namespace or branch itself: everything under it
ALL = "all"  # the category the sheets file every staff member at camp and every block under

# Branches of `activities`. A clinic and a cabin act are staffed the same way but come
# from different sheets and mean different things, so neither can be reached by accident.
CLINICS = "clinics"
CABIN_ACTS = "cabin_acts"

# The two kinds of cabin act, under `activities.cabin_acts`: most run in the cabin act
# block, and a few the board moves to rest hour. Each of the day's acts is under one of
# them by its cabin: `activities.cabin_acts.at_cabin_act.p4`. Beside them, each checkbox on
# the board names the acts it is ticked on: `activities.cabin_acts.level_2_on_ground`.
AT_CABIN_ACT = "at_cabin_act"
AT_REST_HOUR = "at_rest_hour"

# The day's Offerings tab, under `activities.clinics`: each clinic in the block it is offered
# in, `activities.clinics.offerings.clinic_2.archery_1_2`, so one name says what runs and when.
OFFERINGS = "offerings"

# What a mapping key may name: any namespace but `mappings` itself.
KEY_NAMESPACES = (STAFF, ACTIVITIES, BLOCKS, DATES, ROLES)


def written(namespace: str, name: str) -> str:
    """A name as it is typed: `staff.dylan`, or `staff` for the whole namespace."""
    return f"{namespace}.{name}" if name else namespace
