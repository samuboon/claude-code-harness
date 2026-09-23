#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for run_from_urls.py (what the GitHub Actions workflow runs).

    python -m unittest test_run_from_urls -v

No network: fetching goes through a fake opener that serves bytes from memory.
"""
import contextlib
import io
import os
import re
import shutil
import struct
import tempfile
import unittest
import zlib

import normal_y_check as nyc
import run_from_urls as rfu
from test_normal_y_check import N, flip_green, height_bumps, map_central, write_png

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, "normal-y-check.yml")
HF = height_bumps(N)
YPLUS = map_central(HF, N, 3.0)
YMINUS = flip_green(YPLUS)
FLAT = [128, 128, 255] * (N * N)


def slurp(path, text=False):
    with open(path, "r" if text else "rb", **({"encoding": "utf-8"} if text else {})) as f:
        return f.read()


def samples(path):
    w, h, ch, mx, rows = nyc.read_png(path)
    return w, h, ch, mx, [s for row in rows for s in row]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rfu_")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def png(self, name, px, **kw):
        p = os.path.join(self.tmp, name)
        write_png(p, N, N, px, **kw)
        return p

    def png_bytes(self, px, **kw):
        with open(self.png("tmp_bytes.png", px, **kw), "rb") as f:
            return f.read()

    def run_main(self, argv, served=None):
        served = served or {}
        self.requested = []

        def opener(url):
            self.requested.append(url)
            if url not in served:
                raise OSError("404")
            return FakeResponse(served[url])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rfu.main(argv + ["--out", self.out], opener=opener)
        return code, buf.getvalue()


class TestFixing(Base):
    def test_wrong_way_map_is_inverted_and_rechecked(self):
        src = self.png("brick.png", YMINUS)
        r = rfu.process(src, "brick.png", nyc.Y_PLUS, os.path.join(self.out, "fixed"))
        self.assertTrue(r["action"].startswith("green inverted"), r)
        dst = os.path.join(self.out, "fixed", "brick.png")
        self.assertEqual(nyc.check_file(dst)["verdict"], nyc.Y_PLUS)

    def test_only_green_changes(self):
        src = self.png("a.png", YMINUS)
        dst = os.path.join(self.tmp, "b.png")
        rfu.invert_green(src, dst)
        w0, h0, c0, m0, s0 = samples(src)
        w1, h1, c1, m1, s1 = samples(dst)
        self.assertEqual((w0, h0, c0, m0), (w1, h1, c1, m1))
        for i, (a, b) in enumerate(zip(s0, s1)):
            if i % c0 == 1:
                self.assertEqual(b, m0 - a)
            else:
                self.assertEqual(b, a)

    def test_16_bit_rgba_keeps_depth_and_alpha(self):
        px16 = map_central(HF, N, 3.0, green=-1, maxval=65535)
        rgba = []
        for i in range(0, len(px16), 3):
            rgba += px16[i:i + 3] + [(i // 3) % 65536]
        src = self.png("deep.png", rgba, channels=4, depth=16)
        r = rfu.process(src, "deep.png", nyc.Y_PLUS, os.path.join(self.out, "fixed"))
        self.assertTrue(r["action"].startswith("green inverted"), r)
        _w, _h, ch, mx, s1 = samples(os.path.join(self.out, "fixed", "deep.png"))
        self.assertEqual((ch, mx), (4, 65535))
        self.assertEqual(s1[3::4], rgba[3::4])
        self.assertEqual(s1[1::4], [65535 - g for g in rgba[1::4]])

    def test_asking_for_y_minus_fixes_a_y_plus_map(self):
        src = self.png("p.png", YPLUS)
        r = rfu.process(src, "p.png", nyc.Y_MINUS, os.path.join(self.out, "fixed"))
        self.assertTrue(r["action"].startswith("green inverted"), r)
        self.assertEqual(nyc.check_file(os.path.join(self.out, "fixed", "p.png"))["verdict"], nyc.Y_MINUS)

    def test_right_way_map_is_left_alone(self):
        src = self.png("ok.png", YPLUS)
        r = rfu.process(src, "ok.png", nyc.Y_PLUS, os.path.join(self.out, "fixed"))
        self.assertEqual(r["action"], "already Y+")
        self.assertFalse(os.path.exists(os.path.join(self.out, "fixed", "ok.png")))

    def test_undecided_map_is_never_flipped(self):
        src = self.png("flat.png", FLAT)
        r = rfu.process(src, "flat.png", nyc.Y_PLUS, os.path.join(self.out, "fixed"))
        self.assertEqual(r["verdict"], nyc.UNDECIDED)
        self.assertFalse(os.path.exists(os.path.join(self.out, "fixed", "flat.png")))

    def test_a_fix_that_does_not_recheck_is_withheld(self):
        # Simulate a broken inverter (it copies the file unchanged). The re-check must
        # catch it, and no file may be handed over.
        src = self.png("brick.png", YMINUS)
        real = rfu.invert_green
        rfu.invert_green = lambda s, d: shutil.copyfile(s, d)
        try:
            r = rfu.process(src, "brick.png", nyc.Y_PLUS, os.path.join(self.out, "fixed"))
        finally:
            rfu.invert_green = real
        self.assertEqual(r["action"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.out, "fixed", "brick.png")))

    def test_colour_space_chunk_is_kept_and_unknown_unsafe_chunk_dropped(self):
        src = self.png("meta.png", YMINUS)
        with open(src, "rb") as f:
            data = f.read()
        extra = rfu._chunk(b"sRGB", b"\x00") + rfu._chunk(b"xYZW", b"secret")
        data = data[:33] + extra + data[33:]          # right after IHDR (8 + 25 bytes)
        with open(src, "wb") as f:
            f.write(data)
        dst = os.path.join(self.tmp, "meta_fixed.png")
        rfu.invert_green(src, dst)
        tags = [t for t, _b in rfu._chunks(slurp(dst))]
        self.assertIn(b"sRGB", tags)
        self.assertNotIn(b"xYZW", tags)

    def test_written_file_has_valid_crcs(self):
        dst = os.path.join(self.tmp, "c.png")
        rfu.invert_green(self.png("c0.png", YMINUS), dst)
        data = slurp(dst)
        i = 8
        while i < len(data):
            n = struct.unpack(">I", data[i:i + 4])[0]
            body = data[i + 4:i + 8 + n]
            crc = struct.unpack(">I", data[i + 8 + n:i + 12 + n])[0]
            self.assertEqual(zlib.crc32(body) & 0xFFFFFFFF, crc)
            i += 12 + n


class TestLinks(Base):
    def test_only_https(self):
        for bad in ("http://example.com/a.png", "file:///etc/passwd", "ftp://x/a.png", "a.png"):
            with self.assertRaises(rfu.FetchError, msg=bad):
                rfu.normalise_url(bad)

    def test_password_in_link_is_refused(self):
        with self.assertRaises(rfu.FetchError):
            rfu.normalise_url("https://user:pw@example.com/a.png")

    def test_github_page_link_becomes_raw_file(self):
        self.assertEqual(
            rfu.normalise_url("https://github.com/o/r/blob/main/tex/n.png"),
            "https://raw.githubusercontent.com/o/r/main/tex/n.png")

    def test_other_links_unchanged(self):
        u = "https://raw.githubusercontent.com/o/r/main/n.png"
        self.assertEqual(rfu.normalise_url(u), u)

    def test_split_on_spaces_commas_and_newlines(self):
        self.assertEqual(rfu.split_urls(" https://a/1.png, https://b/2.png\nhttps://c/3.png "),
                         ["https://a/1.png", "https://b/2.png", "https://c/3.png"])

    def test_names_are_unique_and_safe(self):
        used = set()
        a = rfu.file_name("https://x/a/normal.png", used)
        b = rfu.file_name("https://y/b/normal.png", used)
        c = rfu.file_name("https://z/..%2F..%2Fevil", used)
        self.assertNotEqual(a, b)
        self.assertNotIn("/", c)
        self.assertNotIn("..", c)
        self.assertTrue(c.endswith(".png"))


class TestFetch(Base):
    def test_non_png_is_refused(self):
        for body, word in ((b"\xff\xd8\xff\xe0jpeg", "JPEG"), (b"<!DOCTYPE html><html>", "web page")):
            with self.assertRaises(rfu.FetchError) as cm:
                rfu.fetch("https://x/a.png", opener=lambda u, b=body: FakeResponse(b))
            self.assertIn(word, str(cm.exception))

    def test_size_limit(self):
        big = nyc.PNG_SIG + b"\0" * 100
        with self.assertRaises(rfu.FetchError):
            rfu.fetch("https://x/a.png", opener=lambda u: FakeResponse(big), limit=50)

    def test_network_error_is_reported_not_raised(self):
        def boom(u):
            raise OSError("connection reset")
        with self.assertRaises(rfu.FetchError):
            rfu.fetch("https://x/a.png", opener=boom)


class TestRun(Base):
    def test_end_to_end(self):
        served = {"https://x/wrong.png": self.png_bytes(YMINUS),
                  "https://x/right.png": self.png_bytes(YPLUS),
                  "https://x/flat.png": self.png_bytes(FLAT)}
        code, text = self.run_main(["--want", "y+", " ".join(served)], served)
        self.assertEqual(code, 0, text)
        self.assertEqual(os.listdir(os.path.join(self.out, "fixed")), ["wrong.png"])
        self.assertIn("1 fixed", text)
        self.assertIn("1 already Y+", text)
        self.assertIn("1 undecided", text)
        rows = slurp(os.path.join(self.out, "verdicts.tsv"), text=True).splitlines()
        self.assertEqual(len(rows), 4)

    def test_failed_fetch_exits_1_and_others_still_run(self):
        served = {"https://x/wrong.png": self.png_bytes(YMINUS)}
        code, text = self.run_main(["--want", "y+", "https://x/missing.png https://x/wrong.png"], served)
        self.assertEqual(code, 1)
        self.assertIn("1 failed", text)
        self.assertTrue(os.path.exists(os.path.join(self.out, "fixed", "wrong.png")))

    def test_downloaded_originals_are_not_left_in_the_result(self):
        served = {"https://x/wrong.png": self.png_bytes(YMINUS)}
        self.run_main(["--want", "y+", "https://x/wrong.png"], served)
        self.assertEqual(sorted(os.listdir(self.out)), ["fixed", "report.md", "verdicts.tsv"])

    def test_http_link_is_not_requested(self):
        code, _text = self.run_main(["--want", "y+", "http://x/a.png"], {})
        self.assertEqual(code, 1)
        self.assertEqual(self.requested, [])

    def test_too_many_links(self):
        links = " ".join("https://x/%d.png" % i for i in range(rfu.MAX_IMAGES + 1))
        code, _text = self.run_main(["--want", "y+", links], {})
        self.assertEqual(code, 2)
        self.assertEqual(self.requested, [])

    def test_no_links(self):
        code, _text = self.run_main(["--want", "y+"], {})
        self.assertEqual(code, 2)

    def test_step_summary_is_written_when_on_actions(self):
        summary = os.path.join(self.tmp, "summary.md")
        os.environ["GITHUB_STEP_SUMMARY"] = summary
        try:
            self.run_main(["--want", "y-", "--file", self.png("local.png", YPLUS)])
        finally:
            del os.environ["GITHUB_STEP_SUMMARY"]
        self.assertIn("1 fixed", slurp(summary, text=True))


class TestWorkflow(unittest.TestCase):
    """The workflow file itself: inputs must never be pasted into a shell line."""

    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as f:
            self.text = f.read()

    def test_inputs_are_not_interpolated_into_run(self):
        run_block = re.search(r"run: \|\n((?:          .*\n)+)", self.text).group(1)
        self.assertNotIn("${{", run_block)

    def test_read_only_token(self):
        self.assertIn("permissions:\n  contents: read", self.text)

    def test_calls_this_script(self):
        self.assertIn("normal-y-check/run_from_urls.py", self.text)
        self.assertTrue(os.path.exists(os.path.join(HERE, "run_from_urls.py")))

    def test_both_choices_map_to_a_convention(self):
        self.assertIn('"Y+ (OpenGL)"', self.text)
        self.assertIn('"Y- (DirectX)"', self.text)
        self.assertIn("Y-*) want=y- ;;", self.text)


if __name__ == "__main__":
    unittest.main()
