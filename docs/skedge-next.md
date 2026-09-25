# Skedge, next version (draft)

A proposal, not the language yet. Nothing here parses today, and where it disagrees with
[the specification](spec.md), the specification is what the app does. Once it is agreed,
it is folded into the specification and the reference, the grammar follows, and saved
requests are rewritten on their next load.

## The idea

An activity is a thing, not a quantity. What happens several times is the blocks, the dates
and the people it happens in; what lasts is the activity. So:

- **A number is a count**, and goes directly in front of the set it counts.
- **A length goes on `FOR`**, and measures the activity within whatever the blocks are taken
  as one unit of.
- **`ANY` never takes a number.** It means "any of these": the set is one pool.

The amount no longer sits after `REQUEST`, far from what it measures, and no longer follows
`DO`.

| Today | Next |
|---|---|
| `REQUEST AT_MOST 2 ANY staff.counselors DO 'break' DURING EACH blocks` | `REQUEST AT_MOST 2 staff.counselors DO 'break' DURING EACH blocks` |
| `REQUEST EXACTLY 3 EACH staff.village_heroes DO 'break'` | `REQUEST EACH staff.village_heroes DO 'break' DURING EXACTLY 3 blocks` |
| `REQUEST AT_LEAST 2h staff.cam_vl DO 'video editing'` | `REQUEST staff.cam_vl DO 'video editing' FOR AT_LEAST 2h DURING ANY blocks` |
| `REQUEST AT_LEAST 2h staff.cam_vl DO 'video editing' DURING ANY CONSECUTIVE blocks` | `REQUEST staff.cam_vl DO 'video editing' FOR AT_LEAST 2h DURING ANY CONSECUTIVE blocks` |
| `REQUEST AT_LEAST 2 staff.charlton DO 'fence building' DURING ANY CONSECUTIVE blocks` | `REQUEST staff.charlton DO 'fence building' DURING AT_LEAST 2 CONSECUTIVE blocks` |
| `REQUEST AT_MOST 1 EACH staff DO ANY activities.clinics DURING ANY CONSECUTIVE blocks` | `REQUEST EACH staff DO ANY activities.clinics DURING AT_MOST 1 CONSECUTIVE blocks` |
| `REQUEST AT_LEAST 1h ANY staff.mfgs DO 'kitchen repair'` | `REQUEST ANY staff.mfgs DO 'kitchen repair' FOR AT_LEAST 1h DURING ANY blocks` |
| `REQUEST ANY 3 staff.village_heroes DO 'lifeguard' DURING blocks.rest_hour` | `REQUEST AT_LEAST 3 staff.village_heroes DO 'lifeguard' DURING blocks.rest_hour` |
| `REQUEST AT_MOST 4 EACH staff.directors NOT FREE` | `REQUEST EACH staff.directors BUSY DURING AT_MOST 4 blocks` |
| `REQUEST staff.hails NOT FREE DURING ANY blocks.evening` | `REQUEST staff.hails BUSY DURING ALL blocks.evening` |
| `REQUEST staff.hails NOT FREE DURING ALL blocks.evening` | `REQUEST staff.hails BUSY DURING AT_LEAST 1 blocks.evening` |
| `IF AT_LEAST 3 s DO ANY activities.clinics DURING ANY CONSECUTIVE blocks` | `IF s DO ANY activities.clinics DURING AT_LEAST 3 CONSECUTIVE blocks` |
| `ANY 1 v IN {staff.dylan + staff.cam_vl}` | `EXACTLY 1 v IN {staff.dylan + staff.cam_vl}` |
| `WITH ANY 2 staff.seniors` | `WITH AT_LEAST 2 staff.seniors` |

## Quantifiers

| Quantifier | Meaning |
|---|---|
| `ALL s` | Every member of `s`, together, as one unit. |
| `EACH s` | The declaration is copied once per member, each copy a separate request. |
| `AT_LEAST n s`, `AT_MOST n s`, `EXACTLY n s` | The number of members of `s` for which the rest of the statement holds compares so with `n`. |
| `ANY s` | Any of these: a pool. The statement is about the set as a whole, not member by member. |

An item takes no quantifier, as today. `n` is at least 1; `AT_MOST 0` and `EXACTLY 0` are
still errors that say to write `NOT DO`.

A count is a count, not a choice: `AT_LEAST 3` holds with three or with four, and `AT_MOST`
and `EXACTLY` forbid the rest. So a requirement with a count can now forbid, which the
specification's "a requirement never forbids" has to give up.

`CONSECUTIVE` goes after a count or `ANY` on the blocks, as today. `DURING AT_LEAST 2
CONSECUTIVE blocks` holds when some run of adjacent blocks reaches 2, `AT_MOST` when no
run exceeds it, `EXACTLY` when both do. `DURING ANY CONSECUTIVE blocks` pools each run
on its own, for a `FOR` to measure.

## Which count is inside which

Where a set is written does not change what it means; its role does. With counts on several
sets in one statement, they apply in this order, outside in:

1. Every `EACH`, anywhere, splits the declaration first, as today.
2. The subject: who.
3. The object: what they do.
4. `ON`: the dates.
5. `DURING`: the blocks.
6. `AS_ROLE`, `WITH`, `WITHOUT` and `FOR`, within one unit of all of the above.

So `AT_MOST 2 staff.counselors DO 'break' DURING AT_LEAST 3 blocks` is "at most two
counselors break in three or more blocks", and `ON AT_LEAST 2 dates.week_1 … DURING EXACTLY
1 blocks` is "on at least two dates, in exactly one block of each". "In at least three
blocks, at most two counselors" — blocks outside people — needs the blocks bound on a line
of their own. At most two at a time is still `DURING EACH blocks`, by rule 1.

`ALL` makes the group one unit, so a count inside it counts what the group does together:

```
REQUEST ALL {staff.dylan + staff.alesa} DO 'video' DURING EXACTLY 1 blocks
```

is one block in which both of them film. Either filming alone elsewhere is not a block of
theirs together, so it is not counted. `EACH {staff.dylan + staff.alesa}` gives one block
each, possibly different ones.

A count on the object counts different activities: `staff.rob DO AT_LEAST 2
activities.clinics DURING ALL {blocks.clinic_1 + blocks.clinic_2}` is two clinics, each
of which Rob runs in both blocks.

## Lengths

`FOR` takes a duration, or a count's word and a duration: `FOR 30m`, `FOR AT_LEAST 2h`,
`FOR AT_MOST 90m`. It needs a quoted task, as today.

It measures the task within one unit of the blocks:

- Blocks taken one at a time — an item, `ALL`, `EACH` or a count — make each block a unit.
  `DO 'break' FOR 30m DURING EXACTLY 3 blocks` is three breaks of 30 minutes. A piece
  never leaves its block, so a unit of one block holds one piece.
- Blocks pooled with `ANY` are one unit together: `DO 'video editing' FOR AT_LEAST 2h DURING
  ANY blocks` is two hours in total, across whichever blocks.
- `ANY CONSECUTIVE` makes each run a unit: `FOR AT_LEAST 2h DURING ANY CONSECUTIVE
  blocks` is two hours in one run of adjacent blocks. `AT_MOST` holds when no run is
  longer.

Dates pool the same way: `FOR AT_LEAST 5h DURING ANY blocks ON ANY dates.week_1` is five
hours over the week.

`ANY` on the blocks of a requirement is only allowed with a `FOR` to measure it, since a pool
otherwise says nothing about how much. Without one, the error says to write a count:
`DURING AT_LEAST 1 blocks`.

## Positions

Subject, verb and object keep their order. `DURING` and `ON` may go anywhere, including
before the subject:

```
REQUEST DURING blocks.clinic_1 staff.rob DO 'break' ON 2026-08-04
```

`AS_ROLE`, `FOR`, `WITH` and `WITHOUT` describe the activity, so they go after the verb:
after `DO`, `FREE` or `BUSY`, before or after the object. `REQUEST FOR 30m staff.rob DO
'break'` is an error that says where `FOR` goes.

## BUSY

`BUSY` replaces `NOT FREE`: the staff member holds an assignment in the block. Someone
resting is neither `FREE` nor `BUSY`, which `NOT FREE` never said.

`NOT FREE` still parses, only to say to write `BUSY`. `NOT BUSY` is an error that says to
write `FREE`.

## NOT

`NOT` is left in `NOT DO` only. Everything to the right of it still describes the situation
that must not happen, a set there still takes `ANY` or `ALL`, and `EACH` still splits.

A count to the right of `NOT` is an error, as `ANY n` is today. Anything it could say is
clearer as a positive count: "not in two or more" is `DURING AT_MOST 1`.

## Statements

| Statement | Met |
|---|---|
| `REQUEST <statement>` | when it holds |
| `PREFER <statement with a count or a FOR length>` | by degree: the closer to the amount, the better |
| `PREFER <pattern> MAXIMIZE …` / `MINIMIZE …` | as today |

`REQUEST <amount> <pattern>` and `PREFER <amount> <pattern>` are gone. `GAP a TO b
<amount>` keeps its amount at the end: there it measures the gap, not a set.

`EXCLUDE` takes no counts, as it takes no `ANY n` today.

## Old spellings

Each old spelling still parses, only to give the new one:

| Old | Message says |
|---|---|
| `REQUEST AT_LEAST 3 ANY staff.x DO …` | the count goes on the set it counts |
| `s DO AT_LEAST 3 …` | the same |
| `ANY n s` | `AT_LEAST n s`, or `EXACTLY n` in a binding |
| `NOT FREE` | `BUSY` |
| `AS_ROLE`, `FOR`, `WITH`, `WITHOUT` before the verb | they go after it |

Saved requests are rewritten on their next load where the new spelling means the same:

- A front count over a pattern with one pooled set moves onto that set as a count.
- A front length moves onto `FOR`, with the blocks pooled.
- `ANY n` becomes `AT_LEAST n` where nothing shares the choice. Where something does — `ANY
  2 staff.x DO … DURING ANY 1 blocks`, two people in the same block — the choice becomes
  a binding line, `EXACTLY 1 b IN blocks`, since a count on the blocks would now be each
  person's own.
- `NOT FREE` becomes `BUSY`.

A request the rewrite cannot carry over is left as it was and reported with the error, for
someone to rewrite by hand.

## Open questions

1. **A count over two pools.** `AT_LEAST 3 ANY staff.x DO 'y' DURING ANY blocks` counts
   person-blocks: three breaks among them, however shared. A count goes on one set, so this
   has no new spelling. Is it needed?
2. **How a `FOR` total is made up.** A task with no `FOR` fills its block. Under a pooled
   `FOR AT_LEAST 2h`, do the pieces still fill their blocks, as a length amount's do today,
   or does the solver choose each piece's length? Filling is what the solver does now;
   choosing is more flexible and a new variable per piece.
3. **`FOR AT_LEAST 30m` per block.** A bound on one piece's length — "breaks of at least 30
   minutes" — has the same question: today a piece is its block or exactly its `FOR`.
4. **`PREFER` with several counts.** Degree is measured on the outermost count; the inner
   ones hold or don't for each unit. Is that the scoring wanted?
5. **Counting activities.** Is a count on the object, "two different clinics", wanted, or
   should the object take only an item, `ANY` or `EACH`?
