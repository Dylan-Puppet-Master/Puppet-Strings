# Skedge reference

Skedge is the language requests are written in. A request is one declaration: a few lines
of clauses that select assignments and say what must, must not, should or should not
happen to them.

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
| `date` | `date.target`, `date.session`, `date.monday` … `date.sunday` |
| `role` | `role.first`, `role.second`, `role.third`; `role.lifeguard`, `role.lifeguard_2`; `role.shadow`, `role.scaffolded`, `role.trainee` |
| `metric` | Metric tables, such as `metric.enjoyment` |

`role.trainee` resolves per staff member: checked off or needing a scaffold becomes
`scaffolded`; needing a shadow or no checkoff becomes `shadow`.

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

`FOR` changes `DURING`: the solver picks any set of the blocks whose lengths add up to the
duration, across the `ON` dates. `CONTINUOUS` requires adjacent blocks on one date.

### FORBID

No assignment matching every clause may exist. Selectors filter, so quantifiers are not
allowed.

### PREFER and AVOID

Each matching assignment adds (`PREFER`) or subtracts (`AVOID`) its score. `~ metric.x`
uses the metric's value for the assignment, normalized to 0–1 against the metric's
declared scale. Neither verb can be `MUST_HAPPEN`.

### AVOID … PER … BEYOND

`PER <fields>` groups matching assignments (fields: `staff`, `activity`, `role`, `date`,
`block`). `BEYOND n` lets the first `n` in each group go free; each further one costs 1.
`ON` sets the window: no `ON` counts within a day, `ON date.session` across the session,
`ON date.target - 6d .. date.target` across a rolling week. Published assignments in the
window are counted. `~` cannot combine with `PER`.

### GAP

`GAP a b <= 5h` requires task `b` to start after task `a` ends with at most five hours
between. `>=` and `==` work too; `GAP a b >= 0m` is plain ordering. Both labels must be
tasks that occupy one block.

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
- `FORBID`, `PREFER` or `AVOID` with a quantifier
- `PREFER` or `AVOID` at `MUST_HAPPEN`, or a weight on a `MUST_HAPPEN` request
- a zero or negative weight
- `PER` on a verb other than `AVOID`, or `BEYOND` below 1
- `~` with `PER`, or `~` on a verb other than `PREFER` or `AVOID`
- `FOR` with `DURING ALL`, or on a verb other than `TASK`
- `ACROSS` with `ALL`, `OF` or `AND` on a clinic without `ROLE`
- a date offset applied to a set of dates
- a `GAP` label that is undefined, defined twice, or on a multi-block task
- a clause given both on a verb's line and on a shared line
- `ROLE` on an ad hoc or `FREE` target, or `FORBID FREE`

## Examples

Names below are those of the sample data in `tests/fixtures`; the test suite validates
every example on this page against it.

### Clinic assignment

Archery during clinic 2, run by a counselor. The Offerings sheet generates a request like
this for every offered clinic, at `CLINIC` priority.

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

Each counselor gets a counselor hour during clinic 1 or 2 and another during clinic 3 or
4, no more than five hours apart. `ON` is omitted, so this applies every day.

```skedge
ACROSS EACH staff.counselor
TASK 'counselor hour' DURING {block.clinic_1 OR block.clinic_2} AS morning
TASK 'counselor hour' DURING {block.clinic_3 OR block.clinic_4} AS afternoon
GAP morning afternoon <= 5h
```

Priority `MUST_HAPPEN`.

### Non-counselor breaks

Each non-director, non-counselor staff member takes three 30-minute breaks per day.

```skedge
ACROSS EACH {staff.all - staff.director - staff.counselor}
DURING 3 OF block.break_slots
TASK 'break'
```

Priority `MUST_HAPPEN`.

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

## Grammar

The grammar the parser uses, in Lark syntax, is `puppet_strings/skedge/grammar.lark`.
