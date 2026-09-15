#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for both sides of the experiment. Standard library only.

    python test_refill_loop.py           # 18 checks, exit 0 when all pass

Every check here was watched to fail once, on purpose, before it was kept: a check
that has never been red is not yet an instrument.
"""
import datetime
import io
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import queue_forecast                                          # noqa: E402
import refill_loop                                             # noqa: E402
from refill_loop import actionable, next_unit, parse_rows, to_date   # noqa: E402

D = datetime.date
SEP15 = D(2026, 9, 15)


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class TestParse(unittest.TestCase):
    def test_kinds_english_and_japanese(self):
        rows = parse_rows("- [ ] (routine) a\n- [ ] 〔判断〕 b\n- [ ] (upstream) c\n", SEP15)
        self.assertEqual([r.kind for r in rows], ["routine", "judgment", "upstream"])

    def test_unmarked_row_needs_a_judgment(self):
        (r,) = parse_rows("- [ ] put one thing on the shelf\n", SEP15)
        self.assertEqual(r.kind, "judgment")
        self.assertEqual(r.text, "put one thing on the shelf")

    def test_marker_is_stripped_but_the_row_text_survives(self):
        (r,) = parse_rows("- [ ] (routine 09-16) shelf A | D+3 numbers\n", SEP15)
        self.assertEqual(r.text, "shelf A | D+3 numbers")
        self.assertEqual(r.date, D(2026, 9, 16))

    def test_wait_is_not_mistaken_for_a_kind(self):
        (r,) = parse_rows("- [ ] (wait) needs the owner\n", SEP15)
        self.assertTrue(r.blocked)
        self.assertEqual(r.kind, "judgment")       # not swallowed as a marker
        self.assertEqual(r.text, "(wait) needs the owner")

    def test_done_rows_and_prose_are_ignored(self):
        rows = parse_rows("# heading\n- [x] done\nsome prose\n- [ ] open\n", SEP15)
        self.assertEqual([r.done for r in rows], [True, False])


class TestDates(unittest.TestCase):
    def test_full_date(self):
        self.assertEqual(to_date("2026-09-16", SEP15), D(2026, 9, 16))

    def test_mm_dd_rolls_over_the_new_year(self):
        # a row marked 01-05, read on 30 December, is next week - not eleven months ago
        self.assertEqual(to_date("01-05", D(2026, 12, 30)), D(2027, 1, 5))

    def test_mm_dd_stays_in_the_past_when_it_is_the_past(self):
        self.assertEqual(to_date("09-14", SEP15), D(2026, 9, 14))

    def test_feb_29_in_a_non_leap_year_does_not_crash(self):
        self.assertEqual(to_date("02-29", D(2026, 3, 1)), D(2028, 2, 29))


class TestPick(unittest.TestCase):
    def test_takes_the_first_actionable_row_from_the_top(self):
        d = next_unit(read("sample_QUEUE.md"), SEP15)
        self.assertEqual(d["action"], "unit")
        self.assertFalse(d["refill"])
        self.assertTrue(d["row"].startswith("shelf C"))

    def test_postponed_and_blocked_rows_are_skipped(self):
        rows = parse_rows(read("sample_QUEUE.md"), SEP15)
        self.assertEqual(len(actionable(rows, SEP15)), 2)
        self.assertEqual(len(actionable(rows, D(2026, 9, 16))), 3)

    def test_an_empty_queue_refills_instead_of_stopping(self):
        d = next_unit(read("sample_QUEUE_broken.md"), SEP15)
        self.assertEqual(d["action"], "unit")          # the whole point: not "stop"
        self.assertTrue(d["refill"])
        self.assertEqual(d["kind"], "upstream")
        self.assertIn("0 of 9 open rows", d["why"])
        self.assertIn("09-16", d["why"])

    def test_the_refill_row_is_a_unit_of_work_not_a_message(self):
        d = next_unit("", SEP15)
        self.assertIn("Do not stop", d["row"])
        self.assertIn("three rows", d["row"])
        self.assertIn("undated", d["row"])

    def test_it_does_stop_once_refilling_has_not_helped(self):
        d = next_unit("", SEP15, same_row=3)
        self.assertEqual(d["action"], "stop")

    def test_cli_exit_codes(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(refill_loop.main([os.path.join(HERE, "sample_QUEUE.md"),
                                               "--today", "2026-09-15", "--json"]), 0)
            self.assertEqual(refill_loop.main([os.path.join(HERE, "sample_QUEUE_broken.md"),
                                               "--today", "2026-09-15",
                                               "--same-row", "3"]), 3)


class TestForecast(unittest.TestCase):
    def test_f1_fires_on_the_queue_that_broke_us(self):
        d = queue_forecast.forecast(read("sample_QUEUE_broken.md"), SEP15)
        self.assertEqual((d["open"], d["actionable"], d["blocked"], d["postponed"]),
                         (9, 0, 1, 8))
        self.assertTrue(d["findings"][0].startswith("F1"))
        self.assertEqual(d["next_date"], "2026-09-16")

    def test_f2_catches_it_a_day_earlier_than_f1(self):
        # run on the evening of 09-14, looking at 09-15: F1 and F2 both fire.
        # run looking at 09-16, when four rows free up, F1 is quiet and F2 is not.
        text = read("sample_QUEUE_broken.md")
        codes = [f[:2] for f in queue_forecast.forecast(text, D(2026, 9, 16))["findings"]]
        self.assertEqual(codes, ["F2"])

    def test_a_healthy_queue_is_quiet(self):
        self.assertEqual(queue_forecast.forecast(read("sample_QUEUE.md"), SEP15)["findings"], [])

    def test_cli_exit_1_on_a_finding_and_2_on_an_unreadable_file(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(queue_forecast.main([os.path.join(HERE, "sample_QUEUE_broken.md"),
                                                  "--date", "2026-09-15"]), 1)
            self.assertEqual(queue_forecast.main([os.path.join(HERE, "sample_QUEUE.md"),
                                                  "--date", "2026-09-15"]), 0)
            self.assertEqual(queue_forecast.main([os.path.join(HERE, "no_such_file.md")]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
