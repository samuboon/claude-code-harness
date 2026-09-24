# -*- coding: utf-8 -*-
"""Break table_total_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker of
this kind plausibly makes -- most of them are a place where re-adding a table is easy to get
wrong (a subtotal added in twice, a rounded column compared exactly, an average taken for an
error, a guess made where the cell reads two ways). The script runs the suite against each mutated
copy and reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "table_total_check.py"
BAK = HERE / "table_total_check.py.mutation-backup"

MUTATIONS = [
    # labels
    ("M1  'Total time' read as a total row",
     "    return bool(cell) and bool(TOTAL_RE.fullmatch(label_text(cell)))",
     "    return bool(cell) and bool(TOTAL_RE.match(label_text(cell)))"),
    ("M2  'Total (USD):' not read as a total row",
     "    s = clean(cell).rstrip(\":：\").strip()",
     "    s = clean(cell)"),
    ("M3  an Average row added into the total",
     "    if is_agg_label(cell):\n        return \"agg\"",
     "    if False:\n        return \"agg\""),
    ("M3b 'AVG-001' read as an Average row",
     "(?=\\s|$|[:(])\", label_text(cell), re.I))",
     "\", label_text(cell), re.I))"),
    ("M4  a Year column summed",
     "        idcol = [c <= lab or bool(ID_HEAD_RE.fullmatch(label_text(t.header[c]) or \"\")) for c in range(ncol)]",
     "        idcol = [c <= lab for c in range(ncol)]"),
    ("M4b the row-number column left of the label summed",
     "        idcol = [c <= lab or bool(",
     "        idcol = [c == lab or bool("),
    # named totals, rates, rounding by trailing zeros
    ("M4c 'Batch 1 Subtotal' read as a row to add",
     "        if SUB_NAMED_RE.fullmatch(lt):\n            return \"sub\"",
     "        if False:\n            return \"sub\""),
    ("M4d a named total that adds up the rows above not allowed to stand for them",
     "                    items.append(i)\n                else:\n                    items += run + [i]",
     "                    items += run + [i]\n                else:\n                    items += run + [i]"),
    ("M4e percentages that are rates flagged",
     "                if tv.pct and s > 100 and tv.value <= 100:",
     "                if False:"),
    ("M4f 19,850,000 + 80,000 compared exactly",
     "and all(trailing_zeros(n.value) >= 3 for n in allv):",
     "and False:"),
    ("M4g 100 + 200 = 301 given rounding slack",
     "all(trailing_zeros(n.value) >= 3 for n in allv)",
     "all(trailing_zeros(n.value) >= 2 for n in allv)"),
    ("M4h 1.429 under whole numbers read as a decimal",
     "    return any(n.amb for n in nums) and any(n.dec == 0 for n in nums)",
     "    return False"),
    ("M4i a '...' row not noticed",
     "            if any(clean(x) in ELIDED for i in parts for x in rows[i][1]):",
     "            if False:"),
    ("M4j a total over one row not checked",
     "        if not nums:\n            return None\n        if ambiguous",
     "        if len(nums) < 2:\n            return None\n        if ambiguous"),
    ("M4k IDR1,194,606 not read",
     "|\" + CODES + r\"|Rp",
     "|Rp"),
    # blocks
    ("M5  subtotals added in again under the grand total",
     "                parts = [j for j in range(last_total, i) if kinds[j] == \"data\"]",
     "                parts = [j for j in range(last_total, i) if kinds[j] in (\"data\", \"sub\")]"),
    ("M6  a total at the top compared with nothing",
     "        if len(tot) == 1 and all(k != \"data\" for k in kinds[:tot[0]]):",
     "        if False:"),
    # numbers
    ("M7  thousands commas read as decimals",
     "        intpart, _, frac = raw.replace(\",\", \"\").partition(\".\")",
     "        intpart, _, frac = raw.replace(\".\", \"\").partition(\",\")"),
    ("M8  the column's decimal commas not used",
     "    hints = [comma_decimal_hint([r[1][c] for r in rows]) for c in range(ncol)]",
     "    hints = [False for c in range(ncol)]"),
    ("M9  (20) read as +20",
     "        neg = True\n    elif m.group(\"close\"):",
     "        neg = False\n    elif m.group(\"close\"):"),
    ("M10 1 200 (a space between thousands) not read",
     "        raw = re.sub(",
     "        raw = raw or re.sub("),
    ("M11 '100+' read as 100",
     "    if m.group(\"suf\") and m.group(\"suf\").strip().endswith(\"+\"):\n        return None",
     "    if False:\n        return None"),
    ("M12 a struck-through value read",
     "    if \"~~\" in s or re.search(r\"<(?:del|s|strike)[\\s>]\", cell, re.I):",
     "    if False:"),
    ("M13 1.2.3 read as a number",
     "        if not re.fullmatch(r\"\\d{1,3}(?:,\\d{3})*(?:\\.\\d+)?|\\d+(?:\\.\\d+)?|\\.\\d+\", raw):\n            return None",
     "        if False:\n            return None"),
    # judging
    ("M14 whole numbers given rounding slack",
     "        return Decimal(0)\n    return ulp(tv.dec)",
     "        return Decimal(1)\n    return ulp(tv.dec)"),
    ("M15 decimals compared exactly",
     "    return ulp(tv.dec) + sum((ulp(n.dec) for n in nums), Decimal(0))\n\n\ndef fmt",
     "    return Decimal(0)\n\n\ndef fmt"),
    ("M16 money with cents given rounding slack",
     "(\"money\" in cls or all(n.dec == 0 for n in allv))",
     "all(n.dec == 0 for n in allv)"),
    ("M17 mixed units added anyway",
     "            if len(u2) > 1:\n                if not quiet:",
     "            if False:\n                if not quiet:"),
    ("M18 text among the rows skipped over",
     "        if any(v is None for v in vals):\n            if not quiet:",
     "        if False:\n            if not quiet:"),
    ("M19 a blank row not mentioned (error, not warning)",
     "                if blanks:\n                    self.add(\"warning\", \"TOTAL?\"",
     "                if False:\n                    self.add(\"warning\", \"TOTAL?\""),
    ("M20 a column of averages flagged",
     "        if abs(t - sum(nums) / len(nums)) <= tol:\n            return \"mean\"",
     "        if False:\n            return \"mean\""),
    ("M21 a max flagged",
     "            if abs(t - v) <= (ulp(tv.dec) if tv.dec < d else (ulp(d) if rounded else 0)) + Decimal(\"1e-9\"):",
     "            if False:"),
    ("M22 whole numbers explained within +-1 (2021 taken for the max, 2020)",
     "(ulp(tv.dec) if tv.dec < d else (ulp(d) if rounded else 0))",
     "(ulp(tv.dec) + ulp(d))"),
    ("M23 a weighted mean flagged",
     "                    if abs(t - wm) <= tol:\n                        return \"weighted mean\"",
     "                    if False:\n                        return \"weighted mean\""),
    ("M23b whole-number parts given their rounding in the mean",
     "part_err = sum((ulp(v.dec) for v in nv), Decimal(0)) / len(nv) if rounded else Decimal(0)",
     "part_err = sum((ulp(v.dec) for v in nv), Decimal(0)) / len(nv)"),
    ("M24 anything accepted as 'explained'",
     "                expl = self.explain(tv, vals, parsed, ti, c, parts, ncol)",
     "                expl = \"x\""),
    # row totals
    ("M25 row totals: every left column added (the Weight column too)",
     "            key = (good, len(comp))\n            if results and (best is None or key > best[0]):",
     "            key = (len(comp), good)\n            if results and (best is None or key > best[0]):"),
    ("M26 row totals: one agreeing row is enough",
     "        if good < 2 or good * 2 < len(results):",
     "        if good < 1:"),
    ("M27 row totals: a total column on the left not tried",
     "            if j in right:\n                run.append(j)",
     "            if False:\n                run.append(j)"),
    # shares
    ("M28 shares: no rows compared",
     "            if good < 2 or good * 3 < len(res) * 2:",
     "            if True:"),
    # reading
    ("M29 code fences read as tables",
     "        if fence:\n            if fm",
     "        if False:\n            if fm"),
    ("M30 HTML comments read as tables",
     "        if s.lstrip().startswith(\"<!--\") and \"-->\" not in s:",
     "        if False:"),
    ("M31 an escaped pipe split",
     "        if c == \"\\\\\" and i + 1 < len(s) and s[i + 1] == \"|\":",
     "        if False:"),
    ("M32 link text not read",
     "    s = MD_LINK.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), cell)",
     "    s = cell"),
    ("M33 exit code 0 on errors",
     "    return 1 if errors or (a.strict and warnings) else 0",
     "    return 0"),
]


def run_tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_table_total_check"],
                       cwd=str(HERE), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
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
            print("%-8s %s" % ("caught" if caught else "SURVIVED", name))
            if not caught:
                survivors.append(name)
    finally:
        shutil.copyfile(BAK, SRC)
        BAK.unlink()
    print("%d of %d mutations caught" % (len(MUTATIONS) - len(survivors), len(MUTATIONS)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
