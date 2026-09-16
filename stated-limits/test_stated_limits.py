# -*- coding: utf-8 -*-
"""Tests for stated_limits. Standard library only.

    python test_stated_limits.py

Every test that asserts a breach has a partner that asserts the same shape does NOT
breach, because a checker that says "over" about everything is worse than no checker.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stated_limits as sl  # noqa: E402

HERE = Path(__file__).resolve().parent

JP_LINE = "行"          # line
JP_CHAR = "字"          # character
JP_WITHIN = "以内"  # within
JP_TIMES = "回"         # times
JP_TOTAL = "合計"   # combined
JP_ONE_LINE = "1 行"    # "1 line"
JP_EACH = "各"          # each


def q(text):
    """Shorthand: the ceilings a sentence declares, as (value, unit) pairs."""
    return [(lim["value"], lim["unit"]) for lim in sl.find_limits(text)]


class Quantities(unittest.TestCase):
    def test_english_unit_after_number(self):
        self.assertEqual(sl.find_quantities("250 lines")[0][:2], (250.0, sl._UNIT_LINES))

    def test_comma_thousands(self):
        self.assertEqual(sl.find_quantities("1,000 lines")[0][0], 1000.0)

    def test_decimal(self):
        self.assertEqual(sl.find_quantities("1.5 MB")[0][0], 1.5)

    def test_japanese_unit(self):
        got = sl.find_quantities("250 " + JP_LINE)
        self.assertEqual(got[0][:2], (250.0, sl._UNIT_LINES))

    def test_no_unit_is_not_a_quantity(self):
        self.assertEqual(sl.find_quantities("chapter 250 of the book"), [])

    def test_kb_multiplier_is_si_by_default(self):
        self.assertEqual(sl.find_quantities("50 KB")[0][2], 1000)

    def test_kib_multiplier_is_binary(self):
        self.assertEqual(sl.find_quantities("50 KiB")[0][2], 1024)

    def test_longest_unit_wins(self):
        # "characters" must not be read as "chars" plus junk.
        val, unit, _, _, end = sl.find_quantities("200 characters")[0]
        self.assertEqual((val, unit), (200.0, sl._UNIT_CHARS))
        self.assertEqual(end, len("200 characters"))


class Ceilings(unittest.TestCase):
    def test_japanese_suffix_makes_a_ceiling(self):
        self.assertEqual(q("250 " + JP_LINE + JP_WITHIN), [(250.0, sl._UNIT_LINES)])

    def test_english_prefix_makes_a_ceiling(self):
        self.assertEqual(q("no more than 250 lines"), [(250.0, sl._UNIT_LINES)])

    def test_under(self):
        self.assertEqual(q("keep it under 80 lines"), [(80.0, sl._UNIT_LINES)])

    def test_at_most(self):
        self.assertEqual(q("at most 12 KB"), [(12.0, sl._UNIT_BYTES)])

    def test_bare_quantity_is_not_a_ceiling(self):
        # The whole point: a number is not a rule. This is what keeps the noise out.
        self.assertEqual(q("the file is 250 lines long"), [])

    def test_measured_value_in_prose_is_not_a_ceiling(self):
        self.assertEqual(q("it measured 111 KB on 2026-09-10"), [])

    def test_chain_shares_one_trailing_cap(self):
        # "250 lines / 50 KB or under" is two ceilings, not one.
        got = q("%s 250 %s・50 KB%s" % (JP_TOTAL, JP_LINE, JP_WITHIN))
        self.assertEqual(sorted(got), [(50.0, sl._UNIT_BYTES), (250.0, sl._UNIT_LINES)])

    def test_chain_stops_at_other_words(self):
        # A quantity separated by prose is not part of the chain.
        got = q("was 900 lines, and is now 250 lines" + "" + " at most 80 lines")
        self.assertEqual(got, [(80.0, sl._UNIT_LINES)])

    def test_english_trailing_cap(self):
        self.assertEqual(q("STATUS.md is 80 lines or under."), [(80.0, sl._UNIT_LINES)])

    def test_english_trailing_cap_after_a_scope_word(self):
        self.assertEqual(q("A.md / B.md, 250 lines combined or under."),
                         [(250.0, sl._UNIT_LINES)])

    def test_at_most_belongs_to_the_number_after_it(self):
        self.assertEqual(q("250 lines at most 80 lines"), [(80.0, sl._UNIT_LINES)])

    def test_at_most_trailing_a_clause_is_a_cap(self):
        self.assertEqual(q("A.md is 80 lines at most."), [(80.0, sl._UNIT_LINES)])

    def test_event_unit_is_still_collected(self):
        self.assertEqual(q("1-3 " + JP_TIMES + JP_WITHIN), [(3.0, sl._UNIT_EVENTS)])

    def test_range_upper_end_is_the_ceiling(self):
        self.assertEqual(q("no more than 1-3 pushes"), [(3.0, sl._UNIT_EVENTS)])

    def test_bare_range_of_events_is_a_ceiling(self):
        # "1-3 pushes a week" with no cap word is the sentence this tool was built from.
        self.assertEqual(q("1-3 " + JP_TIMES), [(3.0, sl._UNIT_EVENTS)])

    def test_bare_range_of_lines_is_not_a_ceiling(self):
        # The same leniency applied to a measurable unit would turn "lines 3-5 of the
        # table" into a verdict about a file. Only event units get it.
        self.assertEqual(q("see lines 3-5 lines"), [])

    def test_scope_per_line(self):
        lim = sl.find_limits("%s(200 %s%s" % (JP_ONE_LINE, JP_CHAR, JP_WITHIN))[0]
        self.assertEqual(lim["scope"], "per-line")

    def test_scope_per_line_english(self):
        self.assertEqual(sl.find_limits("each line under 200 chars")[0]["scope"], "per-line")

    def test_scope_per_file(self):
        self.assertEqual(sl.find_limits("each file under 30 lines")[0]["scope"], "per-file")

    def test_scope_per_file_japanese(self):
        lim = sl.find_limits("%s 30 %s%s" % (JP_EACH, JP_LINE, JP_WITHIN))[0]
        self.assertEqual(lim["scope"], "per-file")

    def test_scope_defaults_to_whole(self):
        self.assertEqual(sl.find_limits("no more than 80 lines")[0]["scope"], "whole")

    def test_as_written_is_kept_verbatim(self):
        self.assertEqual(sl.find_limits("at most 12 KB")[0]["as_written"], "12 KB")


class Targets(unittest.TestCase):
    def test_markdown_link(self):
        self.assertEqual(sl.find_targets("see [S](docs/STATUS.md) now"), ["docs/STATUS.md"])

    def test_anchor_is_dropped(self):
        self.assertEqual(sl.find_targets("[S](docs/S.md#top)"), ["docs/S.md"])

    def test_http_link_is_not_a_file(self):
        self.assertEqual(sl.find_targets("[x](https://example.com/a.md)"), [])

    def test_backtick_path(self):
        self.assertEqual(sl.find_targets("keep `.claude/rules/` small"), [".claude/rules/"])

    def test_bare_path(self):
        self.assertEqual(sl.find_targets("CLAUDE.md is the entry"), ["CLAUDE.md"])

    def test_three_bare_paths_keep_order(self):
        self.assertEqual(sl.find_targets("A.md / B.md / C.md"), ["A.md", "B.md", "C.md"])

    def test_no_extension_is_not_a_target(self):
        # "CLAUDE / STATUS / DECISIONS" names nothing a tool can open. This is the case
        # the tool exists to report, so it must not silently guess an extension.
        self.assertEqual(sl.find_targets("(CLAUDE / STATUS / DECISIONS)"), [])

    def test_glob_is_not_a_target(self):
        self.assertEqual(sl.find_targets('`test_*.py`'), [])

    def test_glob_with_a_slash_is_not_a_target(self):
        # A path-shaped glob reaches the backtick branch, where only the star check
        # stops it. Without a slash the pattern never gets that far, so the first
        # version of this test passed with the star check deleted.
        self.assertEqual(sl.find_targets('keep `docs/*.md` short'), [])

    def test_duplicates_collapse(self):
        self.assertEqual(sl.find_targets("[D](D.md) and D.md"), ["D.md"])


class Sentences(unittest.TestCase):
    def test_fenced_block_is_skipped(self):
        text = "a\n```\nno more than 9 lines\n```\nb\n"
        joined = " ".join(s for _, s in sl.iter_sentences(text))
        self.assertNotIn("9 lines", joined)

    def test_tilde_fence_is_skipped(self):
        text = "a\n~~~\nno more than 9 lines\n~~~\n"
        joined = " ".join(s for _, s in sl.iter_sentences(text))
        self.assertNotIn("9 lines", joined)

    def test_table_cells_split(self):
        got = [s.strip() for _, s in sl.iter_sentences("| A.md | 80 lines |")]
        self.assertIn("A.md", got)
        self.assertIn("80 lines", got)

    def test_japanese_full_stop_splits(self):
        got = [s for _, s in sl.iter_sentences("A.md。B.md。")]
        self.assertEqual(len(got), 2)

    def test_line_numbers_are_one_based(self):
        got = list(sl.iter_sentences("first\nsecond\n"))
        self.assertEqual(got[0][0], 1)
        self.assertEqual(got[1][0], 2)

    def test_english_period_inside_a_filename_does_not_split(self):
        got = [s for _, s in sl.iter_sentences("CLAUDE.md holds the rule")]
        self.assertEqual(len(got), 1)

    def test_emphasis_does_not_move_offsets(self):
        raw = "**250 lines**"
        self.assertEqual(len(sl.strip_emphasis(raw)), len(raw))
        self.assertEqual(q(sl.strip_emphasis("keep to **250 lines**")),
                         [(250.0, sl._UNIT_LINES)])


class Measuring(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, text):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_lines_match_wc_l_when_file_ends_with_newline(self):
        path = self.write("a.txt", "1\n2\n3\n")
        self.assertEqual(sl.measure(path, sl._UNIT_LINES, "whole", ())[0], 3.0)

    def test_last_line_without_newline_still_counts(self):
        path = self.write("a.txt", "1\n2\n3")
        self.assertEqual(sl.measure(path, sl._UNIT_LINES, "whole", ())[0], 3.0)

    def test_empty_file_is_zero_lines(self):
        path = self.write("a.txt", "")
        self.assertEqual(sl.measure(path, sl._UNIT_LINES, "whole", ())[0], 0.0)

    def test_chars_include_newlines(self):
        path = self.write("a.txt", "ab\ncd\n")
        self.assertEqual(sl.measure(path, sl._UNIT_CHARS, "whole", ())[0], 6.0)

    def test_per_line_chars_is_the_longest_line(self):
        path = self.write("a.txt", "ab\nabcdefgh\nx\n")
        got, detail = sl.measure(path, sl._UNIT_CHARS, "per-line", ())
        self.assertEqual(got, 8.0)
        self.assertIn("line 2", detail)

    def test_bytes_is_on_disk_size(self):
        path = self.write("a.txt", "abc")
        self.assertEqual(sl.measure(path, sl._UNIT_BYTES, "whole", ())[0], 3.0)

    def test_multibyte_bytes_differ_from_chars(self):
        path = self.write("a.txt", "行行")
        self.assertEqual(sl.measure(path, sl._UNIT_CHARS, "whole", ())[0], 2.0)
        self.assertEqual(sl.measure(path, sl._UNIT_BYTES, "whole", ())[0], 6.0)

    def test_directory_sums(self):
        self.write("d/a.txt", "1\n2\n")
        self.write("d/b.txt", "1\n")
        self.assertEqual(sl.measure(self.dir / "d", sl._UNIT_LINES, "whole", ())[0], 3.0)

    def test_directory_per_file_takes_the_largest(self):
        self.write("d/a.txt", "1\n2\n")
        self.write("d/b.txt", "1\n")
        got, detail = sl.measure(self.dir / "d", sl._UNIT_LINES, "per-file", ())
        self.assertEqual(got, 2.0)
        self.assertIn("a.txt", detail)

    def test_directory_recurses(self):
        self.write("d/x/a.txt", "1\n")
        self.write("d/b.txt", "1\n")
        self.assertEqual(sl.measure(self.dir / "d", sl._UNIT_LINES, "whole", ())[0], 2.0)

    def test_exclude_applies_to_directories(self):
        self.write("d/a.txt", "1\n2\n")
        self.write("d/skip.txt", "1\n2\n3\n4\n")
        got = sl.measure(self.dir / "d", sl._UNIT_LINES, "whole", ("skip.*",))[0]
        self.assertEqual(got, 2.0)

    def test_empty_directory_raises_rather_than_reporting_zero(self):
        (self.dir / "empty").mkdir()
        with self.assertRaises(sl.ScanError):
            sl.measure(self.dir / "empty", sl._UNIT_LINES, "whole", ())

    def test_cp932_file_is_read_not_skipped(self):
        path = self.dir / "cp932.txt"
        path.write_bytes("行\n".encode("cp932"))
        self.assertEqual(sl.measure(path, sl._UNIT_LINES, "whole", ())[0], 1.0)


class KbReadings(unittest.TestCase):
    def ceilings(self, text, mode="both"):
        return sl._ceilings(sl.find_limits(text)[0], mode)

    def test_kb_is_judged_under_both_readings(self):
        got = dict(self.ceilings("at most 50 KB"))
        self.assertEqual(got["SI 1000"], 50000)
        self.assertEqual(got["binary 1024"], 51200)

    def test_kib_is_unambiguous(self):
        self.assertEqual(len(self.ceilings("at most 50 KiB")), 1)

    def test_lines_are_unambiguous(self):
        self.assertEqual(len(self.ceilings("at most 50 lines")), 1)

    def test_mode_1000_picks_one(self):
        self.assertEqual(self.ceilings("at most 50 KB", "1000"), [("SI 1000", 50000)])

    def test_mode_1024_picks_the_other(self):
        self.assertEqual(self.ceilings("at most 50 KB", "1024"), [("binary 1024", 51200)])

    def test_gb_scales(self):
        got = dict(self.ceilings("at most 5 GB"))
        self.assertEqual(got["SI 1000"], 5 * 1000 ** 3)


class Judging(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_scan(self, doc_text, files=(), **kw):
        (self.dir / "RULES.md").write_text(doc_text, encoding="utf-8")
        for name, text in files:
            path = self.dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return sl.scan([self.dir / "RULES.md"], self.dir, **kw)[0]

    def only(self, rows):
        self.assertEqual(len(rows), 1, "expected exactly one ceiling, got %d" % len(rows))
        return rows[0]

    def test_breach_is_named(self):
        row = self.only(self.run_scan("A.md is at most 2 lines",
                                      [("A.md", "1\n2\n3\n4\n")]))
        self.assertEqual(row["status"], "breach")
        self.assertEqual(row["actual"], 4.0)

    def test_same_shape_under_the_ceiling_is_ok(self):
        row = self.only(self.run_scan("A.md is at most 9 lines", [("A.md", "1\n2\n")]))
        self.assertEqual(row["status"], "ok")

    def test_equal_to_the_ceiling_is_not_a_breach(self):
        row = self.only(self.run_scan("A.md is at most 2 lines", [("A.md", "1\n2\n")]))
        self.assertEqual(row["status"], "ok")

    def test_one_over_is_a_breach(self):
        row = self.only(self.run_scan("A.md is at most 2 lines", [("A.md", "1\n2\n3\n")]))
        self.assertEqual(row["status"], "breach")

    def test_event_ceiling_is_unverifiable(self):
        row = self.only(self.run_scan("A.md: no more than 3 pushes", [("A.md", "x\n")]))
        self.assertEqual((row["status"], row["reason"]),
                         ("unverifiable", sl.R_UNMEASURABLE))

    def test_no_target_is_unverifiable(self):
        row = self.only(self.run_scan("keep the whole thing under 250 lines"))
        self.assertEqual((row["status"], row["reason"]), ("unverifiable", sl.R_NO_TARGET))

    def test_ambiguous_targets(self):
        row = self.only(self.run_scan("A.md / B.md at most 5 lines",
                                      [("A.md", "x\n"), ("B.md", "x\n")]))
        self.assertEqual((row["status"], row["reason"]), ("unverifiable", sl.R_AMBIGUOUS))

    def test_combined_word_resolves_the_ambiguity(self):
        row = self.only(self.run_scan("A.md / B.md combined at most 5 lines",
                                      [("A.md", "1\n2\n"), ("B.md", "1\n2\n")]))
        self.assertEqual((row["status"], row["actual"]), ("ok", 4.0))

    def test_combined_can_breach(self):
        row = self.only(self.run_scan("A.md / B.md combined at most 3 lines",
                                      [("A.md", "1\n2\n"), ("B.md", "1\n2\n")]))
        self.assertEqual(row["status"], "breach")

    def test_each_takes_the_largest_not_the_sum(self):
        row = self.only(self.run_scan("each file A.md / B.md at most 3 lines",
                                      [("A.md", "1\n2\n"), ("B.md", "1\n2\n")]))
        self.assertEqual((row["status"], row["actual"]), ("ok", 2.0))

    def test_missing_target(self):
        row = self.only(self.run_scan("GONE.md is at most 5 lines"))
        self.assertEqual((row["status"], row["reason"]), ("unverifiable", sl.R_MISSING))

    def test_self_reference_needs_the_flag(self):
        row = self.only(self.run_scan("this file stays under 1 lines\nand it does not\n"))
        self.assertEqual((row["status"], row["reason"]), ("unverifiable", sl.R_SELF))

    def test_self_reference_resolves_with_the_flag(self):
        row = self.only(self.run_scan("this file stays under 1 lines\nand it does not\n",
                                      allow_self=True))
        self.assertEqual((row["status"], row["actual"]), ("breach", 2.0))

    def test_target_is_inherited_from_the_previous_clause_on_one_line(self):
        text = "Layer 1 = A.md / B.md。%s 3 %s%s" % (JP_TOTAL, JP_LINE, JP_WITHIN)
        row = self.only(self.run_scan(text, [("A.md", "1\n2\n"), ("B.md", "1\n2\n")]))
        self.assertEqual((row["status"], row.get("inherited")), ("breach", True))

    def test_target_is_not_inherited_across_lines(self):
        text = "Layer 1 = A.md\nkeep it under 1 lines\n"
        row = self.only(self.run_scan(text, [("A.md", "1\n2\n")]))
        self.assertEqual(row["status"], "unverifiable")

    def test_a_later_clause_with_its_own_target_wins(self):
        text = "A.md is the entry。B.md is at most 1 lines。"
        row = self.only(self.run_scan(text, [("A.md", "x\n"), ("B.md", "1\n2\n")]))
        self.assertEqual(row["measured"], ["B.md"])

    def test_borderline_when_the_two_kb_readings_disagree(self):
        row = self.only(self.run_scan("A.md is at most 1 KB",
                                      [("A.md", "x" * 1010)]))
        self.assertEqual(row["status"], "borderline")
        self.assertEqual(row["over_under"], ["SI 1000"])

    def test_over_both_kb_readings_is_a_breach(self):
        row = self.only(self.run_scan("A.md is at most 1 KB", [("A.md", "x" * 2000)]))
        self.assertEqual(row["status"], "breach")

    def test_directory_target(self):
        row = self.only(self.run_scan("each file in `rules/` is at most 1 lines",
                                      [("rules/a.md", "1\n2\n")]))
        self.assertEqual(row["status"], "breach")

    def test_measured_paths_are_relative_to_root(self):
        row = self.only(self.run_scan("A.md is at most 9 lines", [("A.md", "x\n")]))
        self.assertEqual(row["measured"], ["A.md"])


class Report(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def build(self, doc_text, files=()):
        (self.dir / "RULES.md").write_text(doc_text, encoding="utf-8")
        for name, text in files:
            (self.dir / name).write_text(text, encoding="utf-8")
        rows, stats = sl.scan([self.dir / "RULES.md"], self.dir)
        return sl.render(rows, stats, show_all=True), rows

    def test_report_is_pure_ascii(self):
        # The whole class of bug this family of tools exists for: a report that cannot
        # be printed turns a clean run into an exit status somebody else believes.
        text = "%s(200 %s%s) A.md" % (JP_ONE_LINE, JP_CHAR, JP_WITHIN)
        report, _ = self.build(text, [("A.md", "行" * 300 + "\n")])
        report.encode("ascii")
        self.assertIn("BREACH", report)

    def test_report_survives_a_cp932_console(self):
        text = "%s(200 %s%s) A.md" % (JP_ONE_LINE, JP_CHAR, JP_WITHIN)
        report, _ = self.build(text, [("A.md", "行" * 300 + "\n")])
        report.encode("cp932")

    def test_japanese_prose_collapses_instead_of_flooding(self):
        report, _ = self.build("A.md は 1 lines " + JP_WITHIN, [("A.md", "1\n2\n")])
        self.assertIn("<JP", report)

    def test_ok_rows_are_hidden_without_all(self):
        (self.dir / "RULES.md").write_text("A.md is at most 9 lines", encoding="utf-8")
        (self.dir / "A.md").write_text("x\n", encoding="utf-8")
        rows, stats = sl.scan([self.dir / "RULES.md"], self.dir)
        self.assertNotIn("OK", sl.render(rows, stats, show_all=False))
        self.assertIn("OK", sl.render(rows, stats, show_all=True))

    def test_counts_line_up(self):
        report, rows = self.build(
            "A.md is at most 1 lines\nno more than 9 lines\n", [("A.md", "1\n2\n")])
        self.assertIn("limits found   2", report)
        self.assertIn("  checkable    1", report)
        self.assertIn("  unverifiable 1", report)
        self.assertIn("breached       1", report)

    def test_breach_sorts_above_unverifiable(self):
        report, _ = self.build(
            "no more than 9 lines\nA.md is at most 1 lines\n", [("A.md", "1\n2\n")])
        self.assertLess(report.index("BREACH"), report.index("UNVERIFIABLE"))

    def test_borderline_renders(self):
        # The borderline branch shipped with a broken format string and no test reached
        # it: every borderline test stopped at scan() and never rendered the report.
        report, _ = self.build("A.md is at most 1 KB", [("A.md", "x" * 1010)])
        self.assertIn("borderline     1", report)
        self.assertIn("over under SI 1000 only", report)

    def test_long_sentences_are_clipped(self):
        long_doc = "A.md " + "z" * 400 + " is at most 1 lines"
        report, _ = self.build(long_doc, [("A.md", "1\n2\n")])
        for line in report.splitlines():
            self.assertLess(len(line), 300)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_cli(self, *args, codec=None):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = codec or "utf-8"
        # The report is ASCII by contract, so any decoder reads it. Decode as UTF-8 with
        # replacement so that a contract violation shows up as a failed assertion here
        # rather than as an exception inside subprocess's reader thread.
        return subprocess.run(
            [sys.executable, str(HERE / "stated_limits.py")] + list(args),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, cwd=str(self.dir))

    def write(self, name, text):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_exit_0_when_nothing_is_over(self):
        self.write("R.md", "A.md is at most 9 lines")
        self.write("A.md", "x\n")
        self.assertEqual(self.run_cli("R.md").returncode, 0)

    def test_exit_1_on_a_breach(self):
        self.write("R.md", "A.md is at most 1 lines")
        self.write("A.md", "1\n2\n")
        self.assertEqual(self.run_cli("R.md").returncode, 1)

    def test_exit_0_when_only_unverifiable(self):
        # Unverifiable is a finding, not a failure: it must not fail somebody's CI.
        self.write("R.md", "keep it under 9 lines")
        self.assertEqual(self.run_cli("R.md").returncode, 0)

    def test_exit_2_on_a_missing_path(self):
        self.assertEqual(self.run_cli("nope.md").returncode, 2)

    def test_exit_2_when_no_document_matches(self):
        self.dir.joinpath("sub").mkdir()
        self.assertEqual(self.run_cli("sub").returncode, 2)

    def test_json_is_valid_and_ascii(self):
        self.write("R.md", "A.md is at most 1 " + JP_LINE + JP_WITHIN)
        self.write("A.md", "1\n2\n")
        out = self.run_cli("R.md", "--json").stdout
        out.encode("ascii")
        self.assertEqual(json.loads(out)["rows"][0]["status"], "breach")

    def test_directory_of_documents(self):
        self.write("docs/R.md", "A.md is at most 1 lines")
        self.write("A.md", "1\n2\n")
        self.assertEqual(self.run_cli("docs", "--root", ".").returncode, 1)

    def test_rewrite_hint_prints_and_exits_zero(self):
        got = self.run_cli("--rewrite-hint")
        self.assertEqual(got.returncode, 0)
        self.assertIn("decoration", got.stdout)

    def test_runs_on_a_cp932_console(self):
        # Pin the output stream to the codec that killed the link checker and re-run.
        self.write("R.md", "A.md は 1 " + JP_LINE + JP_WITHIN)
        self.write("A.md", "1\n2\n")
        got = self.run_cli("R.md", codec="cp932")
        self.assertEqual(got.returncode, 1, got.stderr)
        self.assertIn("BREACH", got.stdout)

    def test_version(self):
        self.assertIn(sl.__version__, self.run_cli("--version").stdout)

    def test_self_flag_changes_the_verdict(self):
        self.write("R.md", "this file stays under 1 lines\nand it does not\n")
        self.assertEqual(self.run_cli("R.md").returncode, 0)
        self.assertEqual(self.run_cli("R.md", "--self").returncode, 1)

    def test_kb_flag_changes_a_borderline_into_a_breach(self):
        self.write("R.md", "A.md is at most 1 KB")
        self.write("A.md", "x" * 1010)
        self.assertEqual(self.run_cli("R.md").returncode, 0)
        self.assertEqual(self.run_cli("R.md", "--kb", "1000").returncode, 1)


class SelfCheck(unittest.TestCase):
    """The tool's own documentation is subject to the tool."""

    def test_own_readme_has_no_breach(self):
        got = subprocess.run(
            [sys.executable, str(HERE / "stated_limits.py"), str(HERE),
             "--root", str(HERE)],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertIn(got.returncode, (0, 1))
        self.assertNotIn("Traceback", got.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
