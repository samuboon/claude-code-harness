#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""queue_forecast.py - count tomorrow morning's actionable rows, tonight.

Side A of the experiment in README.md: the loop is going to die at 08:39 tomorrow,
and the cheapest moment to learn that is 23:00 tonight, while a human is still awake
and the fix costs one line.

Two checks, both of which fired on the queue that actually broke us:

  F1  tomorrow's actionable rows == 0
      The loop will start, find nothing, and either stop or burn a unit on a refill.

  F2  the last open row carries a date
      The last row is the one that generates the next rows. Once it is scheduled,
      the queue can no longer refill itself: every finished row shortens it and
      nothing lengthens it. F2 catches the failure one day earlier than F1 - while
      today still looks healthy.

Standard library only. Python 3.8+. Meant to run from a nightly cron / task.

    python queue_forecast.py sample_QUEUE.md                 # tomorrow
    python queue_forecast.py sample_QUEUE.md --date 2026-09-15
    python queue_forecast.py sample_QUEUE.md --days 3        # the next three mornings

Exit codes: 0 = clean / 1 = at least one finding / 2 = the queue could not be read
(never exit 0 on a file you failed to parse - a silent pass is the bug you are hunting).
"""
import argparse
import datetime
import sys

try:
    from refill_loop import actionable, next_date, parse_rows
except ImportError:                                            # run from another cwd
    sys.path.insert(0, __file__.rsplit("/", 1)[0].rsplit("\\", 1)[0])
    from refill_loop import actionable, next_date, parse_rows


def forecast(text, when, today=None):
    """Return what the loop will find on the morning of `when`."""
    today = today or when
    rows = parse_rows(text, today)
    open_rows = [r for r in rows if not r.done]
    ready = actionable(open_rows, when)
    findings = []
    if not ready:
        findings.append(
            "F1  0 of %d open rows are actionable on %s "
            "(%d blocked on a human, %d postponed). The loop has nothing to take."
            % (len(open_rows), when.isoformat(),
               sum(1 for r in open_rows if r.blocked),
               sum(1 for r in open_rows if not r.blocked and r.date and r.date > when)))
    if open_rows and open_rows[-1].date is not None:
        findings.append(
            "F2  the last open row (line %d) carries a date (%s). The row that "
            "generates new rows is postponed, so the queue can no longer refill itself."
            % (open_rows[-1].lineno, open_rows[-1].date.isoformat()))
    return {
        "date": when.isoformat(),
        "open": len(open_rows),
        "actionable": len(ready),
        "blocked": sum(1 for r in open_rows if r.blocked),
        "postponed": sum(1 for r in open_rows if not r.blocked and r.date and r.date > when),
        "next_date": (next_date(open_rows, when).isoformat()
                      if next_date(open_rows, when) else None),
        "findings": findings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("queue", help="path to the queue markdown file")
    ap.add_argument("--date", help="YYYY-MM-DD to forecast (default: tomorrow)")
    ap.add_argument("--days", type=int, default=1, help="forecast N consecutive mornings")
    a = ap.parse_args(argv)
    try:
        with open(a.queue, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print("cannot read the queue: %s" % e, file=sys.stderr)
        return 2
    start = (datetime.date(*(int(p) for p in a.date.split("-"))) if a.date
             else datetime.date.today() + datetime.timedelta(days=1))
    bad = False
    for i in range(max(1, a.days)):
        d = forecast(text, start + datetime.timedelta(days=i))
        print("%s  open %d / actionable %d  (blocked %d, postponed %d, next %s)"
              % (d["date"], d["open"], d["actionable"], d["blocked"], d["postponed"],
                 d["next_date"] or "-"))
        for f in d["findings"]:
            print("  " + f)
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
