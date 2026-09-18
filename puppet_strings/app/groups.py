"""Request groups: the shelves the request manager sorts requests onto.

A group is a label a request carries, like a tag, but it is what the left-hand pane
switches between rather than what the filters narrow by. A request may sit in several
groups or in none. There are three groups to begin with; the Puppet Master makes the rest.
"""

from puppet_strings.model import CLINIC_GROUP, DEFAULT_GROUPS

__all__ = ["ALL", "CLINIC_GROUP", "DEFAULT_GROUPS", "UNGROUPED", "clean", "groups_of", "same_group"]

ALL = "All requests"  # the two pane entries that are not groups
UNGROUPED = "Ungrouped"


def clean(name: str) -> str:
    """A group name as it will be stored: trimmed, and with no comma to split it in two."""
    return " ".join(name.replace(",", " ").split())


def same_group(one: str, other: str) -> bool:
    """Whether two names mean the same group. Case and spacing do not make a new group."""
    return clean(one).lower() == clean(other).lower()


def groups_of(request, groups: list[str]) -> tuple[str, ...]:
    """A request's groups, spelled the way the pane spells them."""
    return tuple(known for known in groups if any(same_group(known, g) for g in request.groups))
