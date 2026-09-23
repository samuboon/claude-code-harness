# -*- coding: utf-8 -*-
"""Break forge_scope_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker
of this kind plausibly makes; the first one is the whole point of the tool turned off
(any one declared scope of a set counts as enough). The script runs the suite against each
mutated copy and reports any mutation the suite lets through. Exit code 0 means every one
was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "forge_scope_check.py"
BAK = HERE / "forge_scope_check.py.mutation-backup"

MUTATIONS = [
    ("M1  half a granular set counts as enough",
     "            ok_g = bool(granular) and granular <= declared",
     "            ok_g = bool(granular) and bool(granular & declared)"),
    ("M2  a call with no stated scope is treated as satisfied by classic alone",
     "            ok_c = bool(classic) and classic <= declared",
     "            ok_c = classic <= declared"),
    ("M3  Jira Software missing scopes reported through the classic branch",
     "            if key.split(\" \", 1)[1].startswith(SOFTWARE_PREFIXES) or not classic:",
     "            if key.split(\" \", 1)[1].startswith(SOFTWARE_PREFIXES) and not classic and False:"),
    ("M4  every call read as GET",
     "    m = re.search(r\"\\bmethod\\s*:\\s*(['\\\"`])(\\w+)\\1\", opts)",
     "    m = None"),
    ("M5  unknown method (variable options) guessed as GET",
     "        return None  # method: someVariable / shorthand { method }",
     "        return \"GET\""),
    ("M6  options scanned past the call's own closing brace",
     "            depth -= 1\n            if depth == 0:\n                return \"literal\", text[start:i + 1]",
     "            depth -= 1\n            if depth == -1:\n                return \"literal\", text[start:i + 1]"),
    ("M7  deprecated calls never fail",
     "                (res[\"warnings\"] if allow_deprecated else res[\"findings\"]).append((\"DEPRECATED\", where, msg))",
     "                res[\"warnings\"].append((\"DEPRECATED\", where, msg))"),
    ("M8  unchecked calls count as a pass",
     "    if res[\"unchecked\"]:\n        return 3",
     "    if False:\n        return 3"),
    ("M9  UI resolver not recognised, so every asUser() is flagged",
     "                function_refs(v, under_resolver or k == \"resolver\", out)",
     "                function_refs(v, under_resolver, out)"),
    ("M10 asUser() in a UI-reached function flagged anyway",
     "        if any(ui for _m, ui in uses) or fn not in handlers:",
     "        if fn not in handlers:"),
    ("M11 a file shared with a UI resolver still flagged as a hard finding",
     "    merged = [(path, line, sorted(g[0]), sorted(g[1]), path in ui_files)",
     "    merged = [(path, line, sorted(g[0]), sorted(g[1]), False)"),
    ("M12 literal path segments in the code refuse to match a parameter",
     "            elif b == \"{}\" and \"{}\" not in a:",
     "            elif False:"),
    ("M13 a parameter beats an exact literal (createmeta read as issue/{})",
     "            if score > best_score:",
     "            if score < best_score or best_score < 0:"),
    ("M14 v2 paths not mapped to v3",
     "        path = \"/rest/api/3/\" + path.split(\"/\", 4)[4]",
     "        pass"),
    ("M15 wrappers not followed",
     "    if last is None or arg.group(1) not in (last.group(2), last.group(3)):",
     "    if True:"),
    ("M16 node_modules scanned",
     "        if p.suffix in CODE_EXT and p.is_file() and not (set(p.relative_to(app).parts) & SKIP_DIRS):",
     "        if p.suffix in CODE_EXT and p.is_file():"),
    ("M17 'unused' claimed even while some calls are unchecked",
     "    if not res[\"unchecked\"]:",
     "    if True:"),
    ("M18 redundant-classic warning fires when granular only half covers",
     "        if keys and all(ops[k][\"granular\"] and set(ops[k][\"granular\"]) <= declared for k in keys):",
     "        if keys and any(set(ops[k][\"granular\"]) & declared for k in keys):"),
    ("M19 options held in a constant not read",
     "    if kind == \"ident\":",
     "    if kind == \"ident\" and False:"),
    ("M20 comments read as code",
     "    texts = {p: strip_js_comments(p.read_text(encoding=\"utf-8\", errors=\"replace\")) for p in files}",
     "    texts = {p: p.read_text(encoding=\"utf-8\", errors=\"replace\") for p in files}"),
    ("M21 findings do not change the exit code",
     "    if res[\"findings\"]:\n        return 1",
     "    if False:\n        return 1"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_forge_scope_check"],
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
