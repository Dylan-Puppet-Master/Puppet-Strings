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
you can delete a generated request to drop that clinic, or edit it, for example to add
`ACROSS` to limit who runs it; loading again undoes such edits. **Solve** builds the schedule and opens it in a window with the staff view, the
clinic view and the report; it asks first if no offerings are loaded for the date.
**Publish** in that window writes the schedule to Published Schedules, asking first if the
date is already published.

**The table.** One row per request. Click a column heading to sort by it. Filters above
it: free text over id, description and Skedge; priority; scope; tag; staff; activity; and
a date. The scope is derived from the
request's `ON` clause:

| Scope | The `ON` clause |
|---|---|
| season | none: the request applies every day |
| session | `ON date.session` |
| week | a range, an offset such as `date.target - 6d`, or a weekday name |
| day | one date |
| pin | one date, one staff member or category, `MUST_HAPPEN` |

The staff and activity filters use the names a request resolves to, so filtering by
`dylan` finds requests written for `staff.counselor` as well.

**The editor.** One field per request column and a Skedge editor with highlighting. The
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
shaded. Click any date to insert it into the Skedge editor at the cursor, as `2026-06-15`.
