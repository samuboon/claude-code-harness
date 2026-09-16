# -*- coding: utf-8 -*-
"""Break marker_drift.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
twenty-one specific ways - each one a mistake a checker of this kind plausibly makes -
runs the suite against each, and reports any mutation the suite lets through. Exit code 0
means every mutation was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "marker_drift.py"
BAK = HERE / "marker_drift.py.mutation-backup"

MUTATIONS = [
    ("M1  {n} goes back to \\d+, so a full-width 34 is an exact match",
     '    "{n}": r"[0-9]+",',
     '    "{n}": r"\\d+",'),
    ("M2  {w} goes back to \\w+, so a Japanese word satisfies an ASCII gate",
     '    "{w}": r"[A-Za-z0-9_]+",',
     '    "{w}": r"\\w+",'),
    ("M3  the space axis demands at least one space, so a missing space is invisible",
     '_SPACE_RX = r"\\s*"',
     '_SPACE_RX = r"\\s+"'),
    ("M4  the marker stops being escaped, so its brackets become a capture group",
     "            esc = re.escape(norm)",
     "            esc = norm"),
    ("M5  the space axis stops reaching the whitespace already in the marker",
     ", lambda _m: _SPACE_RX, esc)",
     ", lambda _m: _m.group(0), esc)"),
    ("M6  no whitespace allowed either side of a placeholder",
     "            chunks.append(_SPACE_RX + PLACEHOLDERS[part[0]] + _SPACE_RX if loose",
     "            chunks.append(PLACEHOLDERS[part[0]] if loose"),
    ("M7  --at start stops allowing an indent, and the space axis loses its head",
     '        body = ("^" + _SPACE_RX if loose else "^") + body',
     '        body = "^" + body'),
    ("M8  --at start stops anchoring at all",
     '        body = ("^" + _SPACE_RX if loose else "^") + body',
     "        body = body"),
    ("M9  --at end stops anchoring, so a marker quoted mid-sentence counts",
     '        body = body + (_SPACE_RX + "$" if loose else "$")',
     "        body = body"),
    ("M10 the exact match is never tried, so every hit is reported as drift",
     "    m = strict.search(line)",
     "    m = None"),
    ("M11 the axis set is never minimised: every drift blames all five axes",
     "        if compile_template(template, trial, at).search(cand):",
     "        if False:"),
    ("M12 off by one at the end of the span",
     "    end = idx[m.end() - 1] + 1 if m.end() > m.start() else start",
     "    end = idx[m.end() - 1] if m.end() > m.start() else start"),
    ("M13 exit 0 even with drift found",
     '    return 1 if result["drift"] else 0',
     "    return 0"),
    ("M14 print a green check over a scan that read nothing",
     '    if result["read"] == 0:',
     "    if False:"),
    ("M15 blank lines count as lines read",
     "        if not line.strip():",
     "        if False:"),
    ("M16 the case axis stops being ASCII-only, so it lower-cases Greek too",
     '        if do_case and "A" <= ch <= "Z":',
     "        if do_case and True:"),
    ("M17 the long-vowel mark leaves the dash axis",
     '_DASH = {c: "-" for c in "‐‑‒–—―−－ー⁃﹘﹣"}',
     '_DASH = {c: "-" for c in "‐‑‒–—―−－⁃﹘﹣"}'),
    ("M18 a line longer than the cap is read whole instead of truncated",
     "        if len(line) > MAX_LINE:",
     "        if False:"),
    ("M19 the tsv loses its header row",
     '        out.write("line_no\\taxes\\tfound\\tline\\n")',
     "        pass"),
    ("M20 lines with no marker are printed whether or not they were asked for",
     '    if show_missing and result["missing"]:',
     '    if result["missing"]:'),
    ("M21 a path that is not a file is scanned as if it were empty",
     "        if not path.is_file():",
     "        if False:"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "test_marker_drift"],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def main():
    if not SRC.exists():
        print("marker_drift.py is not here")
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
