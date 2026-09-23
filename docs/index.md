# Puppet Strings

Puppet Strings builds the daily staff schedule for Camp Augusta. The Puppet Master keeps
camp data in Google Sheets, writes scheduling rules as **requests** in a small language
called **Skedge**, and presses Solve. The solver assigns staff to the clinics on the
Offerings sheet, fits in breaks, counselor hours and other tasks, and publishes two
printable views back to Google Sheets.

![The request manager](img/app.png)

## The daily loop

1. Fill in tomorrow's **Offerings** tab, as today.
2. Open the request manager (`puppet-strings app`), press **Load offerings**, then add or
   adjust requests: a day off, a pinned facilitator, a training session.
3. Press **Solve**. Read the staff view, the clinic view and the report of anything that
   could not be satisfied.
4. Press **Publish**. The schedule lands in that day's own spreadsheet.

If the day is already published and someone turns up ill or short of sleep, see
[Same-day changes](same-day.md).

## Where things live

| Thing | Where |
|---|---|
| Clinics, positions, RAL minimums | Clinic_Data spreadsheet |
| Who is checked off on what | Skills spreadsheet |
| Staff categories | A `Staff Categories` spreadsheet in each span's folder |
| Tomorrow's clinics | The Offerings tab of that day's spreadsheet |
| The grid a new day starts from | Offerings tab of Clinic_Schedule |
| Blocks, calendar, mappings, adjustments | The config spreadsheet |
| Requests | A file on the Puppet Master's computer, handed over with [Export and Import](sheets.md#requests-on-this-computer) |
| Published schedules | One spreadsheet per day, in the [schedules tree](sheets.md#the-schedules-tree) |
| The code | This repository, one Python package |

Start with [Install and set up](install.md).
