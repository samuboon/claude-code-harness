# -*- coding: utf-8 -*-
"""Change one amount at a time in each official example invoice and count how often the rule it
belongs to catches it. This is the second table in README.md.

    git clone --depth 1 https://github.com/ConnectingEurope/eInvoicing-EN16931
    python break_examples.py eInvoicing-EN16931/cii/examples

Nothing is written to disk; the examples are changed in memory.
"""
import copy
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import einvoice_total_check as etc

HEAD = "SpecifiedTradeSettlementHeaderMonetarySummation"
# (label, parent, element, delta, rule that must fail)
CHANGES = [
    ("line total +1", HEAD, "LineTotalAmount", Decimal("1"), "BR-CO-10"),
    ("allowance total +0.01", HEAD, "AllowanceTotalAmount", Decimal("0.01"), "BR-CO-11"),
    ("charge total +0.01", HEAD, "ChargeTotalAmount", Decimal("0.01"), "BR-CO-12"),
    ("total without VAT +0.01", HEAD, "TaxBasisTotalAmount", Decimal("0.01"), "BR-CO-13"),
    ("total with VAT +0.01", HEAD, "GrandTotalAmount", Decimal("0.01"), "BR-CO-15"),
    ("amount due +0.01", HEAD, "DuePayableAmount", Decimal("0.01"), "BR-CO-16"),
    ("standard-rate taxable amount +0.01", "S-tax", "BasisAmount", Decimal("0.01"), "BR-S-08"),
    ("standard-rate VAT +2", "S-tax", "CalculatedAmount", Decimal("2"), "BR-S-09"),
]


def bump(root, parent, name, delta):
    """Add delta to the first matching element; parent "S-tax" is the header's standard-rate breakdown."""
    for h in root.iter():
        if parent == "S-tax":
            if etc.local(h) != "ApplicableTradeTax" or not any(etc.text(c) == "S" for c in etc.kids(h, "CategoryCode")):
                continue
            if not etc.kids(h, "BasisAmount"):  # a line's tax has no taxable amount; only the header breakdown
                continue
        elif etc.local(h) != parent:
            continue
        for c in etc.kids(h, name):
            v = etc._dec(etc.text(c))
            if v is not None:
                c.text = str(v + delta)
                return True
    return False


def failed(root):
    res = etc.check_root(root)
    return {r for r in etc.RULES if not res["rules"][r][0]}, res


def main(folder):
    files = sorted(Path(folder).glob("*.xml"))
    if not files:
        print("no .xml files in %s" % folder)
        return 2
    counts = {c[0]: [0, 0] for c in CHANGES}
    slack = [0, 0, 0]  # applied / every official rule passes / STRICT-VAT flags
    for f in files:
        root = ET.parse(f).getroot()
        for label, parent, name, delta, rule in CHANGES:
            m = copy.deepcopy(root)
            if not bump(m, parent, name, delta):
                continue
            counts[label][0] += 1
            counts[label][1] += rule in failed(m)[0]
        m = copy.deepcopy(root)
        if bump(m, "S-tax", "CalculatedAmount", Decimal("0.99")):
            for name in ("TaxTotalAmount", "GrandTotalAmount", "DuePayableAmount"):
                bump(m, HEAD, name, Decimal("0.99"))
            fails, res = failed(m)
            slack[0] += 1
            slack[1] += not fails
            slack[2] += bool(res["strict"])
    print("| Change | Invoices it applies to | Caught by the rule it belongs to |")
    print("|---|---:|---:|")
    for label, (n, c) in counts.items():
        print("| %s | %d | %d |" % (label, n, c))
    print("| standard-rate VAT +0.99, with the totals moved to match | %d | %d pass every official rule; "
          "STRICT-VAT flags %d |" % tuple(slack))
    missed = sum(n - c for n, c in counts.values())
    return 1 if missed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
