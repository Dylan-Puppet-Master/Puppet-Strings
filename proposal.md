# Puppet Strings: A Proposal for Schedule Automation

## High-Level Goal

Create scheduling software that is *maintainable*, *stable*,  *well documented*, and *intuitive*. People other than the original author should be able to understand, use, and modify the software in future years.

## How to Use This Document

This is a blueprint for an AI coding agent. Work proceeds in phases (see "The Task"). Do not write code until the Puppet Master has approved the technical outline.

Where this document states a rule, follow it. Where it marks something as a default awaiting confirmation (see "Unresolved Decisions"), build to the default and list it in the outline's assumptions. Where it is silent, state the assumption in the outline rather than choosing silently.

---

## Camp Augusta Background

### Terminology

- **Clinic**: A facilitated, skill-based activity that campers sign up for the day prior.
- **Offerings**: The list of clinics the Puppet Master decides to offer for a given date, entered on the Offerings sheet.
- **Position**: A staffing slot a clinic requires, such as the 1st and 2nd on a ropes clinic. Positions are ordered, and the order is significant on the printed clinic schedule.
- **Facilitator**: A staff member checked off to fill a clinic position.
- **Cabin Activity**: A time during which all cabins (each comprised of five campers) are given resources to do whatever they want.
- **Playstation**: A facilitated, non-skill-based activity that campers sign up for in the moment.
- **Evening Program (EP)**: A camp-wide game or experience that happens after dinner.
- **Counselor**: A staff member responsible for a cabin.
- **HERO**: A non-counselor staff member.
- **Director**: A senior staff member. Directors are exempt from the legal break requirement.
- **Counselor Hour**: A one-hour period for a counselor, understood as a 30-minute break plus 30 minutes of prep work.
- **Work Projects**: Non-programming work, often scheduled immediately after a 30-minute break.
- **Session**: A period of camp that campers sign up for, lasting one or two weeks.
- **Target Date**: The date a schedule is being generated for, normally the following day.
- **RAL (Risk Assessment Level)**: A rating from 1 (lowest) to 5 (highest). A staff member can lose levels for risky behavior. Risky clinic positions have minimum RAL requirements.
- **Trainee**: A staff member being trained on a clinic. A trainee is always *additional* to the clinic's required positions.
- **Shadow**: A trainee who observes a facilitator running the clinic.
- **Scaffold**: A trainee who facilitates the clinic while a clinic trainer supervises and gives feedback afterward. Only members of the clinic trainer staff category can scaffold. Any checked-off facilitator can be scaffolded.

### The Puppet Master Role

The Puppet Master makes staff schedules. The most time-consuming part is scheduling clinics: the Puppet Master decides which clinics are offered to campers and assigns staff to them.

The Puppet Master also makes staff *available* for the Playstation block. A separate role later assigns available staff to specific playstations. Assigning playstations is out of scope for Puppet Strings.

---

## Everything Is a Request

### What Is a Request?

A request is any constraint on the schedule. It may be soft, such as a preference for facilitators to run clinics they enjoy, or rigid, such as the legal requirement that non-director staff take 30-minute breaks.

Manual adjustments are also requests. To pin a staff member to an assignment, the Puppet Master writes a `MUST_HAPPEN` request rather than editing the output. There is no separate locking feature.

### The Request Data Structure

```
{
.id          = "counselor-hours"
.description = "All counselors get a morning and an afternoon counselor hour"
.skedge      = """
    ACROSS EACH staff.counselors
    TASK 'counselor hour' DURING {block.clinic_1 OR block.clinic_2} AS morning
    TASK 'counselor hour' DURING {block.clinic_3 OR block.clinic_4} AS afternoon
    GAP morning afternoon <= 5h
"""
.priority    = MUST_HAPPEN
.created     = 2026-09-14
}
```

| Field          | Type                | Rules                                                                     |
|----------------|---------------------|---------------------------------------------------------------------------|
| `.id`          | string              | Unique and stable. Used in solver diagnostics.                            |
| `.description` | string              | Natural language. For documentation and debugging.                        |
| `.skedge`      | multi-line string   | A Skedge declaration (see "Skedge Specification").                        |
| `.priority`    | enum                | `MUST_HAPPEN`, `CLINIC`, `HIGH`, `MEDIUM`, `LOW`.                         |
| `.weight`      | positive number     | Default `1`. Exchange rate within a priority tier. Not allowed with `MUST_HAPPEN`. |
| `.created`     | ISO date            | For documentation and debugging.                                          |

Requests are stored as rows in a Requests sheet, one column per field.

### Priorities and Weights

| Priority      | Behavior                                                                                                                                                          |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MUST_HAPPEN` | Hard constraint. If unsatisfiable, the solver reports the conflicting request IDs and produces no schedule.                                                       |
| `CLINIC`      | Soft. Maximized first among soft tiers. Used for staffing offered clinics, so an unstaffable clinic is reported rather than making the whole schedule infeasible. |
| `HIGH`        | Soft, second tier.                                                                                                                                                |
| `MEDIUM`      | Soft, third tier.                                                                                                                                                 |
| `LOW`         | Soft, fourth tier.                                                                                                                                                |

Soft tiers are solved **lexicographically**: maximize the `CLINIC` score, fix that score as a lower bound, maximize `HIGH`, and so on. No amount of `LOW` satisfaction can outweigh a single `HIGH` request.

**Priority decides whether two requests can trade off at all. `.weight` decides the exchange rate when they can.** Requests in different tiers never trade: the higher tier always wins. Requests in the same tier trade according to their weights.

#### Scoring within a tier

A tier's score is the sum of each soft request's contribution times that request's `.weight`:

| Request                  | Contribution                                                 |
| ------------------------ | ------------------------------------------------------------ |
| `TASK`, `FORBID`         | `+1` if satisfied, `0` otherwise                             |
| `PREFER`                 | `+` sum of matched assignment scores                         |
| `AVOID`                  | `−` sum of matched assignment scores                         |
| `AVOID … PER … BEYOND n` | `−` number of assignments past each group's allowance of `n` |

One unit of score is one assignment at the top of a metric's scale, one assignment past an allowance, or one satisfied request.

#### Worked tradeoff: variety versus enjoyment

Both requests are `MEDIUM`:

- `clinic-enjoyment`: `PREFER activity.any_clinic ~ metric.enjoyment`, `.weight = 1`. Enjoyment is rated 1–5, so each point is worth `0.25`.
- `clinic-variety`: `AVOID activity.any_clinic PER staff activity BEYOND 1` over a rolling week, `.weight = 0.5`.

Dylan ran archery yesterday. Today the solver can put him on archery (enjoyment 5) or candle making (enjoyment 3):

| Choice        | Enjoyment        | Variety              | Total   |
|---------------|------------------|----------------------|---------|
| Archery       | `1 × 1.0 = 1.0`  | `0.5 × −1 = −0.5`    | `0.5`   |
| Candle making | `1 × 0.5 = 0.5`  | `0`                  | `0.5`   |

A tie. In general, the solver repeats a clinic only when

```
enjoyment_weight × (normalized_enjoyment_repeat − normalized_enjoyment_alternative) > variety_weight
```

With these weights, a repeat wins only if the repeated clinic is rated **more than 2 points higher**. A variety weight of `1` means no repeat ever wins on enjoyment alone. A variety weight of `0.25` means a repeat wins at 2 or more points higher.

This describes one decision in isolation. In a full schedule, other requests also affect the result, but the weights set the terms of each trade.

To choose a weight, ask: "How many points of enjoyment is one repeat worth giving up?" Divide by the scale's range (4 for a 1–5 scale) and use the result as the variety weight, with enjoyment at `1`.

### Implicit Structural Constraints

These are generated from sheet data on every run. They are never written as requests.

1. **No double booking.** A staff member cannot hold two assignments in blocks that overlap in time.
2. **Eligibility.** A staff member can fill a position only if the Skills sheet shows the required checkoff.
3. **RAL.** A staff member's RAL must meet the RAL listed for the position in Clinic_Data.
4. **Offered clinics are staffed.** Each clinic on the Offerings sheet generates `TASK activity.<clinic>` at `CLINIC` priority for its date and block.
5. **Trainees are additional.** Shadow and scaffolded assignments never fill a required position.
6. **Shadow pairing.** A shadow requires the same clinic instance to be fully staffed.
7. **Scaffold pairing.** A scaffolded trainee requires at least one position holder in the same clinic instance to be a member of `staff.clinic_trainers`.
8. **Trainee capacity.** A clinic instance has at most one trainee unless Clinic_Data specifies otherwise.

The solver creates assignment variables only for combinations that pass rules 2 and 3, which keeps the model small.

---

## Skedge Specification

Skedge is a declarative language for writing requests. It is designed to be read and written by the Puppet Master directly.

### 1. The Underlying Model

Skedge describes constraints over **assignments**. An assignment is a tuple:

```
(staff, activity, role, date, block)
```

The solver creates one boolean variable per eligible tuple. Every declaration selects some tuples and states one of the following about them:

| Verb     | Meaning                                                          | Solver form               |
|----------|------------------------------------------------------------------|---------------------------|
| `TASK`   | Some selected assignment(s) must exist                           | Constraint (hard or soft) |
| `FORBID` | No selected assignment may exist                                 | Constraint (hard or soft) |
| `PREFER` | Selected assignments are rewarded                                | Objective term            |
| `AVOID`  | Selected assignments, or repetitions of them, are penalized      | Objective term            |
| `GAP`    | Two labeled tasks must be separated by a bounded amount of time  | Constraint                |

`TASK`, `FORBID`, `PREFER`, and `AVOID` are **verb lines**. Everything else is a clause that narrows what a verb selects.

### 2. Lexical Rules

- Dates use ISO 8601: `2026-09-14`.
- Durations are a number and unit: `30m`, `2h`, `1.5h`. Date offsets use days: `6d`.
- Names are `namespace.identifier`, written in lowercase `snake_case`.
- Staff names are their identifiers. A sheet name is normalized by lowercasing and replacing spaces with underscores: "Mary Kate" becomes `staff.mary_kate`. Names are reset each season. The validator rejects any two staff members, or a staff member and a staff category, that normalize to the same identifier.
- Ad hoc tasks are single-quoted strings: `'archery maintenance'`.
- `#` starts a comment that runs to the end of the line.
- Keywords are uppercase.
- Braces `{}` are required around any expression containing an operator (`OR`, `AND`, `+`, `-`, `&`). Parentheses group inside braces.

### 3. Namespaces

| Namespace  | Contents                                                                      | Source                           |
| ---------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `staff`    | Staff members, staff categories, and the built-in `staff.all`                 | Staff Categories sheet           |
| `activity` | Clinics, playstations, EPs, and their categories (e.g. `activity.any_clinic`) | Clinic_Data sheet                |
| `block`    | Time blocks, block categories, and the built-in `block.any`                   | Blocks sheet                     |
| `date`     | `date.target`, `date.session`, `date.sunday` … `date.saturday`                | Session calendar                 |
| `role`     | Positions and trainee roles                                                   | Clinic_Data, fixed trainee roles |
| `metric`   | Numeric tables used to score assignments                                      | Metric sheets                    |

#### Roles

Each clinic has ordered positions `role.first`, `role.second`, `role.third`, … in the order its staff columns appear in Clinic_Data.

Trainee roles are fixed:

- `role.shadow`: observes the clinic.
- `role.scaffolded`: facilitates under a clinic trainer who holds one of the positions.
- `role.trainee`: resolves to `role.shadow` or `role.scaffolded` per staff member from their Skills sheet status. No checkoff or "needs shadow" resolves to shadow. Checked off or "needs scaffold" resolves to scaffolded.

### 4. Selectors

A selector is the argument of `ON`, `DURING`, `ACROSS`, `ROLE`, or a verb target. Every selector evaluates to a **list of alternatives**, where each alternative is a set of items that go together.

#### 4.1 Sets

Names and ranges produce sets. Set operators combine them:

| Operator | Meaning               | Example                                    |
|----------|-----------------------|--------------------------------------------|
| `+`      | Union                 | `{staff.counselors + staff.heroes}`        |
| `-`      | Difference            | `{staff.directors - staff.ropes_level_2}`  |
| `&`      | Intersection          | `{staff.counselors & staff.lifeguards}`    |
| `..`     | Date range, inclusive | `2026-09-14 .. 2026-09-18`                 |

Set operators bind tighter than `AND` and `OR`.

A single date may be offset by whole days: `date.target - 6d`. Offsets apply only to a single date followed by a `d` duration; `-` between two sets is always difference.

#### 4.2 Quantifiers

A quantifier precedes a selector that is a plain set (no `OR` or `AND`). It decides how the set becomes alternatives.

| Quantifier      | Alternatives from set `{a, b, c}` | Reading                                     |
|-----------------|-----------------------------------|---------------------------------------------|
| `ANY` (default) | `[a] [b] [c]`                     | One of them                                  |
| `ALL`           | `[a, b, c]`                       | All of them together                         |
| `n OF`          | every combination of `n` items    | Exactly `n` distinct items                   |
| `EACH`          | *(splits the declaration)*        | A separate copy of the declaration per item  |

`EACH` is expanded before solving. `ACROSS EACH staff.counselors` produces one independent declaration per counselor. When several clauses use `EACH`, the copies are the Cartesian product.

#### 4.3 Logical Combinations

`OR` separates alternatives. `AND` joins items within an alternative. Expressions are normalized to disjunctive normal form:

```
{staff.james OR (staff.tryne AND staff.paul)}              ->  [james] [tryne, paul]
{block.cabin_act OR (block.clinic_1 AND block.clinic_2)}   ->  [cabin_act] [clinic_1, clinic_2]
```

A quantifier may not be applied to an expression containing `OR` or `AND`. `{a OR b}` is equivalent to `ANY {a + b}`.

### 5. Clauses

| Clause                        | Required | Default                        |
| ----------------------------- | -------- | ------------------------------ |
| `ON <selector>`               | No       | `ON EACH date.session`         |
| `DURING <selector>`           | Yes      | none                           |
| `ACROSS <selector>`           | No       | `ACROSS staff.all`             |
| `ROLE <selector>`             | No       | see §6.1                       |
| `FOR <duration> [CONTINUOUS]` | No       | the chosen blocks' full length |
| `AS <label>`                  | No       | none                           |
| `~ <metric>`                  | No       | every assignment scores 1      |
| `PER <fields> BEYOND <n>`     | No       | none (`AVOID` only)            |

An omitted `ON` means the declaration applies to *each* date of the active session, not *any* date.

#### Scoping

Clauses may appear in any order on a line, and lines may appear in any order.

- A clause on the **same line as a verb** applies only to that verb.
- A clause on a **line with no verb** applies to every verb in the declaration.
- A verb may not receive the same clause from both places.

### 6. Verbs

#### 6.1 `TASK <target>`

The target is an activity selector, an ad hoc string, or `FREE` (no assignment at all).

For each of `ON`, `DURING`, `ACROSS`, and `ROLE`, the solver chooses exactly one alternative. Every staff member in the chosen `ACROSS` alternative works the task in every block of the chosen `DURING` alternative on every date of the chosen `ON` alternative. Staff grouped with `AND` are scheduled together.

For activities with positions:

- Without `ROLE`, the task means "run this activity": every required position is filled by one staff member from the `ACROSS` pool. The pool quantifier must be `ANY`.
- With `ROLE`, only the selected position or trainee role is filled from the pool.
- A `role.trainee` task attaches to an offered instance of the activity (see "Unresolved Decisions").

Ad hoc strings have no positions, skill requirements, or camper slots. They occupy staff time only. A task occupies the entire chosen block unless `FOR` says otherwise.

`FOR <duration>` changes how `DURING` is satisfied: instead of choosing one alternative, the solver chooses any subset of the `DURING` blocks whose total length is at least the duration. `CONTINUOUS` requires those blocks to be adjacent in time. `FOR` may not be combined with `DURING ALL`.

#### 6.2 `FORBID <target>`

No assignment matching all clauses may exist. Selectors act as filters, so quantifiers other than the default are errors.

#### 6.3 `PREFER <target>` and `AVOID <target>`

No requirement. Each assignment matching all clauses adds its score to the objective (`PREFER`) or subtracts it (`AVOID`). Selectors act as filters. Neither verb may have priority `MUST_HAPPEN`.

The sign lives only in the verb. Weights and metric values are never negative.

##### 6.3.1 Metric Scores: `~`

By default each selected assignment adds 1 point to its tier's objective, multiplied by the request's weight.. `~ <metric>` replaces that weight with a value from a data table:

```
~ metric.enjoyment          # looked up per (staff, activity)
```

A metric is a table keyed by any subset of `staff`, `activity`, `role`, `date`, `block`. The solver looks up each assignment's value using its matching fields.

Each metric sheet declares its scale (for example, 1 to 5). Values are normalized against the declared scale, not the observed data, so `1 → 0.0` and `5 → 1.0`. This keeps the exchange rate between requests fixed when data changes.

The solver is deterministic, so `~` means "weighted in proportion to," not "probability of."

#### 6.4 `GAP <label> <label> <comparison> <duration>`

Requires the second labeled task to start after the first ends, with the time between them satisfying the comparison (`<=`, `>=`, `==`). `GAP a b >= 0m` expresses plain ordering.

#### 6.5 Repetition: `PER <fields> BEYOND <n>`

**The problem.** A plain `AVOID` penalizes every matching assignment equally. `AVOID activity.any_clinic` doesn't encourage variety. It discourages running clinics at all, and every run costs the same whether it is someone's first archery clinic of the week or their fifth.

Variety means the *first* run is fine and *repeats* are not. Expressing that requires two things: counting assignments that belong together, and exempting the first few.

**`PER` says what to count together.** It groups the selected assignments by the listed fields. `PER staff activity` makes one group for each staff member and activity pair: Dylan's archery runs, Dylan's candle making runs, James's archery runs, and so on.

**`BEYOND n` is the allowance.** Within each group, the first `n` assignments cost nothing. Each assignment past the `n`th costs 1.

In plain words:

```
ON date.target - 6d .. date.target
DURING block.any_clinic
AVOID activity.any_clinic PER staff activity BEYOND 1
```

"In the past week, each person may run each clinic once for free. Every additional run of the same clinic by the same person costs 1."

Penalty for one group as its count grows:

| Runs in the group | `BEYOND 1` | `BEYOND 2` |
|-------------------|------------|------------|
| 1                 | 0          | 0          |
| 2                 | 1          | 0          |
| 3                 | 2          | 1          |
| 4                 | 3          | 2          |

`BEYOND 0` would penalize every run, which is the same as a plain `AVOID`. The validator therefore requires `n ≥ 1`.

**Changing the fields changes what kind of variety is measured:**

| Fields           | One group is…                          | Effect                         |
|------------------|----------------------------------------|--------------------------------|
| `staff activity` | A person's runs of one activity        | Variety of clinics per person  |
| `staff role`     | A person's time in one position        | Rotation between 1st and 2nd   |
| `staff date`     | A person's assignments on one day      | Daily workload balance         |
| `staff`          | All of a person's assignments          | Workload balance in the window |

**`ON` sets the window.** Omitting `ON` counts within a single day. `ON date.session` counts across the session. `ON date.target - 6d .. date.target` counts across a rolling week. Assignments from past published schedules in the window are included in the counts.

**Escalating penalties** use stacked requests. A request with `BEYOND 1` at `.weight = 0.5`, plus a second with `BEYOND 2` at `.weight = 1`, makes the second run cost 0.5 and each run after that cost 1.5.

`~` may not be combined with `PER`, since the score is a count.

### 7. Time Horizon

The solver schedules `date.target`. Other dates behave as follows:

- **Past dates** with a published schedule are fixed assignments. They cannot change, but they count toward `AVOID … BEYOND` and toward partially satisfying `TASK` requests (including `FOR` hours already completed).
- **Future dates** select nothing.
- A `TASK` whose `ON` window includes future dates is **deferrable**: if unsatisfied, it is optional on the target date, with a small incentive to schedule it early. On the last date of its window, it is enforced at its priority.
- A `TASK` already satisfied by past published assignments is dropped.
- Windows ignore dates outside the active session.

### 8. Validation Errors

The parser and validator reject a declaration, with line and column, when:

- A name does not exist in its namespace.
- A verb has no `DURING` in scope.
- A quantifier is applied to an expression containing `OR` or `AND`.
- `FORBID`, `PREFER`, or `AVOID` uses a quantifier other than the default.
- `PREFER` or `AVOID` has priority `MUST_HAPPEN`, or `.weight` is set on a `MUST_HAPPEN` request.
- `.weight` is zero or negative.
- `PER` appears without `BEYOND`, `BEYOND` is less than 1, or either appears on a verb other than `AVOID`.
- `~` is combined with `PER`.
- `~` appears on a verb other than PREFER or AVOID.
- `FOR` is combined with `DURING ALL`.
- `ACROSS` has a non-`ANY` quantifier on a positioned activity without `ROLE`.
- A date offset is applied to a set of dates or uses a unit other than `d`.
- A `GAP` references an undefined label, or a label is defined twice.
- A clause is applied to a verb both on its line and from a verb-less line.

### 9. Grammar (Lark EBNF)

```
declaration : _NL* line (_NL+ line)* _NL*
line        : clause+
clause      : on | during | across | role | verb | for_ | label | weight | per | gap

on          : "ON" selector
during      : "DURING" selector
across      : "ACROSS" selector
role        : "ROLE" selector
verb        : VERB target
target      : selector | STRING | FREE
for_        : "FOR" DURATION CONTINUOUS?
label       : "AS" NAME
weight      : "~" ref
per         : "PER" FIELD+ "BEYOND" INT
gap         : "GAP" NAME NAME COMPARISON DURATION

selector    : quantifier? atom
            | "{" expr "}"
            | quantifier "{" setexpr "}"
quantifier  : ANY | ALL | EACH | INT "OF"
expr        : term ("OR" term)*
term        : factor ("AND" factor)*
factor      : setexpr | "(" expr ")"
setexpr     : atom (SETOP atom)*
atom        : date ".." date | date | ref
date        : (DATE | ref) (OFFSET DAYS)?

ref         : NAME ("." NAME)+
VERB        : "TASK" | "FORBID" | "PREFER" | "AVOID"
FREE        : "FREE"
ANY         : "ANY"
ALL         : "ALL"
EACH        : "EACH"
CONTINUOUS  : "CONTINUOUS"
FIELD       : "staff" | "activity" | "role" | "date" | "block"
SETOP       : "+" | "-" | "&"
OFFSET      : "+" | "-"
COMPARISON  : "<=" | ">=" | "=="
DATE        : /\d{4}-\d{2}-\d{2}/
DAYS        : /\d+d/
DURATION    : /\d+(\.\d+)?(m|h)/
STRING      : /'[^']*'/
NAME        : /[a-z_][a-z0-9_]*/

COMMENT     : /#[^\n]*/
_NL         : /\n/
%import common.INT
%import common.WS_INLINE
%ignore WS_INLINE
%ignore COMMENT
```

### 10. Request Examples

#### Clinic assignment

Archery during clinic 2, facilitated by someone from the archery pool. In practice, structural rule 4 generates this from the Offerings sheet.

```
ON 2026-09-14
DURING block.clinic_2
ACROSS staff.archery_facilitators
TASK activity.archery
```
Priority: `CLINIC`

#### Multi-position clinic

Gravity zipline needs a 1st and a 2nd, each a separate checkoff. No `ACROSS` or `ROLE` is needed: both positions are filled from eligible staff.

```
ON 2026-09-14
DURING block.clinic_2
TASK activity.gravity_zipline
```
Priority: `CLINIC`

#### Pinning a staff member to a position

```
ON 2026-09-14
DURING block.clinic_2
ACROSS staff.dylan
TASK activity.gravity_zipline ROLE role.first
```
Priority: `MUST_HAPPEN`

#### Ad hoc task in a date window

Dylan does archery maintenance during any block sometime this week.

```
ON 2026-09-14 .. 2026-09-18
DURING block.any
ACROSS staff.dylan
TASK 'archery maintenance'
```
Priority: `LOW`. Deferrable until 2026-09-18 (§7).

#### Alternative groups with non-continuous hours

James alone, or Tryne and Paul together, practice the campfire dance for two total hours in the next two days.

```
ON 2026-09-14 .. 2026-09-15
DURING block.any
ACROSS {staff.james OR (staff.tryne AND staff.paul)}
TASK 'dance practice' FOR 2h
```
Priority: `MEDIUM`

#### Training

David is trained on candle making for two continuous hours this week.

```
ON 2026-09-14 .. 2026-09-18
DURING block.any
ACROSS staff.david
TASK activity.candle_making ROLE role.trainee FOR 2h CONTINUOUS
```
Priority: `HIGH`. `role.trainee` resolves to shadow or scaffolded from the Skills sheet. David is additional to the clinic's positions.

#### Keeping someone off an activity

```
ON 2026-09-14 .. 2026-09-16
DURING block.any_clinic
ACROSS staff.dylan
FORBID activity.any_ropes
```
Priority: `MUST_HAPPEN`

#### Facilitators run clinics they enjoy

```
DURING block.any_clinic
ACROSS staff.facilitators
PREFER activity.any_clinic ~ metric.enjoyment
```
Priority: `MEDIUM`. Weight: `1`.

#### Clinic variety over a rolling week

```
ON date.target - 6d .. date.target
DURING block.any_clinic
ACROSS staff.facilitators
AVOID activity.any_clinic PER staff activity BEYOND 1
```
Priority: `MEDIUM`. Weight: `0.5`. Shares a tier with the enjoyment request so the two trade off.

#### No repeated clinic within a day

```
DURING block.any_clinic
ACROSS staff.facilitators
AVOID activity.any_clinic PER staff activity BEYOND 1
```
Priority: `HIGH`. `ON` is omitted, so groups are counted per day.

#### Rotate ropes positions

```
ON date.session
DURING block.any_clinic
ACROSS staff.ropes_facilitators
AVOID activity.any_ropes ROLE {role.first + role.second} PER staff role BEYOND 3
```
Priority: `LOW`. Weight: `1`.

#### Balance clinic workload

```
ON date.session
DURING block.any_clinic
ACROSS staff.facilitators
AVOID activity.any_clinic PER staff BEYOND 8
```
Priority: `MEDIUM`. Weight: `0.25`.

#### Counselor hours with a maximum gap

Each counselor gets a counselor hour during clinic 1 or 2 and another during clinic 3 or 4, no more than five hours apart.

```
ACROSS EACH staff.counselors
TASK 'counselor hour' DURING {block.clinic_1 OR block.clinic_2} AS morning
TASK 'counselor hour' DURING {block.clinic_3 OR block.clinic_4} AS afternoon
GAP morning afternoon <= 5h
```
Priority: `MUST_HAPPEN`. `ON` is omitted, so this applies to each session date.

#### Non-counselor breaks

Each non-director, non-counselor staff member takes three 30-minute breaks per day.

```
ACROSS EACH {staff.all - staff.directors - staff.counselors}
DURING 3 OF block.break_slots
TASK 'break'
```
Priority: `MUST_HAPPEN`. `block.break_slots` includes both standalone break blocks and the break half of "break then Work Projects" periods (see "Blocks").

#### Playstation availability

As many non-directors as possible are free during the Playstation block.

```
DURING block.playstation
ACROSS {staff.all - staff.directors}
PREFER FREE
```
Priority: `HIGH`. Each free staff member adds to the score. The schedule marks them "Available" for playstation assignment by another role. `TASK FREE` with `ACROSS ALL` would instead be all-or-nothing.

#### Day off

```
ON 2026-09-16
DURING ALL block.any
ACROSS staff.dylan
TASK FREE
```
Priority: `MUST_HAPPEN`

---

## Data Sources

### Existing Google Sheets

- **Clinic_Data** (id: `1bcCFIBqL77HbPiY1nOM2cqzZ0YC9fhRcdBi4TwZS0-E`)
  Final form. Lists every clinic, its camper slots, the staff positions it requires, and the minimum RAL for each position. Position order defines `role.first`, `role.second`, and so on. Activity categories such as `any_clinic` and `any_ropes` come from this sheet.
- **Clinic_Schedule** (id: `1h_iOC7oqe43QFkpgoS-D-oFzP_r8G1EtDmrxvc83-o8`)
  A manual scheduling prototype. It validates that assigned staff are checked off for their positions and renders a readable clinic schedule, listing the 1st above the 2nd. Only the **Offerings** tab is fixed: it defines which clinics are offered for the following day. The rest may be replaced.
- **Skills** (id: `1SAjIEMtNwdpDWcKkBp8wrEt9BjQJ6kaeHW00zJcBQPs`)
  Which staff are checked off on which skills, including shadow and scaffold status, and which skills each clinic position requires.
- **Staff Categories** (id: `1Z92mJG-AbXKBX_jq5DKztNLVDXPUyL-licZWGvkVPXs`)
  A draft of the category format. Categories are arbitrary and change between sessions. Each category becomes a name in the `staff` namespace.

### New Sheets

- **Blocks**: one row per time block.

  | block_id      | start | end   | day_types | categories                 | display_group             |
  |---------------|-------|-------|-----------|----------------------------|---------------------------|
  | clinic_1      | 09:15 | 10:30 | regular   | any, any_clinic            |                           |
  | break_am      | 10:30 | 11:00 | regular   | any, break_slots           |                           |
  | pm_break      | 13:00 | 13:30 | regular   | any, break_slots           | break_then_work_projects  |
  | work_projects | 13:30 | 14:30 | regular   | any                        | break_then_work_projects  |
  | playstation   | 15:00 | 16:00 | regular   | any                        |                           |

  Times are illustrative. A "30 min break then Work Projects" period is two adjacent blocks sharing a `display_group`, so the schedule shows them as one cell while the solver treats them separately. Blocks may overlap; double booking is checked by time, not by block identity.

- **Requests**: one row per request, one column per request field.
- **Metrics**: one tab per metric (for example, enjoyment), with key columns, a value column, and the declared scale minimum and maximum.
- **Published Schedules**: one tab per date. Past tabs are read as fixed assignments (§7).

---

## Implementation

### Language and Libraries

- Python 3.12 for the parser, validator, solver, and desktop tool, so all components share one Skedge implementation.
- Google OR-Tools CP-SAT for solving.
- Lark for parsing Skedge, using the grammar above.
- gspread for Google Sheets access.
- Any Python library deemed best for the desktop application
- pytest for tests and ruff for linting and formatting.
- MkDocs Material, built and deployed to GitHub Pages by GitHub Actions, for documentation.

### Compilation to CP-SAT

- `x[s, a, r, d, b]`: boolean per eligible assignment.
- Each request `q` gets a literal `sat[q]`. Hard requests add `sat[q]` as an assumption so an infeasible model returns conflicting request IDs through `SufficientAssumptionsForInfeasibility`.
- `TASK`: one literal per alternative per clause; `sum(alternative literals) == sat[q]`; each chosen alternative implies (`OnlyEnforceIf`) its assignment variables.
- `FOR`: `sum(length[b] * y[b]) >= duration − hours_already_completed`, enforced if `sat[q]`. `CONTINUOUS`: precompute each run of adjacent blocks long enough, and treat each run as an alternative.
- `FORBID`: every matched `x` is false, enforced if `sat[q]`.
- `PREFER` / `AVOID`: `± weight * score * x` terms added to the tier objective.
- `AVOID … PER … BEYOND n`: for each group, `count = fixed_past + sum(x in group)`; `excess >= count − n`, `excess >= 0`; add `− weight * excess`.
- `FREE[s, d, b]`: true iff no `x` for `s` overlaps block `b` on date `d`.
- `GAP`: for every pair of chosen-block alternatives that violates the bound, add `AddBoolOr([alt_a.Not(), alt_b.Not()])`.
- CP-SAT objectives require integer coefficients. Multiply all tier coefficients by a fixed scale (for example `1000`) and round.
- Tiers are solved lexicographically, each with a configurable time limit.

### Solver Output

- The schedule for `date.target`.
- For each unsatisfied soft request: its ID, priority, and description.
- For an infeasible run: the IDs of the conflicting `MUST_HAPPEN` requests and no schedule.

---

## Intended User Experience

The Puppet Master maintains data in Google Sheets and requests in the desktop tool. Puppet Strings is a small set of programs sharing one workflow and one data store.

### Desktop Request Manager

- Create, edit, and delete requests, with a field for each request field.
- Validate Skedge as the Puppet Master types, showing errors with line and column.
- Filter requests by date, priority, staff, and activity, including a calendar filter.
- Read valid names (staff, categories, activities, blocks, metrics) from Google Sheets.
- Store requests in the Requests sheet.
- Have option to filter by persistence. That is to say, the Puppet Master should be able to see the requests that are per season, per session, per week, per day, and also have a section for manual "pin" requests

### Google Sheets Integration

- Read the Offerings for the target date.
- Trigger the solver and write the result to Published Schedules.
- Outptut two publishable versions of the schedule:
  - **Staff view**: one row per staff member, one column per block. Staff free during the Playstation block are marked "Available." Blocks sharing a `display_group` appear as one column.
  - **Clinic view**: one row per clinic, one column per clinic block, staff listed in position order (1st above 2nd), trainees listed after positions.
- Display unsatisfied requests and conflict reports.

---

## Testing

- The repository includes a sample dataset exported from the sheets as CSV fixtures, so tests run without Google access.
- Every example in "Request Examples" has a parser test and a solver test.
- Required scenario tests:
  - An infeasible pair of `MUST_HAPPEN` requests reports both IDs.
  - An offered clinic with no eligible staff is reported, and the rest of the schedule is produced.
  - A trainee is added without filling a position, and a scaffolded trainee is placed only with a clinic trainer.
  - The counselor-hour `GAP` rejects combinations more than five hours apart.
  - The variety-versus-enjoyment tradeoff produces the outcomes described in "Worked tradeoff" at weights `0.25`, `0.5`, and `1`.
  - A deferrable task is optional before its last date and enforced on it.
  - Past published assignments count toward `BEYOND` allowances.

---

## Unresolved Decisions

Build to the stated default and list each in the outline's assumptions.

1. **Scaffolder.** Default: the clinic trainer supervising a scaffold is one of the staff filling a required position, not an additional person.
2. **Training instances.** Default: a `role.trainee` task attaches only to a clinic already on the Offerings sheet; the solver does not create instances for training.
3. **Counselors' third break.** Counselor hours provide two 30-minute breaks per day. The legal requirement is three for non-director staff. Where does a counselor's third break come from?
4. **`GAP` measurement.** Default: end of the first task to start of the second.
5. **Variety across sessions.** Default: repetition windows ignore dates outside the active session.

---

## The Task

1. **Technical outline.** Write a detailed outline of how you will build the system, with examples. Then stop and wait for feedback. The outline must include:
   - The architecture, including where the solver runs and how components authenticate.
   - The data schema for every sheet read or written.
   - The module structure of the Python package.
   - How each Skedge construct compiles to CP-SAT, with one worked example.
   - A milestone plan, with what is testable at each milestone.
   - A list of every assumption made, including the defaults under "Unresolved Decisions."
2. **Build.** After the outline is approved, build the software milestone by milestone.
3. **Documentation.** Use MkDocs Material, GitHub Pages, and GitHub Actions to publish documentation, including a Skedge language reference with every example in this document.
4. **README.** Provide a high-level overview of the code and step-by-step instructions for installing and using the software.

---

## Code Style Requests

- Write self-documenting code. Document functions with docstrings; otherwise let the code speak for itself. Keep comments concise. Avoid adjectives, adverbs, and phrases in code, comments, or explanations that add no technical information.
- Removing code is as valuable as adding a feature. Keep the codebase concise.
- Follow the idiomatic style, conventions, and official style guide of each language (PEP 8 for Python), including formatting, naming, and structure.
- Prefer the "return early" pattern. Instead of `if condition: <long block> else: return`, write `if not condition: return` followed by the block.
- Avoid duplication. Reuse code through functions, classes, and modules.
- Use popular, well-maintained, reputable libraries appropriate to the task.

## Final Note
If you think any part of this task is unclear or suboptimal for achieving the high level goal, then pause to ask me for clarification on direction. Above all, I want to avoid spaghetti code and a spaghetti workflow for the future of the Puppet Master role.