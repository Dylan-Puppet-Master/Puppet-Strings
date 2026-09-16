# Puppet Strings

Puppet Strings builds the daily staff schedule for Camp Augusta. The Puppet Master keeps
camp data in Google Sheets, writes scheduling rules as **requests** in a small language
called **Skedge**, and presses Solve. The solver assigns staff to the clinics on the
Offerings sheet, fits in breaks, counselor hours and other tasks, and publishes two
printable views back to Google Sheets.

![The request manager](img/app.png)

## The daily loop

1. Fill in tomorrow's **Offerings** tab, as today.
2. Open the request manager (`puppet-strings app`) and add or adjust requests: a day off,
   a pinned facilitator, a training session.
3. Press **Solve**. Read the staff view, the clinic view and the report of anything that
   could not be satisfied.
4. Press **Publish**. The schedule lands in the Published Schedules spreadsheet.

## Where things live

| Thing | Where |
|---|---|
| Clinics, positions, RAL minimums | Clinic_Data spreadsheet |
| Who is checked off on what | Skills spreadsheet |
| Staff categories | Staff Categories spreadsheet |
| Tomorrow's clinics | Offerings tab of Clinic_Schedule |
| Blocks, calendar, requests, metrics | The Puppet Strings spreadsheet |
| Published schedules | The Published Schedules spreadsheet |
| The code | This repository, one Python package |

Start with [Install and set up](install.md).
