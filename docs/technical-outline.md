# Puppet Strings: Technical Outline

Status: **approved 2026-09-15**, with the Puppet Master's answers folded in (see §10).

The Skedge language was redesigned on 2026-09-17. Where this outline shows request
syntax (`TASK`, `FORBID`, `AVOID`, `ACROSS`, `PER … BEYOND`), the
[Skedge specification](spec.md) is now the definition and the [reference](skedge.md)
the readable version; the pipeline, sheets and solver structure below still hold.

This outline was written after reading the four existing sheets (Clinic_Data, Clinic_Schedule, Skills, Staff Categories). Where the sheets differ from the proposal, this document follows the sheets and says so. Every assumption is collected in §9; open questions are in §10.

---

## 1. Architecture

### 1.1 Overview

Puppet Strings is one Python package, `puppet_strings`, exposed two ways: a command line tool and a desktop window. Both call the same library functions. Google Sheets holds everything but the requests, which are one SQLite file on the Puppet Master's computer (`requests.sqlite`; see §2.7). Beside it in the config folder are credentials, a config file, a cache of Google Sheets tabs kept until Drive says they changed (`sheets-cache.sqlite`), and the Skedge parser's tables (`parser.cache`, rebuilt whenever the grammar changes).

```
 Google Sheets                          Puppet Master's laptop
 ─────────────────────────              ──────────────────────────────────────────────
 Clinic_Data      ─┐                    ┌──────────────┐     ┌──────────────────────┐
 Skills            │  gspread (read)    │ sheets/      │     │ app/  (PySide6 GUI)  │
 Staff Categories  ├───────────────────►│ load_dataset │◄────┤ cli/  (puppet-strings)│
 Offerings tab     │                    └──────┬───────┘     └──────────┬───────────┘
 Blocks, Calendar  │                           │ Dataset                │
 Mappings         ┘                           ▼                        │
 Published (past) ─────────────────────► skedge/ parse+validate         │
                                               │ Declarations           │
                                               ▼                        │
                                         solver/ (CP-SAT)               │
                                               │ Result                 │
 Published (target) ◄──── gspread (write) ─ publish/ ◄──────────────────┘
```

- **The solver runs locally**, on whichever machine runs the tool. OR-Tools cannot run inside Google Apps Script, and a server would add hosting, secrets, and uptime to the Puppet Master's job. A solve for one day is expected to take seconds.
- **Google Sheets is read when it changed.** Each spreadsheet's Drive `version` comes back with the folder listings a load already makes, and a tab read at that version is read off disk (`sheets/cache.py`). The requests are a local file, written on every save (`requests_db.py`).
- **One code path for data.** Sheet readers return plain tables (`list[list[str]]`). The same parsers turn tables from Google Sheets or from CSV files into domain objects, so tests and offline runs use CSV fixtures with no other changes.

### 1.2 Authentication

**OAuth as the Puppet Master.** Revised 2026-09-19; it was a service account until then.

1. A one-time setup creates a Google Cloud project, enables the Sheets and Drive APIs, and downloads a Desktop app OAuth client JSON to `~/.config/puppet_strings/oauth_client.json`.
2. The first run of the app opens a browser for consent and writes the token to `~/.config/puppet_strings/token.json`, mode 600. Every run afterwards refreshes it silently; the Configure pane signs in again as a different account, or signs out.
3. `gspread.authorize(credentials)` reads the sheets, and the same credentials authorize a plain `AuthorizedSession` against Drive v3 `files.list` for browsing (`puppet_strings/drive.py`).

Scopes: `spreadsheets`, `drive.metadata.readonly`, `userinfo.email`, `openid`.

The service account is why this changed: it has no My Drive, nothing shared with it and no shared drives, so it could never back a Drive browser, and every new sheet had to be shared with an address nobody recognises. A service account key at `[auth] credentials` is still honoured when nobody is signed in, so an existing install keeps working.

### 1.3 Configuration

`~/.config/puppet_strings/config.toml` (path overridable with `PUPPET_STRINGS_CONFIG`):

```toml
[sheets]
clinic_data      = "1bcCFIBqL77HbPiY1nOM2cqzZ0YC9fhRcdBi4TwZS0-E"
clinic_schedule  = "1h_iOC7oqe43QFkpgoS-D-oFzP_r8G1EtDmrxvc83-o8"   # Offerings tab only
skills           = "1SAjIEMtNwdpDWcKkBp8wrEt9BjQJ6kaeHW00zJcBQPs"
staff_categories = "1Z92mJG-AbXKBX_jq5DKztNLVDXPUyL-licZWGvkVPXs"
config           = "<new spreadsheet: Blocks, Calendar, Mappings>"
published        = "<new spreadsheet: one tab per published date>"

# Chosen in the Configure pane and kept in settings.json instead, which wins over these.
[folders]
cabin_acts       = "<folder: one cabin act sheet per session and week>"

[auth]
client_secrets = "~/.config/puppet_strings/oauth_client.json"
token          = "~/.config/puppet_strings/token.json"
credentials    = "~/.config/puppet_strings/service_account.json"   # legacy fallback

[storage]
requests = "~/.config/puppet_strings/requests.sqlite"
cache    = "~/.config/puppet_strings/sheets-cache.sqlite"   # "" for no cache

[solver]
time_limit_seconds = 30   # the whole solve, not each tier
workers            = 8
random_seed        = 0
```

### 1.4 Command line

| Command | Effect |
|---|---|
| `puppet-strings validate` | Parse and validate every request the target date loads against current names. Prints errors with request id, line, column. |
| `puppet-strings names` | Print every valid name per namespace. |
| `puppet-strings solve --date 2026-09-16 [--publish]` | Load data, solve, print the schedule and report. With `--publish`, write the day's own spreadsheet. |
| `puppet-strings export-fixtures DIR` | Download every sheet tab as CSV, and copy the requests to `DIR/requests.sqlite`. Used to refresh test fixtures and to work offline. |
| `puppet-strings export-requests FILE` | Copy the requests to a file for another Puppet Master. |
| `puppet-strings import-requests FILE` | Replace the requests with that file's, keeping the old ones in `requests.before-import.sqlite`. |
| `puppet-strings self-check` | Import every module the app can reach, including what only signing in to Google loads. The release build runs it on each packaged executable first. |
| `puppet-strings app` | Open the desktop request manager. |

Every command accepts `--fixtures DIR` to read CSVs instead of Google Sheets, and the requests in `DIR/requests.sqlite` instead of this computer's; `--no-cache` reads every sheet from Google.

### 1.5 Desktop application

**PySide6 (Qt for Python).** Reasons: mature, documented, native windows, and it ships the widgets this app needs without extra libraries: a table with sorting and filtering (`QTableView` + `QSortFilterProxyModel`), a plain-text editor with syntax highlighting (`QPlainTextEdit` + `QSyntaxHighlighter`), and a calendar (`QCalendarWidget`). The GUI is a thin layer: it calls `skedge.validate`, `sheets.requests.save`, and `solver.solve`, and holds no logic of its own. Replacing it with a web UI later would not touch the library.

Alternatives considered: Tkinter (no usable code editor widget), Textual (terminal only, less intuitive for a non-programmer), NiceGUI/Streamlit (browser-based, awkward for live validation while typing).

---

## 2. Data Schemas

Names are normalized as follows (this extends the proposal's rule because clinic names contain `&`, `/`, `:`, `(`, `)` and `'`): trim, lowercase, replace every run of characters outside `a–z 0–9` with one underscore, strip leading and trailing underscores, and prefix `_` if the result starts with a digit.

| Sheet value | Identifier |
|---|---|
| `Mary Kate` | `staff.mary_kate` |
| `Cam VL` | `staff.cam_vl` |
| `Archery 1 & 2` | `activities.clinics.archery_1_2` |
| `Blacksmithing (DBL)` | `activities.clinics.blacksmithing_dbl` |
| `Crow's Nest (DBL)` | `activities.clinics.crow_s_nest_dbl` |
| `Village HERO` | `staff.village_hero` |

The validator rejects collisions within a namespace. The desktop app and `puppet-strings names` show the identifier next to each sheet value.

### 2.1 Clinic_Data (existing, read)

The spreadsheet has one tab per category (Arts, Outdoor, Rolling, …) and one combined tab with a `Category` column. The loader reads **only the combined tab** (the first tab whose header contains `Category`). The per-category tabs are for people. `LG_Required` moves to the combined tab as an optional column.

| Column | Type | Notes |
|---|---|---|
| `Clinic_Name` | text | Activity name. Trailing spaces are trimmed (`Archery 3 `). |
| `Slots` | int | Camper slots. Displayed only; not used by the solver. |
| `Staff_Required` or `Staff_Requested` | int | Number of positions. Both header spellings exist and are accepted. |
| `RAL_Required` | digit string | **One digit per position**, in position order: `53` means 1st needs RAL 5, 2nd needs RAL 3; `543` covers three positions. Exactly `Staff_Required` digits; any other length is a load error naming the row (the current sheet has four such rows to fix). |
| `LG_Required` | int, optional | Lifeguards in addition to `Staff_Required`, each a position needing the `LIFEGUARD` skill at RAL 5. Blank means 0. |
| `Category` | text, optional | Present on the combined tab; otherwise the tab name is used. Becomes `activities.clinics.<category>` (`activities.clinics.ropes`, `activities.clinics.arts`). |

Built-in: `activities.clinics.all` = every row. Positions are `roles.first`, `roles.second`, `roles.third` for `Staff_Required` = 1, 2, 3, followed by `roles.lifeguard`, `roles.lifeguard_2` for `LG_Required` = 1, 2.

### 2.2 Skills (existing, read)

**Main tab.** Three header rows and one row per staff member.

| Row | Content |
|---|---|
| 1 | Skill group (`Ropes`, `Circus`, …). Merged cells. Ignored by the loader. |
| 2 | Skill name (`Canopy Tour`, `Ground Belay`, `Candle making`). A blank cell marks a date column, which is skipped. |
| 3 | Rank (`1st`, `2nd`, `1st CW`, `3rd`) or blank. |

Column A is the staff name, column B is `RAL (+ date of incident)` and column C is a count that the loader ignores. A skill's full name is `"{row 2} {row 3}".strip()`, which matches the sheet's own `Skill_Name` column on its third tab: `Canopy Tour 1st`, `Ground Belay 1st CW`, `Leap of Faith`, `LIFEGUARD`, `Any`.

The RAL cell is parsed as its leading integer, so `4 (6/12)` reads as 4.

Cell values map to a status:

| Cell value | Status | Can fill a position | `roles.trainee` resolves to |
|---|---|---|---|
| `✓`, `WCF` | checked off | yes | scaffolded |
| `Trainer` | checked off, **trainer for this skill**, can supervise a scaffold | yes | scaffolded |
| `w/ scaf`, `w/scaf`, `Brief scaf` | needs scaffold | no | scaffolded |
| `w/ shadow` | needs shadow | no | shadow |
| blank, `Past Ex`, `Interested`, `.` | not checked off | no | shadow |
| anything else (`Yes`, a date) | unknown, treated as not checked off, listed in the load warnings | no | shadow |

The mapping is one table at the top of `sheets/skills.py`. A planned "competent facilitator" status, which also supervises scaffolds, is one added row there: the status carries a `can_scaffold` flag, and the scaffold constraint reads that flag rather than the word `Trainer`.

The staff roster (`staff.all`) is the set of rows on this tab.

**Position skills tab** (`Clinic_Name | 1st | 2nd | 3rd`). Maps each clinic position to the skill it requires. A blank cell, or the value `Any`, means the position needs no checkoff (every staff member holds `Any`). A clinic absent from this tab has no eligible staff and is reported as unstaffable when offered.

**Derived tab** (`Skill | Rank | Skill_Name | staff…`). Not read; the loader derives the same information from the main tab.

### 2.3 Staff Categories (existing, read)

One column per category. Row 1 is the category name; the cells below list members. Every member must be a Skills row. Each column becomes `staff.<category>` (`staff.counselor`, `staff.director`, `staff.ropes_level_2`, `staff.village_hero`). A column headed `etc.` or left blank is skipped.

Built-in: `staff.all`. Derived: `staff.clinic_trainers` = everyone with at least one `Trainer` cell on the Skills tab, unless a Staff Categories column of that name exists, which then wins.

### 2.4 Offerings (existing, in Clinic_Schedule, read)

Layout as it exists today:

| Row | Content |
|---|---|
| 1 | Weekday name, merged (`THURSDAY`). |
| 2 | `Clinic 1 | | | Clinic 2 | slots | staff | Clinic 3 | … | Clinic 4 | …` |
| 3… | Category headings in capitals (`WEAPONS`), clinic names, blank rows. Columns B/C, E/F, … are lookups and are ignored. |
| totals | A row of numbers. Ignored. |
| `Cancelled` | Merged row. Everything below it is ignored. |

The loader finds the columns whose row-2 header normalizes to a block id (`Clinic 1` → `blocks.clinic_1`) and reads each non-blank cell that is a known clinic name. Cells that match a category name or are numeric are skipped; any other unknown text is a load error naming the cell.

The tab carries no date. The target date comes from `--date` (default: tomorrow). The loader warns if the weekday in row 1 does not match the target date.

A clinic whose name ends in `(DBL)` and that appears in two adjacent clinic blocks is one instance: the same staff hold both blocks. See §10.

### 2.5 Blocks (new, read)

One row per time block, as in the proposal.

| Column | Type | Example |
|---|---|---|
| `block_id` | identifier | `clinic_1` |
| `start` | HH:MM | `09:15` |
| `end` | HH:MM | `10:30` |
| `day_types` | comma list | `regular` |
| `categories` | comma list | `any, all_clinics` |
| `display_group` | text, optional | `break_then_work_projects` |

`blocks.any` is added automatically. A block exists on a date only if the date's day type is in `day_types`. Overlap is computed from `start`/`end`.

### 2.6 Calendar (new, read)

One row per **span**: a run of days from `start date` to `end date` running one programme.
This is the "session calendar" the proposal names as the source of the `dates` namespace
but does not define.

| Column | Type | Example |
|---|---|---|
| `name` | text, unique | `Session 1` |
| `start date` | ISO date | `2026-06-14` |
| `end date` | ISO date, on or after the start | `2026-06-27` |
| `program type` | `main season` or `other` | `main season` |

Main season rows are numbered in sheet order, and that number is the name: session 3 is
`dates.session_3.all` and its second week `dates.session_3.week_2.all`. Anything
else is `dates.<name>.all`. Weeks are not written down — a span's week is its days
seven at a time from the start — and nor are day types: a date is `weekday` or `weekend` by
the calendar and `first_day` or `last_day` at the ends of its span, which is what the
Blocks sheet's `day_types` and `program_type` columns are matched against.

See [Dates](skedge.md#dates); this table was rewritten on 2026-09-18 with the date
redesign (§11) and again on 2026-09-19 to spans.

### 2.7 Requests (local file, read and written)

One SQLite file, `requests.sqlite`, with a `requests` table and a `meta` table holding the
format version. Each request has a **scope** — day, week, session or season — kept as the
dates it covers, and a load of a date reads every request whose scope covers it, through an
index on those dates. Export and import copy the whole file.

| Column | Type | Rules |
|---|---|---|
| `id` | text | The primary key: unique in the file, stable, `kebab-case`. |
| `scope` | `day` `week` `session` `season` | |
| `first`, `last` | ISO dates | The days the scope covers, both included. The season is its calendar year. |
| `description` | text | |
| `skedge` | multi-line text | |
| `priority` | `MUST_HAPPEN` `CLINIC` `HIGH` `MEDIUM` `LOW` | `STABILITY` is refused. |
| `weight` | real | Positive; always 1 with `MUST_HAPPEN`. |
| `tags`, `group`, `requester` | text | Tags comma-separated. |
| `created` | ISO date or null | Set by the app on creation. |

### 2.8 Mappings (new, read)

An index tab `Mappings` plus one data tab per mapping. (These were *metrics* until
2026-09-22, when a mapping that gives a name rather than a number was needed for buddy
HEROs; a metric is now a numeric mapping.)

`Mappings`:

| Column | Example | Example |
|---|---|---|
| `mapping` | `enjoyment` | `buddy` |
| `keys` | `staff, activities.clinics.all` | `staff.counselor` |
| `value` | `numeric` | `{staff.all - staff.counselor}` |
| `scale_min` | `1` | |
| `scale_max` | `5` | |
| `default` | `3` | `AT_LEAST 1 {staff.all - staff.counselor - staff.director}` |

`keys` and `value` are Skedge sets (or a bare namespace), so what a call may take and
give is checked like any other name. `mapping_enjoyment`:

| key1 | key2 | value |
|---|---|---|
| Dylan | Archery 1 & 2 | 5 |
| Dylan | Candle Making | 3 |

Keys and values are sheet names, not identifiers, so the Puppet Master can paste from other sheets. Normalized score = `(value − scale_min) / (scale_max − scale_min)`. A key with no row takes the `default`. Values outside the scale, and cells outside their sets, are load errors. The [sheets page](sheets.md#mappings-config-spreadsheet) is the full reference.

### 2.9 The schedules tree (new, read and written)

Revised 2026-09-19; it was one spreadsheet of dated tabs until then. One Drive folder tree
under the `schedules` root chosen in the Configure pane: `<year>/<Program Type>/<span
name>/`, holding one `Staff Categories` spreadsheet and one spreadsheet per day named
`<Weekday>_<week of the span>`. Every part of the path is read off the Calendar sheet.

A day's spreadsheet holds `Offerings` (started from the Clinic Schedule template when the
day is made), `Assignments`, `Staff View`, `Clinic View`, `Report`, and `Changes` after a
same-day re-solve. `Assignments` is the canonical record and what the solver reads back as
fixed past assignments; an empty one means the day is set up but not solved.

| Column | Example |
|---|---|
| `staff` | `Dylan` |
| `activity` | `Archery 1 & 2` or `'counselor hour'` |
| `role` | `first`, `shadow`, `scaffolded`, or blank for ad hoc tasks |
| `block` | `clinic_2` |
| `source` | `offering`, or the request id that required it |

Three further tabs are overwritten on every publish and hold the latest date only: `Staff View`, `Clinic View`, `Report`. Older views can be regenerated from the date tabs with `puppet-strings solve --date … --publish` only if the date is not yet published; a `--views-only` flag re-renders views from an existing tab without solving.

- **Staff View**: one row per staff member, one column per block (blocks sharing a `display_group` merge into one column). A staff member with no assignment in `blocks.playstation` shows `Available`.
- **Clinic View**: one row per clinic somebody is on, one column per clinic block, position holders in order (1st above 2nd), trainees after them marked `(shadow)` or `(scaffolded)`. Coloured one colour per clinic block column and one per Clinic_Data category (`publish/palette.py`); `Styled` carries the fills and `SheetsSource.style` sends them in one `batch_format`.
- **Report**: one row per unsatisfied soft request (`id`, `priority`, `description`) and, for an infeasible run, the conflicting `MUST_HAPPEN` ids.

Republishing a date overwrites its tab after a confirmation prompt.

---

## 3. Package Layout

```
puppet_strings/
├── __init__.py
├── config.py            # config.toml loading, paths
├── names.py             # normalize(), Namespace lookup, collision check
├── model.py             # dataclasses: Staff, Activity, Position, Block, CalendarDay,
│                        #   Request, Assignment, MappingTable, Dataset
├── sheets/
│   ├── source.py        # Table = list[list[str]]; SheetsSource (gspread), CsvSource
│   ├── clinic_data.py   # one parse function per sheet, table -> model objects
│   ├── skills.py
│   ├── categories.py
│   ├── offerings.py
│   ├── blocks.py
│   ├── calendar.py
│   ├── requests.py      # read and write
│   ├── mappings.py
│   ├── published.py     # read past dates; write date tab and views
│   └── load.py          # load_dataset(source, target_date) -> Dataset
├── skedge/
│   ├── grammar.lark     # the grammar from the proposal
│   ├── ast.py           # Declaration, Line, Clause, Verb, Selector nodes
│   ├── parser.py        # text -> AST (Lark transformer)
│   ├── scope.py         # clause scoping, defaults, EACH expansion
│   ├── resolve.py       # selectors -> item sets and alternatives, using a Dataset
│   └── validate.py      # every rule in proposal §8; SkedgeError(line, column, message)
├── solver/
│   ├── variables.py     # eligible assignment tuples -> BoolVar; FREE literals
│   ├── structural.py    # implicit constraints (proposal rules 1–8, plus §4.2 here)
│   ├── compile.py       # one function per verb: TASK, FORBID, PREFER, AVOID, GAP
│   ├── tiers.py         # lexicographic solve loop, integer scaling
│   ├── solve.py         # solve(dataset) -> Result
│   └── result.py        # Result, Schedule, UnsatisfiedRequest, Conflict
├── publish/
│   └── views.py         # staff view and clinic view as tables
├── cli.py               # argparse entry points
└── app/                 # PySide6
    ├── main.py          # window, menu, solve/publish actions
    ├── request_table.py # model + proxy filters (date, priority, staff, activity, scope)
    ├── editor.py        # Skedge editor, highlighter, live validation
    └── namespaces_panel.py # browsable tree of valid names

tests/
├── fixtures/            # CSV export of each tab, trimmed to ~15 staff and ~25 clinics
├── test_names.py
├── test_sheets_*.py     # one per parser
├── test_parser.py       # every proposal example parses
├── test_validate.py     # every rule in proposal §8
├── test_solver_*.py     # one per verb, plus test_scenarios.py for the required scenarios
└── test_views.py

docs/                    # MkDocs Material
mkdocs.yml
pyproject.toml           # package, dependencies, ruff, pytest config
.github/workflows/ci.yml       # ruff + pytest on push and PR
.github/workflows/docs.yml     # mkdocs gh-deploy on push to main
```

Dependencies: `ortools`, `lark`, `gspread`, `PySide6`. Development: `pytest`, `ruff`, `mkdocs-material`. Python 3.12.

---

## 4. Skedge to CP-SAT

### 4.1 Pipeline

1. **Parse** each request's `.skedge` with Lark into an AST of lines and clauses.
2. **Scope**: attach clauses to verbs (same line, or verb-less line), apply defaults (`ON EACH dates.session`, `ACROSS staff.all`), reject duplicates.
3. **Expand `EACH`** into independent declaration copies (Cartesian product when several clauses use it). Each copy gets its own satisfaction literal and reports under `id[copy-key]`, for example `counselor-hours[dylan]`.
4. **Resolve** every selector against the `Dataset` into item sets; normalize `OR`/`AND` to alternatives; apply quantifiers.
5. **Apply the time horizon** (proposal §7): past dates become constants from Published Schedules, future dates are dropped, deferrable tasks are marked.
6. **Compile** to CP-SAT constraints and tier objective terms.
7. **Solve** tiers lexicographically; extract the schedule and report.

### 4.2 Variables and structural constraints

- `x[s, a, r, d, b]`: `BoolVar` for each staff `s`, activity `a`, role `r`, date `d` (target only), block `b` where the Skills status allows `s` in `r` for `a` and RAL is met. Ad hoc tasks (`'counselor hour'`) and `FREE` have `r = None` and no eligibility filter. Trainee variables exist only for offered instances.
- `free[s, d, b]`: true iff no `x` for `s` overlaps block `b` on `d`. Encoded as `free + sum(x overlapping b) == 1` when blocks in the overlap set are pairwise exclusive (always true after the no-double-booking constraint).
- **No double booking**: for each staff and block, `sum(x[s, *, *, d, b]) <= 1`; for each pair of overlapping blocks, `sum over both <= 1`.
- **One holder per position, one instance per block**: `sum_s x[s, a, p, d, b] <= 1` for every position `p`. (Implied by the proposal, stated here.)
- **Offered clinics are staffed**: for each offering `(a, d, b)`, a generated `CLINIC` request `REQUEST activities.clinics.a DURING blocks.b ON d` with id `offering:<a>:<b>`.
- **Lifeguards** are ordinary positions with skill `LIFEGUARD` and RAL 5, so eligibility (rule 2) covers them.
- **Trainees**: `x[s, a, shadow, d, b] → filled[a, d, b]`, where `filled` is the AND of the position-filled literals. `x[s, a, scaffolded, d, b] → OR(x[t, a, p, d, b] for trainers t of p's skill)`. At most one trainee per instance.
- **Past dates**: no variables. Lookups return Python `True`/`False`; compile functions fold constants.

### 4.3 Verb compilation

Every request `q` gets `sat[q]`. `MUST_HAPPEN`: `sat[q]` is added with `model.AddAssumption`. Soft: `+ weight × 1000 × sat[q]` in the request's tier.

**Selectors → choice literals.** For each clause of a `TASK`, the resolver yields items and alternatives. The compiler creates `chosen[item]` per item and, when `OR`/`AND` produced several alternatives, `alt[i]` per alternative with `sum(alt) == sat` and `chosen[item] ⇔ OR(alt[i] for i containing item)`. Quantifiers on plain sets need no alternative enumeration:

| Quantifier | Constraint |
|---|---|
| `ANY` | `sum(chosen) == sat` |
| `ALL` | `chosen[item] == sat` for every item |
| `n OF` | `sum(chosen) == n × sat` |

**`TASK <target>`.** For every combination of staff `s`, date `d`, block `b`, role `r` across the four clauses: `x[s, a, r, d, b]` is enforced by `[chosen_staff[s], chosen_date[d], chosen_block[b], chosen_role[r]]`. For a positioned activity without `ROLE`: `sum(x[s, a, p, d, b] for s in pool) == 1` per position `p`, enforced by `[chosen_date[d], chosen_block[b], sat]`. `TASK FREE` enforces `free[s, d, b]` instead of `x`.

**`FOR <duration> [CONTINUOUS]`.** `y[b]` per block in the union of `DURING` blocks; `sum(minutes[b] × y[b]) >= remaining` enforced by `sat`, where `remaining = duration − minutes already published in the window`. `y[b]` enforces the assignments. `CONTINUOUS`: every run of adjacent blocks long enough becomes an alternative literal; `sum(run) == sat`; a run enforces its blocks' `y`.

**Deferrable `TASK`** (window includes future dates): `sat` is free with `+1` scaled unit (one thousandth of a weight-1 request) as incentive; on the window's last date it is enforced at its priority. With `FOR`, non-final dates instead bound `sum(minutes × y) <= remaining` and reward `+1` unit per scheduled minute, so partial progress counts.

**`FORBID <target>`.** Every matched `x` gets `x == 0` enforced by `sat`.

**`PREFER` / `AVOID`.** Each matched `x` contributes `± round(1000 × weight × score) × x` to the tier, where `score` is 1 or the normalized metric value. `PREFER FREE` uses `free` literals.

**`AVOID … PER <fields> BEYOND n`.** Matched `x` are grouped by the listed fields (past published assignments in the window enter as constants). Per group: `excess = IntVar(0, len(group))`, `excess >= fixed_count + sum(group) − n`, contribution `− round(1000 × weight) × excess`.

**`GAP a b <cmp> duration`.** Both labels must be `TASK` verbs with a single-block `DURING` (no `FOR`, no `ALL`, no `n OF`; validation error otherwise). For every pair of blocks `(b1, b2)` where the gap from `end(b1)` to `start(b2)` fails the comparison, or `b2` does not start after `b1` ends: `AddBoolOr([chosen_a[b1].Not(), chosen_b[b2].Not()])`.

### 4.4 Tiers

Tier expressions are integer linear sums. Solve order: `CLINIC`, `HIGH`, `MEDIUM`, `LOW`. After each tier: read the objective value `v`, add `tier_expr >= v`, clear the objective, set the next. `MUST_HAPPEN` requests never appear in an objective. One clock covers the whole solve (see §11): each pass takes what is left of `time_limit_seconds`, less the `tidy_seconds` held back for the placement pass. If a tier ends at the limit without proving optimality, its best found value becomes the bound and the report says so, with the gap it could not close. `num_workers` and `random_seed` are fixed for reproducible output.

On `INFEASIBLE`, `solver.SufficientAssumptionsForInfeasibility()` returns the assumption indices; the report lists their request ids. An empty set means the structural constraints alone conflict (which the report says).

### 4.5 Worked example: counselor hours

Request `counselor-hours`, `MUST_HAPPEN`:

```
ACROSS EACH staff.counselor
TASK 'counselor hour' DURING {blocks.clinic_1 OR blocks.clinic_2} AS morning
TASK 'counselor hour' DURING {blocks.clinic_3 OR blocks.clinic_4} AS afternoon
GAP morning afternoon <= 5h
```

Blocks (from the Blocks sheet): `clinic_1` 09:15–10:30, `clinic_2` 10:45–12:00, `clinic_3` 14:00–15:15, `clinic_4` 15:45–17:00. Target date 2026-09-16. Counselors: Dylan, James, Paul.

Step 3 expands `EACH` into three copies. For Dylan's copy (`counselor-hours[dylan]`), with `ON` defaulted to `EACH dates.session` and then narrowed by the time horizon to the target date:

```python
sat = model.NewBoolVar("sat:counselor-hours[dylan]")
model.AddAssumption(sat)  # MUST_HAPPEN

# morning: {clinic_1 OR clinic_2} -> two singleton alternatives, so chosen == alt
m1 = model.NewBoolVar("morning:clinic_1")
m2 = model.NewBoolVar("morning:clinic_2")
model.Add(m1 + m2 == sat)  # ANY
model.AddImplication(m1, x["dylan", "counselor hour", None, d, "clinic_1"])
model.AddImplication(m2, x["dylan", "counselor hour", None, d, "clinic_2"])

# afternoon: same shape over clinic_3, clinic_4
a3 = model.NewBoolVar("afternoon:clinic_3")
a4 = model.NewBoolVar("afternoon:clinic_4")
model.Add(a3 + a4 == sat)
model.AddImplication(a3, x["dylan", "counselor hour", None, d, "clinic_3"])
model.AddImplication(a4, x["dylan", "counselor hour", None, d, "clinic_4"])

# GAP morning afternoon <= 5h: end(morning) -> start(afternoon)
#   clinic_1 -> clinic_3: 10:30 -> 14:00 = 3h30   ok
#   clinic_1 -> clinic_4: 10:30 -> 15:45 = 5h15   violates
#   clinic_2 -> clinic_3: 12:00 -> 14:00 = 2h00   ok
#   clinic_2 -> clinic_4: 12:00 -> 15:45 = 3h45   ok
model.AddBoolOr([m1.Not(), a4.Not()])
```

The `x` variables for `'counselor hour'` share the no-double-booking constraints with clinic assignments, so choosing `m1` keeps Dylan off every clinic in `clinic_1`. If Dylan is also pinned to Archery in both `clinic_1` and `clinic_2` by a `MUST_HAPPEN` request, the model is infeasible and the report names `counselor-hours[dylan]` and the pin's id.

### 4.6 Worked example: scoring

`clinic-enjoyment` (`MEDIUM`, weight 1, `~ metrics.enjoyment` on a 1–5 scale) and `clinic-variety` (`MEDIUM`, weight 0.5, `PER staff activity BEYOND 1` over the rolling week). Dylan ran archery yesterday (a constant from Published Schedules).

| Term | Coefficient (scaled by 1000) |
|---|---|
| `x[dylan, archery, first, today, clinic_2]` enjoyment 5 → normalized 1.0 | `+1000` |
| `x[dylan, candle_making, first, today, clinic_2]` enjoyment 3 → 0.5 | `+500` |
| `excess[dylan, archery]` with `excess >= 1 + x[archery] − 1` | `−500` |

Archery: `1000 − 500 = 500`. Candle making: `500`. A tie, as in the proposal's table.

---

## 5. Milestones

Each milestone ends with passing `ruff check`, `ruff format --check`, and `pytest`.

| # | Milestone | Deliverable | Testable outcome |
|---|---|---|---|
| 0 | Scaffold | `pyproject.toml`, package skeleton, CI workflow, `export-fixtures` command, trimmed CSV fixtures committed. | CI green on an empty test suite. Fixtures load as tables. |
| 1 | Data layer | `model.py`, `names.py`, every `sheets/*` parser, `load_dataset`. | Each parser has a test against its fixture. RAL digit strings, Skills statuses, `(DBL)` merging, identifier collisions, and unknown Offerings cells are covered. `puppet-strings names --fixtures` prints every namespace. |
| 2 | Skedge | grammar, parser, scope, resolve, validate. | Every proposal example parses to the expected AST and resolves to the expected alternatives. Every rule in proposal §8 has a failing-input test with line and column asserted. `puppet-strings validate --fixtures` works. |
| 3 | Solver core | variables, structural constraints, `TASK` (with `FREE`, `ROLE`, positions), `FORBID`, tiers, assumptions, report. | Scenarios: infeasible `MUST_HAPPEN` pair reports both ids; unstaffable offered clinic is reported and the rest is scheduled; trainee added without filling a position; scaffold only with a trainer; lifeguard minimum. `puppet-strings solve --fixtures` prints a schedule. |
| 4 | Objectives and time | `PREFER`, `AVOID`, metrics, `PER … BEYOND`, `GAP`, `FOR`/`CONTINUOUS`, past constants, deferral. | Scenarios: tradeoff outcomes at weights 0.25, 0.5, 1; `GAP` rejects the 5h15 pair; deferrable task optional then enforced; past assignments count toward `BEYOND`; `FOR 2h` sums across non-adjacent blocks; `CONTINUOUS` does not. |
| 5 | Sheets integration | `SheetsSource`, Requests read/write, Published read/write, views, `--publish`. | View rendering tested on fixtures (display groups merge, `Available`, position order, trainee labels). Manual test against a copy of the real sheets; a written checklist for it is part of the docs. |
| 6 | Desktop app | request table with filters, editor with live validation, names panel, solve and publish buttons. | Manual checklist. Unit tests for the filter proxy and the highlighter's token rules. |
| 7 | Docs and README | MkDocs Material site: install, setup (Google Cloud steps), user guide, Skedge reference with every proposal example, this outline, developer guide. README with overview and install steps. | `mkdocs build --strict` passes in CI; site deploys to GitHub Pages on push to `main`. |

Milestones 3 and 4 are where the proposal's required scenario tests live; both are testable entirely offline.

---

## 6. Testing Approach

- Fixtures are real exports, trimmed by hand to a small staff and clinic set that still exercises every case (multi-position ropes clinics, a water clinic with `LG_Required`, a trainer, a `w/ shadow` and a `w/ scaf` staff member, a `(DBL)` clinic, an unstaffable clinic).
- Solver tests build a `Dataset` in Python from small literal tables rather than from the full fixtures, so each test states the exact situation it checks.
- Parser tests compare ASTs with dataclass equality. Validation tests assert `(line, column)` of the error.
- The scoring tests read the objective value back from CP-SAT and compare against the hand-computed table in §4.6.

---

## 7. Documentation Plan

MkDocs Material with the following navigation:

1. Home: what Puppet Strings does, one screenshot, one diagram.
2. Install: Python, `pipx install`, config file, Google Cloud setup with screenshots.
3. Sheets: every schema from §2, with what each column means for the Puppet Master.
4. Requests app: creating, editing, filtering, validating, solving, publishing.
5. Skedge reference: language rules, every construct, every example from the proposal with its priority and weight, the validation error list.
6. How the solver decides: priorities, weights, the worked tradeoff.
7. Design: this outline, kept current.
8. Development: layout, running tests, refreshing fixtures, releasing.

Deployment: `docs.yml` runs `mkdocs gh-deploy --force` on push to `main`.

---

## 8. Code Conventions

Per the proposal: PEP 8 via `ruff`, docstrings on public functions, return-early, no duplication. Additions:

- Dataclasses with `frozen=True` for model objects.
- Parsers are pure functions `parse_<sheet>(table) -> objects`; they never call gspread.
- Errors that a Puppet Master must act on (`LoadError`, `SkedgeError`) carry sheet, cell or line/column, and a plain-language message. Internal errors are plain exceptions.
- No global state. The `Dataset` is passed explicitly.

---

## 9. Assumptions

Defaults from "Unresolved Decisions":

1. **Scaffolder**: the supervising trainer is one of the staff filling a required position, not an extra person.
2. **Training instances**: `roles.trainee` attaches only to an offered clinic instance; the solver never creates instances for training.
3. **Counselors' third break**: not modeled. Counselor hours give two breaks; no third break is generated. The Puppet Master can add a `TASK 'break'` request for counselors later without code changes.
4. **`GAP` measurement**: end of the first task to start of the second.
5. **Variety across sessions**: repetition windows ignore dates outside the active session.

Assumptions added by this outline:

6. **Name normalization** replaces every non-alphanumeric run with one underscore (§2). The proposal's rule covered spaces only.
7. **RAL_Required** is a digit string with exactly one digit per position. Confirmed; rows with the wrong length are load errors.
8. **Skills statuses** map as in §2.2. `WCF` is a checkoff, `Brief scaf` needs a scaffold. Unknown values are treated as not checked off and reported. Confirmed.
9. **Trainers are per skill**: a scaffold requires a position holder whose status for that position's skill can scaffold (`Trainer` today). `staff.clinic_trainers` is derived from the Skills tab. Confirmed.
10. **`roles.trainee` resolution** uses the staff member's status for the clinic's **first position** skill.
11. **A blank or `Any` position skill** means no checkoff required.
12. **`LG_Required`** counts extra lifeguard positions beyond `Staff_Required`, each requiring `LIFEGUARD` at RAL 5. Confirmed by the Puppet Master on 2026-09-16.
13. **Trainee capacity** is one per instance; Clinic_Data has no override column, so none is read.
14. **`(DBL)` clinics** span two adjacent clinic blocks: one instance, same staff in both blocks. Confirmed.
15. **Offerings date** is the `--date` argument; the tab's weekday header is only checked, not parsed into a date.
16. **The staff roster** is the Skills main tab. Staff Categories members must appear there.
17. **Category names** are used as-is: `staff.counselor`, `activities.clinics.ropes`. The proposal's `staff.counselors` and `activities.clinics.any_ropes` become whatever the sheets say; documentation examples will use the real names.
18. **Activities are clinics only.** Clinic_Data lists no playstations or evening programs. `blocks.playstation` is just a block.
19. **New sheets**: Blocks, Calendar, Requests, Metrics live in one new config spreadsheet; Published Schedules is a second new spreadsheet. `Calendar` is an addition beyond the proposal.
20. **Metric misses** score the metric's `default` column, or `scale_min` when that column
    is blank, which is the original score-nothing behavior. Values and defaults outside the
    declared scale are load errors.
21. **Deferral incentive** is one scaled unit (0.001 of a weight-1 request) per satisfied deferrable task, or per minute for `FOR` tasks.
22. **`GAP` labels** must be single-block `TASK`s on the same date.
23. **`EACH` copies** each count as one satisfied request in their tier, and report as `id[item]`.
24. **Ad hoc task names** are shared across requests: two requests using `'break'` refer to the same activity, so double-booking applies between them.
25. **Authentication** was a service account only. Superseded 2026-09-19: OAuth as the Puppet Master, because a service account cannot browse Drive and the Configure pane needs to.
26. **The desktop app** is PySide6. Confirmed.
27. **Views** are overwritten per publish; per-date tabs are the durable record.
28. **Solver determinism**: fixed seed and worker count; tier time limits default to 30 seconds.

---

## 10. Questions for the Puppet Master

Answered 2026-09-15. Kept for the record.

1. **`(DBL)`**: a clinic spanning two adjacent clinic blocks. Confirmed.
2. **Skills vocabulary**: `WCF` = "with competent facilitator", treated as a checkoff for now; `Brief scaf` = `w/ scaf`. A "competent facilitator" status that can also scaffold is planned.
3. **Trainers**: scaffolding requires a `Trainer` mark on the specific skill. Confirmed.
4. **RAL digit strings**: `53` means 1st needs 5 and 2nd needs 3. A single digit on a two-position clinic is a data error.
5. **Lifeguards**: answered 2026-09-16. A lifeguard is an additional person: one facilitator plus one lifeguard is `Staff_Required` 1, `LG_Required` 1. All lifeguards need RAL 5.
6. **Zero-slot rows** (`Craft Fairy`, `Lvl. 2 on Ground`, `Battle Royale Setup/Breakdown`) are staffed like any clinic. Confirmed.
7. **Hand-written `CLINIC` priority**: unanswered; default kept (reserved for generated offerings).
8. **Scope**: derived from the `ON` clause. Confirmed.
9. **GUI toolkit**: PySide6. Confirmed.
10. **Credentials**: service account. Superseded 2026-09-19 by signing in as the Puppet Master; see 1.2.

Standing direction from the Puppet Master: the Google Sheets formats are not fixed. When the current layout would force convoluted parsing, change the sheet instead, and document the change. The code must be clear enough for the Puppet Master to update without an LLM.

---

## 11. Changes Made During the Build

Recorded so the outline matches the code.

- **Tidiness pass.** After the last tier, the solver minimizes the number of assignments
  so that nothing is scheduled that no request asked for (otherwise ad hoc tasks such as
  counselor hours could appear in extra blocks at no cost).
- **`PREFER`/`AVOID` never score their own `sat`.** Only `TASK` and `FORBID` copies add
  `weight × sat` to a tier; scoring verbs add their matched assignments only.
- **Deferral incentive** is one scaled unit per satisfied deferrable copy, or per block
  scheduled for a deferrable `FOR` task, in the request's own tier (`CLINIC` for hard
  requests).
- **`(DBL)` assignments count once** in `PREFER`, `AVOID` and `PER … BEYOND`, both for
  today's variables and for published rows.
- **The default `ON EACH dates.session` is shared** by every verb in a declaration, so
  multi-verb requests expand to one copy per date rather than one per date pair.
- **`EACH` copy keys** are the chosen items in source order, dates omitted:
  `counselor-hours[dylan]`.
- **`GAP` compares block times only**; both tasks are assumed to be on the same date.
- **Instances for hand-written `REQUEST activities.clinics.x`** are created for the target date if no
  offering exists in that block, so a request can run an unlisted clinic.
- **Filter verbs (`FORBID`, plain `PREFER`/`AVOID`) look at the target date only.**
  `PER … BEYOND` windows include published past dates.
- **Ad hoc task names are shared across requests**: two requests using `'break'` refer to
  the same activity.
- **Request scope is gone** (Puppet Master, 2026-09-18). The app used to label each
  request season / session / week / day / pin, derived from the dates it resolved to. It
  was never defined anywhere the Puppet Master could read, and a request naming a date the
  Calendar sheet does not have resolved to no dates at all and so was labelled `season` —
  the widest possible reach for a request that reaches nothing. The dates themselves are
  still a facet (`app/facets.py`), and the date filter asks the same question honestly.
- **Tab names are configurable** under `[tabs]` in `config.toml`, with defaults in
  `config.py`.
- **Lifeguards are positions**, not a count over facilitators: `LG_Required` adds
  `roles.lifeguard` (and `roles.lifeguard_2`) positions requiring `LIFEGUARD` at RAL 5.
- **Recurring dates and staff pairing** (Puppet Master, 2026-09-16), both inside the
  existing grammar. A weekday name now holds every such date of the session rather than
  only the target's week, so `ON EACH dates.monday` is a weekly request; ordinal names
  (`dates.second_thursday`, `dates.last_friday`) were added to the `dates` namespace and existed
  only when the session reaches them. For `FORBID`, `PREFER` and `AVOID`, an `ACROSS`
  alternative holding several staff (`{staff.a AND staff.b}`) matches them as a group: one
  match per instance, whose literal is the AND of each member's presence there, reified
  with `AddMinEquality`. `AND` elsewhere on those verbs is a validation error, and a
  staff-keyed metric cannot score a group. `POSITION_ROLES` is now an alias of `ORDINALS`.
- **`EACH` is allowed on `FORBID`, `PREFER` and `AVOID`** (Puppet Master, 2026-09-16); only
  `ALL` and `n OF` are refused, since those choose rather than filter. `EACH` is not
  redundant there: it splits the declaration, so `PER` counts per person rather than over
  the pool. `STABILITY` is refused on the Requests sheet and left out of the app's
  dropdowns, via `WRITABLE_PRIORITIES`.
- **A quoted task happens only where a TASK selected it** (Puppet Master, 2026-09-16).
  `Compiler` records, per ad hoc slot, the conjunction of clause literals that selects it,
  and `close_adhoc_tasks` then adds `x -> OR(selectors)`, or pins `x` to zero when nothing
  selects it. Without it `DURING` on a `TASK` was a floor rather than a total, so a
  `PREFER` covering more blocks than the task needed bought extra occurrences and
  `PREFER` over a set stopped matching `AVOID` over its complement. Clinics keep the old
  rule, because two offerings of one clinic in different blocks must coexist. A filter
  verb naming a quoted task that no `TASK` asks for is now a `RequestError`, since it
  would otherwise be a silent no-op.
- **Same-day changes** (Puppet Master, 2026-09-16). Rests and RAL penalties are per-date
  data on a new optional `Adjustments` tab, applied to `Staff` at load time as
  `resting_blocks` and a reduced `ral`; `resting` is `all day`, `morning` or `afternoon`,
  with a block belonging to the half it starts in, split at `config.midday`. Someone
  resting all day also drops out of every staff category, so mandatory requests over
  `staff.all` stop demanding anything of them, and `add_structural_constraints` pins a
  resting block's variables to zero in case a request names them directly. `load_dataset` reads the target's own
  published tab as `Dataset.baseline`. `solve(..., same_day=True)` rewards each kept
  baseline assignment in a new `STABILITY` tier between `CLINIC` and `HIGH`, hints those
  variables, and returns a `Change` per staff member and block that differs.
- **One name listing** (`resolve.name_listing`) feeds the `names` command, the app's names
  panel and the editor's completer, built from the same table the resolver validates
  against so the three cannot drift apart. The completer is a `QCompleter` on the Skedge
  box, opened by a `namespace.` prefix. Its model is created once and refilled, because a
  replaced Qt object can be collected inside the solver thread and destroyed off the main
  thread, which crashes the process.
- **No pass can lose a working schedule.** `solve_tiers` snapshots the solution after
  every successful pass (`ResponseProto().solution`, indexed by variable) and returns a
  `TierOutcome.value(var)` lookup instead of the live solver. A tier or cosmetic pass that
  returns anything but OPTIMAL or FEASIBLE keeps the previous snapshot, bounds its tier at
  the score that snapshot achieves, and adds a note. The cosmetic pass also hints the
  assignment booleans from the snapshot so it starts from the known schedule. Only the
  first pass can fail the solve, and it names `time_limit_seconds`. The cosmetic pass
  gets its own short budget, `tidy_seconds` (default 2), because the hint makes the
  better schedule appear at once and the rest of the time goes on proving optimality.
  There was once a second cosmetic pass, dropping assignments nobody asked for; that is
  now a constraint built into the model, so it holds however long the solve takes.
- **Requests have tags** (comma-separated column). Offerings are no longer generated
  inside the solver: **Load offerings** (app button or `load-offerings` command) writes
  one `CLINIC` request per offering to the Requests sheet, tagged `generated`, with ids
  `offering:<date>:<activity>:<block>`. The request names every position of the clinic,
  `AS_ROLE EACH {roles.first + roles.second + …}` (facilitators then lifeguards), so the
  positions the clinic wants are written down rather than implied by the structural
  constraints alone. `EACH` gives each position its own choice of person and so its own
  copy; the copies cannot diverge, because filling one position of an instance fills them
  all. A `Result` lists an outcome per copy (`<request id>[<key>]`); `publish.views.report`
  collapses them to one row per request, keeping the failed copies' keys in the
  description, so an unstaffable clinic is one row rather than one per position.
  Loading first removes the date's generated rows. The solver
  warns when no generated requests exist for the target date. Clinic instances come only
  from `TASK` statements; a `(DBL)` clinic asked for with `DURING ALL` of two blocks is
  one instance.
- **Partial blocks replace display groups** (Puppet Master, 2026-09-16). Blocks are the
  real periods of the day. Every assignment is a CP-SAT interval; a clinic fills its
  block, an ad hoc `FOR` task has a movable start and a variable length inside its
  block, and one `AddNoOverlap` per person replaces the per-block double-booking
  constraints. Several partial tasks may share a block. `n OF` with `FOR` means `n`
  blocks each holding the full duration. `GAP` constrains real start and end times.
  The tidiness pass also minimizes task minutes and offsets from block starts. The Staff
  View joins a block's tasks with ", then " and labels unused time `DYOW/WPs`
  (configurable). The published tab gained `start` and `minutes` columns; the Blocks
  sheet lost `display_group`.
- **The `date` namespace is built from session and week numbers** (2026-09-18). The
  Calendar sheet's `session` column holds a number rather than a name, and a new `week`
  column numbers the days within each session. Every date name is then a span or a name
  inside one: `dates.season.all`, `dates.session_4.all`, `dates.session_4.week_2.all`, and
  `dates.session_4.week_2.monday`. `dates.session_1.all` is the session holding the
  target date and `dates.session_1.week_1.all` the week; the old `dates.session_all`,
  `dates.season.all` and `date.<session name>.all` are gone. A span carries `first`,
  `last`, the weekday sets and the counted occurrences; a week, reaching each weekday
  once, carries the weekday as a single date. An unknown name now suggests the nearest
  real one. The request manager's calendar labels each row `S<session>` / `W<week>` in
  place of the ISO week of the year, and the names panel nests on the dots.
- **Requests belong to groups** (Puppet Master, 2026-09-18). A `groups` column on the
  Requests sheet holds the groups a request is in, comma-separated, and the request
  manager switches between them in a pane of its own: `All requests`, `Ungrouped`, the
  two default groups (Special daily requests, Special weekly requests) and whatever the
  Puppet Master makes. Generated clinic requests are in no group, being too many and
  already marked by their tag. A group lives on its requests, so making one
  declares nothing; the filters narrow within the group rather than replacing it. A
  `requester` column records who asked, as a staff name, checked like any other name.
  Saving a request that says nothing about the date being scheduled asks first.
- **A request block holds any number of statements** (Puppet Master, 2026-09-18). `PREFER`
  no longer has to stand alone: a declaration may mix `REQUEST` and `PREFER` statements, so
  one piece of plain English that needs several statements stays one request, with one
  description, priority and weight, and one binding, condition and set of gaps. The
  compiler splits them: the requirements share the declaration's `sat` literal exactly as
  before and are what the report names, and each preference adds its own objective terms in
  the declaration's tier afterwards, where `_collapse` cannot see them. `PREFER` in a
  `MUST_HAPPEN` declaration is still refused — there is no tier above the hard one to weigh
  it in.
- **Conflicts are found without solving** (Puppet Master, 2026-09-18). `app/conflicts.py`
  reads the resolved copies the store already keeps and turns every *forced* statement into
  a claim on a slot — one staff member, one date, one block. A statement is forced when it
  leaves the solver no choice: `who`, `ON` and `DURING` are all `ALL` (or a single item,
  or an `EACH` copy) and a `DO` names one activity or task. Claims on a slot are then
  compared: free against do, do against not-do, free against not-free, and do against do by
  minutes, since partial tasks share a block. The pane groups them by slot. Nothing that
  leaves the solver room — `ANY n`, `PREFER`, an undated `DURING` — makes a claim, which
  is what keeps the pane quiet enough to be worth reading.
- **A publish is six write requests** (Puppet Master, 2026-09-22). Google counts write
  requests against sixty a minute per person, and a publish sent a clear and an update per
  tab, a format call per bold row, and one each for the merge, the unmerge, the freeze and
  the widths — around forty on the sample day and past sixty on a real one, which is a 429
  in the middle of writing a schedule. `Source.write_many` clears and refills every tab of
  a spreadsheet in two requests (`values_batch_clear`, `values_batch_update`), and `style`
  sends one `batch_update` for the shape of the sheet and one `batch_format` for the
  painting, however many rows and fills it holds. A publish is six requests and a save of a
  request is two. Anything Google refuses for coming too fast (429, 503) waits 5, 15 then
  30 seconds and asks again, which is what its own answer asks for; the publish runs on a
  worker with a panel up, so the waiting is visible and the window keeps painting.
- **A load reads the day; a solve reads the days behind it** (Puppet Master, 2026-09-22).
  What was published on past days is read by the solver alone — `variables.was_free`,
  `was_member`, and patterns counting back over a session — and there is a spreadsheet of
  them per day of the season so far, so a reload in August was spending most of its time
  fetching what the window never looks at. `load_dataset(..., history=False)` reads only
  the target's own day, which is what `baseline` and the Same-day toggle need;
  `read_history` fills in the rest and is called on the way into a solve
  (`RequestStore.for_solving`). The request manager then prefetches it on a worker as soon
  as a load finishes, so Solve is usually already holding what it needs. A prefetch
  installs its answer only if the dataset it was asked about is still the one loaded,
  since a Dataset is frozen and swapping one for another is a single assignment. A reload
  is then flat in the age of the season: about a dozen API calls in August as in June.
- **A read is one request** (Puppet Master, 2026-09-22). `read_many` asked Google what
  tabs a spreadsheet had before asking for the values, which is a second round trip per
  spreadsheet — and a load opens one spreadsheet per published day and per cabin act
  sheet, so by late August that question was half the traffic of a reload. The values are
  now asked for outright and the tab list is fetched only when that fails, which is the
  one time the answer says anything: it is what names the missing tab. `_walk` also
  remembers where each folder of the tree is, prefixes included, so looking back over four
  spans walks `2027/Main Season` once rather than four times, and `discover` runs once per
  root and year. Measured over a modelled season, a reload 70 published days in goes from
  143 API calls to 73.
- **A count goes on the set it counts** (Puppet Master, 2026-09-23). An activity has no
  quantity of its own; the blocks, the dates and the people come in numbers. So a count is
  written directly in front of the set it counts — `DURING EXACTLY 3 blocks.all`,
  `AT_MOST 2 staff.counselor` — rather than after `REQUEST`, far from what it measures, or
  after `DO`, where it read as a quantity of the activity. A length goes on `FOR`, which
  measures within one unit of the blocks: each block when they are taken one at a time,
  their total when they are pooled with `ANY`. `ANY n` is gone: a number is always a
  count, `ANY` is always a pool, and a binding line names exactly which, `EXACTLY n x IN`.
  `NOT FREE` is `BUSY`, which was what it meant; with it gone, a count right of `NOT` is
  refused, since what it could say reads better as a count of what does happen. `ALL` is
  one unit inside every count, which is what lets `ALL {…} DURING EXACTLY 1 blocks.all`
  mean one block together. `DURING` and `ON` still go anywhere; `AS_ROLE`, `FOR`, `WITH`
  and `WITHOUT` go after the verb, and the counts nest by role — who, what, dates,
  blocks — rather than by where they were written. A statement with no count but one
  `AT_LEAST`, or with only one-item counts outside it, still compiles as the requirement it
  always was (`resolve._chosen_once`); anything else is a `Tally`, compiled by
  `Compiler._enforce_levels`, `_reify_levels` and `_tally_miss`, which choose for
  `AT_LEAST`, count reified holds for `AT_MOST`, and do both for `EXACTLY`. A `FOR` over a
  pool lets one of its pieces be cut short (`_allow_partial`). Saved requests are read with
  the grammar they were written in, kept as `grammar_v4.lark`, and rewritten on their next
  load; a count over two pools has no spelling now, and is left for somebody to rewrite.
- **Every set says how it is taken, and CONSECUTIVE is on the blocks** (Puppet Master,
  2026-09-23). A set right of `NOT` or in a pattern is matched rather than chosen, and was
  the one kind of set written with no word in front of it; it now takes `ANY`, with no
  number, and a bare set there is an error. Right of `NOT`, `ALL` means "not all of these
  together", since `NOT` turns round the positive request to its right: `_forbid_together`
  forbids, per person, the conjunction over every combination of the `ALL` items, past
  dates counting as facts. `ANY n` stays an error there, "not in two of them" being a count.
  `CONSECUTIVE` moved again, onto the blocks, which are what is in a row: `DURING ANY 2
  CONSECUTIVE blocks.all` chooses, and a count measured in runs says `DURING ANY
  CONSECUTIVE blocks.all`, where `AT_LEAST 3 CONSECUTIVE s DO …` read as three consecutive
  people. An amount may also follow `DO` when the subject is one person per copy, `s DO
  AT_LEAST 3 …`. Saved requests are rewritten on their next load by `skedge.upgrade`,
  which works on the parse tree, where the old spellings still parse; the requests file
  records the syntax version it is written in, so this happens once.
- **CONSECUTIVE comes right after what it is about** (Puppet Master, 2026-09-22). "Two
  blocks" and "two blocks in a row" differ by one word, and were written two different
  ways: a requirement, and a counted pattern. `DURING ANY n <blocks> CONSECUTIVE` now
  chooses n adjacent blocks in the requirement itself, and the count's `CONSECUTIVE` moves
  from after the pattern, where `ON {…} CONSECUTIVE` read as consecutive dates, to after
  the amount. The old place is still parsed, only to say where it goes now. The compiler
  keeps the block choice's literals and picks exactly one run of adjacent blocks
  (`_adjacent`), each block chosen when the run holding it is, so everything else a
  requirement does with a choice (partners, deferral, `ALL` staff together) is
  unchanged; `_loose` leaves such a choice alone, since which blocks it picks matters.
- **EXCLUDE takes somebody out of the day** (Puppet Master, 2026-09-22). A day off is not
  something to ask the solver for, so `EXCLUDE <who> DO '<label>' [DURING] [ON]` is applied
  rather than compiled. `puppet_strings/exclude.py` resolves every `EXCLUDE` on the sheet
  and returns the Dataset those days leave behind: the blocks go into `resting`, so
  `Dataset.holds` is false and no variable is ever made for them; somebody out for a whole
  day drops out of every staff category, which is what keeps a `MUST_HAPPEN` rule written
  about `staff.all` from asking anything of them and is why the day still solves; and
  `Dataset.excluded` carries the label for the published views. The pass is idempotent and
  runs at the end of `load_dataset`, in `solve()` and in `RequestStore.current`, so a
  Dataset is never seen with somebody in a day they are not in. The compiler drops
  `Exclusion` statements, and a copy holding nothing else is done rather than inactive, so
  the report has nothing to say about it.
- **An update can be an archive** (Puppet Master, 2026-09-21). The Linux release is a
  tar.gz carrying the executable, the icon and an `install.sh` that writes the desktop
  entry. `install()` unpacks an archive (`tarfile`, `filter="data"`), puts the executable
  inside it where the running one is, and refreshes the icon beside it *if one is already
  there*. The desktop entry is left alone: it names that folder, which is where the new
  executable went. A bare executable, which is what Windows and macOS release, is moved
  into place as it is.
- **The staff view is formatted too** (Puppet Master, 2026-09-21). It is the sheet
  everybody at camp opens, most of them looking for one row of it, so `staff_view` returns
  a `Styled` like `clinic_view`: title, bold headings, a frozen corner (two rows and the
  name column), the clinic view's block colours on the headings, banding on every other
  row, wrapped cells and column widths. `Styled` carries `freeze_columns`, `wrap` and
  `column_widths` for it, the last going out as one `updateDimensionProperties` batch.
- **The errors pane holds more than conflicts** (Puppet Master, 2026-09-21). Two requests
  disagreeing is not the only thing that is wrong on paper and invisible until a solve:
  `REQUEST staff.henry DO activities.clinics.aerial_silks DURING blocks.clinic_3` validates
  -- every name in it exists -- and is still impossible if Henry has no checkoff, or if the
  day's Offerings tab does not run aerial silks in clinic 3. `app/errors.py` reads the same
  resolved copies the conflict finder does and asks those two questions of every settled
  `REQUEST … DO`; `app/errors_panel.py` shows conflicts and errors in one tree, since both
  name a slot and the requests to go and look at. Both checks are skipped where the solver
  has a choice, and the offering check is skipped entirely when the day offers nothing at
  all, which is one thing to see to rather than a pane full of the same sentence.
- **Only what must happen can conflict** (Puppet Master, 2026-09-21). `find_conflicts`
  reads the `MUST_HAPPEN` requests and no others. A conflict is a day that cannot be built,
  which takes two promises that cannot both be kept; a softer request crossing another is
  settled by dropping the cheaper one, and the day comes out regardless. Everything below
  `MUST_HAPPEN` is the solver's to weigh and the report's to explain.
- **A drag is welcomed at the door and judged at the table** (Puppet Master, 2026-09-21).
  `GroupList.dragEnterEvent` asks only whether the mime type is a set of requests; which
  row the pointer is over is the move's and the drop's question. A widget that ignores a
  drag enter is told nothing more about that drag, so judging the enter by the row under it
  would leave every group undroppable whenever the pointer crossed into the list over `All
  requests` -- the row at the top, and so the one most drags come in over. `dragMoveEvent`
  calls Qt's own first, which is what starts the scrolling when a drag is held at the edge
  of a list too long to show at once.
- **Keywords read in either case** (Puppet Master, 2026-09-21). Every keyword is its own
  terminal at priority 5, written `/WORD\b/i`, rather than an anonymous string. The `i`
  makes `request` and `REQUEST` one word; the priority puts it above `NAME`, which lower
  case would otherwise be lexed as; and the `\b` keeps it to whole words, so `format` is a
  variable and not `FOR` followed by `mat`. The parser upper-cases what a quantifier or a
  bound token says before comparing it, so the tree holds one spelling however it was
  typed. The highlighter matches case-insensitively for the same reason.
- **A gap reaches back into the published days** (Puppet Master, 2026-09-21). `Made` times
  are counted from midnight on the target date, which puts yesterday at a negative time, and
  a labeled requirement satisfied by a published day contributes that day's real start and
  end (`_was_made`). A `GAP` is therefore a distance between two assignments wherever they
  sit, which is what makes a duration in days worth writing: `GAP first TO second AT_LEAST
  40h` is the forty hours it says. Dates after the target hold nothing and cannot be one end
  of a gap; they are checked on the day they land on, when the other end is published.
- **One clock for the whole solve** (Puppet Master, 2026-09-18). `time_limit_seconds` used
  to be handed to every pass, so a day with five tiers could take five times the setting.
  A `Deadline` now starts in `solve()`, before the model is built, and each pass asks it
  what is left; `tidy_seconds` is held back so the cosmetic placement pass still runs. A
  tier reached with nothing left is skipped with a note rather than given a zero-second
  pass. The note for a tier that ran out of time says what it scored, the best it could not
  rule out, and the gap between them in requests, because the schedule is kept either way
  and the only question worth answering is how much might have been missed.
- **Requests are their own spreadsheet, a tab per session** (Puppet Master, 2026-09-19).
  One tab of the config spreadsheet held every request the season had ever made, and every
  load read all of it: the 2026 season reached 2,024 rows, of which a day in session 4
  needs 552. Requests are now a `Requests` spreadsheet beside Config and Skills, found by
  name like the rest, holding `Season Requests` for what crosses sessions and two tabs per
  span — `S4 Clinics` for what Load offerings writes, `S4 Special` for what was asked of
  that session. A load reads three of them. Which tab a request is on is its `home`, read
  off the tab it came from and written back to it rather than kept in a column, so moving
  a request between sessions is a cut and paste; the editor's `on tab` box is how a new one
  goes to the season's tab instead of the session's. `puppet-strings split-requests` makes
  the spreadsheet out of the old tab, reading each id for the span it names and leaving
  anything it cannot place on the season's tab, where every load goes on reading it.
- **A request sits on one shelf, and its id is not its description** (Puppet Master,
  2026-09-19). A request belonged to any number of groups, ticked off in the editor, which
  made the editor and the pane two places to decide the same thing and made "which group is
  this in" a list rather than an answer. A request now has one `group`, or none. It joins
  the group the pane is showing when it is made, and it is moved by dragging its row onto
  another group's label, so the pane is the only place a group is decided; the editor's
  checklist is gone and a `group` line reports where it sits. Right-clicking a group sets
  the Requests tab its *new* requests are written to, kept in settings.json because a group
  is a label its requests carry and there is no row anywhere to hang a default on. The
  sheet's `groups` column becomes `group`; an old one holding several is read as the first.
  Ids are the next free number on the request's tab — `s4-1`, `season-2` — rather than a
  slug of the description, because a description is for people, is allowed to be empty, and
  gets rewritten the moment somebody words it better, none of which an id may do.
- **A statement may run over several lines, and a bound name may be added into a set**
  (Puppet Master, 2026-09-19). Both came from one request that read perfectly and would not
  compile. A newline is no longer the end of a statement when the next line begins with a
  word that continues one — `DO`, `DURING`, `ON`, `FOR`, a set operator, a closing brace —
  which keeps the grammar LALR by deciding it in the lexer: `_CONTINUES` matches those
  newlines and is ignored, and `_NL` gets the rest. `EACH`, `ANY n` and bare names are
  deliberately not continuations, since each of them can begin a line of its own.
  `ANY 1 v IN {…}` could only be used as a whole selector, so "Charlton with either
  Dylan or Donny" had no natural wording; a bound name can now be added into a set with `+`,
  which resolves to a `Choice` carrying `parts` — the items named here, plus whatever each
  part chose. The solver already spoke in a dict of item to literal, so joining them is
  merging two dicts, and the binding's own literals are what keep it the same person
  throughout. Only `+`, and only `ALL`: `-` and `&` ask what a chosen name is not, and
  taking `n` of such a set is choosing out of something still being chosen.
- **`ANY n`, groups, clauses in any order, and named sets** (2026-09-22). `ANY_n_OF` read
  like nothing else in a declarative language and not like its own `AT_LEAST n`, so it is
  now `ANY n`: an `ANY` keyword and an `INT`. The old spelling is still lexed, only to be
  told `write ANY 1, not ANY_1_OF`. A quantifier may now also go on a part of a set, in
  parentheses: an `ast.Group`. Taken whole, a set's groups are flattened (`ALL`) or
  become `parts` (`ANY n`), so `ALL {x + (ANY 1 s)}` compiles to exactly what the binding
  line did. Under `ANY n` each group is one unit of the choice, held in `Choice.units`: the
  solver gives each a literal alongside the plain items' and chooses the group's own members
  under it. Under `EACH` each group is a copy. Items reached twice are merged with an OR,
  where `parts` used to overwrite. Clauses may now sit anywhere around the subject, verb and
  object, which meant one `clauses` rule used at every gap and one clause rule for
  requirements and patterns alike; the pool-only quantifier rule moved from the grammar to
  the builder, which says why rather than what it expected. The line-continuation rule was
  turned round to match: rather than listing the words that continue a statement,
  `_CONTINUES` lists the few that can begin a line — a statement keyword, a binding, a name
  and a colon — and every other newline is nothing. `name: <set>` is an `ast.Definition`,
  written into the lines that use it by the parser, so nothing downstream knows it was
  there; `name: ANY n <set>` and `name: EACH <set>` are binding lines.
- **Requests live on the Puppet Master's computer; Google Sheets are cached by version**
  (Puppet Master, 2026-09-23). Nobody edits requests outside Puppet Strings and only one
  Puppet Master schedules at a time, so requests are one SQLite file, handed over with
  Export and Import in the Configure pane or `export-requests` / `import-requests`. An import
  is checked whole before it replaces anything, and keeps what it replaced beside the file.
  A fixture folder carries its own `requests.sqlite`. The sheets themselves are kept in a
  cache keyed by spreadsheet id and Drive `version`, which the folder listings a load already
  makes return for free. A listed version is trusted for a minute, about one load, so every
  load lists again without anything having to say when a load begins; anything Puppet
  Strings writes drops its entry at once. Drive can be a moment late counting an edit, which is what Clear in the Configure pane and `--no-cache` are for.
- **Requests are scoped, not filed in lists** (Puppet Master, 2026-09-23). A request was
  filed in a named list — the season's, a session's Special, a day's Clinics — and a load
  read three of them, which meant a list for every session and every day the season had.
  A request now has a scope, a day, a week, a session or the season, kept as the dates it
  covers; a load reads whatever covers its date, one indexed query however long the season
  runs. A new request is scoped to its session and a generated one to its day. Ids are
  unique across the whole file, numbered per scope (`s4-3`, `s4w2-1`, `jun08-1`,
  `season-2`), and a save writes the one request it changed rather than rewriting lists.
  The file's format went from 1 to 2 with no conversion: it was a beta.
- **`ALL` and `EACH`, and dates numbered in digits** (Puppet Master, 2026-09-23). Once
  `ANY_n_OF` became `ANY n`, `ALL_OF` and `EACH_OF` were the only keywords left with an
  `_OF`, so they are `ALL` and `EACH`. The lexer still reads the old spellings as the same
  tokens, so the builder can say `write ALL, not ALL_OF` and `skedge/upgrade.py` can find
  and rewrite them; saved requests are rewritten on their next load (syntax 4). `all` and
  `each` are now keywords and so cannot be a name on their own, though `blocks.all` and
  `all_staff` are untouched: a dotted name is one token, and a keyword ends at `\b`. With
  the `dates` namespace flat, sessions and weeks are named by digit, `dates.session_4.week_2`
  rather than `dates.session_four.week_two`, and a file written the old way is rewritten
  when it is opened.
