# -*- coding: utf-8 -*-
"""Break key_expiry.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This script edits a copy of the tool in
fourteen specific ways - each one a mistake a parser of this kind plausibly makes, and
several of which are the reason the corresponding test exists - runs the suite against
each, and reports any mutation the suite lets through. Exit code 0 means every mutation
was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "key_expiry.py"
BAK = HERE / "key_expiry.py.mutation-backup"

MUTATIONS = [
    ("M1  read every two-digit year as 20xx (a 1998 certificate becomes due in 2098)",
     "        year = 1900 + yy if yy >= 50 else 2000 + yy",
     "        year = 2000 + yy"),
    ("M2  report notBefore instead of notAfter",
     "        if len(times) == 2:\n            return der_time(*times[1])",
     "        if len(times) == 2:\n            return der_time(*times[0])"),
    ("M3  accept the indefinite length form (reads it as length 0 and walks off)",
     "        if k == 0 or k > 4 or i + k > len(buf):",
     "        if k > 4 or i + k > len(buf):"),
    ("M4  stop checking that a value fits inside the buffer",
     "    end = i + n\n    if end > len(buf):",
     "    end = i + n\n    if False:"),
    ("M5  stop naming a non-UTC time as such (it is still refused, on length, but the "
     "report then blames the digits instead of the timezone)",
     '    if not s.endswith("Z"):',
     "    if False:"),
    ("M6  let a boolean exp claim through (`true` would date to 1970)",
     "    if isinstance(exp, bool) or not isinstance(exp, (int, float)):",
     "    if not isinstance(exp, (int, float)):"),
    ("M7  stop requiring a JOSE header, so any base64 JSON counts as a token",
     '    if not isinstance(head, dict) or "alg" not in head:',
     "    if False:"),
    ("M8  never look at the UTF-16LE view (the blind spot this inherits from leak-scan)",
     '    if b"\\x00" in data:',
     "    if False:"),
    ("M9  key the de-duplication on the whole match rather than header+payload",
     '                        key = blob.rsplit(b".", 1)[0]',
     "                        key = blob"),
    ("M10 match PEM blocks greedily (a trust store collapses into one bad match)",
     'PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.S)',
     'PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----(.+)-----END CERTIFICATE-----", re.S)'),
    ("M11 report success after reading zero files",
     "    if read == 0:",
     "    if False:"),
    ("M12 always exit 0, whatever is about to expire",
     "    return 1 if due else 0",
     "    return 0"),
    ("M13 make the window exclusive at its edge",
     "    due = [x for x in rows if x[0] <= within]",
     "    due = [x for x in rows if x[0] < within]",),
    ("M14 put the path back into the paste format",
     '        for d, _rel, _line, kind, _w, _n in rows:\n            out.write("%s\\t%d\\n" % (kind, d))',
     '        for d, _rel, _line, kind, _w, _n in rows:\n            out.write("%s\\t%s\\t%d\\n" % (kind, _rel, d))'),
    ("M15 scan the directories that are meant to be skipped",
     "        if any(part in SKIP_DIRS for part in p.parts):",
     "        if False:"),
    ("M16 read files of any size (a partial read can split a PEM block)",
     "            if p.stat().st_size > MAX_BYTES:",
     "            if False:"),
]


def run_suite():
    r = subprocess.run([sys.executable, str(HERE / "test_key_expiry.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode


def main():
    original = SRC.read_text(encoding="utf-8")
    shutil.copy2(SRC, BAK)
    survivors = []
    try:
        if run_suite() != 0:
            print("The suite does not pass on the unmutated file. Fix that first.")
            return 2
        print("baseline: the suite passes\n")
        for name, old, new in MUTATIONS:
            if old not in original:
                print("SKIPPED (the line moved): " + name)
                survivors.append(name + "  [line not found]")
                continue
            SRC.write_text(original.replace(old, new, 1), encoding="utf-8")
            caught = run_suite() != 0
            print(("caught   " if caught else "SURVIVED ") + name)
            if not caught:
                survivors.append(name)
    finally:
        SRC.write_text(original, encoding="utf-8")
        BAK.unlink(missing_ok=True)

    print()
    if survivors:
        print("%d of %d mutations were not caught:" % (len(survivors), len(MUTATIONS)))
        for s in survivors:
            print("  " + s)
        return 1
    print("all %d mutations were caught" % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
