# The sheets

Every value the solver uses comes from a Google Sheet. Names become Skedge identifiers by
this rule: trim, lowercase, replace each run of characters that are not letters or digits
with one underscore, and drop underscores at the ends. `Archery 1 & 2` becomes
`activities.clinics.archery_1_2`; `Cam VL` becomes `staff.cam_vl`. `puppet-strings names` prints
the identifier for every sheet value.

## Clinic_Data

The loader reads the **combined tab** (the one with a `Category` column). The per-category
tabs are for people.

| Column | Meaning |
|---|---|
| `Clinic_Name` | The activity's name. A name ending in `(DBL)` spans two adjacent clinic blocks. |
| `Slots` | Camper slots. Shown, not used by the solver. |
| `Staff_Required` | Number of positions (1st, 2nd, 3rd). `Staff_Requested` is accepted too. |
| `RAL_Required` | One digit per position, in order: `53` means the 1st needs RAL 5 and the 2nd RAL 3. The digit count must equal `Staff_Required`. |
| `LG_Required` | Optional. Lifeguards **in addition to** `Staff_Required`. A water clinic with one facilitator and one lifeguard has `Staff_Required` 1 and `LG_Required` 1. Every lifeguard position needs the `LIFEGUARD` skill at RAL 5. |
| `Category` | Becomes `activity.<category>`, for example `activities.clinics.ropes`. |

Built in: `activities.clinics.all` is every clinic. Positions are `roles.first`, `roles.second`,
`roles.third` for the facilitators, then `roles.lifeguard`, `roles.lifeguard_2` for the
lifeguards.

## Skills

**Main tab.** Three header rows, then one row per staff member. Row 2 holds the skill name
and row 3 the rank; together they form the skill's full name (`Canopy Tour 1st`). A column
whose row 2 is blank is a date column and is skipped. Column A is the name, column B the
RAL (its first number is read, so `4 (6/12)` is 4).

Each cell says where that person stands on that skill:

| Cell | Meaning | Can fill the position | `roles.trainee` becomes |
|---|---|---|---|
| `✓`, `WCF` | checked off | yes | scaffolded |
| `Trainer` | checked off and may supervise a scaffold | yes | scaffolded |
| `w/ scaf`, `w/scaf`, `Brief scaf` | needs a scaffold | no | scaffolded |
| `w/ shadow` | needs to shadow | no | shadow |
| blank, `Past Ex`, `Interested`, `.` | not checked off | no | shadow |
| anything else | unknown; treated as not checked off and listed as a warning | no | shadow |

This table lives in one place in the code, `STATUS_WORDS` at the top of
`puppet_strings/sheets/skills.py`. To add a status, add a row there.

**Positions tab.** `Clinic_Name | 1st | 2nd | 3rd`: the skill each position requires.
`Any` means no checkoff is needed. Every clinic on Clinic_Data must have a row here with a
cell filled in for each of its positions, and every skill named must be a column heading on
the main tab (heading plus rank, e.g. `Canopy Tour 1st`). Clinic and skill names are matched
the way every other name is, ignoring case, spacing and punctuation, so a `Candle making`
column and a `Candle Making` cell are the same skill. A missing row, a blank cell, or a name
nothing matches stops loading with an error listing every one. None of them is read as
"anyone may facilitate" — that is what `Any` is for.

The staff roster is the set of rows on the main tab, and `staff.all` names all of them.
`staff.clinic_trainers` is everyone with at least one `Trainer` cell. A skill itself is not
a name: it is asked for by the position that needs it, on a clinic or on a cabin act.

## Staff Categories (one per span, in the schedules tree)

One column per category, the name in row 1 and members below. Each becomes
`staff.<category>` (`staff.counselor`, `staff.director`, `staff.village_hero`). Members must
be on the Skills sheet. A column headed `etc.` is ignored.

**Every span keeps its own**, in its folder in the [schedules tree](#the-schedules-tree),
because who is on staff changes from session to session — so `staff.counselor` follows the
date being scheduled. A span with no `Staff Categories` spreadsheet is a load error naming
the folder it looked in: loading with no categories at all would quietly drop every request
that names one.

**This sheet is also who is at camp.** `staff.all` is everyone it names, not everyone with a
Skills row: the Skills sheet keeps every person who has ever worked here, including staff
who have left and staff who come for one session. Somebody with a Skills row and no category
is away that span, which is the same to the solver as resting all day — no category offers
them and no position can be filled by them. Their name still resolves, so a request that
names them is simply not met rather than an error, and the load says how many are away.

## Offerings (one per day, in the schedules tree)

The grid you already fill in, a tab of the day's own spreadsheet. The **Clinic Schedule**
spreadsheet chosen in Configure is the template a new day is started from. Row 1 is the weekday; row 2 has `Clinic 1` … `Clinic 4`
above each group of columns. Below, category headings in capitals and clinic names. The
lookup columns (slots, staff) are ignored, as is everything below a `Cancelled` row.

Each row 2 heading must name a block on the Blocks sheet — `Clinic 1` finds the block
`clinic_1`, `Playstation` the block `playstation`. A heading that names no block takes its
whole column with it: nothing under it is offered, and the block looks free all day. That is
a warning, listed with the other load warnings, not an error.

A `(DBL)` clinic must appear in two adjacent clinic blocks; it becomes one instance with
the same staff in both. The tab has no date: the target date is the `--date` argument or
the app's date picker. A weekday mismatch is a warning.

## Cabin act sheets (the Cabin Acts folder)

The cabin act block is a time campers may do anything in, and somebody other than the
Puppet Master fills in what each cabin is doing and who they want along. There is one
spreadsheet per session and week, all of them in one Drive folder chosen in the Configure
pane, and every one of them is read each time the sheets are read.

A cabin act is an **activity**, like a clinic: a thing that happens, with a position per
person it needs. It is not a request, so nothing has to be imported and there is no button
to press. Two requests ask for all of them:

```skedge
REQUEST EACH activities.cabin_acts.at_cabin_act DURING blocks.cabin_act
REQUEST EACH activities.cabin_acts.at_rest_hour DURING blocks.rest_hour
```

The Blocks tab must therefore have a `cabin_act` row and a `rest_hour` row.

The sheet's **title** says which week it is for: `S5W1` is session 5, week 1, matched
anywhere in the title, so `Cabin Act Sorting - S5W1` works. Those two numbers and the
weekday give the date from the Calendar sheet, so nothing on the grid has to carry one.

Only the **Board** tab is read; the Support Requests tab says the same thing a second time
and is ignored. Its layout:

| Where | What |
|---|---|
| Row 1 | The sheet's title |
| Row 2 | A weekday merged over its four columns, then the spare `Extra` columns |
| Column A | The cabin, merged down its block of rows: `M1`, `P4`, `O2` |
| Inside a cabin's block | A label column and a value column beside it, per weekday |

The labels read are `Activity` and `HEROES`; everything else on the grid is for the people
filling it in. Rows are found by their labels rather than by counting, so adding a row to
the cabin block changes nothing. Only Monday to Friday are scheduled: the `Extra` columns
are not days and are skipped.

**HEROES** is a comma-separated list, and each item becomes one position of the activity,
so asking for two people asks for two people. An item is either:

| Item | The position it makes |
|---|---|
| A staff member on the Skills sheet | Only that person may hold it |
| A Staff Categories column | Anyone in that category may hold it |
| A Skills column | Anyone checked off on that skill may hold it |

An item that is none of the three is a warning naming the cabin and the day, and the rest
of that cabin act is still staffed. A cabin act with an empty HEROES cell asks nothing of
anybody and becomes no activity at all.

An **Activity** that starts or ends with `RH` or `Rest Hour` (`RH: Fruit Ninja`,
`REST HOUR Aerial Yoga`, `Stranded in the back 40 - Rest Hour`) is moved to rest hour, and
the cabin rests in the cabin act block instead. One that mentions rest hour only in the
middle, such as `CA: Blackberry picking, RH: muffins`, is a warning and is treated as an
ordinary cabin act. Ask for its rest hour part in a request of its own.

The names it makes are `activities.cabin_acts.<cabin>` (for example
`activities.cabin_acts.p4`), `activities.cabin_acts.all`, and the two halves of the board:
`activities.cabin_acts.at_cabin_act` and `activities.cabin_acts.at_rest_hour`. A cabin's
name stands for its act on whichever days the request is about, so over one day it is one
thing and over a week it is five.

## Blocks (config spreadsheet)

One row per time block. Blocks are the units the solver assigns staff to.

| Column | Meaning |
|---|---|
| `block_id` | The block's name, used in requests as `blocks.<block_id>`. |
| `start`, `end` | The block's times, written any ordinary way: `8:30`, `08:30` and `8:30 AM` all mean the same thing. Blocks may overlap; the solver never gives one person two assignments that overlap in time. |
| `day_types` | **Comma-separated**, from `first_day`, `last_day`, `weekday`, `weekend`. Which kinds of day the block exists on. |
| `program_type` | **Comma-separated**, from `main season`, `other`. Which programmes it exists in. |
| `categories` | **Comma-separated.** Groups of blocks a request can name at once: `blocks.all_clinics`, `blocks.meals`. `blocks.all` (every block) is built in and may not be used as a category name. |

A block exists on a day when the day runs one of its programmes **and** is one of its kinds
of day. Nothing writes a day's kinds down: a day is `weekday` or `weekend` by the calendar,
and also `first_day` or `last_day` when it is one end of its Calendar row, so most days are
two kinds at once.

One block id is spoken for: `cabin_act` is the slot the
[cabin act sheets](#cabin-act-sheets-the-cabin-acts-folder) are scheduled into.

Example:

| block_id | start | end | day_types | program_type | categories |
|---|---|---|---|---|---|
| breakfast | 08:00 | 09:00 | weekday, weekend | main season, other | meals |
| clinic_1 | 09:15 | 10:30 | weekday | main season | all_clinics |
| cabin_act | 13:00 | 14:00 | weekday | main season | |
| pack_out | 09:15 | 11:00 | last_day | main season | |
| playstation | 17:00 | 18:00 | weekday, weekend | main season, other | |

So the clinic blocks run Monday to Friday of a main season session; breakfast, lunch and
playstation run every day of every programme; and pack-out runs only on the day a session
ends. If every day has the same shape, write `weekday, weekend` on every block.

Blocks are the real periods of the day, not 30-minute slices. A short task such as a
break is written with `FOR 30m` and takes part of a block; the Staff View shows the rest
of that block as `DYOW/WPs` ("do your own work or work projects"). See the
[Skedge reference](skedge.md).

Staff with no assignment in the `playstation` block are marked `Available` in the Staff
View.

## Calendar (config spreadsheet)

One row per span of days: a session, or anything else camp runs. A fortnight is one row,
not fourteen.

| Column | Meaning |
|---|---|
| `name` | What the span is called. A `main season` row is reached by its number rather than this name, but the name still has to be there and has to be unique. |
| `start date`, `end date` | Both included. Two rows may not cover the same day. Format the column as a date and write it however you like — see below. |
| `program type` | `main season` or `other`, matched against each block's `program_type`. |

Example:

| name | start date | end date | program type |
|---|---|---|---|
| Session 1 | 2026-06-14 | 2026-06-27 | main season |
| Session 2 | 2026-06-28 | 2026-07-11 | main season |
| Family Camp | 2026-09-01 | 2026-09-05 | other |

**The main season rows are numbered in sheet order**, and that number is the name in
Skedge: the first is `dates.session_1.all`, the second `dates.session_2.all`. Anything
else is reached by its name, as `dates.family_camp.all`. Inserting a main season row
renumbers the ones after it, so a request naming `dates.session_4` follows the sheet.
A row that is not main season cannot be named so that it would read as one of the other
date names — `Season`, `Target`, `Session 4`, `Session Target` — and a load says so.

The target date must be one of these spans. It is the first thing checked on every load,
before any other sheet is read, because no block exists on a day camp is not running and so
nothing else would mean anything.

**Dates may be written however the sheet shows them.** Google Sheets hands the program a
date cell as whatever it *displays*, so a column formatted as a date arrives as
`6/14/2026`, `14 June 2026` or `Sunday, June 14, 2026` depending on the sheet's locale and
format. All of those are read, as is plain `2026-06-14` typed as text, and an unformatted
cell's serial number. The one thing that cannot be worked out is a numeric date whose first
two parts are both twelve or less: `6/7/2026` is the 7th of June on a sheet set to the
United States and the 6th of July on most others. That is what `date_order` in
`config.toml` is for — `mdy` by default, `dmy` for the rest of the world — and it is only
consulted for dates that could be read both ways.

**Weeks are not written down.** A span's week 1 is its first seven days, week 2 the next
seven, and so on, with a short week at the end if it does not divide evenly. A row that
starts on the day your weeks start therefore lines up with the calendar, and the request
manager's calendar shows each row's `S<session>` and `W<week>` down the left-hand side, so
you can see at a glance whether it does.

`dates.session_4.mondays` is every Monday of session 4,
`dates.session_4.week_2.monday` is the one Monday of its second week, and
`dates.season.all` is every date the sheet covers. See
[Dates](skedge.md#dates) for the full list of date names.

## Requests (on this computer)

Requests are not a sheet. Nobody edits them anywhere but in the request manager, and only
one Puppet Master schedules at a time, so they live in one file on the Puppet Master's
computer, `~/.config/puppet_strings/requests.sqlite`. Saving a request is instant and
costs no Google requests.

**Handing over.** When another Puppet Master takes over, **Configure → Requests → Export…**
writes the requests to a file, and they **Import…** it on their computer. An import
replaces every request there with the file's; the ones it replaced are kept beside the
file as `requests.before-import.sqlite` until the next import. A file that is not a
requests file, or holds a request the app would refuse, is refused whole and changes
nothing. From the command line:

```
puppet-strings export-requests handover.sqlite
puppet-strings import-requests handover.sqlite
```

Every request has a **scope**: the days it is read on. A load of a date reads every
request whose scope covers that date, and no other, so a request does its work over
exactly the days of its scope and the rest of the season never sees it.

| Scope | Read on | For |
|---|---|---|
| Day | That one date | The clinics imported from the Offerings tab, which are the day's alone, and anything asked of one day. |
| Week | Every date of its week of the session | A week's arrangements. |
| Session | Every date of its session | What was asked of one session in particular. A new request is scoped to its session unless you say otherwise. |
| Season | Every date of the year's season | What holds all season: the legal limits, the standing agreements. |

Weeks and sessions are the Calendar sheet's: a span that is not a numbered session is its
own session, and its weeks are its days seven at a time. The **scope** box in the request
manager offers the day, week, session and season of the date being scheduled. A request's
Skedge can still narrow the days it is about, with `ON`: its scope says when it is read,
and its Skedge what it asks for once it is.

A load imports a day's clinics only when it has none tagged `clinic_import`, so edits to
them last until **Load offerings** is pressed, which throws the day's imported requests away
and makes them again.

Each request has these fields, all edited in the request manager:

| Field | Meaning |
|---|---|
| `id` | Unique and stable. The app gives a new request the next free number for its scope — `season-2`, `s4-1` for session 4, `s4w2-1` for its second week, `jun08-1` for a day — and never changes it. Appears in the solver's report. |
| `description` | Plain language, for people. May be left empty: the id is what names the request. |
| `skedge` | The request itself; see the [Skedge reference](skedge.md). |
| `priority` | One of `MUST_HAPPEN`, `CLINIC`, `HIGH`, `MEDIUM`, `LOW`. `STABILITY` is the solver's own during a [same-day change](same-day.md) and is never a request's. |
| `weight` | A positive number, 1 unless said otherwise. Always 1 with `MUST_HAPPEN`. |
| `tags` | Any labels you like, for filtering in the request manager. Requests made from the Offerings tab carry the tag `clinic_import`. |
| `group` | The one [group](app.md#groups) the request is on in the request manager, such as `Special daily requests`, or none. |
| `requester` | Who asked for this, as a staff name: `mary_kate`. None if it is nobody's in particular. A name that is not on the Skills sheet makes the request invalid, so a typo is caught rather than lost. |
| `created` | The date it was made, for the record. |

## Adjustments (config spreadsheet)

One row per staff member per date, for the day only: who is resting, and whose RAL is
down. See [Same-day changes](same-day.md) for what each column does and why absence
lives here rather than in a request. The tab is optional; without it nobody is adjusted.

| date | staff | resting | RAL_penalty | note |
|---|---|---|---|---|
| 2026-06-15 | Alesa | all day | | sick |
| 2026-06-15 | Vic | | 1 | short sleep |

## Mappings (config spreadsheet)

A mapping is a table that takes one or more names and gives back a value. There are two
kinds:

- A **numeric** mapping gives a number, such as how much each staff member enjoys each
  clinic. A request scores assignments with it using `MAXIMIZE` or `MINIMIZE`:
  `PREFER EACH s IN staff.all DO EACH c IN activities.clinics.all MAXIMIZE
  mappings.preference(s, c)`.
- Any other mapping gives a **name**, such as each counselor's buddy HERO, who covers their
  cabin at dinner. A request can put the call anywhere a name goes:
  `REQUEST mappings.buddy(c) DO 'cabin cover' DURING blocks.evening`.

Mappings take **two kinds of tab** in the config spreadsheet:

1. **One tab named `Mappings`** that lists every mapping you have, what it takes and what
   it gives. Think of it as a table of contents. It has one row per mapping.
2. **One tab per mapping holding the rows themselves**, named `mapping_` followed by the
   mapping's name: `mapping_enjoyment`.

If you have no mappings yet, create the `Mappings` tab with just its header row and leave
it empty.

### Step by step: an enjoyment mapping

**1. Add a row to the `Mappings` tab.**

| mapping | keys | value | scale_min | scale_max | default |
|---|---|---|---|---|---|
| enjoyment | staff, activities.clinics.all | numeric | 1 | 5 | 3 |

| Column | What to put there |
|---|---|
| `mapping` | A short name. It becomes `mappings.enjoyment` in requests, and names its tab `mapping_enjoyment`. |
| `keys` | **Comma-separated.** What each key may be, as Skedge sets: one per argument the mapping takes. `staff, activities.clinics.all` means one rating per staff member per clinic. A bare namespace such as `staff` means any name in it; a set expression such as `{staff.all - staff.counselor}` narrows it down. |
| `value` | `numeric` for a number, or a Skedge set the value must come from. |
| `scale_min`, `scale_max` | Numeric mappings only. The lowest and highest rating you will ever enter. Ratings are converted to 0–1 against this scale, not against whatever ratings happen to exist, so adding a new rating never changes how the old ones weigh. Leave both blank for any other mapping. |
| `default` | Optional. What a key with no row of its own gives. For a numeric mapping it is a number. Leave it blank and an unrated pair is worth `scale_min`, the bottom of the scale. Set it to the middle of the scale (3 of 1–5 above) and an unrated pair counts as ordinary rather than disliked. A default outside the scale is a load error. |

**2. Create a tab named `mapping_enjoyment`.** Give it one column per key, headed `key1`,
`key2` and so on in the order the `keys` cell lists them, and then a `value` column:

| key1 | key2 | value |
|---|---|---|
| Dylan | Archery 1 & 2 | 5 |
| Dylan | Candle Making | 3 |
| Mogee | Candle Making | 4 |

Write the names as they appear on the other sheets (`Dylan`, `Archery 1 & 2`), not as
Skedge identifiers, so you can paste rows from elsewhere. A value outside the scale is a
load error.

**3. There is no step 3.** A staff-and-clinic pair with no row of its own is worth the
`default`, so you only need rows for the ratings you actually have. A second mapping, say
`variety_need` keyed by `staff`, is another row on the `Mappings` tab and another tab named
`mapping_variety_need` with columns `key1` and `value`.

The default matters more than it looks. With a blank default, every clinic nobody has
rated sits at the bottom of the scale, so the solver treats "not rated yet" as "disliked"
and crowds people onto the few clinics that are rated. A default in the middle of the
scale says "no opinion", and only the ratings you actually enter pull for or against.

### Step by step: buddy HEROs

A cabin has the same buddy for the whole session, so the buddies are a mapping from each
counselor to someone who isn't one.

**1. Add a row to the `Mappings` tab.**

| mapping | keys | value | scale_min | scale_max | default |
|---|---|---|---|---|---|
| buddy | staff.counselor | {staff.all - staff.counselor} | | | AT_LEAST 1 {staff.all - staff.counselor - staff.director} |

For a mapping that gives a name, the `default` is a Skedge phrase: what a call stands for
when its key has no row. `AT_LEAST 1 {…}` lets the solver pick anyone from that set. A
single name such as `staff.alan` also works, and so does `ALL {…}`. A default of more
than one name needs its quantifier. Leave the `default` blank and every counselor needs a
row: a request that asks about one without a row is an error.

**2. Create a tab named `mapping_buddy`.**

| key1 | value |
|---|---|
| Dylan | Alan |
| James | Sarah |

Every row is checked when the day loads, the same way a request is. A key that isn't a
counselor, a buddy who is a counselor, a name that doesn't exist and a default that reaches
outside the `value` set are all load errors, and each one names the row. The one exception is
a person who is resting all day or away. They're in no category that day, so whether they
are a counselor can't be checked, and it isn't. A buddy who is off that day is passed over
for the default, so their cabin is still covered.

## The schedules tree

Everything Puppet Strings reads lives in one folder, chosen in the Configure pane. Nothing
else is configured: the folder is walked and things are recognised by their names.

```
Puppet Strings/
  2027/
    Clinic_Data            the season's reference sheets, found by name
    Clinic_Schedule
    Skills
    Config
    Requests               a tab per session; see above
    Main Season/
      Session 1/
        Staff Categories   one spreadsheet, for that span's staff
        Monday_1           one spreadsheet per day
        Tuesday_1
        Monday_2           the second week's Monday
    Other/
      August Family Camp/
        Staff Categories
        Monday_1
```

The root holds a folder per year and the year is taken from the date being scheduled. A
reference sheet is looked for in that year's folder first and at the root second, so a
season can keep its own `Skills` without copying everything else, and sheets that never
change can sit at the root.

Under the year, the programme is the span's `program type` and the folder under it is its
`name`, both read off the [Calendar](#calendar-config-spreadsheet), so nothing is written
down twice. A day is named for its weekday and which week of its span it falls in, because a
fortnight reaches Monday more than once.

**Load offerings makes a day's spreadsheet** when it is not there yet, with the Offerings
grid copied from the Clinic Schedule template — weekday set to its own — and the other tabs
empty, ready for Publish. It never touches a sheet that is already there, so a grid you have
pruned stays pruned.

### A day's spreadsheet

| Tab | What it is |
|---|---|
| `Offerings` | The grid of what runs that day, started from the template and edited by hand |
| `Assignments` | One row per assignment: the record the solver reads back |
| `Staff View`, `Clinic View`, `Report` | Written on Publish, for people to read |
| `Changes` | Added by a same-day re-solve, saying what moved |

The `Assignments` tab is the one the program reads; the views are drawn from it and cannot
be read back, because a grid of names does not say who was on what for how long. A day whose
`Assignments` tab is empty has been set up but not solved, which is how the app knows
whether a date is published.

| Column | Meaning |
|---|---|
| `staff`, `activity`, `role`, `block` | Who does what, in which role, in which block |
| `start` | Where the task starts inside its block, written as `HH:MM` |
| `minutes` | How long it lasts; a clinic fills its block |
| `source` | `offering`, or the request id that required it |

Ad hoc tasks are written in quotes (`'counselor hour'`).

These tabs are overwritten on every publish:

- **Staff View**: one row per staff member at camp, one column per block, with each block's
  tasks in time order and `DYOW/WPs` for unused time. Only the people the span's Staff
  Categories sheet names get a row; the Skills sheet keeps everyone who has ever worked
  here, and the ones it lists who are not here this session are left off both views.
  Somebody an `EXCLUDE` has taken out of a block has that request's label in the cell —
  `offsite`, `at the dentist` — rather than an empty one.
  A merged title says which day it is, the names and the block headings are frozen so they
  stay put as the grid is scrolled, each block column carries the colour it has on the
  Clinic View, every other row is banded, and the columns are wide enough — and wrapped —
  for two tasks in one block to read as two lines.
- **Clinic View**: the printable clinic schedule. A merged title (`Day 4, Session 1 -
  Wednesday`), a header of clinic blocks, then one row per clinic grouped by category in
  Clinic_Data order with a blank row between groups. A clinic with two positions takes two
  rows (1st above 2nd); trainees get a `Shadow` or `Scaffold` row beneath. Nothing has a
  row unless somebody is on it: a clinic that was offered and could not be staffed, or that
  a request put off to another day, is not happening today and is not on the schedule. The
  Report is what names a clinic that was asked for and did not run. After the clinics come
  the other tasks (counselor hours, breaks) one name per row, a row per `EXCLUDE` label
  with the people it takes out of the day, and a final `DYOW/WPs` group listing everyone
  with nothing in that block. Somebody who is away is in their own row rather than among
  the people who are free. Title and clinic names are bold and the top
  rows are frozen.

    It is also coloured, so a printed copy can be read across a room. Each clinic block
    has a colour of its own, on its heading and on every cell of that column with a name
    in it, which leaves the gaps white: a clinic that runs in one block and not another
    shows as blank in the block it does not run in. Each category on Clinic_Data has a colour of its own too, on
    the name of every clinic in it, so a category reads as one run down the left-hand
    column. Both sets of colours are the lists in `puppet_strings/publish/palette.py`;
    change a colour there and the next publish uses it. Colours are given out in sheet
    order and wrap round if a day ever has more clinic blocks, or Clinic_Data more
    categories, than the list has colours.
- **Report**: unsatisfied and deferred requests, conflicts, and solver notes. One row per
  request, not per `EACH` copy: the `request` column is the request's own id, and where only some copies of a request went wrong, they are listed after the
  description — `no break at lunch (2026-09-18)`.
- **Changes**: what a same-day re-solve moved, written only when the day was already
  published. See [Same-day changes](same-day.md).
