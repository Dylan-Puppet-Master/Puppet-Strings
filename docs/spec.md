# Skedge specification

This is the normative definition of Skedge, the language requests are written in. It says
what every construct means and what is rejected. [Skedge reference](skedge.md) is the
readable version, with worked examples; where the two disagree, this document is right.

Parts of the language are checked mechanically against the code: the grammar below is the
grammar the parser uses, every error message listed here exists in the source, and every
`skedge` block in either document is parsed and validated by the test suite. A change to
one that is not made to the other fails the suite.

## 1. Scope

A **request** is one Skedge declaration plus the fields the request manager keeps with it:
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
are working that day and hold none, and neither if they are resting through it.

Skedge has two statements.

| | |
|---|---|
| `REQUEST` | A constraint that is either met or not met. |
| `PREFER` | A soft constraint that can be partly met: how close the day comes to a count or a length. |

Both say what happens — `<who> DO <what> …`, `<who> FREE …` or `<who> BUSY …` — with every
set in it taken whole, pooled or counted (§6). Right of `NOT`, and in a `PREFER … MAXIMIZE`,
the same words are a **pattern**: they match assignments, and nothing in them is counted
(§8).

## 3. Lexical structure

| Element | Form |
|---|---|
| Keyword | Either case, upper by convention: `REQUEST`, `PREFER`, `IF`, `UNLESS`, `THEN`, `AND`, `OR`, `GAP`, `TO`, `DO`, `EXCLUDE`, `NOT`, `FREE`, `BUSY`, `DURING`, `ON`, `AS_ROLE`, `FOR`, `WITH`, `WITHOUT`, `IN`, `ALL`, `ANY`, `EACH`, `AT_LEAST`, `AT_MOST`, `EXACTLY`, `CONSECUTIVE`, `MAXIMIZE`, `MINIMIZE` |
| Quantifier | `ALL`, `EACH`, `ANY`, a choice `ANY n`, and a count: `AT_LEAST n`, `AT_MOST n` or `EXACTLY n`, for any whole `n` from 1 |
| Name | Dotted, lower case, digits and underscores; any depth: `staff.mary_kate`, `dates.session_4.week_2` |
| Variable, label | A bare identifier: `s`, `morning`. A label or a definition is followed by a colon. |
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

// An ON on the first line is every statement's: written once, where they would each repeat it.
// Only the first, since an ON starting any later line carries on the statement above it.
start       : _NL* (on _NL+)? line (_NL+ line)* _NL*
?line       : binding | define | define_task | if_ | unless | labeled | request | prefer | gap
            | exclude

binding     : (EACH | any_n) NAME _IN set_
// A name for a set, written once and meaning the same wherever it is used. With ANY n or
// EACH in front it is a binding line spelled the other way round.
define      : NAME ":" (ALL | EACH | any_n)? set_
// A name for a quoted task, to write after DO wherever the task is meant.
define_task : NAME ":" STRING
// A condition is for the statements in its block, and only those. A block holds statements
// and further IFs, on lines of their own or all on one.
if_         : _IF _NL* condition _THEN _NL* block
unless      : _UNLESS _NL* condition _THEN _NL* block
block       : "{" _NL* (_inner _NL*)+ "}"
_inner      : if_ | unless | labeled | request | prefer | exclude
labeled     : NAME ":" request
// With no length, the second is only after the first: AT_LEAST 0m.
gap         : _GAP NAME _TO NAME length?

// A statement is its subject, verb and object in that order, with its clauses around them.
// DURING and ON may go anywhere; AS_ROLE, FOR, WITH and WITHOUT describe the activity, so
// the builder refuses them before the verb, which is why the verb is kept in the tree.
request     : _REQUEST _clauses chooser _clauses DO _clauses do_target _clauses               -> request_do
            | _REQUEST _clauses chooser _clauses                                             -> request_activity
            | _REQUEST _clauses chooser _clauses FREE _clauses                                -> request_free
            | _REQUEST _clauses chooser _clauses BUSY _clauses                                -> request_busy
            | _REQUEST _clauses chooser _clauses _NOT DO _clauses do_target _clauses          -> request_not_do
prefer      : _PREFER pattern                                                               -> prefer_count
            | _PREFER pattern goal _clauses                                                 -> prefer_score
            | _PREFER _clauses goal pattern                                                 -> prefer_score

// Who is not at camp for part of a day, and what to write where they would have been.
// It takes a quoted label rather than an activity: they are not doing anything here.
exclude     : _EXCLUDE _clauses chooser _clauses DO _clauses STRING _clauses

// A condition is one test, or several joined by AND or by OR. Mixing the two needs
// parentheses, as mixing set operators does, so there is no precedence to remember.
?condition  : term ((AND | OR) _NL* term)*        -> junction
?term       : test | "(" _NL* condition ")"
test        : pattern

pattern     : _clauses chooser _clauses DO _clauses do_target _clauses               -> pattern_doing
            | _clauses chooser _clauses FREE _clauses                               -> pattern_free
            | _clauses chooser _clauses BUSY _clauses                               -> pattern_busy
goal        : (MAXIMIZE | MINIMIZE) call
call        : REF "(" arg ("," arg)* ")"
?arg        : NAME | REF

// A count: AT_LEAST, AT_MOST or EXACTLY and a number, in front of the set it counts. A length
// is bounded the same way, and is a GAP's.
amount      : BOUND INT
length      : BOUND DURATION

?do_target  : chooser | STRING
_clauses    : clause*
?clause     : during | on | as_role | for_ | with_ | without
during      : _DURING chooser
on          : _ON chooser
as_role     : _AS_ROLE chooser
// A length says how it is bounded.
for_        : _FOR BOUND DURATION
// Who is alongside: one name, or several with ALL or a count to say how many, and with an
// AS_ROLE straight after them, in which role. That AS_ROLE is theirs, not the subject's,
// which is why the parser takes it here rather than as a clause of its own.
with_       : _WITH chooser as_role?
without     : _WITHOUT chooser as_role?

// ANY with no number is any of these: the set is one pool. ANY n chooses n of it, once for
// the statement. A count measures, in front of the set it counts. CONSECUTIVE is about
// blocks, after DURING: `ANY 2 CONSECUTIVE blocks` picks blocks in a row, and
// `ANY CONSECUTIVE blocks` pools each run for a FOR to measure.
chooser     : (ALL | ANY | amount)? CONSECUTIVE? set_
            | any_n CONSECUTIVE? set_
            | EACH set_
            | EACH NAME _IN set_
any_n       : ANY INT

// A set built from others is in braces, and so is every set inside it: {{a .. b} & c}. A
// range is the whole of its braces. Parentheses are for a group, which is a choice rather
// than a set.
?set_       : REF | NAME | DATE | call | "{" setexpr "}"
?setexpr    : operand (SETOP operand)*   -> setop
            | endpoint ".." endpoint     -> date_range
?operand    : endpoint
            | "{" setexpr "}"
            | "(" (ALL | any_n) set_ ")"   -> group
            | (ALL | any_n) set_           -> group
?endpoint   : date_atom OFFSET           -> date_offset
            | date_atom
?date_atom  : DATE | REF | NAME | call

// Two more ways in, for the cells of the Mappings tab rather than for a request: what a
// key or a value may be, and what stands in for a key with no row.
mapping_domain  : setexpr
mapping_default : chooser

// The keywords. A leading `_` keeps the token out of the tree, the way an anonymous string
// would; `.5` puts them above NAME, which lower case would otherwise be read as.
_REQUEST.5  : /REQUEST\b/i
_EXCLUDE.5  : /EXCLUDE\b/i
_PREFER.5   : /PREFER\b/i
_IF.5       : /IF\b/i
_UNLESS.5   : /UNLESS\b/i
_THEN.5     : /THEN\b/i
_GAP.5      : /GAP\b/i
_TO.5       : /TO\b/i
DO.5        : /DO\b/i
_NOT.5      : /NOT\b/i
_IN.5       : /IN\b/i
_DURING.5   : /DURING\b/i
_ON.5       : /ON\b/i
_AS_ROLE.5  : /AS_ROLE\b/i
_FOR.5      : /FOR\b/i
_WITH.5     : /WITH\b/i
_WITHOUT.5  : /WITHOUT\b/i
BOUND.5     : /AT_LEAST\b/i | /AT_MOST\b/i | /EXACTLY\b/i
ALL.5       : /ALL\b/i
EACH.5      : /EACH\b/i
ANY.5       : /ANY\b/i
FREE.5      : /FREE\b/i
BUSY.5      : /BUSY\b/i
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

// A statement may be written over as many lines as it reads well on. A new line starts a new
// statement only where one can start: at REQUEST, PREFER, EXCLUDE, IF, UNLESS or GAP, at a
// binding (`EACH x IN`, `ANY n x IN`), or at a name and a colon. Anywhere else the

// newline before it is nothing, so the line carries on the statement above it. The
// lookahead spells out how `binding`, `define` and `labeled` begin, so it changes with them.
_CONTINUES  : /(\r?\n[ \t]*)+(?![ \t\r\n]|(?i:REQUEST|PREFER|EXCLUDE|IF|UNLESS|GAP)\b|(?i:EACH|ANY[ \t]+\d+)[ \t]+[a-z_][a-z0-9_]*[ \t]+(?i:IN)\b|[a-z_][a-z0-9_]*[ \t]*:|$)/
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
| `staff` | Staff members, staff categories | `staff`, `staff.clinic_trainers` |
| `activities` | Clinics under `clinics`, cabin acts under `cabin_acts` | `activities`, `activities.clinics`, `activities.cabin_acts` |
| `blocks` | Blocks, block categories | `blocks` |
| `dates` | | `dates.target`, and the scopes below |
| `roles` | | `roles.first` … `roles.sixth`, `roles.lifeguard`, `roles.lifeguard_2` …, `roles.shadow`, `roles.scaffolded`, `roles.trainee` |
| `mappings` | The mappings on the Mappings tab | |
| `offerings` | The clinics on `dates.target`'s Offerings tab, under the block each runs in | `offerings` |

A namespace is plural because it holds many names. `activities` has a branch per kind of
activity, so `activities.clinics.archery_1_2` is a clinic and `activities.cabin_acts.p4`
is a cabin act; only `activities` is both.

An **offering** is one row of the Offerings tab: a clinic and the block it runs in, or the
two blocks of a double. `offerings.clinic_2.archery_1_2` is archery as offered in clinic 2,
an item; `offerings.clinic_2` is everything offered then, a set. A double is under both of
its blocks, and is the same item by either name. There are offerings only for
`dates.target`.

Every name is either an **item** (one thing: `staff.rob`, `blocks.clinic_1`, `dates.target`)
or a **set** (`staff.counselor`, `blocks`). Set names are plural or collective; there is
no name that means "any one of": that is what `ANY` and a count are for.

A staff category, and `staff`, hold only the people working on `dates.target`: someone
resting all day is in no category, though their own name still resolves. `staff` is the
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
| `dates.season` | set | every date the Calendar sheet covers |
| `dates.mondays` … `dates.sundays` | set | every date of the season falling on that weekday |
| `dates.weekdays`, `dates.weekends` | set | every Monday to Friday, and every Saturday and Sunday, of the season |
| `dates.session_1` … `dates.session_20` | set | a `main season` row, numbered in sheet order |
| `dates.<name>` | set | any other row, by its `name` column normalized |
| `dates.<span>.week_1` … `.week_20` | set | that week of that span |
| `dates.session_target` | set | the session `dates.target` falls in; absent outside the main season |
| `dates.session_target.week_target` | set | the week of that session `dates.target` falls in |

A span has no names for its days or for its first and last date. Its days are written as
what it shares with the season's: `{dates.session_2 & dates.thursdays}` is every Thursday of
session 2, and `{dates.session_2.week_1 & dates.sundays}` is the Sunday it starts on. That is
a set, even holding one date, so after `ON` it takes a quantifier.

A name exists only if the span reaches it: `dates.session_2.week_2` is a name only
when session 2 runs to a second week. At most 20 main season rows and 20 weeks per span.

Only `dates.target`,
`dates.session_target` and its `week_target` follow the date being scheduled; every other
date name says outright which span it means. A request naming `dates.session_target` on a
date in no session is invalid on that date and is left out of its solve, not an error that
stops it.

`roles.trainee` resolves per staff member from the Skills sheet: checked off or needing a
scaffold becomes `scaffolded`, needing a shadow or no checkoff becomes `shadow`.

`puppet-strings names` prints every name that currently exists.

## 6. Sets, quantifiers and variables

### 6.1 Set expressions

A set is a name, a variable, a date, a mapping call such as `mappings.buddy(c)` (§9.2),
or an expression in braces. Inside braces `+`, `-` and
`&` combine sets left to right, and a set inside the expression is in braces of its own:
`{a - {b & c}}`. Mixing two different operators without them is an error, so there is no
precedence to remember. `a .. b` is an inclusive date range, and is the whole of its
braces: combined with another set it is `{{a .. b} & c}`. A single date may be offset by
whole days, `d + 6d`, with no grouping needed. Parentheses around a set are an error; they
are for groups and conditions. An offset or range
endpoint that is not a single date is an error.

A **group** is a set with a quantifier in front of it, inside braces:
`{staff.charlton + ANY 1 {staff.dylan + staff.donny}}`, parentheses around it optional.
It is one part of the set it stands in, and says who is in it, so it is taken `ALL` or
`ANY n`, never counted:

- In a set taken whole (`ALL`, or with no quantifier), `(ALL s)` adds every member
  of `s`, and `(ANY n s)` adds `n` members of `s`, chosen. So
  `ALL {staff.charlton + (ANY 1 {staff.dylan + staff.donny})}` is Charlton and one of
  the other two, the same as a binding line `ANY 1 x IN {staff.dylan + staff.donny}`
  and `ALL {staff.charlton + x}`. The one not chosen is not ruled out.
- In a choice or a count, each group is one of the things chosen or counted, all of it:
  `ANY 1 {staff.lucy + (ALL {staff.tom + staff.charles})}` is Lucy, or else Tom and
  Charles together. In a count a group is taken whole, so it takes `ALL`.
- In `EACH`, each group is one copy: `EACH {staff.lucy + (ALL {staff.tom +
  staff.charles})}` is one request for Lucy and one for Tom and Charles together.

A group is added with `+` only. `(ALL s)` may also be taken away or crossed, where it is
just `s`; `(ANY n s)` may not, since what it holds is not known until the solver
chooses.

### 6.2 Quantifiers

Every set in a statement carries a quantifier; an item takes none.

| Quantifier | Meaning |
|---|---|
| `ALL s` | Every member of `s`, together, as one unit. |
| `ANY s` | Any of these: `s` is one pool, matched by any of its members. |
| `ANY n s` | A **choice**: `n` members of `s`, picked by the solver once for the statement, which then holds for each of them as if they had been named. |
| `AT_LEAST n s`, `AT_MOST n s`, `EXACTLY n s` | A **count**: how many members of `s` the rest of the statement holds for, compared so with `n`. |
| `EACH s` | The declaration is copied once per member, each copy a separate request. |

`n` is 1 or more. **A choice picks and a count measures.** A positive `REQUEST` asks for
something to happen, so it picks with `ANY n`; a test, a `PREFER`, a `FOR` and a `WITH`
measure what happens, and count. `AT_LEAST n` in a `REQUEST` is an error, since `ANY n`
says it; so is `EXACTLY n`, which would also forbid the rest, and is written as a choice
and a `NOT DO` (§6.3). The count a `REQUEST` takes is `AT_MOST`, a cap. `ANY n` in a test or
a `PREFER` is an error: they measure.

A choice never forbids: `ANY 1 {staff.dylan + staff.alesa} DO 'rake leaves'` is one of
those two raking, and says nothing about the other. A count counts the members of the set
it stands in front of, and nothing else. `AT_LEAST 3` holds with three or with four;
`AT_MOST` and `EXACTLY` rule the rest out, so a statement with either can forbid. On one
item a count of 1 is that item, which is how a `PREFER` weighs one thing; a larger count
there is an error. A pool never forbids either: `ANY {blocks.clinic_1 + blocks.clinic_2}`
holds when the thing happens in at least one of them, and says nothing against both.

Evaluation order is fixed:

1. Every `EACH` in the declaration splits it into copies, one per member; several give
   every combination. Each copy is an independent request with its own satisfaction,
   reported under `id[item, …]`. `EACH` over an empty set gives no copies, and the
   request is inactive.
2. Within a copy, each choice is made once, and the whole statement holds for what it
   picked: `ANY 2 staff.counselor DO 'x' DURING ANY 1 blocks` is two counselors in one
   block. The counts of a test or a `PREFER` apply one inside the other in this order,
   wherever each is written: the subject, the activity, `ON`, `DURING`. So `IF AT_MOST 2
   staff.counselor DO 'break' DURING AT_LEAST 3 blocks` holds when at most two
   counselors have three breaks or more each.
3. A set taken `ALL` is one unit inside every choice and count:
   `ALL {staff.lucy + staff.tom} DO … DURING ANY 1 blocks` is one block that both
   of them work. `EACH` gives each of them a block of their own.
4. A pool is innermost: it is matched by any of its members for each combination of the
   units and chosen or counted items around it. `ALL {staff.lucy + staff.tom} DO … DURING
   ANY blocks` gives each of them a block, not necessarily the same one.

`ANY` on the blocks of a statement is at least one of them, so for one person it is the
same as `ANY 1`; it differs only where rules 3 and 4 differ: a choice sits outside the
units, a pool inside them.

**A block is a block on a date.** Blocks happen every day, so where a statement's dates are
pooled with `ANY`, a count of its blocks counts each block on each of those dates:
`DURING AT_MOST 8 blocks.all_clinics ON ANY dates.session_1` is at most eight clinic
blocks over the session, clinic 1 on Monday and clinic 1 on Tuesday being two. Everywhere
else the blocks are counted on one date at a time — the dates are one date, split with
`EACH`, or counted outside the blocks by rule 2 — except under `ALL` dates, one unit by
rule 3, where a block counts when the rest holds in it on every one of them. A count of
blocks over pooled dates takes no group. `ANY n` of blocks over pooled dates is a pick of
blocks on those dates, the same way: `DURING ANY 2 blocks ON ANY dates.session_1`
is two blocks in the session, on one day or two.

The activity and `AS_ROLE` take one thing at a time, since a person does one thing in a
block. `ALL` of several activities needs the blocks pooled or counted, and `AS_ROLE` takes
a role, `ANY` or `EACH`. A choice or a count of activities is of different ones:
`DO ANY 2 activities.clinics DURING ANY blocks` is two different clinics.

`CONSECUTIVE` goes on the blocks, after `ANY`, `ANY n` or a count. `DURING ANY 2
CONSECUTIVE blocks` picks two adjacent blocks. `DURING AT_LEAST 2 CONSECUTIVE
blocks` holds when some **run** of adjacent blocks the rest holds for reaches 2,
`AT_MOST` when no run exceeds it, and `EXACTLY` when both do. Blocks are adjacent when they
are next to each other in the Blocks sheet, on one date. `DURING ANY CONSECUTIVE blocks`
pools each run on its own, for a `FOR` to measure (§7.1), and needs one. A run never
crosses from one date to the next.

### 6.3 Variables

`EACH x IN s` names the member each copy is about. `x` can then stand wherever a set
can, and as a mapping argument. Written inline, `x` is visible in that statement. Written on
a line of its own, it is visible in every line of the declaration:

| Binding line | Meaning |
|---|---|
| `EACH x IN s` | One copy of the declaration per member of `s`, with `x` that member. |
| `ANY n x IN s` | `x` is `n` members of `s`, chosen once for the whole declaration. With `n` of 1, `x` is an item; otherwise a set, which takes a quantifier where it is used. |

A binding line is the only way for two lines of a declaration to be about the same
person, block or date. It names particular items, so it picks with `ANY n` and is never
counted.

A chosen name may be added into a set with `+`, and taken away from a set with `-`:
`{s - x}` is the members of `s` it did not pick, each in or out as the choice goes. That is
how the rest of a set is forbidden, what `EXACTLY` would have said:

```
ANY 1 r IN {staff.dylan + staff.alesa}
REQUEST r DO 'rake leaves'
REQUEST ALL {{staff.dylan + staff.alesa} - r} NOT DO 'rake leaves'
```

It may not be crossed with `&`.

A **definition** gives a set a name: `office_elves: {staff.emily + staff.tori}`. The name
then stands for that set wherever a set can, in every line of the declaration, before or
after the definition, and in other definitions. It is written in where it is used, so it
chooses nothing on its own: a group inside it chooses afresh wherever it is used. The name
is nobody else's: a definition may not share it with a variable, a label or another
definition, and may not be defined in terms of itself.

A definition may also name a quoted task: `duty: 'on duty'`. The name then stands for the
task after `DO`, in any line of the declaration, and nowhere else: not in a set, and with no
quantifier, since it is one task.

With a quantifier after the colon, a definition is a binding line spelled the other way
round: `videographer: ANY 1 {staff.dylan + staff.donny}` is
`ANY 1 videographer IN {staff.dylan + staff.donny}`, and `c: EACH staff.counselor` is
`EACH c IN staff.counselor`. `x: ALL s` is `x: s`.

## 7. What happens

| Form | Holds for a staff member, a block and a date when |
|---|---|
| `<who> DO <what> [clauses]` | the staff member holds an assignment to the activity there, passing the clauses |
| `<who> FREE [clauses]` | the staff member is working and holds nothing there |
| `<who> BUSY [clauses]` | the staff member holds something there |
| `<who> NOT DO <what> [clauses]` | the staff member holds **no** assignment matching the pattern (§8) |

`<what>` is an activity or a `'quoted task'`. "Anything at all" is not a target: nothing to
do is `FREE`, something to do is `BUSY`, and someone resting is neither.

`REQUEST <activity> [clauses]`, with no subject, is `REQUEST ANY staff DO <activity>`: the
activity runs, staffed from its positions. `REQUEST <offering>` is the same for the
offering's clinic, `DURING` its block, or `ALL` of a double's two, `ON dates.target`. An
offering takes no clauses and no subject, and is one at a time, so all of a day's clinics
are `REQUEST EACH offerings`. An offering anywhere else is an error.

A missing `ON` is `ON dates.target`, everywhere in the language. A missing `DURING` is
`ANY` of the blocks the date has: `REQUEST staff.rob DO 'x'` is at least once today.

Everything to the right of `NOT` describes the situation that must not happen. It is a
pattern (§8): sets there are pools and take `ANY`, `DURING` may be left out to mean every
block, and `EACH` splits as anywhere, apart from `WITH` and `WITHOUT` (§8). A set there may
also take `ALL`, of plain names with no group or chosen name in it: what is forbidden is
then the positive request the words to the right of `NOT` make, with an assignment for
every combination of the `ALL` items, a part taken `ANY` matched by any of its items. Any
one combination on its own is allowed. Past dates count, as facts. A count is an error to
the right of `NOT`, and so is `ANY n`: what they could say is clearer as a cap on what does
happen, so "not in two or more" is `DURING AT_MOST 1`. The subject to the left of `NOT` is
who the `NOT` is about, taken whole or chosen with `ANY n`, so
`ANY 1 {staff.lucy + staff.tom} NOT DO 'break'` is "one of them, picked by the solver,
takes no break" and `ALL {…} NOT DO` is "none of them does".

Clauses of a statement:

| Clause | Meaning |
|---|---|
| `DURING <blocks>`, `ON <dates>` | When. |
| `AS_ROLE <role>` | In that role. Without it, any position of the activity; a trainee role only when named. |
| `FOR AT_LEAST\|AT_MOST\|EXACTLY <duration>` | How long (§7.1). |
| `WITH <staff>` | Enough others from the set are on the same instance (§8). |
| `WITHOUT <staff>` | Not enough are. |

### 7.1 Lengths

`FOR` measures the activity within one unit of the blocks. Blocks taken one at a time — an
item, `ALL`, `EACH`, `ANY n` or a count — make each block a unit, and a quoted-task piece
never leaves its block, so there `FOR` is the length of each piece:
`DO 'break' FOR EXACTLY 30m DURING ANY 3 blocks` is three breaks of 30 minutes. Blocks
pooled with `ANY` are one unit together, and `FOR` is what they add up to:
`DO 'video editing' FOR AT_LEAST 2h DURING ANY blocks` is two hours in whichever
blocks. `ANY CONSECUTIVE` makes each run a unit, a run being one staff member's blocks.
Pooled dates and people are added up the same way.

`FOR` always says how the length is bounded, `EXACTLY`, `AT_LEAST` or `AT_MOST`, as a
count does; a bare `FOR 2h` is an error. A quoted task with
no `FOR` fills its block. Under a `FOR` over a pool the pieces fill their blocks, all but
one, which may be cut short: to what remains, or under `AT_LEAST` to any length that
reaches it.

`FOR` on an activity, `FREE` or `BUSY` adds up the lengths of the blocks, so it needs the
blocks pooled: `EACH staff.counselor FREE FOR AT_LEAST 2h DURING ANY blocks.all_clinics`.

## 8. Patterns

Right of `NOT`, and in a `PREFER … MAXIMIZE` or `MINIMIZE`, the words describe the
assignments to match. `<who> DO <what> [clauses]` matches every assignment that passes all
of its parts; `<who> FREE [clauses]` and `<who> BUSY [clauses]` match every (staff, block,
date) in which the staff member is free, or busy. A clause left out does not filter, except
`ON`.

| Part | Passes an assignment when |
|---|---|
| `<who>` | its staff member is in the pool |
| `DO <what>` | its activity is in the pool, or is that quoted task |
| `DURING`, `ON`, `AS_ROLE` | its block, date, role is in the pool |
| `FOR <bound> <duration>` | its length compares so with the duration |
| `WITH <staff>` | enough others in the set hold an assignment on the same instance |
| `WITHOUT <staff>` | not enough do |

In a pattern a set is a **pool**: the pattern matches an assignment whose field is any
member. A pool says so with `ANY`: `ANY staff.counselor`. A set with no quantifier is an
error in a pattern; an item still takes none, and whether a name is an item is a question
about the name, not the day, so a cabin's act all season, `activities.cabin_acts.p4`, takes
`ANY` even on a day it comes to one act. `EACH` splits the declaration as anywhere. A count,
`ANY n` and an `(ANY n …)` group are errors in a pattern, and so is `ALL` in a score, which
matches one assignment at a time.

`WITH` and `WITHOUT` count company rather than match it. They take one name, or a set with
`ALL` or a count to say how many is enough: `WITH staff.vic` is Vic, `WITH AT_LEAST 2
staff.mfgs` at least two MFGs, `WITH ALL staff.mfgs` every MFG. A set of several with no
quantifier is an error, and so are `EACH` and `ANY`. This holds on both sides of `NOT`.

An `AS_ROLE` written straight after the set of a `WITH` or `WITHOUT` is theirs: it says which
role the others hold on the instance, a role, `ANY` of several or `EACH`, and counts them
only in it. `WITH staff.alan AS_ROLE roles.first` is Alan, first on the same instance. The
subject's own `AS_ROLE` goes anywhere else after the verb, so that it is not read as theirs.

`WITH` and `WITHOUT` are exact opposites: `WITHOUT AT_LEAST 1 staff.mfgs` is no MFG,
`WITHOUT ALL staff.mfgs` is not every MFG. "Others" excludes the assignment's own staff
member, so `ALL` does not ask anyone to be alongside themselves, and counts any role,
trainees included. For a quoted task shorter than its block, "the same instance" also means
the same start time. `AS_ROLE` needs an activity; `FOR` in a pattern needs a quoted task;
`WITH`, `WITHOUT` and `AS_ROLE` cannot follow `FREE` or `BUSY`.

## 9. Statements

| Statement | Met |
|---|---|
| `REQUEST <statement>` | when it holds |
| `PREFER <statement>` | by degree: the closer it comes to its outermost count, or to its `FOR`, the better |
| `PREFER <pattern> MAXIMIZE mappings.x(args)` | by degree: each match earns the mapping's value |
| `PREFER <pattern> MINIMIZE mappings.x(args)` | by degree: each match costs the mapping's value |
| `EXCLUDE <who> DO '<label>' [DURING] [ON]` | not met or unmet: applied (§9.2) |

A `REQUEST` is all or nothing. To get partial credit from a `REQUEST`, split it with
`EACH`: each copy is then met or not on its own. That is how "avoid" is written:
`REQUEST EACH staff.office NOT DO 'break' DURING EACH {blocks.breakfast + blocks.lunch}`
at a soft priority is one small request per person per block.

There is no `PREFER` for "as many as possible": that is `EACH` at a soft priority,
`REQUEST EACH staff.support DO 'lifeguard' DURING blocks.rest_hour`, each one who does it a
request met. "At least two, and more if possible" is that and a `REQUEST ANY 2 …` beside
it, in two declarations, since they matter differently.

A `PREFER` needs something to come close to: a count, or a `FOR`. Its **miss** is how far
the outermost count is from its `n`, the things below it counted as met or not, or how far
its `FOR` is from its duration, in hours. A soft wish that something happen at all is a
`REQUEST` at a soft priority, or a count of 1: `PREFER staff.dylan DO … DURING AT_LEAST 1
blocks.clinic_2`.

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

Nothing in an `EXCLUDE` is chosen or counted, so `ANY` and a count are refused in every
position. It takes no
clause but `DURING` and `ON`, holds no `IF`, no `GAP` and no label, is the only statement
in its declaration, and its priority is `MUST_HAPPEN`.

### 9.2 Mappings

A mapping call names its keys: `mappings.preference(s, c)`. Each argument is an item or a
variable bound by `EACH`. The Mappings tab gives each key a set, and the arguments must
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
- otherwise the mapping's default, a Skedge phrase such as `ANY 1 {staff.office}`. A
  call standing alone with no quantifier stands for the whole phrase, quantifier and all.
  Anywhere else (inside `{…}`, or after a quantifier), a default that is a choice is an
  error, because the solver hasn't chosen yet and the set can't be worked out. `ALL`
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
| Binding | `EACH x IN s`, `ANY n x IN s`, `x: ANY n s`, `x: EACH s` | §6.3. |
| Definition | `x: s`, `x: '<task>'` | A name for a set, or for a quoted task (§6.3). |
| Condition | `IF <test> THEN { … }` | The statements in the braces apply only when this holds. |
| Negative condition | `UNLESS <test> THEN { … }` | The statements in the braces apply only when this does not hold. |
| Shared dates | `ON <dates>`, on the first line only | Goes on every `REQUEST`, `PREFER` and `EXCLUDE`; none may have its own. |
| Gap | `GAP a TO b [<amount>]` | Relates the assignments of the `REQUEST` labeled `a` to those of the one labeled `b`. |

The braces hold statements, labeled or not, and further conditions, which apply only when
every condition around them holds; bindings, definitions and gaps go outside them. A
statement outside every condition always applies. A gap holds only when both of its
statements apply. The braces may be spread over lines, indented or not, or all on one.

A test is a statement that says what happens, true or false of the day, past dates and
today — with no count and no `FOR` it holds when it happens at all — or several tests
joined by `AND` (all hold) or by `OR` (at least one does). Parentheses group, and mixing
`AND` with `OR` requires them.

The subject, the verb and the object keep their order: who, then `DO`, `FREE` or `BUSY`,
then what. `DURING` and `ON` may go anywhere in a statement, before the subject included.
`AS_ROLE`, `FOR`, `WITH` and `WITHOUT` describe the activity, so they go after the verb,
before or after the object. `MAXIMIZE` or `MINIMIZE` goes before or after the pattern it
weighs.

A line may be written over as many lines as it reads well on. A new line starts a new line
of the declaration only where one can start: at `REQUEST`, `PREFER`, `EXCLUDE`, `IF`,
`UNLESS` or `GAP`, at a binding (`EACH x IN`, `ANY n x IN`), or at a name followed by a
colon. Anywhere else it carries on the line above. A line may also end in `IF`, `UNLESS`,
`AND`, `OR` or `(`.

A declaration needs at least one statement, takes any number of conditions, and may mix
`REQUEST` and `PREFER` statements freely: one piece of plain English often needs several
statements, and they belong together under one description, one priority and one weight.

Its `REQUEST` statements stand or fall together: the declaration is met when all of them
and all its gaps hold, or when its condition says they do not apply, and that is what the
report names. Its `PREFER` statements are weighed one by one in the declaration's tier,
whether or not the requirements are met. A condition governs both.

### 10.1 GAP

`GAP a TO b [<bound> <duration>]` compares the assignments of the two labeled
requirements. Every assignment of `a` must end before any of `b` starts, and the time from
the end of the last `a` to the start of the first `b` must meet the bound. With no bound it
is only that order, as `AT_LEAST 0m` is, which is the one place a zero amount is allowed. The times compared are real
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

1. A clinic instance runs only if a `REQUEST … DO` names it, by itself or in a set taken
   `ALL`. A pool or a count of activities, or a `FOR` over them, counts the clinics that run
   and asks for none of its own. Rule 13.4 then staffs the rest of it.
2. A trainee or quoted-task assignment exists only where a positive `REQUEST` asks for it,
   one that does not only cap it with `AT_MOST`, or as the `WITH` partner one of those
   needs.
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
and a cap that must hold is a `REQUEST` with `AT_MOST`.

Soft tiers are solved lexicographically: a tier's score is maximized, fixed as a floor, and
the next tier is then maximized. No amount of a lower tier outweighs a higher one.

Within a tier, a declaration (or each `EACH` copy of it) contributes:

| Statement | Contribution |
|---|---|
| `REQUEST` | 1 if the declaration is met, 0 otherwise |
| `PREFER` with a count or a `FOR` | minus its **miss** (§9), in things counted, or in hours for a `FOR` |
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
  exactly as today's assignments do, in every statement, pattern, condition and count.
- **Future dates** hold nothing yet.
- **Excluded blocks** (§9.1) hold nothing for the person excluded from them, on any date.
- A request all of whose dates are past, or all future, is inactive.
- A positive `REQUEST` that could still be met on later dates is **deferrable**: one whose
  `ON` is pooled or chosen with `ANY n` and can still reach later dates, or a `FOR`
  over dates that reach past the target. Today it must only stay reachable:
  what is still missing after today may not exceed what the later dates can hold. A later
  date holds nothing for a staff member resting through it or a block that does not exist
  on it. On the last date that can hold anything, the whole remainder is due. Until then
  the solver has a small incentive to act early.
- `ALL` dates, `NOT` and `AT_MOST` are enforced every day.
- The solver keeps no memory between days. A choice made on an earlier day is known only
  through the published schedule, which is why past dates count as facts.

## 15. Errors

Every error names the line and column. The parser reports what it expected, which covers a
label on a `PREFER` and `MAXIMIZE` without a mapping call. The parser, the validator and
the solver report:

| Message | Condition |
|---|---|
| `a declaration needs at least one statement` | Only bindings, definitions, conditions or `GAP` lines. |
| `ANY needs a number of 1 or more` | `ANY 0 staff.x`. |
| `to pick` | `AT_LEAST n` on a set a `REQUEST` chooses from; the message gives `ANY n`. |
| `EXACTLY forbids the rest; pick with ANY` | `EXACTLY n` on a set a `REQUEST` chooses from. |
| `measures, so it counts with AT_LEAST, AT_MOST or EXACTLY` | `ANY n` in a test or a `PREFER`. |
| `amount must be at least 1` | `AT_LEAST 0`. |
| `write NOT DO` | `AT_MOST 0`, `EXACTLY 0`. |
| `a count counts the members of a set, and` | A count of 2 or more on one item: `AT_LEAST 2 staff.charlton`. |
| `a group in a count is taken whole, so it takes ALL` | An `(ANY n …)` group inside a count. |
| `a count of blocks over pooled dates counts each block on each date` | `DURING AT_MOST 3 {blocks.a + (ALL …)} ON ANY …`. |
| `a pattern matches one assignment at a time` | `ALL`, `ANY n`, a count or a group in the pattern of a `PREFER … MAXIMIZE`, other than after `WITH` or `WITHOUT`. |
| `right of NOT a set takes ANY, for any of these` | A count, `ANY n` or an `(ANY n …)` group to the right of `NOT`, other than after `WITH` or `WITHOUT`. |
| `ALL right of NOT takes names, not groups or chosen names` | `NOT DO … ALL {staff.x + (ANY 1 …)}` and the like. |
| `a set here is matched, so it takes ANY` | A set with no quantifier in a pattern or to the right of `NOT`. |
| `left of NOT the subject is who the NOT is about` | `ANY` as the subject of a `NOT`. |
| `left of NOT the subject is chosen, so it takes ANY` | `AT_LEAST 1 staff.x NOT DO …`; the message gives `ANY n`. |
| `ANY pools names, not groups or chosen names` | `ANY {staff.x + (ALL …)}`, or `ANY` of a set holding a bound name. |
| `is defined twice` | Two definitions of one name, or a definition sharing its name with a variable or label. |
| `is defined in terms of itself` | `a: {staff.x + b}` and `b: {staff.y + a}`. |
| `names a task, which goes after DO, not in a set` | A task's name used in a set, or after `WITH`. |
| `names one task, so no quantifier` | `DO ANY duty`, where `duty` names a task. |
| `names one item at a time, and` | `EACH x IN` a set holding a group. |
| `CONSECUTIVE counts blocks one at a time, so no groups` | A group in `DURING … CONSECUTIVE …`. |
| `CONSECUTIVE comes after ANY, ANY n or a count` | `DURING ALL CONSECUTIVE …` or `CONSECUTIVE` with no quantifier. |
| `CONSECUTIVE is about blocks, so it goes after DURING` | `CONSECUTIVE` in any clause but `DURING`, or on a subject or activity. |
| `ANY CONSECUTIVE pools each run of blocks for a FOR to measure` | `DURING ANY CONSECUTIVE …` with no `FOR`; to pick blocks in a row, `ANY n` goes there instead. |
| `right of NOT there are no blocks to choose, so no CONSECUTIVE` | `NOT DO … DURING ANY CONSECUTIVE …`; the message gives the count that limits a run instead. |
| `a score counts no runs, so no CONSECUTIVE` | `CONSECUTIVE` in the pattern of a `PREFER … MAXIMIZE`. |
| `needs a quantifier: ALL, ANY, ANY n, EACH or a count` | A set with no quantifier in a statement. |
| `is one item and takes no quantifier` | `ANY staff.rob`; `WITH AT_LEAST 1 staff.vic`; `ALL blocks.clinic_1` right of `NOT`. |
| `needs a quantifier: ALL or a count` | `WITH` or `WITHOUT` a set of several, with no quantifier. |
| `counts who is alongside, so it takes ALL or a count` | `WITH EACH staff.mfgs` or `WITH ANY staff.mfgs`; likewise `WITHOUT`. |
| `an offering already says when it runs, so it takes nothing more` | Any clause on `REQUEST <offering>`. |
| `an offering is asked for on its own, as REQUEST EACH offerings` | An offering after `DO`, after `NOT DO`, or in a pattern. |
| `one offering at a time: REQUEST EACH offerings` | `ALL`, `ANY` or a count of offerings. |
| `one activity at a time` | `ALL` of several activities in blocks that are not pooled or counted, or a group on the activity. |
| `one role at a time: AS_ROLE takes a role, ANY or EACH` | `ALL` of several roles, or a count of them. |
| `describes the activity, so it goes after` | `AS_ROLE`, `FOR`, `WITH` or `WITHOUT` before the verb; the message names the clause and the verb. |
| `FOR on an activity, FREE or BUSY measures its time across blocks` | Such a `FOR` with its blocks not pooled. |
| `PREFER is weighed by how close it comes, so it needs a count or a FOR length` | A `PREFER` with neither. |
| `a GAP is measured from what a REQUEST makes` | A labeled `REQUEST` with a cap, `ANY n` blocks over pooled dates, or a `FOR` over a pool. |
| `given twice` | A clause repeated in one statement. |
| `the ON on the first line gives this its dates already` | A statement with its own `ON` under an `ON` on the first line. |
| `is a namespace, so it can't name anything else` | A variable, label or definition called `staff`, `blocks` or another namespace. |
| `unknown … name` | A name that does not exist in its namespace. |
| `expected a … name` | A name or variable from the wrong namespace. |
| `unknown variable` | A bare identifier no `IN` binds. |
| `variable bound twice` | Two bindings of one identifier. |
| `mixed set operators need braces around one side` | `{a + b & c}` and the like. |
| `mixed AND and OR need parentheses` | `IF a AND b OR c`. |
| `AS_ROLE needs an activity` | `AS_ROLE` with a quoted task, `FREE` or `BUSY`. |
| `FOR needs a quoted task` | `FOR` in a pattern with any other target. |
| `FREE and BUSY have no instance` | `WITH` or `WITHOUT` after `FREE` or `BUSY`. |
| `wrong number of arguments` | A mapping call with more or fewer arguments than the mapping has keys. |
| `takes a name from` | A mapping argument from the wrong namespace. |
| `is not in it` | A mapping argument outside its key's set. |
| `mapping argument must be one item` | A set, or a variable bound to several, as an argument. |
| `gives one from` | A mapping call where a name from another namespace belongs. |
| `gives a number, not a name` | A numeric mapping called where a set belongs. |
| `there is nothing to maximize or minimize` | `MAXIMIZE` or `MINIMIZE` of a mapping that gives names. |
| `and no default` | A mapping call whose key has no row, of a mapping with no default. |
| `its default is a choice` | A call falling back to an `ANY n` default inside a set or after a quantifier. |
| `a default is one choice, so it takes ALL or ANY n` | A default written with `EACH`, `ANY` or a count. |
| `a default of more than one name needs ALL or ANY n` | A default of several names with no quantifier. |
| `PREFER needs a priority it can be weighed at` | A `PREFER` in a `MUST_HAPPEN` declaration; use a `REQUEST`, with `AT_MOST` for a cap. |
| `weight must be positive` | A weight of zero or less. |
| `unknown requester` | A `requester` field naming nobody on the Skills sheet. |
| `weight is not allowed with MUST_HAPPEN` | A weight on a hard request. |
| `only REQUEST … DO can be labeled` | A label on a `NOT`, `FREE` or `BUSY` `REQUEST`. |
| `undefined label` | `GAP` naming a label that no statement defines. |
| `defined twice` | Two statements with the same label. |
| `EXCLUDE is a fact about the day, so it is MUST_HAPPEN` | An `EXCLUDE` at any other priority. |
| `EXCLUDE stands on its own line and its own request` | An `EXCLUDE` beside any other line but a definition. |
| `EXCLUDE says who is away, so nothing in it is chosen, counted or ANY` | A count, `ANY`, `ANY n` or an `(ANY n …)` group anywhere in an `EXCLUDE`. |

| `EXCLUDE takes DURING and ON, not` | Any other clause on an `EXCLUDE`; the message names it. |
| `date range ends before it starts` | A backwards range. |
| `needs a single date here` | An offset or range endpoint that is a set of dates. |
| `invalid date` | A date that is not a date. |
| `no request asks for` | A quoted task that no positive `REQUEST` asks for. |

## 16. Left to the implementation

The language does not decide these, and a future version may change them without any
declaration meaning something different:

- Which optimal schedule is chosen when several score the same.
- How long the solver spends on each tier, and what it reports when it runs out of time.
- That a task shorter than its block sits as early in it as the constraints allow.
- The scale factor the objective uses internally, and the size of the incentive to do a
  deferrable request early.
- How `EACH` copies, counts and pools are encoded. They need not be enumerated.
- Which piece of a `FOR` over a pool is the one cut short, and how short.
