"""The calendar pane: a month of camp days, each week labelled with its session and week.

Qt's calendar puts the ISO week of the year down the left-hand side, which is a number
nobody at camp uses. The delegate below paints the Calendar sheet's own numbering there
instead, so `S4 / W2` next to a row says that row is the second week of session 4 — the
week `date.session.four.second_week` stands for.
"""

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QTextCharFormat
from PySide6.QtWidgets import QCalendarWidget, QStyledItemDelegate, QTableView

from puppet_strings.app import palette
from puppet_strings.model import Dataset

CAMP_DAY = QColor(palette.CAMP_DAY)
ROWS = range(1, 7)  # row 0 of the grid holds the weekday names


class WeekLabel(QStyledItemDelegate):
    """Paints `S<session>` over `W<week>` in the calendar's left-hand column."""

    def __init__(self, calendar: "SessionCalendar") -> None:
        super().__init__(calendar)
        self.calendar = calendar

    def paint(self, painter, option, index) -> None:
        """Label the week this row shows; rows outside camp are left blank."""
        session, week = self.calendar.week_of_row(index.row())
        if session is None:
            return
        painter.save()
        font = QFont(option.font)
        font.setPointSizeF(max(6.5, option.font.pointSizeF() - 1.5))
        painter.setFont(font)
        painter.setPen(option.palette.color(QPalette.Disabled, QPalette.Text))
        painter.drawText(option.rect, Qt.AlignCenter, f"S{session}\nW{week}")
        painter.restore()


class SessionCalendar(QCalendarWidget):
    """A calendar that shades camp days and numbers its weeks the way the sheet does."""

    picked = Signal(date)

    def __init__(self) -> None:
        super().__init__()
        self.days: dict[date, tuple[int, int]] = {}
        self.setGridVisible(True)
        self.setVerticalHeaderFormat(QCalendarWidget.ISOWeekNumbers)  # keeps the column
        view = self.findChild(QTableView, "qt_calendar_calendarview")
        view.setItemDelegateForColumn(0, WeekLabel(self))
        self.view = view
        self.currentPageChanged.connect(lambda *_: view.viewport().update())
        self.clicked.connect(lambda day: self.picked.emit(day.toPython()))

    def show_dataset(self, dataset: Dataset | None) -> None:
        """Shade the dates on the Calendar sheet and label their weeks.

        Any date can still be picked; a date off the sheet is simply not a camp day.
        """
        self.setDateTextFormat(QDate(), QTextCharFormat())  # clear old marks
        if dataset is None:
            self.days = {}
            return
        self.days = {d: (day.session, day.week) for d, day in dataset.calendar.items()}
        camp_day = QTextCharFormat()
        camp_day.setBackground(CAMP_DAY)
        for day in dataset.calendar:
            self.setDateTextFormat(QDate(day), camp_day)
        self.setSelectedDate(QDate(dataset.target))
        self.setCurrentPage(dataset.target.year, dataset.target.month)
        self.view.viewport().update()

    def week_of_row(self, row: int) -> tuple[int | None, int | None]:
        """The session and week the grid's row falls in, from its first camp day."""
        start = self.row_start(row)
        if start is None:
            return None, None
        for day in (start.addDays(i) for i in range(7)):
            numbered = self.days.get(day.toPython())
            if numbered is not None:
                return numbered
        return None, None

    def row_start(self, row: int) -> QDate | None:
        """The date in the row's first column, laid out the way Qt lays the month out."""
        if row not in ROWS:
            return None
        first = QDate(self.yearShown(), self.monthShown(), 1)
        offset = self.firstDayOfWeek().value - first.dayOfWeek()
        return first.addDays(offset - 7 if offset > 0 else offset).addDays((row - 1) * 7)
