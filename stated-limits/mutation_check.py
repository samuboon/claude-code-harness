# -*- coding: utf-8 -*-
"""Break stated_limits.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has watched fail is decoration -- which is the same claim this tool
makes about a limit nobody counts, so it would be poor form not to check our own. This
edits a copy of the tool in twenty-four specific ways, each one a mistake a checker of
this kind plausibly makes, runs the suite against each, and reports every mutation the
suite lets through. Exit 0 means all of them were caught.

The original file is restored in a finally block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "stated_limits.py"
BAK = HERE / "stated_limits.py.mutation-backup"

MUTATIONS = [
    ("M1  a value equal to the ceiling counts as over it",
     "    over = [name for name, ceiling in ceilings if actual > ceiling]",
     "    over = [name for name, ceiling in ceilings if actual >= ceiling]"),
    ("M2  the comparison is inverted, so only files under the ceiling are reported",
     "    over = [name for name, ceiling in ceilings if actual > ceiling]",
     "    over = [name for name, ceiling in ceilings if actual < ceiling]"),
    ("M3  line counting is off by one",
     '        return float(len(text.splitlines())), "splitlines"',
     '        return float(len(text.splitlines()) - 1), "splitlines"'),
    ("M4  a per-line ceiling is checked against the first line, not the longest",
     "            worst = max(range(len(lines)), key=lambda i: len(lines[i]))",
     "            worst = 0"),
    ("M5  a combined ceiling is checked against the largest file, not the sum",
     "            actual = sum(parts)",
     "            actual = max(parts)"),
    ("M6  a directory is summed when the rule said each file",
     '        total = sum(measure(f, unit, "whole", excludes, root)[0] for f in targets)',
     '        total = max(measure(f, unit, "whole", excludes, root)[0] for f in targets)'),
    ("M7  an event ceiling (3 pushes a week) is treated as measurable",
     '    if limit["unit"] == _UNIT_EVENTS:',
     "    if False:"),
    ("M8  a ceiling that names no file is quietly dropped instead of reported",
     "    if not targets:\n        if allow_self and _SELF_REF.search(sentence):",
     "    if not targets and False:\n        if allow_self and _SELF_REF.search(sentence):"),
    ("M9  a ceiling naming a file that does not exist is judged anyway",
     "    if not resolved:",
     "    if resolved and False:"),
    ("M10 the report prints the characters a console cannot encode",
     '            out.append("<U+%04X>" % ord(ch) if name is None else "<%s>" % _short(ch, name))',
     "            out.append(ch)"),
    ("M11 newlines are transcoded too, so the whole report becomes one line",
     '        if ch == "\\n":\n            out.append(ch)  # a report is lines',
     '        if False:\n            out.append(ch)  # a report is lines'),
    ("M12 fenced code blocks are read, so every number in an example becomes a rule",
     "        if fenced:\n            continue",
     "        if False:\n            continue"),
    ("M13 table cells are not split, so a ceiling binds to a file in another column",
     '        for cell in line.split("|"):',
     "        for cell in [line]:"),
    ("M14 markdown emphasis is left in place, hiding every bold limit",
     '    return "".join(" " if ch in "*~" else ch for ch in text)',
     "    return text.replace('*', '')"),
    ("M15 an https link is taken for a file to measure",
     '        if not raw or raw.startswith(("http://", "https://", "#", "mailto:")):',
     "        if not raw:"),
    ("M16 a glob is taken for a file to measure",
     '        if "*" in raw or " " in raw or raw.startswith("-"):',
     '        if " " in raw or raw.startswith("-"):'),
    ("M17 a target is carried across lines, binding a ceiling to a file above it",
     "            if lineno != carried_line:",
     "            if False:"),
    ("M18 targets are never carried, so a two-clause rule loses its files",
     "                targets, inherited = carried, True",
     "                targets, inherited = [], False"),
    ("M19 KB is read one way only, so a borderline size is reported as a fact",
     '    return [("SI 1000", si), ("binary 1024", iec)]',
     '    return [("binary 1024", iec)]'),
    ("M20 over under one reading of KB is reported as a breach",
     '        row["status"] = "borderline"',
     '        row["status"] = "breach"'),
    ("M21 an unverifiable limit fails the caller's build",
     '    return 1 if any(r["status"] == "breach" for r in rows) else 0',
     "    return 1 if rows else 0"),
    ("M22 CRLF is left in, so a character count is two per line larger on Windows",
     '            return data.decode(codec).replace("\\r\\n", "\\n").replace("\\r", "\\n")',
     "            return data.decode(codec)"),
    ("M23 an empty directory measures as zero instead of saying it measured nothing",
     '            raise ScanError("no files under %s" % _rel(path, root))',
     '            return 0.0, "empty"'),
    ("M24 every number becomes a ceiling, cap word or not",
     "    if not capped:\n        return _build(sentence, [])",
     "    if not capped:\n        return _build(sentence, qtys)"),
]


def run_tests():
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-q"],
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
