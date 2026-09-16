#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tile_seam.py.

    python -m unittest test_tile_seam -v

Every PNG used here is built byte by byte in this file, so the suite has no fixtures and no
dependencies. The interesting half is not the decoder - it is the pair of tests that pin the
mistake this tool exists because of: a checkerboard is seamless and a gradient is not, and a
fixed threshold on the raw wrap step gets both of them wrong.
"""
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tile_seam as ts  # noqa: E402


# --- building PNGs by hand ----------------------------------------------------

def paeth_ref(a, b, c):
    """A second, independent Paeth predictor.

    The encoder below must not call the tool's own `_paeth`: if it did, breaking the tool's
    predictor would break the encoder the same way and the round trip would still pass.
    This is written straight from RFC 2083 section 6.6.
    """
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    else:
        return c


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def png_bytes(width, height, rows, ctype=6, depth=8, palette=None, trns=None,
              filter_type=0, interlace=0, split_idat=False):
    """`rows` is a list of already-packed scanline byte strings, unfiltered."""
    ihdr = struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, interlace)
    out = [ts.PNG_SIG, chunk(b"IHDR", ihdr)]
    if palette is not None:
        out.append(chunk(b"PLTE", palette))
    if trns is not None:
        out.append(chunk(b"tRNS", trns))
    stride = len(rows[0]) if rows else 0
    raw = bytearray()
    prev = bytes(stride)
    bpp = max(1, ({0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype] * depth + 7) // 8)
    for line in rows:
        raw.append(filter_type)
        if filter_type == 0:
            raw += line
        elif filter_type == 1:
            enc = bytearray(line)
            for i in range(len(line) - 1, bpp - 1, -1):
                enc[i] = (line[i] - line[i - bpp]) & 0xFF
            raw += enc
        elif filter_type == 2:
            raw += bytes((line[i] - prev[i]) & 0xFF for i in range(stride))
        elif filter_type == 3:
            enc = bytearray(stride)
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                enc[i] = (line[i] - ((left + prev[i]) >> 1)) & 0xFF
            raw += enc
        elif filter_type == 4:
            enc = bytearray(stride)
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                enc[i] = (line[i] - paeth_ref(a, b, c)) & 0xFF
            raw += enc
        prev = bytes(line)
    comp = zlib.compress(bytes(raw))
    if split_idat:
        half = len(comp) // 2
        out.append(chunk(b"IDAT", comp[:half]))
        out.append(chunk(b"IDAT", comp[half:]))
    else:
        out.append(chunk(b"IDAT", comp))
    out.append(chunk(b"IEND", b""))
    return b"".join(out)


def gray_rows(width, height, fn, depth=8):
    """fn(x, y) -> 0..255."""
    if depth == 8:
        return [bytes(fn(x, y) & 0xFF for x in range(width)) for y in range(height)]
    if depth == 16:
        return [b"".join(struct.pack(">H", (fn(x, y) & 0xFF) * 257) for x in range(width))
                for y in range(height)]
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    rows = []
    for y in range(height):
        acc = bytearray()
        byte = 0
        filled = 0
        for x in range(width):
            byte = (byte << depth) | (fn(x, y) & mask)
            filled += 1
            if filled == per_byte:
                acc.append(byte)
                byte = 0
                filled = 0
        if filled:
            acc.append(byte << (depth * (per_byte - filled)))
        rows.append(bytes(acc))
    return rows


def rgba_rows(width, height, fn):
    """fn(x, y) -> (r, g, b, a)."""
    return [b"".join(bytes(fn(x, y)) for x in range(width)) for y in range(height)]


# --- the pictures the tests argue about ---------------------------------------

def checker(x, y, cell=8):
    """Hard edges everywhere, and perfectly periodic: seamless despite the contrast."""
    return 235 if ((x // cell) + (y // cell)) % 2 == 0 else 20


def gradient(x, y, width=64):
    """Smooth everywhere and discontinuous only at the wrap: the textbook seam."""
    return int(255 * x / (width - 1))


def sine_tile(x, y, width=64, height=64):
    """Continuous and exactly periodic in both axes: seamless, with no hard edges at all."""
    v = 0.5 + 0.25 * math.sin(2 * math.pi * 2 * x / width) + 0.25 * math.sin(2 * math.pi * 3 * y / height)
    return int(255 * v)


def write(tmp, name, data):
    p = Path(tmp) / name
    p.write_bytes(data)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tile-seam-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def img(self, name, data):
        return write(self.tmp, name, data)

    def verdict(self, data, name="a.png"):
        return ts.analyse(ts.read_png(self.img(name, data)))


# --- 1. the decoder -----------------------------------------------------------

class TestDecoder(Base):
    def test_rgba8_round_trip(self):
        rows = rgba_rows(4, 3, lambda x, y: (x * 10, y * 20, 7, 255))
        im = ts.read_png(self.img("a.png", png_bytes(4, 3, rows)))
        self.assertEqual((im.width, im.height), (4, 3))
        self.assertEqual(len(im.planes), 4)
        self.assertEqual(im.planes[0], bytes([0, 10, 20, 30] * 3))
        self.assertEqual(im.planes[1], bytes([0] * 4 + [20] * 4 + [40] * 4))

    def test_channel_names_follow_the_channel_count(self):
        im = ts.read_png(self.img("a.png", png_bytes(4, 3, rgba_rows(4, 3, lambda x, y: (1, 2, 3, 4)))))
        self.assertEqual(list(im.names), ["r", "g", "b", "alpha"])

    def test_grayscale_is_one_plane(self):
        rows = gray_rows(4, 2, lambda x, y: x * 3)
        im = ts.read_png(self.img("a.png", png_bytes(4, 2, rows, ctype=0)))
        self.assertEqual(len(im.planes), 1)
        self.assertEqual(im.planes[0], bytes([0, 3, 6, 9, 0, 3, 6, 9]))
        self.assertEqual(list(im.names), ["gray"])

    def test_gray_alpha_is_two_planes(self):
        rows = [b"".join(bytes([x * 5, 128]) for x in range(4)) for _ in range(2)]
        im = ts.read_png(self.img("a.png", png_bytes(4, 2, rows, ctype=4)))
        self.assertEqual(len(im.planes), 2)
        self.assertEqual(im.planes[1], bytes([128] * 8))

    def test_rgb8_is_three_planes(self):
        rows = [b"".join(bytes([x, 9, 200]) for x in range(4)) for _ in range(2)]
        im = ts.read_png(self.img("a.png", png_bytes(4, 2, rows, ctype=2)))
        self.assertEqual(len(im.planes), 3)
        self.assertEqual(im.planes[2], bytes([200] * 8))

    def test_16_bit_keeps_the_high_byte(self):
        rows = gray_rows(4, 2, lambda x, y: x * 40, depth=16)
        im = ts.read_png(self.img("a.png", png_bytes(4, 2, rows, ctype=0, depth=16)))
        self.assertEqual(im.planes[0][:4], bytes([0, 40, 80, 120]))

    def test_depth_1_scales_to_full_range(self):
        rows = gray_rows(8, 1, lambda x, y: x % 2, depth=1)
        im = ts.read_png(self.img("a.png", png_bytes(8, 1, rows, ctype=0, depth=1)))
        self.assertEqual(im.planes[0], bytes([0, 255] * 4))

    def test_depth_2_scales_to_full_range(self):
        rows = gray_rows(4, 1, lambda x, y: x, depth=2)
        im = ts.read_png(self.img("a.png", png_bytes(4, 1, rows, ctype=0, depth=2)))
        self.assertEqual(im.planes[0], bytes([0, 85, 170, 255]))

    def test_depth_4_scales_to_full_range(self):
        rows = gray_rows(4, 1, lambda x, y: x * 5, depth=4)
        im = ts.read_png(self.img("a.png", png_bytes(4, 1, rows, ctype=0, depth=4)))
        self.assertEqual(im.planes[0], bytes([0, 85, 170, 255]))

    def test_low_depth_row_that_does_not_fill_the_last_byte(self):
        rows = gray_rows(3, 1, lambda x, y: x % 2, depth=1)   # 3 pixels in an 8-bit byte
        im = ts.read_png(self.img("a.png", png_bytes(3, 1, rows, ctype=0, depth=1)))
        self.assertEqual(im.planes[0], bytes([0, 255, 0]))

    def test_palette_expands_to_rgb(self):
        pal = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        rows = gray_rows(3, 1, lambda x, y: x, depth=8)
        im = ts.read_png(self.img("a.png", png_bytes(3, 1, rows, ctype=3, palette=pal)))
        self.assertEqual(len(im.planes), 3)
        self.assertEqual(im.planes[0], bytes([255, 0, 0]))
        self.assertEqual(im.planes[1], bytes([0, 255, 0]))

    def test_palette_with_trns_gains_an_alpha_plane(self):
        pal = bytes([255, 0, 0, 0, 255, 0])
        rows = gray_rows(2, 1, lambda x, y: x, depth=8)
        im = ts.read_png(self.img("a.png", png_bytes(2, 1, rows, ctype=3, palette=pal, trns=bytes([0, 255]))))
        self.assertEqual(len(im.planes), 4)
        self.assertEqual(im.planes[3], bytes([0, 255]))

    def test_palette_at_low_depth_indexes_correctly(self):
        pal = bytes([10, 10, 10, 20, 20, 20, 30, 30, 30, 40, 40, 40])
        rows = gray_rows(4, 1, lambda x, y: x, depth=2)
        im = ts.read_png(self.img("a.png", png_bytes(4, 1, rows, ctype=3, depth=2, palette=pal)))
        self.assertEqual(im.planes[0], bytes([10, 20, 30, 40]))

    def test_palette_index_past_the_end_is_an_error(self):
        pal = bytes([1, 2, 3])
        rows = gray_rows(2, 1, lambda x, y: x, depth=8)
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", png_bytes(2, 1, rows, ctype=3, palette=pal)))

    def test_palette_without_plte_is_an_error(self):
        rows = gray_rows(2, 1, lambda x, y: 0, depth=8)
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", png_bytes(2, 1, rows, ctype=3)))

    def test_every_scanline_filter_decodes_to_the_same_pixels(self):
        rows = rgba_rows(6, 5, lambda x, y: (x * 9, y * 11, (x * y) % 251, 255))
        want = ts.read_png(self.img("f0.png", png_bytes(6, 5, rows, filter_type=0))).planes
        for ft in (1, 2, 3, 4):
            got = ts.read_png(self.img("f%d.png" % ft, png_bytes(6, 5, rows, filter_type=ft))).planes
            self.assertEqual(got, want, "filter %d decoded differently" % ft)

    def test_the_paeth_predictor_agrees_with_the_rfc_on_a_grid_of_triples(self):
        for a in range(0, 256, 17):
            for b in range(0, 256, 13):
                for c in range(0, 256, 11):
                    self.assertEqual(ts._paeth(a, b, c), paeth_ref(a, b, c), (a, b, c))

    def test_image_data_split_across_two_idat_chunks(self):
        rows = rgba_rows(5, 4, lambda x, y: (x, y, 0, 255))
        one = ts.read_png(self.img("a.png", png_bytes(5, 4, rows))).planes
        two = ts.read_png(self.img("b.png", png_bytes(5, 4, rows, split_idat=True))).planes
        self.assertEqual(one, two)

    def test_not_a_png(self):
        p = Path(self.tmp) / "a.png"
        p.write_bytes(b"GIF89a and then some")
        with self.assertRaises(ts.PngError):
            ts.read_png(p)

    def test_interlaced_is_refused_by_name(self):
        rows = rgba_rows(4, 4, lambda x, y: (1, 2, 3, 4))
        with self.assertRaises(ts.PngError) as cm:
            ts.read_png(self.img("a.png", png_bytes(4, 4, rows, interlace=1)))
        self.assertIn("interlac", str(cm.exception).lower())

    def test_truncated_file_does_not_crash(self):
        data = png_bytes(4, 4, rgba_rows(4, 4, lambda x, y: (1, 2, 3, 4)))
        p = Path(self.tmp) / "a.png"
        p.write_bytes(data[:len(data) // 2])
        with self.assertRaises(ts.PngError):
            ts.read_png(p)

    def test_corrupt_image_data_is_an_error_not_a_traceback(self):
        parts = [ts.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)),
                 chunk(b"IDAT", b"not zlib at all"), chunk(b"IEND", b"")]
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", b"".join(parts)))

    def test_missing_idat_is_an_error(self):
        parts = [ts.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)),
                 chunk(b"IEND", b"")]
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", b"".join(parts)))

    def test_zero_sized_image_is_an_error(self):
        parts = [ts.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", 0, 4, 8, 6, 0, 0, 0)),
                 chunk(b"IDAT", zlib.compress(b"")), chunk(b"IEND", b"")]
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", b"".join(parts)))

    def test_unknown_colour_type_is_an_error(self):
        parts = [ts.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 5, 0, 0, 0)),
                 chunk(b"IDAT", zlib.compress(b"\x00\x00\x00")), chunk(b"IEND", b"")]
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", b"".join(parts)))

    def test_unknown_scanline_filter_is_an_error(self):
        raw = bytes([9]) + bytes(8) + bytes([0]) + bytes(8)
        parts = [ts.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)),
                 chunk(b"IDAT", zlib.compress(raw)), chunk(b"IEND", b"")]
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", b"".join(parts)))

    def test_chunk_length_past_the_end_is_an_error(self):
        body = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
        bad = struct.pack(">I", 999) + b"IHDR" + body + struct.pack(">I", 0)
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", ts.PNG_SIG + bad))

    def test_unsupported_bit_depth_for_rgb(self):
        parts = [ts.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 4, 2, 0, 0, 0)),
                 chunk(b"IDAT", zlib.compress(b"\x00\x00\x00")), chunk(b"IEND", b"")]
        with self.assertRaises(ts.PngError):
            ts.read_png(self.img("a.png", b"".join(parts)))


# --- 2. the measurement -------------------------------------------------------

class TestSteps(Base):
    def test_column_steps_counts_every_adjacent_pair(self):
        plane = bytes([0, 10, 20, 30] * 2)
        wrap, steps = ts.column_steps(plane, 4, 2)
        self.assertEqual(steps, [10.0, 10.0, 10.0])
        self.assertEqual(wrap, 30.0)

    def test_column_wrap_compares_last_column_to_first(self):
        plane = bytes([5, 1, 1, 9, 5, 1, 1, 9])
        wrap, _ = ts.column_steps(plane, 4, 2)
        self.assertEqual(wrap, 4.0)

    def test_row_steps_counts_every_adjacent_pair(self):
        plane = bytes([0, 0, 8, 8, 16, 16])
        wrap, steps = ts.row_steps(plane, 2, 3)
        self.assertEqual(steps, [8.0, 8.0])
        self.assertEqual(wrap, 16.0)

    def test_one_pixel_wide_has_no_column_steps(self):
        self.assertIsNone(ts.column_steps(bytes([1, 2, 3]), 1, 3))

    def test_one_pixel_tall_has_no_row_steps(self):
        self.assertIsNone(ts.row_steps(bytes([1, 2, 3]), 3, 1))

    def test_median_of_even_count_is_the_average_of_the_middle_two(self):
        self.assertEqual(ts._median([1, 2, 3, 10]), 2.5)

    def test_median_of_odd_count(self):
        self.assertEqual(ts._median([5, 1, 3]), 3)


class TestJudge(unittest.TestCase):
    def test_a_wrap_worse_than_every_neighbour_step_is_a_seam(self):
        v, ratio, rank = ts.judge(50.0, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(v, ts.SEAM)
        self.assertEqual(rank, 1.0)
        self.assertAlmostEqual(ratio, 20.0)

    def test_a_wrap_inside_the_distribution_is_ok_however_large(self):
        v, _, _ = ts.judge(200.0, [10.0, 215.0, 4.0, 220.0])
        self.assertEqual(v, ts.OK)

    def test_a_wrap_above_the_99th_percentile_but_not_the_worst_is_suspect(self):
        steps = [1.0] * 199 + [100.0]
        v, _, _ = ts.judge(99.0, steps)
        self.assertEqual(v, ts.SUSPECT)

    def test_strict_moves_the_suspect_line_down(self):
        steps = [1.0] * 94 + [100.0] * 6
        self.assertEqual(ts.judge(99.0, steps)[0], ts.OK)
        self.assertEqual(ts.judge(99.0, steps, suspect_rank=0.90)[0], ts.SUSPECT)

    def test_a_perfect_wrap_is_ok_even_in_a_flat_image(self):
        v, ratio, _ = ts.judge(0.0, [0.0, 0.0, 0.0])
        self.assertEqual(v, ts.OK)
        self.assertEqual(ratio, 0.0)

    def test_any_wrap_at_all_in_a_flat_image_is_a_seam_with_an_infinite_ratio(self):
        v, ratio, _ = ts.judge(3.0, [0.0, 0.0, 0.0])
        self.assertEqual(v, ts.SEAM)
        self.assertEqual(ratio, float("inf"))

    def test_rank_counts_only_steps_strictly_below_the_wrap(self):
        _, _, rank = ts.judge(5.0, [5.0, 5.0, 1.0, 1.0])
        self.assertEqual(rank, 0.5)


# --- 3. the argument the tool exists to settle --------------------------------

class TestPictures(Base):
    def test_a_checkerboard_tiles_even_though_its_edges_are_brutal(self):
        rows = gray_rows(64, 64, checker)
        r = self.verdict(png_bytes(64, 64, rows, ctype=0))
        self.assertEqual(r["overall"], ts.OK)

    def test_a_fixed_threshold_calls_that_same_checkerboard_broken(self):
        rows = gray_rows(64, 64, checker)
        r = self.verdict(png_bytes(64, 64, rows, ctype=0))
        self.assertEqual(ts.naive_verdict(r), ts.SEAM)     # this is the bug we shipped

    def test_a_horizontal_gradient_seams_on_x_only(self):
        rows = gray_rows(64, 64, lambda x, y: gradient(x, y, 64))
        r = self.verdict(png_bytes(64, 64, rows, ctype=0))
        self.assertEqual(r["x"]["verdict"], ts.SEAM)
        self.assertEqual(r["y"]["verdict"], ts.OK)
        self.assertEqual(r["overall"], ts.SEAM)

    def test_a_vertical_gradient_seams_on_y_only(self):
        rows = gray_rows(64, 64, lambda x, y: gradient(y, x, 64))
        r = self.verdict(png_bytes(64, 64, rows, ctype=0))
        self.assertEqual(r["y"]["verdict"], ts.SEAM)
        self.assertEqual(r["x"]["verdict"], ts.OK)
        self.assertEqual(r["overall"], ts.SEAM)     # a seam on either axis is a seam

    def test_a_smooth_periodic_tile_is_ok_on_both_axes(self):
        rows = gray_rows(64, 64, sine_tile)
        r = self.verdict(png_bytes(64, 64, rows, ctype=0))
        self.assertEqual(r["overall"], ts.OK)

    def test_a_flat_colour_is_ok(self):
        rows = gray_rows(16, 16, lambda x, y: 128)
        self.assertEqual(self.verdict(png_bytes(16, 16, rows, ctype=0))["overall"], ts.OK)

    def test_a_seam_only_in_the_alpha_channel_is_still_found(self):
        def px(x, y):
            return (128, 128, 128, int(255 * x / 63))
        rows = rgba_rows(64, 64, px)
        r = self.verdict(png_bytes(64, 64, rows))
        self.assertEqual(r["x"]["verdict"], ts.SEAM)
        self.assertEqual(r["x"]["channel"], "alpha")

    def test_two_tone_halves_are_not_a_seam_because_the_wrap_matches_an_interior_edge(self):
        # Tiled, this image is a stripe pattern: the wrap edge is indistinguishable from the
        # edge already inside it. Calling that a seam is the false positive the tool avoids.
        def px(x, y):
            return (255, 255, 255, 255) if x < 32 else (0, 0, 0, 0)
        r = self.verdict(png_bytes(64, 64, rgba_rows(64, 64, px)))
        self.assertEqual(r["x"]["verdict"], ts.OK)
        self.assertEqual(ts.naive_verdict(r), ts.SEAM)

    def test_a_seam_only_in_the_blue_channel_is_still_found(self):
        def px(x, y):
            return (100, 100, int(255 * x / 63), 255)
        rows = rgba_rows(64, 64, px)
        r = self.verdict(png_bytes(64, 64, rows))
        self.assertEqual(r["x"]["channel"], "b")
        self.assertEqual(r["x"]["verdict"], ts.SEAM)

    def test_the_worst_channel_wins_not_the_first(self):
        def px(x, y):
            return (checker(x, y), checker(x, y), int(255 * x / 63), 255)
        r = self.verdict(png_bytes(64, 64, rgba_rows(64, 64, px)))
        self.assertEqual(r["x"]["channel"], "b")

    def test_the_gradient_and_the_checkerboard_disagree_with_the_naive_test_both_ways(self):
        g = self.verdict(png_bytes(64, 64, gray_rows(64, 64, lambda x, y: gradient(x, y, 64)), ctype=0), "g.png")
        c = self.verdict(png_bytes(64, 64, gray_rows(64, 64, checker), ctype=0), "c.png")
        self.assertEqual((g["overall"], c["overall"]), (ts.SEAM, ts.OK))
        self.assertEqual((ts.naive_verdict(g), ts.naive_verdict(c)), (ts.SEAM, ts.SEAM))

    def test_a_one_pixel_wide_strip_reports_n_a_for_x(self):
        rows = gray_rows(1, 8, lambda x, y: y * 30)
        r = self.verdict(png_bytes(1, 8, rows, ctype=0))
        self.assertIsNone(r["x"])
        self.assertIsNotNone(r["y"])

    def test_a_single_pixel_has_no_axes_and_no_seam(self):
        rows = gray_rows(1, 1, lambda x, y: 200)
        r = self.verdict(png_bytes(1, 1, rows, ctype=0))
        self.assertIsNone(r["x"])
        self.assertIsNone(r["y"])
        self.assertEqual(r["overall"], ts.OK)


# --- 4. walking and printing --------------------------------------------------

class TestCollect(Base):
    def test_a_folder_is_walked_recursively_for_png_only(self):
        (Path(self.tmp) / "sub").mkdir()
        self.img("a.png", png_bytes(2, 2, rgba_rows(2, 2, lambda x, y: (1, 2, 3, 4))))
        (Path(self.tmp) / "sub" / "b.PNG").write_bytes(
            png_bytes(2, 2, rgba_rows(2, 2, lambda x, y: (1, 2, 3, 4))))
        (Path(self.tmp) / "notes.txt").write_text("hello", encoding="utf-8")
        got = ts.collect([self.tmp])
        self.assertEqual(len(got), 2)
        self.assertTrue(all(w is None for _, w in got))

    def test_the_same_file_named_twice_is_scanned_once(self):
        p = self.img("a.png", png_bytes(2, 2, rgba_rows(2, 2, lambda x, y: (1, 2, 3, 4))))
        self.assertEqual(len(ts.collect([str(p), str(p)])), 1)

    def test_a_missing_path_is_reported_not_raised(self):
        got = ts.collect([os.path.join(self.tmp, "nope.png")])
        self.assertEqual(len(got), 1)
        self.assertIsNotNone(got[0][1])


class TestCli(Base):
    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ts.main(argv)
        return code, buf.getvalue()

    def test_exit_0_when_nothing_seams(self):
        self.img("a.png", png_bytes(64, 64, gray_rows(64, 64, checker), ctype=0))
        code, out = self.run_cli([self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("1 PNG", out)

    def test_exit_1_when_something_seams(self):
        self.img("a.png", png_bytes(64, 64, gray_rows(64, 64, lambda x, y: gradient(x, y, 64)), ctype=0))
        code, out = self.run_cli([self.tmp])
        self.assertEqual(code, 1)
        self.assertIn("seam", out)

    def test_exit_2_when_there_was_nothing_to_read(self):
        code, out = self.run_cli([self.tmp])
        self.assertEqual(code, 2)

    def test_a_broken_file_is_listed_and_the_others_still_run(self):
        self.img("good.png", png_bytes(64, 64, gray_rows(64, 64, checker), ctype=0))
        (Path(self.tmp) / "bad.png").write_bytes(b"nope")
        code, out = self.run_cli([self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("could not be read", out)
        self.assertIn("bad.png", out)

    def test_tsv_has_one_row_per_axis_and_a_header(self):
        self.img("a.png", png_bytes(32, 32, gray_rows(32, 32, checker), ctype=0))
        code, out = self.run_cli([self.tmp, "--tsv"])
        lines = [l for l in out.strip().splitlines() if l]
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("file\twidth\theight\taxis"))
        self.assertEqual(lines[1].split("\t")[3], "x")
        self.assertEqual(lines[2].split("\t")[3], "y")

    def test_naive_prints_the_comparison_line(self):
        self.img("a.png", png_bytes(64, 64, gray_rows(64, 64, checker), ctype=0))
        _, out = self.run_cli([self.tmp, "--naive"])
        self.assertIn("fixed threshold", out)
        self.assertIn("1 of which this tool calls ok", out)

    def test_without_naive_the_comparison_line_is_absent(self):
        self.img("a.png", png_bytes(64, 64, gray_rows(64, 64, checker), ctype=0))
        _, out = self.run_cli([self.tmp])
        self.assertNotIn("fixed threshold", out)

    def test_strict_changes_the_verdict_it_prints(self):
        def px(x, y):
            return 40 if x in (20, 21) else (0 if x < 32 else 6)
        self.img("a.png", png_bytes(64, 64, gray_rows(64, 64, px), ctype=0))
        _, loose = self.run_cli([self.tmp])
        _, strict = self.run_cli([self.tmp, "--strict"])
        self.assertNotEqual(loose, strict)

    def test_the_summary_counts_add_up(self):
        self.img("ok.png", png_bytes(64, 64, gray_rows(64, 64, checker), ctype=0))
        self.img("bad.png", png_bytes(64, 64, gray_rows(64, 64, lambda x, y: gradient(x, y, 64)), ctype=0))
        _, out = self.run_cli([self.tmp])
        self.assertIn("1 seam, 0 suspect, 1 ok", out)

    def test_it_runs_as_a_script(self):
        self.img("a.png", png_bytes(32, 32, gray_rows(32, 32, checker), ctype=0))
        r = subprocess.run([sys.executable, str(HERE / "tile_seam.py"), self.tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
