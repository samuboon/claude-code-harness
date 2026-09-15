#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refill_loop.py - pick the next unit of work, and never answer "nothing to do".

An unattended agent loop dies the moment its queue holds no line it can take today.
This file is one of the two answers we are testing (see README.md):

    side B - "refill in place": if no row is actionable, do not return a stop.
             Return a *refill unit* - a synthetic row that tells the agent to go
             upstream and open the queue itself.

The other answer (side A, `queue_forecast.py`) detects the same condition the night
before, when a human is still awake.

Standard library only. Python 3.8+.

    python refill_loop.py sample_QUEUE.md
    python refill_loop.py sample_QUEUE.md --today 2026-09-15 --json

Exit codes: 0 = a unit was chosen (real row or refill) / 3 = stop (the refill has
already been handed out `--same-row-limit` times in a row and the queue still has
nothing; a human has to look).
"""
import argparse
import datetime
import json
import re
import sys
from collections import namedtuple

Row = namedtuple("Row", "lineno done kind date blocked text raw")

# Marker aliases. Our production copy writes them in Japanese; both are accepted so
# that the example runs on an English queue without a translation step.
KINDS = {
    "routine": "routine", "定型": "routine",
    "judgment": "judgment", "judgement": "judgment", "判断": "judgment",
    "upstream": "upstream", "上流": "upstream",
}

ROW_RE = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]\s*(?P<rest>.*)$")
MARKER_RE = re.compile(
    r"^[\(\[〔]\s*(?P<kind>[A-Za-z]+|定型|判断|上流)"
    r"(?:\s+(?P<date>\d{4}-\d{2}-\d{2}|\d{2}-\d{2}))?\s*[\)\]〕]\s*"
)
BLOCKED_RE = re.compile(r"[\(（](?:wait|waiting|blocked|待)[\)）]", re.IGNORECASE)

# The row handed out when the queue has nothing. It is deliberately a *unit of work*,
# not a message: the agent that receives it has to produce a commit like any other unit.
REFILL_ROW = (
    "refill | The queue has no row that can be taken today. Do not stop. "
    "(1) Read the goal and the whole queue, dated and blocked rows included. "
    "(2) Open at least three rows that can be taken today. "
    "(3) Leave the last row undated - a queue whose every row is scheduled is empty tomorrow. "
    "(4) Write one line of reasoning in the decision log, and commit."
)


def to_date(value, today):
    """'YYYY-MM-DD' -> date. 'MM-DD' -> the nearest such date to `today`.

    Production compared 'MM-DD' as a string, which silently breaks across a new year
    (a row marked 01-05 looks like the far past all through December). Choosing the
    nearest candidate costs three comparisons and removes the whole class of bug.
    """
    if value is None:
        return None
    if len(value) == 10:
        return datetime.date(*(int(p) for p in value.split("-")))
    month, day = (int(p) for p in value.split("-"))
    best = None
    # +-2 years, not +-1: 02-29 has no candidate at all inside a one-year window, and
    # to_date returning None there would make a postponed row look undated - i.e. the
    # loop would take a row it was told to leave alone. (Found by the test below.)
    for year in range(today.year - 2, today.year + 3):
        try:
            cand = datetime.date(year, month, day)
        except ValueError:      # 02-29 in a non-leap year
            continue
        if best is None or abs((cand - today).days) < abs((best - today).days):
            best = cand
    return best


def parse_rows(text, today=None):
    """Markdown checklist -> [Row]. Lines that are not checklist items are ignored."""
    today = today or datetime.date.today()
    rows = []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = ROW_RE.match(line)
        if not m:
            continue
        rest = m.group("rest")
        kind, date = None, None
        mk = MARKER_RE.match(rest)
        if mk and mk.group("kind").lower() in KINDS:
            kind = KINDS[mk.group("kind").lower()]
            date = to_date(mk.group("date"), today)
            rest = rest[mk.end():]
        rows.append(Row(
            lineno=lineno,
            done=m.group("mark") in ("x", "X"),
            kind=kind or "judgment",        # an unmarked row needs a judgment, not a script
            date=date,
            blocked=bool(BLOCKED_RE.search(rest)),
            text=rest.strip(),
            raw=line,
        ))
    return rows


def actionable(rows, today):
    """Rows the loop may take on `today`: open, not blocked on a human, not postponed."""
    return [r for r in rows
            if not r.done and not r.blocked and (r.date is None or r.date <= today)]


def next_date(rows, today):
    """The first day on which a postponed row becomes takeable, or None."""
    dates = sorted(r.date for r in rows
                   if not r.done and not r.blocked and r.date and r.date > today)
    return dates[0] if dates else None


def next_unit(text, today=None, same_row=0, same_row_limit=3):
    """Choose the next unit. Never returns 'stop' just because the queue is empty.

    `same_row` is how many times in a row the caller has already handed out this same
    row without the queue changing. That - not emptiness - is the one condition under
    which stopping is the honest answer.
    """
    today = today or datetime.date.today()
    rows = parse_rows(text, today)
    ready = actionable(rows, today)
    if ready:
        r = ready[0]
        return {"action": "unit", "kind": r.kind, "row": r.text, "refill": False,
                "lineno": r.lineno, "why": "first actionable row"}
    if same_row >= same_row_limit:
        return {"action": "stop", "kind": None, "row": None, "refill": False,
                "lineno": None,
                "why": "refill handed out %d times and the queue still has nothing - "
                       "a human has to look" % same_row}
    nd = next_date(rows, today)
    open_rows = [r for r in rows if not r.done]
    return {
        "action": "unit", "kind": "upstream", "row": REFILL_ROW, "refill": True,
        "lineno": None,
        "why": "0 of %d open rows are actionable (%d blocked on a human, %d postponed%s)"
               % (len(open_rows),
                  sum(1 for r in open_rows if r.blocked),
                  sum(1 for r in open_rows if not r.blocked and r.date and r.date > today),
                  "; next one frees up %s" % nd.isoformat() if nd else ""),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("queue", help="path to the queue markdown file")
    ap.add_argument("--today", help="YYYY-MM-DD (default: the system date)")
    ap.add_argument("--same-row", type=int, default=0,
                    help="how many times this same row was already handed out")
    ap.add_argument("--same-row-limit", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    today = (datetime.date(*(int(p) for p in a.today.split("-")))
             if a.today else datetime.date.today())
    with open(a.queue, encoding="utf-8") as f:
        d = next_unit(f.read(), today, a.same_row, a.same_row_limit)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print("action : %s%s" % (d["action"], "  (refill)" if d["refill"] else ""))
        print("kind   : %s" % d["kind"])
        print("why    : %s" % d["why"])
        if d["row"]:
            print("row    : %s" % d["row"])
    return 3 if d["action"] == "stop" else 0


if __name__ == "__main__":
    sys.exit(main())
