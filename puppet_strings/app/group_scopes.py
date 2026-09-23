"""The scope each group's new requests take.

A group is a shelf in the request manager, and most shelves are about one thing: the
special requests for a session sit on one, the standing agreements that hold all season on
another. Saying so once, on the group, saves saying it on every request made there.

Only *new* requests are affected. A request already written keeps its scope — its scope is
when it applies, and changing that because a group's default changed would move requests
nobody asked to move.
"""

from dataclasses import replace

from puppet_strings.app.groups import same_group
from puppet_strings.settings import load_settings, save_settings


class GroupScopes:
    """The default scope kind per group, kept in the settings file between runs."""

    def __init__(self) -> None:
        self.scopes = dict(load_settings().group_scopes)

    def of(self, group: str) -> str:
        """The scope kind new requests in this group take, or "" if nothing was said."""
        for name, kind in self.scopes.items():
            if same_group(name, group):
                return kind
        return ""

    def set(self, group: str, kind: str) -> None:
        """Say what scope this group's new requests take. An empty one clears it."""
        self.forget(group)
        if kind:
            self.scopes[group] = kind
        self._save()

    def rename(self, old: str, new: str) -> None:
        """Follow a group that has been renamed."""
        kind = self.of(old)
        self.forget(old)
        if kind:
            self.scopes[new] = kind
        self._save()

    def forget(self, group: str) -> None:
        """Drop whatever was said about a group, without writing the file."""
        self.scopes = {n: k for n, k in self.scopes.items() if not same_group(n, group)}

    def _save(self) -> None:
        save_settings(replace(load_settings(), group_scopes=dict(self.scopes)))
