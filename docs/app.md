# The request manager

```
puppet-strings app
```

![The request manager](img/app.png)

**Toolbar.** Pick the target date (tomorrow by default). **Reload** reads every sheet again.
**Load offerings** turns the Offerings tab into one `CLINIC` request per offered clinic,
tagged `generated`, and saves them to the Requests sheet. Loading first removes every
generated request for the target date, so the sheet mirrors the Offerings tab: a clinic
you removed there disappears here. Hand-written requests are never touched. Between loads
you can delete a generated request to drop that clinic, or edit it, for example to
replace `ANY_1_OF staff.all` with a category to limit who runs it; loading again undoes
such edits. **Solve** builds the schedule and opens it in a window with the staff view, the
clinic view and the report; it asks first if no offerings are loaded for the date.
**Publish** in that window writes the schedule to Published Schedules, asking first if the
date is already published.

**Same-day changes.** Once the day on screen is published, the toolbar offers
**Same-day changes** and **Who is off today…**. See [Same-day changes](same-day.md).

## Groups

**The groups pane.** Down the left-hand side is every group of requests, with how many
requests are in each. Click one and the table shows only that group. `All requests` and
`Ungrouped` head the list and are not groups themselves: `Ungrouped` is whatever is in no
group at all, which is how a request that has been forgotten about turns up.

Two groups are always there — **Special daily requests** and **Special weekly
requests** — and you make the rest. Requests made from the Offerings tab are in no group,
so they sit under `Ungrouped`: there are dozens of them and the `generated` tag and the
`CLINIC` priority already tell them apart. **New** asks for a name, **Rename**
renames a group everywhere it is used, and **Delete** takes a group off its requests
without deleting the requests themselves. The two default groups cannot be renamed or
deleted.

A request may belong to as many groups as you like, or to none; groups and tags are
separate, so a request can be in the `Ropes rewrite` group and still be tagged `legal`.
Put a request in a group either by ticking the group in the editor, or by selecting rows
in the table and right-clicking: the menu offers every group, adding or removing the whole
selection at once. Groups live in the `groups` column of the Requests sheet, so they are
there again the next time the app opens. A group you have just made and put nothing in yet
stays in the pane until you close the app.

**The table.** One row per request. Click a column heading to sort by it. Filters above
it: free text over id, description, Skedge and requester; priority; scope; tag; staff;
activity; and a date. These narrow whatever group is showing, so the group is the shelf
and the filters are the search. The scope is derived from the dates a request resolves to:

| Scope | The dates it reaches |
|---|---|
| season | every camp day: no `ON` clause, or `ON date.season` |
| session | exactly one session, such as `ON date.session.four` |
| week | more than one day but less than a session, such as a week, a range, or `date.session.four.mondays` |
| day | one day |
| pin | one day, one staff member, `MUST_HAPPEN` |

The staff and activity filters use the names a request resolves to, so filtering by
`dylan` finds requests written for `staff.counselor` as well.

## Conflicts

**The conflicts pane.** Along the bottom, every place two requests contradict each other,
found without solving. Each heading is one collision — one person, one date, one block —
and everything under it belongs to that collision: the requests caught in it, hardest
first, and the reasons they cannot all hold. A request in two collisions appears under
both. Double-click one to open it in the editor.

| What it catches | Example |
|---|---|
| Asked to work and to be free | `REQUEST staff.dylan DO activity.riflery DURING block.clinic_1` beside `REQUEST staff.dylan FREE DURING block.clinic_1` |
| Asked to do something and told not to | the same, beside `REQUEST staff.dylan NOT DO activity.weapons` |
| Asked to be free and to be busy | `FREE` beside `NOT FREE` in one block |
| Two things at once that do not fit | two `FOR` tasks whose minutes exceed the block, or two clinics in one block |

It reads only what is **settled**. `REQUEST ANY_1_OF staff.all DO …`, `DURING ANY_2_OF
block.all` and every `PREFER` leave the solver room to move, and moving things around each
other is its job, so they are never reported. What is left is worth looking at: a request
saved into a collision says so in the toolbar as it saves. A request can also contradict
itself, now that one request may hold several statements, and that shows up the same way.

The pane is not a substitute for solving. It finds what is plain on paper; the solver
finds the rest and names the requests it could not meet.

**The editor.** One field per request column and a Skedge editor with highlighting. The
**groups** field ticks off every group the request is in, and **requester** records who
asked for it — type a staff name and it completes, the same names `staff.` gives you in
the Skedge box. A requester who is not on the Skills sheet makes the request invalid, so a
misremembered name is caught here rather than saved and forgotten. The
id is made from the description on the first save (`Dylan's day off` becomes
`dylan-s-day-off`, then `-2`, `-3` if taken) and never changes afterwards; it is what the
solver's report refers to. The
line under the editor says whether the request is valid, or shows the first error with its
line and column. Save is enabled only for a valid request. Ctrl+S saves. **New** starts a
fresh request; **Delete** removes the selected one. Every save rewrites the Requests tab.

**Name completion.** Type a namespace and a dot in the Skedge box, such as `staff.`, and a
list of names appears and narrows as you keep typing.

![Completing a staff name](img/completer.png)
 Enter or Tab takes the highlighted
name, Escape closes the list. The names offered are exactly the ones the validator
accepts, so anything the list gives you is spelled right.

**Names.** The panel on the right lists every valid name with what it stands for: a staff
member's name, how many members a category has, a block's times, a date. Double-click one
to insert it at the cursor.

**Calendar.** Below the names, a calendar with camp days (the dates on the Calendar sheet)
shaded. Down its left-hand side, each week is labelled with the session and week it is,
`S4` over `W2`, taken from the Calendar sheet — the numbers `date.session.four.second_week`
is built from, rather than the week of the year. Click any date to insert it into the
Skedge editor at the cursor, as `2026-06-15`.

**Saving a request about other dates.** A request does not have to be about the date being
scheduled: `ON ALL_OF date.session.two.first_week` is a perfectly good request to write in
the middle of session 1. It will do nothing to the schedule you are about to solve, though,
which is easy to write by accident — a mistyped date, or `session.two` where you meant
`session.this`. So saving such a request asks first, names the dates it *is* about, and
lets you either save it anyway or go back to editing.
