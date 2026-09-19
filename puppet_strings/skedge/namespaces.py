"""The namespaces a Skedge name may begin with.

They are plural because each one is a collection of names, and `staff.all` reads no worse
than `blocks.all`. `activities` nests: a clinic is `activities.clinics.archery_1_2` and a
cabin act is `activities.cabin_acts.p4`, so what kind of thing a name stands for is part
of the name rather than something to remember.
"""

STAFF = "staff"
ACTIVITIES = "activities"
BLOCKS = "blocks"
DATES = "dates"
ROLES = "roles"
METRICS = "metrics"

ALL = "all"  # every name in a namespace or one of its branches

# Branches of `activities`. A clinic and a cabin act are staffed the same way but come
# from different sheets and mean different things, so neither can be reached by accident.
CLINICS = "clinics"
CABIN_ACTS = "cabin_acts"

# A Metrics sheet `keys` cell names the fields of one assignment, so it stays singular:
# an assignment has one staff member and one activity. This is how the two line up.
KEY_FIELDS = {STAFF: "staff", ACTIVITIES: "activity", ROLES: "role", DATES: "date", BLOCKS: "block"}
