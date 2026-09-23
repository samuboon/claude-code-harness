# -*- coding: utf-8 -*-
"""Check the rebuilt history against Jira's own history search, day by day.

    python crosscheck.py team.json --days 2026-03-01,2026-06-01,2026-09-01
    python crosscheck.py team.json --every 30 --ready "To Do"

idle_day_forecast.py rebuilds, from each issue's changelog, which issues were ready and
unassigned at the end of every past day. Jira can answer part of the same question itself with
JQL's WAS operator:

    (your JQL) AND status WAS IN (ids of the ready statuses) ON "2026-03-01"
               AND assignee WAS EMPTY ON "2026-03-01" AND created < "2026-03-02"

This script asks that for each day and compares the two sets of issue keys. WAS ... ON matches
an issue that had the value at any moment of that day, while the rebuild looks at the end of the
day, so an issue that changed during the day can be in Jira's set and not in ours; those are
reported apart ("changed that day") and are not counted as disagreements. Neither are issues
that had been unassigned ever since they were created: on Jira Cloud, `assignee WAS EMPTY` did
not match them (only a history row that sets the assignee to empty seems to count), although
`assignee is EMPTY` did ("unassigned since created"). Issues Jira lists that are not in the file are
listed apart too ("not in file"): either the fetch missed them or Jira's history search is wrong
about them, and only reading them tells which (on Jira Cloud we found the second: four issues
Closed in 2020-21, by their own changelogs, listed as Open and unassigned on every day of 2026).
They are not counted as disagreements, but they are always printed. Blockers and start
dates are left out of both sides here (JQL has no history for links).

Read-only (GET). Same --base / credentials as fetch_jira.py. Exit 0 = every day agrees,
1 = at least one real disagreement, 2 = could not run.
"""
import argparse
import datetime as dt
import json
import sys

import fetch_jira
import idle_day_forecast as idf


def jql_keys(j, jql):
    issues, _ = fetch_jira.search_keys(j, jql)
    return {i["key"] for i in issues}


def quote(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--days", help="comma-separated YYYY-MM-DD")
    ap.add_argument("--every", type=int, help="or: every N days from since to the fetch")
    ap.add_argument("--ready")
    ap.add_argument("--status-map", action="append", default=[])
    a = ap.parse_args(argv)
    with open(a.file, encoding="utf-8") as fh:
        doc = json.load(fh)
    ready = [r.strip() for r in a.ready.split(",")] if a.ready else None
    try:
        # links are out of scope here: a phrase that matches nothing turns blockers off
        board = idf.Board(doc, ready=ready, status_map=a.status_map, phrase="\x00no-link\x00",
                          unreadable="ignore")
    except idf.Refused as e:
        print("cannot rebuild: " + "; ".join(e.reasons))
        return 2
    days = board.days()[:-1]  # the fetch day is not over; it cannot be compared
    if a.days:
        want = {dt.date.fromisoformat(x.strip()) for x in a.days.split(",")}
        days = [d for d in days if d[0] in want]
    elif a.every:
        days = days[::a.every]
    meta = board.meta
    j = fetch_jira.Jira(meta["base"], meta["api"])
    ids = doc.get("status_ids") or {}
    if all(ids.get(s) for s in board.ready):
        # by id: on a Cloud site with many workflows, `status WAS "Open"` resolved the name to one of
        # several statuses called Open and missed an issue that had been Open since 2021
        statuses = ",".join(sorted({i for s in board.ready for i in ids[s]}, key=lambda v: (len(v), v)))
    else:
        print("note: the file has no status ids; asking Jira by status name, which can miss issues on Cloud")
        statuses = ",".join(quote(s) for s in sorted(board.ready))
    queue = [x for x in board.tl.values() if x.in_queue]
    bad = 0
    for d, inst in days:
        ours = {x.key for x in queue if board.pickable(x, inst)}
        nxt = (d + dt.timedelta(days=1)).isoformat()
        q = ('(%s) AND status WAS IN (%s) ON "%s" AND assignee WAS EMPTY ON "%s" AND created < "%s"'
             % (meta["jql"], statuses, d.isoformat(), d.isoformat(), nxt))
        theirs = jql_keys(j, q)
        # issues resolved before since are not in the file; Jira may still list them for early days
        known = set(board.tl)
        outside = theirs - known
        theirs &= known
        only_theirs = theirs - ours
        start = inst - 86400 + 1e-6
        changed = set()
        for k in only_theirs:
            x = board.tl[k]
            if board.pickable(x, start) or any(start < t <= inst for t in x.status_t + x.assignee_t):
                changed.add(k)
        only_ours = ours - theirs
        # Jira's own blind spot: an issue that has been unassigned since it was created (no history
        # row ever set the assignee to empty) is not matched by `assignee WAS EMPTY` on Jira Cloud,
        # even when `assignee is EMPTY` matches it (seen on issues.redhat.com, 2026-09-23)
        blind = {k for k in only_ours if not any(v for tt, v in zip(board.tl[k].assignee_t, board.tl[k].assignee_v)
                                                 if tt <= inst)}
        real = (only_theirs - changed) | (only_ours - blind)
        bad += bool(real)
        print("%s  ours %4d  jira %4d  both %4d  changed that day %2d  unassigned since created %2d  not in file %2d  "
              "disagree %d%s"
              % (d, len(ours), len(theirs), len(ours & theirs), len(changed), len(blind), len(outside), len(real),
                 ("  " + ", ".join(sorted(real)[:8])) if real else "")
              + (("  not in file: " + ", ".join(sorted(outside)[:8])) if outside else ""))
    print("%d requests; %d of %d days with a real disagreement" % (j.calls, bad, len(days)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
