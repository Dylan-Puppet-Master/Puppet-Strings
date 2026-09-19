"""The calendar pane: a month of camp days, each week labelled with its session and week.

Qt's calendar puts the ISO week of the year down the left-hand side, which is a number
nobody at camp uses. The delegate below paints the Calendar sheet's own numbering there
instead, so `S4 / W2` next to a row says that row is the second week of session 4 — the
week `dates.session.four.second_week` stands for.
"""

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QTextCharFormat
from PySide6.QtWidgets import QCalendarWidget, QStyledItemDelegate, QTableView

from puppet_strings.app import palette
from puppet_strings.model import Dataset

CAMP_DAY = QColor(palette.CAMP_DAY)
TEXT = QColor(palette.TEXT)
QUIET = QColor(palette.QUIET)
INK = QColor(palette.INK)  # a shaded cell needs its own text colour; the palette is not asked
ROWS = range(1, 7)  # row 0 of the grid holds the weekday names


class WeekLabel(QStyledItemDelegate):
    """Paints `S<session>` over `W<week>` in the calendar's left-hand column."""

    def __init__(self, calendar: "SessionCalendar") -> None:
        super().__init__(calendar)
        self.calendar = calendar

    def paint(self, painter, option, index) -> None:
        """Label the week this row shows; rows outside camp are left blank."""
        session, week = self.calendar.week_of_row(index.row())
        if week is None:
            return
        # A span that is not a numbered session has a week but no S to put above it.
        label = f"S{session}\nW{week}" if session is not None else f"W{week}"
        painter.save()
        font = QFont(option.font)
        font.setPointSizeF(max(6.5, option.font.pointSizeF() - 1.5))
        painter.setFont(font)
        painter.setPen(option.palette.color(QPalette.Disabled, QPalette.Text))
        painter.drawText(option.rect, Qt.AlignCenter, label)
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
        self._even_out_the_week()
        self.view = view
        self.currentPageChanged.connect(lambda *_: view.viewport().update())
        self.clicked.connect(lambda day: self.picked.emit(day.toPython()))

    def _even_out_the_week(self) -> None:
        """Write every weekday in the same ink, and the column of names in a quieter one.

        Qt paints Saturday and Sunday red, which on a dark window reads as an error rather
        than a weekend and collides with the red the conflicts pane uses. Camp runs seven
        days a week anyway: it is the shading that says which days are camp days.
        """
        day = QTextCharFormat()
        day.setForeground(TEXT)
        for weekday in Qt.DayOfWeek:
            self.setWeekdayTextFormat(weekday, day)
        heading = QTextCharFormat()
        heading.setForeground(QUIET)
        self.setHeaderTextFormat(heading)

    def show_dataset(self, dataset: Dataset | None) -> None:
        """Shade the dates on the Calendar sheet and label their weeks."""
        if dataset is None:
            self.show_calendar({})
            return
        self.show_calendar(dataset.calendar, dataset.target)

    def show_calendar(self, calendar: dict, target: date | None = None) -> None:
        """Shade and number the days the Calendar sheet covers, and go to `target`.

        This takes the Calendar sheet and nothing else, because the Calendar sheet and
        nothing else is what the session and week numbers are: a season whose Skills tab
        has a bad row still knows which week of which session it is in, and saying so is
        the pane's whole job. A load that fails part way still calls this.

        Any date can still be picked; a date off the sheet is simply not a camp day.
        """
        self.setDateTextFormat(QDate(), QTextCharFormat())  # clear old marks
        self.days = {d: (day.session, day.week) for d, day in calendar.items()}
        camp_day = QTextCharFormat()
        camp_day.setBackground(CAMP_DAY)
        camp_day.setForeground(INK)  # a cell with a colour of its own says what to write on it
        for day in calendar:
            self.setDateTextFormat(QDate(day), camp_day)
        if target is not None:
            self.setSelectedDate(QDate(target))
            self.setCurrentPage(target.year, target.month)
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
