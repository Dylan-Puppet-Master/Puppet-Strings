# Skedge reference

Skedge is the language requests are written in. A request reads as a sentence with a subject, a verb and an object:

```skedge
REQUEST staff.dylan DO 'archery maintenance' DURING ANY blocks.all ON ANY {2026-09-14 .. 2026-09-18}
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
| `PREFER` | A soft constraint that can be partly met: how close the day comes to a count or a length. |

Each says what happens, in one of three forms:

| Form | Meaning |
|---|---|
| `<who> DO <what> DURING <blocks> ON <dates>` | These people do this, then. |
| `<who> FREE …` | They have nothing to do. |
| `<who> BUSY …` | They have something to do, whatever it is. |
| `<what> DURING <blocks> ON <dates>` | This activity happens, then. It names nobody, because the activity already says who may run it. |

Every set of names says out loud how it is meant:

| Quantifier | Meaning |
|---|---|
| `ALL {staff.lucy + staff.tom}` | Both of them, together, all or nothing. |
| `ANY {staff.lucy + staff.tom}` | Either of them: any of these will do. |
| `AT_LEAST 1 {staff.lucy + staff.tom}` | A **count**: at least one of them. `AT_MOST` and `EXACTLY` count the same way. |
| `EACH {staff.lucy + staff.tom}` | A separate request for each of them, each met or not on its own. |

A number is always a count, and it goes directly in front of the set it counts. A length
goes on `FOR`. A single thing (`staff.rob`, `blocks.clinic_1`, `2026-09-21`) needs no
quantifier, and takes none. A missing `ON` means the day being scheduled, and a missing
`DURING` any block of it.

`NOT DO` forbids, `WITH` / `WITHOUT` say who is alongside, `IF` / `UNLESS` make a request
conditional (`AND` / `OR` join conditions), `GAP` puts time between two requirements, and
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
(`blocks.all`, `dates.session_1.mondays`). There is no `blocks.any`: "any block" is
`ANY blocks.all`, and "two blocks" is `AT_LEAST 2 blocks.all`, so how a set is taken is
always visible.

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
| A session | `dates.session_4.all` | Every date of session 4. |
| Anything else | `dates.family_camp.all` | Every date of that row. |
| A week of a span | `dates.session_4.week_2.all` | Every date of its second week. |

Main season rows are numbered in sheet order and named by number — `session_1`,
`session_2` … — and so are weeks: `week_1`, `week_2` …. Any other row is named after
its `name` column, so a row called Family Camp is `dates.family_camp`. Every step of a date
name is a span, a week or a date; nothing in the tree is only there to hold the rest.

**Only the names with `target` in them follow the date on the toolbar.** `dates.target` is
that date, `dates.session_target` is the session it falls in, and
`dates.session_target.week_target` is the week of that session it falls in. They carry the
same names as any other session and week, so `dates.session_target.mondays` is every Monday
of the session being scheduled. Every other date name says outright which span it means, and
reads the same whenever you open it.

A date outside the main season, such as a day of Family Camp, is in no session, so on that
date `dates.session_target` names nothing. A request that uses it is shown as invalid and
is left out of that day's solve; it can still be saved, and it applies again on the next
date that is in a session.

Every span carries these:

| Name | Holds |
|---|---|
| `dates.session_4.all` | Every date in it. |
| `dates.session_4.first`, `.last` | Its first and last date. |
| `dates.session_4.mondays` … `.sundays` | Every Monday of it. |

A week is short enough to reach each weekday once, so inside a week the weekday is a
single date:

| Name | Holds |
|---|---|
| `dates.session_4.week_2.monday` | One date: that week's Monday. |
| `dates.session_4.week_2.first`, `.last` | That week's first and last date. |

And `dates.target` is the date being scheduled, which is the date every request is about
unless it says `ON` something else.

```skedge
REQUEST ALL staff.director DO 'session opening' DURING AT_LEAST 1 blocks.all ON dates.session_2.first
```

**There is no `first_monday` or `last_friday`.** A week's weekday says the same thing and
says it once: the second Thursday of a session is `dates.session_1.week_2.thursday`.

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

A quantifier can also go inside a set, on a part of it. That part is a **group**, taken
`ALL`, `AT_LEAST n` or `EXACTLY n`, with parentheses around it if they help. In a set taken
whole, `AT_LEAST 1 {…}` adds whichever one the solver picks — "Alesa and one of these two",
the other free to join in — and `EXACTLY 1 {…}` adds one and keeps the other out of it:

```skedge
REQUEST ALL {staff.alesa + EXACTLY 1 {staff.dylan + staff.cam_vl}}
DO 'Video KM Rope Swing' FOR EXACTLY 30m
DURING AT_LEAST 1 blocks.all
```

In a count, each group counts as one of the things counted, all of it, so `(ALL …)` keeps
people together — "Lucy, or else Tom and Charles together":

```skedge
REQUEST AT_LEAST 1 {staff.lucy + (ALL {staff.tom + staff.charles})} DO 'take out garbage' DURING AT_LEAST 1 blocks.all
```

In `EACH`, each group is one of the separate requests: `EACH {staff.lucy +
(ALL {staff.tom + staff.charles})}` is one request for Lucy and one for Tom and Charles
together.

A group is added with `+`. `(ALL s)` may be taken away or crossed like `s`, but
`(AT_LEAST n s)` may not: what it holds is not known until the solver has chosen.

## Saying what happens: `<who> DO <what>`

```skedge
REQUEST ALL {staff.lucy + staff.tom} DO 'take out garbage' DURING AT_LEAST 1 blocks.all ON EACH dates.session_1.mondays
```

Read it in three steps, always in this order:

1. **`EACH` splits.** There is one separate request per Monday.
2. **`ALL` makes one unit.** Lucy and Tom are taken together, as one.
3. **A count counts what the unit does.** At least one block in which Lucy and Tom both
   take out the garbage, so they do it together.

`EACH` in its place would give each of them a request of their own, and so a block of
their own.

The difference between the quantifiers, on one example:

| Request | Meaning |
|---|---|
| `REQUEST staff.rob DO activities.clinics.ropes_course AS_ROLE roles.first DURING ALL {blocks.clinic_1 + blocks.clinic_2} ON 2026-09-28` | Rob is first on ropes in both clinics. One request: both or it is not met. |
| `… DURING ANY {blocks.clinic_1 + blocks.clinic_2} …` | Rob is first on ropes in clinic 1 or clinic 2, or both. One request. |
| `… DURING EXACTLY 1 {blocks.clinic_1 + blocks.clinic_2} …` | In one of them, and not the other. |
| `… DURING EACH {blocks.clinic_1 + blocks.clinic_2} …` | Two requests, one per clinic. Rob may end up with neither, one or both, and each counts on its own. |

At `MUST_HAPPEN`, `ALL` and `EACH` come to the same schedule. They differ when the
request is soft: `ALL` earns nothing for half, `EACH` earns half.

| Clause | Meaning |
|---|---|
| `DURING <blocks>` | When in the day. Left out: any block of the day. |
| `ON <dates>` | Which dates. Left out: the day being scheduled. |
| `AS_ROLE <role>` | In that position or trainee role. Left out: any position. |
| `FOR <bound> <duration>` | How long ([lengths](#lengths-for)): `FOR EXACTLY 30m`, `FOR AT_LEAST 2h`. Left out, a task fills its block. |
| `WITH <staff>` | That person is working the same clinic or task alongside; of a set, a count or `ALL` says how many of it. |
| `WITHOUT <staff>` | The opposite of `WITH` the same. |

`DURING` and `ON` go anywhere in a statement, even before the subject. `AS_ROLE`, `FOR`,
`WITH` and `WITHOUT` describe the activity, so they go after `DO`, `FREE` or `BUSY`:

```skedge
REQUEST DURING blocks.clinic_1 staff.rob DO 'break' FOR EXACTLY 30m ON 2026-09-16
```

An ad hoc task such as `'break'` has no positions, skills or camper slots; it occupies
staff time only. `'break' FOR EXACTLY 30m` is a 30-minute break somewhere inside one block, the
Staff View labels the rest of the block `DYOW/WPs`, and several short tasks can share a
block.

### Counting

A count is `AT_LEAST`, `AT_MOST` or `EXACTLY` and a number, written directly in front of
the set it counts. It counts the members of that set the rest of the statement holds for:

| Request | Meaning |
|---|---|
| `REQUEST AT_LEAST 3 staff.support DO 'lifeguard' DURING blocks.rest_hour` | Three or more support staff lifeguard at rest hour. |
| `REQUEST AT_MOST 2 staff.all DO 'break' DURING EACH blocks.all` | Never more than two people on break in the same block. |
| `REQUEST EACH staff.village_hero DO 'break' DURING EXACTLY 3 blocks.all` | Every village hero has a break in exactly three blocks. |
| `REQUEST staff.rob DO AT_LEAST 2 activities.clinics.all ON ANY dates.session_1.all` | Rob runs at least two different clinics this session. |

A count counts its own set and nothing else. `EXACTLY 1 {staff.dylan + staff.alesa} DO
'rake leaves'` is one of those two raking and the other one not; it says nothing about who
else rakes. `AT_LEAST` never forbids, but `AT_MOST` and `EXACTLY` do, which is what makes
them caps.

An activity has no quantity of its own: it is the blocks, the dates and the people that
come in numbers. So a count of activities counts different ones, and "three breaks" is a
count of the blocks they are in.

Where two sets are counted, the counts go one inside the other in this order, whatever
order they are written in: who, what, the dates, the blocks. `AT_MOST 2 staff.counselor DO
'break' DURING AT_LEAST 3 blocks.all` is at most two counselors who break three or more
times. `ALL` is one unit inside every count, which is what put Lucy and Tom in the same
block above.

#### Blocks across days

A block happens every day, so clinic 1 on Monday and clinic 1 on Tuesday are two blocks.
Where the dates are pooled with `ANY`, a count of blocks counts every block on every one
of those dates, which is how a number of times over a week or a session is written:

```skedge
REQUEST staff.dylan DO ANY activities.clinics.all AS_ROLE roles.first DURING AT_MOST 8 blocks.all_clinics ON ANY dates.session_1.all
```

Dylan facilitates at most eight clinics in the session, however they fall across its days.
How the dates are taken decides what a count of blocks is over:

| Written | A count of blocks is over |
|---|---|
| `ON ANY dates.session_1.all` | every block of every day together: `EXACTLY 1` is once in the whole session |
| `ON EACH dates.session_1.all` | each day on its own, as a separate request: `EXACTLY 1` is once a day, in any block |
| `ON ALL dates.session_1.all` | the days as one unit: a block counts when it happens on every one of them, so `EXACTLY 1` is the same block every day |

Blocks in a row stay within a day: the last block of one day and the first of the next are
not next to each other.

`ANY` is the other way to take a set: any of these will do. It is not a number, so it
says nothing about how many:

```skedge
REQUEST EACH staff.all DO ANY activities.clinics.all DURING AT_MOST 1 CONSECUTIVE blocks.all
```

This counts the blocks, and the clinics only say which blocks those are: blocks in which
they run a clinic, any clinic. `AT_LEAST 1` on the clinics would be a second count asking
something else — whether there is a clinic whose own runs are short — which any clinic
they never run passes. A count asks how many; `ANY` says what counts.

On the blocks of a statement, `ANY` is at least one of them, so it is nearly `AT_LEAST 1`.
The difference is where a pool sits: inside the units, where a count sits outside them.
`ALL {staff.dylan + staff.sarah} DO 'x' DURING ANY blocks.all` gives each of them a block,
not necessarily the same one; `DURING AT_LEAST 1 blocks.all` gives them one together.

### Blocks in a row

`CONSECUTIVE` after a count on the blocks counts blocks that are next to each other:

```skedge
REQUEST ALL {staff.lucy + staff.tom} DO 'take out garbage' DURING AT_LEAST 2 CONSECUTIVE blocks.all
```

Lucy and Tom take out the garbage together, in two blocks one after the other. Blocks are
next to each other when they are next to each other in the Blocks sheet, so
`AT_LEAST 2 CONSECUTIVE blocks.all_clinics` may be clinic 1 and 2, but not clinic 2 and 3
with lunch between them. `AT_MOST` caps the longest run:

```skedge
REQUEST EACH staff.all DO 'break' DURING AT_MOST 1 CONSECUTIVE blocks.all
```

Nobody has a break in two blocks in a row.

`CONSECUTIVE` is always about blocks, since blocks are what can be in a row, so it only
ever goes in a `DURING`, just before the blocks. After `ANY` it pools each run of blocks
for a `FOR` to measure, below.

### Lengths: `FOR`

`FOR` says how long, and measures the activity within one unit of the blocks. Blocks taken
one at a time — one block, `ALL`, `EACH` or a count — make each block a unit, so `FOR` is
the length of each piece. Blocks pooled with `ANY` are one unit together, so `FOR` is what
the pieces add up to:

| You mean | Write |
|---|---|
| Two hours in total, split over any blocks | `REQUEST staff.cam_vl DO 'video editing' FOR AT_LEAST 2h DURING ANY blocks.all` |
| Two hours in one go: one block, or blocks in a row | `REQUEST staff.cam_vl DO 'video editing' FOR AT_LEAST 2h DURING ANY CONSECUTIVE blocks.all` |
| One piece of 45 minutes, in one block | `REQUEST staff.cam_vl DO 'video editing' FOR EXACTLY 45m DURING AT_LEAST 1 blocks.all` |
| Three breaks of 30 minutes | `REQUEST staff.cam_vl DO 'break' FOR EXACTLY 30m DURING EXACTLY 3 blocks.all` |

`FOR` always says how the length is bounded, as a count does: `FOR EXACTLY 2h`,
`FOR AT_LEAST 2h` or `FOR AT_MOST 2h`, never a bare `FOR 2h`. A piece
never leaves its block, so one block shorter than the length cannot hold it. Over a pool
the pieces fill their blocks, all but one, which is cut to what is left, or under
`AT_LEAST` to whatever reaches it: two hours over 75-minute blocks is one whole block and
45 minutes of another.

`FOR` on a clinic, `FREE` or `BUSY` adds up the blocks, so it needs the blocks pooled:

```skedge
PREFER EACH staff.counselor FREE FOR AT_LEAST 2h DURING ANY blocks.all_clinics
```

### Asking for an activity without naming anybody

An activity already records who may run it: each of its positions needs a skill, and a
cabin act's positions may name a person or a category outright. So a request for an
activity names only the activity:

```skedge
REQUEST activities.clinics.archery_1_2 DURING blocks.clinic_2
```

That asks that archery runs in clinic 2, staffed by whoever its positions allow. There is
no `DO`, because there is no subject: adding `AT_LEAST 1 staff.all DO` in front would say
the same thing twice. Filling one position of an activity fills them all, so this is a
request for every person it needs, and the report names the activity once rather than once
per position.

`EACH` over a set asks for each of them separately, which is how two lines ask for a
whole board of cabin acts: one for the acts in the cabin act block, one for those the
board moved to rest hour:

```skedge
REQUEST EACH activities.cabin_acts.at_cabin_act DURING blocks.cabin_act
REQUEST EACH activities.cabin_acts.at_rest_hour DURING blocks.rest_hour
```

To narrow who may run something beyond what the activity says, say so in a second
statement rather than in this one:

```skedge
REQUEST activities.clinics.candle_making DURING blocks.clinic_1
REQUEST EACH staff.counselor NOT DO activities.clinics.candle_making
```

### NOT DO, FREE and BUSY

| Request | Meaning |
|---|---|
| `REQUEST staff.dylan NOT DO ANY activities.clinics.ropes` | Dylan does no ropes clinic today. |
| `REQUEST staff.dylan FREE DURING ALL blocks.all ON 2026-09-16` | At camp with nothing assigned all day. Somebody away is an [`EXCLUDE`](#exclude-somebody-who-is-not-here). |
| `REQUEST EACH {staff.all - staff.director} FREE DURING blocks.playstation` | Each non-director should have nothing on during playstation. |
| `REQUEST EACH staff.counselor BUSY DURING blocks.clinic_1` | Every counselor has something to do in clinic 1. |
| `REQUEST staff.hails BUSY DURING AT_LEAST 1 blocks.evening` | Something to do in at least one evening block. |

`FREE` means working that day with nothing assigned in the block; `BUSY` means having
something assigned. Someone resting is neither. There is no word for "anything": nothing to
do is `FREE`, something to do is `BUSY`.

The subject of a `NOT` is who it is about: `ALL {…} NOT DO` is "none of them does",
`AT_LEAST 1 {…} NOT DO` is "one of them doesn't". Everything to the right of `NOT`
describes the situation that must not happen, so a set there is matched rather than
counted, and says so with `ANY`: `REQUEST staff.rob NOT DO 'break' DURING ANY blocks.meals`
is no break at any meal. `DURING` can be left out to mean all day. `EACH` splits the
request, as it does anywhere; `WITH` and `WITHOUT` count company instead (below).

`NOT` turns round everything to its right, so `ALL` there is "not all of these
together", and any one of them on its own is fine:

| Request | Meaning |
|---|---|
| `REQUEST staff.lisa NOT DO ANY activities.clinics.all DURING ANY {blocks.clinic_1 + blocks.clinic_2}` | Lisa is on no clinic in either block. One request: a clinic in either block breaks it. |
| `REQUEST staff.lisa NOT DO ANY activities.clinics.all DURING EACH {blocks.clinic_1 + blocks.clinic_2}` | The same rule, as two requests, one per block: at a soft priority a clinic in both is twice as bad as one. |
| `REQUEST staff.lisa NOT DO ANY activities.clinics.all DURING ALL {blocks.clinic_1 + blocks.clinic_2}` | Lisa is not on a clinic in both blocks. A clinic in one of them is fine. |

A count is rejected right of `NOT`: "not in two of them" is "in at most one", which a count
of what does happen says plainly — `REQUEST staff.lisa DO ANY activities.clinics.all
DURING AT_MOST 1 {…}`.

**This is how "avoid" is written.** A `REQUEST` is all or nothing, so split it small and
give it a soft priority:

```skedge
REQUEST EACH staff.office NOT DO 'break' DURING EACH {blocks.breakfast + blocks.lunch} ON EACH dates.season.fridays
```

That is one small request per person, per meal, per Friday. Each break at a meal fails
exactly one of them, so three such breaks are three times as bad as one.

### WITH and WITHOUT

| Request | Meaning |
|---|---|
| `REQUEST staff.rob NOT DO ANY activities.clinics.ropes WITHOUT staff.vic` | If Rob is on ropes, Vic must be on it too. |
| `REQUEST EACH staff.junior NOT DO ANY activities.clinics.waterfront WITHOUT AT_LEAST 1 staff.senior` | No junior at the waterfront unless a senior is there. |
| `REQUEST staff.rob NOT DO ANY activities.clinics.ropes WITHOUT ALL {staff.vic + staff.charlton}` | Rob is on ropes only with both Vic and Charlton. |
| `REQUEST staff.jack NOT DO ANY activities.clinics.all WITH staff.lucy` | Jack and Lucy never share a clinic. |
| `REQUEST staff.caroline DO activities.clinics.climbing_wall AS_ROLE roles.trainee WITH staff.alan AS_ROLE roles.first` | Caroline trains on the climbing wall, with Alan first on that same instance. |

An `AS_ROLE` straight after the people of a `WITH` or `WITHOUT` is their role, not the
subject's: above, `roles.first` is Alan's. The subject's own `AS_ROLE` goes before the
`WITH`, or anywhere else after `DO`.

One name stands alone. A set of several needs a count (`AT_LEAST 1`, `EXACTLY 2`, …) or
`ALL` (every one of them), even to the right of `NOT`: `WITHOUT staff.senior` would not
say whether one senior is enough.

"X only if Y is there too" is always "X `NOT DO` it `WITHOUT` Y". At `MUST_HAPPEN` these
are hard rules; at a soft priority they are wishes.

## PREFER: how close

A `PREFER` is scored by how far the day is from something, so it needs a count or a `FOR`
to be scored against:

| Request | Meaning |
|---|---|
| `PREFER EACH staff.all DO ANY activities.clinics.all DURING AT_MOST 8 blocks.all ON ANY dates.session_1.all` | Nobody should run more than 8 clinics a session. Ten is twice as bad as nine. |
| `PREFER staff.james DO 'dance practice' FOR AT_LEAST 2h DURING ANY blocks.all ON ANY {2026-09-16 .. 2026-09-17}` | Two hours of dance practice across the two days, each hour short costing the same. |
| `PREFER staff.dylan DO activities.clinics.riflery DURING AT_LEAST 1 blocks.clinic_2` | Dylan on riflery in clinic 2, if it can be managed. |

With several counts, a `PREFER` is scored on the outermost: `PREFER AT_LEAST 5
staff.counselor DO 'break' DURING AT_LEAST 2 blocks.all` scores the counselors who reach
two breaks, and one with a single break earns nothing. `EACH staff.counselor` in its place
scores each counselor on their own breaks.

`REQUEST` and `PREFER` take the same words. `REQUEST` is met or not, and can be
`MUST_HAPPEN`. `PREFER` is never hard and is scored by how far off it is.

### Mappings

A mapping is a table on the [Mappings tab](sheets.md#mappings-config-spreadsheet) that
takes one or more names and gives back either a number or another name. You call it with
one argument per key: `mappings.buddy(c)`. `EACH x IN <set>` gives each copy's item a
name, so a mapping can be told what to look up.

A **numeric** mapping is a table of ratings, and is what `MAXIMIZE` and `MINIMIZE` score
by:

```skedge
PREFER EACH s IN staff.all DO EACH c IN activities.clinics.all MAXIMIZE mappings.preference(s, c)
```

For each staff member `s` and clinic `c`, every assignment of `s` to `c` earns
`mappings.preference(s, c)`, normalized to 0–1. `MINIMIZE` makes it a cost instead. A pair
the mapping has no row for is worth that mapping's `default`.

Any other mapping gives a **name**, and a call to it goes anywhere a name can. Each cabin
has a buddy HERO who covers it at dinner, and `mappings.buddy` says who:

```skedge
# Every counselor's buddy covers their cabin at dinner.
EACH c IN staff.counselor
REQUEST mappings.buddy(c) DO 'cabin cover' DURING blocks.evening
```

A counselor whose cabin has no row gets the mapping's `default`, which is a phrase such as
`AT_LEAST 1 {staff.all - staff.counselor - staff.director}`: the call stands for that
phrase, count and all, so the solver picks one of them. So does a counselor whose buddy is
resting or away that day, since a buddy who isn't at work can't cover anyone.

The Mappings tab says what a mapping takes and gives, so a call is checked like any other
name. `mappings.buddy(staff.alan)` is an error if Alan isn't a counselor, and so is
`mappings.buddy(c)` written where an activity belongs. A call can also go inside a set,
`ALL {staff.office - mappings.buddy(c)}`, but only when it gives one name or an
`ALL` set. A default that is a count is a choice the solver hasn't made yet, so nothing
can be taken away from it.

## Several lines: variables, IF, UNLESS, GAP

A line `EACH x IN <set>` on its own names the item for the whole request. It is how two
lines come to be about the same person:

```skedge
# Nobody who worked the night block yesterday works clinic 1 today.
EACH s IN staff.all
IF s BUSY DURING blocks.night ON {dates.target - 1d}
REQUEST s FREE DURING blocks.clinic_1
```

`IF` makes the request apply only when its test holds: when what it says happens, or meets
its count. `UNLESS` is the opposite. Published past days are facts, so an `IF` about
yesterday is simply true or false.

Conditions join with `AND` (every one holds) and `OR` (at least one does), and a long one
reads best a test to a line:

```skedge
# If two counselors are on break at once and Dylan is free at lunch, he covers the desk.
IF
AT_LEAST 2 staff.counselor DO 'break' DURING ANY blocks.all
AND
staff.dylan FREE DURING blocks.lunch
REQUEST staff.dylan DO 'front desk' DURING blocks.lunch
```

Mixing the two needs parentheses, the way mixing set operators does, so there is no
precedence to remember: `IF (a AND b) OR c`. `AND` and `OR` are keywords like any other,
so a line beginning with either continues the condition above it.

```skedge
# Someone from the office covers the front desk in clinic 1, unless a director is free then.
UNLESS ANY staff.director FREE DURING blocks.clinic_1
REQUEST AT_LEAST 1 staff.office DO 'front desk' DURING blocks.clinic_1
```

`EXACTLY 1 x IN <set>` on its own line picks one item for the whole request: "the same
person sets up and tears down". `EXACTLY 3 x IN <set>` picks three, and `x` is then a set,
taken `ALL` or `EACH` where it is used.

A name bound this way can also be **added into a set** with `+`, which is how you say
"Alesa and one of these two":

```skedge
EXACTLY 1 videographer IN {staff.dylan + staff.cam_vl}

REQUEST ALL {staff.alesa + videographer}
DO 'Video KM Rope Swing' FOR EXACTLY 30m
DURING AT_LEAST 1 blocks.all
ON AT_LEAST 1 dates.session_1.all
```

Alesa is named outright, so she is always in it; `videographer` brings whichever of Dylan
and Cam the solver picked, and it is the same one everywhere the name appears in the
request. Only `+` works: `-` and `&` ask what a chosen name is *not*, or what it has in
common with something, and neither can be answered before the solver has chosen. A set
holding a bound name is taken with `ALL`, or with nothing at all, for the same reason —
`AT_LEAST 2 {staff.alesa + videographer}` would be counting out of something that is
itself still being chosen.

The same request with the choice written in place is
`ALL {staff.alesa + (AT_LEAST 1 {staff.dylan + staff.cam_vl})}` (see
[choosing inside a set](#choosing-inside-a-set)). The binding line is the one to reach for
when the name is used in more than one place.

### Naming a set

`name: <set>` gives a set a name for the rest of the request, so a long set is written
once and reads as what it is:

```skedge
office_elves: {staff.lucy + staff.tom}

REQUEST EACH {staff.director + office_elves}
DO 'DYOW'
DURING EACH {blocks.all_clinics - blocks.clinic_1}
```

The name stands for the set wherever it is used, before or after the definition, and one
definition may use another. It is only shorthand: nothing is chosen by naming a set, and a
group inside one chooses afresh wherever the name is used. A name can't be both a set and
a variable or a label.

A quoted task can be named the same way, and the name then goes after `DO`, so a long task
name is written once and the lines using it cannot drift apart:

```skedge
duty: 'front desk duty'
REQUEST AT_LEAST 1 staff.office DO duty DURING blocks.clinic_1
REQUEST AT_LEAST 1 staff.office DO duty DURING blocks.clinic_3
```

With a quantifier after the colon, it is a binding line written the other way round:
`videographer: EXACTLY 1 {staff.dylan + staff.cam_vl}` is the same as
`EXACTLY 1 videographer IN {staff.dylan + staff.cam_vl}`, and `c: EACH staff.counselor`
the same as `EACH c IN staff.counselor`.

Label two requirements and put a `GAP` between them:

```skedge
EACH c IN staff.counselor
morning:   REQUEST c DO 'counselor hour' FOR EXACTLY 1h DURING AT_LEAST 1 {blocks.clinic_1 + blocks.clinic_2}
afternoon: REQUEST c DO 'counselor hour' FOR EXACTLY 1h DURING AT_LEAST 1 {blocks.playstation + blocks.clinic_3}
GAP morning TO afternoon AT_MOST 5h
```

`GAP a TO b` means `b` starts after `a` ends, and the time between meets the amount, if
it gives one. With none, `GAP a TO b` is only that order, however long between. Real start and end times are compared, so a
one-hour task may slide around inside its 75-minute block to make a gap work. A labeled
requirement is timed from what it makes, so it takes no count but one `AT_LEAST`, and no
`FOR` over a pool.

Durations are written in minutes, hours or days: `30m`, `1.5h`, `2d`. A gap can reach
across days, which is what the longer units are for:

```skedge
first_meeting:  REQUEST ALL {staff.dylan + staff.sarah} DO 'meeting'
DURING AT_LEAST 1 blocks.all ON AT_LEAST 1 {2026-09-14 .. 2026-09-16}
second_meeting: REQUEST ALL {staff.dylan + staff.sarah} DO 'meeting'
DURING AT_LEAST 1 blocks.all ON AT_LEAST 1 {2026-09-16 .. 2026-09-18}
GAP first_meeting TO second_meeting AT_LEAST 40h
```

One day is scheduled at a time, so what this does day by day is: while both meetings are
still ahead, neither is forced and the solver may put the first one in. Once the first has
been published, the day it went on is what the gap is measured from — the second cannot go
anywhere nearer to it than forty hours, so it waits for a day that is far enough away. A
date later than the one being scheduled holds nothing yet, so it is never the near end of a
gap; it is checked on the day it turns into.

### Where the clauses go

The subject, the verb and the object keep their order. `DURING` and `ON` go anywhere, before
the subject included; `AS_ROLE`, `FOR`, `WITH` and `WITHOUT` go anywhere after the verb.
These are the same request:

```skedge
REQUEST
ON AT_LEAST 1 {2026-09-14 .. 2026-09-18}
ALL {staff.dylan + staff.alesa}
DO 'video'
FOR EXACTLY 30m
DURING AT_LEAST 1 blocks.all
```

```
REQUEST ALL {staff.dylan + staff.alesa} DO 'video' FOR EXACTLY 30m DURING AT_LEAST 1 blocks.all ON AT_LEAST 1 {2026-09-14 .. 2026-09-18}
```

Where a clause is written never changes what it means: the counts in it always go who,
what, dates, blocks. `MAXIMIZE` or `MINIMIZE` goes before or after the pattern it weighs.

### A statement over several lines

A statement can be written on as many lines as it reads well on. A new line starts a new
statement only where one can: at `REQUEST`, `PREFER`, `EXCLUDE`, `IF`, `UNLESS` or `GAP`,
at a binding line (`EACH x IN …`, `EXACTLY n x IN …`), or at a name followed by a colon (a
label or a definition). Every other line carries on the one above it. Nothing needs
indenting, and where a statement fits on one line it can stay there.

So a line inside a statement can't start with `EACH x IN` or `EXACTLY n x IN`, which would
be read as a binding line: put it at the end of the line above instead.

### One request, several statements

A request holds as many `REQUEST` and `PREFER` statements as the thing being asked for
needs. Plain English often does not fit in one statement — "everyone gets a break, and we
would rather they were not all at once" is two — and writing them as one request keeps
them under one description, one priority and one weight, and lets them share a binding, an
`IF` and a `GAP`.

```skedge
# Rob runs the pole course this morning, and we would rather he were free at playstation.
REQUEST staff.rob DO activities.clinics.pole_course_explore_level_1_2_dbl AS_ROLE roles.first DURING ALL {blocks.clinic_1 + blocks.clinic_2}
PREFER staff.rob FREE DURING AT_LEAST 1 blocks.playstation
```

The `REQUEST` statements stand or fall together: the request is met when every one of them
is, and that is what the report names. Each `PREFER` is weighed on its own in the request's
tier, met or not, whether or not the requirements are.

Two things to keep in mind. A binding expands the **whole** request, so `EACH s IN
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
cannot buy or cost anyone a break. A count of clinics, or `ANY` of them, counts the clinics
that are running and starts none of its own. And naming an ad hoc task no `REQUEST` asks
for is an error, which catches misspelled task names.

## Priorities

`MUST_HAPPEN` is hard. `CLINIC`, `HIGH`, `MEDIUM` and `LOW` are soft tiers, and no amount
of a lower tier outweighs a higher one; within a tier, weights set the exchange rate. See
[How the solver decides](solver.md). A `PREFER` cannot be `MUST_HAPPEN`, in a request of
its own or beside requirements; a cap that must hold is a `REQUEST` with `AT_MOST`.

## EXCLUDE: somebody who is not here

A day off, a training course, a dentist's appointment. `EXCLUDE` says that somebody is not
at camp for some of a day. This is different from a break -- someone who is excluded would not factor into the staff pool during the times they are gone.

```skedge
EXCLUDE staff.dylan DO 'offsite' DURING ALL blocks.all ON 2026-09-16
```

Dylan holds nothing in those blocks, no clinic can use him and no request reaches him
there, and the published schedule says `offsite` where his assignments would have been —
on the Staff View in each of his cells, and on the Clinic View in a row of its own beside
the clinics. The quoted word is that label, so write whatever the schedule should say.

| Part | Means |
|---|---|
| `EXCLUDE <who>` | the people who are away: a name, `ALL` a set, or `EACH` one |
| `DO '<label>'` | what the schedule says where they would have been |
| `DURING <blocks>` | the blocks they are away for; left out, every block of the day |
| `ON <dates>` | the dates; left out, the date being scheduled |

**The rules that must happen still must.** A day's legal requirements are written about
the staff who are here — `REQUEST EACH staff.all DO 'break' …` — and somebody out for a
whole day is in no category that day, so nothing is asked of them and the day still solves.
Somebody out for part of a day is still at camp and is still owed their breaks; they are
simply taken in a block they are around for.

An `EXCLUDE` is a fact, so nothing in it is the solver's to choose: `ANY` and counts are
refused, it takes no `IF`, and it is written at `MUST_HAPPEN` in a request of its own.
Naming that person anyway in another request — `REQUEST staff.dylan DO
activities.clinics.riflery` on his day off — is a contradiction the errors pane names: at
`MUST_HAPPEN` the day will not solve, and below it the work simply never happens.

The Adjustments sheet does the same thing for somebody who is [ill or short of
sleep](same-day.md); `EXCLUDE` is for what is known in advance and belongs with the
requests.

## Time horizon

The solver schedules the target date. Published past dates are facts: they cannot change,
and they count in every statement, count and condition. Future dates hold nothing yet.

A request that could still be met later, such as one `ON ANY` a week of dates, is
**deferrable**. It does not have to happen today as long as it can still happen later,
with a small nudge to do it early. The solver knows from the sheets when "later" runs out,
for example because the person rests for the remainder of the week, and enforces it on the
last day that can still hold it. `NOT`, `AT_MOST` and `ALL` dates are enforced every
day.

## Examples

Names below are those of the sample data in `tests/fixtures`; the test suite validates
every example on this page against it.

### Clinic assignment

Archery runs during clinic 2. Loading a date creates a request like this for every
offered clinic, at `CLINIC` priority, tagged `clinic_import`. Asked for by name, the clinic
is staffed from its positions; naming the positions instead asks for a different person in
each with `EACH` — `ALL` would ask one person to hold both. The clinic runs fully staffed
or not at all, so the positions stand together whichever way they are written.

```skedge
REQUEST AT_LEAST 1 staff.all DO activities.clinics.archery_1_2 AS_ROLE EACH {roles.first + roles.second} DURING blocks.clinic_2 ON 2026-09-16
```

Priority `CLINIC`.

### Pinning a staff member to a position

```skedge
REQUEST staff.rob DO activities.clinics.gravity_zip_line AS_ROLE roles.first DURING blocks.clinic_2 ON 2026-09-16
```

Priority `MUST_HAPPEN`.

### Lucy and Tom take out the garbage together every Monday

```skedge
REQUEST ALL {staff.lucy + staff.tom} DO 'take out garbage' DURING AT_LEAST 1 blocks.all ON EACH dates.session_1.mondays
```

Priority `HIGH`.

### Lucy or Tom takes out the garbage every Monday

```skedge
REQUEST AT_LEAST 1 {staff.lucy + staff.tom} DO 'take out garbage' DURING ANY blocks.all ON EACH dates.season.mondays
```

Priority `HIGH`.

### Two of three people, twice in a day

Two of them, each on two blocks of the day.

```skedge
REQUEST AT_LEAST 2 {staff.lucy + staff.tom + staff.charles} DO 'take out garbage' DURING AT_LEAST 2 blocks.all ON 2026-09-21
```

Priority `MEDIUM`.

### Each of three people, some day this week, during playstation

Three separate requests, and each person may get a different day.

```skedge
REQUEST EACH {staff.lucy + staff.tom + staff.charles} DO 'take out garbage' DURING blocks.playstation ON ANY {2026-09-21 .. 2026-09-25}
```

Priority `MEDIUM`.

### Both clinics if possible, some day in session two

One day is chosen; clinic 1 and clinic 2 on it are separate requests.

```skedge
EXACTLY 1 d IN dates.session_2.all
REQUEST staff.dylan DO 'archery maintenance' DURING EACH {blocks.clinic_1 + blocks.clinic_2} ON d
```

Priority `LOW`.

### Training

Cam VL is trained on candle making for two clinics in a row, some day this week.
`roles.trainee` resolves to shadow or scaffolded from the Skills sheet, and the trainee is
additional to the clinic's positions.

```skedge
REQUEST staff.cam_vl DO activities.clinics.candle_making AS_ROLE roles.trainee DURING AT_LEAST 2 CONSECUTIVE blocks.all_clinics ON AT_LEAST 1 {2026-09-14 .. 2026-09-18}
```

Priority `HIGH`.

### Keeping someone off an activity

```skedge
REQUEST staff.dylan NOT DO ANY activities.clinics.ropes ON ANY {2026-09-14 .. 2026-09-16}
```

Priority `MUST_HAPPEN`.

### Staff run clinics they prefer

```skedge
PREFER EACH s IN staff.all DO EACH c IN activities.clinics.all MAXIMIZE mappings.preference(s, c)
```

Priority `MEDIUM`, weight `1`.

### Clinic variety over a rolling week

Each person should run each clinic at most once in any seven days; every repeat costs a
point. Shares a tier with the preference request so the two trade off.

```skedge
PREFER EACH staff.all DO EACH activities.clinics.all DURING AT_MOST 1 blocks.all ON ANY {(dates.target - 6d) .. dates.target}
```

Priority `MEDIUM`, weight `0.5`.

### Rotate ropes positions

Nobody holds the same ropes position more than three times a session.

```skedge
PREFER EACH staff.ropes_level_2 DO ANY activities.clinics.ropes AS_ROLE EACH {roles.first + roles.second} DURING AT_MOST 3 blocks.all ON ANY dates.session_1.all
```

Priority `LOW`.

### Balance clinic workload

Nobody should run more than eight clinics a session: a count of the blocks they run
clinics in, over every day of it.

```skedge
PREFER EACH staff.all DO ANY activities.clinics.all DURING AT_MOST 8 blocks.all ON ANY dates.session_1.all
```

Priority `MEDIUM`, weight `0.25`.

### Never more than three clinics in a row

```skedge
REQUEST EACH staff.all DO ANY activities.clinics.all DURING AT_MOST 3 CONSECUTIVE blocks.all
```

Priority `MUST_HAPPEN`.

### Counselor hours with a maximum gap

Each counselor gets a one-hour counselor hour during clinic 1 or 2 and another during
playstation or clinic 3, no more than five hours apart. `ON` is left out, so this applies
every day.

```skedge
EACH c IN staff.counselor
morning:   REQUEST c DO 'counselor hour' FOR EXACTLY 1h DURING AT_LEAST 1 {blocks.clinic_1 + blocks.clinic_2}
afternoon: REQUEST c DO 'counselor hour' FOR EXACTLY 1h DURING AT_LEAST 1 {blocks.playstation + blocks.clinic_3}
GAP morning TO afternoon AT_MOST 5h
```

Priority `MUST_HAPPEN`.

### Non-counselor breaks

Each non-director, non-counselor staff member takes three 30-minute breaks per day, in
three different blocks. A break in a clinic block keeps that person off clinics in it.

```skedge
REQUEST EACH {staff.all - staff.director - staff.counselor} DO 'break' FOR EXACTLY 30m DURING AT_LEAST 3 blocks.all
```

Priority `MUST_HAPPEN`.

### Breaks at meal times

Where those breaks land: one small request per person per non-meal block.

```skedge
REQUEST EACH {staff.all - staff.director - staff.counselor} NOT DO 'break' DURING EACH {blocks.all - blocks.meals}
```

Priority `HIGH`, weight `2`.

### Never more than two people on break at once

```skedge
REQUEST AT_MOST 2 staff.all DO 'break' DURING EACH blocks.all
```

Priority `MUST_HAPPEN`.

### Two hours of video editing in one go

```skedge
REQUEST staff.cam_vl DO 'video editing' FOR AT_LEAST 2h DURING ANY CONSECUTIVE blocks.all
```

Priority `HIGH`.

### Exactly one of two people rakes the leaves

Whoever else is asked to rake, only one of these two does.

```skedge
REQUEST EXACTLY 1 {staff.dylan + staff.alesa} DO 'rake leaves' DURING ANY blocks.all
```

Priority `HIGH`.

### Playstation availability

As many non-directors as possible are free during the playstation block. Each free person
is one met request; the staff view marks them `Available`.

```skedge
REQUEST EACH {staff.all - staff.director} FREE DURING blocks.playstation
```

Priority `HIGH`.

### Day off

```skedge
EXCLUDE staff.dylan DO 'day off' ON 2026-09-16
```

Priority `MUST_HAPPEN`.

### A review with every director, on the second Thursday

```skedge
REQUEST ALL staff.director DO 'mid-session review' DURING AT_LEAST 1 blocks.all ON dates.session_1.week_2.thursday
```

Priority `MEDIUM`.

### Keeping two staff off the same clinic

One request per block, so each shared clinic costs a point. At `MUST_HAPPEN` it would rule
the pairing out, at the price of leaving a clinic unstaffed when they are the only two
available.

```skedge
REQUEST staff.jack NOT DO ANY activities.clinics.all WITH staff.lucy DURING EACH blocks.all
```

Priority `HIGH`, weight `2`.

### If Rob is on ropes, Vic must be too

```skedge
REQUEST staff.rob NOT DO ANY activities.clinics.ropes WITHOUT staff.vic
```

Priority `MUST_HAPPEN`.

### After three clinics in a row, a free block

```skedge
EACH s IN staff.all
IF s DO ANY activities.clinics.all DURING AT_LEAST 3 CONSECUTIVE blocks.all
REQUEST s FREE DURING ANY blocks.all
```

Priority `HIGH`.

### The same person sets up and tears down

The teardown can be any time after the setup, so its blocks are all of them and the `GAP`
keeps it after.

```skedge
EXACTLY 1 p IN staff.counselor
setup:    REQUEST p DO 'campfire setup' DURING blocks.clinic_4
teardown: REQUEST p DO 'campfire teardown' DURING ANY blocks.all
GAP setup TO teardown
```

Priority `MEDIUM`.

## Grammar

The grammar the parser uses is in the [specification](spec.md#4-grammar), and in
`puppet_strings/skedge/grammar.lark`.
