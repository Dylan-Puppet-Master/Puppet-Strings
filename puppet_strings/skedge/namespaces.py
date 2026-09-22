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
MAPPINGS = "mappings"

ALL = "all"  # every name in a namespace or one of its branches

# Branches of `activities`. A clinic and a cabin act are staffed the same way but come
# from different sheets and mean different things, so neither can be reached by accident.
CLINICS = "clinics"
CABIN_ACTS = "cabin_acts"

# What a mapping key may name: any namespace but `mappings` itself.
KEY_NAMESPACES = (STAFF, ACTIVITIES, BLOCKS, DATES, ROLES)
