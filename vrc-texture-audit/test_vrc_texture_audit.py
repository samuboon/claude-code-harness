#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vrc_texture_audit の試験(標準ライブラリのみ)。

    python test_vrc_texture_audit.py

いちばん重い主張は「アルファ板を持っているが全画素が不透明」の判定なので、
PNG の 5 つのフィルタ全部・8bit と 16bit・グレースケール+アルファ・パレット+tRNS を
それぞれ作って当てる。エンコーダによってフィルタが変わるため、1 つでも取りこぼすと
実物で嘘の判定を出す。
"""
from __future__ import annotations

import io
import os
import random
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vrc_texture_audit as V  # noqa: E402


# --- PNG を組み立てる --------------------------------------------------------

def _chunk(name, data):
    return (struct.pack(">I", len(data)) + name + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF))


def _filter_row(ft, cur, prev, bpp):
    """符号化側。復号側と独立に書いてあるので、片方を壊せば試験が落ちる。"""
    out = bytearray(len(cur))
    for i, x in enumerate(cur):
        a = cur[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if ft == 0:
            p = 0
        elif ft == 1:
            p = a
        elif ft == 2:
            p = b
        elif ft == 3:
            p = (a + b) >> 1
        elif ft == 4:
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            p = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
        else:
            raise ValueError(ft)
        out[i] = (x - p) & 255
    return bytes(out)


def make_png(path, width, height, color_type, bit_depth=8, alpha_values=None,
             filters=None, palette_trns=None, interlace=0, rows_in_idat=None):
    """テスト用の PNG を作る。alpha_values は画素ごとのアルファ(0-255)。"""
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    sample = bit_depth // 8
    bpp = channels * sample
    def px(values):
        """0-255 の成分を、その bit depth のバイト列にする。"""
        if sample == 1:
            return bytes(values)
        return b"".join(struct.pack(">H", v * 257) for v in values)

    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            idx = y * width + x
            if color_type == 6:
                row += px([(x * 7) & 255, (y * 11) & 255, 33])
            elif color_type == 4:
                row += px([(x * 5) & 255])
            elif color_type == 2:
                row += px([1, 2, 3])
            elif color_type == 3:
                row += bytes([idx % max(1, len(palette_trns or [1]))])
            else:
                row += px([7])
            if color_type in (4, 6):
                row += px([alpha_values[idx] if alpha_values else 255])
        rows.append(bytes(row))

    stride = width * bpp
    raw = bytearray()
    prev = b"\x00" * stride
    for y, row in enumerate(rows):
        if rows_in_idat is not None and y >= rows_in_idat:
            break   # IHDR は height 行と言っているのに、IDAT にはこれしか無い
        ft = (filters[y] if filters else 0)
        raw.append(ft)
        raw += _filter_row(ft, row, prev, bpp)
        prev = row

    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace)
    body = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
    if color_type == 3:
        n = max(1, len(palette_trns or [1]))
        body += _chunk(b"PLTE", bytes([9, 9, 9] * n))
        if palette_trns is not None:
            body += _chunk(b"tRNS", bytes(palette_trns))
    body += _chunk(b"IDAT", zlib.compress(bytes(raw)))
    body += _chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(body)
    return path


def make_tga(path, width, height, depth=32, alpha_bits=8):
    head = bytearray(18)
    head[2] = 2
    struct.pack_into("<HH", head, 12, width, height)
    head[16] = depth
    head[17] = alpha_bits
    with open(path, "wb") as fh:
        fh.write(bytes(head) + b"\x00" * (width * height * (depth // 8)))
    return path


def make_bmp(path, width, height, bpp=24):
    head = bytearray(54)
    head[0:2] = b"BM"
    struct.pack_into("<I", head, 14, 40)
    struct.pack_into("<ii", head, 18, width, height)
    struct.pack_into("<H", head, 26, 1)
    struct.pack_into("<H", head, 28, bpp)
    with open(path, "wb") as fh:
        fh.write(bytes(head) + b"\x00" * 16)
    return path


def make_psd(path, width, height, channels=4, color_mode=3):
    head = bytearray(26)
    head[0:4] = b"8BPS"
    struct.pack_into(">H", head, 4, 1)
    struct.pack_into(">H", head, 12, channels)
    struct.pack_into(">II", head, 14, height, width)
    struct.pack_into(">H", head, 22, 8)
    struct.pack_into(">H", head, 24, color_mode)
    with open(path, "wb") as fh:
        fh.write(bytes(head))
    return path


def make_jpeg(path, width, height, with_dht=False):
    body = b"\xff\xd8"
    body += b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    body += b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + b"\x10" * 64
    if with_dht:
        # DHT(0xC4)は 0xC0-0xCF の範囲に居るが SOF ではない。素直に範囲で拾うと
        # ここを寸法として読んでしまう —— 実物の JPEG はたいてい DHT を先に置く
        body += b"\xff\xc4" + struct.pack(">H", 21) + b"\x00" + bytes(range(1, 17)) + b"\x01\x02"
    body += b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    body += b"\xff\xd9"
    with open(path, "wb") as fh:
        fh.write(body)
    return path


def make_gif(path, width, height):
    with open(path, "wb") as fh:
        fh.write(b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00")
    return path


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vrctex")

    def tearDown(self):
        for dirpath, _dirnames, filenames in os.walk(self.dir, topdown=False):
            for name in filenames:
                os.unlink(os.path.join(dirpath, name))
            os.rmdir(dirpath)

    def p(self, name):
        full = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full


# --- ヘッダ ------------------------------------------------------------------

class TestHeaders(Tmp):
    def test_png_rgba_has_alpha(self):
        t = V.read_header(make_png(self.p("a.png"), 8, 4, 6), "a.png")
        self.assertEqual((t.kind, t.width, t.height, t.alpha), ("png", 8, 4, True))

    def test_png_rgb_has_no_alpha(self):
        t = V.read_header(make_png(self.p("b.png"), 5, 3, 2), "b.png")
        self.assertEqual((t.width, t.height, t.alpha), (5, 3, False))

    def test_png_gray_alpha(self):
        t = V.read_header(make_png(self.p("g.png"), 4, 2, 4), "g.png")
        self.assertTrue(t.alpha)

    def test_png_palette_without_trns_has_no_alpha(self):
        t = V.read_header(make_png(self.p("p.png"), 4, 2, 3), "p.png")
        self.assertFalse(t.alpha)

    def test_png_palette_with_trns_has_alpha(self):
        t = V.read_header(make_png(self.p("pt.png"), 4, 2, 3, palette_trns=[255, 0]), "pt.png")
        self.assertTrue(t.alpha)
        self.assertEqual(t.note, "palette")

    def test_png_reads_interlace_flag(self):
        t = V.read_header(make_png(self.p("i.png"), 4, 2, 6, interlace=1), "i.png")
        self.assertEqual(t.png_meta["interlace"], 1)

    def test_tga_32bit_has_alpha(self):
        t = V.read_header(make_tga(self.p("t.tga"), 16, 8), "t.tga")
        self.assertEqual((t.kind, t.width, t.height, t.alpha), ("tga", 16, 8, True))

    def test_tga_24bit_has_no_alpha(self):
        t = V.read_header(make_tga(self.p("t24.tga"), 16, 8, depth=24, alpha_bits=0), "t24.tga")
        self.assertFalse(t.alpha)

    def test_tga_32bit_with_zero_alpha_bits_has_no_alpha(self):
        t = V.read_header(make_tga(self.p("t0.tga"), 4, 4, depth=32, alpha_bits=0), "t0.tga")
        self.assertFalse(t.alpha)

    def test_bmp_32bit(self):
        t = V.read_header(make_bmp(self.p("x.bmp"), 12, 6, bpp=32), "x.bmp")
        self.assertEqual((t.width, t.height, t.alpha), (12, 6, True))

    def test_bmp_core_header_is_refused_not_guessed(self):
        path = self.p("core.bmp")
        make_bmp(path, 12, 6)
        with open(path, "r+b") as fh:
            fh.seek(14)
            fh.write(struct.pack("<I", 12))
        with self.assertRaises(ValueError):
            V.read_header(path, "core.bmp")

    def test_psd_rgb_with_extra_channel_has_alpha(self):
        t = V.read_header(make_psd(self.p("a.psd"), 64, 32), "a.psd")
        self.assertEqual((t.width, t.height, t.alpha), (64, 32, True))

    def test_psd_rgb_three_channels_has_no_alpha(self):
        t = V.read_header(make_psd(self.p("b.psd"), 64, 32, channels=3), "b.psd")
        self.assertFalse(t.alpha)

    def test_psd_unknown_color_mode_is_unknown_not_false(self):
        t = V.read_header(make_psd(self.p("c.psd"), 8, 8, channels=5, color_mode=7), "c.psd")
        self.assertIsNone(t.alpha)

    def test_jpeg_dimensions(self):
        t = V.read_header(make_jpeg(self.p("j.jpg"), 640, 480), "j.jpg")
        self.assertEqual((t.kind, t.width, t.height, t.alpha), ("jpg", 640, 480, False))

    def test_jpeg_skips_a_dht_that_sits_in_the_sof_marker_range(self):
        t = V.read_header(make_jpeg(self.p("d.jpg"), 320, 240, with_dht=True), "d.jpg")
        self.assertEqual((t.width, t.height), (320, 240))

    def test_gif_alpha_is_unknown(self):
        t = V.read_header(make_gif(self.p("g.gif"), 32, 16), "g.gif")
        self.assertIsNone(t.alpha)

    def test_unknown_bytes_raise(self):
        path = self.p("junk.png")
        with open(path, "wb") as fh:
            fh.write(b"not a png at all")
        with self.assertRaises(ValueError):
            V.read_header(path, "junk.png")


# --- アルファの中身 -----------------------------------------------------------

class TestAlphaScan(Tmp):
    def _used(self, path):
        t = V.read_header(path, os.path.basename(path))
        return V.png_alpha_is_used(path, t.png_meta, t.width, t.height)

    def test_all_opaque_rgba_is_not_used(self):
        p = make_png(self.p("o.png"), 16, 8, 6, alpha_values=[255] * 128)
        self.assertIs(self._used(p), False)

    def test_one_transparent_pixel_is_used(self):
        a = [255] * 128
        a[77] = 254
        p = make_png(self.p("u.png"), 16, 8, 6, alpha_values=a)
        self.assertIs(self._used(p), True)

    def test_last_pixel_transparent_is_used(self):
        a = [255] * 128
        a[-1] = 0
        p = make_png(self.p("last.png"), 16, 8, 6, alpha_values=a)
        self.assertIs(self._used(p), True)

    def test_every_filter_type_opaque(self):
        for ft in range(5):
            p = make_png(self.p("f%d.png" % ft), 12, 6, 6,
                         alpha_values=[255] * 72, filters=[ft] * 6)
            self.assertIs(self._used(p), False, "filter %d を不透明と読めていない" % ft)

    def test_every_filter_type_transparent(self):
        for ft in range(5):
            a = [255] * 72
            a[40] = 3
            p = make_png(self.p("t%d.png" % ft), 12, 6, 6,
                         alpha_values=a, filters=[ft] * 6)
            self.assertIs(self._used(p), True, "filter %d の透過を見落とした" % ft)

    def test_mixed_filters_per_row(self):
        a = [255] * 72
        a[70] = 1
        p = make_png(self.p("mix.png"), 12, 6, 6, alpha_values=a, filters=[0, 4, 1, 3, 2, 4])
        self.assertIs(self._used(p), True)

    def test_gray_alpha_opaque(self):
        p = make_png(self.p("ga.png"), 10, 5, 4, alpha_values=[255] * 50)
        self.assertIs(self._used(p), False)

    def test_gray_alpha_transparent(self):
        a = [255] * 50
        a[9] = 200
        p = make_png(self.p("gb.png"), 10, 5, 4, alpha_values=a, filters=[4] * 5)
        self.assertIs(self._used(p), True)

    def test_16bit_opaque(self):
        p = make_png(self.p("h.png"), 8, 4, 6, bit_depth=16,
                     alpha_values=[255] * 32, filters=[4, 1, 3, 2])
        self.assertIs(self._used(p), False)

    def test_16bit_transparent(self):
        a = [255] * 32
        a[17] = 128
        p = make_png(self.p("h2.png"), 8, 4, 6, bit_depth=16, alpha_values=a, filters=[3] * 4)
        self.assertIs(self._used(p), True)

    def test_palette_trns_all_opaque_is_not_used(self):
        p = make_png(self.p("pa.png"), 4, 2, 3, palette_trns=[255, 255])
        self.assertIs(self._used(p), False)

    def test_palette_trns_with_a_hole_is_used(self):
        p = make_png(self.p("pb.png"), 4, 2, 3, palette_trns=[255, 0])
        self.assertIs(self._used(p), True)

    def test_interlaced_is_unknown_not_false(self):
        p = make_png(self.p("il.png"), 8, 4, 6, alpha_values=[255] * 32, interlace=1)
        self.assertIsNone(self._used(p))

    def test_truncated_idat_is_unknown_not_false(self):
        p = make_png(self.p("tr.png"), 16, 8, 6, alpha_values=[255] * 128)
        data = open(p, "rb").read()
        with open(p, "wb") as fh:
            fh.write(data[:len(data) - 30])
        self.assertIsNone(self._used(p))

    def test_idat_short_of_the_declared_height_is_unknown_not_false(self):
        # IHDR は 8 行と言っているのに IDAT には 3 行しか無い。IEND は正しく続く。
        # 読み切れなかったものを「アルファは使われていない」と報告してはいけない。
        p = make_png(self.p("sh.png"), 16, 8, 6, alpha_values=[255] * 128,
                     rows_in_idat=3)
        self.assertIsNone(self._used(p))


# --- フィルタの復号(符号化側と往復させる)-----------------------------------

class TestUnfilter(unittest.TestCase):
    """_unfilter_plane を、独立に書いた符号化側と往復させて確かめる。

    アルファ板が全部 255 の絵だけで試すと、Paeth の 3 候補が同じ値になってしまい、
    Paeth を壊しても試験が落ちない。ばらついた板を通すのはそのための試験である。
    """

    def _planes(self):
        # 再現するように種を固定した疑似乱数。左・上・左上が別々の値になるよう作る。
        rnd = random.Random(20260915)
        prev = bytes(rnd.randrange(256) for _ in range(32))
        cur = bytes(rnd.randrange(256) for _ in range(32))
        return prev, cur

    def test_round_trip_for_every_filter_type(self):
        prev, cur = self._planes()
        for ft in range(5):
            enc = _filter_row(ft, cur, prev, 1)
            self.assertEqual(V._unfilter_plane(ft, enc, prev), cur, "filter %d" % ft)

    def test_paeth_picks_each_of_the_three_candidates_at_least_once(self):
        # 上の往復試験が Paeth の 3 本の枝を実際に通っていることを確かめる。
        prev, cur = self._planes()
        picked = set()
        for i, x in enumerate(cur):
            a = cur[i - 1] if i else 0
            b = prev[i]
            c = prev[i - 1] if i else 0
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            picked.add("a" if (pa <= pb and pa <= pc) else ("b" if pb <= pc else "c"))
        self.assertEqual(picked, {"a", "b", "c"})

    def test_first_row_uses_zero_above(self):
        _, cur = self._planes()
        zero = b"\x00" * len(cur)
        for ft in range(5):
            enc = _filter_row(ft, cur, zero, 1)
            self.assertEqual(V._unfilter_plane(ft, enc, zero), cur, "filter %d" % ft)


# --- 数字 --------------------------------------------------------------------

class TestArithmetic(unittest.TestCase):
    def test_bc3_4096_with_mips(self):
        t = V.Texture("x", "x", "png", 4096, 4096, True)
        # 4096*4096*1.0*4/3 = 22369621.33 バイト = 21.33 MB
        self.assertAlmostEqual(t.est_bytes / (1024 * 1024), 21.333, places=2)

    def test_bc1_is_half_of_bc3(self):
        a = V.Texture("x", "x", "png", 1024, 1024, True)
        b = V.Texture("x", "x", "png", 1024, 1024, False)
        self.assertAlmostEqual(a.est_bytes, b.est_bytes * 2)

    def test_unknown_alpha_is_costed_as_if_present(self):
        u = V.Texture("x", "x", "gif", 512, 512, None)
        a = V.Texture("x", "x", "png", 512, 512, True)
        self.assertEqual(u.est_bytes, a.est_bytes)

    def test_wasted_is_zero_until_proven(self):
        t = V.Texture("x", "x", "png", 512, 512, True)
        self.assertEqual(t.wasted_bytes, 0.0)
        t.alpha_used = True
        self.assertEqual(t.wasted_bytes, 0.0)
        t.alpha_used = False
        self.assertAlmostEqual(t.wasted_bytes, 512 * 512 * 0.5 * 4 / 3)

    def test_npot(self):
        self.assertFalse(V.Texture("x", "x", "png", 1024, 512, False).npot)
        self.assertTrue(V.Texture("x", "x", "png", 1000, 512, False).npot)
        self.assertTrue(V.Texture("x", "x", "png", 1024, 513, False).npot)

    def test_rank_boundaries_pc(self):
        mb = 1024 * 1024
        self.assertEqual(V.rank_for(40 * mb, "pc")[0], "Excellent")
        self.assertEqual(V.rank_for(40 * mb + 1, "pc")[0], "Good")
        self.assertEqual(V.rank_for(75 * mb, "pc")[0], "Good")
        self.assertEqual(V.rank_for(110 * mb, "pc")[0], "Medium")
        self.assertEqual(V.rank_for(150 * mb, "pc")[0], "Poor")
        self.assertEqual(V.rank_for(150 * mb + 1, "pc")[0], "Very Poor")

    def test_rank_boundaries_quest(self):
        mb = 1024 * 1024
        self.assertEqual(V.rank_for(10 * mb, "quest")[0], "Excellent")
        self.assertEqual(V.rank_for(18 * mb, "quest")[0], "Good")
        self.assertEqual(V.rank_for(25 * mb, "quest")[0], "Medium")
        self.assertEqual(V.rank_for(40 * mb, "quest")[0], "Poor")
        self.assertEqual(V.rank_for(41 * mb, "quest")[0], "Very Poor")

    def test_thresholds_match_the_quoted_source(self):
        # 逐語 "Texture Memory | 40 MB | 75 MB | 110 MB | 150 MB" / "10 MB | 18 MB | 25 MB | 40 MB"
        self.assertEqual([v for _n, v in V.THRESHOLDS["pc"]], [40, 75, 110, 150])
        self.assertEqual([v for _n, v in V.THRESHOLDS["quest"]], [10, 18, 25, 40])


# --- 通しで走らせる -----------------------------------------------------------

class TestEndToEnd(Tmp):
    def test_collect_walks_subfolders_and_skips_others(self):
        make_png(self.p("Textures/body.png"), 8, 8, 6)
        make_tga(self.p("Textures/deep/face.tga"), 8, 8)
        with open(self.p("Textures/readme.txt"), "w") as fh:
            fh.write("hi")
        found, failed = V.collect(self.dir)
        self.assertEqual(sorted(t.rel for t in found),
                         ["Textures/body.png", "Textures/deep/face.tga"])
        self.assertEqual(failed, [])

    def test_git_and_pycache_folders_are_not_walked(self):
        make_png(self.p("keep.png"), 8, 8, 6)
        make_png(self.p(".git/objects/blob.png"), 8, 8, 6)
        make_png(self.p("__pycache__/cached.png"), 8, 8, 6)
        found, _ = V.collect(self.dir)
        self.assertEqual([t.rel for t in found], ["keep.png"])

    def test_unreadable_file_lands_in_failed_not_in_found(self):
        make_png(self.p("ok.png"), 8, 8, 6)
        with open(self.p("bad.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        found, failed = V.collect(self.dir)
        self.assertEqual([t.rel for t in found], ["ok.png"])
        self.assertEqual([r for r, _w in failed], ["bad.png"])

    def test_duplicates_are_grouped_by_content(self):
        make_png(self.p("one.png"), 8, 8, 6)
        make_png(self.p("copy.png"), 8, 8, 6)
        make_png(self.p("other.png"), 16, 8, 6)
        found, _ = V.collect(self.dir)
        V.fill_digests(found)
        groups = V.duplicates(found)
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(t.rel for t in groups[0]), ["copy.png", "one.png"])

    def test_max_scan_pixels_leaves_big_png_unchecked(self):
        make_png(self.p("big.png"), 32, 32, 6, alpha_values=[255] * 1024)
        found, _ = V.collect(self.dir)
        V.scan_alpha(found, max_scan_pixels=16)
        self.assertIsNone(found[0].alpha_used)
        self.assertIn("too large to scan", found[0].note)

    def test_main_reports_the_unused_alpha(self):
        make_png(self.p("Textures/body.png"), 32, 16, 6, alpha_values=[255] * 512)
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            code = V.main([self.dir, "--top", "0"])
        finally:
            sys.stdout = old
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("alpha not used", text)
        self.assertIn("UNUSED", text)
        self.assertIn("Excellent", text)

    def test_every_report_is_pure_ascii(self):
        # 日本の Windows の既定のコンソールは cp932 で、U+2014 のような文字は
        # そこで印字に失敗する。この道具の読者の多くがその環境なので、
        # 報告に出る文字は ASCII に限る(注記・失敗の理由・見出しを含む)。
        make_png(self.p("t/body.png"), 32, 16, 6, alpha_values=[255] * 512)
        make_png(self.p("t/copy.png"), 32, 16, 6, alpha_values=[255] * 512)
        make_gif(self.p("t/x.gif"), 30, 10)
        make_psd(self.p("t/y.psd"), 8, 8, channels=2, color_mode=7)
        with open(self.p("t/bad.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        found, failed = V.collect(self.p("t"))
        V.scan_alpha(found, max_scan_pixels=64)
        V.fill_digests(found)
        for fmt in ("text", "tsv", "md"):
            # root は表示にしか使われないので、環境依存の一時パスを渡さない
            report = V.render(found, failed, "both", fmt, 0, 0.0, "fixtures")
            report.encode("ascii")   # ここで UnicodeEncodeError なら不合格

    def test_main_exits_2_on_empty_directory(self):
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            code = V.main([self.dir])
        finally:
            sys.stderr = old
        self.assertEqual(code, 2)
        self.assertIn("read no textures", err.getvalue())

    def test_main_exits_2_on_missing_directory(self):
        err, old = io.StringIO(), sys.stderr
        sys.stderr = err
        try:
            code = V.main([os.path.join(self.dir, "nope")])
        finally:
            sys.stderr = old
        self.assertEqual(code, 2)

    def test_max_mb_fails_the_run(self):
        make_png(self.p("t.png"), 256, 256, 6, alpha_values=[255] * 65536)
        out, err, o1, o2 = io.StringIO(), io.StringIO(), sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            code = V.main([self.dir, "--max-mb", "0.05"])
        finally:
            sys.stdout, sys.stderr = o1, o2
        self.assertEqual(code, 1)
        self.assertIn("exceeds --max-mb", err.getvalue())

    def test_max_mb_passes_when_under(self):
        make_png(self.p("t.png"), 16, 16, 6)
        out, o1 = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            code = V.main([self.dir, "--max-mb", "100"])
        finally:
            sys.stdout = o1
        self.assertEqual(code, 0)

    def test_tsv_has_one_header_and_one_row_per_texture(self):
        make_png(self.p("a.png"), 8, 8, 6)
        make_png(self.p("b.png"), 16, 8, 2)
        out, o1 = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            V.main([self.dir, "--format", "tsv"])
        finally:
            sys.stdout = o1
        rows = [r for r in out.getvalue().splitlines() if r.strip()]
        self.assertTrue(rows[0].startswith("file\tformat"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(rows[1].split("\t")), len(rows[0].split("\t")))

    def test_markdown_table(self):
        make_png(self.p("a.png"), 8, 8, 6)
        out, o1 = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            V.main([self.dir, "--format", "md"])
        finally:
            sys.stdout = o1
        self.assertIn("| `a.png` |", out.getvalue())

    def test_no_alpha_scan_skips_the_decode(self):
        make_png(self.p("a.png"), 16, 16, 6, alpha_values=[255] * 256)
        out, o1 = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            V.main([self.dir, "--no-alpha-scan"])
        finally:
            sys.stdout = o1
        self.assertNotIn("alpha not used", out.getvalue())

    def test_report_says_the_number_is_not_vrchats(self):
        make_png(self.p("a.png"), 8, 8, 6)
        out, o1 = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            V.main([self.dir])
        finally:
            sys.stdout = o1
        self.assertIn("not the number VRChat shows", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
