# Skedge specification

This is the normative definition of Skedge, the language requests are written in. It says
what every construct means and what is rejected. [Skedge reference](skedge.md) is the
readable version, with worked examples; where the two disagree, this document is right.

Parts of the language are checked mechanically against the code: the grammar below is the
grammar the parser uses, and every error message listed here exists in the source. A change
to one that is not made to the other fails the test suite.

## 1. Scope

A **request** is one Skedge declaration plus the fields on its row of the Requests sheet:
an id, a description, a priority, a weight, tags and a date. This document defines the
declaration and the meaning the solver gives it. The sheets that supply the names are in
[The sheets](sheets.md); the tiers a priority selects are in
[How the solver decides](solver.md).

## 2. The model

An **assignment** is one staff member doing one activity in one role in one block on one
date:

```
(staff, activity, role, date, block)
```

The solver decides, for every assignment it is allowed to consider, whether it happens. A
declaration selects some of them and states one thing about them. Nothing else in the
language refers to anything but assignments.

An assignment also has a **start** and a **length**. A clinic fills its block. A quoted
task fills its block unless `FOR` gives it a shorter length, in which case the solver also
chooses where in the block it sits.

## 3. Lexical structure

| Element | Form |
|---|---|
| Keyword | Upper case: `ON`, `DURING`, `ACROSS`, `ROLE`, `TASK`, `FORBID`, `PREFER`, `AVOID`, `FOR`, `CONTINUOUS`, `AS`, `PER`, `BEYOND`, `GAP`, `ANY`, `ALL`, `EACH`, `OF`, `OR`, `AND`, `FREE` |
| Name | `namespace.identifier`, lower case, digits and underscores: `staff.mary_kate` |
| Quoted task | Single quotes, any text but a quote: `'archery maintenance'` |
| Date | `2026-06-14` |
| Day offset | A sign, a number and `d`: `- 6d`, `+2d` |
| Duration | A number and `m` or `h`: `30m`, `2h`, `1.5h` |
| Comparison | `<=`, `>=`, `==` |
| Set operator | `+` union, `-` difference, `&` intersection |
| Comment | `#` to the end of the line |

Spaces and tabs separate tokens and are otherwise ignored. A line break ends a line; blank
lines are ignored. A declaration is one or more lines.

A duration must be a whole number of minutes: `1.5h` is 90 minutes, `1.25m` is an error.

## 4. Grammar

The parser reads this grammar, in [Lark](https://lark-parser.readthedocs.io) EBNF.

```lark
// Skedge grammar. See docs/skedge.md for the language reference.

start       : _NL* line (_NL+ line)* _NL*
line        : clause+
?clause     : on | during | across | role | verb | for_ | label | metric | per | gap

on          : "ON" selector
during      : "DURING" selector
across      : "ACROSS" selector
role        : "ROLE" selector
verb        : VERB target
?target     : selector | STRING | FREE
for_        : "FOR" DURATION CONTINUOUS?
label       : "AS" NAME
metric      : "~" ref
per         : "PER" NAME+ "BEYOND" INT
gap         : "GAP" NAME NAME COMPARISON DURATION

selector    : quantifier? atom
            | quantifier? "{" expr "}"
quantifier  : ANY | ALL | EACH | INT "OF"
?expr       : term ("OR" term)*        -> or_
?term       : factor ("AND" factor)*   -> and_
?factor     : setexpr | "(" expr ")"
?setexpr    : atom (SETOP atom)*       -> setop
?atom       : date_expr ".." date_expr -> date_range
            | date_expr
?date_expr  : date_atom OFFSET         -> date_offset
            | date_atom
?date_atom  : DATE                     -> date_literal
            | ref
ref         : NAME ("." NAME)+

VERB        : "TASK" | "FORBID" | "PREFER" | "AVOID"
FREE        : "FREE"
ANY         : "ANY"
ALL         : "ALL"
EACH        : "EACH"
CONTINUOUS  : "CONTINUOUS"
SETOP       : "+" | "-" | "&"
OFFSET.2    : /[+-][ \t]*\d+d/
COMPARISON  : "<=" | ">=" | "=="
DATE.3      : /\d{4}-\d{2}-\d{2}/
DURATION.2  : /\d+(\.\d+)?[mh]/
STRING      : /'[^']*'/
NAME        : /[a-z_][a-z0-9_]*/

COMMENT     : /#[^\n]*/
_NL         : /(\r?\n[ \t]*)+/
%import common.INT
%import common.WS_INLINE
%ignore WS_INLINE
%ignore COMMENT
```

## 5. Names

A sheet value becomes an identifier by lower casing it, replacing every run of characters
that are not letters or digits with one underscore, dropping underscores at the ends, and
prefixing `_` if the result would start with a digit. `Archery 1 & 2` becomes
`archery_1_2`. Two values in one namespace that normalize alike are a load error.

| Namespace | Holds |
|---|---|
| `staff` | Staff members, staff categories, `staff.all`, `staff.clinic_trainers` |
| `activity` | Clinics, their categories, `activity.any_clinic` |
| `block` | Blocks, block categories, `block.any` |
| `date` | `date.target`, `date.session`, weekdays, weekday ordinals |
| `role` | `role.first` … `role.sixth`, `role.lifeguard` …, `role.shadow`, `role.scaffolded`, `role.trainee` |
| `metric` | The metrics on the Metrics tab |

A staff category offers only the people working that day: someone resting all day is in no
category, though their own name still resolves.

`date.monday` … `date.sunday` hold every date of the session falling on that weekday.
`date.first_monday` … `date.sixth_sunday` and `date.last_monday` … `date.last_sunday` hold
one date each, and exist only if the session reaches that occurrence.

`role.trainee` resolves per staff member from the Skills sheet: checked off or needing a
scaffold becomes `scaffolded`, needing a shadow or no checkoff becomes `shadow`.

`puppet-strings names` prints every name that currently exists.

## 6. Selectors

A selector is the argument of `ON`, `DURING`, `ACROSS`, `ROLE`, or a verb. It evaluates to
a **list of alternatives**, each alternative a set of items that go together.

### 6.1 Sets

A name is a set. `+`, `-` and `&` combine sets and bind tighter than `OR` and `AND`.
`a .. b` is an inclusive date range. A single date may be offset by whole days; an offset
applied to anything but a single date is an error.

### 6.2 Quantifiers

A quantifier precedes a plain set, never an expression containing `OR` or `AND`.

| Quantifier | Alternatives from `{{a, b, c}}` | Reading |
|---|---|---|
| `ANY` (default) | `[a] [b] [c]` | one of them |
| `ALL` | `[a, b, c]` | all of them together |
| `n OF` | every combination of `n` | exactly `n` distinct items |
| `EACH` | splits the declaration | a separate copy per item |

`EACH` is expanded before solving: the declaration becomes one independent copy per item,
each with its own satisfaction. Several `EACH` clauses give the Cartesian product. A copy
reports under `id[item]`.

### 6.3 OR and AND

`OR` separates alternatives; `AND` joins items within one alternative. Expressions are
normalized to disjunctive normal form:

```
{{staff.james OR (staff.sarah AND staff.paul)}}   ->  [james] [sarah, paul]
```

`{{a OR b}}` is `ANY {{a + b}}`.

## 7. Clauses

| Clause | Required | Default |
|---|---|---|
| `ON <dates>` | no | `EACH date.session` |
| `DURING <blocks>` | yes | |
| `ACROSS <staff>` | no | `staff.all` |
| `ROLE <roles>` | no | every position of the activity |
| `FOR <duration> [CONTINUOUS]` | no | the chosen blocks' full length |
| `AS <label>` | no | |
| `~ <metric>` | no | every assignment scores 1 |
| `PER <fields> BEYOND <n>` | no | |

Clauses may appear in any order, and lines in any order. A clause on a verb's line applies
to that verb; a clause on a line with no verb applies to every verb in the declaration; a
verb may not receive the same clause from both places. One verb per line. A declaration
needs at least one verb.

The omitted `ON` means *each* date of the session, not any of them. `GAP` clauses belong to
the declaration rather than to a verb.

## 8. Verbs

### 8.1 TASK

The target is an activity selector, a quoted task, or `FREE`.

The solver chooses exactly one alternative for each of `ON`, `DURING`, `ACROSS` and `ROLE`.
Every staff member in the chosen `ACROSS` alternative works the target in every block of the
chosen `DURING` alternative on every date of the chosen `ON` alternative. Staff joined by
`AND` are scheduled together.

For an activity with positions:

- Without `ROLE`, the task means "run this activity": every position is filled by someone
  from the `ACROSS` pool, which must therefore be a plain pool (`ANY` or `EACH`, no `ALL`,
  `n OF` or `AND`).
- With `ROLE`, only the named positions or trainee roles are filled from the pool.

`TASK FREE` means no assignment at all for the chosen staff in the chosen blocks.

A quoted task has no positions, skills or camper slots. It occupies staff time only.

`FOR <duration>` changes how `DURING` is satisfied:

| `DURING` | Meaning with `FOR d` |
|---|---|
| a plain set | any blocks whose used time adds up to `d`, the last one used partially |
| `n OF <set>` | `n` separate blocks, each holding the full `d` |
| with `CONTINUOUS` | adjacent blocks on one date, all filled but the last |

Time already worked on published past dates counts toward the duration. `FOR` may not
combine with `DURING ALL`.

### 8.2 FORBID

No assignment matching every clause may exist. Selectors filter rather than choose, so
`ALL` and `n OF` are errors; `EACH` is allowed and still splits the declaration.
`FORBID FREE` is an error: it says nothing, since the absence of an assignment is not an
assignment.

### 8.3 PREFER and AVOID

Neither requires anything. Each matching assignment adds (`PREFER`) or subtracts (`AVOID`)
its score from the declaration's tier. Selectors filter, under the same rule as `FORBID`.
Neither verb may be `MUST_HAPPEN`, since neither can fail.

`~ metric.x` replaces the score of 1 with that metric's value for the assignment,
normalized to 0–1 against the metric's declared scale. An assignment the metric has no row
for takes the metric's default, which is the bottom of its scale unless the Metrics tab
says otherwise. Weights and metric values are never negative: the sign lives in the verb.

`PER <fields> BEYOND <n>` groups the matched assignments by the listed fields, which are
some of `staff`, `activity`, `role`, `date`, `block`. Within each group the first `n`
assignments cost nothing and each one after that costs 1. `n` is at least 1. `ON` sets the
window, and published assignments inside it are counted. `PER` is `AVOID` only, and cannot
combine with `~`.

### 8.4 Staff working together

On `FORBID`, `PREFER` and `AVOID`, an `ACROSS` alternative holding several staff, written
with `AND`, matches them as a group: one match per instance, meaning the same activity,
block and date, where every member of the group holds an assignment, whatever positions
they hold. `AND` has no such meaning in `ON`, `DURING`, `ROLE` or the target, where it is an
error. A metric keyed by `staff` cannot score a group.

### 8.5 GAP

`GAP a b <cmp> d` requires the task labeled `b` to start after the task labeled `a` ends,
with the time between them satisfying the comparison. `GAP a b >= 0m` is plain ordering.
The times compared are the tasks' real start and end, so a `FOR 1h` task may sit anywhere in
its block to satisfy a gap.

Both labels must name `TASK` verbs in the same declaration that occupy one block each, with
no `ALL`, `n OF` or `AND`, and whose `ACROSS` names one staff member. `ACROSS EACH` gives
that, one copy per person.

## 9. Priorities and scoring

| Priority | Meaning |
|---|---|
| `MUST_HAPPEN` | Hard. If the hard requests cannot all hold, the solver reports the conflicting ids and produces no schedule. |
| `CLINIC` | Soft, first tier. Staffing the offered clinics. |
| `STABILITY` | Soft, second tier, set by the solver during a same-day change and not writable on a request. |
| `HIGH`, `MEDIUM`, `LOW` | Soft, in that order. |

Soft tiers are solved lexicographically: a tier's score is maximized, fixed as a floor, and
the next tier is then maximized. No amount of a lower tier outweighs a higher one.

Within a tier, a request contributes:

| Request | Contribution |
|---|---|
| `TASK`, `FORBID` | 1 if satisfied, 0 otherwise |
| `PREFER` | the sum of its matched assignments' scores |
| `AVOID` | minus the sum of its matched assignments' scores |
| `AVOID … PER … BEYOND n` | minus the assignments past each group's allowance |

Each contribution is multiplied by the request's weight, which is a positive number,
defaulting to 1, and not allowed on `MUST_HAPPEN`. Priority decides whether two requests can
trade at all; weight decides the rate when they can.

## 10. What the solver enforces regardless

These come from the sheets and are never written as requests.

1. A staff member's assignments never overlap in time.
2. A position is filled only by someone whose Skills row shows the checkoff and whose RAL
   that day meets the position's minimum.
3. Someone resting holds nothing in the blocks they are resting through.
4. A clinic runs fully staffed or not at all, and each position holds one person.
5. A clinic whose name ends in `(DBL)` keeps the same staff across both of its blocks.
6. Lifeguard positions are extra positions requiring the `LIFEGUARD` skill at RAL 5.
7. A trainee never fills a position. A shadow needs the instance fully staffed; a
   scaffolded trainee needs a position holder who is a trainer on that position's skill.
   One trainee per instance.
8. A quoted task happens only in a place some `TASK` selected. A `FORBID`, `PREFER` or
   `AVOID` naming a quoted task that no `TASK` asks for is an error rather than a line that
   does nothing.

## 11. Time horizon

The solver schedules `date.target`.

- **Past dates** with a published schedule are fixed. They cannot change, but they count
  toward `AVOID … BEYOND` windows and toward `FOR` durations.
- **Future dates** select nothing.
- A `TASK` whose `ON` window reaches past the target is **deferrable**: optional today, with
  a small incentive to do it early, and enforced at its priority on the window's last date.
- A window is clipped to the target's session.

## 12. Errors

Every error names the line and column. The parser reports what it expected. The validator
and the solver report:

| Message | Condition |
|---|---|
| `a declaration needs at least one verb` | The declaration has only clauses. |
| `one verb per line` | Two verbs on one line. |
| `given twice` | A clause repeated on one line. |
| `is given here and on a shared line` | A verb gets one clause from both places. |
| `AS belongs on a verb's line` | `AS` on a line with no verb. |
| `needs DURING` | A verb with no `DURING` in scope. |
| `unknown … name` | A name that does not exist in its namespace. |
| `expected a … name` | A name from the wrong namespace, or a date where a name belongs. |
| `a quantifier cannot apply to an expression with OR or AND` | `ALL {{a OR b}}` and the like. |
| `takes no ALL or OF` | `ALL` or `n OF` on `FORBID`, `PREFER` or `AVOID`. |
| `AND belongs in ACROSS` | `AND` outside `ACROSS` on a filter verb. |
| `ACROSS must be a plain pool` | `ALL`, `n OF` or `AND` on a `TASK` for a positioned activity with no `ROLE`. |
| `ROLE needs an activity target` | `ROLE` on a quoted task or `FREE`. |
| `FORBID FREE is not allowed` | `FORBID FREE`. |
| `cannot be MUST_HAPPEN` | `PREFER` or `AVOID` at `MUST_HAPPEN`. |
| `weight must be positive` | A weight of zero or less. |
| `weight is not allowed with MUST_HAPPEN` | A weight on a hard request. |
| `AS is only for TASK` | `AS` on another verb. |
| `FOR is only for TASK` | `FOR` on another verb. |
| `FOR cannot combine with DURING ALL` | Both on one verb. |
| `~ is only for PREFER and AVOID` | `~` elsewhere. |
| `~ cannot combine with PER` | Both on one verb. |
| `PER ... BEYOND is only for AVOID` | `PER` on another verb. |
| `PER fields must be some of` | A field that is not an assignment field. |
| `BEYOND must be at least 1` | `BEYOND 0`. |
| `it cannot score an ACROSS group` | A staff-keyed metric on a group. |
| `GAP tasks must occupy a single block` | A labeled task with `ALL`, `n OF` or `AND`. |
| `GAP tasks must be for one staff member` | A labeled task whose `ACROSS` names several. |
| `undefined label` | `GAP` naming a label that no verb defines. |
| `defined twice` | Two verbs with the same label. |
| `this set is empty` | `ALL`, `n OF` or `EACH` over nothing. |
| `OF a set of` | `n OF` where `n` exceeds the set. |
| `date range ends before it starts` | A backwards range. |
| `needs a single date here` | An offset or range endpoint that is a set of dates. |
| `invalid date` | A date that is not a date. |
| `no request asks for` | A filter verb naming a quoted task no `TASK` asks for. |

## 13. Left to the implementation

The language does not decide these, and a future version may change them without any
declaration meaning something different:

- Which optimal schedule is chosen when several score the same.
- How long the solver spends on each tier, and what it reports when it runs out of time.
- That a partial task sits as early in its block as the constraints allow, and that
  assignments nothing asked for are dropped.
- The scale factor the objective uses internally, and the size of the incentive to do a
  deferrable task early.
