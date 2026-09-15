# -*- coding: utf-8 -*-
"""Break leak_scan.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
sixteen specific ways - each one a mistake we could plausibly make, and several of which
we actually made - runs the suite against each, and reports any mutation the suite lets
through. Exit code 0 means every mutation was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "leak_scan.py"
BAK = HERE / "leak_scan.py.mutation-backup"

MUTATIONS = [
    ("M1  search UTF-8 only, never UTF-16LE (the blind spot this tool exists for)",
     'for enc, step in (("utf-8", 1), ("utf-16-le", 2)):',
     'for enc, step in (("utf-8", 1),):'),
    ("M2  drop the ASCII word-boundary test",
     "                if check_boundary and not _boundary_ok(data, i, end):",
     "                if False and not _boundary_ok(data, i, end):"),
    ("M3  drop the katakana boundary test",
     "                if kata and not _kata_boundary_ok(data, i, end):",
     "                if False and not _kata_boundary_ok(data, i, end):"),
    ("M4  treat a bare key prefix in prose as a key",
     "    return len(tail) == need and all(b in KEY_BODY for b in tail)",
     "    return True"),
    ("M5  accept a value of any length after a secret-shaped name",
     "ASSIGN_MIN = 8",
     "ASSIGN_MIN = 0"),
    ("M6  stop filtering placeholder values",
     "    return not any(p in low for p in PLACEHOLDERS)",
     "    return True"),
    ("M7  treat an interpolation like ${VAR} as a literal secret",
     "    if text.startswith(INTERP_START):",
     "    if False:"),
    ("M8  print what was found instead of masking it",
     '    return text[:2] + "*" * min(len(text) - 2, 12)',
     "    return text"),
    ("M9  report success after reading zero files",
     '        print("nothing was read, so this is not a pass", file=sys.stderr)\n        return 2',
     '        print("nothing was read, so this is not a pass", file=sys.stderr)\n        return 0'),
    ("M10 shrug off a missing patterns file and scan without identifiers",
     '            print("patterns file not found: " + args.patterns, file=sys.stderr)\n            return 2',
     '            print("patterns file not found: " + args.patterns, file=sys.stderr)\n            return 0'),
    ("M11 stop excluding .git by default",
     'DEFAULT_EXCLUDES = (".git",)',
     "DEFAULT_EXCLUDES = ()"),
    ("M12 report every hit as line 1",
     '    return data.count(b"\\n", 0, pos) + 1',
     "    return 1"),
    ("M13 report a match and every shorter match inside it",
     "        if any(other is not span and other[2] <= pos and other[2] + other[4] >= pos + length",
     "        if False and any(other is not span and other[2] <= pos and other[2] + other[4] >= pos + length"),
    ("M14 find hits and exit 0 anyway",
     '    if total_hits and args.fail_on == "any":',
     "    if False:"),
    ("M15 ignore the allow list",
     '        if (rel, needle) in allow or ("*", needle) in allow:',
     "        if False:"),
    ("M16 treat a bare PEM header in prose as a private key",
     "    return body >= PEM_BODY_MIN",
     "    return True"),
]


def run_suite():
    r = subprocess.run([sys.executable, str(HERE / "test_leak_scan.py")],
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
