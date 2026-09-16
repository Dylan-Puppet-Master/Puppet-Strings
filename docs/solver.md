# How the solver decides

## Priorities

| Priority | Behavior |
|---|---|
| `MUST_HAPPEN` | Hard. If the hard requests cannot all hold, the report names the conflicting ids and no schedule is produced. |
| `CLINIC` | Soft, first tier. The offered clinics. An unstaffable clinic is reported instead of blocking the schedule. |
| `HIGH`, `MEDIUM`, `LOW` | Soft, in that order. |

Soft tiers are solved one after another: the `CLINIC` score is maximized and then fixed as
a floor, then `HIGH`, and so on. No amount of `LOW` satisfaction outweighs one `HIGH`
request. After the last tier, the solver drops any assignment no request asked for.

## Scores within a tier

| Request | Contribution |
|---|---|
| `TASK`, `FORBID` | `+1` if satisfied |
| `PREFER` | `+` the sum of matched assignments' scores |
| `AVOID` | `−` the sum of matched assignments' scores |
| `AVOID … PER … BEYOND n` | `−` the number of assignments past each group's allowance |

Each contribution is multiplied by the request's weight. A metric score is the sheet value
normalized against the metric's declared scale, so on a 1–5 scale a 5 is worth 1 and a 3 is
worth 0.5. An assignment to a `(DBL)` clinic counts once, not once per block.

## The variety-versus-enjoyment trade

Both requests are `MEDIUM`. `clinic-enjoyment` prefers clinics by `metric.enjoyment` at
weight 1. `clinic-variety` avoids repeating a clinic within a rolling week at weight 0.5.

Dylan ran archery yesterday. Today the solver can put him on archery (enjoyment 5) or
candle making (enjoyment 3):

| Choice | Enjoyment | Variety | Total |
|---|---|---|---|
| Archery | 1 × 1.0 = 1.0 | 0.5 × −1 = −0.5 | 0.5 |
| Candle making | 1 × 0.5 = 0.5 | 0 | 0.5 |

A tie. A repeat wins only when the repeated clinic is rated more than 2 points higher. With
a variety weight of 1 no repeat ever wins on enjoyment alone; with 0.25 a repeat wins at 2
or more points higher.

To choose a weight, ask "how many points of enjoyment is one repeat worth giving up?",
divide by the scale's range (4 on a 1–5 scale), and use that as the variety weight.

## What the solver enforces on its own

These come from the sheets and never need a request:

1. No one holds two assignments in overlapping blocks.
2. A position is filled only by someone checked off on its skill with a high enough RAL.
3. Each offered clinic is a `CLINIC` request; a clinic runs fully staffed or not at all.
4. A water clinic's `LG_Required` lifeguards are extra positions beyond its facilitators,
   each needing the `LIFEGUARD` skill at RAL 5.
5. Trainees never fill a position. A shadow needs the clinic fully staffed; a scaffolded
   trainee needs a position holder who is a trainer on that skill. One trainee per clinic.
6. A `(DBL)` clinic keeps the same staff across both of its blocks.

## The report

After each solve the report lists every soft request that was not satisfied, every
deferrable task that was put off, and, if the hard requests conflict, their ids. It also
notes if a tier hit its time limit, in which case that tier's score may not be optimal.
Raise `time_limit_seconds` in `config.toml` if that happens often.
