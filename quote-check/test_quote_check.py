# -*- coding: utf-8 -*-
"""Tests for quote_check.py. Standard library only: python -m unittest test_quote_check -v"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import quote_check as qc


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dir = Path(self._d.name)
        self.addCleanup(self._d.cleanup)

    def write(self, name, text, encoding="utf-8"):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding=encoding)
        return p

    def run_tool(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = qc.main(argv)
        return code, buf.getvalue()


class TestExtract(Tmp):
    def test_corner_brackets_and_double_quotes(self):
        got = qc.extract('\u300cthe fee is 7.0 percent\u300d and "a second quotation here"', 8, False)
        self.assertEqual([q for _, q in got], ["the fee is 7.0 percent", "a second quotation here"])

    def test_nested_corner_brackets_are_kept_whole(self):
        got = qc.extract("\u300cthe page said \u300cno\u300d to that\u300d", 8, False)
        self.assertEqual([q for _, q in got], ["the page said \u300cno\u300d to that"])

    def test_short_quotes_are_skipped(self):
        self.assertEqual(qc.extract('"tiny" \u300cshort\u300d', 8, False), [])

    def test_fenced_code_is_skipped(self):
        doc = 'before "quoted text here"\n```\n"not a quotation at all"\n```\nafter'
        self.assertEqual([q for _, q in qc.extract(doc, 8, False)], ["quoted text here"])

    def test_inline_code_is_skipped(self):
        self.assertEqual(qc.extract('`"inside code span here"`', 8, False), [])

    def test_line_numbers_are_reported(self):
        doc = 'first line\n\n\u300cthe quotation on line three\u300d'
        self.assertEqual(qc.extract(doc, 8, False)[0][0], 3)

    def test_blockquote_block_is_one_quote(self):
        doc = "> the first half of it\n> and the second half\n\nplain"
        got = qc.extract(doc, 8, True)
        self.assertEqual([q for _, q in got], ["the first half of it and the second half"])

    def test_blockquote_only_with_the_flag(self):
        self.assertEqual(qc.extract("> a blockquote line", 8, False), [])

    def test_blockquote_at_end_of_file_is_not_dropped(self):
        got = qc.extract("intro\n> the last block in the file", 8, True)
        self.assertEqual([q for _, q in got], ["the last block in the file"])


class TestNormalize(Tmp):
    def test_index_map_points_back_at_the_input(self):
        raw = "a\u3000\u3000b"
        norm, idx = qc.normalize(raw, ("space",))
        self.assertEqual(norm, "a b")
        self.assertEqual([raw[i] for i in idx], ["a", "\u3000", "b"])
        # the contract is the START of a collapsed run, not somewhere inside it: a slice
        # that begins or ends on whitespace is cut with these numbers
        self.assertEqual(idx, [0, 1, 3])

    def test_invisible_characters_are_dropped(self):
        self.assertEqual(qc.normalize("a\u200bb", ("invisible",))[0], "ab")

    def test_axes_are_independent(self):
        self.assertEqual(qc.normalize("A\u3000B", ("case",))[0], "a\u3000b")
        self.assertEqual(qc.normalize("A\u3000B", ("space",))[0], "A B")

    def test_space_axis_strips_the_ends(self):
        self.assertEqual(qc.normalize("  a b  ", ("space",))[0], "a b")


class TestDescribe(Tmp):
    def test_a_line_break_is_named(self):
        self.assertIn("U+000A LINE FEED", qc.describe("\n"))

    def test_a_named_character_uses_its_unicode_name(self):
        self.assertIn("U+00A0 NO-BREAK SPACE", qc.describe(" "))

    def test_one_line_shows_a_line_break_as_an_escape(self):
        self.assertEqual(qc.oneline("a\nb\tc"), "a\\nb\\tc")


class TestVerdicts(Tmp):
    def source(self, text):
        return [("src", text)]

    def test_exact(self):
        f = qc.check_one("the fee is 7.0 percent", self.source("x the fee is 7.0 percent y"))
        self.assertEqual(f["verdict"], "exact")

    def test_full_width_space_is_named_as_space(self):
        f = qc.check_one("145 + 270 = 585", self.source("total: 145 +\u3000270 = 585 yen"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "space"))
        self.assertEqual(f["found"], "145 +\u3000270 = 585")

    def test_curly_quotes_are_named_as_quotes(self):
        f = qc.check_one('he said "the whole thing" once',
                         self.source('he said \u201cthe whole thing\u201d once'))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "quotes"))

    def test_em_dash_is_named_as_punct(self):
        f = qc.check_one("the fee - and the rest", self.source("the fee \u2014 and the rest"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "punct"))

    def test_full_width_digits_are_named_as_width(self):
        f = qc.check_one("the fee is 7.0 percent", self.source("the fee is \uff17.\uff10 percent"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "width"))

    def test_case_alone(self):
        f = qc.check_one("The Fee Is Seven", self.source("the fee is seven"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "case"))

    def test_zero_width_space_is_named_as_invisible(self):
        f = qc.check_one("the fee is seven", self.source("the fee\u200b is seven"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "invisible"))

    def test_line_wrap_in_the_source_is_a_space_difference(self):
        f = qc.check_one("the fee is seven percent",
                         self.source("the fee is\n    seven percent of each sale"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "space"))

    def test_two_axes_at_once_are_reported_as_multiple(self):
        f = qc.check_one("The fee is 7.0 percent", self.source("the fee is \uff17.\uff10 percent"))
        self.assertEqual((f["verdict"], f["axis"]), ("formatting", "multiple"))

    def test_one_changed_digit_is_substantive(self):
        f = qc.check_one("the fee is 7.0 percent of each sale",
                         self.source("we take the fee is 7.5 percent of each sale here"))
        self.assertEqual(f["verdict"], "substantive")
        self.assertEqual(f["a"][f["at"]], "0")
        self.assertEqual(f["b"][f["at"]], "5")

    def test_substantive_reports_the_closest_source(self):
        f = qc.check_one("the fee is 7.0 percent of each sale",
                         [("far", "nothing like it at all in here"),
                          ("near", "the fee is 7.5 percent of each sale")])
        self.assertEqual(f["source"], "near")
        self.assertGreater(f["score"], 0.9)

    def test_invented_quote_is_unfound(self):
        f = qc.check_one("there is no refund under any circumstances",
                         self.source("payouts are made on the tenth of the month"))
        self.assertEqual(f["verdict"], "unfound")

    def test_nfc_difference_is_not_a_finding(self):
        doc = self.write("d.md", "\u300cthe word is \u304c here\u300d")
        src = self.write("s.txt", "the word is \u304b\u3099 here")
        code, out = self.run_tool([str(doc), "--source", str(src)])
        self.assertEqual(code, 0)
        self.assertIn("exact       1", out)


class TestCli(Tmp):
    def test_exact_run_exits_zero(self):
        doc = self.write("d.md", '\u300cthe fee is 7.0 percent\u300d')
        self.write("pages/a.txt", "the fee is 7.0 percent of each sale")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertEqual(code, 0)
        self.assertIn("exact       1", out)

    def test_substantive_exits_one_and_names_the_character(self):
        doc = self.write("d.md", '\u300cthe fee is 7.0 percent of each sale\u300d')
        self.write("pages/a.txt", "the fee is 7.5 percent of each sale")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertEqual(code, 1)
        self.assertIn("substantive difference", out)
        self.assertIn("DIGIT ZERO", out)
        self.assertIn("DIGIT FIVE", out)

    def test_formatting_passes_by_default_and_fails_under_strict(self):
        doc = self.write("d.md", '\u300cthe fee is 7.0 percent\u300d')
        self.write("pages/a.txt", "the fee is\u30007.0 percent")
        args = [str(doc), "--sources", str(self.dir / "pages")]
        self.assertEqual(self.run_tool(args)[0], 0)
        code, out = self.run_tool(args + ["--strict"])
        self.assertEqual(code, 1)
        self.assertIn("formatting difference (space)", out)

    def test_formatting_names_the_differing_character_too(self):
        doc = self.write("d.md", '「Fees are quoted exclusive of tax」')
        self.write("pages/a.txt", "Fees are quoted exclusive of tax")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertEqual(code, 0)
        self.assertIn("NO-BREAK SPACE", out)

    def test_a_line_break_in_the_source_is_shown_as_an_escape(self):
        doc = self.write("d.md", '「the fee is seven percent」')
        self.write("pages/a.txt", "the fee is\nseven percent")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertIn("the fee is\\nseven percent", out)
        self.assertIn("LINE FEED", out)

    def test_unfound_exits_one(self):
        doc = self.write("d.md", '\u300cthere is no refund under any circumstances\u300d')
        self.write("pages/a.txt", "payouts are made on the tenth")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertEqual(code, 1)
        self.assertIn("not found in any source", out)

    def test_no_sources_is_two(self):
        doc = self.write("d.md", '\u300ca quotation here\u300d')
        self.assertEqual(self.run_tool([str(doc)])[0], 2)

    def test_missing_named_source_is_two(self):
        doc = self.write("d.md", '\u300ca quotation here\u300d')
        self.assertEqual(self.run_tool([str(doc), "--source", str(self.dir / "gone.txt")])[0], 2)

    def test_missing_document_is_two(self):
        self.write("pages/a.txt", "anything")
        self.assertEqual(self.run_tool([str(self.dir / "gone.md"), "--sources", str(self.dir / "pages")])[0], 2)

    def test_binary_source_is_skipped_and_never_confirms_a_quote(self):
        # the NUL-bearing file decodes as UTF-8 and contains the quote; it must not count
        doc = self.write("d.md", '\u300cthe fee is 7.0 percent\u300d')
        (self.dir / "pages").mkdir(exist_ok=True)
        (self.dir / "pages" / "b.bin").write_bytes(b"\x00the fee is 7.0 percent\x00")
        self.write("pages/a.txt", "payouts are made on the tenth")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertEqual(code, 1)
        self.assertIn("not found in any source", out)

    def test_a_readable_text_source_beside_an_unreadable_one_still_works(self):
        doc = self.write("d.md", '\u300cthe fee is 7.0 percent\u300d')
        (self.dir / "pages").mkdir(exist_ok=True)
        (self.dir / "pages" / "b.bin").write_bytes(b"\xff\xfe\x00\x01")
        self.write("pages/a.txt", "the fee is 7.0 percent")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages")])
        self.assertEqual(code, 0)
        self.assertIn("exact       1", out)

    def test_min_length_is_honoured(self):
        doc = self.write("d.md", '\u300cshort\u300d')
        self.write("pages/a.txt", "nothing similar here")
        self.assertEqual(self.run_tool([str(doc), "--sources", str(self.dir / "pages")])[0], 0)
        self.assertEqual(self.run_tool([str(doc), "--sources", str(self.dir / "pages"),
                                        "--min-length", "3"])[0], 1)

    def test_json_output_is_machine_readable(self):
        doc = self.write("d.md", '\u300cthe fee is 7.0 percent\u300d')
        self.write("pages/a.txt", "the fee is\u30007.0 percent")
        code, out = self.run_tool([str(doc), "--sources", str(self.dir / "pages"), "--json"])
        rows = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]["verdict"], "formatting")
        self.assertEqual(rows[0]["axis"], "space")
        self.assertEqual(rows[0]["line"], 1)
        self.assertNotIn("a", rows[0])


if __name__ == "__main__":
    unittest.main()
