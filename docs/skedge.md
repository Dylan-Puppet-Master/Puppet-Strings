# Skedge reference

Skedge is the language requests are written in. A request reads as a sentence with a
subject, a verb and an object:

```skedge
REQUEST staff.dylan DO 'archery maintenance' DURING ANY 1 blocks.all ON ANY 1 {2026-09-14 .. 2026-09-18}
```

This page is the readable version, with worked examples. For the exact rules, including
the grammar and every error the validator reports, see the
[Skedge specification](spec.md).

## Skedge in one minute

An **assignment** is one staff member doing one activity in one role in one block on one
date. There are two statements:

| Statement | Meaning |
|---|---|
| `REQUEST` | A constraint that is either met or not met. Its priority says how much it matters; `MUST_HAPPEN` makes it hard. |
| `PREFER` | A soft constraint that can be partly met: closer is better. |

And two ways to talk about assignments:

| Form | Meaning |
|---|---|
| `<what> DURING <blocks> ON <dates>` | An **activity requirement**: this activity happens, then. It names nobody, because the activity already says who may run it. |
| `<who> DO <what> DURING <blocks> ON <dates>` | A **requirement**: these people do this, then. |
| `<amount> <who> DO <what> …` | A **pattern**, with how many of it you want: all the assignments where these people are doing this. Used for counting, scoring and conditions. |

In a requirement, every set of names says out loud how it is meant:

| Quantifier | Meaning |
|---|---|
| `ALL_OF {staff.lucy + staff.tom}` | Both of them, together, all or nothing. |
| `ANY 1 {staff.lucy + staff.tom}` | One of them, the solver's choice. `ANY 2`, `ANY 3`, … work the same way. |
| `EACH_OF {staff.lucy + staff.tom}` | A separate request for each of them, each met or not on its own. |

A single thing (`staff.rob`, `blocks.clinic_1`, `2026-09-21`) needs no quantifier. A missing
`ON` means the day being scheduled.

`NOT DO` forbids, `FREE` means nothing to do (and `NOT FREE` something), `WITH` / `WITHOUT` say who is alongside,
`IF` / `UNLESS` make a request conditional (`AND` / `OR` join conditions), `GAP` puts time between two requirements, and
`EXCLUDE` takes somebody out of the day altogether. That is the whole language.

Keywords are written in upper case here and everywhere else, which is what makes a request
skimmable, but they are read in either case: `request staff.dylan do 'x' during
blocks.clinic_1` is the same request, and the editor colours it the same. Names, variables
and labels are lower case, so none of them may be spelled like a keyword — `on` is `ON`,
whatever was meant by it.

## Names

Names are dotted, lowercase `snake_case`. Sheet values become identifiers by the rule in
[The sheets](sheets.md). `puppet-strings names` lists them all.

| Namespace | Contents |
|---|---|
| `staff` | Staff members and staff categories, plus `staff.all`, `staff.clinic_trainers` |
| `activity` | Clinics and their categories (`activities.clinics.ropes`), plus `activities.clinics.all` |
| `block` | Blocks and block categories (`blocks.meals`), plus `blocks.all` |
| `date` | `dates.target`, and the nested scopes below |
| `role` | `roles.first`, `roles.second`, …; `roles.lifeguard`, `roles.lifeguard_2`; `roles.shadow`, `roles.scaffolded`, `roles.trainee` |
| `mapping` | Mapping tables, such as `mappings.preference` and `mappings.buddy` |

A name is either one thing or a set, and sets are always plural or collective
(`blocks.all`, `dates.session.one.mondays`). There is no `blocks.any`: "any one block" is
`ANY 1 blocks.all`, so the choosing is always visible.

A staff category holds only the people working on the day being scheduled. Someone resting
all day is in no category, though their own name still works.

`staff.all` is everyone the span's Staff Categories sheet names, not everyone on the Skills
sheet. Skills keeps every person who has ever worked here; the Staff Categories sheet says
who is here this span.

There is no name for "anyone checked off on a skill". Asking for a skill is asking for
somebody to do a thing that needs it, and the thing already says so: that is what an
activity's positions are. See
[asking for an activity without naming anybody](#asking-for-an-activity-without-naming-anybody).

### Dates

Date names are the Calendar sheet read out loud. Each row of that sheet is a **span** — a
session, or any other run of days camp runs — and every span carries exactly the same
names, so what can be said of one can be said of any other.

| Span | Written | Holds |
|---|---|---|
| The season | `dates.season.all` | Every date the Calendar sheet covers. |
| A session | `dates.session.four.all` | Every date of session 4. |
| Anything else | `dates.other.family_camp.all` | Every date of that row. |
| A week of a span | `dates.session.four.week.two.all` | Every date of its second week. |

Main season rows are numbered in sheet order and named by number in words — `one`, `two`,
`three` … — and so are weeks. Any other row is named after its `name` column.

**Every date name says which span it means.** There is no `this` session or `this` week: a
request about the session being scheduled names that session. `dates.target` is the only
name that follows the date on the toolbar, which is why a request reads the same whenever
you open it.

Every span carries these:

| Name | Holds |
|---|---|
| `dates.session.four.all` | Every date in it. |
| `dates.session.four.first`, `.last` | Its first and last date. |
| `dates.session.four.mondays` … `.sundays` | Every Monday of it. |

A week is short enough to reach each weekday once, so inside a week the weekday is a
single date:

| Name | Holds |
|---|---|
| `dates.session.four.week.two.monday` | One date: that week's Monday. |
| `dates.session.four.week.two.first`, `.last` | That week's first and last date. |

And `dates.target` is the date being scheduled, which is the date every request is about
unless it says `ON` something else.

```skedge
REQUEST ALL_OF staff.director DO 'session opening' DURING ANY 1 blocks.all ON ALL_OF dates.session.two.week.one.all
```

**There is no `first_monday` or `last_friday`.** A week's weekday says the same thing and
says it once: the second Thursday of a session is `dates.session.one.week.two.thursday`.

A name a span never reaches does not exist, and using it is a validation error rather than
a request that silently never fires. A near miss is told the nearest real name.

### Combining sets

Any expression goes in braces. `+` is union, `-` is difference, `&` is intersection, `..`
is an inclusive date range, and a single date can be offset by days. Parentheses group, and
mixing different operators requires them, so there is no precedence to remember:

```
{staff.all - staff.director - staff.counselor}
{staff.all - (staff.counselor & staff.lifeguard)}
{(dates.target - 6d) .. dates.target}
```

### Choosing inside a set

A quantifier can also go inside a set, on a part of it in parentheses. That part is a
**group**, taken the way its own quantifier says. In a set taken whole, `(ANY 1 …)` adds
whichever one the solver picks — "Alesa and one of these two":

```skedge
REQUEST ALL_OF {staff.alesa + (ANY 1 {staff.dylan + staff.cam_vl})}
DO 'Video KM Rope Swing' FOR 30m
DURING ANY 1 blocks.all
```

In `ANY n`, each group counts as one of the things chosen from, so `(ALL_OF …)` keeps
people together — "Lucy, or else Tom and Charles together":

```skedge
REQUEST ANY 1 {staff.lucy + (ALL_OF {staff.tom + staff.charles})} DO 'take out garbage' DURING ANY 1 blocks.all
```

In `EACH_OF`, each group is one of the separate requests: `EACH_OF {staff.lucy +
(ALL_OF {staff.tom + staff.charles})}` is one request for Lucy and one for Tom and Charles
together.

A group is added with `+`. `(ALL_OF s)` may be taken away or crossed like `s`, but
`(ANY n s)` may not: what it holds is not known until the solver has chosen.

## Requirements: `<who> DO <what>`

```skedge
REQUEST ALL_OF {staff.lucy + staff.tom} DO 'take out garbage' DURING ANY 1 blocks.all ON EACH_OF dates.session.one.mondays
```

Read it in three steps, always in this order:

1. **`EACH_OF` splits.** There is one separate request per Monday.
2. **`ANY n` chooses, once.** Within each Monday's request, the solver picks one block.
3. **Everyone chosen does it in every chosen block on every chosen date.** Lucy and Tom
   both take out the garbage in that one block, so they do it together.

A requirement never forbids anything. `DURING ANY 1 {blocks.clinic_1 + blocks.clinic_2}`
is met when the thing happens in one of them, and does not mind if it happens in both.

The difference between the three quantifiers, on one example:

| Request | Meaning |
|---|---|
| `REQUEST staff.rob DO activities.clinics.ropes_course AS_ROLE roles.first DURING ALL_OF {blocks.clinic_1 + blocks.clinic_2} ON 2026-09-28` | Rob is first on ropes in both clinics. One request: both or it is not met. |
| `… DURING ANY 1 {blocks.clinic_1 + blocks.clinic_2} …` | Rob is first on ropes in clinic 1 or clinic 2. One request. |
| `… DURING EACH_OF {blocks.clinic_1 + blocks.clinic_2} …` | Two requests, one per clinic. Rob may end up with neither, one or both, and each counts on its own. |

At `MUST_HAPPEN`, `ALL_OF` and `EACH_OF` come to the same schedule. They differ when the
request is soft: `ALL_OF` earns nothing for half, `EACH_OF` earns half.

| Clause | Meaning |
|---|---|
| `DURING <blocks>` | When in the day. Required. |
| `ON <dates>` | Which dates. Left out: the day being scheduled. |
| `AS_ROLE <role>` | In that position or trainee role. Left out: any position. |
| `FOR <duration>` | How long each one is. Ad hoc tasks only; left out, a task fills its block. |
| `WITH <staff>` | That person is working the same clinic or task alongside; of a set, `ANY n` or `ALL_OF` says how many of it. |
| `WITHOUT <staff>` | The opposite of `WITH` the same. |

An ad hoc task such as `'break'` has no positions, skills or camper slots; it occupies
staff time only. `'break' FOR 30m` is a 30-minute break somewhere inside one block, the
Staff View labels the rest of the block `DYOW/WPs`, and several short tasks can share a
block.

### Blocks in a row

`CONSECUTIVE` right after `ANY n` blocks chooses blocks that are next to each other:

```skedge
REQUEST ALL_OF {staff.lucy + staff.tom} DO 'take out garbage' DURING ANY 2 blocks.all CONSECUTIVE
```

Lucy and Tom take out the garbage together, in two blocks one after the other. Blocks are
next to each other when they are next to each other in the Blocks sheet, so
`ANY 2 blocks.all_clinics CONSECUTIVE` may be clinic 1 and 2, but not clinic 2 and 3
with lunch between them. It needs `ANY n` with n of 2 or more: anything else has nothing
to choose.

`CONSECUTIVE` always comes right after what it is about. After `ANY n` blocks it is the
blocks chosen; after an amount ([patterns](#patterns-who-do-what)) it is the amount,
measured over runs.

### Asking for an activity without naming anybody

An activity already records who may run it: each of its positions needs a skill, and a
cabin act's positions may name a person or a category outright. So a request for an
activity names only the activity:

```skedge
REQUEST activities.clinics.archery_1_2 DURING blocks.clinic_2
```

That asks that archery runs in clinic 2, staffed by whoever its positions allow. There is
no `DO`, because there is no subject: adding `ANY 1 staff.all DO` in front would say the
same thing twice. Filling one position of an activity fills them all, so this is a request
for every person it needs, and the report names the activity once rather than once per
position.

`EACH_OF` over a set asks for each of them separately, which is how two lines ask for a
whole board of cabin acts: one for the acts in the cabin act block, one for those the
board moved to rest hour:

```skedge
REQUEST EACH_OF activities.cabin_acts.at_cabin_act DURING blocks.cabin_act
REQUEST EACH_OF activities.cabin_acts.at_rest_hour DURING blocks.rest_hour
```

To narrow who may run something beyond what the activity says, say so in a second
statement rather than in this one:

```skedge
REQUEST activities.clinics.candle_making DURING blocks.clinic_1
REQUEST EACH_OF staff.counselor NOT DO activities.clinics.candle_making
```

### NOT DO and FREE

| Request | Meaning |
|---|---|
| `REQUEST staff.dylan NOT DO activities.clinics.ropes` | Dylan does no ropes clinic today. |
| `REQUEST staff.dylan FREE DURING ALL_OF blocks.all ON 2026-09-16` | At camp with nothing assigned all day. Somebody away is an [`EXCLUDE`](#exclude-somebody-who-is-not-here). |
| `REQUEST EACH_OF {staff.all - staff.director} FREE DURING blocks.playstation` | Each non-director should have nothing on during playstation. |
| `REQUEST EACH_OF staff.counselor NOT FREE DURING blocks.clinic_1` | Every counselor has something to do in clinic 1. |

`FREE` means working that day with nothing assigned in the block; `NOT FREE` means having
something assigned. Someone resting is neither. There is no word for "anything": nothing to
do is `FREE`, something to do is `NOT FREE`.

The subject of a `NOT` still chooses: `ALL_OF {…} NOT DO` is "none of them does",
`ANY 1 {…} NOT DO` is "one of them doesn't". Everything to the right of `NOT` is a plain
description of what must not happen: sets there mean "any of these", `DURING` can be left
out to mean all day, and the only quantifier allowed is `EACH_OF` (`WITH` and `WITHOUT`
count company instead, below). `NOT DO ANY 1 …` is rejected, because it reads two ways
in English.

**This is how "avoid" is written.** A `REQUEST` is all or nothing, so split it small and
give it a soft priority:

```skedge
REQUEST EACH_OF staff.office NOT DO 'break' DURING EACH_OF {blocks.breakfast + blocks.lunch} ON EACH_OF dates.season.fridays
```

That is one small request per person, per meal, per Friday. Each break at a meal fails
exactly one of them, so three such breaks are three times as bad as one.

### WITH and WITHOUT

| Request | Meaning |
|---|---|
| `REQUEST staff.rob NOT DO activities.clinics.ropes WITHOUT staff.vic` | If Rob is on ropes, Vic must be on it too. |
| `REQUEST EACH_OF staff.junior NOT DO activities.clinics.waterfront WITHOUT ANY 1 staff.senior` | No junior at the waterfront unless a senior is there. |
| `REQUEST staff.rob NOT DO activities.clinics.ropes WITHOUT ALL_OF {staff.vic + staff.charlton}` | Rob is on ropes only with both Vic and Charlton. |
| `REQUEST staff.jack NOT DO activities.clinics.all WITH staff.lucy` | Jack and Lucy never share a clinic. |

One name stands alone. A set of several needs `ANY n` (at least n of them) or `ALL_OF`
(every one of them), even to the right of `NOT`: `WITHOUT staff.senior` would not say
whether one senior is enough.

"X only if Y is there too" is always "X `NOT DO` it `WITHOUT` Y". At `MUST_HAPPEN` these
are hard rules; at a soft priority they are wishes.

## Patterns: `<who> DO <what>`

A pattern describes assignments without asking for them. It is the same `DO` a requirement
is written with; what makes it a pattern is the amount in front of it. Sets in a pattern
are pools ("any of these"), and the only quantifier is `EACH_OF`, apart from `WITH` and `WITHOUT`. Put an amount in front and it
becomes something you can request or prefer:

| Request | Meaning |
|---|---|
| `REQUEST AT_MOST 2 staff.all DO 'break' DURING EACH_OF blocks.all` | Never more than two people on break at once. Met or not. |
| `PREFER AT_MOST 8 EACH_OF staff.all DO activities.clinics.all ON dates.session.one.all` | Nobody should run more than 8 clinics a session. Ten is twice as bad as nine. |
| `REQUEST AT_LEAST 2h staff.james DO 'dance practice' ON {2026-09-16 .. 2026-09-17}` | James's dance practice adds up to two hours. |

An amount is `AT_LEAST`, `AT_MOST` or `EXACTLY`, then a number of assignments or a length
of time. Add `CONSECUTIVE` right after it and it is measured over back-to-back blocks on one
day: `AT_LEAST 2h CONSECUTIVE …` is one unbroken two-hour stretch, `AT_MOST 3 CONSECUTIVE …`
is never more than three in a row.

`REQUEST` and `PREFER` take the same amount and pattern. `REQUEST` is met or not, and can
be `MUST_HAPPEN`. `PREFER` is never hard and is scored by how far off it is.

### Mappings

A mapping is a table on the [Mappings tab](sheets.md#mappings-config-spreadsheet) that
takes one or more names and gives back either a number or another name. You call it with
one argument per key: `mappings.buddy(c)`. `EACH_OF x IN <set>` gives each copy's item a
name, so a mapping can be told what to look up.

A **numeric** mapping is a table of ratings, and is what `MAXIMIZE` and `MINIMIZE` score
by:

```skedge
PREFER EACH_OF s IN staff.all DO EACH_OF c IN activities.clinics.all MAXIMIZE mappings.preference(s, c)
```

For each staff member `s` and clinic `c`, every assignment of `s` to `c` earns
`mappings.preference(s, c)`, normalized to 0–1. `MINIMIZE` makes it a cost instead. A pair
the mapping has no row for is worth that mapping's `default`.

Any other mapping gives a **name**, and a call to it goes anywhere a name can. Each cabin
has a buddy HERO who covers it at dinner, and `mappings.buddy` says who:

```skedge
# Every counselor's buddy covers their cabin at dinner.
EACH_OF c IN staff.counselor
REQUEST mappings.buddy(c) DO 'cabin cover' DURING blocks.evening
```

A counselor whose cabin has no row gets the mapping's `default`, which is a phrase such as
`ANY 1 {staff.all - staff.counselor - staff.director}`: the call stands for that phrase,
quantifier and all, so the solver picks one of them. So does a counselor whose buddy is
resting or away that day, since a buddy who isn't at work can't cover anyone.

The Mappings tab says what a mapping takes and gives, so a call is checked like any other
name. `mappings.buddy(staff.alan)` is an error if Alan isn't a counselor, and so is
`mappings.buddy(c)` written where an activity belongs. A call can also go inside a set,
`ALL_OF {staff.office - mappings.buddy(c)}`, but only when it gives one name or an
`ALL_OF` set. A default of `ANY 1` is a choice the solver hasn't made yet, so nothing
can be taken away from it.

## Several lines: variables, IF, UNLESS, GAP

A line `EACH_OF x IN <set>` on its own names the item for the whole request. It is how two
lines come to be about the same person:

```skedge
# Nobody who worked the night block yesterday works clinic 1 today.
EACH_OF s IN staff.all
IF s NOT FREE DURING blocks.night ON {dates.target - 1d}
REQUEST s FREE DURING blocks.clinic_1
```

`IF <pattern>` makes the request apply only when the pattern has a match (or meets an
amount: `IF AT_LEAST 3 s DO …`). `UNLESS` is the opposite. Published past days are
facts, so an `IF` about yesterday is simply true or false.

Conditions join with `AND` (every one holds) and `OR` (at least one does), and a long one
reads best a test to a line:

```skedge
# If two counselors are on break at once and Dylan is free at lunch, he covers the desk.
IF
AT_LEAST 2 staff.counselor DO 'break' DURING EACH_OF blocks.all
AND
staff.dylan FREE DURING blocks.lunch
REQUEST staff.dylan DO 'front desk' DURING blocks.lunch
```

Mixing the two needs parentheses, the way mixing set operators does, so there is no
precedence to remember: `IF (a AND b) OR c`. `AND` and `OR` are keywords like any other,
so a line beginning with either continues the condition above it.

```skedge
# Someone from the office covers the front desk in clinic 1, unless a director is free then.
UNLESS staff.director FREE DURING blocks.clinic_1
REQUEST ANY 1 staff.office DO 'front desk' DURING blocks.clinic_1
```

`ANY 1 x IN <set>` on its own line picks one item for the whole request: "the same
person sets up and tears down".

A name bound this way can also be **added into a set** with `+`, which is how you say
"Alesa and one of these two":

```skedge
ANY 1 videographer IN {staff.dylan + staff.cam_vl}

REQUEST ALL_OF {staff.alesa + videographer}
DO 'Video KM Rope Swing'
DURING ANY 1 blocks.all FOR 30m
ON ANY 1 dates.session.one.all
```

Alesa is named outright, so she is always in it; `videographer` brings whichever of Dylan
and Cam the solver picked, and it is the same one everywhere the name appears in the
request. Only `+` works: `-` and `&` ask what a chosen name is *not*, or what it has in
common with something, and neither can be answered before the solver has chosen. A set
holding a bound name is taken with `ALL_OF`, or with nothing at all, for the same reason —
`ANY 2 {staff.alesa + videographer}` would be choosing out of something that is
itself still being chosen.

The same request with the choice written in place is
`ALL_OF {staff.alesa + (ANY 1 {staff.dylan + staff.cam_vl})}` (see
[choosing inside a set](#choosing-inside-a-set)). The binding line is the one to reach for
when the name is used in more than one place.

### Naming a set

`name: <set>` gives a set a name for the rest of the request, so a long set is written
once and reads as what it is:

```skedge
office_elves: {staff.lucy + staff.tom}

REQUEST EACH_OF {staff.director + office_elves}
DO 'DYOW'
DURING EACH_OF {blocks.all_clinics - blocks.clinic_1}
```

The name stands for the set wherever it is used, before or after the definition, and one
definition may use another. It is only shorthand: nothing is chosen by naming a set, and a
group inside one chooses afresh wherever the name is used. A name can't be both a set and
a variable or a label.

With a quantifier after the colon, it is a binding line written the other way round:
`videographer: ANY 1 {staff.dylan + staff.cam_vl}` is the same as
`ANY 1 videographer IN {staff.dylan + staff.cam_vl}`, and `c: EACH_OF staff.counselor` the
same as `EACH_OF c IN staff.counselor`.

Label two requirements and put a `GAP` between them:

```skedge
EACH_OF c IN staff.counselor
morning:   REQUEST c DO 'counselor hour' FOR 1h DURING ANY 1 {blocks.clinic_1 + blocks.clinic_2}
afternoon: REQUEST c DO 'counselor hour' FOR 1h DURING ANY 1 {blocks.playstation + blocks.clinic_3}
GAP morning TO afternoon AT_MOST 5h
```

`GAP a TO b` means `b` starts after `a` ends, and the time between meets the amount.
`GAP a TO b AT_LEAST 0m` is plain ordering. Real start and end times are compared, so a
one-hour task may slide around inside its 75-minute block to make a gap work.

Durations are written in minutes, hours or days: `30m`, `1.5h`, `2d`. A gap can reach
across days, which is what the longer units are for:

```skedge
first_meeting:  REQUEST ALL_OF {staff.dylan + staff.sarah} DO 'meeting'
DURING ANY 1 blocks.all ON ANY 1 {2026-09-14 .. 2026-09-16}
second_meeting: REQUEST ALL_OF {staff.dylan + staff.sarah} DO 'meeting'
DURING ANY 1 blocks.all ON ANY 1 {2026-09-16 .. 2026-09-18}
GAP first_meeting TO second_meeting AT_LEAST 40h
```

One day is scheduled at a time, so what this does day by day is: while both meetings are
still ahead, neither is forced and the solver may put the first one in. Once the first has
been published, the day it went on is what the gap is measured from — the second cannot go
anywhere nearer to it than forty hours, so it waits for a day that is far enough away. A
date later than the one being scheduled holds nothing yet, so it is never the near end of a
gap; it is checked on the day it turns into.

### Clauses in any order

`DURING`, `ON`, `AS_ROLE`, `FOR`, `WITH` and `WITHOUT` can go anywhere in a statement: before
the subject, between it and `DO`, or after the object. Only the subject, `DO` and the
object keep their order. These are the same request:

```skedge
REQUEST
ON ANY 1 {2026-09-14 .. 2026-09-18}
ALL_OF {staff.dylan + staff.alesa}
DO 'video'
FOR 30m
DURING ANY 1 blocks.all
```

```
REQUEST ALL_OF {staff.dylan + staff.alesa} DO 'video' FOR 30m DURING ANY 1 blocks.all ON ANY 1 {2026-09-14 .. 2026-09-18}
```

The same goes for patterns, and for `MAXIMIZE` or `MINIMIZE` in a `PREFER`. A clause
written before an amount, `REQUEST DURING blocks.lunch AT_MOST 2 staff.all DO 'break'`, is
part of the pattern the amount counts.

### A statement over several lines

A statement can be written on as many lines as it reads well on. A new line starts a new
statement only where one can: at `REQUEST`, `PREFER`, `EXCLUDE`, `IF`, `UNLESS` or `GAP`,
at a binding line (`EACH_OF x IN …`, `ANY n x IN …`), or at a name followed by a colon (a
label or a definition). Every other line carries on the one above it. Nothing needs
indenting, and where a statement fits on one line it can stay there.

So a line inside a statement can't start with `EACH_OF x IN` or `ANY n x IN`, which would
be read as a binding line: put it at the end of the line above instead.

### One request, several statements

A request holds as many `REQUEST` and `PREFER` statements as the thing being asked for
needs. Plain English often does not fit in one statement — "everyone gets a break, and we
would rather they were not all at once" is two — and writing them as one request keeps
them under one description, one priority and one weight, and lets them share a binding, an
`IF` and a `GAP`.

```skedge
# Rob runs the pole course this morning, and we would rather he were free at playstation.
REQUEST staff.rob DO activities.clinics.pole_course_explore_level_1_2_dbl AS_ROLE roles.first DURING ALL_OF {blocks.clinic_1 + blocks.clinic_2}
PREFER AT_LEAST 1 staff.rob FREE DURING blocks.playstation
```

The `REQUEST` statements stand or fall together: the request is met when every one of them
is, and that is what the report names. Each `PREFER` is weighed on its own in the request's
tier, met or not, whether or not the requirements are.

Two things to keep in mind. A binding expands the **whole** request, so `EACH_OF s IN
staff.all` beside a `REQUEST` makes that requirement once per person, which is usually
what is wanted but is worth seeing. And a `PREFER` still cannot sit in a `MUST_HAPPEN`
request, together with requirements or alone: there is no tier above the hard one to weigh
it in, so put the preference at a soft priority, in a request of its own if the
requirements must be hard.

## What makes things happen

**Only a positive `REQUEST` makes things happen.** A clinic runs, a trainee shadows, or an
ad hoc task exists only because some `REQUEST` asks for it. `NOT`, `AT_MOST`, `PREFER`,
`IF` and `UNLESS` steer where those things land; they never create more of them. So a
request that people `NOT DO 'break'` outside meals moves the breaks they already have and
cannot buy or cost anyone a break. It also means that naming an ad hoc task no `REQUEST`
asks for is an error, which catches misspelled task names.

## Priorities

`MUST_HAPPEN` is hard. `CLINIC`, `HIGH`, `MEDIUM` and `LOW` are soft tiers, and no amount
of a lower tier outweighs a higher one; within a tier, weights set the exchange rate. See
[How the solver decides](solver.md). A `PREFER` cannot be `MUST_HAPPEN`, in a request of
its own or beside requirements; a cap that must hold is `REQUEST AT_MOST`.

## EXCLUDE: somebody who is not here

A day off, a training course, a dentist's appointment. `EXCLUDE` says that somebody is not
at camp for some of a day, which is not a thing to ask for — it is what the day is like:

```skedge
EXCLUDE staff.dylan DO 'offsite' DURING ALL_OF blocks.all ON 2026-09-16
```

Dylan holds nothing in those blocks, no clinic can use him and no request reaches him
there, and the published schedule says `offsite` where his assignments would have been —
on the Staff View in each of his cells, and on the Clinic View in a row of its own beside
the clinics. The quoted word is that label, so write whatever the schedule should say.

| Part | Means |
|---|---|
| `EXCLUDE <who>` | the people who are away: a name, `ALL_OF` a set, or `EACH_OF` one |
| `DO '<label>'` | what the schedule says where they would have been |
| `DURING <blocks>` | the blocks they are away for; left out, every block of the day |
| `ON <dates>` | the dates; left out, the date being scheduled |

**The rules that must happen still must.** A day's legal requirements are written about
the staff who are here — `REQUEST EACH_OF staff.all DO 'break' …` — and somebody out for a
whole day is in no category that day, so nothing is asked of them and the day still solves.
Somebody out for part of a day is still at camp and is still owed their breaks; they are
simply taken in a block they are around for.

An `EXCLUDE` is a fact, so nothing in it is the solver's to choose: `ANY n` is refused,
it takes no `IF`, and it is written at `MUST_HAPPEN` in a request of its own. Naming that
person anyway in another request — `REQUEST staff.dylan DO activities.clinics.riflery` on
his day off — is a contradiction the errors pane names: at `MUST_HAPPEN` the day will not
solve, and below it the work simply never happens.

The Adjustments sheet does the same thing for somebody who is [ill or short of
sleep](same-day.md); `EXCLUDE` is for what is known in advance and belongs with the
requests.

## Time horizon

The solver schedules the target date. Published past dates are facts: they cannot change,
and they count in every requirement, amount and condition. Future dates hold nothing yet.

A request that could still be met later, such as one `ON ANY 1` a week of dates, is
**deferrable**. It does not have to happen today as long as it can still happen later,
with a small nudge to do it early. The solver knows from the sheets when "later" runs out,
for example because the person rests for the remainder of the week, and enforces it on the
last day that can still hold it. `NOT`, `AT_MOST` and `ALL_OF` dates are enforced every
day.

## Examples

Names below are those of the sample data in `tests/fixtures`; the test suite validates
every example on this page against it.

### Clinic assignment

Archery runs during clinic 2. **Load offerings** creates a request like this for every
offered clinic, at `CLINIC` priority, tagged `generated`, naming every position on
Clinic_Data. `EACH_OF` over the roles is what asks for a different person in each;
`ALL_OF` would ask one person to hold both. The clinic runs fully staffed or not at all,
so the positions stand together whichever way they are written.

```skedge
REQUEST ANY 1 staff.all DO activities.clinics.archery_1_2 AS_ROLE EACH_OF {roles.first + roles.second} DURING blocks.clinic_2 ON 2026-09-16
```

Priority `CLINIC`.

### Pinning a staff member to a position

```skedge
REQUEST staff.rob DO activities.clinics.gravity_zip_line AS_ROLE roles.first DURING blocks.clinic_2 ON 2026-09-16
```

Priority `MUST_HAPPEN`.

### Lucy and Tom take out the garbage together every Monday

```skedge
REQUEST ALL_OF {staff.lucy + staff.tom} DO 'take out garbage' DURING ANY 1 blocks.all ON EACH_OF dates.session.one.mondays
```

Priority `HIGH`.

### Lucy or Tom takes out the garbage on the first Monday of every session

```skedge
REQUEST ANY 1 {staff.lucy + staff.tom} DO 'take out garbage' DURING ANY 1 blocks.all ON EACH_OF dates.season.mondays
```

Priority `HIGH`.

### Two of three people, twice in a day

The same two people, in the same two blocks.

```skedge
REQUEST ANY 2 {staff.lucy + staff.tom + staff.charles} DO 'take out garbage' DURING ANY 2 blocks.all ON 2026-09-21
```

Priority `MEDIUM`.

### Each of three people, some day this week, during playstation

Three separate requests, and each person may get a different day.

```skedge
REQUEST EACH_OF {staff.lucy + staff.tom + staff.charles} DO 'take out garbage' DURING blocks.playstation ON ANY 1 {2026-09-21 .. 2026-09-25}
```

Priority `MEDIUM`.

### Both clinics if possible, some day in session two

One day is chosen; clinic 1 and clinic 2 on it are separate requests.

```skedge
ANY 1 d IN dates.session.two.all
REQUEST staff.dylan DO 'archery maintenance' DURING EACH_OF {blocks.clinic_1 + blocks.clinic_2} ON d
```

Priority `LOW`.

### Training

Cam VL is trained on candle making for two clinics in a row, some day this week.
`roles.trainee` resolves to shadow or scaffolded from the Skills sheet, and the trainee is
additional to the clinic's positions.

```skedge
REQUEST staff.cam_vl DO activities.clinics.candle_making AS_ROLE roles.trainee DURING ANY 2 blocks.all_clinics CONSECUTIVE ON ANY 1 {2026-09-14 .. 2026-09-18}
```

Priority `HIGH`.

### Keeping someone off an activity

```skedge
REQUEST staff.dylan NOT DO activities.clinics.ropes ON {2026-09-14 .. 2026-09-16}
```

Priority `MUST_HAPPEN`.

### Staff run clinics they prefer

```skedge
PREFER EACH_OF s IN staff.all DO EACH_OF c IN activities.clinics.all MAXIMIZE mappings.preference(s, c)
```

Priority `MEDIUM`, weight `1`.

### Clinic variety over a rolling week

Each person should run each clinic at most once in any seven days; every repeat costs a
point. Shares a tier with the preference request so the two trade off.

```skedge
PREFER AT_MOST 1 EACH_OF staff.all DO EACH_OF activities.clinics.all ON {(dates.target - 6d) .. dates.target}
```

Priority `MEDIUM`, weight `0.5`.

### Rotate ropes positions

```skedge
PREFER AT_MOST 3 EACH_OF staff.ropes_level_2 DO activities.clinics.ropes AS_ROLE EACH_OF {roles.first + roles.second} ON dates.session.one.all
```

Priority `LOW`.

### Balance clinic workload

```skedge
PREFER AT_MOST 8 EACH_OF staff.all DO activities.clinics.all ON dates.session.one.all
```

Priority `MEDIUM`, weight `0.25`.

### Never more than three clinics in a row

```skedge
REQUEST AT_MOST 3 CONSECUTIVE EACH_OF staff.all DO activities.clinics.all
```

Priority `MUST_HAPPEN`.

### Counselor hours with a maximum gap

Each counselor gets a one-hour counselor hour during clinic 1 or 2 and another during
playstation or clinic 3, no more than five hours apart. `ON` is left out, so this applies
every day.

```skedge
EACH_OF c IN staff.counselor
morning:   REQUEST c DO 'counselor hour' FOR 1h DURING ANY 1 {blocks.clinic_1 + blocks.clinic_2}
afternoon: REQUEST c DO 'counselor hour' FOR 1h DURING ANY 1 {blocks.playstation + blocks.clinic_3}
GAP morning TO afternoon AT_MOST 5h
```

Priority `MUST_HAPPEN`.

### Non-counselor breaks

Each non-director, non-counselor staff member takes three 30-minute breaks per day, in
three different blocks. A break in a clinic block keeps that person off clinics in it.

```skedge
REQUEST EACH_OF {staff.all - staff.director - staff.counselor} DO 'break' FOR 30m DURING ANY 3 blocks.all
```

Priority `MUST_HAPPEN`.

### Breaks at meal times

Where those breaks land: one small request per person per non-meal block.

```skedge
REQUEST EACH_OF {staff.all - staff.director - staff.counselor} NOT DO 'break' DURING EACH_OF {blocks.all - blocks.meals}
```

Priority `HIGH`, weight `2`.

### Never more than two people on break at once

```skedge
REQUEST AT_MOST 2 staff.all DO 'break' DURING EACH_OF blocks.all
```

Priority `MUST_HAPPEN`.

### Playstation availability

As many non-directors as possible are free during the playstation block. Each free person
is one met request; the staff view marks them `Available`.

```skedge
REQUEST EACH_OF {staff.all - staff.director} FREE DURING blocks.playstation
```

Priority `HIGH`.

### Day off

```skedge
EXCLUDE staff.dylan DO 'day off' ON 2026-09-16
```

Priority `MUST_HAPPEN`.

### A review with every director, on the second Thursday

```skedge
REQUEST ALL_OF staff.director DO 'mid-session review' DURING ANY 1 blocks.all ON dates.session.one.week.two.thursday
```

Priority `MEDIUM`.

### Keeping two staff off the same clinic

One request per block, so each shared clinic costs a point. At `MUST_HAPPEN` it would rule
the pairing out, at the price of leaving a clinic unstaffed when they are the only two
available.

```skedge
REQUEST staff.jack NOT DO activities.clinics.all WITH staff.lucy DURING EACH_OF blocks.all
```

Priority `HIGH`, weight `2`.

### If Rob is on ropes, Vic must be too

```skedge
REQUEST staff.rob NOT DO activities.clinics.ropes WITHOUT staff.vic
```

Priority `MUST_HAPPEN`.

### After three clinics in a row, a free block

```skedge
EACH_OF s IN staff.all
IF AT_LEAST 3 CONSECUTIVE s DO activities.clinics.all
REQUEST s FREE DURING ANY 1 blocks.all
```

Priority `HIGH`.

### The same person sets up and tears down

```skedge
ANY 1 p IN staff.counselor
first: REQUEST p DO 'campfire setup' DURING blocks.clinic_4
last:  REQUEST p DO 'campfire teardown' DURING blocks.evening
GAP first TO last AT_LEAST 0m
```

Priority `MEDIUM`.

## Grammar

The grammar the parser uses is in the [specification](spec.md#4-grammar), and in
`puppet_strings/skedge/grammar.lark`.
