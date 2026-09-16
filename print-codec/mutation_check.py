# -*- coding: utf-8 -*-
"""Break print_codec.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has watched fail is decoration. This edits a copy of the tool in
twenty-two specific ways - each one a mistake a checker of this kind plausibly makes -
runs the suite against each, and reports every mutation the suite lets through. Exit 0
means all of them were caught.

The original file is restored in a finally block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "print_codec.py"
BAK = HERE / "print_codec.py.mutation-backup"

MUTATIONS = [
    ("M1  an unencodable character is called encodable, so nothing is ever at risk",
     "            hit = False",
     "            hit = True"),
    ("M2  the report quotes the source line verbatim, and dies of the bug it reports",
     '        out.append(ch if encodable(ch, codec) else "<U+{:04X}>".format(ord(ch)))',
     "        out.append(ch)"),
    ("M3  no file is ever seen as protecting itself",
     "            if needle in text:\n                return label",
     "            if needle in text and False:\n                return label"),
    ("M4  only reconfigure counts as protection, so TextIOWrapper looks unguarded",
     '    ("TextIOWrapper", ("TextIOWrapper(sys.stdout.buffer", "TextIOWrapper(sys.stderr.buffer",',
     '    ("TextIOWrapper", ("TextIOWrapper(NOTHING.buffer", "TextIOWrapper(NOTHING2.buffer",'),
    ("M5  PYTHONIOENCODING stops counting as protection",
     '    ("PYTHONIOENCODING", ("PYTHONIOENCODING",)),',
     '    ("PYTHONIOENCODING", ("PYTHONIOENCODING_NEVER",)),'),
    ("M6  print(..., file=open(...)) is treated as a console write",
     "            if kw.arg == \"file\" and _stream_of(kw.value) is None:\n                return None",
     "            if False:\n                return None"),
    ("M7  sys.stdout.write is not a console write",
     '    if isinstance(func, ast.Attribute) and func.attr == "write":',
     '    if isinstance(func, ast.Attribute) and func.attr == "write_never":'),
    ("M8  logging is read whether it was asked for or not",
     "    if include_logging and isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS:",
     "    if isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS:"),
    ("M9  any object with an .info() is taken for a logger",
     "        if isinstance(owner, ast.Name) and owner.id in _LOG_OWNERS:",
     "        if isinstance(owner, ast.Name):"),
    ("M10 a name assigned twice is still resolved, to whichever value came last",
     "    for name in twice:\n        found.pop(name, None)",
     "    for name in twice:\n        pass"),
    ("M11 assignments inside functions are collected as module constants",
     "    for node in tree.body:",
     "    for node in ast.walk(tree):"),
    ("M12 the literal halves of an f-string are dropped",
     "    if isinstance(node, ast.JoinedStr):  # f-string: only the literal halves are known",
     "    if isinstance(node, ast.JoinedStr) and False:"),
    ("M13 a printed module constant is no longer followed",
     "    if isinstance(node, ast.Name):\n        return constants.get(node.id, \"\")",
     "    if isinstance(node, ast.Name):\n        return \"\""),
    ("M14 only the left half of a concatenation is read",
     "            return (literal_text(node.left, constants, depth + 1)\n                    + literal_text(node.right, constants, depth + 1))",
     "            return literal_text(node.left, constants, depth + 1)"),
    ("M15 a %-format template is no longer read",
     '        if isinstance(node.op, ast.Mod):  # "%s done" % value',
     "        if isinstance(node.op, ast.Mod) and False:"),
    ("M16 .format() and .join() templates are no longer read",
     '        if node.func.attr in ("format", "join"):',
     '        if node.func.attr in ("format_never", "join_never"):'),
    ("M17 sep= and end= stop being console text",
     '        if kw.arg in ("sep", "end"):',
     '        if kw.arg in ("sep_never", "end_never"):'),
    ("M18 the same character is listed once per occurrence",
     "                if not encodable(ch, codec) and ch not in bad:",
     "                if not encodable(ch, codec):"),
    ("M19 findings come back in whatever order the walk produced",
     '    rows.sort(key=lambda r: (r["line"], r["call"]))',
     "    pass"),
    ("M20 __main__ alone no longer marks a file that decides an exit status",
     '    return "sys.exit(" in text or \'__name__ == "__main__"\' in text or "__name__ == \'__main__\'" in text',
     '    return "sys.exit(" in text'),
    ("M21 --exclude is ignored",
     "            if any(fnmatch.fnmatch(posix, pat) or fnmatch.fnmatch(q.name, pat) for pat in excludes):\n                continue",
     "            if False:\n                continue"),
    ("M22 a protected file still sets the exit status to 1",
     '    return 1 if any(f["rows"] and not f["protected"] for f in files) else 0',
     '    return 1 if any(f["rows"] for f in files) else 0'),
    ("M23 the same file named twice is scanned twice",
     "            if q not in seen:\n                seen.append(q)",
     "            seen.append(q)"),
    ("M24 a file that will not parse takes the whole scan down with it",
     "        except ScanError as exc:\n            skipped.append",
     "        except ZeroDivisionError as exc:\n            skipped.append"),
]


def run_tests():
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-q"],
                          capture_output=True, cwd=str(HERE))
    return proc.returncode == 0


def main():
    original = SRC.read_text(encoding="utf-8")
    shutil.copy2(SRC, BAK)
    survivors, applied = [], 0
    try:
        if not run_tests():
            sys.stdout.write("the suite does not pass on the unmutated file; stopping.\n")
            return 2
        sys.stdout.write("baseline: green\n\n")
        for label, before, after in MUTATIONS:
            if original.count(before) != 1:
                sys.stdout.write("SKIPPED (pattern not unique): {}\n".format(label))
                survivors.append(label + "   [pattern not found]")
                continue
            SRC.write_text(original.replace(before, after), encoding="utf-8")
            applied += 1
            caught = not run_tests()
            sys.stdout.write("{}  {}\n".format("caught " if caught else "SURVIVED", label))
            if not caught:
                survivors.append(label)
    finally:
        shutil.copy2(BAK, SRC)
        BAK.unlink()
    sys.stdout.write("\n{} mutations applied, {} survived\n".format(applied, len(survivors)))
    for s in survivors:
        sys.stdout.write("  survived: {}\n".format(s))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
