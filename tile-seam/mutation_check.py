# -*- coding: utf-8 -*-
"""Break tile_seam.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
twenty specific ways - each one a mistake a seam checker of this kind plausibly makes, and
the first two are the exact mistake this tool was written to stop making - runs the suite
against each, and reports any mutation the suite lets through. Exit code 0 means every
mutation was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "tile_seam.py"
BAK = HERE / "tile_seam.py.mutation-backup"

MUTATIONS = [
    ("M1  call a tie a seam, so a stripe whose wrap matches its own interior edge fails",
     "    if wrap > worst:",
     "    if wrap >= worst:"),
    ("M2  judge by the median instead of by the worst edge (the test we shipped and had to withdraw)",
     "    if wrap > worst:",
     "    if ratio > 2.0:"),
    ("M3  drop the suspect band entirely",
     "    if rank >= suspect_rank:",
     "    if False:"),
    ("M4  count a neighbour step equal to the wrap as one the wrap beat",
     "    rank = sum(1 for s in steps if s < wrap) / n",
     "    rank = sum(1 for s in steps if s <= wrap) / n"),
    ("M5  take the left/right wrap one column early",
     "    wrap = _mean_abs(plane[width - 1::width], plane[0::width])",
     "    wrap = _mean_abs(plane[width - 2::width], plane[0::width])"),
    ("M6  take the top/bottom wrap one row early",
     "    wrap = _mean_abs(plane[(height - 1) * width:height * width], plane[0:width])",
     "    wrap = _mean_abs(plane[(height - 2) * width:(height - 1) * width], plane[0:width])"),
    ("M7  average the column steps over the wrong dimension",
     "    steps = [a / height for a in acc]",
     "    steps = [a / width for a in acc]"),
    ("M8  keep the first channel's answer instead of the worst channel's",
     "        if best is None or key > best[0]:",
     "        if best is None:"),
    ("M9  let the left/right axis decide on its own, ignoring top/bottom",
     "    for a in present:",
     "    for a in present[:1]:"),
    ("M10 exit 0 even when a seam was found",
     '    return 1 if any(r["overall"] == SEAM for r in results) else 0',
     "    return 0"),
    ("M11 print a clean report over a scan that read nothing",
     "    if not results:\n        return 2",
     "    if False:\n        return 2"),
    ("M12 set the fixed threshold so high that nothing reaches it",
     "NAIVE_THRESHOLD = 8.0",
     "NAIVE_THRESHOLD = 255.0"),
    ("M13 swap the two Paeth fallbacks, so the wrong neighbour predicts the pixel",
     "    if pb <= pc:\n        return b\n    return c",
     "    if pb <= pc:\n        return c\n    return b"),
    ("M14 drop the left neighbour from the Average filter",
     "                line[i] = (line[i] + ((line[i - bpp] + prev[i]) >> 1)) & 0xFF",
     "                line[i] = (line[i] + (prev[i] >> 1)) & 0xFF"),
    ("M15 make the Sub filter look one byte back instead of one pixel back",
     "                line[i] = (line[i] + line[i - bpp]) & 0xFF",
     "                line[i] = (line[i] + line[i - 1]) & 0xFF"),
    ("M16 read 16-bit samples as if they were 8-bit, so channels interleave",
     "    step = nch * (2 if depth == 16 else 1)",
     "    step = nch"),
    ("M17 stop scaling 1/2/4-bit samples, so a 1-bit image is all zeros and ones",
     "                out[dst + x] = ((byte >> shift) & mask) * scale",
     "                out[dst + x] = ((byte >> shift) & mask)"),
    ("M18 decode an interlaced PNG as if it were not, producing a scrambled picture",
     '        raise PngError("Adam7-interlaced PNGs are not supported; re-save without interlacing")',
     "        pass"),
    ("M19 scan the same file twice when it is named twice",
     "            if key not in seen:",
     "            if True:"),
    ("M20 ignore tRNS, so a palette image's transparency is invisible to the scan",
     "        has_alpha = trns is not None and len(trns) > 0",
     "        has_alpha = False"),
    ("M21 return the mean where the median was wanted",
     "    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0",
     "    return sum(s) / n"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "test_tile_seam"],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def main():
    if not SRC.exists():
        print("tile_seam.py is not here")
        return 2
    original = SRC.read_text(encoding="utf-8")
    shutil.copy2(SRC, BAK)
    survived = []
    try:
        if not run_tests():
            print("the suite fails before any mutation. Fix that first.")
            return 2
        print("baseline: the suite passes on the unmutated tool")
        for name, before, after in MUTATIONS:
            if before not in original:
                print("SKIP %s - the line it edits is gone; update this script" % name)
                survived.append(name + "  (stale)")
                continue
            SRC.write_text(original.replace(before, after, 1), encoding="utf-8")
            caught = not run_tests()
            print(("caught   " if caught else "SURVIVED ") + name)
            if not caught:
                survived.append(name)
    finally:
        SRC.write_text(original, encoding="utf-8")
        BAK.unlink(missing_ok=True)

    print()
    if survived:
        print("%d of %d mutations were not caught:" % (len(survived), len(MUTATIONS)))
        for s in survived:
            print("  " + s)
        return 1
    print("all %d mutations caught" % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
