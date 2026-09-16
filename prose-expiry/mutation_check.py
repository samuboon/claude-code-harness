# -*- coding: utf-8 -*-
"""Break prose_expiry.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
sixteen specific ways - each one a mistake a scanner of this kind plausibly makes, and
most of which are the reason the corresponding test exists - runs the suite against each,
and reports any mutation the suite lets through. Exit code 0 means every mutation was
caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "prose_expiry.py"
BAK = HERE / "prose_expiry.py.mutation-backup"

MUTATIONS = [
    ("M1  accept any year (a 1969 build stamp becomes an overdue deadline)",
     "        if not 1970 <= y <= 2100:\n            return None",
     "        if False:\n            return None"),
    ("M2  stop checking the calendar (2026-02-30 becomes a date)",
     "        return date(y, m, d)",
     "        return date(y, m, 1) if d > 28 else date(y, m, d)"),
    ("M3  read the day as the month in ISO order",
     "            y, m, d = int(y), int(m), int(d)",
     "            y, m, d = int(y), int(d), int(m)"),
    ("M4  drop the proximity rule: any cue on the line claims every date on it",
     "                if gap <= near and (best is None or (weak, gap) < (best[0], best[1])):",
     "                if (best is None or (weak, gap) < (best[0], best[1])):"),
    ("M5  measure the gap from the wrong end, so a cue after the date looks adjacent",
     "    return b_start - a_end if b_start >= a_end else a_start - b_end",
     "    return 0"),
    ("M6  let a weak cue outrank a strong one when it sits closer",
     "                if gap <= near and (best is None or (weak, gap) < (best[0], best[1])):",
     "                if gap <= near and (best is None or gap < best[1]):"),
    ("M7  count weak cues as findings by default",
     "            if weak and not include_weak:\n                weak_seen += 1\n                continue",
     "            if False:\n                weak_seen += 1\n                continue"),
    ("M8  let the heading reach the whole file",
     "            if name is None and n - heading_line <= HEADING_REACH:",
     "            if name is None:"),
    ("M9  report the date one day late (off-by-one in the day count)",
     '            rows.append({"days": (d - today).days,',
     '            rows.append({"days": (d - today).days + 1,'),
    ("M10 redact on length alone, so every long path becomes [redacted]",
     '    if "/" in s:                      # a path, and a path is not a finding worth hiding\n        return False',
     '    if "/" in s:\n        return True'),
    ("M11 stop redacting mixed-case tokens",
     "    return digits >= 2 and any(c.isupper() for c in s) and any(c.islower() for c in s)",
     "    return False"),
    ("M12 half-read an oversized file instead of skipping it",
     "                if p.stat().st_size > MAX_BYTES:\n                    skipped += 1\n                    continue",
     "                if False:\n                    skipped += 1\n                    continue"),
    ("M13 print a green check over a scan that read nothing",
     "    if files_read == 0 and ledger_rows == 0:",
     "    if False:"),
    ("M14 exit 0 even when something has already passed",
     "    return 1 if (passed or soon) else 0",
     "    return 0"),
    ("M15 sort by date string instead of by days left",
     '    rows.sort(key=lambda r: (r["days"], r["where"]))',
     '    rows.sort(key=lambda r: r["where"])'),
    ("M16 let --format paste print the line it matched",
     '        print("  %d rows over %d distinct dates" % (len(rows), len({r["date"] for r in rows})))',
     '        print("  %d rows over %d distinct dates %s" % (len(rows), len({r["date"] for r in rows}), [r["what"] for r in rows] + [r["where"] for r in rows]))'),
    ("M17 guess today's date for a ledger row that has none",
     "        got = dates_in(cells[1])\n        if not got:\n            continue",
     "        got = dates_in(cells[1])\n        if not got:\n            got = [(0, 0, today)]"),
    ("M18 accept a month name that only starts like one (Maybe -> May)",
     r'    ("mdy", re.compile(r"\b(" + MONTH_ALT + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),',
     r'    ("mdy", re.compile(r"\b(" + MONTH_ALT + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),'),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "test_prose_expiry"],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def main():
    if not SRC.exists():
        print("prose_expiry.py is not here")
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
