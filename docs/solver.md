# How the solver decides

## Priorities

| Priority | Behavior |
|---|---|
| `MUST_HAPPEN` | Hard. If the hard requests cannot all hold, the report names the conflicting ids and no schedule is produced. |
| `CLINIC` | Soft, first tier. The offered clinics. An unstaffable clinic is reported instead of blocking the schedule. |
| `STABILITY` | Soft, second tier, and only during a [same-day change](same-day.md): keep the published schedule. The solver sets this itself; it cannot be written on a request. |
| `HIGH`, `MEDIUM`, `LOW` | Soft, in that order. |

Soft tiers are solved one after another: the `CLINIC` score is maximized and then fixed as
a floor, then `HIGH`, and so on. No amount of `LOW` satisfaction outweighs one `HIGH`
request. After the last tier, the solver drops any assignment no request asked for.

## Scores within a tier

| Statement | Contribution |
|---|---|
| `REQUEST` | `+1` if the declaration is met (each `EACH_OF` copy on its own) |
| `PREFER <amount> …` | `−` how far the matches are from the amount, in assignments or hours |
| `PREFER … MAXIMIZE metric.x(…)` | `+` the metric's value for each match |
| `PREFER … MINIMIZE metric.x(…)` | `−` the metric's value for each match |

Each contribution is multiplied by the request's weight. A metric score is the sheet value
normalized against the metric's declared scale, so on a 1–5 scale a 5 is worth 1 and a 3 is
worth 0.5. A `(DBL)` clinic is two assignments, one per block.

## The variety-versus-preference trade

Both requests are `MEDIUM`. `clinic-preference` scores clinics by `metric.preference` at
weight 1. `clinic-variety` prefers at most one run of each clinic per person in a rolling
week, at weight 0.5.

Dylan ran archery yesterday. Today the solver can put him on archery (preference 5) or
candle making (preference 3):

| Choice | Preference | Variety | Total |
|---|---|---|---|
| Archery | 1 × 1.0 = 1.0 | 0.5 × −1 = −0.5 | 0.5 |
| Candle making | 1 × 0.5 = 0.5 | 0 | 0.5 |

A tie. A repeat wins only when the repeated clinic is rated more than 2 points higher. With
a variety weight of 1 no repeat ever wins on preference alone; with 0.25 a repeat wins at 2
or more points higher.

To choose a weight, ask "how many points of preference is one repeat worth giving up?",
divide by the scale's range (4 on a 1–5 scale), and use that as the variety weight.

A deferrable `REQUEST`, one that could still be met on a later date, earns a bonus of one
thousandth of a point in the `LOW` tier for what it does today, so it happens early when
nothing else is at stake and never at the expense of another request.

## What the solver enforces on its own

These come from the sheets and never need a request:

1. No one's assignments overlap in time. A clinic fills its block; a `FOR` task takes
   part of a block, and several such tasks can share one block back to back.
2. A position is filled only by someone checked off on its skill with a high enough RAL.
3. A clinic runs only where a `REQUEST … DO` names it. Each offered clinic is such a
   request at `CLINIC` priority, created by **Load offerings**; a clinic runs fully
   staffed or not at all.
4. A water clinic's `LG_Required` lifeguards are extra positions beyond its facilitators,
   each needing the `LIFEGUARD` skill at RAL 5.
5. Trainees never fill a position. A shadow needs the clinic fully staffed; a scaffolded
   trainee needs a position holder who is a trainer on that skill. One trainee per clinic.
6. A `(DBL)` clinic keeps the same staff across both of its blocks.

## The report

**Nothing happens that no request asked for.** A clinic runs only where a `REQUEST … DO`
names it, and a trainee or a quoted task exists only where such a request, or a `REQUEST
AT_LEAST` or `EXACTLY` pattern, selected it. This is built into the model rather than
tidied up afterwards, so it holds however long the solve takes. It is what keeps a
`PREFER` from inflating the amount of work: a preference moves the breaks people already
have and cannot buy anyone another.

**Tidiness.** After the last tier the solver pushes a task shorter than its block to the
start of the block, unless a `GAP` or another task moves it. The Staff View labels the
rest of a partly used block `DYOW/WPs` (the wording is `remainder` under `[views]` in
`config.toml`).

After each solve the report lists every soft request that was not satisfied, every
deferrable request that was put off, every request that was inactive (its dates all past
or all future, or an `EACH_OF` over nothing), and, if the hard requests conflict, their
ids.

It also carries notes about the time limit. Each pass after the first starts from a
schedule that already works, so a pass that runs out of time keeps that schedule and says
so rather than failing the solve:

| Note | Means |
|---|---|
| tier X hit the time limit | That tier's score may not be the best possible. |
| tier X ran out of time | That tier found nothing new; the schedule so far stands. |
| placement pass ran out of time | A task shorter than its block may sit later in it than it needs to. |

Raise `time_limit_seconds` in `config.toml` if the tier notes appear often, or
`tidy_seconds` for the last one. If even the first pass
finds nothing in that time, the solve stops and says so, since there is no schedule to
fall back on.
