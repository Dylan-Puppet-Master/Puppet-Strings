"""What a name in the Namespaces pane stands for, spelled out.

The pane lists every name and a one-line note. That is enough to write a request and not
enough to check one: a category's note says how many people are in it, not who, and an
activity's says nothing about who may run it, which is the whole question now that a
request for an activity names nobody. So a name can be opened, and this works out what to
show for it.

Dates and roles have nothing to add — a date's note is the date, and a role is a word — so
they open nothing. Mappings open their table instead, because a mapping is worth editing
rather than reading.
"""

from dataclasses import dataclass, replace

from puppet_strings.model import Activity, Dataset, SkillStatus, Staff
from puppet_strings.skedge.namespaces import (
    ACTIVITIES,
    ALL,
    CABIN_ACTS,
    CLINICS,
    MAPPINGS,
    OFFERINGS,
    STAFF,
)

NOBODY = "nobody on the sheets today"
CHECKED = "✓"  # how the Skills tab writes a plain checkoff, and how it is shown back


@dataclass(frozen=True)
class Section:
    """One headed block of the popup: label and value per row."""

    heading: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Details:
    """What to show for one name."""

    title: str
    subtitle: str
    sections: tuple[Section, ...]


def is_mapping(name: str) -> bool:
    """Whether a name opens its mapping table rather than a popup."""
    return name.startswith(f"{MAPPINGS}.")


def details(name: str, dataset: Dataset) -> Details | None:
    """What to show for a name, or None if it has nothing worth showing."""
    namespace, _, rest = name.partition(".")
    if namespace == STAFF:
        return _staff(name, rest, dataset)
    if namespace == ACTIVITIES:
        return _activities(name, rest, dataset)
    return None  # dates say the date, roles say the role, mappings open their table


# -- staff ------------------------------------------------------------------------------


def _staff(name: str, rest: str, dataset: Dataset) -> Details | None:
    member = dataset.staff.get(rest)
    if member is not None:
        return _member(name, member, dataset)
    # the sheets file everyone at camp under `all`, which is written as `staff` alone
    members = None if rest == ALL else dataset.staff_categories.get(rest or ALL)
    if members is None:
        return None
    return Details(
        title=name,
        subtitle=f"{len(members)} working today",
        sections=(Section("Members", _people(members, dataset)),),
    )


def _member(name: str, member: Staff, dataset: Dataset) -> Details:
    """One staff member: where they stand on every skill, and what they are counted among."""
    skills = tuple(
        (skill, _standing(member, skill))
        for skill, status in sorted(member.skills.items())
        if status is not SkillStatus.NONE
    )
    others = tuple(
        (f"{STAFF}.{category}", "")
        for category, ids in sorted(dataset.staff_categories.items())
        if member.id in ids
    )
    return Details(
        title=name,
        subtitle=f"{member.name}, RAL {member.ral}",
        sections=(
            Section("Skills", skills or (("nothing yet", ""),)),
            Section("In these categories", others),
        ),
    )


def _standing(member: Staff, skill: str) -> str:
    """Where a staff member stands on one skill, in the Skills tab's own word.

    A plain checkoff is shown as the tick it is written as; everything else keeps the word
    the sheet used, because `WCF` and `w/ scaf` say more than the status they map to.
    """
    word = member.written.get(skill, "").strip()
    if not word or word == CHECKED:
        return CHECKED if member.skills[skill].eligible else word
    return word


def _people(ids, dataset: Dataset) -> tuple[tuple[str, str], ...]:
    rows = tuple((dataset.staff[i].name, f"RAL {dataset.staff[i].ral}") for i in sorted(ids))
    return rows or ((NOBODY, ""),)


# -- activities -------------------------------------------------------------------------


def _activities(name: str, rest: str, dataset: Dataset) -> Details | None:
    branch, _, leaf = rest.partition(".")
    if branch == CABIN_ACTS:
        return _cabin_act(name, rest, dataset)
    if branch == CLINICS and leaf in dataset.activities:
        return _activity(name, dataset.activities[leaf], dataset)
    if branch == CLINICS and leaf.partition(".")[0] == OFFERINGS:
        return _offerings(name, rest, dataset)
    return _set_of_activities(name, rest, dataset)


def _offerings(name: str, rest: str, dataset: Dataset) -> Details | None:
    """One offering is its clinic, at its time; several are listed, each at its time."""
    from puppet_strings.skedge.resolve import activity_names, offering_id

    named = activity_names(dataset).get(rest)
    if named is None:
        return None
    offered = {offering_id(o): o for o in dataset.offerings}
    if named.single:
        offering = offered[next(iter(named.items))]
        found = _activity(name, dataset.activities[offering.activity], dataset)
        return replace(found, subtitle=f"{found.subtitle} in {', '.join(offering.blocks)}")
    rows = tuple(
        (dataset.activities[o.activity].name, ", ".join(o.blocks))
        for o in sorted((offered[i] for i in named.items), key=lambda o: (o.blocks, o.activity))
    )
    return Details(
        title=name,
        subtitle=f"{len(rows)} offered on {dataset.target}",
        sections=(Section("It holds", rows or (("nothing", ""),)),),
    )


def _cabin_act(name: str, rest: str, dataset: Dataset) -> Details | None:
    """Today's act for one cabin, card and all; several are listed."""
    from puppet_strings.skedge.resolve import activity_names

    named = activity_names(dataset).get(rest)
    if named is not None and named.single:
        return _activity(name, dataset.activities[next(iter(named.items))], dataset, card=True)
    return _set_of_activities(name, rest, dataset)


def _activity(name: str, activity: Activity, dataset: Dataset, card: bool = False) -> Details:
    """An activity's positions: what each asks for, and who on the sheets could hold it."""
    wanted = tuple(
        (
            f"{position.role}: {_asks_for(position)}",
            ", ".join(sorted(m.name for m in dataset.staff.values() if position.allows(m)))
            or NOBODY,
        )
        for position in activity.positions
    )
    sections = [Section("It asks for", wanted or (("nobody", ""),))]
    if card and activity.card:
        sections.append(Section("On the cabin act board", activity.card))
    return Details(
        title=name,
        subtitle=f"{activity.name}{f' on {activity.day}' if activity.day else ''}",
        sections=tuple(sections),
    )


def _asks_for(position) -> str:
    """How one position was asked for, in the words it was asked in."""
    if position.wanted:
        return position.wanted
    if position.skill:
        return f"{position.skill} at RAL {position.ral}"
    return f"anyone at RAL {position.ral}"


def _set_of_activities(name: str, rest: str, dataset: Dataset) -> Details | None:
    """A name standing for several activities lists them."""
    from puppet_strings.skedge.resolve import activity_names

    named = activity_names(dataset).get(rest)
    if named is None:
        return None
    rows = tuple(
        (dataset.activities[i].name, dataset.activities[i].day.isoformat())
        if dataset.activities[i].day
        else (dataset.activities[i].name, "")
        for i in sorted(named.items)
    )
    return Details(
        title=name,
        subtitle=f"{len(rows)} activities",
        sections=(Section("It holds", rows or (("nothing", ""),)),),
    )
