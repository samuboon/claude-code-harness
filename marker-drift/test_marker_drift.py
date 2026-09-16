# -*- coding: utf-8 -*-
"""Tests for marker_drift.py.  python -m unittest discover -s marker-drift -p "test_*.py" """
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marker_drift as md  # noqa: E402

UNIT = "(unit {n})"


def kind(line, marker=UNIT, at="anywhere"):
    return md.analyse(line, marker, at)["kind"]


def axes(line, marker=UNIT, at="anywhere"):
    return md.analyse(line, marker, at)["axes"]


def found(line, marker=UNIT, at="anywhere"):
    return md.analyse(line, marker, at)["found"]


def run(argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    real = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
        sys.stdin.isatty = lambda: False  # type: ignore[method-assign]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = md.main(argv)
    finally:
        sys.stdin = real
    return code, out.getvalue(), err.getvalue()


class ExactMatches(unittest.TestCase):
    def test_plain_hit_is_not_drift(self):
        self.assertEqual(kind("chore: something (unit 42)"), "exact")

    def test_marker_at_end_of_line(self):
        self.assertEqual(kind("done (unit 7)"), "exact")

    def test_marker_at_start_of_line(self):
        self.assertEqual(kind("(unit 7) done"), "exact")

    def test_many_digits(self):
        self.assertEqual(kind("(unit 1234567)"), "exact")

    def test_line_without_the_marker_is_none(self):
        self.assertEqual(kind("chore: no marker here"), "none")

    def test_empty_line_is_none(self):
        self.assertEqual(kind(""), "none")

    def test_template_brackets_are_escaped_not_regex(self):
        # "(unit {n})" must not compile as a capture group: "unit 3" alone is not a hit.
        self.assertEqual(kind("chore: unit 3"), "none")

    def test_placeholder_n_rejects_letters(self):
        self.assertEqual(kind("(unit four)"), "none")

    def test_placeholder_n_needs_at_least_one_digit(self):
        self.assertEqual(kind("(unit )"), "none")

    def test_a_longer_word_is_not_the_marker(self):
        # "units" is not "unit": no axis turns one into the other.
        self.assertEqual(kind("chore: x (units 12)"), "none")

    def test_prefix_word_is_not_the_marker(self):
        self.assertEqual(kind("chore: x (subunit 12)"), "none")

    def test_ascii_digits_only_so_full_width_shows_up_as_drift(self):
        # \d would swallow "３４" and report an exact match, which is the opposite of
        # what this tool is for.
        self.assertEqual(kind("(unit ３４)"), "drift")

    def test_ascii_word_only(self):
        self.assertEqual(kind("単位-12", "{w}-{n}"), "none")

    def test_a_space_where_the_marker_has_none_is_not_caught(self):
        # A limit, written down as a test: the space axis relaxes the runs of whitespace
        # the marker already has, and the boundaries of placeholders. Not every gap.
        self.assertEqual(kind("chore: x ( unit 34)"), "none")


class OneAxisAtATime(unittest.TestCase):
    def test_space_removed(self):
        r = md.analyse("chore: x (unit34)", UNIT)
        self.assertEqual(r["kind"], "drift")
        self.assertEqual(r["axes"], ("space",))
        self.assertEqual(r["found"], "(unit34)")

    def test_space_doubled(self):
        self.assertEqual(axes("chore: x (unit  34)"), ("space",))

    def test_ideographic_space(self):
        self.assertEqual(axes("chore: x (unit　34)"), ("space",))

    def test_non_breaking_space(self):
        self.assertEqual(axes("chore: x (unit 34)"), ("space",))

    def test_tab_instead_of_space(self):
        self.assertEqual(axes("chore: x (unit\t34)"), ("space",))

    def test_case(self):
        self.assertEqual(axes("chore: x (UNIT 34)"), ("case",))

    def test_mixed_case(self):
        self.assertEqual(axes("chore: x (Unit 34)"), ("case",))

    def test_full_width_digits(self):
        self.assertEqual(axes("chore: x (unit ３４)"), ("width",))

    def test_full_width_letters(self):
        self.assertEqual(axes("chore: x (ｕｎｉｔ 34)"), ("width",))

    def test_full_width_brackets(self):
        self.assertEqual(axes("chore: x （unit 34）"), ("bracket",))

    def test_japanese_lenticular_brackets(self):
        self.assertEqual(axes("chore: x 【unit 34】", "[unit {n}]"), ("bracket",))

    def test_dash_en(self):
        self.assertEqual(axes("chore: x ABC–123", "{w}-{n}"), ("dash",))

    def test_dash_long_vowel_mark(self):
        self.assertEqual(axes("chore: x ABCー123", "{w}-{n}"), ("dash",))

    def test_full_width_colon(self):
        self.assertEqual(axes("fix：thing", "fix:"), ("width",))

    def test_two_axes_when_two_things_moved(self):
        self.assertEqual(set(axes("chore: x (UNIT34)")), {"case", "space"})

    def test_space_after_the_placeholder(self):
        # The marker has no space there, so this only works because a placeholder is
        # allowed whitespace on either side of it.
        self.assertEqual(axes("chore: x (unit 34 )"), ("space",))

    def test_space_before_the_placeholder_beyond_the_one_in_the_marker(self):
        self.assertEqual(axes("chore: x (unit　 34)"), ("space",))


class MinimalAxisSet(unittest.TestCase):
    def test_only_the_axis_that_mattered_is_named(self):
        # Nothing here is full width, so "width" must not appear in the answer.
        self.assertEqual(axes("chore: x (unit34)"), ("space",))

    def test_full_width_answer_does_not_drag_in_case(self):
        self.assertNotIn("case", axes("chore: x (unit ３４)"))

    def test_axes_are_reported_in_a_fixed_order(self):
        got = axes("chore: x （ＵＮＩＴ３４）")
        self.assertEqual(got, tuple(a for a in md.AXES if a in got))

    def test_exact_line_reports_no_axes(self):
        self.assertEqual(axes("(unit 1)"), ())


class SpansPointAtTheOriginal(unittest.TestCase):
    def test_span_after_removed_space(self):
        line = "chore: x (unit34) tail"
        r = md.analyse(line, UNIT)
        self.assertEqual(line[r["span"][0]:r["span"][1]], "(unit34)")

    def test_span_with_wide_characters_before_it(self):
        line = "テクスチャの継ぎ目を直した(unit34)"
        r = md.analyse(line, UNIT)
        self.assertEqual(line[r["span"][0]:r["span"][1]], "(unit34)")

    def test_span_with_several_spaces_before_it(self):
        line = "a   b   c (unit  9)"
        r = md.analyse(line, UNIT)
        self.assertEqual(line[r["span"][0]:r["span"][1]], "(unit  9)")

    def test_span_of_an_exact_hit(self):
        line = "zzz (unit 5) zzz"
        r = md.analyse(line, UNIT)
        self.assertEqual(line[r["span"][0]:r["span"][1]], "(unit 5)")

    def test_caret_line_is_not_longer_than_the_widest_reasonable_line(self):
        line = "日本語 (unit34)"
        r = md.analyse(line, UNIT)
        caret = md.caret_line(line, r["span"])
        self.assertTrue(set(caret.strip()) == {"^"})

    def test_first_marker_on_the_line_wins(self):
        line = "(unit34) and (unit35)"
        r = md.analyse(line, UNIT)
        self.assertEqual(r["found"], "(unit34)")


class Normalisation(unittest.TestCase):
    def test_the_space_axis_never_edits_the_line(self):
        # It relaxes the marker instead. If this ever starts deleting, "--at start"
        # silently changes meaning and "xx feat:" matches a gate anchored at the head.
        src = "a b　c"
        norm, idx = md.normalize(src, ("space",))
        self.assertEqual(norm, src)
        self.assertEqual(idx, list(range(len(src))))

    def test_index_map_length_matches_output(self):
        norm, idx = md.normalize("（Ａ）", ("width", "bracket"))
        self.assertEqual(len(norm), len(idx))
        self.assertEqual(norm, "(A)")

    def test_one_for_one_axes_keep_offsets(self):
        src = "（ＡＢ）"
        norm, idx = md.normalize(src, ("width", "bracket"))
        self.assertEqual(norm, "(AB)")
        self.assertEqual(idx, [0, 1, 2, 3])

    def test_unknown_axis_name_changes_nothing(self):
        self.assertEqual(md.normalize("（A）", ("nonsense",))[0], "（A）")

    def test_case_axis_leaves_non_ascii_alone(self):
        self.assertEqual(md.normalize("ΣA", ("case",))[0], "Σa")

    def test_width_then_case_chain(self):
        self.assertEqual(md.normalize("Ａ", ("width", "case"))[0], "a")


class Templates(unittest.TestCase):
    def test_split_keeps_literals_and_placeholders(self):
        self.assertEqual(md.split_template("(unit {n})"),
                         ["(unit ", ("{n}",), ")"])

    def test_unknown_placeholder_stays_literal(self):
        self.assertEqual(md.split_template("{zz}"), ["{zz}"])
        self.assertEqual(kind("a {zz} b", "{zz}"), "exact")

    def test_word_placeholder(self):
        self.assertEqual(kind("see ABC-12", "{w}-{n}"), "exact")

    def test_any_placeholder(self):
        self.assertEqual(kind("feat(scope): x", "{w}({any}): "), "exact")

    def test_empty_marker_is_refused(self):
        with self.assertRaises(ValueError):
            md.compile_template("", ())

    def test_marker_of_only_spaces_never_matches_under_the_space_axis(self):
        rx = md.compile_template("  ", ("space",))
        self.assertIsNone(rx.search("anything at all"))

    def test_marker_of_only_spaces_still_matches_exactly(self):
        self.assertEqual(kind("a  b", "  "), "exact")

    def test_regex_metacharacters_in_the_marker_are_literal(self):
        self.assertEqual(kind("a.b", "a.b"), "exact")
        self.assertEqual(kind("axb", "a.b"), "none")


class Anchoring(unittest.TestCase):
    def test_start_anchor_rejects_a_marker_in_the_middle(self):
        self.assertEqual(kind("xx feat: y", "{w}: ", at="start"), "none")

    def test_start_anchor_accepts_a_marker_at_the_head(self):
        self.assertEqual(kind("feat: y", "{w}: ", at="start"), "exact")

    def test_start_anchor_with_leading_space_is_a_space_drift(self):
        self.assertEqual(axes(" feat: y", "{w}: ", at="start"), ("space",))

    def test_start_anchor_allows_an_indent_before_a_literal_marker(self):
        # No placeholder at the head of this marker, so the anchor itself has to give.
        self.assertEqual(axes("  (unit 3) x", UNIT, at="start"), ("space",))

    def test_end_anchor_accepts_a_marker_at_the_tail(self):
        self.assertEqual(kind("did a thing (unit 3)", at="end"), "exact")

    def test_end_anchor_rejects_a_marker_quoted_mid_sentence(self):
        # The real false positive this option exists for: a commit that *talks about*
        # the marker instead of carrying it.
        self.assertEqual(kind("fix: counted (unit34) as missing (BUG-59)", at="end"),
                         "none")
        self.assertEqual(kind("fix: counted (unit34) as missing (BUG-59)"), "drift")

    def test_end_anchor_still_sees_the_drift_at_the_tail(self):
        self.assertEqual(axes("did a thing (unit3)", at="end"), ("space",))

    def test_end_anchor_tolerates_trailing_space_only_under_the_space_axis(self):
        self.assertEqual(kind("did a thing (unit 3) ", at="end"), "drift")


class ScanAndCounts(unittest.TestCase):
    def setUp(self):
        self.lines = [
            "chore: a (unit 1)",
            "chore: b (unit2)",
            "",
            "   ",
            "chore: c nothing",
        ]
        self.res = md.scan_lines(self.lines, UNIT)

    def test_blank_lines_are_not_read(self):
        self.assertEqual(self.res["read"], 3)

    def test_exact_count(self):
        self.assertEqual(self.res["exact"], 1)

    def test_drift_count(self):
        self.assertEqual(len(self.res["drift"]), 1)

    def test_missing_count(self):
        self.assertEqual(len(self.res["missing"]), 1)

    def test_line_numbers_count_blank_lines(self):
        self.assertEqual(self.res["drift"][0]["line_no"], 2)

    def test_long_lines_are_truncated_not_dropped(self):
        res = md.scan_lines(["x" * (md.MAX_LINE + 50) + " (unit 1)"], UNIT)
        self.assertEqual(res["read"], 1)
        self.assertEqual(res["exact"], 0)


class ExitCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, name="lines.txt"):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_no_drift_is_zero(self):
        code, out, _ = run(["--marker", UNIT, "--file", self.write("a (unit 1)\n")])
        self.assertEqual(code, 0)
        self.assertIn("the gate lost nothing", out)

    def test_drift_is_one(self):
        code, _, _ = run(["--marker", UNIT, "--file", self.write("a (unit1)\n")])
        self.assertEqual(code, 1)

    def test_a_scan_that_read_nothing_is_not_a_pass(self):
        code, _, err = run(["--marker", UNIT, "--file", self.write("\n\n  \n")])
        self.assertEqual(code, 2)
        self.assertIn("read 0 lines", err)

    def test_missing_file_is_two(self):
        code, _, err = run(["--marker", UNIT, "--file", str(self.tmp / "nope.txt")])
        self.assertEqual(code, 2)
        self.assertIn("not a file", err)

    def test_empty_marker_is_two(self):
        code, _, err = run(["--marker", "", "--file", self.write("a\n")])
        self.assertEqual(code, 2)
        self.assertIn("bad marker", err)

    def test_stdin_is_read_when_no_source_is_given(self):
        code, out, _ = run(["--marker", UNIT], stdin="a (unit1)\n")
        self.assertEqual(code, 1)
        self.assertIn("drift       1", out)

    def test_two_files_are_read_in_order(self):
        a = self.write("a (unit 1)\n", "a.txt")
        b = self.write("b (unit2)\n", "b.txt")
        code, out, _ = run(["--marker", UNIT, "--file", a, b])
        self.assertEqual(code, 1)
        self.assertIn("lines read  2", out)


class Output(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "l.txt"
        self.p.write_text("a (unit1)\nb nothing\nc (unit 2)\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_text_report_names_the_axis(self):
        _, out, _ = run(["--marker", UNIT, "--file", str(self.p)])
        self.assertIn("space", out)
        self.assertIn(md.AXIS_HELP["space"], out)

    def test_text_report_shows_the_line(self):
        _, out, _ = run(["--marker", UNIT, "--file", str(self.p)])
        self.assertIn("a (unit1)", out)

    def test_tsv_has_a_header_and_one_row_per_drift(self):
        _, out, _ = run(["--marker", UNIT, "--file", str(self.p), "--format", "tsv"])
        rows = [r for r in out.splitlines() if r.strip()]
        self.assertEqual(rows[0].split("\t"), ["line_no", "axes", "found", "line"])
        self.assertEqual(len(rows), 2)

    def test_missing_lines_are_hidden_by_default(self):
        _, out, _ = run(["--marker", UNIT, "--file", str(self.p)])
        self.assertNotIn("b nothing", out)
        self.assertNotIn("no marker at all", out)

    def test_list_missing_prints_them_with_a_warning(self):
        _, out, _ = run(["--marker", UNIT, "--file", str(self.p), "--list-missing", "5"])
        self.assertIn("b nothing", out)
        self.assertIn("cannot tell you whether", out)

    def test_counts_line_up_with_the_file(self):
        _, out, _ = run(["--marker", UNIT, "--file", str(self.p)])
        self.assertIn("lines read  3", out)
        self.assertIn("exact       1", out)
        self.assertIn("no marker   1", out)


class GitInput(unittest.TestCase):
    """Real repository, real commits. Skipped where git is not installed."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is not installed")
        cls.tmp = Path(tempfile.mkdtemp())
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        import os
        env = {**os.environ, **env}
        def g(*a):
            subprocess.run(["git", "-C", str(cls.tmp), *a], check=True,
                           capture_output=True, env=env)
        g("init", "-q")
        (cls.tmp / "f").write_text("1", encoding="utf-8")
        g("add", "f")
        g("commit", "-q", "-m", "chore: first (unit 1)")
        (cls.tmp / "f").write_text("2", encoding="utf-8")
        g("commit", "-q", "-a", "-m", "chore: second (unit2)")
        (cls.tmp / "f").write_text("3", encoding="utf-8")
        g("commit", "-q", "-a", "-m", "chore: third, no marker")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_reads_subjects_from_a_repository(self):
        code, out, _ = run(["--marker", UNIT, "--git", str(self.tmp)])
        self.assertEqual(code, 1)
        self.assertIn("lines read  3", out)
        self.assertIn("exact       1", out)
        self.assertIn("drift       1", out)

    def test_max_limits_how_far_back_it_reads(self):
        _, out, _ = run(["--marker", UNIT, "--git", str(self.tmp), "--max", "1"])
        self.assertIn("lines read  1", out)

    def test_a_directory_that_is_not_a_repository_is_two(self):
        other = Path(tempfile.mkdtemp())
        try:
            code, _, err = run(["--marker", UNIT, "--git", str(other)])
            self.assertEqual(code, 2)
            self.assertIn("git log failed", err)
        finally:
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
