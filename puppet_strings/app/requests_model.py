"""Qt models for the request table: the rows and the filters over them."""

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt

from puppet_strings.app.groups import ALL, UNGROUPED, same_group
from puppet_strings.app.store import RequestStore
from puppet_strings.model import Request

COLUMNS = ("id", "priority", "scope", "groups", "tags", "requester", "valid", "description")


class RequestsModel(QAbstractTableModel):
    """One row per request in the store."""

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store

    def refresh(self) -> None:
        """Tell views the store changed."""
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent=None) -> int:  # noqa: N802
        """Number of requests."""
        if parent is not None and parent.isValid():
            return 0
        return len(self.store.requests)

    def columnCount(self, parent=None) -> int:  # noqa: N802
        """Number of columns."""
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        """Column titles."""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        """Cell text, or the Request itself for UserRole."""
        request = self.store.requests[index.row()]
        if role == Qt.UserRole:
            return request
        if role != Qt.DisplayRole:
            return None
        facet = self.store.facets.get(request.id)
        return {
            "id": request.id,
            "priority": request.priority.value,
            "scope": facet.scope if facet else "",
            "groups": ", ".join(request.groups),
            "tags": ", ".join(request.tags),
            "requester": request.requester,
            "description": request.description,
            "valid": "" if facet is None or facet.valid else "error",
        }[COLUMNS[index.column()]]

    def request(self, request_id: str) -> Request | None:
        """The request with this id."""
        return next((r for r in self.store.requests if r.id == request_id), None)


class RequestFilter(QSortFilterProxyModel):
    """Filters by group, text, priority, scope, tag, staff, activity, and date."""

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.text = ""
        self.group = ALL
        self.priority: str | None = None
        self.scope: str | None = None
        self.tag: str | None = None
        self.staff: str | None = None
        self.activity: str | None = None
        self.date: date | None = None

    def set_filters(self, **filters) -> None:
        """Update any of the filter attributes and refilter."""
        keep_empty = ("text", "group")
        for name, value in filters.items():
            setattr(self, name, value if name in keep_empty else value or None)
        self.invalidate()

    def _in_group(self, request: Request) -> bool:
        """Whether a request belongs on the shelf the groups pane is showing."""
        if self.group == ALL:
            return True
        if self.group == UNGROUPED:
            return not request.groups
        return any(same_group(self.group, group) for group in request.groups)

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        """Whether the request at this source row passes every active filter."""
        request = self.store.requests[row]
        facet = self.store.facets.get(request.id)
        if not self._in_group(request):
            return False
        text = (self.text or "").lower()
        haystack = f"{request.id} {request.description} {request.skedge} {request.requester}"
        if text and text not in haystack.lower():
            return False
        if self.priority and request.priority.value != self.priority:
            return False
        if self.tag and self.tag not in request.tags:
            return False
        if facet is None:
            return not (self.scope or self.staff or self.activity or self.date)
        if self.scope and facet.scope != self.scope:
            return False
        if self.staff and self.staff not in facet.staff:
            return False
        if self.activity and self.activity not in facet.activities:
            return False
        return not self.date or self.date in facet.dates
