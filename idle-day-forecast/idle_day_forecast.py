# -*- coding: utf-8 -*-
"""Forecast the day a Jira team runs out of work it can pick up.

    python idle_day_forecast.py team.json                     # forecast as of the fetch
    python idle_day_forecast.py team.json --ready "Ready,Selected for Development"
    python idle_day_forecast.py team.json --backtest          # replay the past and score it
    python idle_day_forecast.py team.json --series            # one TSV row per day
    python idle_day_forecast.py team.json --fail-within 10    # exit 1 if it is forecast within 10 days

An issue can be picked up on a given day when, at the end of that day,
  - it exists, and its status is a ready status (default: every status in the "To Do" category),
  - nobody is assigned (unless --ignore-assignee),
  - every issue it "is blocked by" is in a Done-category status,
  - and its start date, if --start-field was fetched, is not in the future.

The file comes from fetch_jira.py. Every issue's state on every past day is rebuilt from its
changelog, so the count on 2026-06-03 is what the board would have shown that evening.

The forecast is arithmetic, not a model: pickable now / (how much the pickable count fell per
day over the last --window days). The range comes from the fastest and slowest single week in
that window. When anything the definition needs is missing or cannot be trusted, the script
refuses (exit 2) and says what is missing, instead of forecasting from a partial picture:
the search returned fewer issues than it reported, a changelog was cut short, a status name in
the history is not on the site, a history does not lead to the issue's current state, or an
issue is blocked by something that was not fetched.

Exit codes: 0 forecast made / 1 --fail-within was hit / 2 refused (see the reasons) / 64 usage.
Standard library only. No network.
"""
import argparse
import bisect
import datetime as dt
import json
import math
import re
import sys

BLOCKED_BY = "is blocked by"
TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)$")


class Refused(Exception):
    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def parse_ts(s):
    """Jira timestamps: 2026-09-23T10:13:23.000+0000, ...+10:00, ...Z. Returns epoch seconds."""
    m = TS.match(s or "")
    if not m:
        raise ValueError("not a Jira timestamp: %r" % (s,))
    base, frac, off = m.groups()
    t = dt.datetime.fromisoformat(base)
    if off == "Z":
        tz = dt.timezone.utc
    else:
        off = off.replace(":", "")
        sign = 1 if off[0] == "+" else -1
        tz = dt.timezone(sign * dt.timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))
    return t.replace(tzinfo=tz).timestamp() + (float(frac) if frac else 0.0)


def parse_tz(s):
    m = re.match(r"^(UTC|Z|[+-]\d\d:?\d\d)$", s or "")
    if not m:
        raise ValueError("--tz takes UTC or an offset like +09:00")
    if s in ("UTC", "Z"):
        return dt.timezone.utc
    off = s.replace(":", "")
    sign = 1 if off[0] == "+" else -1
    return dt.timezone(sign * dt.timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))


class Timeline:
    """One issue: when it was created, and its status / assignee / blockers over time."""

    def __init__(self, key, created, status_steps, assignee_steps, blocker_initial, blocker_events,
                 start, in_queue):
        self.key = key
        self.created = created
        self.status_t = [t for t, _ in status_steps]
        self.status_v = [v for _, v in status_steps]
        self.assignee_t = [t for t, _ in assignee_steps]
        self.assignee_v = [v for _, v in assignee_steps]
        self.blocker_initial = frozenset(blocker_initial)
        self.blocker_events = blocker_events  # sorted [(t, key, +1 / -1)]
        self.start = start
        self.in_queue = in_queue

    def status_at(self, t):
        return self.status_v[bisect.bisect_right(self.status_t, t) - 1]

    def assigned_at(self, t):
        return self.assignee_v[bisect.bisect_right(self.assignee_t, t) - 1]

    def blockers_at(self, t):
        s = set(self.blocker_initial)
        for et, k, d in self.blocker_events:
            if et > t:
                break
            if d > 0:
                s.add(k)
            else:
                s.discard(k)
        return s


def _items(issue, field):
    out = []
    for h in sorted(issue["changelog"]["histories"], key=lambda h: parse_ts(h["created"])):
        t = parse_ts(h["created"])
        for it in h.get("items") or []:
            if (it.get("field") or "").lower() == field:
                out.append((t, it))
    return out


def build_timeline(issue, in_queue, phrase, start_field, problems):
    key = issue["key"]
    f = issue["fields"]
    created = parse_ts(f["created"])
    cl = issue.get("changelog") or {}
    hist = cl.get("histories") or []
    if cl.get("total", len(hist)) > len(hist) or cl.get("complete") is False:
        problems.append("%s: changelog is cut short (%d of %s histories)" % (key, len(hist), cl.get("total")))

    # status: walk the history forward from the first "from"
    now_status = f["status"]["name"]
    st = _items(issue, "status")
    steps = [(created, st[0][1].get("fromString") if st else now_status)]
    prev = steps[0][1]
    for t, it in st:
        if it.get("fromString") != prev:
            problems.append("%s: status history jumps from %r to a change that starts at %r"
                            % (key, prev, it.get("fromString")))
        prev = it.get("toString")
        steps.append((t, prev))
    if prev != now_status:
        problems.append("%s: status history ends at %r but the issue is now %r" % (key, prev, now_status))

    # assignee: only whether someone is assigned
    now_assigned = bool(f.get("assignee"))
    asg = _items(issue, "assignee")

    def who(it, side):
        return bool(it.get(side) or it.get(side + "String"))

    a_steps = [(created, who(asg[0][1], "from") if asg else now_assigned)]
    aprev = a_steps[0][1]
    for t, it in asg:
        aprev = who(it, "to")
        a_steps.append((t, aprev))
    if aprev != now_assigned:
        problems.append("%s: assignee history ends %s but the issue is now %s"
                        % (key, "assigned" if aprev else "unassigned",
                           "assigned" if now_assigned else "unassigned"))

    # blockers: current inward "is blocked by" links, unwound through the history
    now_block = set()
    for link in (f.get("issuelinks") or []):
        typ = link.get("type") or {}
        if "inwardIssue" in link and phrase in (typ.get("inward") or "").lower():
            now_block.add(link["inwardIssue"]["key"])
    events = []
    for t, it in _items(issue, "link"):
        if it.get("to") and phrase in (it.get("toString") or "").lower():
            events.append((t, it["to"], +1))
        if it.get("from") and phrase in (it.get("fromString") or "").lower():
            events.append((t, it["from"], -1))
    initial = set(now_block)
    for t, k, d in reversed(events):
        if d > 0:
            initial.discard(k)
        else:
            initial.add(k)

    # an issue moved in from another project joins the queue when it arrives, not when it was created
    moves = _items(issue, "project")
    entered = max(created, moves[-1][0]) if moves else created

    start = None
    if start_field:
        v = f.get(start_field)
        if v:
            start = dt.date.fromisoformat(str(v)[:10])
    tl = Timeline(key, created, steps, a_steps, initial, events, start, in_queue)
    tl.entered = entered
    return tl


class Board:
    def __init__(self, doc, ready=None, status_map=None, ignore_assignee=False, tz=dt.timezone.utc,
                 phrase=BLOCKED_BY, unreadable="refuse"):
        meta = doc.get("meta") or {}
        self.unreadable_mode = unreadable
        problems = []
        self.meta = meta
        self.tz = tz
        self.ignore_assignee = ignore_assignee
        if not meta.get("since"):
            raise Refused(["the file has no meta.since, so it is unknown which days are complete"])
        self.since = dt.date.fromisoformat(meta["since"])
        self.as_of = parse_ts(meta["fetched_at"]) if meta.get("fetched_at") else None
        if self.as_of is None:
            raise Refused(["the file has no meta.fetched_at"])
        issues = doc.get("issues") or []
        total = meta.get("search_total")
        if total is not None and total != len(issues):
            problems.append("the search reported %s issues but the file has %d" % (total, len(issues)))
        if meta.get("blockers_not_readable") and unreadable == "refuse":
            problems.append("blockers that could not be read: %s" % ", ".join(meta["blockers_not_readable"][:10]))

        cats = {}
        for name, cat in (doc.get("statuses") or {}).items():
            cats[name] = cat
        for spec in (status_map or []):
            name, _, cat = spec.partition("=")
            cats[name.strip()] = cat.strip()
        self.cats = cats

        self.start_field = meta.get("start_field")
        self.tl = {}
        for i in issues:
            self.tl[i["key"]] = build_timeline(i, True, phrase, self.start_field, problems)
        for i in doc.get("context") or []:
            if i["key"] not in self.tl:
                self.tl[i["key"]] = build_timeline(i, False, phrase, self.start_field, problems)
        if self.start_field and not any(x.start for x in self.tl.values() if x.in_queue):
            problems.append("start field %s was fetched but no issue has a value in it" % self.start_field)

        unknown = set()
        for x in self.tl.values():
            for name in x.status_v:
                if cats.get(name) not in ("new", "indeterminate", "done"):
                    unknown.add(name)
        if unknown:
            problems.append("status names with no known category (rename? add --status-map 'Name=done'): %s"
                            % ", ".join(sorted(unknown)))

        missing = set()
        for x in self.tl.values():
            if not x.in_queue:
                continue
            for k in x.blocker_initial:
                if k not in self.tl:
                    missing.add(k)
            for _, k, _ in x.blocker_events:
                if k not in self.tl:
                    missing.add(k)
        self.unreadable = missing
        if missing and unreadable == "refuse":
            problems.append("blocked by issues that are not in the file: %s (if your account cannot see them, "
                            "choose --unreadable-blockers blocking or ignore)" % ", ".join(sorted(missing)[:10]))

        if ready:
            bad = [r for r in ready if r not in cats]
            if bad:
                problems.append("--ready names statuses the site does not have: %s" % ", ".join(bad))
            self.ready = set(ready)
        else:
            self.ready = {n for n, c in cats.items() if c == "new"}
        if problems:
            raise Refused(problems)

    def pickable(self, x, t):
        if x.entered > t:
            return False
        if x.status_at(t) not in self.ready:
            return False
        if not self.ignore_assignee and x.assigned_at(t):
            return False
        for b in x.blockers_at(t):
            if b not in self.tl:
                if self.unreadable_mode == "blocking":
                    return False
                continue
            bt = self.tl[b]
            if bt.created <= t and self.cats.get(bt.status_at(t)) != "done":
                return False
        if x.start is not None and x.start > dt.datetime.fromtimestamp(t, self.tz).date():
            return False
        return True

    def days(self):
        """(date, instant) for every day from since to the fetch day. The fetch day ends at the fetch."""
        last = dt.datetime.fromtimestamp(self.as_of, self.tz).date()
        out = []
        d = self.since
        while d <= last:
            if d == last:
                inst = self.as_of
            else:
                nxt = d + dt.timedelta(days=1)
                inst = dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=self.tz).timestamp() - 1e-6
            out.append((d, inst))
            d += dt.timedelta(days=1)
        return out

    def series(self):
        """[(date, set of pickable keys)] for every day."""
        queue = [x for x in self.tl.values() if x.in_queue]
        return [(d, {x.key for x in queue if self.pickable(x, t)}) for d, t in self.days()]


def forecast_at(counts, c, window):
    """Forecast from the count on day index c, using days c-window .. c. Returns a dict."""
    if c - window < 0:
        raise Refused(["the history covers %d days before this day; --window needs %d" % (c, window)])
    n = counts[c]
    drain = (counts[c - window] - n) / window
    weeks = []
    for b in range(window // 7):
        lo = c - window + 7 * b
        weeks.append((counts[lo] - counts[lo + 7]) / 7)
    fast = max(weeks) if weeks else drain
    slow = min(weeks) if weeks else drain

    def days_for(rate):
        if n == 0:
            return 0
        if rate <= 0:
            return None
        return math.ceil(n / rate)

    return {"now": n, "drain": drain, "days": days_for(drain), "earliest": days_for(fast),
            "latest": days_for(slow), "fast": fast, "slow": slow}


def first_zero(counts, c, horizon):
    for k in range(c + 1, min(len(counts), c + horizon + 1)):
        if counts[k] == 0:
            return k - c
    return None


def backtest(counts, window, horizon, step=7, tolerance=7):
    """Replay: forecast every `step` days using only what was known then, compare with what happened."""
    rows = []
    for c in range(window, len(counts) - horizon, step):
        if counts[c] == 0:
            rows.append((c, None, None, "already-idle"))
            continue
        f = forecast_at(counts, c, window)
        pred = f["days"] if f["days"] is not None and f["days"] <= horizon else None
        actual = first_zero(counts, c, horizon)
        if pred is None and actual is None:
            kind = "quiet-right"
        elif pred is None:
            kind = "missed"
        elif actual is None:
            kind = "false-alarm"
        elif abs(pred - actual) <= tolerance:
            kind = "hit"
        elif pred < actual:
            kind = "early"
        else:
            kind = "late"
        rows.append((c, pred, actual, kind))
    return rows


def runs_of_zero(counts):
    best, cur, end = 0, 0, None
    for i, n in enumerate(counts):
        cur = cur + 1 if n == 0 else 0
        if cur > best:
            best, end = cur, i
    return best, end


def _date(d0, k):
    return (d0 + dt.timedelta(days=k)).isoformat()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", help="JSON written by fetch_jira.py")
    ap.add_argument("--ready", help="comma-separated status names that count as ready (default: the To Do category)")
    ap.add_argument("--status-map", action="append", default=[],
                    help="'Old status name=done' for names the site no longer has (repeatable)")
    ap.add_argument("--ignore-assignee", action="store_true",
                    help="an assigned issue can still be picked up (teams that assign on creation)")
    ap.add_argument("--window", type=int, default=28, help="days of history the pace is taken from (default 28)")
    ap.add_argument("--horizon", type=int, default=42, help="how far ahead a forecast counts (default 42)")
    ap.add_argument("--tz", default="UTC", help="where the team's day ends: UTC (default) or +09:00")
    ap.add_argument("--blocked-by", default=BLOCKED_BY, help="the inward name of the blocking link type")
    ap.add_argument("--unreadable-blockers", choices=("refuse", "blocking", "ignore"), default="refuse",
                    help="blockers you cannot read: refuse (default), count them as never finished, or drop them")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--series", action="store_true", help="TSV: date, pickable, entered, left")
    ap.add_argument("--fail-within", type=int, help="exit 1 if the forecast (or today) is idle within N days")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    if a.window < 7 or a.window % 7:
        print("--window must be a multiple of 7", file=sys.stderr)
        return 64
    try:
        tz = parse_tz(a.tz)
        with open(a.file, encoding="utf-8") as fh:
            doc = json.load(fh)
        ready = [r.strip() for r in a.ready.split(",")] if a.ready else None
        board = Board(doc, ready=ready, status_map=a.status_map, ignore_assignee=a.ignore_assignee, tz=tz,
                      phrase=a.blocked_by.lower(), unreadable=a.unreadable_blockers)
        ser = board.series()
        counts = [len(s) for _, s in ser]
        d0 = ser[0][0]
        if a.series:
            print("date\tpickable\tentered\tleft")
            for k, (d, s) in enumerate(ser):
                if k == 0:
                    print("%s\t%d\t\t" % (d, len(s)))
                else:
                    prev = ser[k - 1][1]
                    print("%s\t%d\t%d\t%d" % (d, len(s), len(s - prev), len(prev - s)))
            return 0
        c = len(counts) - 1
        f = forecast_at(counts, c, a.window)
    except Refused as e:
        print("REFUSED  no forecast; the data cannot support one:")
        for r in e.reasons[:25]:
            print("  - " + r)
        if len(e.reasons) > 25:
            print("  ... and %d more" % (len(e.reasons) - 25))
        return 2
    except (OSError, ValueError, KeyError) as e:
        print("REFUSED  %s" % e)
        return 2

    meta = board.meta
    today = ser[c][0]
    entered = sum(len(ser[k][1] - ser[k - 1][1]) for k in range(c - a.window + 1, c + 1))
    left = sum(len(ser[k - 1][1] - ser[k][1]) for k in range(c - a.window + 1, c + 1))
    print("idle-day-forecast  %s  (%s)" % (meta.get("jql"), meta.get("base")))
    shown = (", ".join(sorted(board.ready)) if ready
             else "every status in the To Do category (%d on this site)" % len(board.ready))
    print("as of %s, day ends at %s; ready = %s%s"
          % (today, a.tz, shown,
             "; assignee ignored" if a.ignore_assignee else ""))
    if board.unreadable:
        print("blockers not in the file: %d, counted as %s (--unreadable-blockers)"
              % (len(board.unreadable), "never finished" if a.unreadable_blockers == "blocking" else "absent"))
    print("pickable now: %d" % f["now"] + ("  (%s)" % ", ".join(sorted(ser[c][1])[:10]) if ser[c][1] else ""))
    print("last %d days: %d became pickable, %d stopped being pickable -> the count fell %.2f a day"
          % (a.window, entered, left, f["drain"]))
    if f["now"] == 0:
        run = 0
        k = c
        while k >= 0 and counts[k] == 0:
            run, k = run + 1, k - 1
        print("forecast: nothing to pick up now (for %d day%s)" % (run, "" if run == 1 else "s"))
        hit = a.fail_within is not None
    elif f["days"] is None:
        print("forecast: at the pace of the last %d days the pickable count does not reach 0" % a.window)
        hit = False
    else:
        early = _date(today, f["earliest"]) if f["earliest"] is not None else "never"
        late = _date(today, f["latest"]) if f["latest"] is not None else "never"
        print("forecast: pickable reaches 0 around %s (in %d days; fastest week -> %s, slowest week -> %s)"
              % (_date(today, f["days"]), f["days"], early, late))
        hit = a.fail_within is not None and f["days"] <= a.fail_within
    zeros = sum(1 for n in counts if n == 0)
    best, end = runs_of_zero(counts)
    print("history %s .. %s: %d idle day%s%s" % (d0, today, zeros, "" if zeros == 1 else "s",
                                                 ", longest run %d ending %s" % (best, _date(d0, end)) if best else ""))

    if a.backtest:
        rows = backtest(counts, a.window, a.horizon)
        kinds = {}
        for r in rows:
            kinds[r[3]] = kinds.get(r[3], 0) + 1
        scored = [r for r in rows if r[3] != "already-idle"]
        right = sum(1 for r in scored if r[3] in ("hit", "quiet-right"))
        base = sum(1 for r in scored if r[2] is None)
        print("")
        print("backtest: %d forecasts, one a week, each using only the %d days before it, checked %d days ahead"
              % (len(rows), a.window, a.horizon))
        for k in ("hit", "early", "late", "false-alarm", "missed", "quiet-right", "already-idle"):
            print("  %-12s %d" % (k, kinds.get(k, 0)))
        if scored:
            print("  right %d of %d; always saying 'no idle day' would have been right %d of %d"
                  % (right, len(scored), base, len(scored)))
        for c2, pred, actual, kind in rows:
            print("  %s  pickable %3d  forecast %-10s actual %-10s %s"
                  % (_date(d0, c2), counts[c2], "day %d" % pred if pred is not None else "-",
                     "day %d" % actual if actual is not None else "-", kind))
    return 1 if hit else 0


if __name__ == "__main__":
    sys.exit(main())
