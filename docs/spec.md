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
| `<who> DO <what> …` after `REQUEST <chooser>` | A **requirement**: these people do this. Quantifiers *choose* who, what and when. |
| `<who> DO <what> …` after an amount | A **pattern**: the assignments in which these people are doing this. A pattern matches assignments; nothing in it chooses. |

## 3. Lexical structure

| Element | Form |
|---|---|
| Keyword | Either case, upper by convention: `REQUEST`, `PREFER`, `IF`, `UNLESS`, `AND`, `OR`, `GAP`, `TO`, `DO`, `EXCLUDE`, `NOT`, `FREE`, `DURING`, `ON`, `AS_ROLE`, `FOR`, `WITH`, `WITHOUT`, `IN`, `ALL_OF`, `ANY_n_OF`, `EACH_OF`, `AT_LEAST`, `AT_MOST`, `EXACTLY`, `CONSECUTIVE`, `MAXIMIZE`, `MINIMIZE` |
| Quantifier | `ALL_OF`, `EACH_OF`, and `ANY_n_OF` for any whole `n` from 1: `ANY_1_OF`, `ANY_3_OF` |
| Name | Dotted, lower case, digits and underscores; any depth: `staff.mary_kate`, `dates.session.four.week.two.monday` |
| Variable, label | A bare identifier: `s`, `morning`. A label is followed by a colon. |
| Quoted task | Single quotes, any text but a quote: `'archery maintenance'` |
| Date | `2026-06-14` |
| Day offset | A sign, a number and `d`: `- 6d`, `+2d` |
| Duration | A number and `m`, `h` or `d`: `30m`, `2h`, `1.5h`, `2d` |
| Set expression | In braces: `+` union, `-` difference, `&` intersection, `..` date range, `( )` group |
| Comment | `#` to the end of the line |

Spaces and tabs separate tokens and are otherwise ignored. A line break ends a line; blank
lines are ignored. A declaration is one or more lines.

A duration must be a whole number of minutes: `1.5h` is 90 minutes, `1d` is 1,440, and
`1.25m` is an error.

## 4. Grammar

The parser reads this grammar, in [Lark](https://lark-parser.readthedocs.io) EBNF (LALR).
Requirements and patterns have separate rules, so a choosing quantifier inside a pattern,
or a clause a statement cannot take, is a parse error and not a validation rule.

```lark
// Skedge grammar. See docs/skedge.md for the language reference.
//
// Every keyword is case-insensitive: `REQUEST` and `request` are one word. Upper case is
// the convention, and is what the docs and the examples are written in, but nobody should
// have a request refused over a shift key. Names, variables and labels stay lower case,
// and so cannot be spelled like a keyword: `on` reads as `ON` whatever was meant by it.
//
// Each keyword is a terminal of its own at a priority above NAME, and ends in `\b` so that
// it only ever takes a whole word: `format` is a name, not `FOR` and then `mat`.

start       : _NL* line (_NL+ line)* _NL*
?line       : binding | if_ | unless | labeled | request | prefer | gap | exclude

binding     : (EACH_OF | ANY_N_OF) NAME _IN set_
if_         : _IF _NL* condition
unless      : _UNLESS _NL* condition
labeled     : NAME ":" request
gap         : _GAP NAME _TO NAME amount

request     : _REQUEST chooser _DO do_target do_clause*           -> request_do
            | _REQUEST chooser do_clause*                         -> request_activity
            | _REQUEST chooser FREE do_clause*                    -> request_free
            | _REQUEST chooser _NOT _DO target clause*            -> request_not_do
            | _REQUEST chooser _NOT FREE clause*                  -> request_not_free
            | _REQUEST amount CONSECUTIVE? pattern CONSECUTIVE?   -> request_count
prefer      : _PREFER amount CONSECUTIVE? pattern CONSECUTIVE?    -> prefer_count
            | _PREFER pattern goal                                -> prefer_score

// Who is not at camp for part of a day, and what to write where they would have been.
// It takes a quoted label rather than an activity: they are not doing anything here.
exclude     : _EXCLUDE chooser _DO STRING do_clause*

// A condition is one test, or several joined by AND or by OR. Mixing the two needs
// parentheses, as mixing set operators does, so there is no precedence to remember.
?condition  : term ((AND | OR) _NL* term)*        -> junction
?term       : test | "(" _NL* condition ")"
test        : (amount CONSECUTIVE?)? pattern CONSECUTIVE?

pattern     : pool _DO target clause*                            -> pattern_doing
            | pool FREE clause*                                  -> pattern_free
            | pool _NOT FREE clause*                             -> pattern_busy
goal        : (MAXIMIZE | MINIMIZE) call
call        : REF "(" arg ("," arg)* ")"
?arg        : NAME | REF

// CONSECUTIVE goes after the amount it measures in runs. One after the pattern is where it
// used to go, and is parsed only to say where it goes now.
amount      : BOUND (INT | DURATION)

// Left of NOT, and in a positive REQUEST, quantifiers choose.
?do_target  : chooser | STRING
?do_clause  : during_c | on_c | as_role_c | for_ | with_ | without
// CONSECUTIVE after ANY_n_OF blocks: the chosen blocks are next to each other.
during_c    : _DURING chooser CONSECUTIVE?
on_c        : _ON chooser
as_role_c   : _AS_ROLE chooser
chooser     : (ALL_OF | ANY_N_OF)? set_
            | EACH_OF set_
            | EACH_OF NAME _IN set_

// In a pattern, a set is a pool; only EACH_OF may precede it.
?target     : pool | STRING
?clause     : during | on | as_role | for_ | with_ | without
during      : _DURING pool
on          : _ON pool
as_role     : _AS_ROLE pool
pool        : set_
            | EACH_OF set_
            | EACH_OF NAME _IN set_

for_        : _FOR DURATION
// Who is alongside: one name, or several with ALL_OF or ANY_n_OF to say how many.
with_       : _WITH company
without     : _WITHOUT company
company     : (ALL_OF | ANY_N_OF | EACH_OF)? set_

?set_       : REF | NAME | DATE | call | "{" setexpr "}"
?setexpr    : range (SETOP range)*     -> setop
?range      : primary ".." primary     -> date_range
            | primary
?primary    : date_atom OFFSET         -> date_offset
            | date_atom
            | "(" setexpr ")"
?date_atom  : DATE | REF | NAME | call

// Two more ways in, for the cells of the Mappings tab rather than for a request: what a
// key or a value may be, and what stands in for a key with no row.
mapping_domain  : "{" setexpr "}" | setexpr
mapping_default : chooser

// The keywords. A leading `_` keeps the token out of the tree, the way an anonymous string
// would; `.5` puts them above NAME, which lower case would otherwise be read as.
_REQUEST.5  : /REQUEST\b/i
_EXCLUDE.5  : /EXCLUDE\b/i
_PREFER.5   : /PREFER\b/i
_IF.5       : /IF\b/i
_UNLESS.5   : /UNLESS\b/i
_GAP.5      : /GAP\b/i
_TO.5       : /TO\b/i
_DO.5       : /DO\b/i
_NOT.5      : /NOT\b/i
_IN.5       : /IN\b/i
_DURING.5   : /DURING\b/i
_ON.5       : /ON\b/i
_AS_ROLE.5  : /AS_ROLE\b/i
_FOR.5      : /FOR\b/i
_WITH.5     : /WITH\b/i
_WITHOUT.5  : /WITHOUT\b/i
BOUND.5     : /AT_LEAST\b/i | /AT_MOST\b/i | /EXACTLY\b/i
ALL_OF.5    : /ALL_OF\b/i
EACH_OF.5   : /EACH_OF\b/i
ANY_N_OF.5  : /ANY_[1-9][0-9]*_OF\b/i
FREE.5      : /FREE\b/i
MAXIMIZE.5  : /MAXIMIZE\b/i
MINIMIZE.5  : /MINIMIZE\b/i
CONSECUTIVE.5 : /CONSECUTIVE\b/i
AND.5       : /AND\b/i
OR.5        : /OR\b/i

SETOP       : "+" | "-" | "&"
OFFSET.2    : /[+-][ \t]*\d+d/
DATE.3      : /\d{4}-\d{2}-\d{2}/
DURATION.2  : /\d+(\.\d+)?[mhd]/
STRING      : /'[^']*'/
REF.2       : /[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+/
NAME        : /[a-z_][a-z0-9_]*/

COMMENT     : /#[^\n]*/

// A statement may be written over as many lines as it reads well on. A line beginning
// with a word that continues a statement -- DO, DURING, ON, FOR, AND, a set operator -- is
// a continuation of the one above, and the newline before it is nothing. A line ending in
// IF, UNLESS, AND, OR or an opening parenthesis runs on into the next, by the grammar. EACH_OF and
// ANY_n_OF are deliberately not on the list: they begin a binding line of their own, and
// a line starting with a bare name may be a label, so neither can continue anything.
_CONTINUES  : /(\r?\n[ \t]*)+(?=(?i:DO|NOT|FREE|DURING|ON|AS_ROLE|FOR|WITH|WITHOUT|IN|TO|CONSECUTIVE|ALL_OF|MAXIMIZE|MINIMIZE|AND|OR)\b|[+&}),]|\.\.|-[ \t]*[a-z_{(])/
_NL         : /(\r?\n[ \t]*)+/
%import common.INT
%import common.WS_INLINE
%ignore WS_INLINE
%ignore COMMENT
%ignore _CONTINUES
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
| `activities` | Clinics under `clinics`, cabin acts under `cabin_acts` | `activities.all`, `activities.clinics.all`, `activities.cabin_acts.all` |
| `blocks` | Blocks, block categories | `blocks.all` |
| `dates` | | `dates.target`, and the scopes below |
| `roles` | | `roles.first` … `roles.sixth`, `roles.lifeguard`, `roles.lifeguard_2` …, `roles.shadow`, `roles.scaffolded`, `roles.trainee` |
| `mappings` | The mappings on the Mappings tab | |

A namespace is plural because it holds many names. `activities` has a branch per kind of
activity, so `activities.clinics.archery_1_2` is a clinic and `activities.cabin_acts.p4`
is a cabin act; only `activities.all` is both.

Every name is either an **item** (one thing: `staff.rob`, `blocks.clinic_1`, `dates.target`)
or a **set** (`staff.counselor`, `blocks.all`). Set names are plural or collective; there is
no name that means "any one of": that is what `ANY_1_OF` is for.

A staff category, and `staff.all`, hold only the people working on `dates.target`: someone
resting all day is in no category, though their own name still resolves. `staff.all` is the
union of the span's Staff Categories columns, not the Skills sheet's rows; a staff member in
no category is away for that span and is treated as resting all day.

A skill is not a name. What a skill may be asked for is a position on an activity, which
carries the skill it needs, so `REQUEST <activity>` asks for people with those skills
without naming any of them.

### 5.1 Dates

Date names are nested spans. A **span** is one row of the Calendar sheet: a run of days
from its `start date` to its `end date`, running one `program type`. A date cell is read
however the sheet displays it; a numeric date that could be read both ways follows
`date_order` in `config.toml`. Every span carries the
same names, and a span's weeks are its days seven at a time from the start.

| Span | Kind | Covers |
|---|---|---|
| `dates.target` | item | the date being scheduled |
| `dates.season.all` | set | every date the Calendar sheet covers |
| `dates.session.one.all` … `dates.session.twenty.all` | set | a `main season` row, numbered in sheet order |
| `dates.other.<name>.all` | set | any other row, by its `name` column normalized |
| `dates.<span>.week.one.all` … `.week.twenty.all` | set | that week of that span |

| Name within any span | Kind | Holds |
|---|---|---|
| `all` | set | every date of the span |
| `mondays` … `sundays` | set | every date of the span falling on that weekday |
| `first`, `last` | item | the span's first and last date |

| Name within a week | Kind | Holds |
|---|---|---|
| `all` | set | every date of the week |
| `monday` … `sunday` | item | that weekday of the week |
| `first`, `last` | item | the week's first and last date |

A name exists only if the span reaches it: `dates.session.two.week.two.all` is a name only
when session 2 runs to a second week. At most 20 main season rows and 20 weeks per span.

There are no `first_monday` / `last_friday` names and no cross-session `first_mondays`
sets: a week's weekday is how an occurrence is named. There is no `this` span or `this`
week either — every date name but `dates.target` says outright which span it means.

`roles.trainee` resolves per staff member from the Skills sheet: checked off or needing a
scaffold becomes `scaffolded`, needing a shadow or no checkoff becomes `shadow`.

`puppet-strings names` prints every name that currently exists.

## 6. Sets, quantifiers and variables

### 6.1 Set expressions

A set is a name, a variable, a date, a mapping call such as `mappings.buddy(c)` (§9.2),
or an expression in braces. Inside braces `+`, `-` and
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

So `ALL_OF {staff.lucy + staff.tom} DO … DURING ANY_1_OF blocks.all` puts Lucy and Tom in
the same block, because there is one block choice and both work it.

A requirement never forbids. `ANY_1_OF {blocks.clinic_1 + blocks.clinic_2}` holds when the
thing happens in at least one of them, and says nothing against both.

The activity and `AS_ROLE` of a requirement take an item, `ANY_1_OF` or `EACH_OF`, since a
person does one thing at a time. `ANY_n_OF` over fewer than `n` members cannot hold.

`DURING ANY_n_OF <blocks> CONSECUTIVE` chooses `n` blocks that are next to each other in
the Blocks sheet, on a date the requirement is about, which is what adjacent means for an
amount too (§8.1). The choice is still one choice, made once, so everyone chosen does it in
the same run of blocks. It takes `ANY_n_OF` with `n` of 2 or more, and cannot hold when no
`n` members of the set are next to each other.

### 6.3 Sets in a pattern

In a pattern a set is a **pool**: the pattern matches an assignment whose field is any
member. The only quantifier a pattern takes is `EACH_OF`, which splits the declaration
exactly as above. `ALL_OF` and `ANY_n_OF` are parse errors in a pattern, except after `WITH`
and `WITHOUT`, which count company rather than choose it (§8).

### 6.4 Variables

`EACH_OF x IN s` names the member each copy is about. `x` can then stand wherever a set
can, and as a mapping argument. Written inline, `x` is visible in that statement. Written on
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

`DURING` is required in the positive forms. A missing `ON` is `ON dates.target`, everywhere
in the language; it is the only default.

Everything to the right of `NOT` is a pattern (§8): sets there are pools, `DURING` may be
left out to mean every block, and only `EACH_OF` may quantify, apart from `WITH` and
`WITHOUT` (§8). The subject to the left of
`NOT` still chooses, so `ANY_1_OF {staff.lucy + staff.tom} NOT DO 'break'` is "one of them
takes no break" and `ALL_OF {…} NOT DO` is "none of them does".

Clauses of a requirement:

| Clause | Meaning |
|---|---|
| `DURING <blocks>`, `ON <dates>` | When. |
| `AS_ROLE <role>` | In that role. Without it, any position of the activity; a trainee role only when named. |
| `FOR <duration>` | The length of each assignment. Quoted tasks only. |
| `WITH <staff>` | Enough others from the set are on the same instance (§8). |
| `WITHOUT <staff>` | Not enough are. |

## 8. Patterns

`<who> DO <what> [clauses]` matches every assignment that passes all of its parts.
`<who> FREE [clauses]` matches every (staff, block, date) in which the staff member is
free, and `<who> NOT FREE [clauses]` every one in which they are busy. A clause left out does not filter, except `ON`.

| Part | Passes an assignment when |
|---|---|
| `<who>` | its staff member is in the pool |
| `DO <what>` | its activity is in the pool, or is that quoted task |
| `DURING`, `ON`, `AS_ROLE` | its block, date, role is in the pool |
| `FOR <duration>` | its length is exactly the duration |
| `WITH <staff>` | enough others in the set hold an assignment on the same instance |
| `WITHOUT <staff>` | not enough do |

`WITH` and `WITHOUT` take one name, or a set with `ALL_OF` or `ANY_n_OF` to say how many is
enough: `WITH staff.vic` is Vic, `WITH ANY_2_OF staff.mfgs` at least two MFGs, `WITH ALL_OF
staff.mfgs` every MFG. A set of several with no quantifier is an error, as in a
requirement, and so is `EACH_OF`. This holds on both sides of `NOT`.

`WITH` and `WITHOUT` are exact opposites: `WITHOUT ANY_1_OF staff.mfgs` is no MFG,
`WITHOUT ALL_OF staff.mfgs` is not every MFG. "Others" excludes the assignment's own staff
member, so `ALL_OF` does not ask anyone to be alongside themselves, and counts any role,
trainees included. For a quoted task shorter than its block,
"the same instance" also means the same start time. `AS_ROLE` needs an activity; `FOR` needs a quoted task; `WITH`, `WITHOUT`, `AS_ROLE` and `FOR` cannot follow
`FREE`.

### 8.1 Amounts

An amount turns a pattern into a condition.

| Amount | Holds when |
|---|---|
| `AT_LEAST n`, `AT_MOST n`, `EXACTLY n` | the number of matches compares so with `n` |
| `AT_LEAST d`, `AT_MOST d`, `EXACTLY d` | the summed length of the matches compares so with duration `d` |

`n` is at least 1. `AT_MOST 0` and `EXACTLY 0` are errors: write `NOT DO`.

With `CONSECUTIVE` after the amount, the amount is measured over **runs**. A run is one
staff member's matches in adjacent blocks on one date, blocks being adjacent when they are
next to each other in the Blocks sheet. `AT_LEAST` holds when some run reaches the amount,
`AT_MOST` when no run exceeds it, `EXACTLY` when both do.

## 9. Statements

| Statement | Met |
|---|---|
| `REQUEST <requirement>` | when the requirement holds |
| `REQUEST <amount> [CONSECUTIVE] <pattern>` | when the condition holds |
| `PREFER <amount> [CONSECUTIVE] <pattern>` | by degree: the closer the matches are to the amount, the better |
| `PREFER <pattern> MAXIMIZE mappings.x(args)` | by degree: each match earns the mapping's value |
| `PREFER <pattern> MINIMIZE mappings.x(args)` | by degree: each match costs the mapping's value |
| `EXCLUDE <who> DO '<label>' [DURING] [ON]` | not met or unmet: applied (§9.2) |

A `REQUEST` is all or nothing. To get partial credit from a `REQUEST`, split it with
`EACH_OF`: each copy is then met or not on its own. That is how "avoid" is written:
`REQUEST EACH_OF staff.office NOT DO 'break' DURING EACH_OF {blocks.breakfast + blocks.lunch}`
at a soft priority is one small request per person per block.

`PREFER` takes patterns only. A soft wish that some requirement hold is a `REQUEST` at a
soft priority, so `PREFER <who> DO …` does not exist.

### 9.1 EXCLUDE

`EXCLUDE <who> DO '<label>' [DURING <blocks>] [ON <dates>]` says that these people are not
at camp for those blocks on those dates. `DURING` left out is every block the date has;
`ON` left out is the date being scheduled. It is applied rather than solved:

- No assignment of theirs exists in those blocks, and no statement of any kind reaches
  them there. It is the same state the Adjustments sheet's `resting` puts somebody in.
- Somebody excluded from every block a date has is in no staff category on that date, so a
  `REQUEST` written about a category asks nothing of them. Somebody excluded from part of
  a date stays in their categories.
- `<label>` is what the published views write where their assignments would have been.

Nothing in an `EXCLUDE` is chosen, so `ANY_n_OF` is refused in every position. It takes no
clause but `DURING` and `ON`, holds no `IF`, no `GAP` and no label, is the only statement
in its declaration, and its priority is `MUST_HAPPEN`.

### 9.2 Mappings

A mapping call names its keys: `mappings.preference(s, c)`. Each argument is an item or a
variable bound by `EACH_OF`. The Mappings tab gives each key a set, and the arguments must
agree with those sets in number, in namespace, and in membership. The one exception is a
staff member not working that day: they are in no category, so membership can't be judged
and isn't checked.

A mapping whose `value` is `numeric` goes only after `MAXIMIZE` or `MINIMIZE`. Its value
is normalized to 0–1 against the mapping's declared scale. A key it has no row for takes
the mapping's default, which is the bottom of its scale unless the Mappings tab says
otherwise.

Any other mapping gives a name from the set its `value` names, and a call to it is a set
expression: it can stand wherever a set can, as a `set_` or inside `{…}`. The namespace a
call gives is the namespace of its `value`. What it stands for is:

- the name its row gives, if there is a row and that name is in the `value` set that day.
  A row naming somebody not working that day is passed over.
- otherwise the mapping's default, a Skedge phrase such as `ANY_1_OF {staff.office}`. A
  call standing alone with no quantifier stands for the whole phrase, quantifier and all.
  Anywhere else (inside `{…}`, or after a quantifier), a default that is `ANY_n_OF` is an
  error, because the solver hasn't chosen yet and the set can't be worked out. `ALL_OF`
  and single-name defaults are their sets.
- with neither a row nor a default, an error.

The Mappings tab is checked when the day loads: every key and value cell must name a name
in its set, and the default must be within the `value` set. The same exception applies to
staff not working that day.

## 10. Declarations

A declaration is lines of these kinds, in any order.

| Line | Form | Meaning |
|---|---|---|
| Statement | `[label:] REQUEST …` or `PREFER …` | §9. Only a positive `REQUEST … DO` may be labeled. |
| Binding | `EACH_OF x IN s`, `ANY_n_OF x IN s` | §6.4. |
| Condition | `IF <test>` | The statements apply only when this holds. |
| Negative condition | `UNLESS <test>` | The statements apply only when this does not hold. |
| Gap | `GAP a TO b <amount>` | Relates the assignments of the `REQUEST` labeled `a` to those of the one labeled `b`. |

A test is `[<amount> [CONSECUTIVE]] <pattern>`, which with no amount holds when there is a
match, or several tests joined by `AND` (all hold) or by `OR` (at least one does).
Parentheses group, and mixing `AND` with `OR` requires them. A condition may run over as
many lines as it reads well on: a line may end in `IF`, `UNLESS`, `AND`, `OR` or `(`, and
a line beginning with `AND` or `OR` continues the one above.

A declaration needs at least one statement and takes at most one condition, and may mix
`REQUEST` and `PREFER` statements freely: one piece of plain English often needs several
statements, and they belong together under one description, one priority and one weight.

Its `REQUEST` statements stand or fall together: the declaration is met when all of them
and all its gaps hold, or when its condition says they do not apply, and that is what the
report names. Its `PREFER` statements are weighed one by one in the declaration's tier,
whether or not the requirements are met. A condition governs both.

### 10.1 GAP

`GAP a TO b <bound> <duration>` compares the assignments of the two labeled requirements.
Every assignment of `a` must end before any of `b` starts, and the time from the end of the
last `a` to the start of the first `b` must meet the bound. `GAP a TO b AT_LEAST 0m` is
plain ordering, and the one place a zero amount is allowed. The times compared are real
starts and ends, so a task shorter than its block may sit anywhere in it to satisfy a gap.

A gap spans days. Times are counted from midnight on the date being scheduled, so an
assignment on a published day behind it is a negative time: 16:00 yesterday is −480. A
requirement whose `ON` reaches back is met by what that day already holds, and the gap is
measured from it, which is how `AT_LEAST 40h` between two meetings is read against the
meeting that actually happened.

A date *after* the one being scheduled holds nothing yet and so cannot be one end of a
gap. A requirement that defers to such a date is checked on the day it lands on, by which
time it is a published assignment like any other.

## 11. What can exist

Only a positive `REQUEST` makes things happen. `NOT`, `AT_MOST`, `PREFER`, `IF` and
`UNLESS` steer what is otherwise asked for and never create an assignment.

1. A clinic instance runs only if a `REQUEST … DO` names it. Rule 13.4 then staffs the rest
   of it.
2. A trainee or quoted-task assignment exists only where a `REQUEST … DO` asks for it, where
   a `REQUEST AT_LEAST` or `REQUEST EXACTLY` pattern matches it, or as the `WITH` partner
   one of those needs.
3. A `REQUEST` whose condition says it does not apply asks for nothing.
4. Nothing exists in a block an `EXCLUDE` has taken somebody out of, whatever asks for it.

A quoted task named in a pattern or a `NOT DO` that no positive `REQUEST` in any request
names is an error, not a line that does nothing.

## 12. Priorities and scoring

| Priority | Meaning |
|---|---|
| `MUST_HAPPEN` | Hard. If the hard requests cannot all hold, the solver reports the conflicting ids and produces no schedule. |
| `CLINIC` | Soft, first tier. Staffing the offered clinics. |
| `STABILITY` | Soft, second tier, set by the solver during a same-day change and not writable on a request. |
| `HIGH`, `MEDIUM`, `LOW` | Soft, in that order. |

`REQUEST` may have any priority. `PREFER` may not be `MUST_HAPPEN`, in a declaration of its
own or beside requirements: there is no tier above the hard one to weigh a preference in,
and a cap that must hold is `REQUEST AT_MOST`.

Soft tiers are solved lexicographically: a tier's score is maximized, fixed as a floor, and
the next tier is then maximized. No amount of a lower tier outweighs a higher one.

Within a tier, a declaration (or each `EACH_OF` copy of it) contributes:

| Statement | Contribution |
|---|---|
| `REQUEST` | 1 if the declaration is met, 0 otherwise |
| `PREFER <amount> …` | minus its **miss**: how far the matches are from the amount, in assignments, or in hours when the amount is a duration |
| `PREFER … MAXIMIZE` | the sum of the mapping's value over the matches |
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

The solver schedules `dates.target`.

- **Past dates** with a published schedule are facts. They cannot change, and they count
  exactly as today's assignments do, in every requirement, pattern, condition and amount.
- **Future dates** hold nothing yet.
- **Excluded blocks** (§9.1) hold nothing for the person excluded from them, on any date.
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
`ALL_OF` or `ANY_n_OF` inside a pattern or to the right of `NOT` (other than after `WITH` or
`WITHOUT`), `PREFER` with a
requirement, a label on a `PREFER`, `CONSECUTIVE` without an amount or anywhere but after
one or after `DURING`'s blocks, and `MAXIMIZE` without a mapping call. `CONSECUTIVE` after
a pattern, where it used to go, is told `CONSECUTIVE goes after the amount`. The validator
and the solver report:

| Message | Condition |
|---|---|
| `a declaration needs at least one statement` | Only bindings, conditions or `GAP` lines. |
| `needs a quantifier: ALL_OF, ANY_n_OF or EACH_OF` | A set with no quantifier in a requirement. |
| `is one item and takes no quantifier` | `ANY_1_OF staff.rob`. |
| `needs a quantifier: ALL_OF or ANY_n_OF` | `WITH` or `WITHOUT` a set of several, with no quantifier. |
| `takes ALL_OF or ANY_n_OF, not EACH_OF` | `WITH EACH_OF staff.mfgs`; likewise `WITHOUT`. |
| `one activity at a time` | `ALL_OF` or `ANY_2_OF` on a requirement's activity or `AS_ROLE`. |
| `needs DURING` | A positive requirement with no `DURING`. |
| `CONSECUTIVE after DURING chooses blocks next to each other` | `CONSECUTIVE` after `DURING` a single block, `ALL_OF`, `EACH_OF` or `ANY_1_OF`. |
| `given twice` | A clause repeated in one statement. |
| `only one IF or UNLESS per declaration` | Two condition lines. |
| `unknown … name` | A name that does not exist in its namespace. |
| `expected a … name` | A name or variable from the wrong namespace. |
| `unknown variable` | A bare identifier no `IN` binds. |
| `variable bound twice` | Two bindings of one identifier. |
| `mixed set operators need parentheses` | `{a + b & c}` and the like. |
| `mixed AND and OR need parentheses` | `IF a AND b OR c`. |
| `AS_ROLE needs an activity` | `AS_ROLE` with a quoted task or `FREE`. |
| `FOR needs a quoted task` | `FOR` with any other target. |
| `FREE has no instance` | `WITH` or `WITHOUT` after `FREE`. |
| `amount must be at least 1` | `AT_LEAST 0`. |
| `write NOT DO` | `AT_MOST 0`, `EXACTLY 0`. |
| `wrong number of arguments` | A mapping call with more or fewer arguments than the mapping has keys. |
| `takes a name from` | A mapping argument from the wrong namespace. |
| `is not in it` | A mapping argument outside its key's set. |
| `mapping argument must be one item` | A set, or an `ANY_2_OF` variable, as an argument. |
| `gives one from` | A mapping call where a name from another namespace belongs. |
| `gives a number, not a name` | A numeric mapping called where a set belongs. |
| `there is nothing to maximize or minimize` | `MAXIMIZE` or `MINIMIZE` of a mapping that gives names. |
| `and no default` | A mapping call whose key has no row, of a mapping with no default. |
| `its default is a choice` | A call falling back to an `ANY_n_OF` default inside a set or after a quantifier. |
| `PREFER needs a priority it can be weighed at` | A `PREFER` in a `MUST_HAPPEN` declaration; use `REQUEST AT_MOST`, `AT_LEAST` or `EXACTLY`. |
| `weight must be positive` | A weight of zero or less. |
| `unknown requester` | A `requester` field naming nobody on the Skills sheet. |
| `weight is not allowed with MUST_HAPPEN` | A weight on a hard request. |
| `GAP needs a duration` | `GAP a TO b AT_LEAST 3`. |
| `only REQUEST … DO can be labeled` | A label on a `NOT`, `FREE` or amount `REQUEST`. |
| `undefined label` | `GAP` naming a label that no statement defines. |
| `defined twice` | Two statements with the same label. |
| `EXCLUDE is a fact about the day, so it is MUST_HAPPEN` | An `EXCLUDE` at any other priority. |
| `EXCLUDE stands on its own line and its own request` | An `EXCLUDE` beside any other line. |
| `EXCLUDE says who is away, so nothing in it is ANY_n_OF` | `ANY_n_OF` anywhere in an `EXCLUDE`. |
| `EXCLUDE takes DURING and ON, not` | Any other clause on an `EXCLUDE`; the message names it. |
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
