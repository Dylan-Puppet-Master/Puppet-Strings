"""Compile resolved Skedge declarations into CP-SAT constraints and objective terms.

Each active copy of a REQUEST gets a satisfaction literal `sat`: an assumption when the
request is hard, `weight * sat` in its tier when soft. A copy's constraints are enforced
by `active`, which is `sat` and, for a statement inside an IF or UNLESS, that every
condition around it holds.
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
    POOL,
    TRAINEE,
    Choice,
    Company,
    Condition,
    Exclusion,
    Forbid,
    Junction,
    Level,
    Pattern,
    Predicate,
    Requirement,
    Resolved,
    Score,
    Tally,
    asks,
    is_prefer,
)
from puppet_strings.solver.variables import Literal, Slot, Variables

SCALE = 1000
DEFER_BONUS = 1  # for acting early on a deferrable request; sits in the last tier
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_HOUR = 60
FIELDS = {"staff": "who", "activity": "what", "date": "on", "block": "during"}
_MATCH_FIELD = {"staff": "staff", "activity": "activity", "date": "date", "block": "block"}
EXACT, ABOVE, BELOW = "exact", "above", "below"  # what a literal must say of what it stands for


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
        trainee assignment exists where one asks for it, or where a counted REQUEST could
        match it, partners named by `WITH` included. A count or a FOR over a pool of
        activities asks for no clinic of its own: it counts the ones that run.
        """
        target = self.dataset.target
        for request, copy in copies:
            for st in copy.statements:
                if isinstance(st, Requirement) and st.what is not None and target in st.on.items:
                    named = not isinstance(st.what, Choice) or st.what.kind == ALL
                    self._create(
                        st.who.items, st.what, st.during, st.role, st.with_, request.id, named
                    )
        # second, so these attach to the clinics above rather than bringing their own
        for request, copy in copies:
            for st in copy.statements:
                if not isinstance(st, Tally) or not asks(st):
                    continue
                p = st.pattern
                if p.what is not None and target in p.on.items:
                    named = isinstance(p.what, Choice) and p.what.kind == ALL
                    clinics = st.measure is None and named
                    self._create(
                        p.who.items, p.what, p.during, p.role, p.with_, request.id, clinics=clinics
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
        copy = copy.keeping(lambda st: not isinstance(st, Exclusion))
        if not copy.statements:
            return True
        if not self._active(copy):
            return False
        self._name = name = f"{request.id}[{copy.key}]" if copy.key else request.id
        self._bindings, self._shared = copy.bindings, {}
        tier = Priority.CLINIC if request.priority.hard else request.priority
        holds = {id(c): self._holds(c, f"if:{name}.{i}") for i, c in enumerate(copy.conditions)}
        applies: dict[tuple[int, ...], Literal] = {}  # statements in one block share theirs
        for when in copy.when:
            key = tuple(id(c) for c in when)
            if key not in applies:
                applies[key] = self._all_of(
                    [holds[k] for k in key], f"applies:{name}.{len(applies)}"
                )
        guarded = [
            (st, applies[tuple(id(c) for c in when)])
            for st, when in zip(copy.statements, copy.when, strict=True)
        ]
        wanted = [(st, guard) for st, guard in guarded if is_prefer(st)]
        required = [(st, guard) for st, guard in guarded if not is_prefer(st)]
        if required:
            # first, so that a preference can be about what the requirements chose, and so
            # that `_collapse` sees only the constraints the requirements posted
            self._required(request, copy, required, tier, name)
        for index, (statement, guard) in enumerate(wanted):
            label = name if index == 0 else f"{name}#{index + 1}"
            self._prefer(statement, guard, request.weight, tier, label)
        return True

    def _required(
        self, request: Request, copy: Resolved, statements: list, tier, name: str
    ) -> None:
        """Compile the copy's REQUEST statements, which stand or fall together.

        Each is enforced by `sat` and whatever conditions it is under; one whose conditions
        do not hold asks for nothing, so it is met.
        """
        sat: Literal = self.model.NewBoolVar(f"sat:{name}")
        if request.priority.hard:
            self.model.AddAssumption(sat)
        actives: dict[int, Literal] = {}

        def active(applies: Literal) -> Literal:
            if id(applies) not in actives:
                actives[id(applies)] = self._all_of([sat, applies], f"active:{name}.{len(actives)}")
            return actives[id(applies)]

        for var, binding in copy.bindings.items():
            self._shared[var] = self._choose(replace(binding, var=None), sat, f"{name}:{var}")
        self._implied = []
        posted = len(self.model.Proto().constraints)
        deferred: list[Literal] = []
        made: dict[str, tuple[list[Made], Literal]] = {}
        for st, applies in statements:
            if isinstance(st, Requirement):
                assignments, later = self._require(st, active(applies), name)
                deferred.append(later)
                if st.label:
                    made[st.label] = assignments, applies
            elif isinstance(st, Forbid):
                self._forbid(st, active(applies), name)
            else:
                deferred.append(self._tally(st, active(applies), name))
        for gap in copy.gaps:
            (first, first_applies), (second, second_applies) = made[gap.first], made[gap.second]
            # a GAP holds between its statements only when both are asked for
            both = self._all_of([sat, first_applies, second_applies], f"gap:{name}:applies")
            self._gap(gap, both, first, second, name)
        if not request.priority.hard:
            conditional = any(applies is not True for _, applies in statements)
            sat = self._collapse(sat, not conditional, posted)
            self.terms[tier].append((round(SCALE * request.weight), sat))
        self.compiled.append(
            Compiled(name, request, sat, self._any_of(deferred, f"deferred:{name}"))
        )

    def _collapse(self, sat: Literal, unconditional: bool, posted: int) -> Literal:
        """The literal a copy's satisfaction already is, when the model holds one.

        A copy that does nothing but imply a single literal is met exactly when that
        literal is true, which is most of what `EACH` splits a declaration into. Scoring
        that literal rather than a fresh boolean standing behind an implication lets the
        solver weigh the request against the assignments it is really about; the boolean is
        then unused and presolve drops it, along with the implication.
        """
        if not unconditional or len(self._implied) != 1:
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

    def _holds(self, condition: Condition, name: str) -> Literal:
        """A literal true when an IF's test holds, or an UNLESS's does not."""
        holds = self._test(condition.test, name)
        return _negate(holds) if condition.unless else holds

    def _test(self, test: Predicate | Junction, name: str) -> Literal:
        """A literal true when a condition's test holds: AND and OR over its predicates."""
        if isinstance(test, Junction):
            parts = [self._test(part, f"{name}.{i}") for i, part in enumerate(test.parts)]
            return self._all_of(parts, name) if test.all else self._any_of(parts, name)
        tally = test.tally
        return self._reify_levels(tally, tally.levels, tally.pattern, name)

    # -- PREFER --------------------------------------------------------------------------------

    def _prefer(self, st: Score | Tally, applies: Literal, weight: float, tier, name: str) -> None:
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
        miss, bound = self._tally_miss(st, name)
        if isinstance(miss, int):
            return
        if applies is not True:
            gated = self.model.NewIntVar(0, bound, f"miss:{name}:applies")
            self.model.Add(gated >= miss).OnlyEnforceIf(applies)
            miss = gated
        unit = 1 if st.levels else MINUTES_PER_HOUR  # a count, or else a FOR length
        self.terms[tier].append((-round(SCALE * weight / unit), miss))

    # -- requirements --------------------------------------------------------------------------

    def _require(self, st: Requirement, active, name: str) -> tuple[list[Made], Literal]:
        """Every chosen staff member does the thing in every chosen block on every chosen date.

        A pooled set is chosen from one item at a time, for each combination of the sets that
        are not: `ALL {staff.x + staff.y} DO … DURING ANY blocks` gives each of them a
        block of their own.
        """
        target = self.dataset.target
        loose = self._loose(st)

        def chosen(choice: Choice, label: str) -> dict:
            if choice is loose or choice.kind == POOL:
                return dict.fromkeys(choice.items, True)  # counted at the end, or picked below
            return self._choose(choice, active, f"{name}:{label}")

        fields = (st.on, st.during, st.who, st.what, st.role)
        pooled = [isinstance(c, Choice) and c.kind == POOL and c is not loose for c in fields]
        who = chosen(st.who, "staff")
        whats = chosen(st.what, "activity") if isinstance(st.what, Choice) else {st.what: True}
        blocks = chosen(st.during, "block")
        if st.during.consecutive:
            self._adjacent(blocks, st.during.n, st.on.items, active, f"{name}:block")
        roles = chosen(st.role, "role") if st.role else {None: True}
        dates = chosen(st.on, "date")
        made = []
        counted: list[Literal] = []
        picks: dict[tuple, dict[tuple, Literal]] = {}
        under: dict[tuple, list] = {}
        for combination in product(
            dates.items(), blocks.items(), who.items(), whats.items(), roles.items()
        ):
            (d, on), (b, on_b), (s, on_s), (w, on_w), (r, on_r) = combination
            conds = [active, on, on_b, on_s, on_w, on_r]
            if any(pooled):
                key = tuple(v for (v, _), p in zip(combination, pooled, strict=True) if not p)
                pick = tuple(v for (v, _), p in zip(combination, pooled, strict=True) if p)
                options = picks.setdefault(key, {})
                if pick not in options:
                    options[pick] = self.model.NewBoolVar(f"{name}:pick:{key}:{pick}")
                under.setdefault(
                    key, [c for (_, c), p in zip(combination, pooled, strict=True) if not p]
                )
                conds.append(options[pick])
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
        for key, options in picks.items():
            self._add(sum(options.values()) == 1, [active, *under[key]])  # one of each pool
        if loose is not None:
            terms = [x for x in counted if x is not False and x is not True]
            constant = sum(1 for x in counted if x is True)
            self._add(sum(terms) + constant >= loose.n, [active])
        if pooled[0]:  # the dates are pooled: a pick of a later date is met later
            later = [
                lit for opts in picks.values() for pick, lit in opts.items() if pick[0] > target
            ]
            for opts in picks.values():
                for pick, lit in opts.items():
                    if pick[0] == target:
                        self._bonus(lit)
            return made, self._any_of(later, f"later:{name}")
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

        ANY n asks that n of a set do the one thing named of them, which is the same
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
        if len(wide) != 1 or wide[0].kind not in (ANY, POOL) or wide[0].var is not None:
            return None
        if wide[0].minus:
            return None  # who is in waits on another choice
        if wide[0].consecutive or wide[0].units:
            return None  # which n matters, not only how many
        return wide[0]

    def _hold(self, s: str, w, r, b: str, st: Requirement, conds: list, name: str) -> tuple:
        """The literal for one assignment on the target date, and its start and end."""
        block = self.dataset.blocks[b]
        if w is None:
            state = self.variables.busy(s, b) if st.busy else self.variables.free(s, b)
            return state, block.start_minute, block.end_minute
        if isinstance(w, ast.Task):
            var = self.variables.adhoc(s, w.text, b, name)
            slot = Slot(s, w.text, None, b)
            interval = self.variables.intervals[slot]
            selector = self._all_of(conds, f"asks:{name}:{s}:{b}")
            self.asked_for.setdefault(slot, []).append(selector)
            if st.minutes is not None:
                self._add(_length(interval.size, st.minutes, st.length_bound), conds)
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
        """Whether enough others from the set, or all of them, share the instance `s` is on."""
        roles = self._roles(Choice(tuple(company.roles), POOL)) if company.roles else None
        together = [self._together(s, p, what, d, b, roles) for p in sorted(company.staff - {s})]
        terms = [t for t in together if not isinstance(t, bool)]
        constant = sum(t is True for t in together)
        if company.n is not None and company.bound != ast.AT_LEAST:
            amount = ast.Amount(company.bound, company.n, False, DEFAULT_POS)
            return self._compare(terms, constant, amount, name)
        n = len(together) if company.n is None else company.n
        if n > len(together):
            return False
        if n == len(together):
            return self._all_of(together, name)
        if n == 1:
            return self._any_of(together, name)
        return self._at_least(terms, constant, n, name)

    def _together(self, s: str, p: str, what, d: date, b: str, roles=None) -> Literal:
        """Whether `p` holds an assignment on the same instance as `s`, in `roles` or any.

        For a quoted task the same instance also means the same start time.
        """
        activity = what.text if isinstance(what, ast.Task) else what
        if d < self.dataset.target:
            mine = list(self.variables.was_member(s, activity, d, b))
            theirs = [
                a
                for a in self.variables.was_member(p, activity, d, b)
                if roles is None or a.role in roles
            ]
            if not isinstance(what, ast.Task):
                return bool(theirs)
            return any(a.start == a2.start for a in mine for a2 in theirs)
        if not isinstance(what, ast.Task):
            in_roles = "+".join(sorted(roles)) if roles else "any"
            return self._any_of(
                self.variables.members(p, activity, b, roles),
                f"member:{p}:{activity}:{b}:{in_roles}",
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
            free = self.variables.was_free(s, d, b)
            return not free if st.busy else free
        activity = w.text if isinstance(w, ast.Task) else w
        rows = list(self.variables.was_member(s, activity, d, b))
        if isinstance(w, ast.Task):
            held = any(
                st.minutes is None or _length(a.minutes, st.minutes, st.length_bound) for a in rows
            )
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
        """NOT DO: no assignment of a chosen staff member matches."""
        who = self._choose(st.who, active, f"{name}:staff")
        if _together(st.pattern):
            self._forbid_together(st, who, active, name)
            return
        for m in self._matches(st.pattern, past=False):
            self._imply(
                [active, who[m.staff]], m.literal if st.pattern.busy else _negate(m.literal)
            )

    def _forbid_together(self, st: Forbid, who: dict, active, name: str) -> None:
        """`NOT DO … DURING ALL {…}`: not every one of them together; any on its own is fine.

        What must not happen is the positive request the words to the right of NOT make: for
        every combination of the ALL items, an assignment matching it, where a part taken
        ANY is matched by any of its items. A combination nothing could ever match means
        the whole cannot happen, so nothing is forbidden. The past counts, since yesterday's
        half of "not on both days" is already settled.
        """
        together = _together(st.pattern)
        pattern = st.pattern
        found: dict[str, dict[tuple, list]] = {}
        for m in self._matches(pattern, past=True):
            key = tuple(getattr(m, field) for field, _ in together)
            found.setdefault(m.staff, {}).setdefault(key, []).append(m.literal)
        combinations = list(product(*(items for _, items in together)))
        for s, by_key in found.items():
            if any(c not in by_key for c in combinations):
                continue
            each = [
                self._any_of(by_key[c], f"{name}:{s}:{'+'.join(map(str, c))}") for c in combinations
            ]
            self._imply([active, who[s]], _negate(self._all_of(each, f"{name}:{s}:together")))

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
        return self._less(chosen, choice, name)

    def _less(self, chosen: dict, choice: Choice, name: str) -> dict:
        """A set less the names a binding chose: each member is in when it was not chosen."""
        for i, minus in enumerate(choice.minus):
            taken = self._choose_one(minus, True, f"{name}:minus{i}")
            for item, literal in taken.items():
                if item in chosen:
                    chosen[item] = self._all_of(
                        [chosen[item], _negate(literal)], f"{name}:less:{item}"
                    )
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
        """`ANY n CONSECUTIVE <blocks>`: the n chosen blocks are a run of adjacent ones.

        Blocks are adjacent when they are next to each other in the Blocks sheet, as they
        are for a CONSECUTIVE amount, on any of the dates the requirement is about. Exactly
        one such run is picked when the requirement is active, and it is what is chosen.
        """
        runs: set[tuple] = set()
        for day in days:
            order = [b.id for b in self.dataset.blocks_on(day)]
            for i in range(len(order) - n + 1):
                run = tuple(order[i : i + n])
                if all((day, b) in chosen for b in run):  # blocks on each of pooled dates
                    run = tuple((day, b) for b in run)
                if all(b in chosen for b in run):
                    runs.add(run)
        if not runs:
            self._imply([active], False)  # no n of them are ever next to each other
            return
        picked = {
            run: self.model.NewBoolVar(f"{name}:run:{'+'.join(map(str, run))}")
            for run in sorted(runs, key=str)
        }
        self.model.Add(sum(picked.values()) == active)
        for block, literal in chosen.items():
            self.model.Add(literal == sum(p for run, p in picked.items() if block in run))

    def _pool(self, choice: Choice | None) -> dict:
        """Each item of a pool with the condition for its membership: True, or a shared choice."""
        if choice is None:
            return {}
        if choice.var is None and not choice.parts:
            return self._less(dict.fromkeys(choice.items, True), choice, "pool")
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
                parts.append(self._length_is(row, pattern.minutes, pattern.length_bound))
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

    def _length_is(self, row: Row, minutes: int | None, bound: str = ast.EXACTLY) -> Literal:
        if minutes is None:
            return True
        if isinstance(row.minutes, int):
            return _length(row.minutes, minutes, bound)
        same = self.model.NewBoolVar(f"length:{row.staff}:{row.activity}:{row.block}:{minutes}")
        self.model.Add(_length(row.minutes, minutes, bound)).OnlyEnforceIf(same)
        self.model.Add(_length(row.minutes, minutes, _OPPOSITE[bound])).OnlyEnforceIf(same.Not())
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

    # -- tallies ---------------------------------------------------------------------------------

    def _tally(self, st: Tally, active: Literal, name: str) -> Literal:
        """A REQUEST with counts, or a FOR over a pool. Returns its being deferred."""
        deferred = self._enforce_levels(st, st.levels, st.pattern, active, name)
        return self._any_of(deferred, f"deferred:{name}")

    def _enforce_levels(self, st: Tally, levels, pattern: Pattern, active, name: str) -> list:
        """Post a tally's counts, outermost first, down to what each item they count asks for.

        AT_LEAST n chooses n items and asks the rest of the statement of each, which is also
        how the solver makes what they need. AT_MOST counts the items the rest holds for, and
        EXACTLY does both.
        """
        if not levels:
            return self._enforce_leaf(st, pattern, active, name)
        level, rest = levels[0], levels[1:]
        field = level.field
        choice = self._counted(level, pattern)
        deferred = []
        if choice.bound != ast.AT_MOST:
            chosen = self._choose(replace(choice, kind=ANY, bound=None), active, f"{name}:{field}")
            if choice.consecutive:
                self._adjacent(chosen, choice.n, pattern.on.items, active, f"{name}:{field}")
            for item, literal in chosen.items():
                fixed = _fixed(pattern, field, item)
                deferred += self._enforce_levels(st, rest, fixed, literal, f"{name}:{item}")
            later = [lit for item, lit in chosen.items() if _day(field, item) > self.dataset.target]
            deferred.append(self._any_of(later, f"{name}:later"))
        if choice.bound != ast.AT_LEAST:
            holds = self._each_holds(st, level, rest, pattern, name, ABOVE)
            if choice.consecutive:
                for window in self._windows_of(level, holds, pattern, choice.n + 1):
                    self._imply([active, *window], False)  # not every block of it
            else:
                terms, constant = _split(list(holds.values()))
                self._add(sum(terms) + constant <= choice.n, [active])
        return deferred

    def _enforce_leaf(self, st: Tally, pattern: Pattern, active, name: str) -> list:
        """What is left of a tally once each count has an item: a requirement, or a FOR."""
        if st.measure is None:
            during = pattern.during or Choice(self._day_blocks(pattern.on), POOL)
            requirement = Requirement(
                who=pattern.who,
                what=pattern.what,
                during=during,
                on=pattern.on,
                role=pattern.role,
                minutes=pattern.minutes,
                with_=pattern.with_,
                without=pattern.without,
                label=None,
                pos=pattern.pos,
                busy=pattern.busy,
                length_bound=pattern.length_bound,
            )
            return [self._require(requirement, active, name)[1]]
        return [
            self._measure(unit, st.measure, st.runs, active, f"{name}:unit{i}")
            for i, unit in enumerate(self._units(pattern))
        ]

    def _each_holds(
        self, st: Tally, level: Level, rest, pattern: Pattern, name: str, sense: str = EXACT
    ) -> dict:
        """A literal per thing a count counts: each item, and each group, all of it.

        `sense` is what the caller needs of the literals: EXACT both ways, ABOVE only that
        each is true when its item holds (enough for a cap), BELOW only that it is false
        when it does not (enough to reach a floor). Half of an equivalence is a smaller model
        that the solver propagates better.
        """
        direct = self._holds_by_item(st, level, rest, pattern, name, sense)

        def holds_at(item) -> Literal:
            if direct is not None:
                return direct.get(item, False)
            fixed = _fixed(pattern, level.field, item)
            return self._reify_levels(st, rest, fixed, f"{name}:{item}")

        if direct is not None:
            holds = dict(direct)  # an item with nothing that could match it holds for no one
        else:
            holds = {item: holds_at(item) for item in self._counted(level, pattern).items}
        for i, unit in enumerate(level.choice.units):
            each = [self._literal(holds_at(item), f"{name}:{item}") for item in unit.items]
            holds[("group", i)] = self._all_of(each, f"{name}:group{i}")
        return holds

    def _holds_by_item(
        self, st: Tally, level: Level, rest, pattern: Pattern, name, sense
    ) -> dict | None:
        """Each counted item's literal from one pass over the matches, where there can be one.

        When nothing is counted below this count and the pattern has no set taken ALL, an
        item holds when one of its own matches does, so the matches of the whole set are
        found once and grouped by item rather than found again for each. None otherwise.
        """
        if rest or (st.measure is not None and st.runs):
            return None
        members = set(level.choice.items) | {i for unit in level.choice.units for i in unit.items}
        attr = FIELDS[level.field]
        over_days = _over_days(level, pattern)
        pool = sorted(members, key=str)
        pooled = replace(pattern, **{attr: Choice(tuple(pool), POOL)})
        units = self._units(pooled)
        if len(units) != 1:
            return None
        grouped: dict = {}
        for m in self._matches(units[0], past=True):
            key = (m.date, m.block) if over_days else getattr(m, _MATCH_FIELD[level.field])
            grouped.setdefault(key, []).append(m)
        found = {}
        for item, matches in grouped.items():
            label = f"{name}:{item}"
            if st.measure is not None:
                terms, constant = self._amount(matches, True)
                found[item] = self._compare(terms, constant, st.measure, label)
            elif self._exclusive(matches):
                found[item] = Exclusive(m.literal for m in matches)
            else:
                found[item] = self._one_of([m.literal for m in matches], label, sense)
        return found

    def _exclusive(self, matches: list[Match]) -> bool:
        """Whether at most one of these can hold, so that their sum counts the item exactly.

        One person's whole-block assignments in one block on one date never overlap.
        """
        if len(matches) < 2:
            return False
        first = matches[0]
        return all(
            m.staff == first.staff
            and m.date == first.date
            and m.block == first.block
            and isinstance(m.minutes, int)
            and m.minutes == self.dataset.blocks[m.block].minutes
            for m in matches
        )

    def _literal(self, held, name: str) -> Literal:
        """An item's holds as one literal, where it was left as the sum of exclusive ones."""
        if isinstance(held, Exclusive):
            return self._any_of(list(held), name)
        return held

    def _one_of(self, literals: list, name: str, sense: str) -> Literal:
        """A literal for any of these being true, both ways or only the way `sense` asks."""
        if sense == EXACT or any(v is True for v in literals):
            return self._any_of(literals, name)
        real = _distinct([v for v in literals if v is not False])
        if len(real) < 2:
            return self._any_of(literals, name)
        var = self.model.NewBoolVar(name)
        if sense == ABOVE:
            for v in real:
                self.model.AddImplication(v, var)
        else:
            self.model.AddBoolOr(real).OnlyEnforceIf(var)
        return var

    def _reify_levels(self, st: Tally, levels, pattern: Pattern, name: str) -> Literal:
        """A literal equivalent to a tally holding, over past dates and today."""
        if not levels:
            return self._leaf_holds(st, pattern, name)
        level, rest = levels[0], levels[1:]
        holds = self._each_holds(st, level, rest, pattern, name)
        choice = level.choice
        if choice.consecutive:
            reaching = [
                self._all_of(window, f"{name}:run{i}")
                for i, window in enumerate(self._windows_of(level, holds, pattern, choice.n))
            ]
            exceeding = [
                self._all_of(window, f"{name}:long{i}")
                for i, window in enumerate(self._windows_of(level, holds, pattern, choice.n + 1))
            ]
            at_least = self._any_of(reaching, f"{name}:reached")
            at_most = _negate(self._any_of(exceeding, f"{name}:exceeded"))
            if choice.bound == ast.AT_LEAST:
                return at_least
            if choice.bound == ast.AT_MOST:
                return at_most
            return self._all_of([at_least, at_most], f"{name}:exact")
        terms, constant = _split(list(holds.values()))
        amount = ast.Amount(choice.bound, choice.n, False, DEFAULT_POS)
        return self._compare(terms, constant, amount, name)

    def _leaf_holds(self, st: Tally, pattern: Pattern, name: str) -> Literal:
        """Whether every unit of the pattern is matched, or measures up to its FOR."""
        parts = []
        for i, unit in enumerate(self._units(pattern)):
            matches = self._matches(unit, past=True)
            label = f"{name}:unit{i}"
            if st.measure is None:
                parts.append(self._any_of([m.literal for m in matches], label))
            elif st.runs:
                parts.append(self._runs_hold(st.measure, matches, label))
            else:
                terms, constant = self._amount(matches, True)
                parts.append(self._compare(terms, constant, st.measure, label))
        return self._all_of(parts, name)

    def _units(self, pattern: Pattern) -> list[Pattern]:
        """The pattern once per combination of the sets it takes ALL of, each a pool of one.

        A set taken whole is one unit: every one of its items must be matched, so each is
        matched, or measured, on its own.
        """
        split = []
        for attr in ("who", "what", "during", "on", "role"):
            choice = getattr(pattern, attr)
            if isinstance(choice, Choice) and choice.kind == ALL and not choice.parts:
                split.append((attr, [replace(choice, items=(i,), kind=POOL) for i in choice.items]))
        if not split:
            return [pattern]
        return [
            replace(pattern, **{attr: c for (attr, _), c in zip(split, combination, strict=True)})
            for combination in product(*(options for _, options in split))
        ]

    def _counted(self, level: Level, pattern: Pattern) -> Choice:
        """What a count counts: the items of its set, or for blocks, each one on each date.

        A block happens once a date, so where the dates are pooled a count of blocks is of
        every block on every one of those dates: clinic 1 on Monday and clinic 1 on Tuesday
        are two. Anywhere else the dates are one, or one at a time, and a block is itself.
        """
        if not _over_days(level, pattern):
            return level.choice
        items = tuple(
            (d, b.id)
            for d in pattern.on.items
            for b in self.dataset.blocks_on(d)
            if b.id in level.choice.items
        )
        return replace(level.choice, items=items)

    def _windows_of(self, level: Level, holds: dict, pattern: Pattern, length: int) -> list:
        """The literals of every `length` counted blocks in a row, in the Blocks sheet's order.

        A run never crosses from one date to the next.
        """
        days = pattern.on.items
        if _over_days(level, pattern):
            orders = [[(d, b.id) for b in self.dataset.blocks_on(d)] for d in days]
        elif len(days) == 1:
            orders = [[b.id for b in self.dataset.blocks_on(days[0])]]
        else:
            on_some = {b.id for d in days for b in self.dataset.blocks_on(d)}
            orders = [[b for b in self.dataset.blocks if b in on_some]]
        windows = []
        for order in orders:
            run = []
            for key in order:
                if key not in holds or holds[key] is False:
                    run = []
                    continue
                run.append(key)
                if len(run) >= length:
                    windows.append(run[-length:])
        # only the blocks some window reaches need a literal of their own
        literal = {k: self._literal(holds[k], f"run:{k}") for k in {k for w in windows for k in w}}
        return [[literal[k] for k in window] for window in windows]

    def _day_blocks(self, on: Choice) -> tuple[str, ...]:
        blocks = {b.id for d in on.items for b in self.dataset.blocks_on(d)}
        return tuple(sorted(blocks))

    def _tally_miss(self, st: Tally, name: str) -> tuple:
        """How far a PREFER is from its outermost count, or from its FOR; (0, 0) when fixed."""
        if not st.levels:
            misses, bound = [], 0
            for i, unit in enumerate(self._units(st.pattern)):
                miss, most = self._miss(st.measure, unit, st.runs, f"{name}:unit{i}")
                if not isinstance(miss, int):
                    misses.append(miss)
                    bound += most
            if len(misses) < 2:
                return (misses[0], bound) if misses else (0, 0)
            total = self.model.NewIntVar(0, bound, f"miss:{name}")
            self.model.Add(total == sum(misses))
            return total, bound
        level, rest = st.levels[0], st.levels[1:]
        choice, n = level.choice, level.choice.n
        sense = {ast.AT_MOST: ABOVE, ast.AT_LEAST: BELOW}.get(choice.bound, EXACT)
        holds = self._each_holds(
            st, level, rest, st.pattern, name, EXACT if choice.consecutive else sense
        )
        if choice.consecutive:
            return self._runs_miss(level, holds, st.pattern, name)
        terms, constant = _split(list(holds.values()))
        if not terms:
            return 0, 0
        bound = max(n, len(holds))
        miss = self.model.NewIntVar(0, bound, f"miss:{name}")
        total = sum(terms) + constant
        if choice.bound != ast.AT_MOST:
            self.model.Add(miss >= n - total)
        if choice.bound != ast.AT_LEAST:
            self.model.Add(miss >= total - n)
        return miss, bound

    def _runs_miss(self, level: Level, holds: dict, pattern: Pattern, name: str) -> tuple:
        """How far the runs of counted blocks are from a CONSECUTIVE count."""
        choice, n = level.choice, level.choice.n
        runs = []
        for length in range(1, len(holds) + 1):
            for i, window in enumerate(self._windows_of(level, holds, pattern, length)):
                present = self._all_of(window, f"{name}:run{length}:{i}")
                if present is not False:
                    runs.append((length, present))
        if not runs:
            return 0, 0
        bound = max(n, max(length for length, _ in runs))
        miss = self.model.NewIntVar(0, bound, f"miss:{name}")
        if choice.bound != ast.AT_LEAST:
            for length, present in runs:
                if length > n:
                    self._add(miss >= length - n, [present])
        if choice.bound != ast.AT_MOST:
            reaches = []
            for i, (length, present) in enumerate(runs):
                reach = self.model.NewIntVar(0, length, f"{name}:reach{i}")
                self._add(reach == length, [present])
                self._add(reach == 0, [_negate(present)])
                reaches.append(reach)
            best = self.model.NewIntVar(0, bound, f"{name}:best_run")
            self.model.AddMaxEquality(best, reaches)
            self.model.Add(miss >= n - best)
        return miss, bound

    def _allow_partial(self, matches: list[Match], name: str) -> None:
        """A FOR over a pool fills whole blocks, all but one of which may be cut short.

        A task with no FOR of its own fills its block; this lets one of the pieces a length
        is made of be shorter, so two hours and six minutes over one-hour blocks is two
        blocks and six minutes of a third.
        """
        target = self.dataset.target
        partial = []
        for m in matches:
            if m.date != target or isinstance(m.minutes, int):
                continue
            cut = self.model.NewBoolVar(f"{name}:partial:{m.staff}:{m.activity}:{m.block}")
            self.shortened.setdefault(Slot(m.staff, m.activity, None, m.block), []).append(cut)
            partial.append(cut)
        if len(partial) > 1:
            self.model.Add(sum(partial) <= 1)

    def _measure(self, p: Pattern, amount, consecutive: bool, active, name: str) -> Literal:
        """A FOR over a pool. Returns the literal for its being deferred."""
        n = amount.value
        target = self.dataset.target
        later = [d for d in p.on.items if d > target]
        capacity = 0
        if later and amount.bound != ast.AT_MOST:
            capacity = self._capacity(p, later, amount.duration, consecutive)
        matches = self._matches(p, past=True)
        self._allow_partial(matches, name)
        if amount.bound != ast.AT_MOST:
            self._ask_for(matches, p, active)
        # a run must fit inside one date, so it defers only to a date that can hold all of it
        due = n if consecutive else 1
        if capacity < due:  # later dates cannot hold the remainder, so it is all due today
            self._enforce(amount, matches, consecutive, [active], name)
            return False
        # deferrable: today it must only stay reachable, and progress earns the early bonus
        if consecutive:
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


def _fixed(pattern: Pattern, field: str, item) -> Pattern:
    """A pattern with one of its fields down to one item: the one a count is at.

    A block counted over pooled dates is a block on a date, so both come down to one.
    """
    if field == "block" and isinstance(item, tuple):
        day, block = item
        pattern = replace(pattern, on=Choice((day,), ALL, pos=pattern.on.pos))
        item = block
    choice = getattr(pattern, FIELDS[field])
    return replace(pattern, **{FIELDS[field]: Choice((item,), ALL, pos=choice.pos)})


def _over_days(level: Level, pattern: Pattern) -> bool:
    """Whether a count of blocks is over several pooled dates, each block on each of them."""
    on = pattern.on
    return level.field == "block" and on.kind == POOL and len(on.items) > 1


def _day(field: str, item) -> date:
    """The date a counted item is on, where it is on one; else no later than any."""
    if field == "date":
        return item
    if field == "block" and isinstance(item, tuple):
        return item[0]
    return date.min


class Exclusive(list):
    """Literals at most one of which can hold, standing for their sum rather than a literal."""


def _split(literals: list) -> tuple[list, int]:
    """Literals as variable terms and the number of them that are true already.

    An Exclusive group is its members, whose sum is exactly whether any of them holds.
    """
    flat = [x for held in literals for x in (held if isinstance(held, Exclusive) else [held])]
    terms = [x for x in flat if not isinstance(x, bool)]
    return terms, sum(1 for x in flat if x is True)


_OPPOSITE = {
    ast.EXACTLY: "DIFFERS",
    ast.AT_LEAST: "BELOW",
    ast.AT_MOST: "ABOVE",
}


def _length(value, minutes: int, bound: str):
    """`value` compared with `minutes` by a FOR's bound, or by its opposite."""
    if bound == ast.EXACTLY:
        return value == minutes
    if bound == ast.AT_LEAST:
        return value >= minutes
    if bound == ast.AT_MOST:
        return value <= minutes
    if bound == "DIFFERS":
        return value != minutes
    if bound == "BELOW":
        return value <= minutes - 1
    return value >= minutes + 1


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


def _together(pattern: Pattern) -> list[tuple[str, tuple]]:
    """The parts of a NOT's pattern written ALL, as the Match field each one fills."""
    parts = (("activity", pattern.what), ("block", pattern.during), ("date", pattern.on))
    parts += (("role", pattern.role),)
    return [
        (field, choice.items)
        for field, choice in parts
        if isinstance(choice, Choice) and choice.kind == ALL
    ]


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
