"""The two printable views of a schedule, and the report, as tables."""

from puppet_strings.config import DEFAULT_REMAINDER
from puppet_strings.model import (
    LIFEGUARD_ROLES,
    POSITION_ROLES,
    SCAFFOLDED,
    SHADOW,
    TRAINEE_ROLES,
    Assignment,
    Block,
    Dataset,
    minute_to_time,
)
from puppet_strings.publish.palette import (
    BANDING,
    BLOCK_COLOURS,
    CATEGORY_COLOURS,
    NAME_COLUMN,
    colour,
)
from puppet_strings.sheets.source import Fill, Styled, Table
from puppet_strings.solver.result import RequestOutcome, Result

AVAILABLE = "Available"
FREE = "free"
PLAYSTATION = "playstation"
ANY_CLINIC = "any_clinic"
HEADINGS_ROW = 1  # row 0 is the title; row 1 names the blocks


STAFF_COLUMN_WIDTH = 150  # a name; the block columns hold a sentence
BLOCK_COLUMN_WIDTH = 190


def staff_view(
    dataset: Dataset, assignments: tuple[Assignment, ...], remainder: str = DEFAULT_REMAINDER
) -> Styled:
    """One row per staff member at camp, one column per block.

    A block's cell lists the person's tasks in time order, joined by ", then ". Time in the
    block that no task covers is labeled with `remainder` (DYOW/WPs by default).

    Only the staff the span's Staff Categories sheet names get a row. The Skills sheet keeps
    everyone who has ever worked here, and a schedule listing people who are not at camp
    this session is a schedule people have to read past.

    It is read by everybody at camp, most of them looking for one row of it, so it is dressed
    for that: the day it is says so at the top, the names and the headings stay on screen as
    the grid is scrolled, each block's column carries the colour it has on the clinic view,
    and every other row is banded so that an eye crossing ten columns stays on one person.
    """
    blocks = dataset.blocks_on(dataset.target)
    rows: Table = [[_title(dataset)], ["Staff"] + [_label(b.id) for b in blocks]]
    by_staff_block: dict[tuple[str, str], list[Assignment]] = {}
    for a in assignments:
        by_staff_block.setdefault((a.staff, a.block), []).append(a)
    for staff_id in sorted(dataset.at_camp, key=lambda s: dataset.staff[s].name):
        row = [dataset.staff[staff_id].name]
        for block in blocks:
            here = sorted(by_staff_block.get((staff_id, block.id), []), key=lambda a: a.start)
            row.append(_cell(dataset, staff_id, block, here, remainder))
        rows.append(row)
    columns = len(blocks) + 1
    return Styled(
        rows,
        title_span=columns,
        bold_rows=(0, HEADINGS_ROW),
        freeze_rows=2,
        freeze_columns=1,  # the names, so a row is still somebody's at the far end of the day
        wrap=True,
        column_widths=(
            (0, 0, STAFF_COLUMN_WIDTH),
            (1, len(blocks), BLOCK_COLUMN_WIDTH),
        ),
        fills=_staff_fills(len(rows), len(blocks)),
    )


def _staff_fills(rows: int, blocks: int) -> tuple[Fill, ...]:
    """The headings in their block's colour, the names in their own, and a band per row."""
    fills = [Fill(HEADINGS_ROW, c + 1, colour(BLOCK_COLOURS, c)) for c in range(blocks)]
    fills.append(Fill(HEADINGS_ROW, 0, NAME_COLUMN))
    for row in range(HEADINGS_ROW + 1, rows):
        fills.append(Fill(row, 0, NAME_COLUMN))
        if (row - HEADINGS_ROW) % 2 == 0:
            fills += [Fill(row, c + 1, BANDING) for c in range(blocks)]
    return tuple(fills)


def _cell(
    dataset: Dataset, staff_id: str, block: Block, here: list[Assignment], remainder: str
) -> str:
    excused = dataset.excused(staff_id, block.id)
    if excused:
        return excused  # an EXCLUDE: they are not at camp for this block, and it says so
    if not here:
        return AVAILABLE if block.id == PLAYSTATION else ""
    segments = []
    cursor = block.start_minute
    for a in here:
        if _minute(a.start) > cursor:
            segments.append(remainder)
        segments.append(_describe(dataset, a))
        cursor = a.end_minute
    if cursor < block.end_minute:
        segments.append(remainder)
    return ", then ".join(segments)


def _minute(t) -> int:
    return t.hour * 60 + t.minute


TRAINEE_LABELS = {SHADOW: "Shadow", SCAFFOLDED: "Scaffold"}


def clinic_view(
    dataset: Dataset, assignments: tuple[Assignment, ...], remainder: str = DEFAULT_REMAINDER
) -> Styled:
    """The printed clinic schedule: one column per clinic block.

    Clinics come first, grouped by category in Clinic_Data order, one row per position
    holder (1st above 2nd) and a Shadow or Scaffold row for trainees. Then every other
    task, one name per row, and finally `remainder` listing staff with nothing in that
    block.

    Nothing has a row unless somebody is on it in one of these blocks. A clinic that was
    offered and could not be staffed, or that a request deferred to another day, is not
    happening today, and a row of empty cells on the schedule is a clinic people go looking
    for. The Report is where a clinic that was asked for and did not run is named.

    Two sets of colours make the grid readable on paper: each clinic block column has its
    own, on its heading and on every cell of it that says something, and each category on
    Clinic_Data has its own, on the name of every clinic in it. A category is a run of
    rows down the left-hand column, so one colour marks where it starts and ends.
    """
    clinic_ids = dataset.block_categories.get(ANY_CLINIC, frozenset())
    blocks = [b.id for b in dataset.blocks_on(dataset.target) if b.id in clinic_ids]
    names = {s: dataset.staff[s].name for s in dataset.staff}
    rows: Table = [[_title(dataset)], ["Clinic"] + [_label(b) for b in blocks]]
    bold = [0, 1]
    by_activity_block: dict[tuple[str, str], list[Assignment]] = {}
    for a in assignments:
        if a.block in blocks:
            by_activity_block.setdefault((a.activity, a.block), []).append(a)

    # from the assignments in these blocks, so that a row always has a name on it
    shown = {activity for activity, _ in by_activity_block if activity in dataset.activities}
    labels: list[Fill] = []  # the left-hand column, one colour per category
    categories = dict.fromkeys(a.category for a in dataset.activities.values())
    for index, category in enumerate(categories):
        activities = [
            a for a in dataset.activities.values() if a.category == category and a.id in shown
        ]
        if not activities:
            continue
        shade = colour(CATEGORY_COLOURS, index)
        for activity in activities:
            bold.append(len(rows))
            labels.append(Fill(len(rows), 0, shade))
            holders = {
                b: [
                    names[a.staff]
                    for a in sorted(
                        _holders(by_activity_block.get((activity.id, b), [])),
                        key=lambda a: _role_order(a.role),
                    )
                ]
                for b in blocks
            }
            rows += _stack(activity.name, holders, blocks)
            for role, label in TRAINEE_LABELS.items():
                trainees = {
                    b: [
                        names[a.staff]
                        for a in by_activity_block.get((activity.id, b), [])
                        if a.role == role
                    ]
                    for b in blocks
                }
                if any(trainees.values()):
                    labels.append(Fill(len(rows), 0, shade))  # still that clinic's category
                    rows += _stack(label, trainees, blocks)
        rows.append([])

    tasks = dict.fromkeys(a for a, _ in by_activity_block if a not in dataset.activities)
    for task in tasks:
        bold.append(len(rows))
        people = {b: [names[a.staff] for a in by_activity_block.get((task, b), [])] for b in blocks}
        rows += _stack(task, people, blocks)
    if tasks:
        rows.append([])

    here = sorted(dataset.at_camp, key=lambda s: names[s])
    for label, people in _excused(dataset, here, blocks).items():
        bold.append(len(rows))
        rows += _stack(label, people, blocks)

    bold.append(len(rows))
    busy = {(a.staff, a.block) for a in assignments}
    # Free means free and here: somebody this span does not have is not spare, and somebody
    # an EXCLUDE took out of the block is not spare either -- they are already accounted for.
    free = {
        b: [names[s] for s in here if (s, b) not in busy and not dataset.excused(s, b)]
        for b in blocks
    }
    rows += _stack(remainder, free, blocks)
    return Styled(
        rows,
        title_span=len(blocks) + 1,
        bold_rows=tuple(bold),
        freeze_rows=2,
        fills=tuple(labels) + _block_fills(rows, len(blocks)),
    )


def _excused(dataset: Dataset, here: list[str], blocks: list[str]) -> dict[str, dict[str, list]]:
    """The people an EXCLUDE took out of these blocks, a row per label it wrote.

    They are neither on a clinic nor free, so they are their own group: `offsite` reads
    beside the clinics the way `DYOW/WPs` does, and somebody looking for a name finds it.
    """
    names = {s: dataset.staff[s].name for s in dataset.staff}
    labels = dict.fromkeys(
        dataset.excused(s, b) for b in blocks for s in here if dataset.excused(s, b)
    )
    return {
        label: {b: [names[s] for s in here if dataset.excused(s, b) == label] for b in blocks}
        for label in labels
    }


def _block_fills(rows: Table, count: int) -> tuple[Fill, ...]:
    """Each clinic block column's colour: on its heading, and on every cell that says something.

    The heading is always coloured, so the top of the sheet says which colour is which
    block; below it an empty cell stays white, which is what makes a clinic that runs in
    one block and not another, or a block somebody is free in, show up as a gap.
    """
    return tuple(
        Fill(r, c, colour(BLOCK_COLOURS, c - 1))
        for r, row in enumerate(rows)
        if r >= HEADINGS_ROW
        for c in range(1, count + 1)
        if r == HEADINGS_ROW or (c < len(row) and row[c])
    )


def _title(dataset: Dataset) -> str:
    """Where the day sits: which day of its span, which span, and which weekday."""
    day = dataset.session_dates.index(dataset.target) + 1
    today = dataset.calendar[dataset.target]
    span = dataset.this_span.name
    return f"Day {day}, {span} Week {today.week} - {dataset.target:%A}"


def _holders(here: list[Assignment]) -> list[Assignment]:
    return [a for a in here if a.role not in TRAINEE_ROLES]


def _stack(label: str, per_block: dict[str, list[str]], blocks: list[str]) -> Table:
    """Rows for one label: the label once, then one name per row in each block's column."""
    height = max([len(v) for v in per_block.values()] + [1])
    rows = []
    for i in range(height):
        cells = [label if i == 0 else ""]
        cells += [per_block[b][i] if i < len(per_block[b]) else "" for b in blocks]
        rows.append(cells)
    return rows


def changes_view(dataset: Dataset, result: Result) -> Table:
    """One row per staff member and block that a same-day re-solve moved."""
    rows: Table = [["Staff", "Block", "Was", "Now"]]
    for change in result.changes:
        rows.append(
            [
                dataset.staff[change.staff].name,
                _label(change.block),
                _held(dataset, change.before),
                _held(dataset, change.after),
            ]
        )
    return rows


def _held(dataset: Dataset, assignments: tuple[Assignment, ...]) -> str:
    return ", ".join(_timed(dataset, a) for a in assignments) or FREE


def _timed(dataset: Dataset, a: Assignment) -> str:
    """The task, with its times when it takes only part of its block."""
    text = _describe(dataset, a)
    if a.minutes >= dataset.blocks[a.block].minutes:
        return text
    return f"{text} {a.start:%H:%M}-{minute_to_time(a.end_minute):%H:%M}"


def report(result: Result) -> Table:
    """Unsatisfied, deferred and inactive requests, conflicts, and the solver's notes.

    One row per request, not per copy. `EACH_OF` splits a request into a copy per date,
    per block or per clinic position, and a clinic nobody can staff fails every one of its
    positions at once; three rows saying the same thing bury the rest of the report. The
    `request` column names the request as the Requests sheet has it, so it can be looked
    up, and the keys of the copies that failed follow the description, so a request that
    failed on one Friday out of four still says which.
    """
    rows: Table = [["status", "request", "priority", "description"]]
    listed = (
        ("unsatisfied", result.unsatisfied),
        ("deferred", result.deferred),
        ("inactive", result.inactive),
    )
    for status, outcomes in listed:
        for outcome, keys in _per_request(outcomes):
            rows.append(
                [
                    status,
                    _request_of(outcome.id),
                    outcome.priority.value,
                    _and_keys(outcome.description, keys),
                ]
            )
    for request_id, keys in _per_request_id(result.conflicts):
        rows.append(["conflict", request_id, "MUST_HAPPEN", _and_keys("infeasible together", keys)])
    for note in result.notes:
        rows.append(["note", "", "", note])
    return rows


def _per_request(
    outcomes: tuple[RequestOutcome, ...],
) -> list[tuple[RequestOutcome, list[str]]]:
    """The outcomes one per request, in the order the requests first appear, with their keys."""
    grouped: dict[str, tuple[RequestOutcome, list[str]]] = {}
    for outcome in outcomes:
        request_id, key = _split(outcome.id)
        _, keys = grouped.setdefault(request_id, (outcome, []))
        if key:
            keys.append(key)
    return list(grouped.values())


def _per_request_id(ids: tuple[str, ...]) -> list[tuple[str, list[str]]]:
    """The same, for conflicts, which are ids rather than outcomes."""
    grouped: dict[str, list[str]] = {}
    for copy_id in ids:
        request_id, key = _split(copy_id)
        keys = grouped.setdefault(request_id, [])
        if key:
            keys.append(key)
    return list(grouped.items())


def _split(copy_id: str) -> tuple[str, str]:
    """A copy's id as the request it came from and the key of the copy, if it has one.

    A copy is named `<request id>[<key>]`, and a key is the `EACH_OF` items that made it,
    which can itself hold a comma: `weekly[2026-09-18, clinic_1]`.
    """
    if not copy_id.endswith("]") or "[" not in copy_id:
        return copy_id, ""
    request_id, key = copy_id[:-1].rsplit("[", 1)
    return request_id, key


def _request_of(copy_id: str) -> str:
    return _split(copy_id)[0]


def _and_keys(description: str, keys: list[str]) -> str:
    """The description, then the copies it is about; `; ` because a key may hold a comma."""
    return f"{description} ({'; '.join(keys)})" if keys else description


def _label(block_id: str) -> str:
    return block_id.replace("_", " ").title()


def _describe(dataset: Dataset, a: Assignment) -> str:
    if a.activity not in dataset.activities:
        return a.activity
    name = dataset.activities[a.activity].name
    if a.role in TRAINEE_ROLES or a.role in LIFEGUARD_ROLES:
        return f"{name} ({a.role})"
    if len(dataset.activities[a.activity].positions) > 1:
        return f"{name} ({_ordinal(a.role)})"
    return name


def _role_order(role: str | None) -> int:
    ordered = POSITION_ROLES + LIFEGUARD_ROLES + TRAINEE_ROLES
    return ordered.index(role) if role in ordered else len(ordered)


def _ordinal(role: str | None) -> str:
    return {"first": "1st", "second": "2nd", "third": "3rd"}.get(role or "", role or "")
