"""Which Requests tab each group's new requests are written to.

A group is a shelf in the request manager, and most shelves are about one thing: the
special requests for a session sit on one, the standing agreements that hold all season on
another. Saying so once, on the group, saves saying it on every request made there.

Only *new* requests are affected. A request already written somewhere stays where it is —
its tab is when it applies, and changing that because a group's default changed would move
requests nobody asked to move.
"""

from puppet_strings.app.groups import same_group
from puppet_strings.settings import load_settings, save_settings


class GroupTabs:
    """The default tab per group, kept in the settings file between runs."""

    def __init__(self) -> None:
        self.tabs = dict(load_settings().group_tabs)

    def of(self, group: str) -> str:
        """The tab new requests in this group go to, or "" if nothing was said."""
        for name, tab in self.tabs.items():
            if same_group(name, group):
                return tab
        return ""

    def set(self, group: str, tab: str) -> None:
        """Say where this group's new requests go. An empty tab clears it."""
        self.forget(group)
        if tab:
            self.tabs[group] = tab
        self._save()

    def rename(self, old: str, new: str) -> None:
        """Follow a group that has been renamed."""
        tab = self.of(old)
        self.forget(old)
        if tab:
            self.tabs[new] = tab
        self._save()

    def forget(self, group: str) -> None:
        """Drop whatever was said about a group, without writing the file."""
        self.tabs = {n: t for n, t in self.tabs.items() if not same_group(n, group)}

    def _save(self) -> None:
        from dataclasses import replace

        save_settings(replace(load_settings(), group_tabs=dict(self.tabs)))
