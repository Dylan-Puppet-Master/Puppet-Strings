# The sheets

Every value the solver uses comes from a Google Sheet. Names become Skedge identifiers by
this rule: trim, lowercase, replace each run of characters that are not letters or digits
with one underscore, and drop underscores at the ends. `Archery 1 & 2` becomes
`activity.archery_1_2`; `Cam VL` becomes `staff.cam_vl`. `puppet-strings names` prints
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
| `Category` | Becomes `activity.<category>`, for example `activity.ropes`. |

Built in: `activity.all` is every clinic. Positions are `role.first`, `role.second`,
`role.third` for the facilitators, then `role.lifeguard`, `role.lifeguard_2` for the
lifeguards.

## Skills

**Main tab.** Three header rows, then one row per staff member. Row 2 holds the skill name
and row 3 the rank; together they form the skill's full name (`Canopy Tour 1st`). A column
whose row 2 is blank is a date column and is skipped. Column A is the name, column B the
RAL (its first number is read, so `4 (6/12)` is 4).

Each cell says where that person stands on that skill:

| Cell | Meaning | Can fill the position | `role.trainee` becomes |
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
`staff.clinic_trainers` is everyone with at least one `Trainer` cell. Each skill column is
a category of its own, `staff.skills.<skill>`, holding everyone checked off on it.

## Staff Categories

One column per category, the name in row 1 and members below. Each becomes
`staff.<category>` (`staff.counselor`, `staff.director`, `staff.village_hero`). Members must
be on the Skills sheet. A column headed `etc.` is ignored.

## Offerings (in Clinic_Schedule)

The grid you already fill in. Row 1 is the weekday; row 2 has `Clinic 1` … `Clinic 4`
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
pane, and the **Import cabin acts** button reads every one of them.

The sheet's **title** says which week it is for: `S5W1` is session 5, week 1, matched
anywhere in the title, so `Cabin Act Sorting - S5W1` works. Those two numbers and the
weekday are looked up on the Calendar sheet to get the date, so nothing on the sheet has
to carry one.

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

**HEROES** is a comma-separated list, and each item becomes its own statement in the
request, so asking for two people asks for two people. An item is either:

| Item | Becomes | The task reads |
|---|---|---|
| A staff member on the Skills sheet | `REQUEST staff.vic` | `help M2 with CA` |
| A Staff Categories column | `REQUEST ANY_1_OF staff.village_hero` | `Village HERO with M2` |
| A Skills column | `REQUEST ANY_1_OF staff.skills.lifeguard` | `LIFEGUARD with M2` |

A person named is being asked for as themselves, so the task says they are there to help;
anything else is being asked for what it can do, so the task says what that is. An item
that is none of the three is a warning naming the cabin and the day, and the rest of that
cabin act still imports. A cabin act with an empty HEROES cell asks nothing of anybody and
makes no request.

## Blocks (config spreadsheet)

One row per time block. Blocks are the units the solver assigns staff to.

| Column | Meaning |
|---|---|
| `block_id` | The block's name, used in requests as `block.<block_id>`. |
| `start`, `end` | The block's times, written any ordinary way: `8:30`, `08:30` and `8:30 AM` all mean the same thing. Blocks may overlap; the solver never gives one person two assignments that overlap in time. |
| `day_types` | **Comma-separated.** The kinds of day this block exists on. Each date's kind comes from the Calendar sheet's `day_type` column. A block whose list does not include that day's type does not exist that day, so no request can select it. |
| `categories` | **Comma-separated.** Groups of blocks a request can name at once: `block.any_clinic`, `block.meals`. `block.all` (every block) is built in and may not be used as a category name. |

One block id is spoken for: `cabin_act` is the slot the [cabin act sheets](#cabin-act-sheets-the-cabin-acts-folder) are imported into, and importing them without it is an error.

Example:

| block_id | start | end | day_types | categories |
|---|---|---|---|---|
| clinic_1 | 09:15 | 10:30 | regular | any_clinic |
| clinic_2 | 10:45 | 12:00 | regular | any_clinic |
| lunch | 12:00 | 13:00 | regular, changeover | meals |
| cabin_act | 13:00 | 14:00 | regular | |
| pack_out | 09:15 | 11:00 | changeover | |
| playstation | 17:00 | 18:00 | regular, changeover | |

On a `regular` day the clinic blocks, lunch and playstation exist; on a `changeover` day
only pack-out, lunch and playstation do.

Blocks are the real periods of the day, not 30-minute slices. A short task such as a
break is written with `FOR 30m` and takes part of a block; the Staff View shows the rest
of that block as `DYOW/WPs` ("do your own work or work projects"). See the
[Skedge reference](skedge.md).

If every day has the same shape, use one day type everywhere: `regular` on every block
and on every Calendar row.

Staff with no assignment in the `playstation` block are marked `Available` in the Staff
View.

## Calendar (config spreadsheet)

One row per camp day.

| Column | Meaning |
|---|---|
| `date` | `YYYY-MM-DD`. |
| `session` | Which session the day belongs to, as a number: `1`, `2`, `3` …. Session 4 is `date.session.four` in a request. |
| `week` | Which week **of that session** the day is in, as a number starting at `1` for each session. Week 2 of session 4 is `date.session.four.second_week`. Number a session's weeks 1, 2, 3 … with none skipped. |
| `day_type` | The kind of day, matched against each block's `day_types`. Any label you like; `regular` for an ordinary day. |

The two numbers are what the whole `date` namespace is built from, so they are worth
getting right: a day's session and week decide which requests reach it. A week does not
have to be seven days, and it does not have to start on a particular weekday — it is
whatever run of days you number alike. The request manager's calendar shows each row's
`S<session>` and `W<week>` down the left-hand side, so a mis-numbered day is easy to spot.

`date.session.four.mondays` is every Monday of session 4, `date.session.four.second_week.monday`
is the one Monday of its second week, and `date.season` is every date on the sheet. See
[Dates](skedge.md#dates) for the full list of date names.

## Requests (config spreadsheet)

One row per request. The request manager edits this tab for you; you can also edit it by
hand.

| Column | Meaning |
|---|---|
| `id` | Unique and stable, in `kebab-case`. Appears in the solver's report. |
| `description` | Plain language, for people. |
| `skedge` | The request itself; see the [Skedge reference](skedge.md). Multi-line cells are fine. |
| `priority` | One of `MUST_HAPPEN`, `CLINIC`, `HIGH`, `MEDIUM`, `LOW`. `STABILITY` is the solver's own during a [same-day change](same-day.md) and is refused here. |
| `weight` | Blank (meaning 1) or a positive number. Not allowed with `MUST_HAPPEN`. |
| `tags` | **Comma-separated.** Any labels you like, for filtering in the request manager. Requests made from the Offerings tab carry the tag `generated`. |
| `groups` | **Comma-separated.** The [groups](app.md#groups) the request belongs to in the request manager, such as `Special daily requests`. A request may be in several groups or in none. Written in plain language, not `kebab-case`. |
| `requester` | Who asked for this, as a staff name: `mary_kate`. Blank if it is nobody's in particular. A name that is not on the Skills sheet makes the request invalid, so a typo is caught rather than lost. |
| `created` | `YYYY-MM-DD`, for the record. |

## Adjustments (config spreadsheet)

One row per staff member per date, for the day only: who is resting, and whose RAL is
down. See [Same-day changes](same-day.md) for what each column does and why absence
lives here rather than in a request. The tab is optional; without it nobody is adjusted.

| date | staff | resting | RAL_penalty | note |
|---|---|---|---|---|
| 2026-06-15 | Alesa | all day | | sick |
| 2026-06-15 | Vic | | 1 | short sleep |

## Metrics (config spreadsheet)

A metric is a table of ratings the solver can score assignments with, such as how much
each staff member prefers each clinic. A request uses it with `MAXIMIZE` or `MINIMIZE`,
for example `PREFER EACH_OF s IN staff.all DOING EACH_OF c IN activity.all MAXIMIZE
metric.preference(s, c)`.

Metrics take **two kinds of tab** in the config spreadsheet:

1. **One tab named `Metrics`** that lists every metric you have and the scale its ratings
   use. Think of it as a table of contents. It has one row per metric.
2. **One tab per metric holding the ratings themselves**, named `metric_` followed by the
   metric's name: `metric_enjoyment`.

If you have no metrics yet, create the `Metrics` tab with just its header row and leave it
empty.

### Step by step: an enjoyment metric

**1. Add a row to the `Metrics` tab.**

| metric | keys | scale_min | scale_max | default |
|---|---|---|---|---|
| enjoyment | staff, activity | 1 | 5 | 3 |

| Column | What to put there |
|---|---|
| `metric` | A short name. It becomes `metric.enjoyment` in requests, and names the ratings tab `metric_enjoyment`. |
| `keys` | **Comma-separated.** What each rating is about. `staff, activity` means one rating per staff member per clinic. Choose from `staff`, `activity`, `role`, `date`, `block`. |
| `scale_min`, `scale_max` | The lowest and highest rating you will ever enter. Ratings are converted to 0–1 against this scale, not against whatever ratings happen to exist, so adding a new rating never changes how the old ones weigh. |
| `default` | Optional. What a pair with no row of its own is worth. Leave it blank and an unrated pair is worth `scale_min`, the bottom of the scale. Set it to the middle of the scale (3 of 1–5 above) and an unrated pair counts as ordinary rather than disliked. A default outside the scale is a load error. |

**2. Create a tab named `metric_enjoyment`.** Give it one column for each key you listed,
in any order, plus a `value` column:

| staff | activity | value |
|---|---|---|
| Dylan | Archery 1 & 2 | 5 |
| Dylan | Candle Making | 3 |
| Mogee | Candle Making | 4 |

Write the names as they appear on the other sheets (`Dylan`, `Archery 1 & 2`), not as
Skedge identifiers, so you can paste rows from elsewhere. A value outside the scale is a
load error.

**3. There is no step 3.** A staff-and-clinic pair with no row of its own is worth the
`default`, so you only need rows for the ratings you actually have. A second metric, say
`variety_need` keyed by `staff`, is another row on the `Metrics` tab and another tab named
`metric_variety_need` with columns `staff` and `value`.

The default matters more than it looks. With a blank default, every clinic nobody has
rated sits at the bottom of the scale, so the solver treats "not rated yet" as "disliked"
and crowds people onto the few clinics that are rated. A default in the middle of the
scale says "no opinion", and only the ratings you actually enter pull for or against.

## Published Schedules

One tab per published date, named by the date, with one row per assignment. Ad hoc tasks
are written in quotes (`'counselor hour'`). These tabs are the record the solver reads
back for past dates.

| Column | Meaning |
|---|---|
| `staff`, `activity`, `role`, `block` | Who does what, in which role, in which block |
| `start` | Where the task starts inside its block, written as `HH:MM` |
| `minutes` | How long it lasts; a clinic fills its block |
| `source` | `offering`, or the request id that required it |

These tabs are overwritten on every publish:

- **Staff View**: one row per staff member, one column per block, with each block's tasks
  in time order and `DYOW/WPs` for unused time.
- **Clinic View**: the printable clinic schedule. A merged title (`Day 4, Session 1 -
  Wednesday`), a header of clinic blocks, then one row per clinic grouped by category in
  Clinic_Data order with a blank row between groups. A clinic with two positions takes two
  rows (1st above 2nd); trainees get a `Shadow` or `Scaffold` row beneath. An offered
  clinic nobody could staff keeps its row, empty. After the clinics come the other tasks
  (counselor hours, breaks) one name per row, and a final `DYOW/WPs` group listing everyone
  with nothing in that block. Title and clinic names are bold and the top rows are frozen.

    It is also coloured, so a printed copy can be read across a room. Each clinic block
    has a colour of its own, on its heading and on every cell of that column with a name
    in it, which leaves the gaps white: an unstaffed clinic and a block somebody is free
    in both show as blank. Each category on Clinic_Data has a colour of its own too, on
    the name of every clinic in it, so a category reads as one run down the left-hand
    column. Both sets of colours are the lists in `puppet_strings/publish/palette.py`;
    change a colour there and the next publish uses it. Colours are given out in sheet
    order and wrap round if a day ever has more clinic blocks, or Clinic_Data more
    categories, than the list has colours.
- **Report**: unsatisfied and deferred requests, conflicts, and solver notes. One row per
  request, not per `EACH_OF` copy: the `request` column is the id as the Requests sheet has
  it, and where only some copies of a request went wrong, they are listed after the
  description — `no break at lunch (2026-09-18)`.
- **Changes**: what a same-day re-solve moved, written only when the day was already
  published. See [Same-day changes](same-day.md).
