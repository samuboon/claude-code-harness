# -*- coding: utf-8 -*-
"""Break vrc_texture_audit.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
twenty specific ways - each one a mistake we could plausibly make - runs the suite against
each, and reports any mutation the suite lets through. Exit code 0 means every mutation
was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "vrc_texture_audit.py"
BAK = HERE / "vrc_texture_audit.py.mutation-backup"

MUTATIONS = [
    ("M1  charge alpha textures the same as opaque ones (BC3 == BC1)",
     "BYTES_PER_PIXEL_ALPHA = 1.0",
     "BYTES_PER_PIXEL_ALPHA = 0.5"),
    ("M2  forget mipmaps (every estimate 25% low)",
     "MIPMAP_FACTOR = 4.0 / 3.0",
     "MIPMAP_FACTOR = 1.0"),
    ("M3  mistype one of VRChat's published thresholds",
     '"pc": [("Excellent", 40), ("Good", 75), ("Medium", 110), ("Poor", 150)],',
     '"pc": [("Excellent", 40), ("Good", 70), ("Medium", 110), ("Poor", 150)],'),
    ("M4  make the rank boundary exclusive (exactly 40 MB stops being Excellent)",
     "        if mb <= limit:",
     "        if mb < limit:"),
    ("M5  call a nearly-opaque pixel opaque",
     "                    if not used and min(cur) != 255:",
     "                    if not used and min(cur) < 250:"),
    ("M6  skip the Up filter (leave the row as encoded)",
     "        return bytes((c + p) & 255 for c, p in zip(cur, prev))",
     "        return cur"),
    ("M7  drop the running left value in the Sub filter",
     "            a = (c + a) & 255",
     "            a = c & 255"),
    ("M8  average against the left byte only",
     "            a = (c + ((a + prev[i]) >> 1)) & 255",
     "            a = (c + (a >> 1)) & 255"),
    ("M9  break Paeth's third candidate",
     "            pc = abs(a + b - 2 * upleft)",
     "            pc = abs(a - b)"),
    ("M10 fall back to 0 instead of the upper-left byte in Paeth",
     "                pred = upleft",
     "                pred = 0"),
    ("M11 decode an interlaced PNG as if it were not (wrong answer, stated confidently)",
     '    if meta.get("interlace"):',
     "    if False:"),
    ("M12 hit IEND before the declared last row and call it 'alpha not used'",
     '            if name == b"IEND":\n                return None',
     '            if name == b"IEND":\n                return used'),
    ("M12b run out of file mid-chunk and call it 'alpha not used'",
     "            if len(chunk_head) < 8:\n                return None",
     "            if len(chunk_head) < 8:\n                return used"),
    ("M13 treat any tRNS chunk as proof the alpha is used",
     "        return any(v != 255 for v in trns)",
     "        return True"),
    ("M14 compute the stride from the channel count, ignoring 16-bit depth",
     "    bpp = channels * (bit_depth // 8)",
     "    bpp = channels"),
    ("M15 give up on 16-bit PNGs instead of reading them",
     "    if bit_depth not in (8, 16):",
     "    if bit_depth not in (8,):"),
    ("M16 call every 32-bit TGA alpha-bearing, ignoring the attribute bits",
     "    alpha = depth == 32 and alpha_bits > 0",
     "    alpha = depth == 32"),
    ("M17 count a PSD's last colour channel as an alpha channel",
     '    return width, height, channels > base, ""',
     '    return width, height, channels >= base, ""'),
    ("M18 cost an unknown alpha as if it were absent (under-report the budget)",
     "        per = BYTES_PER_PIXEL_NO_ALPHA if self.alpha is False else BYTES_PER_PIXEL_ALPHA",
     "        per = BYTES_PER_PIXEL_ALPHA if self.alpha else BYTES_PER_PIXEL_NO_ALPHA"),
    ("M19 claim a saving from an alpha channel we never actually checked",
     "        if self.alpha and self.alpha_used is False:",
     "        if self.alpha and self.alpha_used is not True:"),
    ("M20 call every size a power of two",
     "    return n > 0 and (n & (n - 1)) == 0",
     "    return True"),
    ("M21 print a clean report for a folder holding no textures",
     "        return 2\n    if not args.no_alpha_scan:",
     "        return 0\n    if not args.no_alpha_scan:"),
    ("M22 accept a total over --max-mb",
     "        if total_mb > args.max_mb:",
     "        if False:"),
    ("M23 read a JPEG's DHT segment as if it were the SOF",
     "        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):",
     "        if 0xC0 <= m <= 0xCF:"),
    ("M24 walk .git and __pycache__ as if they held avatar textures",
     '        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__"))',
     "        dirnames[:] = sorted(dirnames)"),
    ("M25 report a single file as a duplicate group",
     "    return [group for group in by_digest.values() if len(group) > 1]",
     "    return [group for group in by_digest.values() if len(group) >= 1]"),
    ("M27 put a character back in the report that a Japanese Windows console cannot print",
     '"too large to scan"',
     '"大きすぎて未走査"'),
    ("M26 ignore --max-scan-pixels and decode every image anyway",
     '        if max_scan_pixels and meta["color_type"] != 3 and tex.pixels > max_scan_pixels:',
     "        if False:"),
]


def run_suite():
    r = subprocess.run([sys.executable, str(HERE / "test_vrc_texture_audit.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode


def main():
    original = SRC.read_text(encoding="utf-8")
    shutil.copy2(SRC, BAK)
    survivors = []
    try:
        if run_suite() != 0:
            print("the suite is already red on the unmodified file; fix that first")
            return 2
        for label, old, new in MUTATIONS:
            if old not in original:
                print("SKIP  %s  (anchor text not found - the tool moved under it)" % label)
                survivors.append(label + "  [anchor missing]")
                continue
            SRC.write_text(original.replace(old, new, 1), encoding="utf-8")
            caught = run_suite() != 0
            print(("caught   " if caught else "SURVIVED ") + label)
            if not caught:
                survivors.append(label)
    finally:
        SRC.write_text(original, encoding="utf-8")
        BAK.unlink(missing_ok=True)

    print("\n%d mutations, %d survived" % (len(MUTATIONS), len(survivors)))
    for s in survivors:
        print("  - " + s)
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
