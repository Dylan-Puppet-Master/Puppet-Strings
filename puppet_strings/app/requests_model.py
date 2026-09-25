"""Qt models for the request table: the rows and the filters over them."""

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QMimeData, QSortFilterProxyModel, Qt

from puppet_strings.app.groups import ALL, UNGROUPED, same_group
from puppet_strings.app.store import RequestStore
from puppet_strings.model import Request

COLUMNS = ("id", "priority", "group", "tags", "requester", "description")
REQUEST_IDS = "application/x-puppet-strings-requests"  # what a dragged row carries


def request_ids(data: QMimeData) -> list[str]:
    """The ids a drag of rows carries, in the order they were picked up."""
    return [i for i in bytes(data.data(REQUEST_IDS)).decode().split("\n") if i]


class RequestsModel(QAbstractTableModel):
    """One row per request in the file, whatever date it is scoped to.

    The rows are the store's requests as they were at the last `refresh`, which everything
    that changes them calls. Sorting asks for every cell of every row, and the store makes
    its list afresh each time it is asked: with hundreds of requests, asking it per cell
    made every save wait a third of a second on a table that was often not even shown.
    """

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.rows: list[Request] = list(store.every)
        self.cells: dict[int, tuple[str, ...]] = {}  # each row's text, once asked for

    def refresh(self) -> None:
        """Tell views the store changed."""
        self.beginResetModel()
        self.rows = list(self.store.every)
        self.cells = {}
        self.endResetModel()

    def rowCount(self, parent=None) -> int:  # noqa: N802
        """Number of requests."""
        if parent is not None and parent.isValid():
            return 0
        return len(self.rows)

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
        row = index.row()
        if role == Qt.UserRole:
            return self.rows[row]
        if role != Qt.DisplayRole:
            return None
        if row not in self.cells:
            request = self.rows[row]
            self.cells[row] = (  # in the order of COLUMNS
                request.id,
                request.priority.value,
                request.group,
                ", ".join(request.tags),
                request.requester,
                request.description,
            )
        return self.cells[row][index.column()]

    def request(self, request_id: str) -> Request | None:
        """The request with this id."""
        return next((r for r in self.rows if r.id == request_id), None)

    def flags(self, index):
        """Rows can be picked up, which is how a request is moved to another group."""
        return super().flags(index) | Qt.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:  # noqa: N802
        """A drag carries the ids of the requests picked up, and nothing else."""
        return [REQUEST_IDS]

    def mimeData(self, indexes):  # noqa: N802
        """The ids of the rows being dragged, one per line."""
        ids = dict.fromkeys(self.rows[i.row()].id for i in indexes if i.isValid())
        data = QMimeData()
        data.setData(REQUEST_IDS, "\n".join(ids).encode())
        return data


class RequestFilter(QSortFilterProxyModel):
    """Filters by group, text, priority, tag, staff, activity, and date."""

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.text = ""
        self.group = ALL
        self.priority: str | None = None
        self.tag: str | None = None
        self.staff: str | None = None
        self.activity: str | None = None
        self.date: date | None = None

    def set_filters(self, **filters) -> None:
        """Update any of the filter attributes and refilter."""
        keep_empty = ("text", "group")
        self.beginFilterChange()
        for name, value in filters.items():
            setattr(self, name, value if name in keep_empty else value or None)
        # Which rows pass, not their order: the rows kept stay sorted, and a sort is what
        # costs, as it asks for every cell over and over.
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def _in_group(self, request: Request) -> bool:
        """Whether a request belongs on the shelf the groups pane is showing."""
        if self.group == ALL:
            return True
        if self.group == UNGROUPED:
            return not request.group
        return same_group(self.group, request.group)

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        """Whether the request at this source row is on the group shown and passes the rest."""
        request = self.sourceModel().rows[row]
        return self._in_group(request) and self.passes(request)

    def passes(self, request: Request) -> bool:
        """Whether a request passes every filter but the group, which is what a group counts.

        With a date, a request passes when it is read on that date and is about it. One
        that does not validate is about nothing anybody can tell, so the date lets it
        through rather than hiding a broken request from the view it would be fixed in.
        """
        text = (self.text or "").lower()
        haystack = f"{request.id} {request.description} {request.skedge} {request.requester}"
        if text and text not in haystack.lower():
            return False
        if self.priority and request.priority.value != self.priority:
            return False
        if self.tag and self.tag not in request.tags:
            return False
        if self.date and request.scope is not None and not request.scope.covers(self.date):
            return False
        if not (self.staff or self.activity or self.date):
            return True
        if self.store.dataset is None:
            return False  # no date loaded: nothing to resolve a name or a date against
        facet = self.store.facet(request)
        if self.staff and self.staff not in facet.staff:
            return False
        if self.activity and self.activity not in facet.activities:
            return False
        return not self.date or not facet.valid or self.date in facet.dates
