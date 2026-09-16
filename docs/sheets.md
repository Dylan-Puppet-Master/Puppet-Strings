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
| `LG_Required` | Optional. How many of the position holders must hold the `LIFEGUARD` skill. |
| `Category` | Becomes `activity.<category>`, for example `activity.ropes`. |

Built in: `activity.any_clinic` is every clinic.

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

## Blocks (Puppet Strings spreadsheet)

| block_id | start | end | day_types | categories | display_group |
|---|---|---|---|---|---|
| clinic_1 | 09:15 | 10:30 | regular | any_clinic | |
| pm_break | 13:00 | 13:30 | regular | break_slots | break_then_work_projects |
| work_projects | 13:30 | 14:00 | regular | | break_then_work_projects |
| playstation | 17:00 | 18:00 | regular | | |

`block.any` is built in. A block exists on a date only if the date's day type is listed.
Blocks sharing a `display_group` appear as one column in the staff view. Staff with nothing
in the `playstation` block are marked `Available`.

## Calendar (Puppet Strings spreadsheet)

| date | session | day_type |
|---|---|---|
| 2026-06-14 | session_1 | regular |

`date.session` is every date sharing the target's session. `date.monday` … `date.sunday`
are the dates of the target's Sunday-to-Saturday week that fall inside the session.

## Requests (Puppet Strings spreadsheet)

| id | description | skedge | priority | weight | created |
|---|---|---|---|---|---|

The request manager edits this tab for you. `priority` is one of `MUST_HAPPEN`, `CLINIC`,
`HIGH`, `MEDIUM`, `LOW`. `weight` is blank or a positive number, never with `MUST_HAPPEN`.

## Metrics (Puppet Strings spreadsheet)

An index tab `Metrics` and one data tab per metric named `metric_<name>`:

| metric | keys | scale_min | scale_max |
|---|---|---|---|
| enjoyment | staff, activity | 1 | 5 |

`metric_enjoyment`:

| staff | activity | value |
|---|---|---|
| Dylan | Archery 1 & 2 | 5 |

Key cells hold sheet names. A missing row scores 0. Values outside the scale are errors.

## Published Schedules

One tab per published date, named by the date, with one row per assignment:
`staff | activity | role | block | source`. Ad hoc tasks are written in quotes
(`'counselor hour'`). These tabs are the record the solver reads back for past dates.

Three tabs are overwritten on every publish: **Staff View**, **Clinic View**, **Report**.
