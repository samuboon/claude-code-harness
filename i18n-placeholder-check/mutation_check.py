# -*- coding: utf-8 -*-
"""Break i18n_placeholder_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- most of them are a place where it is easy to be "almost" like
java.text.MessageFormat. The script runs the suite against each mutated copy and reports any
mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "i18n_placeholder_check.py"
BAK = HERE / "i18n_placeholder_check.py.mutation-backup"

MUTATIONS = [
    ("M1  '' read as a quote toggle instead of one apostrophe",
     "                if i + 1 < len(p) and p[i + 1] == \"'\":\n                    segs[part] += ch\n                    res.render += ch",
     "                if False:\n                    segs[part] += ch\n                    res.render += ch"),
    ("M2  a brace inside quotes starts an argument",
     "            elif ch == \"{\" and not in_quote:",
     "            elif ch == \"{\":"),
    ("M3  the argument index is trimmed (Java does not)",
     "    idx = _java_parse_int(segs[1])",
     "    idx = _java_parse_int(segs[1].strip())"),
    ("M4  an unmatched brace is accepted",
     "    if brace == 0 and part != SEG_RAW:\n        raise PatternError(\"Unmatched braces in the pattern.\")",
     "    if False:\n        raise PatternError(\"Unmatched braces in the pattern.\")"),
    ("M5  unknown format types accepted",
     "    if typ is None:\n        raise PatternError(\"unknown format type: \" + segs[2])",
     "    if typ is None:\n        typ = segs[2]"),
    ("M6  choice branches not read as nested messages",
     "                if \"{\" not in text:\n                    continue",
     "                if True:\n                    continue"),
    ("M7  choice limits not validated",
     "            start = _java_parse_double(seg[0])",
     "            start = 0.0"),
    ("M8  a quoted section with a brace also counts as a stray apostrophe",
     "    if any(\"{\" not in sec and \"}\" not in sec for sec in parsed.sections):",
     "    if parsed.sections:"),
    ("M9  QUOTED folded into MISSING",
     "        quoted = [k for k in missing if re.search(r\"\\{\\s*%d\\s*[,}]\" % k, hidden)]",
     "        quoted = []"),
    ("M10 extra placeholders not reported",
     "        if extra:\n            findings.append((tpath, tline, \"EXTRA\"",
     "        if False:\n            findings.append((tpath, tline, \"EXTRA\""),
    ("M11 a dropped type reported as TYPE",
     "            added = (ttypes[k] - {\"\"}) - (btypes[k] - {\"\"})",
     "            added = ttypes[k] ^ btypes[k]"),
    ("M12 every value read as MessageFormat by default",
     "        as_mf = always_mf or bool(btypes)",
     "        as_mf = True"),
    ("M13 properties continuation keeps the next line's indentation",
     "            seg = nat[i].lstrip(\" \\t\\f\")",
     "            seg = nat[i]"),
    ("M14 an even run of backslashes continues the line",
     "            if bs % 2 == 0:\n                break",
     "            if bs == 0:\n                break"),
    ("M15 a malformed \\u escape is let through",
     "                raise PropertiesError(lineno, \"Malformed \\\\uxxxx encoding.\")",
     "                out.append(\"?\")\n                continue"),
    ("M16 BOM stripped silently (hides the broken first key)",
     "    for key in [k for k in entries if k.startswith(\"\\ufeff\")]:",
     "    for key in []:"),
    ("M17 a translation with no base file counted as a pass",
     "    if unchecked:\n        return 3",
     "    if False:\n        return 3"),
    ("M18 --key-as-base compares id keys with themselves",
     "        elif key_as_base and _looks_like_text(key):",
     "        elif key_as_base:"),
    ("M19 the shortest stem is tried first (Messages_pt for Messages_pt_BR)",
     "    for c in reversed(cuts):",
     "    for c in cuts:"),
    ("M20 standalone files self-checked by default (configuration read as messages)",
     "        for key, (line, val) in (bentries.items() if trans or always_mf else ()):",
     "        for key, (line, val) in bentries.items():"),
    ("M21 warnings fail without --strict",
     "    if errors or (a.strict and warnings):",
     "    if errors or warnings:"),
    ("M23 Java 25's extra format types accepted under Java 21",
     "    typ = _find_keyword(segs[2], TYPES_25 if JAVA[\"version\"] >= 25 else TYPES_21)",
     "    typ = _find_keyword(segs[2], TYPES_25)"),
    ("M24 Java 21 reads '#' inside a choice branch as text (it throws)",
     "        elif ch in \"<#\\u2264\" and j25 and part == 1:",
     "        elif ch in \"<#\\u2264\" and part == 1:"),
    ("M25 no upper limit on the argument index",
     "    if idx >= MAX_ARGUMENT_INDEX:",
     "    if False:"),
    ("M26 an infinity limit with a space before it accepted (Java compares before trimming)",
     "    if s == \"\\u221e\":",
     "    if s.strip() == \"\\u221e\":"),
    ("M22 an orphan key's value is not checked",
     "                findings.append((tpath, tline, \"ORPHAN\", key, \"not in the base file\"))\n            check_value(tpath, tline, key, tval, always_mf, findings)",
     "                findings.append((tpath, tline, \"ORPHAN\", key, \"not in the base file\"))"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_i18n_placeholder_check"],
                       cwd=str(HERE), capture_output=True, text=True)
    return r.returncode == 0


def main():
    original = SRC.read_text(encoding="utf-8")
    if not run_tests():
        print("the unmutated suite already fails; fix that first")
        return 2
    shutil.copyfile(SRC, BAK)
    survivors = []
    try:
        for name, old, new in MUTATIONS:
            if original.count(old) != 1:
                print("SKIP-BROKEN  %s  (pattern found %d times)" % (name, original.count(old)))
                survivors.append(name + " [pattern missing]")
                continue
            SRC.write_text(original.replace(old, new), encoding="utf-8")
            caught = not run_tests()
            print("%-7s %s" % ("caught" if caught else "SURVIVED", name))
            if not caught:
                survivors.append(name)
    finally:
        shutil.copyfile(BAK, SRC)
        BAK.unlink()
    print("%d of %d mutations caught" % (len(MUTATIONS) - len(survivors), len(MUTATIONS)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
