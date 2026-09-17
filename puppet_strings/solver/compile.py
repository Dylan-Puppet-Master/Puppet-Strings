"""Compile resolved Skedge declarations into CP-SAT constraints and objective terms.

Each active copy of a REQUEST gets a satisfaction literal `sat`: an assumption when the
request is hard, `weight * sat` in its tier when soft. A copy's constraints are enforced
by `active`, which is `sat` and, when the declaration has a condition, that it applies.
A PREFER adds objective terms only.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date
from itertools import product

from ortools.sat.python import cp_model

from puppet_strings.model import (
    SCAFFOLDED,
    SHADOW,
    SOFT_TIERS,
    TRAINEE_ROLES,
    Assignment,
    Dataset,
    Priority,
    Request,
)
from puppet_strings.skedge import ast
from puppet_strings.skedge.resolve import (
    ALL,
    ANY,
    DEFAULT_POS,
    TRAINEE,
    Choice,
    Condition,
    Count,
    Forbid,
    Pattern,
    Requirement,
    Resolved,
    Score,
)
from puppet_strings.solver.variables import Literal, Slot, Variables

SCALE = 1000
DEFER_BONUS = 1  # for acting early on a deferrable request; sits in the last tier
MINUTES_PER_HOUR = 60
ONE_MATCH = ast.Amount(ast.AT_LEAST, 1, False, DEFAULT_POS)


@dataclass(frozen=True)
class Compiled:
    """One active copy of a REQUEST in the model."""

    id: str
    request: Request
    sat: cp_model.IntVar
    deferred: Literal  # true when the copy is met only by what later dates can still hold


@dataclass(frozen=True)
class Match:
    """One assignment a pattern matches: its fields, its literal and its length."""

    staff: str
    activity: str
    role: str | None
    date: date
    block: str
    literal: Literal
    minutes: int | cp_model.IntVar


@dataclass(frozen=True)
class Made:
    """One assignment a requirement makes on the target date, with its times, for GAP."""

    literal: Literal
    start: int | cp_model.IntVar
    end: int | cp_model.IntVar


@dataclass(frozen=True)
class Row:
    """An assignment the target date may hold, or a past date did."""

    staff: str
    activity: str
    role: str | None
    block: str
    literal: Literal
    minutes: int | cp_model.IntVar
    start: int | cp_model.IntVar


class Compiler:
    """Adds requests to a CpModel. Create one per solve."""

    def __init__(self, model: cp_model.CpModel, variables: Variables, dataset: Dataset) -> None:
        self.model = model
        self.variables = variables
        self.dataset = dataset
        self.terms: dict[Priority, list[tuple[int, cp_model.IntVar]]] = {t: [] for t in SOFT_TIERS}
        self.compiled: list[Compiled] = []
        self.asked_for: dict[Slot, list[Literal]] = {}  # what asks for each quoted-task assignment
        self.shortened: dict[Slot, list[Literal]] = {}  # what gives it a FOR length
        self._same_starts: dict[tuple[int, int], cp_model.IntVar] = {}
        self._published: dict[date, dict[tuple[str, str], list[Row]]] = {}
        self._name = ""
        self._bindings: dict[str, Choice] = {}
        self._shared: dict[str, dict] = {}

    # -- preparation ---------------------------------------------------------------------------

    def prepare(self, copies: list[tuple[Request, Resolved]]) -> None:
        """Create what a positive REQUEST may put on the target date.

        A clinic instance exists only where a `REQUEST … DO` names it. A quoted-task or
        trainee assignment exists where one asks for it, or where a `REQUEST AT_LEAST` or
        `EXACTLY` pattern could match it, partners named by `WITH` included.
        """
        target = self.dataset.target
        for request, copy in copies:
            for st in copy.statements:
                if isinstance(st, Requirement) and st.what is not None and target in st.on.items:
                    self._create(st.who.items, st.what, st.during, st.role, st.with_, request.id)
                if not isinstance(st, Count) or st.prefer or st.amount.bound == ast.AT_MOST:
                    continue
                p = st.pattern
                if p.what is not None and target in p.on.items:
                    self._create(p.who.items, p.what, p.during, p.role, p.with_, request.id)

    def _create(self, staff_ids, what, during, role, partners, source: str) -> None:
        today = [b.id for b in self.dataset.blocks_on(self.dataset.target)]
        blocks = [b for b in (during.items if during else today) if b in today]
        people = set(staff_ids) | (partners or frozenset())
        if isinstance(what, ast.Task):
            for s, b in product(people, blocks):
                self.variables.adhoc(s, what.text, b, source)
            return
        spans = during is not None and during.kind == ALL and len(blocks) == 2
        trainees = role is not None and set(role.items) & {TRAINEE, *TRAINEE_ROLES}
        for activity_id in what.items:
            if spans and self.dataset.activities[activity_id].double:
                ordered = sorted(blocks, key=lambda b: self.dataset.blocks[b].start)
                self.variables.instance(activity_id, tuple(ordered), source)
            else:
                for b in blocks:
                    self.variables.instance(activity_id, (b,), source)
            if trainees:
                for s, b in product(staff_ids, blocks):
                    self.variables.trainee(s, activity_id, b, source)

    # -- one copy ------------------------------------------------------------------------------

    def compile(self, request: Request, copy: Resolved) -> bool:
        """Add one copy. Returns False when it is inactive: its dates all past or all future."""
        if not self._active(copy):
            return False
        self._name = name = f"{request.id}[{copy.key}]" if copy.key else request.id
        self._bindings, self._shared = copy.bindings, {}
        tier = Priority.CLINIC if request.priority.hard else request.priority
        applies = self._applies(copy.condition, name)
        statement = copy.statements[0]
        if isinstance(statement, Score) or (isinstance(statement, Count) and statement.prefer):
            self._prefer(statement, applies, request.weight, tier, name)
            return True
        sat = self.model.NewBoolVar(f"sat:{name}")
        if request.priority.hard:
            self.model.AddAssumption(sat)
        else:
            self.terms[tier].append((round(SCALE * request.weight), sat))
        active = self._all_of([sat, applies], f"active:{name}")
        for var, binding in copy.bindings.items():
            self._shared[var] = self._choose(replace(binding, var=None), sat, f"{name}:{var}")
        deferred: list[Literal] = []
        made: dict[str, list[Made]] = {}
        for st in copy.statements:
            if isinstance(st, Requirement):
                assignments, later = self._require(st, active, name)
                deferred.append(later)
                if st.label:
                    made[st.label] = assignments
            elif isinstance(st, Forbid):
                self._forbid(st, active, name)
            else:
                deferred.append(self._count(st, active, name))
        for gap in copy.gaps:
            self._gap(gap, active, made[gap.first], made[gap.second], name)
        self.compiled.append(
            Compiled(name, request, sat, self._any_of(deferred, f"deferred:{name}"))
        )
        return True

    def _active(self, copy: Resolved) -> bool:
        target = self.dataset.target
        dates = {d for st in copy.statements for d in _dates_of(st)}
        if target in dates:
            return True
        return any(d < target for d in dates) and any(d > target for d in dates)

    def _applies(self, condition: Condition | None, name: str) -> Literal:
        if condition is None:
            return True
        amount = condition.amount or ONE_MATCH
        holds = self._holds(amount, condition.pattern, condition.consecutive, f"if:{name}")
        return _negate(holds) if condition.unless else holds

    # -- PREFER --------------------------------------------------------------------------------

    def _prefer(self, st: Score | Count, applies: Literal, weight: float, tier, name: str) -> None:
        if applies is False:
            return
        if isinstance(st, Score):
            metric = self.dataset.metrics[st.metric]
            sign = 1 if st.maximize else -1
            coefficient = sign * round(SCALE * weight * metric.normalized(st.key))
            if not coefficient:
                return
            for m in self._matches(st.pattern, past=False):
                literal = self._all_of([m.literal, applies], f"score:{name}:{m.staff}:{m.block}")
                if not isinstance(literal, bool):
                    self.terms[tier].append((coefficient, literal))
            return
        miss, bound = self._miss(st.amount, st.pattern, st.consecutive, name)
        if isinstance(miss, int):
            return
        if applies is not True:
            gated = self.model.NewIntVar(0, bound, f"miss:{name}:applies")
            self.model.Add(gated >= miss).OnlyEnforceIf(applies)
            miss = gated
        unit = MINUTES_PER_HOUR if st.amount.duration else 1
        self.terms[tier].append((-round(SCALE * weight / unit), miss))

    # -- requirements --------------------------------------------------------------------------

    def _require(self, st: Requirement, active, name: str) -> tuple[list[Made], Literal]:
        """Every chosen staff member does the thing in every chosen block on every chosen date."""
        target = self.dataset.target
        who = self._choose(st.who, active, f"{name}:staff")
        whats = (
            self._choose(st.what, active, f"{name}:activity")
            if isinstance(st.what, Choice)
            else {st.what: True}
        )
        blocks = self._choose(st.during, active, f"{name}:block")
        roles = self._choose(st.role, active, f"{name}:role") if st.role else {None: True}
        dates = self._choose(st.on, active, f"{name}:date")
        made = []
        for (d, on), (b, on_b), (s, on_s), (w, on_w), (r, on_r) in product(
            dates.items(), blocks.items(), who.items(), whats.items(), roles.items()
        ):
            conds = [active, on, on_b, on_s, on_w, on_r]
            if d < target:
                self._imply(conds, self._was_held(s, w, r, d, b, st))
                continue
            if not self.dataset.holds(s, d, b):
                self._imply(conds, False)
                continue
            if d > target:
                continue  # a later date can hold it, and holds nothing yet
            held, start, end = self._hold(s, w, r, b, st, conds, name)
            self._imply(conds, held)
            self._partners(s, w, b, st, conds, name)
            made.append(Made(self._all_of(conds, f"made:{name}:{s}:{b}"), start, end))
        later = [on for d, on in dates.items() if d > target]
        if not later or st.on.kind != ANY:
            return made, False
        if target in dates:
            self._bonus(dates[target])
        return made, self._any_of(later, f"later:{name}")

    def _hold(self, s: str, w, r, b: str, st: Requirement, conds: list, name: str) -> tuple:
        """The literal for one assignment on the target date, and its start and end."""
        block = self.dataset.blocks[b]
        if w is None:
            return self.variables.free(s, b), block.start_minute, block.end_minute
        if isinstance(w, ast.Task):
            var = self.variables.adhoc(s, w.text, b, name)
            slot = Slot(s, w.text, None, b)
            interval = self.variables.intervals[slot]
            selector = self._all_of(conds, f"asks:{name}:{s}:{b}")
            self.asked_for.setdefault(slot, []).append(selector)
            if st.minutes is not None:
                self._add(interval.size == st.minutes, conds)
                self.shortened.setdefault(slot, []).append(selector)
            return var, interval.start, interval.end
        if r is None:
            held = self._any_of(self.variables.holders(s, w, b), f"holds:{name}:{s}:{w}:{b}")
        elif r == TRAINEE or r in TRAINEE_ROLES:
            role, var = self.variables.trainee(s, w, b, name)
            held = var if r in (TRAINEE, role) else False
        else:
            held = self.variables.lookup(s, w, r, b)
        return held, block.start_minute, block.end_minute

    def _partners(self, s: str, w, b: str, st: Requirement, conds: list, name: str) -> None:
        """WITH: someone else from the set is on the same instance. WITHOUT: nobody is."""
        if st.with_ is not None:
            others = [p for p in st.with_ if p != s]
            if isinstance(w, ast.Task):
                selector = self._all_of(conds, f"asks:{name}:{s}:{b}:with")
                for p in others:
                    self.asked_for.setdefault(Slot(p, w.text, None, b), []).append(selector)
            together = [self._together(s, p, w, self.dataset.target, b) for p in others]
            self._imply(conds, self._any_of(together, f"with:{name}:{s}:{b}"))
        if st.without is not None:
            for p in st.without:
                if p != s:
                    self._imply(conds, _negate(self._together(s, p, w, self.dataset.target, b)))

    def _together(self, s: str, p: str, what, d: date, b: str) -> Literal:
        """Whether `p` holds an assignment on the same instance as `s`, in any role.

        For a quoted task the same instance also means the same start time.
        """
        activity = what.text if isinstance(what, ast.Task) else what
        if d < self.dataset.target:
            mine = list(self.variables.was_member(s, activity, d, b))
            theirs = list(self.variables.was_member(p, activity, d, b))
            if not isinstance(what, ast.Task):
                return bool(theirs)
            return any(a.start == a2.start for a in mine for a2 in theirs)
        if not isinstance(what, ast.Task):
            return self._any_of(
                self.variables.members(p, activity, b), f"member:{p}:{activity}:{b}"
            )
        var = self.variables.lookup(p, activity, None, b)
        if var is False:
            return False
        mine = self.variables.intervals[Slot(s, activity, None, b)]
        theirs = self.variables.intervals[Slot(p, activity, None, b)]
        return self._all_of(
            [var, self._same_start(mine, theirs)], f"together:{s}:{p}:{activity}:{b}"
        )

    def _same_start(self, a, b) -> cp_model.IntVar:
        key = tuple(sorted((a.start.Index(), b.start.Index())))
        if key not in self._same_starts:
            same = self.model.NewBoolVar(f"same_start:{key[0]}:{key[1]}")
            self.model.Add(a.start == b.start).OnlyEnforceIf(same)
            self.model.Add(a.start != b.start).OnlyEnforceIf(same.Not())
            self._same_starts[key] = same
        return self._same_starts[key]

    def _was_held(self, s: str, w, r, d: date, b: str, st: Requirement) -> bool:
        """Whether a published date holds what the requirement asks for."""
        if w is None:
            return self.variables.was_free(s, d, b)
        activity = w.text if isinstance(w, ast.Task) else w
        rows = list(self.variables.was_member(s, activity, d, b))
        if isinstance(w, ast.Task):
            held = any(st.minutes in (None, a.minutes) for a in rows)
        elif r is None:
            held = any(a.role not in TRAINEE_ROLES for a in rows)
        elif r == TRAINEE:
            held = any(a.role in TRAINEE_ROLES for a in rows)
        else:
            held = any(a.role == r for a in rows)
        if not held:
            return False
        return self._partners_were(s, w, d, b, st.with_, st.without)

    def _partners_were(self, s, what, d, b, with_, without) -> bool:
        if with_ is not None and not any(self._together(s, p, what, d, b) for p in with_ if p != s):
            return False
        return without is None or not any(
            self._together(s, p, what, d, b) for p in without if p != s
        )

    def _forbid(self, st: Forbid, active, name: str) -> None:
        """NOT DO: no assignment of a chosen staff member matches. NOT FREE: they are busy."""
        who = self._choose(st.who, active, f"{name}:staff")
        for m in self._matches(st.pattern, past=False):
            self._imply(
                [active, who[m.staff]], m.literal if st.pattern.busy else _negate(m.literal)
            )

    # -- choices -------------------------------------------------------------------------------

    def _choose(self, choice: Choice, active: Literal, name: str) -> dict:
        """One literal per item: `active` itself for ALL, else `n` of them chosen together."""
        if choice.var is not None:
            if choice.var not in self._shared:  # a PREFER, which has no sat
                binding = replace(self._bindings[choice.var], var=None)
                self._shared[choice.var] = self._choose(binding, True, f"{self._name}:{choice.var}")
            return self._shared[choice.var]
        if choice.kind == ALL:
            return dict.fromkeys(choice.items, active)
        chosen = {item: self.model.NewBoolVar(f"{name}:{item}") for item in choice.items}
        total = sum(chosen.values())
        if isinstance(active, bool):
            self.model.Add(total == (choice.n if active else 0))
        else:
            self.model.Add(total == choice.n * active)
        return chosen

    def _pool(self, choice: Choice | None) -> dict:
        """Each item of a pool with the condition for its membership: True, or a shared choice."""
        if choice is None:
            return {}
        if choice.var is None:
            return dict.fromkeys(choice.items, True)
        return self._choose(choice, True, "")

    # -- patterns ------------------------------------------------------------------------------

    def _matches(self, pattern: Pattern, past: bool) -> list[Match]:
        """Every assignment the pattern matches on the target date and, with `past`, before it."""
        target = self.dataset.target
        who = self._pool(pattern.who)
        whats = self._pool(pattern.what) if isinstance(pattern.what, Choice) else None
        blocks = set(pattern.during.items) if pattern.during else None
        roles = self._roles(pattern.role)
        matches = []
        for d in pattern.on.items:
            if d > target or (d < target and not past):
                continue
            on_day = [b for b in self.dataset.blocks_on(d) if blocks is None or b.id in blocks]
            if pattern.what is None:
                for (s, on_s), block in product(who.items(), on_day):
                    state = self._state(s, d, block.id, pattern.busy)
                    literal = self._all_of([state, on_s], f"state:{s}:{d}:{block.id}")
                    matches.append(Match(s, "", None, d, block.id, literal, block.minutes))
                continue
            ids = {b.id for b in on_day}
            activities = [pattern.what.text] if whats is None else list(whats)
            for row in self._rows(d, who, activities):
                if row.block not in ids or (roles is not None and row.role not in roles):
                    continue
                parts = [row.literal, who[row.staff], whats[row.activity] if whats else True]
                parts.append(self._length_is(row, pattern.minutes))
                parts.append(self._partner_matches(row, pattern, d))
                literal = self._all_of(parts, f"match:{row.staff}:{row.activity}:{d}:{row.block}")
                matches.append(
                    Match(row.staff, row.activity, row.role, d, row.block, literal, row.minutes)
                )
        return matches

    def _state(self, s: str, d: date, b: str, busy: bool) -> Literal:
        if d == self.dataset.target:
            return self.variables.busy(s, b) if busy else self.variables.free(s, b)
        free = self.variables.was_free(s, d, b)
        return not free if busy else free

    def _rows(self, d: date, staff_ids, activities) -> Iterator[Row]:
        """The assignments of these people to these activities on a date, from the indexes."""
        if d != self.dataset.target:
            index = self._published_rows(d)
            for key in product(staff_ids, activities):
                yield from index.get(key, ())
            return
        for key in product(staff_ids, activities):
            for slot in self.variables.slots.get(key, ()):
                interval = self.variables.intervals[slot]
                yield Row(
                    slot.staff,
                    slot.activity,
                    slot.role,
                    slot.block,
                    self.variables.x[slot],
                    interval.size,
                    interval.start,
                )

    def _published_rows(self, d: date) -> dict[tuple[str, str], list[Row]]:
        if d not in self._published:
            index: dict[tuple[str, str], list[Row]] = {}
            for a in self.variables.published(d):
                row = Row(a.staff, a.activity, a.role, a.block, True, a.minutes, _minute(a))
                index.setdefault((a.staff, a.activity), []).append(row)
            self._published[d] = index
        return self._published[d]

    def _length_is(self, row: Row, minutes: int | None) -> Literal:
        if minutes is None:
            return True
        if isinstance(row.minutes, int):
            return row.minutes == minutes
        same = self.model.NewBoolVar(f"length:{row.staff}:{row.activity}:{row.block}:{minutes}")
        self.model.Add(row.minutes == minutes).OnlyEnforceIf(same)
        self.model.Add(row.minutes != minutes).OnlyEnforceIf(same.Not())
        return same

    def _partner_matches(self, row: Row, pattern: Pattern, d: date) -> Literal:
        what = pattern.what if isinstance(pattern.what, ast.Task) else row.activity
        if pattern.with_ is not None:
            others = [
                self._together(row.staff, p, what, d, row.block)
                for p in pattern.with_
                if p != row.staff
            ]
            return self._any_of(others, f"with:{row.staff}:{row.activity}:{d}:{row.block}")
        if pattern.without is not None:
            others = [
                self._together(row.staff, p, what, d, row.block)
                for p in pattern.without
                if p != row.staff
            ]
            return _negate(
                self._any_of(others, f"without:{row.staff}:{row.activity}:{d}:{row.block}")
            )
        return True

    @staticmethod
    def _roles(choice: Choice | None) -> set[str] | None:
        if choice is None:
            return None
        roles = set(choice.items)
        if TRAINEE in roles:
            roles |= {SHADOW, SCAFFOLDED}
        return roles

    # -- amounts -------------------------------------------------------------------------------

    def _amount(self, matches: list[Match], duration: bool) -> tuple[list, int]:
        """The matched amount as variable terms and a constant part."""
        terms, constant = [], 0
        for m in matches:
            if m.literal is False:
                continue
            if not duration:
                if m.literal is True:
                    constant += 1
                else:
                    terms.append(m.literal)
            elif isinstance(m.minutes, int):
                if m.literal is True:
                    constant += m.minutes
                else:
                    terms.append(m.minutes * m.literal)
            else:
                terms.append(self._used(m))
        return terms, constant

    def _used(self, m: Match) -> cp_model.IntVar:
        """The minutes a quoted-task assignment takes: its length when made, else 0."""
        bound = self.dataset.blocks[m.block].minutes
        used = self.model.NewIntVar(0, bound, f"used:{m.staff}:{m.activity}:{m.block}")
        self.model.Add(used == m.minutes).OnlyEnforceIf(m.literal)
        self.model.Add(used == 0).OnlyEnforceIf(_negate(m.literal))
        return used

    def _most(self, matches: list[Match], duration: bool) -> int:
        """The largest amount the matches could reach."""
        live = [m for m in matches if m.literal is not False]
        if not duration:
            return len(live)
        return sum(
            m.minutes if isinstance(m.minutes, int) else self.dataset.blocks[m.block].minutes
            for m in live
        )

    def _at_least(self, terms: list, constant: int, n: int, name: str) -> Literal:
        """A literal equivalent to `terms + constant >= n`."""
        if n - constant <= 0:
            return True
        if not terms:
            return False
        literal = self.model.NewBoolVar(name)
        self.model.Add(sum(terms) >= n - constant).OnlyEnforceIf(literal)
        self.model.Add(sum(terms) <= n - constant - 1).OnlyEnforceIf(literal.Not())
        return literal

    def _compare(self, terms: list, constant: int, amount: ast.Amount, name: str) -> Literal:
        """A literal equivalent to the amount's comparison holding."""
        n = amount.value
        if amount.bound == ast.AT_LEAST:
            return self._at_least(terms, constant, n, f"{name}:ge")
        at_most = _negate(self._at_least(terms, constant, n + 1, f"{name}:gt"))
        if amount.bound == ast.AT_MOST:
            return at_most
        return self._all_of(
            [self._at_least(terms, constant, n, f"{name}:ge"), at_most], f"{name}:eq"
        )

    def _holds(self, amount: ast.Amount, pattern: Pattern, consecutive: bool, name: str) -> Literal:
        """A literal equivalent to the condition holding over past dates and today."""
        matches = self._matches(pattern, past=True)
        if consecutive:
            return self._runs_hold(amount, matches, name)
        terms, constant = self._amount(matches, amount.duration)
        return self._compare(terms, constant, amount, name)

    def _windows(self, matches: list[Match]) -> Iterator[list[list[Match]]]:
        """Each run of adjacent blocks one person's matches could fill on one date.

        Blocks are adjacent when they are next to each other on the Blocks sheet; a block
        nothing matches in breaks the run.
        """
        grouped: dict[tuple[str, date], dict[str, list[Match]]] = {}
        for m in matches:
            grouped.setdefault((m.staff, m.date), {}).setdefault(m.block, []).append(m)
        for (_, d), per_block in grouped.items():
            order = [b.id for b in self.dataset.blocks_on(d)]
            for i in range(len(order)):
                for j in range(i, len(order)):
                    if order[j] not in per_block:
                        break
                    yield [per_block[b] for b in order[i : j + 1]]

    def _window(self, window: list[list[Match]], duration: bool, name: str) -> tuple:
        """(present, terms, constant, most): the run is fully matched, and its amount."""
        flat = [m for block in window for m in block]
        blocks = [self._any_of([m.literal for m in block], f"{name}:block") for block in window]
        present = self._all_of(blocks, f"{name}:present")
        terms, constant = self._amount(flat, duration)
        return present, terms, constant, self._most(flat, duration)

    def _runs_hold(self, amount: ast.Amount, matches: list[Match], name: str) -> Literal:
        """AT_LEAST: some run reaches the amount. AT_MOST: no run exceeds it. EXACTLY: both."""
        n = amount.value
        reaching, exceeding = [], []
        for i, window in enumerate(self._windows(matches)):
            present, terms, constant, most = self._window(window, amount.duration, f"{name}:run{i}")
            if amount.bound != ast.AT_MOST and most >= n:
                reaches = self._at_least(terms, constant, n, f"{name}:run{i}:ge")
                reaching.append(self._all_of([present, reaches], f"{name}:run{i}:reaching"))
            if amount.bound != ast.AT_LEAST and most > n:
                exceeds = self._at_least(terms, constant, n + 1, f"{name}:run{i}:gt")
                exceeding.append(self._all_of([present, exceeds], f"{name}:run{i}:exceeding"))
        at_least = self._any_of(reaching, f"{name}:reached")
        at_most = _negate(self._any_of(exceeding, f"{name}:exceeded"))
        if amount.bound == ast.AT_LEAST:
            return at_least
        if amount.bound == ast.AT_MOST:
            return at_most
        return self._all_of([at_least, at_most], f"{name}:exact")

    def _miss(self, amount: ast.Amount, pattern: Pattern, consecutive: bool, name: str) -> tuple:
        """How far the matches are from the amount, as (variable, bound); (0, 0) when fixed."""
        matches = self._matches(pattern, past=True)
        n = amount.value
        if not consecutive:
            terms, constant = self._amount(matches, amount.duration)
            if not terms:
                return 0, 0
            bound = max(n, self._most(matches, amount.duration))
            miss = self.model.NewIntVar(0, bound, f"miss:{name}")
            total = sum(terms) + constant
            if amount.bound != ast.AT_MOST:
                self.model.Add(miss >= n - total)
            if amount.bound != ast.AT_LEAST:
                self.model.Add(miss >= total - n)
            return miss, bound
        gated, bound = [], 0
        for i, window in enumerate(self._windows(matches)):
            present, terms, constant, most = self._window(window, amount.duration, f"{name}:run{i}")
            if present is False:
                continue
            reach = self.model.NewIntVar(0, most, f"{name}:run{i}:amount")
            self._add(reach == sum(terms) + constant, [present])
            self._add(reach == 0, [_negate(present)])
            gated.append(reach)
            bound = max(bound, most)
        if not gated:
            return 0, 0
        bound = max(n, bound)
        miss = self.model.NewIntVar(0, bound, f"miss:{name}")
        if amount.bound != ast.AT_LEAST:
            for reach in gated:
                self.model.Add(miss >= reach - n)
        if amount.bound != ast.AT_MOST:
            best = self.model.NewIntVar(0, bound, f"{name}:best_run")
            self.model.AddMaxEquality(best, gated)
            self.model.Add(miss >= n - best)
        return miss, bound

    def _count(self, st: Count, active: Literal, name: str) -> Literal:
        """A REQUEST with an amount. Returns the literal for its being deferred."""
        p, amount, n = st.pattern, st.amount, st.amount.value
        target = self.dataset.target
        later = [d for d in p.on.items if d > target]
        capacity = 0
        if later and amount.bound != ast.AT_MOST:
            capacity = self._capacity(p, later, amount.duration, st.consecutive)
        matches = self._matches(p, past=True)
        if amount.bound != ast.AT_MOST:
            self._ask_for(matches, p, active)
        if st.consecutive:
            now = self._runs_hold(amount, matches, name)
            if capacity < n:
                self._imply([active], now)
                return False
            if amount.bound == ast.EXACTLY:
                upper = replace(amount, bound=ast.AT_MOST)
                self._imply([active], self._runs_hold(upper, matches, f"{name}:upper"))
            self._bonus(now)
            return _negate(now)
        terms, constant = self._amount(matches, amount.duration)
        if amount.bound != ast.AT_MOST:
            self._imply(
                [active], self._at_least(terms, constant, n - capacity, f"{name}:reachable")
            )
        if amount.bound != ast.AT_LEAST:
            self._imply([active], _negate(self._at_least(terms, constant, n + 1, f"{name}:gt")))
        if not capacity:
            return False
        reached = self._at_least(terms, constant, n, f"{name}:reached")
        progress = self.model.NewIntVar(0, n, f"{name}:progress")
        self.model.Add(progress <= sum(terms) + constant)
        self._bonus(progress)
        return _negate(reached)

    def _ask_for(self, matches: list[Match], p: Pattern, active: Literal) -> None:
        """A quoted-task assignment an AT_LEAST or EXACTLY pattern matches may exist for it."""
        if not isinstance(p.what, ast.Task):
            return
        for m in matches:
            if m.date != self.dataset.target:
                continue
            people = {m.staff, *(p.with_ or ())}
            for s in people:
                self.asked_for.setdefault(Slot(s, m.activity, None, m.block), []).append(active)

    def _bonus(self, term) -> None:
        """The incentive to act early on a deferrable request, below every tier's requests."""
        if not isinstance(term, bool):
            self.terms[Priority.LOW].append((DEFER_BONUS, term))

    def _capacity(self, p: Pattern, later: list[date], duration: bool, consecutive: bool) -> int:
        """What later dates can still hold: every block, or the longest run of adjacent blocks."""
        best, total = 0, 0
        for d, s in product(later, p.who.items):
            run = 0
            for block in self.dataset.blocks_on(d):
                in_pool = p.during is None or block.id in p.during.items
                if not in_pool or not self.dataset.holds(s, d, block.id):
                    run = 0
                    continue
                amount = block.minutes if duration else 1
                total += amount
                run += amount
                best = max(best, run)
        return best if consecutive else total

    # -- GAP -----------------------------------------------------------------------------------

    def _gap(self, gap: ast.Gap, active, first: list[Made], second: list[Made], name: str) -> None:
        """Every `first` ends before any `second` starts, and the gap between meets the bound."""
        bound, minutes = gap.amount.bound, gap.amount.value
        close = []
        for i, (a, b) in enumerate(product(first, second)):
            conds = [active, a.literal, b.literal]
            between = b.start - a.end
            self._add(between >= 0, conds)
            if bound != ast.AT_MOST:
                self._add(between >= minutes, conds)
            if bound != ast.AT_LEAST:
                near = self.model.NewBoolVar(f"gap:{name}:{gap.first}:{gap.second}:{i}")
                self._add(between <= minutes, [near])
                self._imply([near], a.literal)
                self._imply([near], b.literal)
                close.append(near)
        if bound == ast.AT_LEAST:
            return
        any_first = self._any_of([m.literal for m in first], f"gap:{name}:{gap.first}:any")
        any_second = self._any_of([m.literal for m in second], f"gap:{name}:{gap.second}:any")
        self._imply([active, any_first, any_second], self._any_of(close, f"gap:{name}:close"))

    # -- closing -------------------------------------------------------------------------------

    def close_adhoc_tasks(self) -> None:
        """A quoted-task assignment exists only where something asks for it. Call once.

        It is as long as its block unless a request with `FOR` selects it.
        """
        for slot, var in self.variables.x.items():
            if slot.activity in self.dataset.activities:
                continue
            asked = [s for s in self.asked_for.get(slot, []) if s is not False]
            if not any(s is True for s in asked):
                self.model.AddBoolOr([var.Not(), *asked])
            shortened = [s for s in self.shortened.get(slot, []) if s is not False]
            if any(s is True for s in shortened):
                continue
            interval = self.variables.intervals[slot]
            unless = [var, *(s.Not() for s in shortened)]
            self.model.Add(interval.size == interval.block.minutes).OnlyEnforceIf(unless)

    # -- literals ------------------------------------------------------------------------------

    def _add(self, constraint, conds: list) -> None:
        """Add a constraint enforced when every condition holds, with constants folded."""
        if any(c is False for c in conds):
            return
        literals = [c for c in conds if c is not True]
        if isinstance(constraint, bool):
            if not constraint:
                self._imply(literals, False)
            return
        added = self.model.Add(constraint)
        if literals:
            added.OnlyEnforceIf(literals)

    def _imply(self, conds: list, consequence: Literal) -> None:
        """Conditions all true -> consequence, with constants folded."""
        if consequence is True or any(c is False for c in conds):
            return
        clause = [c.Not() for c in conds if c is not True]
        if consequence is not False:
            clause.append(consequence)
        self.model.AddBoolOr(clause)

    def _any_of(self, literals: list, name: str) -> Literal:
        """A literal true when any of these are, with constants folded."""
        if any(v is True for v in literals):
            return True
        real = _distinct([v for v in literals if v is not False])
        if len(real) < 2:
            return real[0] if real else False
        var = self.model.NewBoolVar(name)
        self.model.AddBoolOr(real).OnlyEnforceIf(var)
        self.model.AddBoolAnd([v.Not() for v in real]).OnlyEnforceIf(var.Not())
        return var

    def _all_of(self, literals: list, name: str) -> Literal:
        """A literal true when all of these are, with constants folded."""
        if any(v is False for v in literals):
            return False
        real = _distinct([v for v in literals if v is not True])
        if len(real) < 2:
            return real[0] if real else True
        var = self.model.NewBoolVar(name)
        self.model.AddBoolAnd(real).OnlyEnforceIf(var)
        self.model.AddBoolOr([v.Not() for v in real]).OnlyEnforceIf(var.Not())
        return var


def _distinct(literals: list) -> list:
    seen: dict[tuple[int, bool], object] = {}
    for literal in literals:
        seen.setdefault((literal.Index(), _is_negated(literal)), literal)
    return list(seen.values())


def _is_negated(literal) -> bool:
    return not isinstance(literal, cp_model.IntVar)


def _negate(literal: Literal) -> Literal:
    if isinstance(literal, bool):
        return not literal
    return literal.Not()


def _minute(a: Assignment) -> int:
    return a.start.hour * 60 + a.start.minute


def _dates_of(statement) -> tuple[date, ...]:
    if isinstance(statement, Requirement):
        return statement.on.items
    return statement.pattern.on.items
