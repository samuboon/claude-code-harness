# -*- coding: utf-8 -*-
"""Break quote_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. This edits a copy of the tool in
twenty-five specific ways - each one a mistake a checker of this kind plausibly makes -
runs the suite against each, and reports any mutation the suite lets through. Exit code 0
means every mutation was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "quote_check.py"
BAK = HERE / "quote_check.py.mutation-backup"

MUTATIONS = [
    ("M1  the exact test is done on normalised text, so a formatting difference reads as verbatim",
     "        if quote in text:",
     "        if normalize(quote, AXES)[0] in normalize(text, AXES)[0]:"),
    ("M2  width is tried before space, so a full-width space is blamed on character width",
     'AXES = ("invisible", "space", "quotes", "punct", "width", "case")',
     'AXES = ("invisible", "width", "space", "quotes", "punct", "case")'),
    ("M3  the ideographic space is left out of the whitespace set",
     'SPACE = "\\t\\n\\r\\f\\v \\u00a0\\u3000',
     'SPACE = "\\t\\n\\r\\f\\v \\u00a0'),
    ("M4  runs of whitespace are not collapsed, only translated",
     "            if not prev_space:",
     "            if True:"),
    ("M5  the index map points at the end of a collapsed run instead of its start",
     "                out.append(\" \")\n                idx.append(i)\n                prev_space = True",
     "                out.append(\" \")\n                idx.append(i + 1)\n                prev_space = True"),
    ("M6  the located slice stops one character short",
     "    end = smap[pos + len(qn) - 1] + 1",
     "    end = smap[pos + len(qn) - 1]"),
    ("M7  the zero-width space is left out of the invisible set",
     'INVISIBLE = "\\u200b',
     'INVISIBLE = "'),
    ("M8  the first differing character is always reported as the first character",
     "    for i, (x, y) in enumerate(zip(a, b)):\n        if x != y:\n            return i",
     "    for i, (x, y) in enumerate(zip(a, b)):\n        if x != y:\n            return 0"),
    ("M9  no difference is ever located, so every miss prints the vague message",
     "def first_difference(a, b):",
     "def first_difference(a, b):\n    return None"),
    ("M10 fenced code blocks are read as prose",
     "        if FENCE.match(line):\n            in_fence = not in_fence",
     "        if FENCE.match(line):\n            in_fence = False"),
    ("M11 inline code spans are read as prose",
     "        for m in QUOTED.finditer(INLINE_CODE.sub(\" \", line)):",
     "        for m in QUOTED.finditer(line):"),
    ("M12 the minimum length is not applied",
     "            if len(q.strip()) >= min_length:",
     "            if q.strip():"),
    ("M13 line numbers are counted from zero",
     'for n, line in enumerate(text.split("\\n"), 1):',
     'for n, line in enumerate(text.split("\\n")):'),
    ("M14 a blockquote that ends the file is dropped",
     "    if block is not None:\n        joined",
     "    if False:\n        joined"),
    ("M15 blockquotes are collected whether or not they were asked for",
     "        if blockquote:\n            if line.lstrip().startswith(\">\"):",
     "        if True:\n            if line.lstrip().startswith(\">\"):"),
    ("M16 every axis is relaxed at once, so no single axis is ever named",
     "    for axis in AXES:",
     "    for axis in (AXES,):"),
    ("M17 a quote that is not found verbatim is called invented without looking for it",
     "    best = None\n    for name, text in sources:\n        got = anchor_window(quote, text)",
     "    best = None\n    for name, text in []:\n        got = anchor_window(quote, text)"),
    ("M18 the anchor is the whole quote, which by definition does not match a changed quote",
     "    size = max(4, min(12, len(qn) // 3))",
     "    size = len(qn)"),
    ("M19 a quote found in no source at all does not fail the run",
     '    bad = counts["substantive"] + counts["unfound"]',
     '    bad = counts["substantive"] + 0 * counts["unfound"]'),
    ("M20 --strict does nothing",
     '+ (counts["formatting"] if a.strict else 0)',
     "+ 0"),
    ("M21 files are not normalised to NFC on load, so a decomposed source looks altered",
     '    return unicodedata.normalize("NFC", data.decode("utf-8", errors="strict")).replace("\\r\\n", "\\n")',
     '    return data.decode("utf-8", errors="strict").replace("\\r\\n", "\\n")'),
    ("M22 a file with NUL bytes is accepted as a text source",
     '    if b"\\x00" in data[:4096]:',
     "    if False:"),
    ("M23 a line break inside a source is printed as a line break, hiding it in the layout",
     '    return s.replace("\\\\", "\\\\\\\\").replace("\\n", "\\\\n").replace("\\t", "\\\\t")',
     "    return s"),
    ("M24 formatting differences are reported without naming the character that differs",
     '            i = first_difference(f["quote"], f["found"])',
     "            i = None"),
    ("M25 the control characters lose their names, so a line break prints as unnamed",
     '        name = CONTROL_NAMES.get(ch, "unnamed")',
     '        name = "unnamed"'),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "test_quote_check"],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def main():
    original = SRC.read_text(encoding="utf-8")
    shutil.copy2(SRC, BAK)
    survivors = []
    try:
        if not run_tests():
            print("the suite does not pass before any mutation; fix that first")
            return 2
        for desc, old, new in MUTATIONS:
            if old not in original:
                print("%s\n    SKIPPED - the text this mutation edits is not in the file" % desc)
                survivors.append(desc)
                continue
            SRC.write_text(original.replace(old, new, 1), encoding="utf-8")
            caught = not run_tests()
            print("%-4s %s" % ("ok" if caught else "LIVE", desc))
            if not caught:
                survivors.append(desc)
    finally:
        SRC.write_text(original, encoding="utf-8")
        BAK.unlink(missing_ok=True)
        for p in HERE.glob("__pycache__/*"):
            p.unlink(missing_ok=True)
    print("\n%d mutations, %d caught, %d survived" % (len(MUTATIONS), len(MUTATIONS) - len(survivors), len(survivors)))
    for s in survivors:
        print("  survived: %s" % s)
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
