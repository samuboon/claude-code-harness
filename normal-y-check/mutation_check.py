# -*- coding: utf-8 -*-
"""Break normal_y_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker
of this kind plausibly makes; the first one is the whole point of the tool turned upside
down (answer Y+ where the evidence says Y-). The script runs the suite against each mutated
copy and reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "normal_y_check.py"
BAK = HERE / "normal_y_check.py.mutation-backup"

MUTATIONS = [
    ("M1  reverse the verdict: call agreement Y- and disagreement Y+",
     "    return (Y_PLUS if agreement > 0 else Y_MINUS), agreement, z, \"\"",
     "    return (Y_PLUS if agreement < 0 else Y_MINUS), agreement, z, \"\""),
    ("M2  read green with the DirectX sign while calling the result Y+",
     "            t[x] = ny / nz",
     "            t[x] = -ny / nz"),
    ("M3  forget the minus on red, so the across-slope points the wrong way",
     "            p[x] = -nx / nz",
     "            p[x] = nx / nz"),
    ("M4  take the across-slope change along the row instead of down the column",
     "                    a = p_dn[x] - p_up[x]",
     "                    a = middle[0][x + 1] - middle[0][x - 1]"),
    ("M5  guess Y+ when there is no relief that bends both ways",
     "        return (UNDECIDED, 0.0, 0.0,\n                \"no relief that bends both ways",
     "        return (Y_PLUS, 0.0, 0.0,\n                \"no relief that bends both ways"),
    ("M6  drop the significance floor, so noise gets a verdict",
     "    if abs(z) < MIN_Z:",
     "    if False:"),
    ("M7  drop the agreement floor, so rounding alone gets a verdict",
     "    if abs(agreement) < MIN_AGREEMENT:",
     "    if False:"),
    ("M8  report the two curl figures the wrong way round",
     "    return (total - 2.0 * st.s_ab) / total, (total + 2.0 * st.s_ab) / total",
     "    return (total + 2.0 * st.s_ab) / total, (total - 2.0 * st.s_ab) / total"),
    ("M9  accept a colour texture as a normal map",
     "    if st.pixels == 0 or st.valid < MIN_VALID * st.pixels:",
     "    if st.pixels == 0:"),
    ("M10 never rebuild an empty blue channel",
     "        if row[k + 2] == 0:",
     "        if False:"),
    ("M11 rebuild blue for every dark pixel, so a colour texture decodes as a normal map",
     "        if row[k + 2] == 0:",
     "        if nz < NZ_FLOOR:"),
    ("M12 read 16-bit samples as if they were 8-bit",
     "    maxval = 65535 if depth == 16 else 255",
     "    maxval = 255"),
    ("M13 swap the two Paeth fallbacks",
     "    if pb <= pc:\n        return b\n    return c",
     "    if pb <= pc:\n        return c\n    return b"),
    ("M14 drop the left neighbour from the Average filter",
     "                    line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF",
     "                    line[x] = (line[x] + (prev[x] >> 1)) & 0xFF"),
    ("M15 make the Sub filter look one byte back instead of one pixel back",
     "                    line[x] = (line[x] + line[x - bpp]) & 0xFF",
     "                    line[x] = (line[x] + line[x - 1]) & 0xFF"),
    ("M16 exit 0 when a map contradicts --expect",
     "        if wrong:\n            code = 1",
     "        if wrong:\n            code = 0"),
    ("M17 call it a pass when --expect was given and nothing could be decided",
     "        elif n_plus + n_minus == 0:\n            code = 3",
     "        elif n_plus + n_minus == 0:\n            code = 0"),
    ("M18 count an undecided map as a contradiction",
     "        wrong = [r for r in results if r[\"verdict\"] not in (want, UNDECIDED)]",
     "        wrong = [r for r in results if r[\"verdict\"] != want]"),
    ("M19 exit 0 over a file that could not be read",
     "        code = 2 if code in (0, 3) else code",
     "        code = code"),
    ("M20 read the same file twice when it is named twice",
     "            if key not in seen:",
     "            if True:"),
    ("M21 accept a greyscale PNG and read its grey as red",
     "    if ctype in (0, 4):\n        raise PngError",
     "    if False:\n        raise PngError"),
]


def run_suite():
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_normal_y_check"],
                       cwd=str(HERE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode == 0


def main():
    original = SRC.read_text(encoding="utf-8")
    if not run_suite():
        print("the unmutated suite fails; fix that first")
        return 2
    shutil.copyfile(str(SRC), str(BAK))
    survivors = []
    try:
        for name, old, new in MUTATIONS:
            if original.count(old) != 1:
                print("NOT APPLIED  %s  (target text found %d times)" % (name, original.count(old)))
                survivors.append(name)
                continue
            SRC.write_text(original.replace(old, new), encoding="utf-8")
            caught = not run_suite()
            print("%-8s %s" % ("caught" if caught else "SURVIVED", name))
            if not caught:
                survivors.append(name)
    finally:
        shutil.copyfile(str(BAK), str(SRC))
        BAK.unlink()
    print("\n%d mutations, %d caught, %d survived" % (
        len(MUTATIONS), len(MUTATIONS) - len(survivors), len(survivors)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
