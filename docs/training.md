# Learning Skedge: the trainer

```
puppet-strings train
```

opens **Skedge Training**, a practice window for new Puppet Masters. In the app, **Open
trainer** in the **Configure** pane starts it too, before anybody has signed in. It holds a couple of
hundred plain-English requests, in levels that each introduce one idea — a single task, sets
of people, `ANY` and `AT_LEAST`, splitting with `EACH`, dates, `FREE`, `BUSY` and `NOT`,
clinics and cabin acts, set arithmetic, counting and lengths, `WITH`, `PREFER`, bindings
and mappings, `IF` / `UNLESS` with
`AND` / `OR`, `GAP` and `EXCLUDE` — and ends with requests that combine several of them.

It runs entirely offline, on a copy of **2026 Main Season, Session 6** bundled with the app:
the real staff, categories, blocks, clinics, cabin act boards and mappings. Nothing written
in it goes near a real schedule.

## The window

| Pane | What it is for |
|---|---|
| The trail, on the left | Every level and problem, ticked off as it is solved. Progress is saved as you go. |
| The problem, in the middle | What camp asks for, the priority it is asked at and the day being scheduled; a Skedge box with the same name suggestions as the request manager; and what the checker made of your answer. |
| Names and Calendar, on the right | The same two panes as the request manager. Search the names by any part of them; double-click one to see what it stands for; click a day to put its date in your answer. |

Each level has a cheat sheet. Each problem has hints, and an answer to peek at.

## How an answer is marked

An answer is never compared with the expected text: most requests can be written several
ways, and any of them is right. It is marked by what it does.

1. Both are resolved against the session, which turns every spelling of a set into the same
   people, blocks and dates. If they come out the same, the answer is right.
2. Otherwise the solver builds days of Session 6 — the emptiest ones each request allows,
   the fullest, and many in between — and holds each against the other request. A day that
   meets one and not the other is shown to you as a small schedule: the clearest way to see
   what your request says that you didn't mean.
3. A few things no single day shows are compared directly: `PREFER` against `REQUEST`, the
   dates a request is about, how long a `FOR` task lasts, what a `MAXIMIZE` scores, what an
   `EXCLUDE` takes out, and below `MUST_HAPPEN` how many separate requests `EACH` makes.

## Adding problems

Problems live in `puppet_strings/training/problems/`, one TOML file per level:

```toml
[[problem]]
id = "first-rob-lunch-break"
title = "Rob's lunch break"
prompt = "Rob should take a 'break' during lunch."
answer = "REQUEST staff.rob DO 'break' DURING blocks.lunch"
priority = "HIGH"                       # optional; HIGH by default
day = "2026-08-04"                      # optional; the level's day by default
hints = ["…", "…"]
explain = "Shown once it is solved."
alternatives = ["other answers that must be marked right"]
wrong = ["near misses that must be marked wrong"]
```

The test suite holds every problem to its answer, its alternatives and its near misses, so a
new problem is checked the moment it is written. `tools/snapshot_training.py` refreshes the
bundled session from the sheets.
