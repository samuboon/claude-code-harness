# -*- coding: utf-8 -*-
"""Tests for unbacked_numbers.py.  python -m unittest discover -s unbacked-numbers -p "test_*.py" """
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unbacked_numbers as ubn  # noqa: E402


def scan(text, min_value=10.0, drift=0.05, strict=False, include_years=False):
    return ubn.scan_text(text, "x.md", min_value, drift, strict, include_years)


def raws(rows):
    return [r["raw"] for r in rows]


def kinds(rows):
    return {r["raw"]: r["kind"] for r in rows}


QUOTE = "> the page said 500 downloads\n\n"      # gives every fixture some evidence


class Splitting(unittest.TestCase):
    def test_fenced_block_is_evidence(self):
        rows, _ = scan("We saw 44 files.\n\n```\nfiles: 44\n```\n")
        self.assertEqual(raws(rows), [])

    def test_prose_outside_the_fence_is_still_prose(self):
        rows, _ = scan("We saw 44 files and 90 rows.\n\n```\nfiles: 44\n```\n")
        self.assertEqual(raws(rows), ["90"])

    def test_unclosed_fence_swallows_the_rest_of_the_file(self):
        rows, _ = scan("```\nfiles: 44\nlater we claim 90 rows\n")
        self.assertEqual(raws(rows), [])

    def test_blockquote_line_is_evidence(self):
        rows, _ = scan("It was 44.\n\n> total: 44\n")
        self.assertEqual(raws(rows), [])

    def test_inline_code_is_evidence(self):
        # the block quote is here so the file still has evidence if inline code stops
        # counting - otherwise the "quotes nothing at all" skip hides the regression
        rows, _ = scan(QUOTE + "It was 44.\n\nthe log line `files=44` says so\n")
        self.assertEqual(raws(rows), [])

    def test_a_number_alone_in_backticks_does_not_back_itself(self):
        rows, _ = scan(QUOTE + "the table says `184` firings\n")
        self.assertEqual(raws(rows), ["184"])

    def test_backticks_with_a_word_in_them_are_evidence(self):
        rows, _ = scan(QUOTE + "the log line `firings=184` says so, and 184 is the count\n")
        self.assertEqual(raws(rows), [])

    def test_japanese_quote_marks_are_evidence(self):
        rows, _ = scan("実測は 44 件。\n\n「44 件を検出」\n")
        self.assertEqual(raws(rows), [])

    def test_straight_double_quotes_are_evidence(self):
        rows, _ = scan('It was 44.\n\nthe report says "we scanned 44 files"\n')
        self.assertEqual(raws(rows), [])

    def test_a_quote_mark_that_never_closes_is_not_evidence(self):
        rows, _ = scan(QUOTE + 'we claim "44 files\n')
        self.assertEqual(raws(rows), ["44"])

    def test_fence_marker_line_itself_is_not_prose(self):
        rows, _ = scan("```text 44\nfiles: 90\n```\n")
        self.assertEqual(raws(rows), [])


class Backing(unittest.TestCase):
    def test_comma_spelling_matches_a_plain_quote(self):
        rows, _ = scan("We processed 1,200 rows.\n\n```\nrows=1200\n```\n")
        self.assertEqual(raws(rows), [])

    def test_plain_spelling_matches_a_comma_quote(self):
        rows, _ = scan("We processed 1200 rows.\n\n```\nrows: 1,200\n```\n")
        self.assertEqual(raws(rows), [])

    def test_fullwidth_digits_in_prose_match_an_ascii_quote(self):
        rows, _ = scan("実測４４ 件。\n\n```\n44\n```\n")
        self.assertEqual(raws(rows), [])

    def test_man_in_the_quote_backs_the_expanded_prose(self):
        rows, _ = scan("The goal is 30000 yen.\n\n```\n目標 3万\n```\n")
        self.assertEqual(raws(rows), [])

    def test_man_in_the_prose_is_checked_expanded(self):
        rows, _ = scan("The goal is 3万 yen.\n\n```\n30000\n```\n")
        self.assertEqual(raws(rows), [])

    def test_the_bare_digit_of_a_man_number_is_not_a_finding_of_its_own(self):
        rows, _ = scan("目標は 3万 円。\n\n```\n30000\n```\n")
        self.assertEqual(raws(rows), [])

    def test_fullwidth_comma_in_prose_matches_an_ascii_quote(self):
        rows, _ = scan("実測１，２００ 行。\n\n```\n1200\n```\n")
        self.assertEqual(raws(rows), [])

    def test_a_quoted_man_number_also_backs_the_bare_digit(self):
        # deliberately lenient: on the quoted side 3万 is recorded as both 3 and 30000,
        # so a checker that cannot be sure does not invent a finding
        rows, _ = scan("there were 3 of them\n\n```\n3万\n```\n", min_value=1.0)
        self.assertEqual(raws(rows), [])

    def test_prose_and_evidence_are_different_halves_of_the_file(self):
        rows, _ = scan(QUOTE + "we claim 900 rows\n", strict=True)
        self.assertEqual(raws(rows), ["900"])

    def test_decimals_match_exactly(self):
        rows, _ = scan("It was 8.6%.\n\n```\nrate 8.6\n```\n")
        self.assertEqual(raws(rows), [])

    def test_a_different_decimal_is_not_backed(self):
        rows, _ = scan("It was 8.6%.\n\n```\nrate 9.9\n```\n", drift=0.0)
        self.assertEqual(raws(rows), ["8.6"])

    def test_a_number_quoted_anywhere_in_the_file_backs_it(self):
        rows, _ = scan("```\n44\n```\n\nlater on, 44 again, far from the quote\n")
        self.assertEqual(raws(rows), [])


class NearMiss(unittest.TestCase):
    def test_a_close_quoted_number_makes_it_a_near_miss(self):
        rows, _ = scan("The issue had 153 thumbs-up.\n\n```\n+1: 149\n```\n")
        self.assertEqual(kinds(rows), {"153": "near-miss"})
        self.assertEqual(rows[0]["note"], "149")

    def test_drift_zero_turns_the_near_miss_into_a_plain_finding(self):
        rows, _ = scan("The issue had 153 thumbs-up.\n\n```\n+1: 149\n```\n", drift=0.0)
        self.assertEqual(kinds(rows), {"153": "unbacked"})

    def test_a_far_quoted_number_is_not_a_near_miss(self):
        rows, _ = scan("We saw 900 rows.\n\n```\n44\n```\n")
        self.assertEqual(kinds(rows), {"900": "unbacked"})

    def test_an_exact_match_is_never_reported_as_a_near_miss(self):
        rows, _ = scan("We saw 44 rows.\n\n```\n44\n```\n")
        self.assertEqual(raws(rows), [])

    def test_a_small_number_is_never_called_a_near_miss(self):
        # 19 beside a quoted 20 is inside 5%, but below the floor that makes a ratio mean
        # anything - it is reported, just not as a mistyped number
        rows, _ = scan("we ran it 19 times.\n\n```\n20\n```\n", min_value=1.0)
        self.assertEqual(kinds(rows), {"19": "unbacked"})

    def test_just_above_the_floor_it_is_a_near_miss(self):
        rows, _ = scan("we ran it 190 times.\n\n```\n195\n```\n")
        self.assertEqual(kinds(rows), {"190": "near-miss"})

    def test_near_miss_wins_over_link_only(self):
        rows, _ = scan("153 per https://example.com/x\n\n```\n149\n```\n")
        self.assertEqual(kinds(rows), {"153": "near-miss"})


class LinkOnly(unittest.TestCase):
    def test_a_url_on_the_line_marks_it_link_only(self):
        rows, _ = scan(QUOTE + "traffic was 2660 per https://example.com/stats\n")
        self.assertEqual(kinds(rows), {"2660": "link-only"})

    def test_no_url_means_plain_unbacked(self):
        rows, _ = scan(QUOTE + "traffic was 2660\n")
        self.assertEqual(kinds(rows), {"2660": "unbacked"})

    def test_the_url_itself_contributes_no_numbers(self):
        rows, _ = scan(QUOTE + "see https://example.com/2660/report-90\n")
        self.assertEqual(raws(rows), [])


class Ignoring(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(raws(scan(QUOTE + "on 2026-09-16 we shipped\n")[0]), [])

    def test_japanese_date(self):
        self.assertEqual(raws(scan(QUOTE + "2026年9月16日 に出した\n")[0]), [])

    def test_us_date(self):
        self.assertEqual(raws(scan(QUOTE + "on 9/30/2026 it stops\n")[0]), [])

    def test_short_month_day(self):
        self.assertEqual(raws(scan(QUOTE + "on 09-16 we shipped\n")[0]), [])

    def test_clock_time(self):
        self.assertEqual(raws(scan(QUOTE + "at 10:58 it ran\n")[0]), [])

    def test_version_string(self):
        self.assertEqual(raws(scan(QUOTE + "harness v3.1 runs it\n")[0]), [])

    def test_semver(self):
        self.assertEqual(raws(scan(QUOTE + "python 3.13.1 ran it\n")[0]), [])

    def test_section_number(self):
        self.assertEqual(raws(scan(QUOTE + "see § 2 and 第 3 章\n")[0]), [])

    def test_issue_ref(self):
        self.assertEqual(raws(scan(QUOTE + "setuptools#3772 was the case\n")[0]), [])

    def test_footnote_ref(self):
        self.assertEqual(raws(scan(QUOTE + "as noted[^12] earlier\n")[0]), [])

    def test_path(self):
        self.assertEqual(raws(scan(QUOTE + "see docs/notes/900.md for it\n")[0]), [])

    def test_url_with_digits(self):
        self.assertEqual(raws(scan(QUOTE + "see https://example.com/900 for it\n")[0]), [])

    def test_identifier(self):
        self.assertEqual(raws(scan(QUOTE + "IMP-45 and plan x20 cover it\n")[0]), [])

    def test_commit_hash(self):
        self.assertEqual(raws(scan(QUOTE + "commit bb8c301 did it\n")[0]), [])

    def test_ordered_list_marker(self):
        self.assertEqual(raws(scan(QUOTE + "12. the twelfth point\n")[0]), [])

    def test_bare_year(self):
        self.assertEqual(raws(scan(QUOTE + "back in 2019 nobody cared\n")[0]), [])

    def test_include_years_promotes_it(self):
        rows, _ = scan(QUOTE + "back in 2019 nobody cared\n", include_years=True)
        self.assertEqual(raws(rows), ["2019"])

    def test_a_year_shaped_number_with_a_unit_is_kept(self):
        rows, _ = scan(QUOTE + "the price was 1980 円\n")
        self.assertEqual(raws(rows), ["1980"])


class Threshold(unittest.TestCase):
    def test_small_bare_integer_is_below_the_floor(self):
        rows, stats = scan(QUOTE + "there were 7 of them\n")
        self.assertEqual(raws(rows), [])
        self.assertEqual(stats["below_min"], 1)

    def test_lowering_min_promotes_it(self):
        rows, _ = scan(QUOTE + "there were 7 of them\n", min_value=1.0)
        self.assertEqual(raws(rows), ["7"])

    def test_percent_survives_the_floor(self):
        self.assertEqual(raws(scan(QUOTE + "it was 7% of the total\n")[0]), ["7"])

    def test_currency_survives_the_floor(self):
        self.assertEqual(raws(scan(QUOTE + "it cost ¥7 in the end\n")[0]), ["7"])

    def test_japanese_counter_survives_the_floor(self):
        self.assertEqual(raws(scan(QUOTE + "反応は 7 件だった\n")[0]), ["7"])

    def test_decimal_survives_the_floor(self):
        self.assertEqual(raws(scan(QUOTE + "it was 7.5 on average\n")[0]), ["7.5"])

    def test_english_unit_survives_the_floor(self):
        self.assertEqual(raws(scan(QUOTE + "it took 7 days to land\n")[0]), ["7"])


class NoEvidenceFile(unittest.TestCase):
    def test_a_file_that_quotes_nothing_is_skipped_by_default(self):
        rows, stats = scan("we measured 44 files and 900 rows\n")
        self.assertEqual(raws(rows), [])
        self.assertEqual(stats["no_evidence"], 1)

    def test_strict_scans_it(self):
        rows, stats = scan("we measured 44 files and 900 rows\n", strict=True)
        self.assertEqual(raws(rows), ["44", "900"])
        self.assertEqual(stats["no_evidence"], 0)


class Reporting(unittest.TestCase):
    def test_line_number_is_the_line_the_number_is_on(self):
        rows, _ = scan("```\n44\n```\n\nfiller\n\nwe also claim 900 rows\n")
        self.assertEqual(rows[0]["line"], 7)

    def test_row_carries_the_line_text(self):
        rows, _ = scan(QUOTE + "we also claim 900 rows\n")
        self.assertEqual(rows[0]["text"], "we also claim 900 rows")

    def test_redaction_hides_a_credential_shaped_token(self):
        line = "token ghpABCDEFGHijklmnop0123456789 was used"
        self.assertIn("[redacted]", ubn.redact(line))

    def test_redaction_leaves_a_long_path_alone(self):
        line = "see docs/a/very/long/path/to/some/File0123456789.md here"
        self.assertNotIn("[redacted]", ubn.redact(line))

    def test_redaction_leaves_long_prose_alone(self):
        line = "計測は RUNS.tsv、2026-09-10から09-13 の間"
        self.assertNotIn("[redacted]", ubn.redact(line))


class CLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ubn.run(list(argv))
        return code, out.getvalue() + err.getvalue()

    def test_clean_file_exits_zero(self):
        self.write("a.md", "it was 44.\n\n```\n44\n```\n")
        code, _ = self.run_cli(str(self.root))
        self.assertEqual(code, 0)

    def test_findings_exit_one(self):
        self.write("a.md", "it was 900.\n\n```\n44\n```\n")
        code, _ = self.run_cli(str(self.root))
        self.assertEqual(code, 1)

    def test_a_scan_that_read_nothing_exits_two(self):
        self.write("a.png", "not text")
        code, out = self.run_cli(str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("read 0 files", out)

    def test_a_missing_target_exits_two(self):
        code, _ = self.run_cli(str(self.root / "nope.md"))
        self.assertEqual(code, 2)

    def test_key_material_is_never_opened(self):
        self.write("secret.pem", "900 900 900\n")
        code, _ = self.run_cli(str(self.root))
        self.assertEqual(code, 2)

    def test_exclude_glob_skips_the_file(self):
        self.write("a.md", "it was 900.\n\n```\n44\n```\n")
        code, _ = self.run_cli(str(self.root), "--exclude", "a.md")
        self.assertEqual(code, 2)

    def test_paste_prints_no_path_and_no_line_text(self):
        self.write("secret-name.md", "the balance was 900 dollars.\n\n```\n44\n```\n")
        code, out = self.run_cli(str(self.root), "--format", "paste")
        self.assertEqual(code, 1)
        self.assertNotIn("secret-name", out)
        self.assertNotIn("balance", out)
        self.assertNotIn("900", out)

    def test_github_format_annotates_the_line(self):
        self.write("a.md", "it was 900.\n\n```\n44\n```\n")
        code, out = self.run_cli(str(self.root), "--format", "github")
        self.assertEqual(code, 1)
        self.assertIn("::warning file=", out)
        self.assertIn("line=1", out)

    def test_tsv_names_the_closest_quoted_number(self):
        self.write("a.md", "the issue had 153 thumbs-up.\n\n```\n149\n```\n")
        code, out = self.run_cli(str(self.root))
        self.assertEqual(code, 1)
        self.assertIn("near-miss", out)
        self.assertIn("149", out)

    def test_near_misses_are_printed_before_the_rest(self):
        self.write("a.md", "we saw 900 rows.\n\nand the issue had 153 thumbs-up.\n\n```\n149\n```\n")
        code, out = self.run_cli(str(self.root))
        self.assertEqual(code, 1)
        self.assertLess(out.index("near-miss\t"), out.index("unbacked\t"))

    def test_summary_counts_files_read(self):
        self.write("a.md", "it was 44.\n\n```\n44\n```\n")
        self.write("b.md", "it was 90.\n\n```\n90\n```\n")
        code, out = self.run_cli(str(self.root))
        self.assertIn("in 2 files", out)

    def test_git_directory_is_skipped(self):
        self.write(os.path.join(".git", "a.md"), "it was 900.\n\n```\n44\n```\n")
        code, _ = self.run_cli(str(self.root))
        self.assertEqual(code, 2)

    def test_a_single_file_target_works(self):
        p = self.write("a.md", "it was 900.\n\n```\n44\n```\n")
        code, out = self.run_cli(str(p))
        self.assertEqual(code, 1)
        self.assertIn("in 1 files", out)


if __name__ == "__main__":
    unittest.main()
