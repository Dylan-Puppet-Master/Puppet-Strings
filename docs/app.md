# The request manager

```
puppet-strings app
```

![The request manager](img/app.png)

**Toolbar.** Pick the target date (tomorrow by default). **Reload** reads every sheet again.
**Solve** builds the schedule and opens it in a window with the staff view, the clinic view
and the report; **Publish** in that window writes it to Published Schedules, asking first if
the date is already published.

**The table.** One row per request. Filters above it: free text over id, description and
Skedge; priority; scope; staff; activity; and a date. The scope is derived from the
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
line under the editor says whether the request is valid, or shows the first error with its
line and column. Save is enabled only for a valid request. Ctrl+S saves. **New** starts a
fresh request; **Delete** removes the selected one. Every save rewrites the Requests tab.

**Names.** The panel on the right lists every valid name. Double-click one to insert it at
the cursor.
