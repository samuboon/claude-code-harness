# -*- coding: utf-8 -*-
"""Tests for table_total_check.py.   python -m unittest test_table_total_check -v"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import table_total_check as t  # noqa: E402


def run(md):
    return t.check_text(md, "x.md")


def codes(md, level=None):
    return [f["code"] for f in run(md).findings if level is None or f["level"] == level]


def table(header, *rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out) + "\n"


class TotalRow(unittest.TestCase):
    def test_wrong_total_is_an_error(self):
        md = table(["Repo", "Stars"], ["a", "1,200"], ["b", "800"], ["**Total**", "**2,100**"])
        ch = run(md)
        self.assertEqual([f["code"] for f in ch.findings], ["TOTAL"])
        self.assertEqual(ch.findings[0]["line"], 5)
        self.assertIn("2,100", ch.findings[0]["message"])
        self.assertIn("2,000", ch.findings[0]["message"])

    def test_right_total_is_quiet(self):
        md = table(["Repo", "Stars"], ["a", "1,200"], ["b", "800"], ["Total", "2,000"])
        self.assertEqual(codes(md), [])
        self.assertEqual(run(md).stats["ok"], 1)

    def test_off_by_one_integer_is_an_error(self):
        md = table(["Suite", "Tests"], ["a", "41"], ["b", "12"], ["c", "7"], ["Total", "61"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_total_row_at_the_top(self):
        md = table(["Item", "n"], ["Total", "9"], ["a", "4"], ["b", "4"])
        self.assertEqual(codes(md), ["TOTAL"])
        md = table(["Item", "n"], ["Total", "8"], ["a", "4"], ["b", "4"])
        self.assertEqual(codes(md), [])

    def test_subtotals_and_a_grand_total(self):
        wrong = table(["Part", "Cost"], ["a", "1"], ["b", "2"], ["Subtotal", "3"], ["c", "4"], ["d", "5"],
                      ["Subtotal", "9"], ["Grand total", "13"])
        ch = run(wrong)
        self.assertEqual([f["code"] for f in ch.findings], ["TOTAL"])
        self.assertEqual(ch.findings[0]["line"], 9)
        # 1+2+4+5 = 3+9 = 12: the subtotals are not added in twice
        right = table(["Part", "Cost"], ["a", "1"], ["b", "2"], ["Subtotal", "3"], ["c", "4"], ["d", "5"],
                      ["Subtotal", "9"], ["Grand total", "12"])
        self.assertEqual(codes(right), [])

    def test_a_wrong_subtotal(self):
        md = table(["Part", "Cost"], ["a", "1"], ["b", "2"], ["Subtotal", "4"], ["c", "4"], ["Total", "7"])
        self.assertEqual(codes(md), ["TOTAL"])
        self.assertEqual(run(md).findings[0]["line"], 5)

    def test_invoice_subtotal_tax_total(self):
        md = table(["Item", "Price"], ["A", "$10.00"], ["B", "$5.50"], ["Subtotal", "$15.50"], ["Tax", "$1.24"],
                   ["Total", "$16.74"])
        self.assertEqual(codes(md), [])

    def test_money_with_cents_is_exact(self):
        md = table(["Item", "Price"], ["A", "$10.00"], ["B", "$5.50"], ["Total", "$15.49"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_japanese_label_and_yen(self):
        md = table(["項目", "金額"], ["家賃", "80,000円"], ["光熱費", "12,000円"], ["合計", "93,000円"])
        self.assertEqual(codes(md), ["TOTAL"])
        md = table(["項目", "件数"], ["A", "3"], ["B", "4"], ["計", "7"])
        self.assertEqual(codes(md), [])

    def test_label_with_parenthesis_and_colon(self):
        md = table(["Item", "Cost"], ["a", "1"], ["b", "2"], ["Total (USD):", "4"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_total_time_is_not_a_total_label(self):
        md = table(["Metric", "Value"], ["Stars", "10"], ["Forks", "3"], ["Total time", "99"])
        self.assertEqual(codes(md), [])
        self.assertEqual(run(md).stats["total_rows"], 0)

    def test_average_row_is_not_added(self):
        md = table(["Run", "ms"], ["a", "10"], ["b", "20"], ["Average", "15"], ["Total", "30"])
        self.assertEqual(codes(md), [])

    def test_year_column_is_not_summed(self):
        md = table(["Name", "Year", "Count"], ["a", "2019", "1"], ["b", "2020", "2"], ["Total", "2021", "3"])
        self.assertEqual(codes(md), [])


class Rounding(unittest.TestCase):
    def test_decimals_within_their_rounding(self):
        md = table(["Step", "s"], ["a", "1.2"], ["b", "3.4"], ["Total", "4.7"])
        self.assertEqual(codes(md), [])

    def test_decimals_beyond_their_rounding(self):
        md = table(["Step", "s"], ["a", "1.2"], ["b", "3.4"], ["Total", "4.9"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_percentages_that_round_to_100(self):
        md = table(["Kind", "Share"], ["a", "33.3%"], ["b", "33.3%"], ["c", "33.3%"], ["Total", "100%"])
        self.assertEqual(codes(md), [])

    def test_rates_are_not_shares(self):
        # a subtotal row under columns of accuracy rates: not a sum, and not a mean the table shows
        md = table(["Set", "n", "Acc"], ["a", "115", "90.4%"], ["b", "100", "99.0%"], ["c", "30607", "76.9%"],
                   ["**小计**", "**30822**", "**78.2%**"])
        ch = run(md)
        self.assertEqual(ch.findings, [])
        self.assertTrue(any("rates" in k for k in ch.unjudged))

    def test_percentages_that_do_not(self):
        md = table(["Kind", "Share"], ["a", "40%"], ["b", "35%"], ["c", "20%"], ["Total", "100%"])
        self.assertEqual(codes(md), ["TOTAL"])


class FromRealTables(unittest.TestCase):
    """Cases named after the public files (tuning half) that taught them."""

    def test_openai_evals_token_counts_rounded_to_three_figures(self):
        # evals/elsuite/already_said_that/README.md: 19,850,000 + 80,000 is shown as 19,940,000
        md = table(["Variant", "Input", "Output", "Total"], ["a", "17,960,000", "80,000", "18,040,000"],
                   ["b", "27,750,000", "110,000", "27,860,000"], ["c", "19,850,000", "80,000", "19,940,000"])
        self.assertEqual(codes(md), [])
        # but a difference larger than the rounding is still reported
        md = table(["Variant", "Input", "Output", "Total"], ["a", "17,960,000", "80,000", "18,040,000"],
                   ["b", "27,750,000", "110,000", "27,860,000"], ["c", "19,850,000", "80,000", "19,990,000"])
        self.assertEqual(codes(md), ["ROWTOTAL"])
        # and exact counts that happen to end in 00 are still exact
        md = table(["Suite", "Tests"], ["a", "100"], ["b", "200"], ["Total", "301"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_executorch_rows_left_out(self):
        # docs/source/llm/export-llm.md: a "..." row, and a row-number column left of the label
        md = table(["", "op_type", "n"], ["0", "add", "3"], ["", "...", ""], ["15", "mul", "4"],
                   ["42", "Total", "20"])
        ch = run(md)
        self.assertEqual(ch.findings, [])
        self.assertIn("rows are left out (...)", ch.unjudged)
        md = table(["", "op_type", "n"], ["0", "add", "3"], ["15", "mul", "4"], ["42", "Total", "7"])
        self.assertEqual(codes(md), [])

    def test_qbot_currency_codes(self):
        # README.md: **IDR1,194,606** / **USD78.71** -- a currency code written before the amount
        md = table(["Item", "IDR", "USD"], ["a", "IDR1,000,000", "USD 60.00"], ["b", "IDR194,606", "USD18.71"],
                   ["**Total**", "**IDR1,194,606**", "**USD94.22**"])
        self.assertEqual(codes(md), ["TOTAL"])
        self.assertEqual(t.parse_num("94.22 USD").cur, "usd")

    def test_eecs581_one_row_total(self):
        # minesweeper/docs/SystemArchitecture.md: one task, and a Total of 1 under it
        md = table(["Task", "Estimated", "Actual"], ["Documentation", "3.5", "5"], ["**Total**", "**1**", "**2**"])
        self.assertEqual(codes(md), ["TOTAL", "TOTAL"])
        md = table(["Task", "Estimated", "Actual"], ["Documentation", "3.5", "5"], ["**Total**", "**3.5**", "**5**"])
        self.assertEqual(codes(md), [])

    def test_lightspeedwp_named_subtotals(self):
        # AGENT_SKILLS_INVENTORY.md: "Batch 1 Subtotal", "Batch 2-3 Subtotal", "TOTAL (16 Agents)"
        md = table(["Agent", "Skills"], ["a", "25"], ["b", "24"], ["**Batch 1 Subtotal**", "**49**"],
                   ["c", "8"], ["d", "13"], ["**Batch 2-3 Subtotal**", "**21**"], ["**TOTAL (16 Agents)**", "**70**"])
        self.assertEqual(codes(md), [])
        # PHASE-2B-SKILLS-AUDIT.md: the Total column on an "Avg Skills/Agent" row is an average
        md = table(["Metric", "Batch 1", "Batch 2", "Total"], ["Skills", "125", "252", "377"],
                   ["Attached", "84", "108", "192"], ["Local", "16", "62", "78"],
                   ["**Avg Skills/Agent**", "25", "23", "23.6"])
        self.assertEqual(codes(md), [])

    def test_alarmpcb_named_totals(self):
        # README.md (a BOM): "COMPONENTS MERCHANDISE TOTAL" adds up the parts; "PCB MERCHANDISE TOTAL"
        # is a line of its own; the GRAND TOTAL adds up the merchandise total and the lines below it
        md = table(["Part", "Price"], ["R1", "0.45"], ["C1", "0.66"], ["**COMPONENTS MERCHANDISE TOTAL**", "**1.11**"],
                   ["**COMPONENTS SHIPPING FEE**", "**12.95**"], ["**PCB MERCHANDISE TOTAL**", "**10.30**"],
                   ["**PCB DISCOUNT**", "**-10.00**"], ["**GRAND TOTAL**", "**14.36**"])
        self.assertEqual(codes(md), [])
        self.assertEqual(codes(md.replace("**14.36**", "**14.46**")), ["TOTAL"])

    def test_functional_interface_package_named_avg(self):
        # QUANT-V4-...-P2.md: a package called `AVG-001` is a row to add, not an Average row
        md = table(["Package", "Questions"], ["`ALG-001`", "4"], ["`AVG-001`", "1"], ["`DI-001`", "2"],
                   ["**Total**", "**7**"])
        self.assertEqual(codes(md), [])

    def test_medicita_dot_thousands(self):
        # README.md: a Total of "1.429" under whole numbers is 1,429 written with a dot
        md = table(["Autor", "Commits"], ["a", "1000"], ["b", "429"], ["Total", "1.429"])
        ch = run(md)
        self.assertEqual(ch.findings, [])
        self.assertTrue(any("dot" in k for k in ch.unjudged))
        md = table(["Step", "s"], ["a", "1.250"], ["b", "2.500"], ["Total", "3.750"])
        self.assertEqual(codes(md), [])

    def test_eo_ai_funding_column(self):
        # README.md: ESA funding 5,500 + 15,000 + 7,000 + 11,500 + 8,500 = 47,500; the TOTAL row says 47,000
        md = table(["Task", "Title", "Total", "ESA"], ["**Task 1**", "x", "€ 6,000", "€ 5,500"],
                   ["**Task 2**", "y", "€ 17,500", "€ 15,000"], ["**Task 3**", "z", "€ 7,500", "€ 7,000"],
                   ["**TOTAL**", "**Summary**", "**€ 31,000**", "**€ 27,000**"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_tango_per_node_column(self):
        # docs/tgb/tgb.md: the B/node column adds up to 19.40 and the TOTAL row says 18.5
        md = table(["column", "comp MB", "B/node"], ["HASH", "21.52", "8.00"], ["DEPS", "9.96", "3.70"],
                   ["DICT", "5.95", "2.21"], ["**TOTAL**", "**37.43**", "**12.9**"])
        self.assertEqual(codes(md), ["TOTAL"])


class NotASum(unittest.TestCase):
    def test_mean(self):
        md = table(["Model", "Score"], ["a", "80.1"], ["b", "70.3"], ["c", "60.0"], ["Total", "70.1"])
        self.assertEqual(codes(md), [])
        self.assertEqual(run(md).stats["explained"], 1)

    def test_whole_numbers_are_not_explained_loosely(self):
        # 2021 is one more than the max (2020) and 1.5 from the mean: neither, so it is an error
        md = table(["Name", "Build", "Count"], ["a", "2019", "1"], ["b", "2020", "2"], ["Total", "2021", "3"])
        self.assertEqual(codes(md), ["TOTAL"])
        # 5 is neither 3+5 nor the mean of 3 and 5
        md = table(["Name", "n"], ["a", "3"], ["b", "5"], ["c", "1"], ["Total", "4"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_max(self):
        md = table(["Job", "Peak MB"], ["a", "120"], ["b", "300"], ["c", "80"], ["Total", "300"])
        self.assertEqual(codes(md), [])

    def test_ratio_of_two_other_totals(self):
        md = table(["Suite", "Passed", "Run", "Pass rate"], ["a", "9", "10", "90%"], ["b", "3", "5", "60%"],
                   ["Total", "12", "15", "80%"])
        self.assertEqual(codes(md), [])

    def test_weighted_mean(self):
        md = table(["Group", "n", "Avg"], ["a", "10", "2.0"], ["b", "30", "4.0"], ["Total", "40", "3.5"])
        self.assertEqual(codes(md), [])


class NotJudged(unittest.TestCase):
    def test_mixed_units(self):
        md = table(["File", "Size"], ["a", "900 KB"], ["b", "1.2 MB"], ["Total", "2 MB"])
        ch = run(md)
        self.assertEqual(ch.findings, [])
        self.assertEqual(ch.unjudged.get("mixed units"), 1)

    def test_text_among_the_rows(self):
        md = table(["Task", "Hours"], ["a", "3"], ["b", "3 (est.)"], ["Total", "9"])
        ch = run(md)
        self.assertEqual(ch.findings, [])
        self.assertTrue(ch.unjudged)

    def test_approximate(self):
        md = table(["Task", "Hours"], ["a", "~3"], ["b", "3"], ["Total", "9"])
        self.assertEqual(codes(md), [])

    def test_open_ended(self):
        md = table(["Task", "Users"], ["a", "100+"], ["b", "3"], ["Total", "900"])
        self.assertEqual(codes(md), [])

    def test_struck_through(self):
        md = table(["Task", "Hours"], ["a", "~~3~~ 4"], ["b", "3"], ["Total", "9"])
        self.assertEqual(codes(md), [])
        md = table(["Task", "Hours"], ["a", "<s>3</s>"], ["b", "3"], ["Total", "9"])
        self.assertEqual(codes(md), [])
        md = table(["Task", "Hours"], ["a", "<span>3</span>"], ["b", "3"], ["Total", "9"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_unknown(self):
        md = table(["Task", "Hours"], ["a", "?"], ["b", "3"], ["c", "3"], ["Total", "9"])
        self.assertEqual(codes(md), [])

    def test_blank_part_is_a_warning(self):
        md = table(["Task", "Hours"], ["a", "4"], ["b", "—"], ["c", "3"], ["Total", "9"])
        self.assertEqual(codes(md), ["TOTAL?"])
        self.assertEqual(codes(md, "error"), [])


class RowTotal(unittest.TestCase):
    def test_one_wrong_row(self):
        md = table(["Name", "Q1", "Q2", "Q3", "Total"], ["x", "1", "2", "3", "6"], ["y", "4", "5", "6", "15"],
                   ["z", "7", "8", "9", "25"])
        ch = run(md)
        self.assertEqual([f["code"] for f in ch.findings], ["ROWTOTAL"])
        self.assertEqual(ch.findings[0]["line"], 5)

    def test_total_column_first(self):
        md = table(["Name", "Total", "A", "B"], ["x", "3", "1", "2"], ["y", "9", "4", "5"], ["z", "4", "2", "1"])
        self.assertEqual(codes(md), ["ROWTOTAL"])

    def test_no_columns_add_up(self):
        md = table(["Name", "A", "B", "Total"], ["x", "1", "2", "10"], ["y", "4", "5", "20"], ["z", "7", "8", "30"])
        ch = run(md)
        self.assertEqual(ch.findings, [])
        self.assertTrue(any("adds up" in k for k in ch.unjudged))

    def test_one_row_that_adds_up_is_not_enough(self):
        md = table(["Name", "A", "B", "Total"], ["x", "1", "2", "3"], ["y", "4", "5", "20"], ["z", "7", "8", "30"])
        ch = run(md)
        self.assertEqual(ch.findings, [])

    def test_not_all_left_columns(self):
        # "Weight" is not part of the total: the two columns next to it are
        md = table(["Name", "Weight", "A", "B", "Total"], ["x", "70", "1", "2", "3"], ["y", "80", "4", "5", "9"],
                   ["z", "60", "2", "2", "5"])
        ch = run(md)
        self.assertEqual([f["code"] for f in ch.findings], ["ROWTOTAL"])
        self.assertEqual(ch.findings[0]["line"], 5)


class Share(unittest.TestCase):
    def test_wrong_share(self):
        md = table(["Lang", "Files", "%"], ["py", "50", "50.0%"], ["js", "30", "30.0%"], ["go", "20", "25.0%"],
                   ["Total", "100", "100%"])
        codes_ = codes(md)
        self.assertIn("SHARE", codes_)

    def test_right_share(self):
        md = table(["Lang", "Files", "%"], ["py", "50", "50.0%"], ["js", "30", "30.0%"], ["go", "20", "20.0%"],
                   ["Total", "100", "100%"])
        self.assertEqual(codes(md), [])


class Reading(unittest.TestCase):
    def test_code_fence_is_skipped(self):
        md = "```\n" + table(["a", "b"], ["x", "1"], ["y", "1"], ["Total", "3"]) + "```\n"
        self.assertEqual(codes(md), [])
        self.assertEqual(run(md).stats["tables"], 0)

    def test_html_comment_is_skipped(self):
        md = "<!--\n" + table(["a", "b"], ["x", "1"], ["y", "1"], ["Total", "3"]) + "-->\n"
        self.assertEqual(run(md).stats["tables"], 0)

    def test_european_decimals(self):
        md = table(["Posten", "Betrag"], ["a", "1.234,50"], ["b", "10,25"], ["Summe", "1.244,75"])
        self.assertEqual(codes(md), [])
        md = table(["Posten", "Betrag"], ["a", "1.234,50"], ["b", "10,25"], ["Summe", "1.254,75"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_negative_in_parentheses(self):
        md = table(["Line", "USD"], ["sales", "$100"], ["refunds", "($20)"], ["Total", "$80"])
        self.assertEqual(codes(md), [])

    def test_escaped_pipe_and_links(self):
        md = table(["Name", "Stars"], ["a \\| b", "[10](https://x)"], ["c", "**5**"], ["Total", "16"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_code_ticks_and_footnote(self):
        md = table(["Name", "n"], ["a", "`3`"], ["b", "4*"], ["Total", "7"])
        self.assertEqual(codes(md), [])

    def test_unit_written_once(self):
        md = table(["Step", "Time"], ["a", "10 ms"], ["b", "20 ms"], ["Total", "30 ms"])
        self.assertEqual(codes(md), [])

    def test_space_thousands(self):
        md = table(["Name", "n"], ["a", "1 200"], ["b", "300"], ["Total", "1 500"])
        self.assertEqual(codes(md), [])
        self.assertEqual(run(md).stats["ok"], 1)
        md = table(["Name", "n"], ["a", "1 200"], ["b", "300"], ["Total", "1 600"])
        self.assertEqual(codes(md), ["TOTAL"])

    def test_version_like_cells_are_not_numbers(self):
        self.assertIsNone(t.parse_num("1.2.3"))
        self.assertIsNone(t.parse_num("3-5"))
        self.assertIsNone(t.parse_num("1/2"))
        self.assertIsNone(t.parse_num("1,2345"))
        self.assertIsNone(t.parse_num("~3"))
        self.assertIsNone(t.parse_num("約3"))
        self.assertIsInstance(t.parse_num("-4"), t.Num)
        self.assertEqual(t.parse_num("1,234.5").value, t.Decimal("1234.5"))


class Cli(unittest.TestCase):
    def test_exit_codes_and_json(self):
        d = tempfile.mkdtemp()
        try:
            bad = os.path.join(d, "bad.md")
            good = os.path.join(d, "good.md")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write(table(["a", "n"], ["x", "1"], ["y", "1"], ["Total", "3"]))
            with open(good, "w", encoding="utf-8") as fh:
                fh.write(table(["a", "n"], ["x", "1"], ["y", "1"], ["Total", "2"]))
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(t.main([good]), 0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(t.main([d, "--json"]), 1)
            out = json.loads(buf.getvalue())
            self.assertEqual(out["files"], 2)
            self.assertEqual(len(out["findings"]), 1)
            self.assertTrue(out["findings"][0]["path"].endswith("bad.md"))
        finally:
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
            os.rmdir(d)


if __name__ == "__main__":
    unittest.main()
