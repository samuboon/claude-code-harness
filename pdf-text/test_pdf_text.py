# -*- coding: utf-8 -*-
"""python -m unittest test_pdf_text -v  (standard library only, no network)

The tests that matter here are the ones about failure. A reader that returns text for
readable PDFs is easy; the thing being tested is that the two unreadable demos do not
come back as an empty string, and that no code point is ever silently dropped.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import make_demo_pdfs
import pdf_text

HERE = Path(__file__).parent


class Demos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        make_demo_pdfs.write_all(cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, name):
        return pdf_text.read(self.dir / name)


class TestReadable(Demos):
    def test_simple_font_keeps_every_digit(self):
        r = self.read("text.pdf")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["missing"], 0)
        for number in ("3,200", "7.5%", "2,960"):
            self.assertIn(number, r["text"])

    def test_cid_font_with_tounicode_reads_japanese(self):
        r = self.read("cid-japanese.pdf")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["missing"], 0)
        self.assertIn("契約書", r["text"])          # 契約書
        self.assertIn("2026年9月23日", r["text"])   # 2026年9月23日
        self.assertTrue(r["fonts"][0]["tounicode"])


class TestUnreadableIsNamed(Demos):
    def test_scanned_pdf_is_not_an_empty_string(self):
        r = self.read("scanned.pdf")
        self.assertEqual(r["status"], "unreadable")
        self.assertEqual(r["text"], "")
        self.assertEqual(r["images"], 1)
        self.assertEqual(r["text_operators"], 0)
        joined = " ".join(r["reasons"]).lower()
        self.assertIn("image", joined)
        self.assertIn("ocr", joined)

    def test_font_without_tounicode_is_named_by_basefont(self):
        r = self.read("glyph-ids.pdf")
        self.assertEqual(r["status"], "unreadable")
        # The characters were reached, so they are in the output - as U+FFFD, not as nothing.
        self.assertEqual(r["missing"], r["chars"])
        self.assertEqual(r["text"].strip(), pdf_text.MISSING * 7)
        joined = " ".join(r["reasons"])
        self.assertIn("ABCDEF+KozMinPr6N-Regular", joined)
        self.assertIn("/ToUnicode", joined)
        self.assertEqual([f["decodable"] for f in r["fonts"]], [False])

    def test_not_a_pdf(self):
        p = self.dir / "notes.txt"
        p.write_text("this is not a PDF", encoding="utf-8")
        r = pdf_text.read(p)
        self.assertEqual(r["status"], "unreadable")
        self.assertIn("not a PDF", " ".join(r["reasons"]))

    def test_encrypted_pdf_says_encrypted(self):
        p = self.dir / "encrypted.pdf"
        data = (self.dir / "text.pdf").read_bytes()
        p.write_bytes(data.replace(b"/Size", b"/Encrypt 9 0 R /Size"))
        r = pdf_text.read(p)
        self.assertEqual(r["status"], "unreadable")
        self.assertIn("encrypted", " ".join(r["reasons"]))

    def test_unsupported_filter_is_named_not_guessed(self):
        p = self.dir / "lzw.pdf"
        data = (self.dir / "text.pdf").read_bytes()
        p.write_bytes(data.replace(b"/Filter /FlateDecode", b"/Filter /LZWDecode  "))
        r = pdf_text.read(p)
        self.assertIn("LZWDecode", r["unsupported_filters"])
        self.assertIn("LZWDecode", " ".join(r["reasons"]))


class TestNothingIsDroppedSilently(unittest.TestCase):
    def test_one_code_in_one_character_out_two_byte(self):
        stats = {"total": 0, "missing": 0}
        out = pdf_text.decode_show(bytes([0, 1, 0, 2, 0, 3]), {1: "a"}, True, stats)
        self.assertEqual(out, "a" + pdf_text.MISSING * 2)
        self.assertEqual(stats, {"total": 3, "missing": 2})

    def test_odd_trailing_byte_still_counts(self):
        stats = {"total": 0, "missing": 0}
        out = pdf_text.decode_show(bytes([0, 1, 9]), {1: "a"}, True, stats)
        self.assertEqual(out, "a" + pdf_text.MISSING)

    def test_single_byte_font_keeps_length(self):
        stats = {"total": 0, "missing": 0}
        out = pdf_text.decode_show(b"3,200", pdf_text.WINANSI, False, stats)
        self.assertEqual(out, "3,200")
        self.assertEqual(stats["missing"], 0)

    def test_octal_escape(self):
        self.assertEqual(pdf_text.unescape(rb"A\101\n"), b"AA\n")


class TestOutputSurvivesCp932(Demos):
    def test_report_is_ascii_even_for_a_japanese_path(self):
        src = (self.dir / "cid-japanese.pdf").read_bytes()
        p = self.dir / "請求書.pdf"   # 請求書.pdf
        p.write_bytes(src)
        r = pdf_text.read(p)
        text = pdf_text.report(r, p.with_suffix(".txt"))
        text.encode("cp932")   # would raise before it ever reached the console
        text.encode("ascii")

    def test_cli_writes_utf8_file_and_prints_nothing_to_stdout(self):
        out = self.dir / "out.txt"
        code = subprocess.run(
            [sys.executable, str(HERE / "pdf_text.py"), str(self.dir / "cid-japanese.pdf"),
             "-o", str(out)],
            capture_output=True, cwd=str(HERE))
        self.assertEqual(code.returncode, 0)
        self.assertEqual(code.stdout, b"")
        self.assertIn("契約書", out.read_text(encoding="utf-8"))

    def test_exit_codes(self):
        cases = {"text.pdf": 0, "cid-japanese.pdf": 0, "scanned.pdf": 2, "glyph-ids.pdf": 2}
        for name, expected in cases.items():
            with self.subTest(name):
                r = subprocess.run(
                    [sys.executable, str(HERE / "pdf_text.py"), str(self.dir / name),
                     "-o", str(self.dir / (name + ".txt"))],
                    capture_output=True, cwd=str(HERE))
                self.assertEqual(r.returncode, expected)

    def test_json_report_carries_the_reasons(self):
        r = subprocess.run(
            [sys.executable, str(HERE / "pdf_text.py"), str(self.dir / "scanned.pdf"),
             "-o", str(self.dir / "j.txt"), "--json"],
            capture_output=True, cwd=str(HERE))
        payload = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(payload["status"], "unreadable")
        self.assertTrue(payload["reasons"])
        self.assertIsNone(payload["out"])


def mixed_pdf(content):
    """One readable font (/F1) and one that cannot be decoded (/F2) on the same page."""
    objs = make_demo_pdfs.page_skeleton(4, b"<< /Font << /F1 5 0 R /F2 6 0 R >> >>")
    objs.append(make_demo_pdfs.stream(b"<< >>", content, compress=False))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /XXXXXX+Ghost "
                b"/Encoding /Identity-H >>")
    return make_demo_pdfs.build(objs)


class TestPartial(Demos):
    def test_unused_broken_font_is_not_reported(self):
        p = self.dir / "mixed-clean.pdf"
        p.write_bytes(mixed_pdf(b"BT /F1 14 Tf 72 780 Td (Opening balance 3,200 JPY) Tj ET\n"))
        r = pdf_text.read(p)
        self.assertEqual(r["status"], "ok")
        self.assertIn("3,200", r["text"])
        self.assertNotIn("XXXXXX+Ghost", " ".join(r["reasons"]))

    def test_mixed_document_is_partial_and_says_how_much(self):
        p = self.dir / "mixed.pdf"
        p.write_bytes(mixed_pdf(
            b"BT /F2 14 Tf 72 800 Td <00010002> Tj\n"
            b"/F1 14 Tf 0 -20 Td (Opening balance 3,200 JPY) Tj ET\n"))
        r = pdf_text.read(p, max_missing=0.02)
        self.assertEqual(r["status"], "partial")
        # The readable half is still delivered - a partial read is not a failed read.
        self.assertIn("3,200", r["text"])
        self.assertEqual(r["missing"], 2)
        joined = " ".join(r["reasons"])
        self.assertIn("XXXXXX+Ghost", joined)
        self.assertIn("lost a digit", joined)

    def test_max_missing_moves_the_line(self):
        p = self.dir / "mixed-threshold.pdf"
        p.write_bytes(mixed_pdf(
            b"BT /F2 14 Tf 72 800 Td <00010002> Tj\n"
            b"/F1 14 Tf 0 -20 Td (Opening balance 3,200 JPY) Tj ET\n"))
        self.assertEqual(pdf_text.read(p, max_missing=0.02)["status"], "partial")
        self.assertEqual(pdf_text.read(p, max_missing=0.9)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
