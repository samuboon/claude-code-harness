#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for normal_y_check.py.   python -m unittest test_normal_y_check -v

Every map here is built from a height field whose answer we know, by one of four methods
that do not share code with the tool: central differences, a Sobel filter, forward
differences, and exact analytic normals. The PNG writer below carries its own filters,
including its own Paeth predictor written from RFC 2083 section 6.6, so breaking the tool's
decoder cannot break the encoder the same way.
"""
import contextlib
import io
import math
import os
import random
import shutil
import struct
import tempfile
import unittest
import zlib

import normal_y_check as nyc

N = 96


# ---------------------------------------------------------------- an independent PNG writer

def _rfc_paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    return c


def write_png(path, w, h, pixels, channels=3, depth=8, filter_type=0):
    """pixels: flat list of samples (0..255 or 0..65535), `channels` per pixel."""
    ctype = {3: 2, 4: 6, 1: 0}[channels]
    bps = 2 if depth == 16 else 1
    bpp = channels * bps
    stride = w * bpp
    raw = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        line = bytearray()
        for s in pixels[y * w * channels:(y + 1) * w * channels]:
            line += struct.pack(">H", s) if bps == 2 else bytes([s])
        out = bytearray(stride)
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            v = line[x]
            if filter_type == 0:
                out[x] = v
            elif filter_type == 1:
                out[x] = (v - a) % 256
            elif filter_type == 2:
                out[x] = (v - b) % 256
            elif filter_type == 3:
                out[x] = (v - (a + b) // 2) % 256
            else:
                out[x] = (v - _rfc_paeth(a, b, c)) % 256
        raw.append(filter_type)
        raw += out
        prev = line

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- height fields and maps

def height_bumps(n):
    """Round bumps plus a product of sines: relief that bends in both directions."""
    rnd = random.Random(7)
    centres = [(rnd.uniform(0.1, 0.9) * n, rnd.uniform(0.1, 0.9) * n, rnd.uniform(3, 9) * n / 96.0)
               for _ in range(9)]
    out = []
    for y in range(n):
        for x in range(n):
            v = 0.0
            for cx, cy, r in centres:
                v += math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r))
            v += 0.3 * math.sin(2 * math.pi * 3 * x / n) * math.sin(2 * math.pi * 2 * y / n)
            out.append(v)
    return out


def encode(nx, ny, nz, maxval=255):
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    return [int((c / ln * 0.5 + 0.5) * maxval + 0.5) for c in (nx, ny, nz)]


def map_central(hf, n, strength, green=+1, maxval=255, sx=1.0, sy=1.0):
    """Y+ when green=+1: ny carries (below - above), as a Y+ baker writes it."""
    px = []
    for y in range(n):
        for x in range(n):
            l = hf[y * n + max(0, x - 1)]
            r = hf[y * n + min(n - 1, x + 1)]
            u = hf[max(0, y - 1) * n + x]
            d = hf[min(n - 1, y + 1) * n + x]
            px += encode((l - r) * 0.5 * strength * sx, (d - u) * 0.5 * strength * sy * green, 1.0, maxval)
    return px


def map_sobel(hf, n, strength, green=+1):
    def H(x, y):
        return hf[min(n - 1, max(0, y)) * n + min(n - 1, max(0, x))]
    px = []
    for y in range(n):
        for x in range(n):
            gx = (H(x + 1, y - 1) + 2 * H(x + 1, y) + H(x + 1, y + 1)
                  - H(x - 1, y - 1) - 2 * H(x - 1, y) - H(x - 1, y + 1)) / 8.0
            gy = (H(x - 1, y + 1) + 2 * H(x, y + 1) + H(x + 1, y + 1)
                  - H(x - 1, y - 1) - 2 * H(x, y - 1) - H(x + 1, y - 1)) / 8.0
            px += encode(-gx * strength, gy * strength * green, 1.0)
    return px


def map_forward(hf, n, strength, green=+1):
    px = []
    for y in range(n):
        for x in range(n):
            c = hf[y * n + x]
            r = hf[y * n + min(n - 1, x + 1)]
            d = hf[min(n - 1, y + 1) * n + x]
            px += encode(-(r - c) * strength, (d - c) * strength * green, 1.0)
    return px


def map_analytic(n, green=+1):
    """Exact surface normals of h = A sin(kx x) sin(ky y) + a dome; no finite differences."""
    A, kx, ky = 6.0, 2 * math.pi * 3 / n, 2 * math.pi * 2 / n
    px = []
    for y in range(n):
        for x in range(n):
            dhdx = A * kx * math.cos(kx * x) * math.sin(ky * y)
            dhdy = A * ky * math.sin(kx * x) * math.cos(ky * y)
            fx, fy = x - n / 2.0, y - n / 2.0
            dhdx += -0.004 * 2 * fx * 0.5
            dhdy += -0.004 * 2 * fy * 0.5
            # image y runs down, so the Y+ green is +dh/dy(image)
            px += encode(-dhdx, dhdy * green, 1.0)
    return px


def flip_green(px, channels=3, maxval=255):
    out = list(px)
    for i in range(1, len(out), channels):
        out[i] = maxval - out[i]
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nyc_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, name, px, n=N, **kw):
        p = os.path.join(self.tmp, name)
        write_png(p, n, n, px, **kw)
        return p

    def verdict_of(self, px, **kw):
        return nyc.check_file(self.save("m.png", px, **kw))


class TestDecides(Base):
    hf = height_bumps(N)

    def test_central_yplus(self):
        self.assertEqual(self.verdict_of(map_central(self.hf, N, 8.0))["verdict"], nyc.Y_PLUS)

    def test_central_yminus(self):
        self.assertEqual(self.verdict_of(map_central(self.hf, N, 8.0, green=-1))["verdict"], nyc.Y_MINUS)

    def test_sobel_both_ways(self):
        self.assertEqual(self.verdict_of(map_sobel(self.hf, N, 8.0))["verdict"], nyc.Y_PLUS)
        self.assertEqual(self.verdict_of(map_sobel(self.hf, N, 8.0, green=-1))["verdict"], nyc.Y_MINUS)

    def test_forward_difference_both_ways(self):
        self.assertEqual(self.verdict_of(map_forward(self.hf, N, 8.0))["verdict"], nyc.Y_PLUS)
        self.assertEqual(self.verdict_of(map_forward(self.hf, N, 8.0, green=-1))["verdict"], nyc.Y_MINUS)

    def test_analytic_normals_both_ways(self):
        self.assertEqual(self.verdict_of(map_analytic(N))["verdict"], nyc.Y_PLUS)
        self.assertEqual(self.verdict_of(map_analytic(N, green=-1))["verdict"], nyc.Y_MINUS)

    def test_flipping_green_flips_the_answer(self):
        """The exact transform of our own shipped mistake: green -> 255 - green."""
        px = map_central(self.hf, N, 8.0)
        self.assertEqual(self.verdict_of(flip_green(px))["verdict"], nyc.Y_MINUS)

    def test_unequal_axis_scales(self):
        """Non-square texels or a baker that scales X and Y differently: the sign still holds."""
        r = self.verdict_of(map_central(self.hf, N, 8.0, sx=3.0, sy=0.4))
        self.assertEqual(r["verdict"], nyc.Y_PLUS)
        self.assertGreater(r["agreement"], 0.9)

    def test_right_reading_has_less_curl(self):
        r = self.verdict_of(map_central(self.hf, N, 8.0))
        self.assertLess(r["curl_yplus"], 0.2)
        self.assertGreater(r["curl_yminus"], 1.8)
        r = self.verdict_of(map_central(self.hf, N, 8.0, green=-1))
        self.assertLess(r["curl_yminus"], 0.2)
        self.assertGreater(r["curl_yplus"], 1.8)

    def test_survives_added_noise(self):
        rnd = random.Random(3)
        px = [min(255, max(0, v + rnd.randint(-3, 3))) for v in map_central(self.hf, N, 8.0)]
        self.assertEqual(self.verdict_of(px)["verdict"], nyc.Y_PLUS)

    def test_never_wrong_across_strengths(self):
        """Weak maps may come back undecided; no strength may produce the wrong answer."""
        decided = 0
        for s in (0.05, 0.2, 0.5, 1, 2, 4, 8, 16, 40, 100):
            for green, want in ((+1, nyc.Y_PLUS), (-1, nyc.Y_MINUS)):
                v = self.verdict_of(map_central(self.hf, N, s, green=green))["verdict"]
                self.assertIn(v, (want, nyc.UNDECIDED), "strength %s green %d" % (s, green))
                decided += v == want
        self.assertGreaterEqual(decided, 14)


class TestRefuses(Base):
    def test_flat_map_is_undecided(self):
        r = self.verdict_of([128, 128, 255] * (N * N))
        self.assertEqual(r["verdict"], nyc.UNDECIDED)
        self.assertIn("bends both ways", r["reason"])

    def test_vertical_stripes_are_undecided(self):
        hf = [1.0 if (x // 8) % 2 else 0.0 for y in range(N) for x in range(N)]
        r = self.verdict_of(map_central(hf, N, 4.0))
        self.assertEqual(r["verdict"], nyc.UNDECIDED)

    def test_horizontal_stripes_are_undecided(self):
        hf = [math.sin(y / 3.0) for y in range(N) for x in range(N)]
        self.assertEqual(self.verdict_of(map_central(hf, N, 8.0))["verdict"], nyc.UNDECIDED)

    def test_diagonal_stripes_are_decided(self):
        """h = f(x + y) does bend both ways; it must not be lumped in with axis stripes."""
        hf = [math.sin((x + y) / 4.0) for y in range(N) for x in range(N)]
        self.assertEqual(self.verdict_of(map_central(hf, N, 8.0))["verdict"], nyc.Y_PLUS)
        self.assertEqual(self.verdict_of(map_central(hf, N, 8.0, green=-1))["verdict"], nyc.Y_MINUS)

    def test_pure_noise_is_undecided(self):
        for seed in range(6):
            rnd = random.Random(seed)
            px = []
            for _ in range(N * N):
                px += encode(rnd.uniform(-0.4, 0.4), rnd.uniform(-0.4, 0.4), 1.0)
            r = self.verdict_of(px)
            self.assertEqual(r["verdict"], nyc.UNDECIDED, "seed %d z %.2f" % (seed, r["z"]))

    def test_rounding_only_is_undecided(self):
        """Relief so faint that 8-bit rounding is all that is left."""
        hf = height_bumps(N)
        r = self.verdict_of(map_central(hf, N, 0.02))
        self.assertEqual(r["verdict"], nyc.UNDECIDED)

    def test_not_a_normal_map(self):
        """A colour texture: most pixels decode to a normal pointing down."""
        px = [200, 40, 30] * (N * N)
        r = self.verdict_of(px)
        self.assertEqual(r["verdict"], nyc.UNDECIDED)
        self.assertIn("upward-facing", r["reason"])

    def test_small_noisy_patches_never_get_a_verdict(self):
        """Few pixels make chance agreement easy; the significance floor has to hold it back.
        (Added after mutation_check showed the agreement floor alone let this through.)"""
        decided = []
        for seed in range(60):
            rnd = random.Random(1000 + seed)
            px = []
            for _ in range(8 * 8):
                px += encode(rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5), 1.0)
            r = nyc.check_file(self.save("s%d.png" % seed, px, n=8))
            if r["verdict"] != nyc.UNDECIDED:
                decided.append((seed, round(r["agreement"], 3), round(r["z"], 2)))
        self.assertEqual(decided, [])

    def test_16_bit_colour_texture_is_not_a_normal_map(self):
        """16-bit samples scaled as 8-bit would make every pixel look upward-facing."""
        px = [200 * 257, 40 * 257, 30 * 257] * (N * N)
        r = nyc.check_file(self.save("c16.png", px, depth=16))
        self.assertEqual(r["verdict"], nyc.UNDECIDED)
        self.assertIn("upward-facing", r["reason"])

    def test_tiny_image_is_undecided(self):
        p = os.path.join(self.tmp, "t.png")
        write_png(p, 3, 3, [128, 160, 240] * 9)
        self.assertEqual(nyc.check_file(p)["verdict"], nyc.UNDECIDED)


class TestReading(Base):
    hf = height_bumps(N)

    def test_all_five_filters_read_the_same(self):
        px = map_central(self.hf, N, 8.0)
        base = self.verdict_of(px)
        for ft in range(1, 5):
            r = nyc.check_file(self.save("f%d.png" % ft, px, filter_type=ft))
            self.assertEqual(r["verdict"], nyc.Y_PLUS, "filter %d" % ft)
            self.assertAlmostEqual(r["agreement"], base["agreement"], places=9, msg="filter %d" % ft)

    def test_rgba(self):
        px = map_central(self.hf, N, 8.0)
        rgba = []
        for i in range(0, len(px), 3):
            rgba += px[i:i + 3] + [255]
        r = nyc.check_file(self.save("a.png", rgba, channels=4, filter_type=4))
        self.assertEqual(r["verdict"], nyc.Y_PLUS)

    def test_16_bit_both_ways(self):
        px = map_central(self.hf, N, 8.0, maxval=65535)
        r = nyc.check_file(self.save("s.png", px, depth=16, filter_type=1))
        self.assertEqual(r["verdict"], nyc.Y_PLUS)
        r = nyc.check_file(self.save("s2.png", flip_green(px, maxval=65535), depth=16, filter_type=4))
        self.assertEqual(r["verdict"], nyc.Y_MINUS)

    def test_16_bit_rgba_with_filters(self):
        px = map_central(self.hf, N, 8.0, green=-1, maxval=65535)
        rgba = []
        for i in range(0, len(px), 3):
            rgba += px[i:i + 3] + [65535]
        r = nyc.check_file(self.save("s4.png", rgba, channels=4, depth=16, filter_type=3))
        self.assertEqual(r["verdict"], nyc.Y_MINUS)

    def test_empty_blue_channel_is_rebuilt(self):
        """Two-channel maps (blue left at 0) must still be read."""
        px = map_central(self.hf, N, 8.0)
        for i in range(2, len(px), 3):
            px[i] = 0
        self.assertEqual(self.verdict_of(px)["verdict"], nyc.Y_PLUS)
        self.assertEqual(self.verdict_of(flip_green(px))["verdict"], nyc.Y_MINUS)

    def test_greyscale_is_refused_with_a_reason(self):
        p = os.path.join(self.tmp, "g.png")
        write_png(p, 8, 8, [128] * 64, channels=1)
        with self.assertRaises(nyc.PngError) as cm:
            nyc.check_file(p)
        self.assertIn("greyscale", str(cm.exception))

    def test_not_a_png(self):
        p = os.path.join(self.tmp, "x.png")
        with open(p, "wb") as f:
            f.write(b"GIF89a....")
        with self.assertRaises(nyc.PngError):
            nyc.check_file(p)


class TestCommandLine(Base):
    hf = height_bumps(N)

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = nyc.main(list(argv))
        return code, buf.getvalue()

    def test_expect_match_exits_0(self):
        self.save("a.png", map_central(self.hf, N, 8.0))
        code, out = self.run_cli(self.tmp, "--expect", "y+")
        self.assertEqual(code, 0, out)
        self.assertIn("Y+ 1, Y- 0", out)

    def test_expect_contradiction_exits_1(self):
        self.save("a.png", map_central(self.hf, N, 8.0))
        self.save("b.png", map_central(self.hf, N, 8.0, green=-1))
        code, out = self.run_cli(self.tmp, "--expect", "y+")
        self.assertEqual(code, 1, out)
        self.assertIn("1 CONTRADICT", out)

    def test_expect_with_nothing_decided_is_not_a_pass(self):
        self.save("flat.png", [128, 128, 255] * (N * N))
        code, out = self.run_cli(self.tmp, "--expect", "y+")
        self.assertEqual(code, 3, out)
        self.assertIn("undecided 1", out)

    def test_undecided_does_not_count_as_contradiction(self):
        self.save("a.png", map_central(self.hf, N, 8.0))
        self.save("flat.png", [128, 128, 255] * (N * N))
        code, out = self.run_cli(self.tmp, "--expect", "y+")
        self.assertEqual(code, 0, out)
        self.assertIn("1 not checked", out)

    def test_unreadable_file_exits_2(self):
        self.save("a.png", map_central(self.hf, N, 8.0))
        with open(os.path.join(self.tmp, "broken.png"), "wb") as f:
            f.write(b"not a png")
        code, out = self.run_cli(self.tmp)
        self.assertEqual(code, 2, out)
        self.assertIn("unreadable 1", out)

    def test_no_files_exits_2(self):
        code, out = self.run_cli(self.tmp)
        self.assertEqual(code, 2)

    def test_same_file_named_twice_is_read_once(self):
        p = self.save("a.png", map_central(self.hf, N, 8.0))
        code, out = self.run_cli(p, p, self.tmp)
        self.assertIn("1 file(s)", out)

    def test_tsv_has_one_row_per_file(self):
        self.save("a.png", map_central(self.hf, N, 8.0))
        self.save("b.png", map_central(self.hf, N, 8.0, green=-1))
        code, out = self.run_cli(self.tmp, "--tsv")
        rows = [l for l in out.splitlines() if l.startswith(("Y+\t", "Y-\t", "undecided\t"))]
        self.assertEqual(sorted(r.split("\t")[0] for r in rows), ["Y+", "Y-"])


if __name__ == "__main__":
    unittest.main()
