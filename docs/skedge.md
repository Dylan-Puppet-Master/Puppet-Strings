# Skedge reference

Skedge is the language requests are written in. A request is one declaration: a few lines
of clauses that select assignments and say what must, must not, should or should not
happen to them.

This page is the readable version, with worked examples. For the exact rules, including
the grammar and every error the validator reports, see the
[Skedge specification](spec.md).

## The model

An **assignment** is one staff member doing one activity in one role in one block on one
date. The solver decides, for every possible assignment, whether it happens. A declaration
selects some assignments and states one thing about them:

| Verb | Meaning |
|---|---|
| `TASK` | Some selected assignment(s) must exist |
| `FORBID` | No selected assignment may exist |
| `PREFER` | Selected assignments earn points |
| `AVOID` | Selected assignments, or repeats of them, cost points |
| `GAP` | Two labeled tasks must be separated by a bounded amount of time |

## Lexical rules

- Dates are `2026-06-14`. Durations are `30m`, `2h`, `1.5h`. Day offsets are `6d`.
- Names are `namespace.identifier` in lowercase `snake_case`. Sheet values become
  identifiers by the rule in [The sheets](sheets.md). `puppet-strings names` lists them all.
- Ad hoc tasks are single-quoted: `'archery maintenance'`.
- `#` starts a comment.
- Keywords are uppercase.
- Braces `{}` go around any expression with an operator (`OR`, `AND`, `+`, `-`, `&`).
  Parentheses group inside braces.

## Namespaces

| Namespace | Contents |
|---|---|
| `staff` | Staff members, staff categories, `staff.all`, `staff.clinic_trainers` |
| `activity` | Clinics and their categories (`activity.ropes`), plus `activity.any_clinic` |
| `block` | Blocks and block categories, plus `block.any` |
| `date` | `date.target`, `date.session`, weekdays and their ordinals (see below) |
| `role` | `role.first`, `role.second`, `role.third`; `role.lifeguard`, `role.lifeguard_2`; `role.shadow`, `role.scaffolded`, `role.trainee` |
| `metric` | Metric tables, such as `metric.enjoyment` |

`role.trainee` resolves per staff member: checked off or needing a scaffold becomes
`scaffolded`; needing a shadow or no checkoff becomes `shadow`.

### Dates

| Name | Holds |
|---|---|
| `date.target` | The date being scheduled. |
| `date.session` | Every date of the target's session. |
| `date.monday` … `date.sunday` | Every date of the session falling on that weekday. |
| `date.first_monday` … `date.sixth_sunday` | That one occurrence within the session. |
| `date.last_monday` … `date.last_sunday` | The final occurrence within the session. |

A weekday name holds every matching date of the session, so the quantifier says which you
mean: `ON date.monday` is "one Monday", `ON EACH date.monday` is "every Monday". That is
how a recurring weekly request is written.

An ordinal name exists only if the session reaches it. A one-week session has a
`date.first_thursday` but no `date.second_thursday`, and naming one that does not exist is
a validation error rather than a request that silently never fires.

## Selectors

A selector is the argument of `ON`, `DURING`, `ACROSS`, `ROLE`, or a verb.

**Sets.** Names produce sets. `+` is union, `-` difference, `&` intersection, `..` an
inclusive date range. A single date may be offset by days: `date.target - 6d`.

**Quantifiers** go before a plain set:

| Quantifier | Meaning |
|---|---|
| `ANY` (default) | one of them |
| `ALL` | all of them together |
| `n OF` | exactly `n` distinct items |
| `EACH` | a separate copy of the declaration per item |

**`OR` and `AND`** build alternatives: `{staff.james OR (staff.sarah AND staff.paul)}` means
James alone, or Sarah and Paul together. A quantifier cannot be applied to an expression
containing `OR` or `AND`.

## Clauses

| Clause | Required | Default |
|---|---|---|
| `ON <dates>` | no | every date of the session, one copy per date |
| `DURING <blocks>` | yes | |
| `ACROSS <staff>` | no | `staff.all` |
| `ROLE <roles>` | no | all positions (run the whole clinic) |
| `FOR <duration> [CONTINUOUS]` | no | the chosen blocks' full length |
| `AS <label>` | no | |
| `~ <metric>` | no | every assignment scores 1 |
| `PER <fields> BEYOND <n>` | no | (`AVOID` only) |

A clause on the same line as a verb applies to that verb only. A clause on a line with no
verb applies to every verb. A verb cannot get the same clause from both places.

## Verbs

### TASK

The target is an activity, an ad hoc `'string'`, or `FREE`. The solver chooses one
alternative for each of `ON`, `DURING`, `ACROSS` and `ROLE`; every chosen staff member
works the task in every chosen block on every chosen date.

For a clinic without `ROLE`, the task means "run this clinic": every position is filled
from the `ACROSS` pool. With `ROLE`, only that position or trainee role is filled.

Without `FOR`, a task fills its whole block. `FOR <duration>` lets a task take part of a
block: `TASK 'break' FOR 30m` is a 30-minute break somewhere inside one block, and the
Staff View labels the rest of the block `DYOW/WPs`. Several partial tasks can share a
block. The solver places a partial task at the start of its block unless a `GAP` or
another task moves it.

With `FOR`, `DURING` means:

| `DURING` | Meaning with `FOR d` |
|---|---|
| a plain set (default `ANY`) | any blocks whose used time adds up to `d`, the last one used partially |
| `n OF <set>` | `n` separate blocks, each holding the full duration `d` |
| with `CONTINUOUS` | adjacent blocks on one date, all filled except the last |

Published past dates count toward the duration.

### FORBID

No assignment matching every clause may exist. Selectors filter, so `ALL` and `n OF` have
nothing to choose and are errors. `EACH` still works, and still splits the declaration.

### PREFER and AVOID

Each matching assignment adds (`PREFER`) or subtracts (`AVOID`) its score. `~ metric.x`
uses the metric's value for the assignment, normalized to 0–1 against the metric's
declared scale; an assignment the metric has no row for is worth that metric's `default`.
Neither verb can be `MUST_HAPPEN`.

Selectors filter here, so `ALL` and `n OF` are errors. `EACH` is allowed and still splits
the declaration, which matters with `PER`: `ACROSS EACH staff.facilitators` gives each
person their own allowance, while `ACROSS staff.facilitators` makes the pool share one.

Preferring a set of blocks and avoiding everything outside it say the same thing, so
`PREFER 'break' DURING block.meals` and `AVOID 'break' DURING {block.any - block.meals}`
give the same schedule. Write whichever reads better.

A quoted task happens only where a `TASK` asks for it, which is what keeps those two
readings in step: a preference cannot buy extra occurrences of a task beyond the ones
requested. It follows that a `PREFER`, `AVOID` or `FORBID` naming a quoted task that no
`TASK` asks for is an error rather than a line that quietly does nothing, which also
catches a misspelled task name.

### Staff working together

`AND` means "together" everywhere in Skedge, and on `FORBID`, `PREFER` and `AVOID` that
gives pairing. `ACROSS {staff.james AND staff.paul}` matches the two of them **as a
group**: one match per clinic instance (same activity, block and date) where both hold an
assignment, whatever positions they hold. So `AVOID` keeps two people off the same clinic,
`PREFER` puts them on it, and `FORBID` rules the pairing out. More than two names work the
same way, and `ACROSS {staff.james + staff.paul}` (union, not `AND`) still matches each of
them separately.

Because `AND` selects a group of staff, it is only meaningful in `ACROSS` on these verbs;
using it in `ON`, `DURING`, `ROLE` or the target is a validation error. A metric keyed by
`staff` cannot score a group, since the group has no single staff member.

### AVOID … PER … BEYOND

`PER <fields>` groups matching assignments (fields: `staff`, `activity`, `role`, `date`,
`block`). `BEYOND n` lets the first `n` in each group go free; each further one costs 1.
`ON` sets the window: no `ON` counts within a day, `ON date.session` across the session,
`ON date.target - 6d .. date.target` across a rolling week. Published assignments in the
window are counted. `~` cannot combine with `PER`.

### GAP

`GAP a b <= 5h` requires task `b` to start after task `a` ends with at most five hours
between, measured from the tasks' real times: a `FOR 1h` task that ends at 10:30 may sit
at the end of a 09:15–10:30 block. `>=` and `==` work too; `GAP a b >= 0m` is plain
ordering. Both labels must be tasks for one staff member (use `ACROSS EACH`) that occupy
one block each.

## Time horizon

The solver schedules the target date. Past dates with a published schedule are fixed and
count toward `BEYOND` allowances and `FOR` hours. Future dates select nothing. A `TASK`
whose window includes future dates is **deferrable**: optional today with a small nudge to
do it early, enforced on the window's last date. A window entirely in the past is dropped.

## Validation errors

Each error carries a line and column. The validator rejects:

- a name that does not exist in its namespace
- a verb with no `DURING`
- a quantifier applied to an expression containing `OR` or `AND`
- `FORBID`, `PREFER` or `AVOID` with `ALL` or `n OF`, which choose rather than filter
- `PREFER` or `AVOID` at `MUST_HAPPEN`, or a weight on a `MUST_HAPPEN` request
- a zero or negative weight
- `PER` on a verb other than `AVOID`, or `BEYOND` below 1
- `~` with `PER`, or `~` on a verb other than `PREFER` or `AVOID`
- `~` with a staff-keyed metric on a verb whose `ACROSS` selects a group
- `AND` outside `ACROSS` on `FORBID`, `PREFER` or `AVOID`
- `FORBID`, `PREFER` or `AVOID` on a quoted task that no `TASK` asks for
- `FOR` with `DURING ALL`, or on a verb other than `TASK`
- `ACROSS` with `ALL`, `OF` or `AND` on a clinic without `ROLE`
- a date offset applied to a set of dates
- a `GAP` label that is undefined, defined twice, or on a task with `ALL`, `OF` or `AND`
- a clause given both on a verb's line and on a shared line
- `ROLE` on an ad hoc or `FREE` target, or `FORBID FREE`

## Examples

Names below are those of the sample data in `tests/fixtures`; the test suite validates
every example on this page against it.

### Clinic assignment

Archery during clinic 2, run by a counselor. **Load offerings** creates a request like
this (without `ACROSS`) for every offered clinic, at `CLINIC` priority, tagged `generated`.

```skedge
ON 2026-09-16
DURING block.clinic_2
ACROSS staff.counselor
TASK activity.archery_1_2
```

Priority `CLINIC`.

### Multi-position clinic

Gravity zip line needs a 1st and a 2nd. No `ACROSS` or `ROLE`: both positions are filled
from eligible staff.

```skedge
ON 2026-09-16
DURING block.clinic_2
TASK activity.gravity_zip_line
```

Priority `CLINIC`.

### Pinning a staff member to a position

```skedge
ON 2026-09-16
DURING block.clinic_2
ACROSS staff.rob
TASK activity.gravity_zip_line ROLE role.first
```

Priority `MUST_HAPPEN`.

### Ad hoc task in a date window

Dylan does archery maintenance during any block sometime this week. Deferrable until the
last date.

```skedge
ON 2026-09-14 .. 2026-09-18
DURING block.any
ACROSS staff.dylan
TASK 'archery maintenance'
```

Priority `LOW`.

### Alternative groups with non-continuous hours

James alone, or Sarah and Paul together, practice the campfire dance for two total hours
over two days.

```skedge
ON 2026-09-16 .. 2026-09-17
DURING block.any
ACROSS {staff.james OR (staff.sarah AND staff.paul)}
TASK 'dance practice' FOR 2h
```

Priority `MEDIUM`.

### Training

Cam VL is trained on candle making for two continuous hours this week. `role.trainee`
resolves to shadow or scaffolded from the Skills sheet, and the trainee is additional to
the clinic's positions.

```skedge
ON 2026-09-14 .. 2026-09-18
DURING block.any
ACROSS staff.cam_vl
TASK activity.candle_making ROLE role.trainee FOR 2h CONTINUOUS
```

Priority `HIGH`.

### Keeping someone off an activity

```skedge
ON 2026-09-14 .. 2026-09-16
DURING block.any_clinic
ACROSS staff.dylan
FORBID activity.ropes
```

Priority `MUST_HAPPEN`.

### Facilitators run clinics they enjoy

```skedge
DURING block.any_clinic
PREFER activity.any_clinic ~ metric.enjoyment
```

Priority `MEDIUM`, weight `1`.

### Clinic variety over a rolling week

Shares a tier with the enjoyment request so the two trade off; see
[How the solver decides](solver.md).

```skedge
ON date.target - 6d .. date.target
DURING block.any_clinic
AVOID activity.any_clinic PER staff activity BEYOND 1
```

Priority `MEDIUM`, weight `0.5`.

### No repeated clinic within a day

`ON` is omitted, so groups are counted per day.

```skedge
DURING block.any_clinic
AVOID activity.any_clinic PER staff activity BEYOND 1
```

Priority `HIGH`.

### Rotate ropes positions

```skedge
ON date.session
DURING block.any_clinic
ACROSS staff.ropes_level_2
AVOID activity.ropes ROLE {role.first + role.second} PER staff role BEYOND 3
```

Priority `LOW`, weight `1`.

### Balance clinic workload

```skedge
ON date.session
DURING block.any_clinic
AVOID activity.any_clinic PER staff BEYOND 8
```

Priority `MEDIUM`, weight `0.25`.

### Counselor hours with a maximum gap

Each counselor gets a one-hour counselor hour during clinic 1 or 2 and another during
clinic 3 or 4, no more than five hours apart. `ON` is omitted, so this applies every day.
The hour takes part of a 75-minute clinic block; the rest shows as `DYOW/WPs`.

```skedge
ACROSS EACH staff.counselor
TASK 'counselor hour' FOR 1h DURING {block.clinic_1 OR block.clinic_2} AS morning
TASK 'counselor hour' FOR 1h DURING {block.clinic_3 OR block.clinic_4} AS afternoon
GAP morning afternoon <= 5h
```

Priority `MUST_HAPPEN`.

### Non-counselor breaks

Each non-director, non-counselor staff member takes three 30-minute breaks per day, in
three different blocks. A break in a clinic block keeps that person off clinics in it.

```skedge
ACROSS EACH {staff.all - staff.director - staff.counselor}
DURING 3 OF block.any
TASK 'break' FOR 30m
```

Priority `MUST_HAPPEN`.

### Breaks at meal times

Where those breaks land. There are still three of them, wherever the meal blocks are.

```skedge
ACROSS EACH {staff.all - staff.director - staff.counselor}
DURING {block.any - block.meals}
AVOID 'break'
```

Writing it with `EACH`, like the request it steers, gives each person their own reading of
the rule. That is the same thing here, and different as soon as `PER` is involved.

Priority `HIGH`. Weight: `2`.

### Playstation availability

As many non-directors as possible are free during the playstation block. Each free staff
member adds to the score; the staff view marks them `Available`.

```skedge
DURING block.playstation
ACROSS {staff.all - staff.director}
PREFER FREE
```

Priority `HIGH`.

### Day off

```skedge
ON 2026-09-16
DURING ALL block.any
ACROSS staff.dylan
TASK FREE
```

Priority `MUST_HAPPEN`.

### Something every Monday

`EACH` makes a separate copy per Monday of the session, so this happens on all of them.
Written with `ON date.monday` instead, it would happen on one Monday.

```skedge
ON EACH date.monday
DURING block.clinic_1
ACROSS staff.audrey
TASK 'staff meeting' FOR 30m
```

Priority `HIGH`.

### Something on the second Thursday of the session

```skedge
ON date.second_thursday
DURING block.clinic_4
ACROSS ALL staff.director
TASK 'mid-session review'
```

Priority `MEDIUM`.

### Keeping two staff off the same clinic

James and Paul are matched as a group, so this costs a point only when both are on one
clinic. `FORBID` in place of `AVOID` would rule it out outright, at the price of leaving a
clinic unstaffed when they are the only two available.

```skedge
DURING block.any_clinic
ACROSS {staff.james AND staff.paul}
AVOID activity.any_clinic
```

Priority `HIGH`. Weight: `2`.

### Putting two staff on the same clinic

```skedge
DURING block.any_clinic
ACROSS {staff.rob AND staff.vic}
PREFER activity.ropes
```

Priority `LOW`.

## Grammar

The grammar the parser uses is in the [specification](spec.md#4-grammar), and in
`puppet_strings/skedge/grammar.lark`.
