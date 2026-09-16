# -*- coding: utf-8 -*-
"""Tests for prose_expiry.py. Standard library only.

    python -m unittest discover -s prose-expiry -p "test_*.py" -v

Each test here exists because the tool can be wrong in that exact way, and
mutation_check.py breaks the tool in those ways to confirm the tests notice.
"""
import io
import contextlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

import prose_expiry as pe

TODAY = date(2026, 9, 16)

# Built from pieces on purpose: this repository's own commit guard refuses a literal that
# is shaped like a GitHub token, including a fake one in a test file. It was right to.
FAKE_TOKEN = "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"


def scan(line, **kw):
    rows, weak = pe.scan_text(line, "f.md", TODAY, **kw)
    return rows


def run(args):
    """main() with stdout captured. Returns (exit code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = pe.main(args)
    return code, buf.getvalue()


class Dates(unittest.TestCase):
    def test_iso(self):
        self.assertEqual([d for _, _, d in pe.dates_in("x 2026-09-30 y")], [date(2026, 9, 30)])

    def test_iso_single_digit_parts(self):
        self.assertEqual([d for _, _, d in pe.dates_in("2026-9-3")], [date(2026, 9, 3)])

    def test_separator_must_repeat(self):
        # 2026-09/30 is a version string or a range, not a date.
        self.assertEqual(pe.dates_in("2026-09/30"), [])

    def test_impossible_calendar_date_is_not_a_date(self):
        self.assertEqual(pe.dates_in("2026-02-30"), [])
        self.assertEqual(pe.dates_in("2026-13-01"), [])

    def test_leap_day_is_a_date(self):
        self.assertEqual([d for _, _, d in pe.dates_in("2028-02-29")], [date(2028, 2, 29)])

    def test_year_range(self):
        self.assertEqual(pe.dates_in("1969-01-01"), [])
        self.assertEqual(pe.dates_in("2101-01-01"), [])
        self.assertEqual(len(pe.dates_in("1970-01-01")), 1)

    def test_japanese(self):
        self.assertEqual([d for _, _, d in pe.dates_in("2026年9月30日")], [date(2026, 9, 30)])

    def test_month_name_both_orders(self):
        self.assertEqual([d for _, _, d in pe.dates_in("September 30, 2026")], [date(2026, 9, 30)])
        self.assertEqual([d for _, _, d in pe.dates_in("30 Sep 2026")], [date(2026, 9, 30)])
        self.assertEqual([d for _, _, d in pe.dates_in("Sep 1st 2026")], [date(2026, 9, 1)])

    def test_not_a_month_name(self):
        # "May" + "be": the first draft read this as the thirtieth of May.
        self.assertEqual(pe.dates_in("Maybe 30 2026"), [])
        self.assertEqual(pe.dates_in("Junk 30 2026"), [])
        self.assertEqual([d for _, _, d in pe.dates_in("Sept 30 2026")], [date(2026, 9, 30)])

    def test_longer_run_of_digits_is_not_a_date(self):
        self.assertEqual(pe.dates_in("12026-09-30"), [])
        self.assertEqual(pe.dates_in("2026-09-300"), [])

    def test_two_dates_on_one_line_both_found(self):
        self.assertEqual(len(pe.dates_in("from 2026-01-01 to 2026-12-31")), 2)

    def test_same_date_two_patterns_counted_once_per_column(self):
        self.assertEqual(len(pe.dates_in("2026-09-30")), 1)


class Cues(unittest.TestCase):
    def test_strong_cue_beside_the_date(self):
        rows = scan("support ends: EOL 2026-09-30")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cue"], "eol")

    def test_no_cue_means_no_row(self):
        self.assertEqual(scan("released 2026-09-30"), [])

    def test_cue_too_far_away_does_not_count(self):
        far = "expires " + ("x" * 60) + " 2026-09-30"
        self.assertEqual(scan(far), [])
        self.assertEqual(len(scan(far, near=200)), 1)

    def test_weak_cue_is_excluded_by_default_and_counted(self):
        rows, weak = pe.scan_text("renew on 2026-09-30", "f.md", TODAY)
        self.assertEqual(rows, [])
        self.assertEqual(weak, 1)

    def test_weak_cue_included_on_request(self):
        rows = scan("renew on 2026-09-30", include_weak=True)
        self.assertEqual([r["cue"] for r in rows], ["renew"])

    def test_strong_cue_wins_over_a_nearer_weak_one(self):
        # "due" is two characters from the date and "expires" is twenty-odd, and the
        # strong cue still has to win: the tiers are an ordering, not a tie-break.
        rows = scan("expires at some point - due 2026-09-30", include_weak=True)
        self.assertEqual(rows[0]["cue"], "expires")

    def test_japanese_cues(self):
        self.assertEqual(scan("有効期限 2026-09-30")[0]["cue"], "期限")
        self.assertEqual(scan("ライセンスが失効 2026-09-30")[0]["cue"], "失効")
        self.assertEqual(scan("提供終了 2026年9月30日")[0]["cue"], "提供終了")

    def test_heading_reaches_a_few_lines(self):
        text = "## End of support\n\n2026-09-30\n"
        rows = scan(text)
        self.assertEqual(len(rows), 1)
        self.assertIn("(heading)", rows[0]["cue"])

    def test_heading_does_not_reach_the_whole_section(self):
        text = "## 期限\n" + ("filler\n" * 10) + "2026-09-30\n"
        self.assertEqual(scan(text), [])

    def test_a_later_heading_replaces_the_earlier_one(self):
        text = "## 期限\n## Release notes\n2026-09-30\n"
        self.assertEqual(scan(text), [])


class Rows(unittest.TestCase):
    def test_days_are_signed_from_today(self):
        self.assertEqual(scan("expires 2026-09-30")[0]["days"], 14)
        self.assertEqual(scan("expired 2026-09-01")[0]["days"], -15)
        self.assertEqual(scan("expires 2026-09-16")[0]["days"], 0)

    def test_line_number_is_reported(self):
        rows = scan("a\nb\nEOL 2026-09-30\n")
        self.assertTrue(rows[0]["where"].endswith(":3"))

    def test_what_is_trimmed_of_markdown_furniture(self):
        self.assertEqual(scan("| - EOL 2026-09-30 |")[0]["what"], "EOL 2026-09-30 |")

    def test_what_is_truncated(self):
        rows = scan("EOL 2026-09-30 " + "x" * 400)
        self.assertLessEqual(len(rows[0]["what"]), 100)


class Redaction(unittest.TestCase):
    def test_token_is_redacted(self):
        self.assertIn("[redacted]", pe.redact(FAKE_TOKEN))

    def test_hex_digest_is_redacted(self):
        self.assertIn("[redacted]", pe.redact("a" * 8 + "0123456789abcdef0123456789abcdef"))

    def test_mixed_case_with_digits_is_redacted(self):
        self.assertIn("[redacted]", pe.redact("Zm9vYmFyMTIzNDU2Nzg5MDEyMzQ1Njc4OQ"))

    def test_a_path_is_not_redacted(self):
        self.assertEqual(pe.redact("key-expiry/trust_store_demo"), "key-expiry/trust_store_demo")

    def test_a_long_plain_word_is_not_redacted(self):
        self.assertEqual(pe.redact("internationalisation_of_everything"),
                         "internationalisation_of_everything")

    def test_redaction_reaches_the_report(self):
        rows = scan("EOL 2026-09-30 token=" + FAKE_TOKEN)
        self.assertIn("[redacted]", rows[0]["what"])
        self.assertNotIn(FAKE_TOKEN[:12], rows[0]["what"])


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_binary_and_credential_files_are_never_opened(self):
        self.write("a.md", "EOL 2026-09-30")
        self.write("b.png", "EOL 2026-09-30")
        self.write("server.pem", "EOL 2026-09-30")
        self.write(".env", "EOL 2026-09-30")
        got = [p.name for p in pe.walk(self.root)]
        self.assertEqual(got, ["a.md"])

    def test_skip_dirs(self):
        self.write("node_modules/x.md", "EOL 2026-09-30")
        self.write("keep.md", "EOL 2026-09-30")
        self.assertEqual([p.name for p in pe.walk(self.root)], ["keep.md"])

    def test_exclude_glob(self):
        self.write("test_x.md", "EOL 2026-09-30")
        self.write("keep.md", "EOL 2026-09-30")
        self.assertEqual([p.name for p in pe.walk(self.root, ["test_*"])], ["keep.md"])

    def test_oversized_file_is_skipped_not_half_read(self):
        self.write("big.md", "x" * (pe.MAX_BYTES + 10) + "\nEOL 2026-09-30\n")
        code, out = run([str(self.root), "--today", "2026-09-16"])
        self.assertEqual(code, 2)                       # read nothing -> no green check
        self.assertNotIn("2026-09-30", out)

    def test_exit_1_when_something_is_inside_the_window(self):
        self.write("a.md", "EOL 2026-09-30")
        code, out = run([str(self.root), "--today", "2026-09-16"])
        self.assertEqual(code, 1)
        self.assertIn("2026-09-30", out)

    def test_exit_0_when_everything_is_far_away(self):
        self.write("a.md", "EOL 2027-12-31")
        code, out = run([str(self.root), "--today", "2026-09-16"])
        self.assertEqual(code, 0)
        self.assertIn("later", out)

    def test_exit_1_when_something_already_passed_even_outside_the_window(self):
        self.write("a.md", "EOL 2020-01-01")
        code, _ = run([str(self.root), "--today", "2026-09-16", "--within", "1"])
        self.assertEqual(code, 1)

    def test_exit_2_on_a_missing_target(self):
        code, _ = run([str(self.root / "nope"), "--today", "2026-09-16"])
        self.assertEqual(code, 2)

    def test_exit_2_when_no_file_matched(self):
        self.write("a.png", "EOL 2026-09-30")
        code, _ = run([str(self.root), "--today", "2026-09-16"])
        self.assertEqual(code, 2)

    def test_exit_2_with_no_target_at_all(self):
        self.assertEqual(run([])[0], 2)

    def test_paste_format_carries_no_path_or_line_text(self):
        self.write("secretproject.md", "EOL 2026-09-30 internal codename")
        code, out = run([str(self.root), "--today", "2026-09-16", "--format", "paste"])
        self.assertEqual(code, 1)
        self.assertNotIn("secretproject", out)
        self.assertNotIn("codename", out)
        self.assertNotIn(str(self.root), out)
        self.assertIn("already passed", out)

    def test_github_format_names_file_and_line(self):
        self.write("a.md", "EOL 2026-09-30")
        _, out = run([str(self.root), "--today", "2026-09-16", "--format", "github"])
        self.assertIn("::warning file=", out)
        self.assertIn(",line=1::", out)

    def test_rows_are_sorted_most_overdue_first(self):
        self.write("a.md", "EOL 2026-09-30\nEOL 2020-01-01\nEOL 2026-09-20\n")
        _, out = run([str(self.root), "--today", "2026-09-16"])
        body = [l for l in out.splitlines() if l and l[0] in "-0123456789"]
        self.assertEqual([l.split("\t")[1] for l in body[:3]],
                         ["2020-01-01", "2026-09-20", "2026-09-30"])

    def test_distinct_dates_are_counted_separately_from_rows(self):
        self.write("a.md", "EOL 2026-09-30\nEOL 2026-09-30\n")
        _, out = run([str(self.root), "--today", "2026-09-16"])
        self.assertIn("2 written expiry dates over 1 distinct dates", out)


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def ledger(self, text):
        p = self.root / "EXPIRY.tsv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_header_and_comments_are_not_rows(self):
        p = self.ledger("# a note\nkind\tdate\twhat_stops\n"
                        "domain\t2026-10-31\tthe site\tinvoice\t0\n")
        rows = pe.read_ledger(p, TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-10-31")
        self.assertEqual(rows[0]["what"], "the site")

    def test_row_without_a_date_is_skipped(self):
        p = self.ledger("domain\tsoon\tthe site\n")
        self.assertEqual(pe.read_ledger(p, TODAY), [])

    def test_empty_ledger_alone_reads_nothing(self):
        p = self.ledger("kind\tdate\twhat_stops\thow_you_found_out\tdays_late\n")
        code, _ = run(["--ledger", str(p), "--today", "2026-09-16"])
        self.assertEqual(code, 2)

    def test_ledger_rows_join_the_report(self):
        p = self.ledger("kind\tdate\twhat_stops\ndomain\t2026-09-20\tthe site\n")
        (self.root / "a.md").write_text("EOL 2027-12-31", encoding="utf-8")
        code, out = run([str(self.root), "--ledger", str(p), "--today", "2026-09-16"])
        self.assertEqual(code, 1)
        self.assertIn("of which from the ledger: 1", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
