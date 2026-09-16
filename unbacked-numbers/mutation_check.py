# -*- coding: utf-8 -*-
"""Break unbacked_numbers.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
eighteen specific ways - each one a mistake a checker of this kind plausibly makes - runs
the suite against each, and reports any mutation the suite lets through. Exit code 0
means every mutation was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "unbacked_numbers.py"
BAK = HERE / "unbacked_numbers.py.mutation-backup"

MUTATIONS = [
    ("M1  a quoted 3\u4e07 stops backing the prose 30000",
     "    quoted = sorted({v for v, _o, _r, _u in numbers_in(evidence)})",
     "    quoted = sorted({v for v, _o, _r, _u in numbers_in(evidence, both=False)})"),
    ("M2  read 1,200 as 1 (thousands separator dropped, not stripped)",
     '            value = float(whole.replace(",", "") + ("." + frac if frac else ""))',
     '            value = float(whole.split(",")[0] + ("." + frac if frac else ""))'),
    ("M3  measure drift in absolute units, so 153 vs 149 stops being a near-miss",
     "            g = 1.0 if scale == 0 else abs(q - value) / scale",
     "            g = abs(q - value)"),
    ("M4  only the fence markers count as evidence, not the lines between them",
     '        if in_fence or line.lstrip().startswith(">"):',
     '        if line.lstrip().startswith(">"):'),
    ("M5  let the prose back itself (the two halves stop being different)",
     "    evidence = keep_only(text, spans)",
     "    evidence = text"),
    ("M6  off by one in the line number",
     "    return lo + 1",
     "    return lo"),
    ("M7  exit 0 even with findings",
     "    return 1 if rows else 0",
     "    return 0"),
    ("M8  print a green check over a scan that read nothing",
     "    if files_read == 0:",
     "    if False:"),
    ("M9  let --format paste print the rows it found",
     '    elif args.format == "tsv":',
     '    elif args.format in ("tsv", "paste"):'),
    ("M10 scan files that quote nothing at all, by default",
     "    if not quoted and not strict:",
     "    if False:"),
    ("M11 apply the small-number floor to numbers that carry a unit",
     "        if not has_unit and value == int(value) and value < min_value:",
     "        if value < min_value:"),
    ("M12 open every file, not only the ones people write sentences in",
     "        if p.suffix.lower() not in SUFFIXES:\n            continue",
     "        if False:\n            continue"),
    ("M13 stop masking dates, versions, paths and issue refs",
     "    prose = mask_identifiers(blank_out(text, spans), include_years)",
     "    prose = blank_out(text, spans)"),
    ("M14 call any four-digit number a year",
     r'BARE_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)"',
     r'BARE_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)"'),
    ("M15 redact on length alone, so every long path becomes [redacted]",
     '    if "/" in s:                      # a path, and a path is not a finding worth hiding\n        return False',
     '    if "/" in s:\n        return True'),
    ("M16 stop treating inline code as a quote",
     '    re.compile(r"`[^`\\n]+`"),',
     '    re.compile(r"(?!x)x"),'),
    ("M17 read the digits inside a file path as claims",
     '    re.compile(r"\\S*[\\\\/]\\S*"),                                        # paths',
     '    re.compile(r"(?!x)x"),'),
    ("M18 stop normalising full-width digits",
     "    return text.translate(FULLWIDTH)",
     "    return text"),
    ("M22 let a number alone in backticks stand as its own evidence",
     "                if DIGITS_ONLY.match(mm.group(0)[1:-1]):\n                    continue",
     "                if False:\n                    continue"),
    ("M20 call 19 a mistyped 20 (the floor under the ratio is removed)",
     "NEAR_MISS_FLOOR = 100",
     "NEAR_MISS_FLOOR = 0"),
    ("M21 redact any long run of text, not only token-shaped ones",
     '    if not re.fullmatch(r"[A-Za-z0-9_.\\-]+", s):   # prose, not a token\n        return False',
     "    if False:\n        return False"),
    ("M19 sort by path, burying the near-misses among the rest",
     '    rows.sort(key=lambda r: (ORDER[r["kind"]], r["path"], r["line"], r["value"]))',
     '    rows.sort(key=lambda r: (r["path"], r["line"]))'),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "test_unbacked_numbers"],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def main():
    if not SRC.exists():
        print("unbacked_numbers.py is not here")
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
