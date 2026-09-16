"""Compile resolved Skedge statements into CP-SAT constraints and objective terms.

Each expanded copy of a request gets a satisfaction literal `sat`. TASK, FORBID and GAP add
constraints enforced by `sat`; PREFER and AVOID add objective terms. Hard requests make
`sat` an assumption; soft ones put `weight * sat` in their tier.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from itertools import product

from ortools.sat.python import cp_model

from puppet_strings.model import SCAFFOLDED, SHADOW, SOFT_TIERS, Dataset, Priority, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.resolve import TRAINEE, Choice, Resolved, Statement
from puppet_strings.solver.variables import Literal, Slot, Variables

SCALE = 1000
DEFER_BONUS = 1


@dataclass(frozen=True)
class Compiled:
    """One expanded copy of a request in the model."""

    id: str
    request: Request
    sat: cp_model.IntVar
    deferrable: bool
    constrained: bool

    @property
    def enforced(self) -> bool:
        """Whether `sat` must be true: hard and not deferrable."""
        return self.request.priority.hard and not self.deferrable

    @property
    def tier(self) -> Priority:
        """The tier whose objective this copy's terms join."""
        return Priority.CLINIC if self.request.priority.hard else self.request.priority


@dataclass(frozen=True)
class Matched:
    """One assignment a filter verb matched: its fields and its literal."""

    staff: str
    activity: str
    role: str | None
    date: date
    block: str
    literal: Literal


class Compiler:
    """Adds requests to a CpModel. Create one per solve."""

    def __init__(self, model: cp_model.CpModel, variables: Variables, dataset: Dataset) -> None:
        self.model = model
        self.variables = variables
        self.dataset = dataset
        self.terms: dict[Priority, list[tuple[int, cp_model.IntVar]]] = {t: [] for t in SOFT_TIERS}
        self.compiled: list[Compiled] = []

    def prepare(self, copies: list[tuple[Request, Resolved]]) -> None:
        """Create instances for every activity a TASK may run on the target date.

        A (DBL) clinic asked for with `DURING ALL` of two blocks is one instance spanning
        both, so the same staff hold it throughout.
        """
        for request, copy in copies:
            for statement in copy.statements:
                if statement.verb != "TASK" or not isinstance(statement.target, Choice):
                    continue
                if statement.role or self.dataset.target not in statement.on.items:
                    continue
                blocks = sorted(statement.during.items, key=lambda b: self.dataset.blocks[b].start)
                spans = statement.during.quantifier.kind == "ALL" and len(blocks) == 2
                for activity_id in statement.target.items:
                    if spans and self.dataset.activities[activity_id].double:
                        self.variables.instance(activity_id, tuple(blocks), request.id)
                        continue
                    for block in blocks:
                        self.variables.instance(activity_id, (block,), request.id)

    def compile(self, request: Request, copy: Resolved) -> Compiled | None:
        """Add one expanded copy of a request. Returns None when it has nothing to decide."""
        target = self.dataset.target
        task_dates = [d for s in copy.statements if s.verb == "TASK" for d in s.on.items]
        if task_dates and target not in task_dates:
            return None
        if not task_dates and not any(target in s.on.items for s in copy.statements):
            return None
        deferrable = bool(task_dates) and max(task_dates) > target
        constrained = any(s.verb in ("TASK", "FORBID") for s in copy.statements)
        name = f"{request.id}[{copy.key}]" if copy.key else request.id
        sat = self.model.NewBoolVar(f"sat:{name}")
        compiled = Compiled(name, request, sat, deferrable, constrained)
        if not constrained:
            self.model.Add(sat == 1)  # PREFER and AVOID score their matches, not `sat`
        elif compiled.enforced:
            self.model.AddAssumption(sat)
        elif deferrable:
            self.terms[compiled.tier].append((DEFER_BONUS, sat))
        else:
            self.terms[compiled.tier].append((round(SCALE * request.weight), sat))
        labels: dict[str, tuple[Statement, dict, dict]] = {}
        for statement in copy.statements:
            if statement.verb == "TASK":
                across, chosen_blocks = self._task(statement, sat, name, deferrable, compiled.tier)
                if statement.label:
                    labels[statement.label] = (statement, across, chosen_blocks)
            elif statement.verb == "FORBID":
                self._forbid(statement, sat)
            else:
                self._score(statement, request.weight, compiled.tier)
        for gap in copy.gaps:
            self._gap(gap, sat, name, labels[gap.first], labels[gap.second])
        self.compiled.append(compiled)
        return compiled

    # -- TASK --------------------------------------------------------------------------------

    def _task(self, st: Statement, sat, name: str, deferrable: bool, tier: Priority):
        """Returns the staff choice literals and the target-date block literals."""
        across = self._choose(st.across, sat, f"{name}:staff")
        roles = self._choose(st.role, sat, f"{name}:role") if st.role else {None: sat}
        targets = (
            self._choose(st.target, sat, f"{name}:activity")
            if isinstance(st.target, Choice)
            else {st.target: sat}
        )
        target = self.dataset.target
        if st.minutes is None:
            on = self._choose(st.on, sat, f"{name}:date")
            chosen_blocks = self._choose(st.during, sat, f"{name}:block")
            slots = {(d, b): [on[d], chosen_blocks[b]] for d in on for b in chosen_blocks}
        else:
            slots = self._for_slots(st, sat, name, deferrable, tier, across)
            chosen_blocks = {b: lits[0] for (d, b), lits in slots.items() if d == target}
        for (day, block), conditions in slots.items():
            for target, target_lit in targets.items():
                for staff_id, staff_lit in across.items():
                    for role, role_lit in roles.items():
                        conds = conditions + [target_lit, staff_lit, role_lit]
                        self._require(st, target, staff_id, role, day, block, conds, name)
                if isinstance(target, str) and st.role is None:
                    pool = set(across)
                    for outside in self.variables.holders_outside(target, day, block, pool):
                        self._imply(conditions + [target_lit], _negate(outside))
        return across, chosen_blocks

    def _require(self, st: Statement, target, staff_id, role, day, block, conds, name) -> None:
        if isinstance(target, ast.Free):
            self._imply(conds, self.variables.is_free(staff_id, day, block))
        elif isinstance(target, ast.AdHoc):
            if day != self.dataset.target:
                self._imply(conds, self.variables.lookup(staff_id, target.text, None, day, block))
                return
            interval = self.variables.adhoc_interval(staff_id, target.text, block, name)
            self._imply(conds, self.variables.adhoc(staff_id, target.text, block, name))
            if st.minutes is None:  # without FOR, the task fills the block
                self.model.Add(interval.size == interval.block.minutes).OnlyEnforceIf(conds)
        elif st.role is None:
            self._imply(conds, self.variables.filled(target, day, block))
        elif role == TRAINEE:
            if day == self.dataset.target:
                self._imply(conds, self.variables.trainee(staff_id, target, block, name))
            else:
                done = any(
                    self.variables.lookup(staff_id, target, r, day, block)
                    for r in (SHADOW, SCAFFOLDED)
                )
                self._imply(conds, done)
        else:
            self._imply(conds, self.variables.lookup(staff_id, target, role, day, block))

    def _for_slots(self, st: Statement, sat, name: str, deferrable, tier, across) -> dict:
        """`FOR`: a literal per (date, block) plus the minutes the task takes in each.

        Without a quantifier the minutes add up to the duration across any blocks, with
        blocks used partially. `n OF` means `n` blocks each holding the full duration. A
        labeled task (used in a GAP) takes exactly one block. `CONTINUOUS` uses adjacent
        blocks, filling all but the last.
        """
        target = self.dataset.target
        partial = isinstance(st.target, ast.AdHoc)
        y = {
            (d, b): self.model.NewBoolVar(f"{name}:y:{d}:{b}")
            for d in st.on.items
            for b in st.during.items
            if b in {blk.id for blk in self.dataset.blocks_on(d)}
        }
        contributions = []
        for (day, block), chosen in y.items():
            length = self.dataset.blocks[block].minutes
            minutes = self.model.NewIntVar(0, length, f"{name}:minutes:{day}:{block}")
            self.model.Add(minutes <= length * chosen)
            contributions.append(minutes)
            if not partial:
                continue  # a clinic fills its block; the block's length counts when chosen
            text = st.target.text
            for staff_id, staff_lit in across.items():
                if day == target:
                    interval = self.variables.adhoc_interval(staff_id, text, block, name)
                    self.model.Add(minutes <= interval.size).OnlyEnforceIf([chosen, staff_lit])
                    if st.during.quantifier.kind == "OF":
                        size_needed = interval.size >= st.minutes
                        self.model.Add(size_needed).OnlyEnforceIf([chosen, staff_lit])
                else:
                    done = self.variables.past_minutes(staff_id, text, day, block)
                    self.model.Add(minutes <= done).OnlyEnforceIf([chosen, staff_lit])
        if st.during.quantifier.kind == "OF":
            self.model.Add(sum(y.values()) == st.during.quantifier.n * sat)
        self.model.Add(sum(contributions) >= st.minutes).OnlyEnforceIf(sat)
        if st.label and not st.continuous:
            self.model.Add(sum(y.values()) == sat)
        if st.continuous:
            self._continuous_runs(st, y, sat, name, across)
        elif deferrable:
            for (day, _), chosen in y.items():
                if day == target:
                    self.terms[tier].append((DEFER_BONUS, chosen))
        return {key: [chosen] for key, chosen in y.items()}

    def _continuous_runs(self, st: Statement, y: dict, sat, name: str, across) -> None:
        """Adjacent blocks whose lengths reach the duration; the last may be partial."""
        blocks = self.dataset.blocks
        target = self.dataset.target
        runs: list[tuple[cp_model.IntVar, dict[tuple[date, str], int]]] = []
        for day in st.on.items:
            ordered = [b.id for b in self.dataset.blocks_on(day) if (day, b.id) in y]
            for i in range(len(ordered)):
                members: dict[tuple[date, str], int] = {}
                remaining = st.minutes
                for j in range(i, len(ordered)):
                    if j > i and blocks[ordered[j - 1]].gap_to(blocks[ordered[j]]) != 0:
                        break
                    used = min(remaining, blocks[ordered[j]].minutes)
                    members[day, ordered[j]] = used
                    remaining -= used
                    if remaining == 0:
                        runs.append(
                            (self.model.NewBoolVar(f"{name}:run:{day}:{ordered[i]}"), members)
                        )
                        break
        self.model.Add(sum(run for run, _ in runs) == sat)
        for key, chosen in y.items():
            self.model.Add(chosen == sum(run for run, members in runs if key in members))
        if not isinstance(st.target, ast.AdHoc):
            return  # a clinic fills every block of its run
        for run, members in runs:
            for (day, block), used in members.items():
                for staff_id, staff_lit in across.items():
                    if day != target:
                        if self.variables.past_minutes(staff_id, st.target.text, day, block) < used:
                            self.model.AddBoolOr([run.Not(), staff_lit.Not()])
                        continue
                    interval = self.variables.adhoc_interval(staff_id, st.target.text, block, name)
                    self.model.Add(interval.size >= used).OnlyEnforceIf([run, staff_lit])
                    self.model.Add(interval.start == interval.block.start_minute).OnlyEnforceIf(
                        [run, staff_lit]
                    )

    def _choose(self, choice: Choice, sat, name: str) -> dict:
        """One literal per item, tied to `sat` by the choice's alternatives or quantifier."""
        chosen = {item: self.model.NewBoolVar(f"{name}:{item}") for item in choice.items}
        if choice.alternatives is not None:
            alts = [
                self.model.NewBoolVar(f"{name}:alt{i}") for i in range(len(choice.alternatives))
            ]
            self.model.Add(sum(alts) == sat)
            for item, lit in chosen.items():
                self.model.Add(
                    lit
                    == sum(
                        a for a, alt in zip(alts, choice.alternatives, strict=True) if item in alt
                    )
                )
            return chosen
        kind = choice.quantifier.kind
        if kind == "ALL":
            for lit in chosen.values():
                self.model.Add(lit == sat)
        else:
            n = choice.quantifier.n if kind == "OF" else 1
            self.model.Add(sum(chosen.values()) == n * sat)
        return chosen

    def _imply(self, conditions: list, consequence: Literal) -> None:
        """Conditions all true -> consequence, with constants folded."""
        if consequence is True:
            return
        clause = [c.Not() for c in conditions]
        if consequence is not False:
            clause.append(consequence)
        self.model.AddBoolOr(clause)

    # -- FORBID, PREFER, AVOID -------------------------------------------------------------------

    def _forbid(self, st: Statement, sat) -> None:
        for match in self._matched(st, past=False):
            self._imply([sat], _negate(match.literal))

    def _score(self, st: Statement, weight: float, priority: Priority) -> None:
        sign = 1 if st.verb == "PREFER" else -1
        tier = self.terms[priority]
        if st.per is None:
            metric = self.dataset.metrics[st.metric] if st.metric else None
            for match in self._matched(st, past=False):
                score = metric.normalized(_fields(match, metric.keys)) if metric else 1.0
                coefficient = round(SCALE * weight * score)
                if coefficient:
                    tier.append((sign * coefficient, match.literal))
            return
        groups: dict[tuple, list[Matched]] = {}
        for match in self._matched(st, past=True):
            groups.setdefault(_fields(match, st.per), []).append(match)
        for key, members in groups.items():
            fixed = sum(1 for m in members if m.literal is True)
            variables = [m.literal for m in members if m.literal is not True]
            if fixed + len(variables) <= st.beyond:
                continue
            excess = self.model.NewIntVar(0, len(members), f"excess:{':'.join(map(str, key))}")
            self.model.Add(excess >= fixed + sum(variables) - st.beyond)
            tier.append((-round(SCALE * weight), excess))

    def _matched(self, st: Statement, past: bool) -> Iterator[Matched]:
        """Assignments matching every clause. A (DBL) instance counts once."""
        target = self.dataset.target
        roles = self._role_filter(st)
        dates = [d for d in st.on.items if d == target or (past and d < target)]
        if isinstance(st.target, ast.Free):
            for day, staff_id, block in product(dates, st.across.items, st.during.items):
                yield Matched(
                    staff_id, "", None, day, block, self.variables.is_free(staff_id, day, block)
                )
            return
        seen: set = set()
        for day in dates:
            if day == target:
                entries = [
                    (slot.staff, slot.activity, slot.role, slot.block, var)
                    for slot, var in self.variables.x.items()
                ]
            else:
                entries = [(*key, True) for key in self.variables.past_assignments(day)]
            for staff_id, activity, role, block, literal in entries:
                if not self._accepts(st, roles, staff_id, activity, role, block):
                    continue
                key = (
                    (day, staff_id, activity, role)
                    if self._double(activity)
                    else (day, staff_id, activity, role, block)
                )
                if key in seen:
                    continue
                seen.add(key)
                yield Matched(staff_id, activity, role, day, block, literal)

    def _accepts(self, st, roles, staff_id, activity, role, block) -> bool:
        if isinstance(st.target, ast.AdHoc):
            if activity != st.target.text:
                return False
        elif activity not in st.target.items:
            return False
        if roles is not None and role not in roles:
            return False
        return staff_id in st.across.items and block in st.during.items

    def _double(self, activity_id: str) -> bool:
        activity = self.dataset.activities.get(activity_id)
        return activity is not None and activity.double

    @staticmethod
    def _role_filter(st: Statement) -> set[str] | None:
        if st.role is None:
            return None
        roles = set(st.role.items)
        if TRAINEE in roles:
            roles |= {SHADOW, SCAFFOLDED}
        return roles

    # -- GAP -----------------------------------------------------------------------------------

    def _gap(self, gap: ast.Gap, sat, name: str, first: tuple, second: tuple) -> None:
        """Second task starts after the first ends, with the gap satisfying the comparison."""
        end_first = self.model.NewIntVar(0, 24 * 60, f"{name}:gap:{gap.first}:end")
        start_second = self.model.NewIntVar(0, 24 * 60, f"{name}:gap:{gap.second}:start")
        for literal, (_, end) in self._task_intervals(gap, first):
            self.model.Add(end_first == end).OnlyEnforceIf(literal)
        for literal, (start, _) in self._task_intervals(gap, second):
            self.model.Add(start_second == start).OnlyEnforceIf(literal)
        between = start_second - end_first
        self.model.Add(between >= 0).OnlyEnforceIf(sat)
        if gap.comparison in ("<=", "=="):
            self.model.Add(between <= gap.minutes).OnlyEnforceIf(sat)
        if gap.comparison in (">=", "=="):
            self.model.Add(between >= gap.minutes).OnlyEnforceIf(sat)

    def _task_intervals(self, gap: ast.Gap, labeled: tuple):
        """(chosen literal, (start, end)) for each block a labeled task may use."""
        st, across, chosen_blocks = labeled
        if len(across) != 1:
            raise ast.SkedgeError(
                "GAP tasks must be for one staff member (use ACROSS EACH)",
                gap.pos.line,
                gap.pos.column,
            )
        staff_id = next(iter(across))
        for block, literal in chosen_blocks.items():
            times: tuple = (
                self.dataset.blocks[block].start_minute,
                self.dataset.blocks[block].end_minute,
            )
            if isinstance(st.target, ast.AdHoc):
                interval = self.variables.intervals.get(Slot(staff_id, st.target.text, None, block))
                if interval is not None:
                    times = (interval.start, interval.end)
            yield literal, times


def _compare(value: int, comparison: str, bound: int) -> bool:
    return {"<=": value <= bound, ">=": value >= bound, "==": value == bound}[comparison]


def _negate(literal: Literal) -> Literal:
    if isinstance(literal, bool):
        return not literal
    return literal.Not()


def _fields(match: Matched, fields: tuple[str, ...]) -> tuple[str, ...]:
    values = {
        "staff": match.staff,
        "activity": match.activity,
        "role": match.role or "",
        "date": match.date.isoformat(),
        "block": match.block,
    }
    return tuple(values[f] for f in fields)
