# -*- coding: utf-8 -*-
"""Break einvoice_total_check.py on purpose, one line at a time, and check the tests notice.

    python mutation_check.py

A test suite nobody has seen fail is decoration. Each mutation below is a mistake a checker
of this kind plausibly makes; the first one widens the official VAT tolerance, the second
makes a SPLIT count as a pass. The script runs the suite against each mutated copy and
reports any mutation the suite lets through. Exit code 0 means every one was caught.

The original file is restored in a `finally` block, including on Ctrl-C.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "einvoice_total_check.py"
BAK = HERE / "einvoice_total_check.py.mutation-backup"

MUTATIONS = [
    ("M1  BR-S-09 tolerance widened to 2",
     "            hold = abs(calc) - 1 < expect < abs(calc) + 1",
     "            hold = abs(calc) - 2 < expect < abs(calc) + 2"),
    ("M2  a SPLIT counted as a pass",
     "    if res[\"split\"]:\n        return 3",
     "    if False:\n        return 3"),
    ("M3  BR-CO-17 tolerance read as strictly less than 1",
     "            hold = abs(calc) - 1 <= expect <= abs(calc) + 1",
     "            hold = abs(calc) - 1 < expect < abs(calc) + 1"),
    ("M4  a SPLIT rule that fails the primary reading reported as a failure",
     "    failed = [r for r in RULES if not res[\"rules\"][r][0] and r not in res[\"split\"]]",
     "    failed = [r for r in RULES if not res[\"rules\"][r][0]]"),
    ("M5  UBL reported as unreadable instead of unchecked",
     "        return None, \"ubl\", \"UBL syntax; only CII is read\"",
     "        return None, \"unreadable\", \"UBL syntax; only CII is read\""),
    ("M6  whole-unit rounding accepted for every amount",
     "        if basis == basis.to_integral_value() and calc == calc.to_integral_value():",
     "        if True:"),
    ("M7  --strict does not change the exit code",
     "    if failed or (strict and res[\"strict\"]):",
     "    if failed:"),
    ("M8  BR-CO-14 compares a total VAT in another currency",
     "    tax_in_cur = [e for e in kids(h, \"TaxTotalAmount\") if e.get(\"currencyID\") == cur]",
     "    tax_in_cur = kids(h, \"TaxTotalAmount\")"),
    ("M9  BR-S-08 ignores allowances",
     "a.r2(parts[0]) + a.r2(parts[1]) - a.r2(parts[2])",
     "a.r2(parts[0]) + a.r2(parts[1])"),
    ("M10 BR-CO-16 ignores the paid amount",
     "        want = want - TP if TP is not None else None",
     "        want = want"),
    ("M11 BR-CO-17 accepts any amount when there is no rate",
     "            hold = _round0(calc) == 0\n            d17.append(\"%s no rate",
     "            hold = True\n            d17.append(\"%s no rate"),
    ("M12 no double-precision reading",
     "          Arith(\"double\", _flt, _r2_double)]",
     "          ]"),
    ("M13 no second tie rule",
     "ARITHS = [Arith(\"decimal\", _dec, _r2_ceil), Arith(\"decimal-away\", _dec, _r2_away),",
     "ARITHS = [Arith(\"decimal\", _dec, _r2_ceil),"),
    ("M14 BR-CO-10 sum not rounded",
     "    want = a.r2(s) if s is not None else None\n    out[\"BR-CO-10\"]",
     "    want = s\n    out[\"BR-CO-10\"]"),
    ("M15 BR-CO-15 without its 'total with VAT = total without' branch",
     "        hold = (want is not None and GT == want) or (GT is not None and GT == TB)",
     "        hold = want is not None and GT == want"),
    ("M16 allowances and charges not told apart",
     "        items = [x for x in acs if flag(x) is is_charge]",
     "        items = [x for x in acs if flag(x) is not None]"),
    ("M17 BR-CO-13 adds allowances",
     "        want = a.r2(LT - AT + CT) if None not in parts else None",
     "        want = a.r2(LT + AT + CT) if None not in parts else None"),
    ("M18 a SPLIT outranks a failure across files",
     "    order = {0: 0, 3: 1, 1: 2, 2: 3}",
     "    order = {0: 0, 3: 2, 1: 1, 2: 3}"),
    ("M19 STRICT-VAT accepts any amount within a cent",
     "        if calc not in allowed:",
     "        if min(abs(calc - x) for x in allowed) > CENT:"),
    ("M20 a missing total counted as zero",
     "    def total(vals):\n        return None if None in vals else sum(vals, a.zero())",
     "    def total(vals):\n        return sum((v for v in vals if v is not None), a.zero())"),
]


def run_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_einvoice_total_check"],
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
