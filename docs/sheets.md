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

Built in: `activity.any_clinic` is every clinic. Positions are `role.first`, `role.second`,
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
Blank or `Any` means no checkoff is needed. A clinic missing from this tab has no eligible
staff and is reported as unstaffable when offered.

The staff roster is the set of rows on the main tab, and `staff.all` names all of them.
`staff.clinic_trainers` is everyone with at least one `Trainer` cell.

## Staff Categories

One column per category, the name in row 1 and members below. Each becomes
`staff.<category>` (`staff.counselor`, `staff.director`, `staff.village_hero`). Members must
be on the Skills sheet. A column headed `etc.` is ignored.

## Offerings (in Clinic_Schedule)

The grid you already fill in. Row 1 is the weekday; row 2 has `Clinic 1` … `Clinic 4`
above each group of columns. Below, category headings in capitals and clinic names. The
lookup columns (slots, staff) are ignored, as is everything below a `Cancelled` row.

A `(DBL)` clinic must appear in two adjacent clinic blocks; it becomes one instance with
the same staff in both. The tab has no date: the target date is the `--date` argument or
the app's date picker. A weekday mismatch is a warning.

## Blocks (config spreadsheet)

One row per time block. Blocks are the units the solver assigns staff to.

| Column | Meaning |
|---|---|
| `block_id` | The block's name, used in requests as `block.<block_id>`. |
| `start`, `end` | Times as `HH:MM` on a 24-hour clock. Blocks may overlap; the solver never gives one person two assignments that overlap in time. |
| `day_types` | **Comma-separated.** The kinds of day this block exists on. Each date's kind comes from the Calendar sheet's `day_type` column. A block whose list does not include that day's type does not exist that day, so no request can select it. |
| `categories` | **Comma-separated.** Groups of blocks a request can name at once: `block.any_clinic`, `block.break_slots`. `block.any` (every block) is built in and need not be listed. |

Example:

| block_id | start | end | day_types | categories |
|---|---|---|---|---|
| clinic_1 | 09:15 | 10:30 | regular | any_clinic |
| clinic_2 | 10:45 | 12:00 | regular | any_clinic |
| lunch | 12:00 | 13:00 | regular, changeover | meals |
| pack_out | 09:15 | 11:00 | changeover | |
| playstation | 17:00 | 18:00 | regular, changeover | |

On a `regular` day the clinic blocks, lunch and playstation exist; on a `changeover` day
only pack-out, lunch and playstation do.

Blocks are the real periods of the day, not 30-minute slices. A short task such as a
break is written with `FOR 30m` and takes part of a block; the Staff View shows the rest
of that block as `DYOW/WPs` ("do your own work or work projects"). See
[Skedge reference](skedge.md#task).

If every day has the same shape, use one day type everywhere: `regular` on every block
and on every Calendar row.

Staff with no assignment in the `playstation` block are marked `Available` in the Staff
View.

## Calendar (config spreadsheet)

One row per camp day.

| Column | Meaning |
|---|---|
| `date` | `YYYY-MM-DD`. |
| `session` | Which session the day belongs to, such as `session_1`. `date.session` in a request means every date with the same session as the target date. Repetition windows (`AVOID … BEYOND`) never look outside the session. |
| `day_type` | The kind of day, matched against each block's `day_types`. Any label you like; `regular` for an ordinary day. |

`date.monday` … `date.sunday` are the dates of the target's Sunday-to-Saturday week that
fall inside the session.

## Requests (config spreadsheet)

One row per request. The request manager edits this tab for you; you can also edit it by
hand.

| Column | Meaning |
|---|---|
| `id` | Unique and stable, in `kebab-case`. Appears in the solver's report. |
| `description` | Plain language, for people. |
| `skedge` | The request itself; see the [Skedge reference](skedge.md). Multi-line cells are fine. |
| `priority` | One of `MUST_HAPPEN`, `CLINIC`, `HIGH`, `MEDIUM`, `LOW`. |
| `weight` | Blank (meaning 1) or a positive number. Not allowed with `MUST_HAPPEN`. |
| `tags` | **Comma-separated.** Any labels you like, for filtering in the request manager. Requests made from the Offerings tab carry the tag `generated`. |
| `created` | `YYYY-MM-DD`, for the record. |

## Adjustments (config spreadsheet)

One row per staff member per date, for the day only: who is off, and whose RAL has
dropped. See [Same-day changes](same-day.md) for what each column does and why absence
lives here rather than in a request. The tab is optional; without it nobody is adjusted.

| date | staff | available | ral | note |
|---|---|---|---|---|
| 2026-06-15 | Alesa | no | | sick |
| 2026-06-15 | Vic | | 4 | short sleep |

## Metrics (config spreadsheet)

A metric is a table of ratings the solver can score assignments with, such as how much
each staff member enjoys each clinic. A request uses it with `~`, for example
`PREFER activity.any_clinic ~ metric.enjoyment`.

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
| `start` | `HH:MM`, where the task starts inside its block |
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
- **Report**: unsatisfied and deferred requests, conflicts, and solver notes.
- **Changes**: what a same-day re-solve moved, written only when the day was already
  published. See [Same-day changes](same-day.md).
