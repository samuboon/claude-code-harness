**日本語版: [README.ja.md](README.ja.md)**

# refill-loop — the morning our unattended loop ran zero units, and the two fixes we can't choose between

An unattended agent loop has one failure that costs a whole day and leaves no trace in
any log: **the queue runs out of rows it can take today, so the agent stops.** Nothing
crashed. Nothing was refused. The loop just had nothing to do, said so, and waited for
a human who was at work for the next twelve hours.

This directory is the minimal implementation of the two answers to that, **both of them**,
because we genuinely do not know which one is right. Standard library only, no
dependencies, ~300 lines total.

| file | side | what it does |
|---|---|---|
| [`queue_forecast.py`](queue_forecast.py) | **A — see it coming** | Run it at 23:00. It counts how many rows will be actionable tomorrow morning and fails loudly if the answer is 0 — while a human is still awake and the fix is one line. |
| [`refill_loop.py`](refill_loop.py) | **B — keep going** | Run it in the loop. When no row is actionable it does not return a stop; it returns a **refill unit** — a synthetic unit of work whose content is "go upstream and open three rows yourself." |

---

## What it cost us (measured, 2026-09-15, one incident)

Our production loop hands one queue row at a time to a fresh agent, which must end with
a commit. The evening before, the agent tidied the queue and put a date on every row —
including the last one, whose only job is to generate new rows and therefore to stay
undated.

| the queue at 22:09 the night before | |
|---|---:|
| open rows | **9** |
| …blocked on a human | 1 |
| …postponed to 09-16 or later | **8** (including the last row, dated 09-21) |
| **rows the loop could take the next morning** | **0** |

| the next morning, 08:39 → 10:29 | |
|---|---:|
| minutes in which the loop produced commits | **53** (3 units, 3 commits) |
| minutes in which it produced nothing | **57** |
| …queue empty, loop idle until a human noticed | 12 min, **0 commits** |
| …a later unit hit a permission boundary and ended without committing | 27 min, **0 commits** |
| …the driver then re-issued the same row twice | 40 s, **0 commits** |

Two different ways to produce nothing in the same two hours. The 12-minute one is what
this directory is about; the 27-minute one is a different bug (an agent that treats
"I need approval" as "I may end my turn") and is fixed elsewhere in this repo.

The human budget being spent here is 10–20 minutes a day. A loop that stalls at 08:39
and is noticed at 08:39 costs almost nothing; one that stalls at 08:39 and is noticed
at 21:00 costs the day.

---

## Run it

```console
$ python queue_forecast.py sample_QUEUE_broken.md --date 2026-09-15
2026-09-15  open 9 / actionable 0  (blocked 1, postponed 8, next 2026-09-16)
  F1  0 of 9 open rows are actionable on 2026-09-15 (1 blocked on a human, 8 postponed). The loop has nothing to take.
  F2  the last open row (line 20) carries a date (2026-09-21). The row that generates new rows is postponed, so the queue can no longer refill itself.
$ echo $?
1

$ python refill_loop.py sample_QUEUE_broken.md --today 2026-09-15
action : unit  (refill)
kind   : upstream
why    : 0 of 9 open rows are actionable (1 blocked on a human, 8 postponed; next one frees up 2026-09-16)
row    : refill | The queue has no row that can be taken today. Do not stop. (1) Read the goal and the whole queue, dated and blocked rows included. (2) Open at least three rows that can be taken today. (3) Leave the last row undated - a queue whose every row is scheduled is empty tomorrow. (4) Write one line of reasoning in the decision log, and commit.

$ python test_refill_loop.py
Ran 19 tests in 0.003s
OK
```

`sample_QUEUE_broken.md` is the real marker layout of the queue that broke us, taken
from the commit. Only the row texts are replaced — the kinds and the dates are ours.

**Queue format** — a markdown checklist, one row per unit of work:

```markdown
- [ ] (routine 09-16) shelf A | D+3 numbers
- [ ] (judgment) (wait) shelf B | blocked on a human
- [ ] (judgment) generative order | write the order that produces new rows
```

`routine` (a script can do it) / `judgment` (someone has to decide) / `upstream` (the
plan itself is in question) — the kind is what you route to a cheap or an expensive
model. A date means "not before this day". `(wait)` means blocked on a human, and the
loop skips it. Japanese markers (`〔定型 09-16〕`, `(待)`) parse too; that is what our own
queue uses.

---

## The part we argue about

Two of our reviewers were asked the same question and answered differently, and the
disagreement is not silly on either side:

> **A.** The queue going empty is a *planning* failure, and planning failures should be
> caught by a human, cheaply, at a known time. Detect it the night before and say so.
> An agent that refills its own queue at 08:39 is an agent writing its own work orders
> with nobody awake to read them.

> **B.** Any check that depends on a human being awake has already lost. The loop's job
> is to keep going; "no rows" is not an error condition, it is *the* upstream condition,
> and it should be handed back to the agent as work. Detecting it the night before only
> moves the stall to the night before.

We built both. The one thing we are sure of is the failure mode they share: an empty
queue must never be a reason to end the turn.

**If you run an unattended agent loop: which one do you use, and did the other one bite
you?** [Open an issue](https://github.com/samuboon/claude-code-harness/issues) — that is the
whole reason both are in here.

---

## What we cannot claim

- **n = 1.** One incident, one morning, one project. Everything above is measured, and
  none of it is a rate.
- **The refill path has fired 0 times in production.** It was added on the morning of
  the incident; since then the queue has never been empty. Its only evidence is the
  tests.
- **The forecast has never run in production at all.** This directory is its first
  implementation; it is checked against the real broken queue after the fact, which is
  the weakest kind of evidence there is.
- **Neither side is shown to be better.** We have no instrument that separates "the
  refill unit opened good rows" from "the refill unit invented busywork", and inventing
  busywork is the obvious failure of side B.
- The date comparison here is slightly stricter than our production copy's: `MM-DD` is
  resolved to the nearest year rather than compared as a string, which our production
  copy would get wrong every January. The test that found that bug (`02-29`) is in the file.

MIT, same as the rest of this repository.
