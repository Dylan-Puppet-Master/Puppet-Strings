"""Compile resolved Skedge declarations into CP-SAT constraints and objective terms.

Each active copy of a REQUEST gets a satisfaction literal `sat`: an assumption when the
request is hard, `weight * sat` in its tier when soft. A copy's constraints are enforced
by `active`, which is `sat` and, when the declaration has a condition, that it applies.
A PREFER adds objective terms only.

A declaration may hold both. Its REQUEST statements share the one `sat`, exactly as they
would alone, and its PREFER statements add their terms afterwards, so a block that says
"these things must happen, and this is what we would rather have" is compiled as the two
things it says.
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
    Company,
    Condition,
    Count,
    Exclusion,
    Forbid,
    Junction,
    Pattern,
    Predicate,
    Requirement,
    Resolved,
    Score,
    is_prefer,
)
from puppet_strings.solver.variables import Literal, Slot, Variables

SCALE = 1000
DEFER_BONUS = 1  # for acting early on a deferrable request; sits in the last tier
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_HOUR = 60
ONE_MATCH = ast.Amount(ast.AT_LEAST, 1, False, DEFAULT_POS)


@dataclass(frozen=True)
class Compiled:
    """One active copy of a REQUEST in the model."""

    id: str
    request: Request
    sat: Literal
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
    """One assignment a requirement makes, with its times, for GAP.

    `start` and `end` are minutes from midnight on the target date, so a published day
    behind the target is negative: 16:00 yesterday is -480. A gap is a distance between two
    assignments, and a distance only means anything if both are measured from one place.
    """

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
        self.asked_instances: dict[tuple[str, str], list[Literal]] = {}  # and for each clinic
        self.asked_trainees: dict[tuple[str, str, str], list[Literal]] = {}  # and each trainee
        self.shortened: dict[Slot, list[Literal]] = {}  # what gives it a FOR length
        self._same_starts: dict[tuple[int, int], cp_model.IntVar] = {}
        self._published: dict[date, dict[tuple[str, str], list[Row]]] = {}
        self._implied: list[tuple[list, Literal]] = []  # what the copy being compiled implies
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
        # second, so these attach to the clinics above rather than bringing their own
        for request, copy in copies:
            for st in copy.statements:
                if not isinstance(st, Count) or st.prefer or st.amount.bound == ast.AT_MOST:
                    continue
                p = st.pattern
                if p.what is not None and target in p.on.items:
                    self._create(
                        p.who.items, p.what, p.during, p.role, p.with_, request.id, clinics=False
                    )

    def _create(self, staff_ids, what, during, role, partners, source: str, clinics=True) -> None:
        today = [b.id for b in self.dataset.blocks_on(self.dataset.target)]
        blocks = [b for b in (during.items if during else today) if b in today]
        people = set(staff_ids) | (partners.staff if partners else frozenset())
        if isinstance(what, ast.Task):
            for s, b in product(people, blocks):
                self.variables.adhoc(s, what.text, b, source)
            return
        spans = during is not None and during.kind == ALL and len(blocks) == 2
        trainees = role is not None and set(role.items) & {TRAINEE, *TRAINEE_ROLES}
        for activity_id in what.items:
            double = spans and self.dataset.activities[activity_id].double
            if clinics and double:
                ordered = sorted(blocks, key=lambda b: self.dataset.blocks[b].start)
                self.variables.instance(activity_id, tuple(ordered), source)
            elif clinics:
                for b in blocks:
                    self.variables.instance(activity_id, (b,), source)
            if trainees:
                for s, b in product(staff_ids, blocks):
                    self.variables.trainee(s, activity_id, b, source)

    # -- one copy ------------------------------------------------------------------------------

    def compile(self, request: Request, copy: Resolved) -> bool:
        """Add one copy. Returns False when it is inactive: its dates all past or all future.

        An `EXCLUDE` is not compiled at all: who is away was settled before the model was
        built, by taking those blocks out of the day (`puppet_strings.exclude`). A copy
        that holds nothing else is done rather than inactive, so the report leaves it be.
        """
        statements = tuple(st for st in copy.statements if not isinstance(st, Exclusion))
        if not statements:
            return True
        copy = replace(copy, statements=statements)
        if not self._active(copy):
            return False
        self._name = name = f"{request.id}[{copy.key}]" if copy.key else request.id
        self._bindings, self._shared = copy.bindings, {}
        tier = Priority.CLINIC if request.priority.hard else request.priority
        applies = self._applies(copy.condition, name)
        wanted = [st for st in copy.statements if is_prefer(st)]
        required = [st for st in copy.statements if not is_prefer(st)]
        if required:
            # first, so that a preference can be about what the requirements chose, and so
            # that `_collapse` sees only the constraints the requirements posted
            self._required(request, copy, required, applies, tier, name)
        for index, statement in enumerate(wanted):
            label = name if index == 0 else f"{name}#{index + 1}"
            self._prefer(statement, applies, request.weight, tier, label)
        return True

    def _required(
        self, request: Request, copy: Resolved, statements: list, applies: Literal, tier, name: str
    ) -> None:
        """Compile the copy's REQUEST statements, which stand or fall together."""
        sat: Literal = self.model.NewBoolVar(f"sat:{name}")
        if request.priority.hard:
            self.model.AddAssumption(sat)
        active = self._all_of([sat, applies], f"active:{name}")
        for var, binding in copy.bindings.items():
            self._shared[var] = self._choose(replace(binding, var=None), sat, f"{name}:{var}")
        self._implied = []
        posted = len(self.model.Proto().constraints)
        deferred: list[Literal] = []
        made: dict[str, list[Made]] = {}
        for st in statements:
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
        if not request.priority.hard:
            sat = self._collapse(sat, applies, posted)
            self.terms[tier].append((round(SCALE * request.weight), sat))
        self.compiled.append(
            Compiled(name, request, sat, self._any_of(deferred, f"deferred:{name}"))
        )

    def _collapse(self, sat: Literal, applies: Literal, posted: int) -> Literal:
        """The literal a copy's satisfaction already is, when the model holds one.

        A copy that does nothing but imply a single literal is met exactly when that
        literal is true, which is most of what `EACH_OF` splits a declaration into. Scoring
        that literal rather than a fresh boolean standing behind an implication lets the
        solver weigh the request against the assignments it is really about; the boolean is
        then unused and presolve drops it, along with the implication.
        """
        if applies is not True or len(self._implied) != 1:
            return sat
        conds, consequence = self._implied[0]
        if isinstance(consequence, bool):
            return sat
        gating = _distinct([c for c in conds if c is not True])
        if len(gating) != 1 or gating[0] is not sat:
            return sat
        if len(self.model.Proto().constraints) != posted + 1:
            return sat  # the copy posted more than that one implication
        return consequence

    def _active(self, copy: Resolved) -> bool:
        target = self.dataset.target
        dates = {d for st in copy.statements for d in _dates_of(st)}
        if target in dates:
            return True
        return any(d < target for d in dates) and any(d > target for d in dates)

    def _applies(self, condition: Condition | None, name: str) -> Literal:
        if condition is None:
            return True
        holds = self._test(condition.test, f"if:{name}")
        return _negate(holds) if condition.unless else holds

    def _test(self, test: Predicate | Junction, name: str) -> Literal:
        """A literal true when a condition's test holds: AND and OR over its predicates."""
        if isinstance(test, Junction):
            parts = [self._test(part, f"{name}.{i}") for i, part in enumerate(test.parts)]
            return self._all_of(parts, name) if test.all else self._any_of(parts, name)
        amount = test.amount or ONE_MATCH
        return self._holds(amount, test.pattern, test.consecutive, name)

    # -- PREFER --------------------------------------------------------------------------------

    def _prefer(self, st: Score | Count, applies: Literal, weight: float, tier, name: str) -> None:
        if applies is False:
            return
        if isinstance(st, Score):
            mapping = self.dataset.mappings[st.mapping]
            sign = 1 if st.maximize else -1
            coefficient = sign * round(SCALE * weight * mapping.normalized(st.key))
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
        loose = self._loose(st)

        def chosen(choice: Choice, label: str) -> dict:
            if choice is loose:
                return dict.fromkeys(choice.items, True)  # counted at the end, not chosen here
            return self._choose(choice, active, f"{name}:{label}")

        who = chosen(st.who, "staff")
        whats = chosen(st.what, "activity") if isinstance(st.what, Choice) else {st.what: True}
        blocks = chosen(st.during, "block")
        if st.during.consecutive:
            self._adjacent(blocks, st.during.n, st.on.items, active, f"{name}:block")
        roles = chosen(st.role, "role") if st.role else {None: True}
        dates = chosen(st.on, "date")
        made = []
        counted: list[Literal] = []
        for (d, on), (b, on_b), (s, on_s), (w, on_w), (r, on_r) in product(
            dates.items(), blocks.items(), who.items(), whats.items(), roles.items()
        ):
            conds = [active, on, on_b, on_s, on_w, on_r]
            if d < target:
                held = self._was_held(s, w, r, d, b, st)
                self._imply(conds, held)
                if held and st.label:
                    made += self._was_made(s, w, r, d, b, conds, name)
                continue
            if not self.dataset.holds(s, d, b):
                if loose is None:
                    self._imply(conds, False)
                else:
                    counted.append(False)  # this member has nothing it could hold
                continue
            if d > target:
                continue  # a later date can hold it, and holds nothing yet
            held, start, end = self._hold(s, w, r, b, st, conds, name)
            if loose is None:
                self._imply(conds, held)
            else:
                counted.append(held)
            self._partners(s, w, b, st, conds, name)
            made.append(Made(self._all_of(conds, f"made:{name}:{s}:{b}"), start, end))
        if loose is not None:
            terms = [x for x in counted if x is not False and x is not True]
            constant = sum(1 for x in counted if x is True)
            self._add(sum(terms) + constant >= loose.n, [active])
        later = [on for d, on in dates.items() if d > target]
        if not later or st.on.kind != ANY:
            return made, False
        if target in dates:
            self._bonus(dates[target])
        return made, self._any_of(later, f"later:{name}")

    def _was_made(self, s, w, r, d: date, b: str, conds: list, name: str) -> list[Made]:
        """What a published day already holds, timed for a GAP that reaches across days.

        Only a labeled requirement asks, because only a label can be one end of a gap. The
        times are the ones published, offset by how far back the day is, so `AT_LEAST 40h`
        between two meetings is read against the meeting that actually happened rather than
        against nothing.
        """
        if w is None:
            return []
        activity = w.text if isinstance(w, ast.Task) else w
        offset = (d - self.dataset.target).days * MINUTES_PER_DAY
        literal = self._all_of(conds, f"was:{name}:{s}:{d}:{b}")
        made = []
        for a in self.variables.was_member(s, activity, d, b):
            if r is not None and r != TRAINEE and a.role != r:
                continue
            start = offset + a.start.hour * 60 + a.start.minute
            made.append(Made(literal, start, start + a.minutes))
        return made

    def _loose(self, st: Requirement) -> Choice | None:
        """The one chooser a requirement can count rather than choose, if it has one.

        `ANY n` asks that n of a pool do the one thing named of them, which is the same
        as asking that n of those assignments happen. When everything else in the
        requirement names a single thing, so each member has exactly one assignment to its
        name, counting says it without a variable per member. A quoted task keeps its
        choice, which is also what stops the task happening where nobody asked for it.
        """
        if st.with_ or st.without or st.label or isinstance(st.what, ast.Task):
            return None
        if st.on.items != (self.dataset.target,):
            return None
        wide = [
            c
            for c in (st.who, st.what, st.during, st.role)
            if isinstance(c, Choice) and (len(c.items) > 1 or c.units)
        ]
        if len(wide) != 1 or wide[0].kind != ANY or wide[0].var is not None:
            return None
        if wide[0].consecutive or wide[0].units:
            return None  # which n matters, not only how many
        return wide[0]

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
        asks = self._all_of(conds, f"asks:{name}:{s}:{w}:{b}")
        self.asked_instances.setdefault((w, b), []).append(asks)
        if r is None:
            held = self._any_of(self.variables.holders(s, w, b), f"holds:{name}:{s}:{w}:{b}")
        elif r == TRAINEE or r in TRAINEE_ROLES:
            role, var = self.variables.trainee(s, w, b, name)
            held = var if r in (TRAINEE, role) else False
            self.asked_trainees.setdefault((s, w, b), []).append(asks)
        else:
            held = self.variables.lookup(s, w, r, b)
        return held, block.start_minute, block.end_minute

    def _partners(self, s: str, w, b: str, st: Requirement, conds: list, name: str) -> None:
        """WITH: enough others from the set are on the same instance. WITHOUT: not so."""
        target = self.dataset.target
        if st.with_ is not None:
            if isinstance(w, ast.Task):
                selector = self._all_of(conds, f"asks:{name}:{s}:{b}:with")
                for p in st.with_.staff - {s}:
                    self.asked_for.setdefault(Slot(p, w.text, None, b), []).append(selector)
            self._imply(conds, self._company(s, w, target, b, st.with_, f"with:{name}:{s}:{b}"))
        if st.without is not None:
            company = self._company(s, w, target, b, st.without, f"without:{name}:{s}:{b}")
            self._imply(conds, _negate(company))

    def _company(self, s: str, what, d: date, b: str, company: Company, name: str) -> Literal:
        """Whether `n` others from the set, or all of them, share the instance `s` is on."""
        together = [self._together(s, p, what, d, b) for p in sorted(company.staff - {s})]
        n = len(together) if company.n is None else company.n
        if n > len(together):
            return False
        if n == len(together):
            return self._all_of(together, name)
        if n == 1:
            return self._any_of(together, name)
        terms = [t for t in together if not isinstance(t, bool)]
        return self._at_least(terms, sum(t is True for t in together), n, name)

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
        if with_ is not None and not self._company(s, what, d, b, with_, ""):
            return False
        return without is None or not self._company(s, what, d, b, without, "")

    def _forbid(self, st: Forbid, active, name: str) -> None:
        """NOT DO: no assignment of a chosen staff member matches. NOT FREE: they are busy."""
        who = self._choose(st.who, active, f"{name}:staff")
        for m in self._matches(st.pattern, past=False):
            self._imply(
                [active, who[m.staff]], m.literal if st.pattern.busy else _negate(m.literal)
            )

    # -- choices -------------------------------------------------------------------------------

    def _choose(self, choice: Choice, active: Literal, name: str) -> dict:
        """One literal per item: `active` itself for ALL, else `n` of them chosen together.

        A choice with `parts` is a set somebody added a bound name into, so it is the
        items here together with whatever each part chose; the parts keep their own
        literals, which is what makes `videographer` the same person everywhere it appears.
        """
        chosen = self._choose_one(choice, active, name)
        for i, part in enumerate(choice.parts):
            more = self._choose_one(part, active, f"{name}:part{i}")
            # a part of its own is chosen under `active`, so an item `active` holds stays so
            covering = active if part.var is None else None
            chosen = self._merge(chosen, more, name, covering)
        return chosen

    def _merge(self, chosen: dict, more: dict, name: str, covering=None) -> dict:
        """Two choices over the same items: an item named by both is in when either has it.

        An item `chosen` holds by `covering`, a literal nothing in `more` is true without,
        is left as it is, since OR-ing it with anything gives itself back.
        """
        merged = dict(chosen)
        for item, literal in more.items():
            if item not in merged:
                merged[item] = literal
            elif merged[item] is not covering:
                merged[item] = self._any_of([merged[item], literal], f"{name}:either:{item}")
        return merged

    def _choose_one(self, choice: Choice, active: Literal, name: str) -> dict:
        """One part of a choice, before any it is joined with."""
        if choice.var is not None:
            if choice.var not in self._shared:  # a PREFER, which has no sat
                binding = replace(self._bindings[choice.var], var=None)
                self._shared[choice.var] = self._choose(binding, True, f"{self._name}:{choice.var}")
            return self._shared[choice.var]
        if choice.kind == ALL:
            return dict.fromkeys(choice.items, active)
        chosen = {item: self.model.NewBoolVar(f"{name}:{item}") for item in choice.items}
        # a group is one of the things chosen from, and brings what it takes when it is
        picked = [self.model.NewBoolVar(f"{name}:group{i}") for i in range(len(choice.units))]
        total = sum(chosen.values()) + sum(picked)
        if isinstance(active, bool):
            self.model.Add(total == (choice.n if active else 0))
        else:
            self.model.Add(total == choice.n * active)
        for i, (unit, pick) in enumerate(zip(choice.units, picked, strict=True)):
            chosen = self._merge(chosen, self._choose(unit, pick, f"{name}:group{i}"), name)
        return chosen

    def _adjacent(self, chosen: dict, n: int, days, active: Literal, name: str) -> None:
        """`ANY n <blocks> CONSECUTIVE`: the n chosen blocks are a run of adjacent ones.

        Blocks are adjacent when they are next to each other in the Blocks sheet, as they
        are for a CONSECUTIVE amount, on any of the dates the requirement is about. Exactly
        one such run is picked when the requirement is active, and it is what is chosen.
        """
        runs: set[tuple[str, ...]] = set()
        for day in days:
            order = [b.id for b in self.dataset.blocks_on(day)]
            for i in range(len(order) - n + 1):
                run = tuple(order[i : i + n])
                if all(b in chosen for b in run):
                    runs.add(run)
        if not runs:
            self._imply([active], False)  # no n of them are ever next to each other
            return
        picked = {run: self.model.NewBoolVar(f"{name}:run:{'+'.join(run)}") for run in sorted(runs)}
        self.model.Add(sum(picked.values()) == active)
        for block, literal in chosen.items():
            self.model.Add(literal == sum(p for run, p in picked.items() if block in run))

    def _pool(self, choice: Choice | None) -> dict:
        """Each item of a pool with the condition for its membership: True, or a shared choice."""
        if choice is None:
            return {}
        if choice.var is None and not choice.parts:
            return dict.fromkeys(choice.items, True)
        if choice.var is None:
            return {**dict.fromkeys(choice.items, True), **self._choose(choice, True, "")}
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
            for row in self._rows(d, who, activities, ids):
                if roles is not None and row.role not in roles:
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

    def _rows(self, d: date, staff_ids, activities, blocks: set[str]) -> Iterator[Row]:
        """The assignments of these people to these activities in these blocks on a date.

        The blocks are checked before a row is made: most of a person's assignments to a
        category of clinics are in blocks the pattern is not about.
        """
        if d != self.dataset.target:
            index = self._published_rows(d)
            for key in product(staff_ids, activities):
                yield from (row for row in index.get(key, ()) if row.block in blocks)
            return
        for key in product(staff_ids, activities):
            for slot in self.variables.slots.get(key, ()):
                if slot.block not in blocks:
                    continue
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
        where = f"{row.staff}:{row.activity}:{d}:{row.block}"
        if pattern.with_ is not None:
            return self._company(row.staff, what, d, row.block, pattern.with_, f"with:{where}")
        if pattern.without is not None:
            company = self._company(
                row.staff, what, d, row.block, pattern.without, f"without:{where}"
            )
            return _negate(company)
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

    def _block_most(self, here: list[Match], duration: bool) -> int:
        """The most one block can hold: a person's assignments in it never overlap in time.

        So whole-block assignments rule each other out, and the tasks sharing a block can
        add up to no more than its length. Without this the bound would count every
        candidate assignment, and a window would carry a large constraint that the
        no-overlap rule already makes vacuous.
        """
        live = [m for m in here if m.literal is not False]
        if not live:
            return 0
        minutes = self.dataset.blocks[live[0].block].minutes
        if duration:
            lengths = [m.minutes if isinstance(m.minutes, int) else minutes for m in live]
            return min(minutes, sum(lengths))
        published = [m for m in live if m.literal is True]
        if published:
            return len(published)  # a past date is a fact, however many it holds
        partial = [m for m in live if not isinstance(m.minutes, int) or m.minutes < minutes]
        return max(len(partial), 1)

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

    def _windows(
        self, matches: list[Match], duration: bool, needed: int, name: str
    ) -> Iterator[tuple]:
        """Every window of adjacent blocks one person's matches could fill, on one date.

        A window is (block literals, amount terms, constant, largest possible amount). Each
        block's literal and contribution are worked out once and shared by every window
        covering it; a block nothing matches breaks the run, since blocks are adjacent only
        when they are next to each other in the Blocks sheet. A person and date whose
        longest run could never reach `needed` is skipped before anything is built for it.
        """
        grouped: dict[tuple[str, date], dict[str, list[Match]]] = {}
        for m in matches:
            grouped.setdefault((m.staff, m.date), {}).setdefault(m.block, []).append(m)
        for (staff_id, day), per_block in grouped.items():
            order = [b.id for b in self.dataset.blocks_on(day)]
            most = [
                self._block_most(per_block[b], duration) if b in per_block else None for b in order
            ]
            if _longest(most) < needed:
                continue
            cells = []
            for block_id, amount in zip(order, most, strict=True):
                if amount is None:
                    cells.append(None)  # a gap: no run crosses it
                    continue
                here = per_block[block_id]
                filled = self._any_of(
                    [m.literal for m in here], f"{name}:filled:{staff_id}:{day}:{block_id}"
                )
                terms, constant = self._amount(here, duration)
                cells.append((filled, terms, constant, amount))
            yield from _runs_from(cells)

    def _runs_hold(self, amount: ast.Amount, matches: list[Match], name: str) -> Literal:
        """A literal: AT_LEAST some run reaches the amount, AT_MOST no run exceeds it."""
        n = amount.value
        reaching, exceeding = [], []
        windows = self._windows(matches, amount.duration, _needed(amount), name)
        for i, (blocks, terms, constant, most) in enumerate(windows):
            wants_least = amount.bound != ast.AT_MOST and most >= n
            wants_most = amount.bound != ast.AT_LEAST and most > n
            if not (wants_least or wants_most):
                continue
            present = self._all_of(blocks, f"{name}:run{i}:present")
            if wants_least:
                reaches = self._at_least(terms, constant, n, f"{name}:run{i}:ge")
                reaching.append(self._all_of([present, reaches], f"{name}:run{i}:reaching"))
            if wants_most:
                exceeds = self._at_least(terms, constant, n + 1, f"{name}:run{i}:gt")
                exceeding.append(self._all_of([present, exceeds], f"{name}:run{i}:exceeding"))
        at_least = self._any_of(reaching, f"{name}:reached")
        at_most = _negate(self._any_of(exceeding, f"{name}:exceeded"))
        if amount.bound == ast.AT_LEAST:
            return at_least
        if amount.bound == ast.AT_MOST:
            return at_most
        return self._all_of([at_least, at_most], f"{name}:exact")

    def _enforce(self, amount, matches: list[Match], consecutive: bool, conds: list, name) -> None:
        """Post the amount's comparison as constraints, for a caller that only enforces it.

        A reified literal says both when the comparison holds and when it does not, which
        the solver propagates poorly. Where the answer is only ever "this must hold", the
        comparison goes in directly, with the conditions as enforcement literals.
        """
        n = amount.value
        if not consecutive:
            terms, constant = self._amount(matches, amount.duration)
            if amount.bound != ast.AT_MOST:
                self._add(sum(terms) + constant >= n, conds)
            if amount.bound != ast.AT_LEAST:
                self._add(sum(terms) + constant <= n, conds)
            return
        reaching = []
        windows = self._windows(matches, amount.duration, _needed(amount), name)
        for i, (blocks, terms, constant, most) in enumerate(windows):
            if amount.bound != ast.AT_LEAST and most > n:
                self._add(sum(terms) + constant <= n, [*conds, *blocks])
            if amount.bound != ast.AT_MOST and most >= n:
                present = self._all_of(blocks, f"{name}:run{i}:present")
                reaches = self._at_least(terms, constant, n, f"{name}:run{i}:ge")
                reaching.append(self._all_of([present, reaches], f"{name}:run{i}:reaching"))
        if amount.bound != ast.AT_MOST:
            self._imply(conds, self._any_of(reaching, f"{name}:reached"))

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
        # a run short of AT_LEAST still counts, since the miss is how far the best run falls short
        needed = _needed(amount) if amount.bound == ast.AT_MOST else 1
        windows = self._windows(matches, amount.duration, needed, name)
        for i, (blocks, terms, constant, most) in enumerate(windows):
            present = self._all_of(blocks, f"{name}:run{i}:present")
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
        # a run must fit inside one date, so it defers only to a date that can hold all of it
        due = n if st.consecutive else 1
        if capacity < due:  # later dates cannot hold the remainder, so it is all due today
            self._enforce(amount, matches, st.consecutive, [active], name)
            return False
        # deferrable: today it must only stay reachable, and progress earns the early bonus
        if st.consecutive:
            now = self._runs_hold(amount, matches, name)
            if amount.bound == ast.EXACTLY:
                upper = replace(amount, bound=ast.AT_MOST)
                self._enforce(upper, matches, True, [active], f"{name}:upper")
            self._bonus(now)
            return _negate(now)
        terms, constant = self._amount(matches, amount.duration)
        self._add(sum(terms) + constant >= n - capacity, [active])
        if amount.bound == ast.EXACTLY:
            self._add(sum(terms) + constant <= n, [active])
        reached = self._at_least(terms, constant, n, f"{name}:reached")
        progress = self.model.NewIntVar(0, n, f"{name}:progress")
        self.model.Add(progress <= sum(terms) + constant)
        self._bonus(progress)
        return _negate(reached)

    def _ask_for(self, matches: list[Match], p: Pattern, active: Literal) -> None:
        """An assignment an AT_LEAST or EXACTLY pattern matches may exist for it."""
        if p.what is None:
            return
        for m in matches:
            if m.date != self.dataset.target:
                continue
            if isinstance(p.what, ast.Task):
                for s in {m.staff, *(p.with_.staff if p.with_ else ())}:
                    self.asked_for.setdefault(Slot(s, m.activity, None, m.block), []).append(active)
                continue
            if m.role in TRAINEE_ROLES:  # a clinic itself runs only where a REQUEST … DO says
                self.asked_trainees.setdefault((m.staff, m.activity, m.block), []).append(active)

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

    def close(self) -> None:
        """Nothing happens that no request asked for. Call once, after compiling.

        A quoted-task assignment, a clinic and a trainee each exist only where a positive
        REQUEST, or a counted pattern that has an amount to reach, selected them. Position
        holders need no rule of their own: a clinic that runs is staffed and one that does
        not is empty. A quoted task is as long as its block unless a `FOR` selects it.
        """
        for slot, var in self.variables.x.items():
            if slot.activity in self.dataset.activities:
                continue
            self._only_if_asked(var, self.asked_for.get(slot, []))
            shortened = [s for s in self.shortened.get(slot, []) if s is not False]
            if any(s is True for s in shortened):
                continue
            interval = self.variables.intervals[slot]
            unless = [var, *(s.Not() for s in shortened)]
            self.model.Add(interval.size == interval.block.minutes).OnlyEnforceIf(unless)
        for instance in self.variables.unique_instances():
            activity = instance.activity.id
            asked = [
                a for b in instance.blocks for a in self.asked_instances.get((activity, b), [])
            ]
            self._only_if_asked(instance.filled, asked)
            for staff_id, (_, var) in instance.trainees.items():
                asked = [
                    a
                    for b in instance.blocks
                    for a in self.asked_trainees.get((staff_id, activity, b), [])
                ]
                self._only_if_asked(var, asked)

    def _only_if_asked(self, var: cp_model.IntVar, asked: list[Literal]) -> None:
        """Allow this only where one of these selected it."""
        live = _distinct([a for a in asked if a is not False])
        if any(a is True for a in asked):
            return
        self.model.AddBoolOr([var.Not(), *live])

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
        """Conditions all true -> consequence, with constants folded and repeats dropped."""
        if consequence is True or any(c is False for c in conds):
            return
        clause = [c.Not() for c in _distinct([c for c in conds if c is not True])]
        if consequence is not False:
            clause.append(consequence)
        self.model.AddBoolOr(clause)
        self._implied.append((conds, consequence))

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


def _needed(amount: ast.Amount) -> int:
    """The smallest amount a window must be able to reach before it is worth building."""
    return amount.value + (1 if amount.bound == ast.AT_MOST else 0)


def _longest(most: list[int | None]) -> int:
    """The largest total over one stretch of adjacent blocks that hold matches."""
    best = run = 0
    for amount in most:
        run = 0 if amount is None else run + amount
        best = max(best, run)
    return best


def _runs_from(cells: list) -> Iterator[tuple]:
    """Every contiguous window of the filled cells, each accumulating the ones before it."""
    for i in range(len(cells)):
        literals, terms, constant, most = [], [], 0, 0
        for cell in cells[i:]:
            if cell is None:
                break
            literals.append(cell[0])
            terms = terms + cell[1]
            constant += cell[2]
            most += cell[3]
            yield list(literals), terms, constant, most


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
