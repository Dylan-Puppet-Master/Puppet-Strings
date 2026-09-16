"""Every request example from the proposal, verbatim. Shared by parser and docs tests."""

EXAMPLES = {
    "clinic-assignment": (
        "ON 2026-09-14\nDURING block.clinic_2\nACROSS staff.archery_facilitators\n"
        "TASK activity.archery"
    ),
    "multi-position": "ON 2026-09-14\nDURING block.clinic_2\nTASK activity.gravity_zipline",
    "pin": (
        "ON 2026-09-14\nDURING block.clinic_2\nACROSS staff.dylan\n"
        "TASK activity.gravity_zipline ROLE role.first"
    ),
    "ad-hoc-window": (
        "ON 2026-09-14 .. 2026-09-18\nDURING block.any\nACROSS staff.dylan\n"
        "TASK 'archery maintenance'"
    ),
    "alternative-groups": (
        "ON 2026-09-14 .. 2026-09-15\nDURING block.any\n"
        "ACROSS {staff.james OR (staff.tryne AND staff.paul)}\nTASK 'dance practice' FOR 2h"
    ),
    "training": (
        "ON 2026-09-14 .. 2026-09-18\nDURING block.any\nACROSS staff.david\n"
        "TASK activity.candle_making ROLE role.trainee FOR 2h CONTINUOUS"
    ),
    "forbid": (
        "ON 2026-09-14 .. 2026-09-16\nDURING block.any_clinic\nACROSS staff.dylan\n"
        "FORBID activity.any_ropes"
    ),
    "enjoyment": (
        "DURING block.any_clinic\nACROSS staff.facilitators\n"
        "PREFER activity.any_clinic ~ metric.enjoyment"
    ),
    "variety-week": (
        "ON date.target - 6d .. date.target\nDURING block.any_clinic\nACROSS staff.facilitators\n"
        "AVOID activity.any_clinic PER staff activity BEYOND 1"
    ),
    "variety-day": (
        "DURING block.any_clinic\nACROSS staff.facilitators\n"
        "AVOID activity.any_clinic PER staff activity BEYOND 1"
    ),
    "rotate-ropes": (
        "ON date.session\nDURING block.any_clinic\nACROSS staff.ropes_facilitators\n"
        "AVOID activity.any_ropes ROLE {role.first + role.second} PER staff role BEYOND 3"
    ),
    "workload": (
        "ON date.session\nDURING block.any_clinic\nACROSS staff.facilitators\n"
        "AVOID activity.any_clinic PER staff BEYOND 8"
    ),
    "counselor-hours": (
        "ACROSS EACH staff.counselors\n"
        "TASK 'counselor hour' FOR 1h DURING {block.clinic_1 OR block.clinic_2} AS morning\n"
        "TASK 'counselor hour' FOR 1h DURING {block.clinic_3 OR block.clinic_4} AS afternoon\n"
        "GAP morning afternoon <= 5h"
    ),
    "breaks": (
        "ACROSS EACH {staff.all - staff.directors - staff.counselors}\n"
        "DURING 3 OF block.any\nTASK 'break' FOR 30m"
    ),
    "playstation": "DURING block.playstation\nACROSS {staff.all - staff.directors}\nPREFER FREE",
    "day-off": "ON 2026-09-16\nDURING ALL block.any\nACROSS staff.dylan\nTASK FREE",
}
