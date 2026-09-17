# Skedge specification

This is the normative definition of Skedge, the language requests are written in. It says
what every construct means and what is rejected. [Skedge reference](skedge.md) is the
readable version, with worked examples; where the two disagree, this document is right.

Parts of the language are checked mechanically against the code: the grammar below is the
grammar the parser uses, every error message listed here exists in the source, and every
`skedge` block in either document is parsed and validated by the test suite. A change to
one that is not made to the other fails the suite.

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

An **instance** is one activity in one block on one date; the assignments on it are the
people working it together.

An assignment has a **length**. A clinic assignment is as long as its block. A quoted-task
assignment is as long as its block unless `FOR` gives a shorter length, in which case the
solver also chooses where in the block it sits.

In any block, a staff member is **busy** if they hold an assignment in it, **free** if they
are working that day and hold none, and neither if they are resting through it. `NOT FREE`
means busy.

Skedge has two statements and two ways of talking about assignments.

| | |
|---|---|
| `REQUEST` | A constraint that is either met or not met. |
| `PREFER` | A soft constraint that can be partly met. |
| `<who> DO <what> …` | A **requirement**: these people do this. Quantifiers *choose* who, what and when. |
| `<who> DOING <what> …` | A **pattern**: the assignments in which these people are doing this. A pattern matches assignments; nothing in it chooses. |

## 3. Lexical structure

| Element | Form |
|---|---|
| Keyword | Upper case: `REQUEST`, `PREFER`, `IF`, `UNLESS`, `GAP`, `TO`, `DO`, `DOING`, `NOT`, `FREE`, `DURING`, `ON`, `AS_ROLE`, `FOR`, `WITH`, `WITHOUT`, `IN`, `ALL_OF`, `ANY_n_OF`, `EACH_OF`, `AT_LEAST`, `AT_MOST`, `EXACTLY`, `CONSECUTIVE`, `MAXIMIZE`, `MINIMIZE` |
| Quantifier | `ALL_OF`, `EACH_OF`, and `ANY_n_OF` for any whole `n` from 1: `ANY_1_OF`, `ANY_3_OF` |
| Name | Dotted, lower case, digits and underscores: `staff.mary_kate`, `date.session.mondays` |
| Variable, label | A bare identifier: `s`, `morning`. A label is followed by a colon. |
| Quoted task | Single quotes, any text but a quote: `'archery maintenance'` |
| Date | `2026-06-14` |
| Day offset | A sign, a number and `d`: `- 6d`, `+2d` |
| Duration | A number and `m` or `h`: `30m`, `2h`, `1.5h` |
| Set expression | In braces: `+` union, `-` difference, `&` intersection, `..` date range, `( )` group |
| Comment | `#` to the end of the line |

Spaces and tabs separate tokens and are otherwise ignored. A line break ends a line; blank
lines are ignored. A declaration is one or more lines.

A duration must be a whole number of minutes: `1.5h` is 90 minutes, `1.25m` is an error.

## 4. Grammar

The parser reads this grammar, in [Lark](https://lark-parser.readthedocs.io) EBNF (LALR).
Requirements and patterns have separate rules, so a choosing quantifier inside a pattern,
or a clause a statement cannot take, is a parse error and not a validation rule.

```lark
// Skedge grammar. See docs/skedge.md for the language reference.

start       : _NL* line (_NL+ line)* _NL*
?line       : binding | if_ | unless | labeled | request | prefer | gap

binding     : (EACH_OF | ANY_N_OF) NAME "IN" set_
if_         : "IF" condition
unless      : "UNLESS" condition
labeled     : NAME ":" request
gap         : "GAP" NAME "TO" NAME amount

request     : "REQUEST" chooser "DO" do_target do_clause*         -> request_do
            | "REQUEST" chooser FREE do_clause*                   -> request_free
            | "REQUEST" chooser "NOT" "DO" target clause*         -> request_not_do
            | "REQUEST" chooser "NOT" FREE clause*                -> request_not_free
            | "REQUEST" amount pattern CONSECUTIVE?               -> request_count
prefer      : "PREFER" amount pattern CONSECUTIVE?                -> prefer_count
            | "PREFER" pattern goal                               -> prefer_score
condition   : amount? pattern CONSECUTIVE?

pattern     : pool "DOING" target clause*                        -> pattern_doing
            | pool FREE clause*                                  -> pattern_free
            | pool "NOT" FREE clause*                            -> pattern_busy
goal        : (MAXIMIZE | MINIMIZE) REF "(" arg ("," arg)* ")"
?arg        : NAME | REF

amount      : BOUND (INT | DURATION)

// Left of NOT, and in a positive REQUEST, quantifiers choose.
?do_target  : chooser | STRING
?do_clause  : during_c | on_c | as_role_c | for_ | with_ | without
during_c    : "DURING" chooser
on_c        : "ON" chooser
as_role_c   : "AS_ROLE" chooser
chooser     : (ALL_OF | ANY_N_OF)? set_
            | EACH_OF set_
            | EACH_OF NAME "IN" set_

// In a pattern, a set is a pool; only EACH_OF may precede it.
?target     : pool | STRING
?clause     : during | on | as_role | for_ | with_ | without
during      : "DURING" pool
on          : "ON" pool
as_role     : "AS_ROLE" pool
pool        : set_
            | EACH_OF set_
            | EACH_OF NAME "IN" set_

for_        : "FOR" DURATION
with_       : "WITH" set_
without     : "WITHOUT" set_

?set_       : REF | NAME | DATE | "{" setexpr "}"
?setexpr    : range (SETOP range)*     -> setop
?range      : primary ".." primary     -> date_range
            | primary
?primary    : date_atom OFFSET         -> date_offset
            | date_atom
            | "(" setexpr ")"
?date_atom  : DATE | REF | NAME

BOUND       : "AT_LEAST" | "AT_MOST" | "EXACTLY"
ALL_OF      : "ALL_OF"
EACH_OF     : "EACH_OF"
ANY_N_OF    : /ANY_[1-9][0-9]*_OF/
FREE        : "FREE"
MAXIMIZE    : "MAXIMIZE"
MINIMIZE    : "MINIMIZE"
CONSECUTIVE : "CONSECUTIVE"
SETOP       : "+" | "-" | "&"
OFFSET.2    : /[+-][ \t]*\d+d/
DATE.3      : /\d{4}-\d{2}-\d{2}/
DURATION.2  : /\d+(\.\d+)?[mh]/
STRING      : /'[^']*'/
REF.2       : /[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+/
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
`archery_1_2`. Two values in one namespace that normalize alike, or a sheet value that
normalizes to a built-in name, are a load error.

| Namespace | Holds | Built in |
|---|---|---|
| `staff` | Staff members, staff categories | `staff.all`, `staff.clinic_trainers` |
| `activity` | Clinics, clinic categories | `activity.all` (every clinic) |
| `block` | Blocks, block categories | `block.all` |
| `date` | | `date.target`, and the scopes below |
| `role` | | `role.first` … `role.sixth`, `role.lifeguard`, `role.lifeguard_2` …, `role.shadow`, `role.scaffolded`, `role.trainee` |
| `metric` | The metrics on the Metrics tab | |

Every name is either an **item** (one thing: `staff.rob`, `block.clinic_1`, `date.target`)
or a **set** (`staff.counselor`, `block.all`). Set names are plural or collective; there is
no name that means "any one of": that is what `ANY_1_OF` is for.

A staff category, and `staff.all`, hold only the people working on `date.target`: someone
resting all day is in no category, though their own name still resolves.

### 5.1 Dates

Date names are nested: `date.<scope>.<name>`.

| Scope | Covers |
|---|---|
| `date.session` | the session `date.target` falls in |
| `date.season` | every session of the season |
| `date.<session>` | one named session from the Calendar sheet, such as `date.session_2` |

| Name within a scope | Kind | Holds |
|---|---|---|
| `all` | set | every date of the scope |
| `mondays` … `sundays` | set | every date of the scope falling on that weekday |
| `first`, `last` | item | the scope's first and last date |
| `first_monday` … `sixth_sunday`, `last_monday` … `last_sunday` | item | that occurrence within the scope |
| `first_mondays` … `last_sundays` | set, `date.season` only | that occurrence within each session of the season |

An item name exists only if the scope reaches that occurrence.

`role.trainee` resolves per staff member from the Skills sheet: checked off or needing a
scaffold becomes `scaffolded`, needing a shadow or no checkoff becomes `shadow`.

`puppet-strings names` prints every name that currently exists.

## 6. Sets, quantifiers and variables

### 6.1 Set expressions

A set is a name, a variable, a date, or an expression in braces. Inside braces `+`, `-` and
`&` combine sets left to right and parentheses group; mixing two different operators
without parentheses is an error, so there is no precedence to remember. `a .. b` is an
inclusive date range, and a single date may be offset by whole days. An offset or range
endpoint that is not a single date is an error.

### 6.2 Quantifiers in a requirement

In a requirement every set must carry a quantifier. An item takes none.

| Quantifier | Meaning |
|---|---|
| `ALL_OF s` | Every member of `s`, as one all-or-nothing requirement. |
| `ANY_n_OF s` | `n` different members of `s`, the solver's choice. |
| `EACH_OF s` | The declaration is copied once per member, each copy a separate request. |

Evaluation order is fixed:

1. Every `EACH_OF` in the declaration splits it into copies, one per member; several give
   every combination. Each copy is an independent request with its own satisfaction,
   reported under `id[item, …]`. `EACH_OF` over an empty set gives no copies, and the
   request is reported as inactive.
2. Within a copy, each `ANY_n_OF` is one choice, made once.
3. Every chosen staff member then does the chosen activity in **every** chosen block on
   **every** chosen date.

So `ALL_OF {staff.lucy + staff.tom} DO … DURING ANY_1_OF block.all` puts Lucy and Tom in
the same block, because there is one block choice and both work it.

A requirement never forbids. `ANY_1_OF {block.clinic_1 + block.clinic_2}` holds when the
thing happens in at least one of them, and says nothing against both.

The activity and `AS_ROLE` of a requirement take an item, `ANY_1_OF` or `EACH_OF`, since a
person does one thing at a time. `ANY_n_OF` over fewer than `n` members cannot hold.

### 6.3 Sets in a pattern

In a pattern a set is a **pool**: the pattern matches an assignment whose field is any
member. The only quantifier a pattern takes is `EACH_OF`, which splits the declaration
exactly as above. `ALL_OF` and `ANY_n_OF` are parse errors in a pattern.

### 6.4 Variables

`EACH_OF x IN s` names the member each copy is about. `x` can then stand wherever a set
can, and as a metric argument. Written inline, `x` is visible in that statement. Written on
a line of its own, it is visible in every line of the declaration:

| Binding line | Meaning |
|---|---|
| `EACH_OF x IN s` | One copy of the declaration per member of `s`, with `x` that member. |
| `ANY_n_OF x IN s` | `x` is `n` members of `s`, chosen once for the whole declaration. With `n` of 1, `x` is an item. |

A binding line is the only way for two lines of a declaration to be about the same
person, block or date.

## 7. Requirements

| Form | Holds when, for every chosen staff member, block and date |
|---|---|
| `<who> DO <what> DURING <blocks> [clauses]` | the staff member holds an assignment to the activity there, passing the clauses |
| `<who> FREE DURING <blocks> [ON …]` | the staff member is free there |
| `<who> NOT DO <pattern target> [pattern clauses]` | the staff member holds **no** assignment matching the pattern |
| `<who> NOT FREE [pattern clauses]` | the staff member is busy in every block the clauses allow |

`<what>` is an activity or a `'quoted task'`. "Anything at all" is not a target: nothing to
do is `FREE`, and something to do is `NOT FREE`.

`DURING` is required in the positive forms. A missing `ON` is `ON date.target`, everywhere
in the language; it is the only default.

Everything to the right of `NOT` is a pattern (§8): sets there are pools, `DURING` may be
left out to mean every block, and only `EACH_OF` may quantify. The subject to the left of
`NOT` still chooses, so `ANY_1_OF {staff.lucy + staff.tom} NOT DO 'break'` is "one of them
takes no break" and `ALL_OF {…} NOT DO` is "none of them does".

Clauses of a requirement:

| Clause | Meaning |
|---|---|
| `DURING <blocks>`, `ON <dates>` | When. |
| `AS_ROLE <role>` | In that role. Without it, any position of the activity; a trainee role only when named. |
| `FOR <duration>` | The length of each assignment. Quoted tasks only. |
| `WITH <staff>` | Someone else from the set is on the same instance. |
| `WITHOUT <staff>` | Nobody else from the set is on the same instance. |

## 8. Patterns

`<who> DOING <what> [clauses]` matches every assignment that passes all of its parts.
`<who> FREE [clauses]` matches every (staff, block, date) in which the staff member is
free, and `<who> NOT FREE [clauses]` every one in which they are busy. A clause left out does not filter, except `ON`.

| Part | Passes an assignment when |
|---|---|
| `<who>` | its staff member is in the pool |
| `DOING <what>` | its activity is in the pool, or is that quoted task |
| `DURING`, `ON`, `AS_ROLE` | its block, date, role is in the pool |
| `FOR <duration>` | its length is exactly the duration |
| `WITH <staff>` | someone else in the set holds an assignment on the same instance |
| `WITHOUT <staff>` | nobody else in the set holds an assignment on the same instance |

`WITH` and `WITHOUT` are exact opposites. "Someone else" excludes the assignment's own staff
member and counts any role, trainees included. For a quoted task shorter than its block,
"the same instance" also means the same start time. `AS_ROLE` needs an activity; `FOR` needs a quoted task; `WITH`, `WITHOUT`, `AS_ROLE` and `FOR` cannot follow
`FREE`.

### 8.1 Amounts

An amount turns a pattern into a condition.

| Amount | Holds when |
|---|---|
| `AT_LEAST n`, `AT_MOST n`, `EXACTLY n` | the number of matches compares so with `n` |
| `AT_LEAST d`, `AT_MOST d`, `EXACTLY d` | the summed length of the matches compares so with duration `d` |

`n` is at least 1. `AT_MOST 0` and `EXACTLY 0` are errors: write `NOT DO`.

With `CONSECUTIVE` after the pattern, the amount is measured over **runs**. A run is one
staff member's matches in adjacent blocks on one date, blocks being adjacent when they are
next to each other in the Blocks sheet. `AT_LEAST` holds when some run reaches the amount,
`AT_MOST` when no run exceeds it, `EXACTLY` when both do.

## 9. Statements

| Statement | Met |
|---|---|
| `REQUEST <requirement>` | when the requirement holds |
| `REQUEST <amount> <pattern> [CONSECUTIVE]` | when the condition holds |
| `PREFER <amount> <pattern> [CONSECUTIVE]` | by degree: the closer the matches are to the amount, the better |
| `PREFER <pattern> MAXIMIZE metric.x(args)` | by degree: each match earns the metric's value |
| `PREFER <pattern> MINIMIZE metric.x(args)` | by degree: each match costs the metric's value |

A `REQUEST` is all or nothing. To get partial credit from a `REQUEST`, split it with
`EACH_OF`: each copy is then met or not on its own. That is how "avoid" is written:
`REQUEST EACH_OF staff.office NOT DO 'break' DURING EACH_OF {block.breakfast + block.lunch}`
at a soft priority is one small request per person per block.

`PREFER` takes patterns only. A soft wish that some requirement hold is a `REQUEST` at a
soft priority, so `PREFER <who> DO …` does not exist.

### 9.1 Metrics

A metric call names its keys: `metric.preference(s, c)`. Each argument is an item or a
variable bound by `EACH_OF`, and the arguments must agree in number and namespace with the
metric's key columns on the Metrics tab. The value is normalized to 0–1 against the
metric's declared scale. A key the metric has no row for takes the metric's default, which
is the bottom of its scale unless the Metrics tab says otherwise.

## 10. Declarations

A declaration is lines of these kinds, in any order.

| Line | Form | Meaning |
|---|---|---|
| Statement | `[label:] REQUEST …` or `PREFER …` | §9. Only a positive `REQUEST … DO` may be labeled. |
| Binding | `EACH_OF x IN s`, `ANY_n_OF x IN s` | §6.4. |
| Condition | `IF [amount] <pattern> [CONSECUTIVE]` | The statements apply only when this holds. With no amount, it holds when there is a match. |
| Negative condition | `UNLESS [amount] <pattern> [CONSECUTIVE]` | The statements apply only when this does not hold. |
| Gap | `GAP a TO b <amount>` | Relates the assignments of the `REQUEST` labeled `a` to those of the one labeled `b`. |

A declaration needs at least one statement and takes at most one condition. It is met when
all its statements and gaps hold, or when its condition says they do not apply. A `PREFER`
must be the only statement in its declaration.

### 10.1 GAP

`GAP a TO b <bound> <duration>` is read separately on each date. On a date where both
requirements have assignments, every assignment of `a` must end before any of `b` starts,
and the time from the end of the last `a` to the start of the first `b` must meet the
bound. `GAP a TO b AT_LEAST 0m` is plain ordering, and the one place a zero amount is
allowed. The times compared are real starts and ends, so a task shorter than its block may
sit anywhere in it to satisfy a gap.

## 11. What can exist

Only a positive `REQUEST` makes things happen. `NOT`, `AT_MOST`, `PREFER`, `IF` and
`UNLESS` steer what is otherwise asked for and never create an assignment.

1. A clinic instance runs only if a `REQUEST … DO` names it. Rule 13.4 then staffs the rest
   of it.
2. A trainee or quoted-task assignment exists only where a `REQUEST … DO` asks for it, where
   a `REQUEST AT_LEAST` or `REQUEST EXACTLY` pattern matches it, or as the `WITH` partner
   one of those needs.
3. A `REQUEST` whose condition says it does not apply asks for nothing.

A quoted task named in a pattern or a `NOT DO` that no positive `REQUEST` in any request
names is an error, not a line that does nothing.

## 12. Priorities and scoring

| Priority | Meaning |
|---|---|
| `MUST_HAPPEN` | Hard. If the hard requests cannot all hold, the solver reports the conflicting ids and produces no schedule. |
| `CLINIC` | Soft, first tier. Staffing the offered clinics. |
| `STABILITY` | Soft, second tier, set by the solver during a same-day change and not writable on a request. |
| `HIGH`, `MEDIUM`, `LOW` | Soft, in that order. |

`REQUEST` may have any priority. `PREFER` may not be `MUST_HAPPEN`: a cap that must hold is
`REQUEST AT_MOST`.

Soft tiers are solved lexicographically: a tier's score is maximized, fixed as a floor, and
the next tier is then maximized. No amount of a lower tier outweighs a higher one.

Within a tier, a declaration (or each `EACH_OF` copy of it) contributes:

| Statement | Contribution |
|---|---|
| `REQUEST` | 1 if the declaration is met, 0 otherwise |
| `PREFER <amount> …` | minus its **miss**: how far the matches are from the amount, in assignments, or in hours when the amount is a duration |
| `PREFER … MAXIMIZE` | the sum of the metric's value over the matches |
| `PREFER … MINIMIZE` | minus that sum |

Each contribution is multiplied by the request's weight, a positive number defaulting to 1
and not allowed on `MUST_HAPPEN`. Priority decides whether two requests can trade at all;
weight decides the rate when they can.

## 13. What the solver enforces regardless

These come from the sheets and are never written as requests.

1. A staff member's assignments never overlap in time.
2. A position is filled only by someone whose Skills row shows the checkoff and whose RAL
   that day meets the position's minimum.
3. Someone resting holds nothing in the blocks they are resting through, and is not free
   in them either.
4. A clinic runs fully staffed or not at all, and each position holds one person.
5. A clinic whose name ends in `(DBL)` keeps the same staff across both of its blocks.
6. Lifeguard positions are extra positions requiring the `LIFEGUARD` skill at RAL 5.
7. A trainee never fills a position. A shadow needs the instance fully staffed; a
   scaffolded trainee needs a position holder who is a trainer on that position's skill.
   One trainee per instance.

## 14. Time horizon

The solver schedules `date.target`.

- **Past dates** with a published schedule are facts. They cannot change, and they count
  exactly as today's assignments do, in every requirement, pattern, condition and amount.
- **Future dates** hold nothing yet.
- A request all of whose dates are past, or all future, is inactive.
- A positive `REQUEST` that could still be met on later dates is **deferrable**: a
  requirement whose `ON ANY_n_OF` can still choose later dates, or an `AT_LEAST` or
  `EXACTLY` pattern whose `ON` reaches past the target. Today it must only stay reachable:
  what is still missing after today may not exceed what the later dates can hold. A later
  date holds nothing for a staff member resting through it or a block that does not exist
  on it. On the last date that can hold anything, the whole remainder is due. Until then
  the solver has a small incentive to act early.
- `ALL_OF` dates, `NOT`, `AT_MOST`, and the upper half of `EXACTLY` are enforced every day.
- The solver keeps no memory between days. A choice made on an earlier day is known only
  through the published schedule, which is why past dates count as facts.

## 15. Errors

Every error names the line and column. The parser reports what it expected, which covers
`ALL_OF` or `ANY_n_OF` inside a pattern or to the right of `NOT`, `PREFER` with a
requirement, a label on a `PREFER`, `CONSECUTIVE` without a pattern, and `MAXIMIZE` without
a metric call. The validator and the solver report:

| Message | Condition |
|---|---|
| `a declaration needs at least one statement` | Only bindings, conditions or `GAP` lines. |
| `needs a quantifier: ALL_OF, ANY_n_OF or EACH_OF` | A set with no quantifier in a requirement. |
| `is one item and takes no quantifier` | `ANY_1_OF staff.rob`. |
| `one activity at a time` | `ALL_OF` or `ANY_2_OF` on a requirement's activity or `AS_ROLE`. |
| `needs DURING` | A positive requirement with no `DURING`. |
| `given twice` | A clause repeated in one statement. |
| `only one IF or UNLESS per declaration` | Two condition lines. |
| `PREFER stands alone` | A `PREFER` beside another statement. |
| `unknown … name` | A name that does not exist in its namespace. |
| `expected a … name` | A name or variable from the wrong namespace. |
| `unknown variable` | A bare identifier no `IN` binds. |
| `variable bound twice` | Two bindings of one identifier. |
| `mixed set operators need parentheses` | `{a + b & c}` and the like. |
| `AS_ROLE needs an activity` | `AS_ROLE` with a quoted task or `FREE`. |
| `FOR needs a quoted task` | `FOR` with any other target. |
| `FREE has no instance` | `WITH` or `WITHOUT` after `FREE`. |
| `amount must be at least 1` | `AT_LEAST 0`. |
| `write NOT DO` | `AT_MOST 0`, `EXACTLY 0`. |
| `metric arguments do not match its keys` | Wrong number or namespace of arguments. |
| `metric argument must be one item` | A set, or an `ANY_2_OF` variable, as an argument. |
| `PREFER cannot be MUST_HAPPEN` | Use `REQUEST AT_MOST`, `AT_LEAST` or `EXACTLY`. |
| `weight must be positive` | A weight of zero or less. |
| `weight is not allowed with MUST_HAPPEN` | A weight on a hard request. |
| `GAP needs a duration` | `GAP a TO b AT_LEAST 3`. |
| `only REQUEST … DO can be labeled` | A label on a `NOT`, `FREE` or amount `REQUEST`. |
| `undefined label` | `GAP` naming a label that no statement defines. |
| `defined twice` | Two statements with the same label. |
| `date range ends before it starts` | A backwards range. |
| `needs a single date here` | An offset or range endpoint that is a set of dates. |
| `invalid date` | A date that is not a date. |
| `no request asks for` | A quoted task that no positive `REQUEST` names. |

## 16. Left to the implementation

The language does not decide these, and a future version may change them without any
declaration meaning something different:

- Which optimal schedule is chosen when several score the same.
- How long the solver spends on each tier, and what it reports when it runs out of time.
- That a task shorter than its block sits as early in it as the constraints allow.
- The scale factor the objective uses internally, and the size of the incentive to do a
  deferrable request early.
- How `EACH_OF` copies and `ANY_n_OF` choices are encoded. They need not be enumerated.
