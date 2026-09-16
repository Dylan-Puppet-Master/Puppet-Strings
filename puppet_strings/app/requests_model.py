"""Qt models for the request table: the rows and the filters over them."""

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt

from puppet_strings.app.store import RequestStore
from puppet_strings.model import Request

COLUMNS = ("id", "priority", "scope", "tags", "valid", "description")


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
            "tags": ", ".join(request.tags),
            "description": request.description,
            "valid": "" if facet is None or facet.valid else "error",
        }[COLUMNS[index.column()]]

    def request(self, request_id: str) -> Request | None:
        """The request with this id."""
        return next((r for r in self.store.requests if r.id == request_id), None)


class RequestFilter(QSortFilterProxyModel):
    """Filters by text, priority, scope, tag, staff, activity, and date."""

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.text = ""
        self.priority: str | None = None
        self.scope: str | None = None
        self.tag: str | None = None
        self.staff: str | None = None
        self.activity: str | None = None
        self.date: date | None = None

    def set_filters(self, **filters) -> None:
        """Update any of the filter attributes and refilter."""
        for name, value in filters.items():
            setattr(self, name, value if name == "text" else value or None)
        self.invalidate()

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        """Whether the request at this source row passes every active filter."""
        request = self.store.requests[row]
        facet = self.store.facets.get(request.id)
        text = (self.text or "").lower()
        if text and text not in f"{request.id} {request.description} {request.skedge}".lower():
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
