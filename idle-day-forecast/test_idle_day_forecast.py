# -*- coding: utf-8 -*-
"""Tests for idle_day_forecast.py.   python -m unittest test_idle_day_forecast -v"""
import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest

import idle_day_forecast as idf

STATUSES = {"To Do": "new", "Ready": "new", "Backlog": "new", "In Progress": "indeterminate",
            "Done": "done", "Closed": "done"}
SINCE = "2026-01-01"


def ts(day, hour=12, minute=0, off="+0000"):
    """Timestamp `day` days after SINCE, in Jira's format."""
    d = dt.date.fromisoformat(SINCE) + dt.timedelta(days=day)
    return "%sT%02d:%02d:00.000%s" % (d.isoformat(), hour, minute, off)


def issue(key, created=0, status="To Do", assignee=None, history=(), blocked_by=(), start=None):
    """history: [(day, field, from, to)] with field status / assignee / link (to = key added, from = removed)."""
    hs = []
    for h in history:
        day, field, frm, to = h[:4]
        hour = h[4] if len(h) > 4 else 12
        if field == "status":
            it = {"field": "status", "fromString": frm, "toString": to}
        elif field == "assignee":
            it = {"field": "assignee", "from": frm, "fromString": frm, "to": to, "toString": to}
        else:
            it = {"field": "Link", "from": frm, "to": to,
                  "fromString": "This issue is blocked by %s" % frm if frm else None,
                  "toString": "This issue is blocked by %s" % to if to else None}
        hs.append({"created": ts(day, hour), "items": [it]})
    links = [{"type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
              "inwardIssue": {"key": k}} for k in blocked_by]
    f = {"created": ts(created, 1), "status": {"name": status}, "assignee": {"accountId": assignee} if assignee else None,
         "issuelinks": links, "resolutiondate": None}
    if start:
        f["customfield_1"] = start
    return {"key": key, "fields": f, "changelog": {"histories": hs, "total": len(hs)}}


def doc(issues, fetched_day=40, context=(), total=None, **meta):
    m = {"base": "https://example.invalid", "jql": "project = T", "since": SINCE,
         "fetched_at": ts(fetched_day, 23, 0), "search_total": len(issues) if total is None else total,
         "blockers_not_readable": []}
    m.update(meta)
    return {"meta": m, "statuses": dict(STATUSES), "issues": list(issues), "context": list(context)}


def counts(d, **kw):
    b = idf.Board(d, **kw)
    return [len(s) for _, s in b.series()]


def run(d, *args):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = idf.main([path] + list(args))
    finally:
        os.remove(path)
    return code, out.getvalue()


class Timestamps(unittest.TestCase):
    def test_formats(self):
        a = idf.parse_ts("2026-09-23T10:13:23.000+0000")
        self.assertEqual(a, idf.parse_ts("2026-09-23T10:13:23+00:00"))
        self.assertEqual(a, idf.parse_ts("2026-09-23T10:13:23Z"))
        self.assertEqual(a, idf.parse_ts("2026-09-23T20:13:23.000+1000"))
        self.assertEqual(a, idf.parse_ts("2026-09-23T05:13:23.000-05:00"))
        self.assertAlmostEqual(idf.parse_ts("2026-09-23T10:13:23.250+0000") - a, 0.25)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            idf.parse_ts("23/Sep/26 10:13")


class Rebuild(unittest.TestCase):
    def test_assigned_stops_being_pickable(self):
        d = doc([issue("T-1", assignee="u1", history=[(3, "assignee", None, "u1")])])
        c = counts(d)
        self.assertEqual(c[:5], [1, 1, 1, 0, 0])
        self.assertEqual(c[-1], 0)

    def test_created_later_is_not_counted_before(self):
        d = doc([issue("T-1", created=5)])
        c = counts(d)
        self.assertEqual(c[4], 0)
        self.assertEqual(c[5], 1)

    def test_moved_in_from_another_project_counts_from_the_move(self):
        i = issue("T-1", created=0)
        i["changelog"]["histories"].append({"created": ts(5), "items": [
            {"field": "project", "from": "10", "fromString": "Other", "to": "20", "toString": "This"}]})
        i["changelog"]["total"] = 1
        c = counts(doc([i]))
        self.assertEqual(c[4], 0)
        self.assertEqual(c[5], 1)

    def test_moved_back_to_todo_is_pickable_again(self):
        d = doc([issue("T-1", status="To Do", history=[(2, "status", "To Do", "In Progress"),
                                                         (6, "status", "In Progress", "To Do")])])
        c = counts(d)
        self.assertEqual(c[:8], [1, 1, 0, 0, 0, 0, 1, 1])

    def test_blocked_until_blocker_done(self):
        blocker = issue("T-2", status="Done", assignee="u2", history=[(0, "assignee", None, "u2", 2),
                                                                       (0, "status", "To Do", "In Progress", 3),
                                                                       (5, "status", "In Progress", "Done")])
        d = doc([issue("T-1", blocked_by=["T-2"]), blocker])
        b = idf.Board(d)
        ser = b.series()
        self.assertNotIn("T-1", ser[4][1])
        self.assertIn("T-1", ser[5][1])

    def test_blocker_in_context_file_is_used_but_not_counted(self):
        blocker = issue("X-9", status="In Progress", history=[(0, "status", "To Do", "In Progress", 3)])
        d = doc([issue("T-1", blocked_by=["X-9"])], context=[blocker])
        c = counts(d)
        self.assertEqual(c[0], 0)          # blocked, and X-9 itself is not part of the queue
        self.assertEqual(max(c), 0)

    def test_link_removed_unblocks(self):
        blocker = issue("T-2", status="In Progress", assignee="u", history=[(0, "status", "To Do", "In Progress", 3)])
        d = doc([issue("T-1", history=[(4, "link", "T-2", None)]), blocker])
        ser = idf.Board(d).series()
        self.assertNotIn("T-1", ser[3][1])
        self.assertIn("T-1", ser[4][1])

    def test_link_added_later_blocks_from_then(self):
        blocker = issue("T-2", status="In Progress", assignee="u", history=[(0, "status", "To Do", "In Progress", 3)])
        d = doc([issue("T-1", blocked_by=["T-2"], history=[(4, "link", None, "T-2")]), blocker])
        ser = idf.Board(d).series()
        self.assertIn("T-1", ser[3][1])
        self.assertNotIn("T-1", ser[4][1])

    def test_blocker_reopened_blocks_again(self):
        blocker = issue("T-2", status="To Do", assignee="u",
                        history=[(0, "status", "To Do", "Done", 3), (6, "status", "Done", "To Do")])
        d = doc([issue("T-1", blocked_by=["T-2"]), blocker])
        ser = idf.Board(d).series()
        self.assertIn("T-1", ser[5][1])
        self.assertNotIn("T-1", ser[6][1])

    def test_future_start_date_is_not_pickable(self):
        d = doc([issue("T-1", start="2026-01-10")], start_field="customfield_1")
        ser = idf.Board(d).series()
        self.assertNotIn("T-1", ser[8][1])
        self.assertIn("T-1", ser[9][1])

    def test_ready_statuses_can_be_narrowed(self):
        d = doc([issue("T-1", status="Backlog"), issue("T-2", status="Ready")])
        self.assertEqual(counts(d)[-1], 2)
        self.assertEqual(counts(d, ready=["Ready"])[-1], 1)

    def test_ignore_assignee(self):
        d = doc([issue("T-1", assignee="u", history=[(0, "assignee", None, "u", 3)])])
        self.assertEqual(counts(d)[-1], 0)
        self.assertEqual(counts(d, ignore_assignee=True)[-1], 1)

    def test_day_ends_in_the_team_time_zone(self):
        # assigned at 20:00 UTC on day 3 = 05:00 on day 4 in +09:00
        d = doc([issue("T-1", assignee="u", history=[(3, "assignee", None, "u", 20)])])
        self.assertEqual(counts(d)[3], 0)
        self.assertEqual(counts(d, tz=idf.parse_tz("+09:00"))[3], 1)

    def test_entered_and_left_in_series(self):
        d = doc([issue("T-1", assignee="u", history=[(3, "assignee", None, "u")]), issue("T-2", created=3)])
        code, out = run(d, "--series")
        self.assertEqual(code, 0)
        row = [l for l in out.splitlines() if l.startswith("2026-01-04")][0]
        self.assertEqual(row.split("\t"), ["2026-01-04", "1", "1", "1"])


class Refusals(unittest.TestCase):
    def refused(self, d, *args):
        code, out = run(d, *args)
        self.assertEqual(code, 2, out)
        self.assertIn("REFUSED", out)
        return out

    def test_search_total_mismatch(self):
        out = self.refused(doc([issue("T-1")], total=5))
        self.assertIn("reported 5", out)

    def test_changelog_cut_short(self):
        i = issue("T-1", history=[(2, "status", "To Do", "In Progress")], status="In Progress")
        i["changelog"]["total"] = 3
        self.assertIn("cut short", self.refused(doc([i])))

    def test_unknown_status_name(self):
        i = issue("T-1", status="To Do", history=[(2, "status", "Selected", "To Do")])
        out = self.refused(doc([i]))
        self.assertIn("Selected", out)
        code, _ = run(doc([i]), "--status-map", "Selected=new")
        self.assertEqual(code, 0)

    def test_ambiguous_status_name(self):
        d = doc([issue("T-1", status="Ready", history=[(2, "status", "To Do", "Ready")])])
        d["statuses"]["Ready"] = "ambiguous"
        self.assertIn("Ready", self.refused(d))
        code, _ = run(d, "--status-map", "Ready=new")
        self.assertEqual(code, 0)

    def test_history_does_not_reach_current_status(self):
        i = issue("T-1", status="Done", history=[(2, "status", "To Do", "In Progress")])
        self.assertIn("ends at", self.refused(doc([i])))

    def test_history_with_a_gap(self):
        i = issue("T-1", status="Done", history=[(2, "status", "To Do", "In Progress"),
                                                 (3, "status", "Ready", "Done")])
        self.assertIn("jumps", self.refused(doc([i])))

    def test_assignee_history_does_not_reach_current(self):
        i = issue("T-1", assignee=None, history=[(2, "assignee", None, "u")])
        self.assertIn("assignee history", self.refused(doc([i])))

    def test_blocker_not_in_file(self):
        self.assertIn("not in the file", self.refused(doc([issue("T-1", blocked_by=["Z-1"])])))

    def test_unreadable_blockers_chosen_explicitly(self):
        d = doc([issue("T-1", blocked_by=["Z-1"]), issue("T-2")], blockers_not_readable=["Z-1"])
        self.refused(d)
        code, out = run(d, "--unreadable-blockers", "blocking")
        self.assertEqual(code, 0, out)
        self.assertIn("pickable now: 1", out)
        self.assertIn("never finished", out)
        code, out = run(d, "--unreadable-blockers", "ignore")
        self.assertIn("pickable now: 2", out)

    def test_blocker_that_was_removed_is_still_needed(self):
        # the link existed for a while; its blocker's state then matters, so it must be in the file
        i = issue("T-1", history=[(4, "link", "Z-1", None)])
        self.assertIn("Z-1", self.refused(doc([i])))

    def test_fetch_said_blockers_unreadable(self):
        self.assertIn("could not be read", self.refused(doc([issue("T-1")], blockers_not_readable=["Z-1"])))

    def test_ready_typo(self):
        self.assertIn("does not have", self.refused(doc([issue("T-1")]), "--ready", "Redy"))

    def test_start_field_with_no_values(self):
        self.assertIn("no issue has a value", self.refused(doc([issue("T-1")], start_field="customfield_1")))

    def test_window_longer_than_history(self):
        self.assertIn("--window needs", self.refused(doc([issue("T-1")], fetched_day=10)))

    def test_no_since(self):
        d = doc([issue("T-1")])
        del d["meta"]["since"]
        self.refused(d)


class Forecast(unittest.TestCase):
    def test_arithmetic(self):
        c = [10 + 28 - k for k in range(29)]   # 38 .. 10, falling 1 a day
        f = idf.forecast_at(c, 28, 28)
        self.assertEqual(f["now"], 10)
        self.assertAlmostEqual(f["drain"], 1.0)
        self.assertEqual(f["days"], 10)

    def test_rounds_up(self):
        # fell 21 in 28 days = 0.75 a day; 10 left -> 13.3 days -> 14, never 13
        f = idf.forecast_at([31] + [10] * 28, 28, 28)
        self.assertAlmostEqual(f["drain"], 0.75)
        self.assertEqual(f["days"], 14)

    def test_week_range(self):
        # weeks fall 14, 7, 0, 7 -> fastest 2 a day, slowest 0 a day
        c = [40]
        for per_day in [2] * 7 + [1] * 7 + [0] * 7 + [1] * 7:
            c.append(c[-1] - per_day)
        f = idf.forecast_at(c, 28, 28)
        self.assertEqual(f["now"], 12)
        self.assertEqual(f["earliest"], 6)
        self.assertIsNone(f["latest"])
        self.assertEqual(f["days"], 12)

    def test_growing_backlog_never(self):
        f = idf.forecast_at([5] + [6] * 28, 28, 28)
        self.assertIsNone(f["days"])

    def test_end_to_end_date(self):
        # 20 issues, one assigned a day from day 1: 40 days of history
        iss = [issue("T-%d" % k, assignee="u", history=[(k, "assignee", None, "u")]) for k in range(1, 41)]
        iss += [issue("T-%d" % k) for k in range(41, 51)]
        code, out = run(doc(iss, fetched_day=30), "--window", "28")
        self.assertEqual(code, 0, out)
        # day 30: 20 still pickable (T-31..T-50), falling 1 a day -> 20 days -> 2026-01-31 + 20
        self.assertIn("pickable now: 20", out)
        self.assertIn("around 2026-02-20", out)

    def test_fail_within(self):
        iss = [issue("T-%d" % k, assignee="u", history=[(k, "assignee", None, "u")]) for k in range(1, 36)]
        code, out = run(doc(iss, fetched_day=30), "--fail-within", "10")
        self.assertIn("pickable now: 5", out)
        self.assertEqual(code, 1)
        code, _ = run(doc(iss, fetched_day=30), "--fail-within", "4")
        self.assertEqual(code, 0)

    def test_idle_now_with_fail_within(self):
        iss = [issue("T-1", assignee="u", history=[(2, "assignee", None, "u")])]
        code, out = run(doc(iss, fetched_day=30), "--fail-within", "3")
        self.assertIn("nothing to pick up now", out)
        self.assertEqual(code, 1)
        code, _ = run(doc(iss, fetched_day=30))
        self.assertEqual(code, 0)


class Backtest(unittest.TestCase):
    def test_classification(self):
        w, h = 7, 14
        # day 7: 14 left, falling 2 a day -> day 7 forecast = 7 days; zero really comes at day 14 -> hit
        c = [28 - 2 * k for k in range(15)] + [0] * 20
        rows = idf.backtest(c, w, h, step=7)
        self.assertEqual(rows[0][:4], (7, 7, 7, "hit"))
        self.assertEqual(rows[1][3], "already-idle")

    def test_false_alarm_quiet_and_missed(self):
        w, h = 7, 7
        c = [14 - k for k in range(8)] + [7] * 7 + [7] * 7 + [0] * 8
        rows = {r[0]: r[3] for r in idf.backtest(c, w, h, step=7)}
        self.assertEqual(rows[7], "false-alarm")   # predicted zero in 7, it stayed at 7
        self.assertEqual(rows[14], "quiet-right")  # flat, no forecast, nothing happened
        self.assertEqual(rows[21], "missed")       # flat, no forecast; then everything closed at once

    def test_early_and_late(self):
        w, h = 7, 28
        # from day 7: falling 1 a day -> forecast 28 days; it really empties 21 days later -> late
        c = [35 - k for k in range(8)] + [28] * 20 + [0] * 15
        rows = {r[0]: r for r in idf.backtest(c, w, h, step=7, tolerance=3)}
        self.assertEqual(rows[7][1:], (28, 21, "late"))
        # from day 7: falling 5 a day -> forecast 7 days; it slows down and empties 20 days later -> early
        c2 = [70 - 5 * k for k in range(8)] + [35 - (35 * j) // 20 for j in range(1, 21)] + [0] * 15
        rows2 = {r[0]: r for r in idf.backtest(c2, w, h, step=7, tolerance=3)}
        self.assertEqual(rows2[7][1:], (7, 20, "early"))

    def test_backtest_output_compares_with_never(self):
        iss = [issue("T-%d" % k, assignee="u", history=[(k, "assignee", None, "u")]) for k in range(1, 81)]
        code, out = run(doc(iss, fetched_day=120), "--backtest", "--horizon", "14")
        self.assertEqual(code, 0, out)
        self.assertIn("always saying 'no idle day' would have been right", out)


if __name__ == "__main__":
    unittest.main()
