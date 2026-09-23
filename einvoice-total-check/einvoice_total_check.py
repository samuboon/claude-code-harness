# -*- coding: utf-8 -*-
"""Recompute the totals and VAT amounts of an EN 16931 CII e-invoice (the XML inside ZUGFeRD /
Factur-X, and XRechnung in CII syntax) and say which declared amount disagrees, and by how much.

    python einvoice_total_check.py invoice.xml [more.xml ...]
    python einvoice_total_check.py invoice.xml --strict      # the VAT amount must match to the cent
    python einvoice_total_check.py invoice.xml --tsv         # one row per rule and file

Rules (all "fatal" in the official EN 16931 CII rule set, re-read from its Schematron binding):
  BR-CO-10 line total      BR-CO-11 allowances      BR-CO-12 charges        BR-CO-13 total without VAT
  BR-CO-14 total VAT       BR-CO-15 total with VAT  BR-CO-16 amount due
  BR-S-08  standard-rated taxable amount per rate   BR-S-09 standard-rated VAT amount (tolerance < 1.00)
  BR-CO-17 VAT amount of every VAT breakdown (tolerance <= 1.00)
Not an official rule, reported separately:
  STRICT-VAT  the VAT amount of a breakdown differs from taxable amount x rate, rounded to the cent

Exit codes: 0 = every rule checked, all hold. 1 = at least one rule fails (or, with --strict,
a STRICT-VAT finding). 2 = not readable as a CII invoice. 3 = nothing failed, but a rule came out
differently under two readings of the official arithmetic (SPLIT) or the file is UBL, which this
does not read. 3 is not a pass.

Standard library only. This is not the official validator: it does not check the schema, code
lists, mandatory fields or any of the ~770 other rules.
"""
import argparse
import math
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP

RULES = ["BR-CO-10", "BR-CO-11", "BR-CO-12", "BR-CO-13", "BR-CO-14", "BR-CO-15", "BR-CO-16",
         "BR-S-08", "BR-S-09", "BR-CO-17"]
CENT = Decimal("0.01")


def local(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def kids(el, name):
    return [c for c in el if local(c) == name] if el is not None else []


def walk(el, *names):
    cur = [el] if el is not None else []
    for n in names:
        cur = [c for e in cur for c in kids(e, n)]
    return cur


def text(el):
    return (el.text or "").strip() if el is not None else ""


# ---- arithmetic -----------------------------------------------------------------------------
# The official rules are XPath 2.0 inside XSLT. Some sums run over untyped values (xs:double),
# some cast to xs:decimal first, and round() breaks ties one way for decimals. Rather than
# pretend to know exactly which applies where, every rule is evaluated three ways and a rule
# that does not come out the same in all three is reported as SPLIT, not as a pass.

class Arith:
    def __init__(self, name, parse, r2):
        self.name, self.parse, self.r2 = name, parse, r2

    def num(self, el):
        return self.parse(text(el)) if el is not None else None

    def zero(self):
        return self.parse("0")


def _dec(s):
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return v if v.is_finite() else None


def _flt(s):
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _r2_ceil(x):  # round(x*100) div 100, ties toward +infinity (XPath fn:round)
    return (x * 100 + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR) / 100


def _r2_away(x):  # ties away from zero
    return (x * 100).to_integral_value(rounding=ROUND_HALF_UP) / 100


def _r2_double(x):
    return math.floor(x * 100 + 0.5) / 100


ARITHS = [Arith("decimal", _dec, _r2_ceil), Arith("decimal-away", _dec, _r2_away),
          Arith("double", _flt, _r2_double)]


# ---- rules ----------------------------------------------------------------------------------

def fmt(v):
    if v is None:
        return "(missing)"
    if isinstance(v, float):
        return repr(v)
    return format(v, "f")


def evaluate(root, a):
    """{rule: (holds, detail)} under arithmetic a, or None when the invoice has no totals block."""
    tt = (kids(root, "SupplyChainTradeTransaction") or [None])[0]
    st = (kids(tt, "ApplicableHeaderTradeSettlement") or [None])[0]
    hs = kids(st, "SpecifiedTradeSettlementHeaderMonetarySummation")
    if not hs:
        return None
    h = hs[0]
    out = {}

    def first(name):
        k = kids(h, name)
        return a.num(k[0]) if k else None

    def has(name):
        return bool(kids(h, name))

    def total(vals):
        return None if None in vals else sum(vals, a.zero())

    def flag(ac):
        ind = walk(ac, "ChargeIndicator", "Indicator")
        return text(ind[0]) in ("true", "1") if ind else None

    def actual(ac):
        k = kids(ac, "ActualAmount")
        return a.num(k[0]) if k else None

    acs = kids(st, "SpecifiedTradeAllowanceCharge")
    LT, AT, CT = first("LineTotalAmount"), first("AllowanceTotalAmount"), first("ChargeTotalAmount")
    TB, GT = first("TaxBasisTotalAmount"), first("GrandTotalAmount")
    TP, RA, DP = first("TotalPrepaidAmount"), first("RoundingAmount"), first("DuePayableAmount")

    # BR-CO-10: sum of line net amounts
    lines = [a.num(e) for e in walk(tt, "IncludedSupplyChainTradeLineItem", "SpecifiedLineTradeSettlement",
                                     "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount")]
    s = total(lines)
    want = a.r2(s) if s is not None else None
    out["BR-CO-10"] = (want is not None and LT == want,
                       "LineTotalAmount %s, sum of %d line amounts = %s" % (fmt(LT), len(lines), fmt(want)))

    # BR-CO-11 / 12: document-level allowances and charges
    for rid, is_charge, name, label in (("BR-CO-11", False, "AllowanceTotalAmount", "allowances"),
                                        ("BR-CO-12", True, "ChargeTotalAmount", "charges")):
        items = [x for x in acs if flag(x) is is_charge]
        s = total([actual(x) for x in items])
        declared = first(name)
        if not items and not has(name):
            out[rid] = (True, "no document-level %s" % label)
        else:
            want = a.r2(s) if s is not None else None
            out[rid] = (want is not None and declared == want,
                        "%s %s, sum of %d %s = %s" % (name, fmt(declared), len(items), label, fmt(want)))

    # BR-CO-13: total without VAT
    if has("AllowanceTotalAmount") and has("ChargeTotalAmount"):
        parts, expr = (LT, AT, CT), "lines - allowances + charges"
        want = a.r2(LT - AT + CT) if None not in parts else None
    elif has("AllowanceTotalAmount"):
        parts, expr = (LT, AT), "lines - allowances"
        want = a.r2(LT - AT) if None not in parts else None
    elif has("ChargeTotalAmount"):
        parts, expr = (LT, CT), "lines + charges"
        want = a.r2(LT + CT) if None not in parts else None
    else:
        expr = "lines"
        want = a.r2(LT) if LT is not None else None
    out["BR-CO-13"] = (want is not None and TB == want,
                       "TaxBasisTotalAmount %s, %s = %s" % (fmt(TB), expr, fmt(want)))

    # BR-CO-14: total VAT in the invoice currency = sum of the breakdown's VAT amounts
    cur = text((kids(st, "InvoiceCurrencyCode") or [None])[0])
    breakdown = kids(st, "ApplicableTradeTax")
    tax_in_cur = [e for e in kids(h, "TaxTotalAmount") if e.get("currencyID") == cur]
    s = total([a.num((kids(t, "CalculatedAmount") or [None])[0]) for t in breakdown
               if kids(t, "CalculatedAmount")])
    want = a.r2(s) if s is not None else None
    if not tax_in_cur:
        out["BR-CO-14"] = (True, "no TaxTotalAmount in %s" % (cur or "(no currency)"))
    else:
        got = [a.num(e) for e in tax_in_cur]
        out["BR-CO-14"] = (want is not None and all(g == want for g in got),
                           "TaxTotalAmount %s, sum of %d breakdown VAT amounts = %s"
                           % (", ".join(fmt(g) for g in got), len(breakdown), fmt(want)))

    # BR-CO-15: total with VAT
    ok, details = True, []
    for c in kids(st, "InvoiceCurrencyCode"):
        tax = [e for e in kids(h, "TaxTotalAmount") if e.get("currencyID") == text(c)]
        tv = a.num(tax[0]) if len(tax) == 1 else None
        want = a.r2(TB + tv) if None not in (TB, tv) else None
        hold = (want is not None and GT == want) or (GT is not None and GT == TB)
        ok = ok and hold
        details.append("GrandTotalAmount %s, without VAT %s + VAT %s = %s"
                       % (fmt(GT), fmt(TB), fmt(tv), fmt(want)))
    out["BR-CO-15"] = (ok, "; ".join(details) or "no InvoiceCurrencyCode")

    # BR-CO-16: amount due (no rounding in the official rule)
    want = GT
    if want is not None and has("TotalPrepaidAmount"):
        want = want - TP if TP is not None else None
    if want is not None and has("RoundingAmount"):
        want = want + RA if RA is not None else None
    out["BR-CO-16"] = (want is not None and DP == want,
                       "DuePayableAmount %s, total with VAT - paid + rounding = %s" % (fmt(DP), fmt(want)))

    # BR-S-08 / BR-S-09: standard-rated breakdowns
    line_settle = walk(tt, "IncludedSupplyChainTradeLineItem", "SpecifiedLineTradeSettlement")

    def s_rate(el, rate):
        return any(text((kids(t, "CategoryCode") or [None])[0]) == "S"
                   and any(a.num(r) == rate for r in kids(t, "RateApplicablePercent"))
                   for t in el)

    ok08 = ok09 = True
    d08, d09 = [], []
    for t in breakdown:
        if not any(text(c) == "S" for c in kids(t, "CategoryCode")):
            continue
        basis = a.num((kids(t, "BasisAmount") or [None])[0])
        calc = a.num((kids(t, "CalculatedAmount") or [None])[0])
        rates = kids(t, "RateApplicablePercent")
        for r in rates:
            rate = a.num(r)
            ls = [a.num(e) for l in line_settle if s_rate(kids(l, "ApplicableTradeTax"), rate)
                  for e in walk(l, "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount")]
            cs = [actual(x) for x in acs if flag(x) is True and s_rate(kids(x, "CategoryTradeTax"), rate)]
            als = [actual(x) for x in acs if flag(x) is False and s_rate(kids(x, "CategoryTradeTax"), rate)]
            parts = [total(ls), total(cs), total(als)]
            want = None if rate is None or None in parts else a.r2(parts[0]) + a.r2(parts[1]) - a.r2(parts[2])
            hold = want is not None and basis == want
            ok08 = ok08 and hold
            d08.append("S %s%%: BasisAmount %s, lines %s + charges %s - allowances %s = %s"
                       % (fmt(rate), fmt(basis), fmt(parts[0]), fmt(parts[1]), fmt(parts[2]), fmt(want)))
            if None in (basis, calc, rate):
                ok09 = False
                d09.append("S %s%%: CalculatedAmount %s, BasisAmount %s" % (fmt(rate), fmt(calc), fmt(basis)))
                continue
            expect = a.r2(abs(basis) * rate / 100)
            hold = abs(calc) - 1 < expect < abs(calc) + 1
            ok09 = ok09 and hold
            d09.append("S %s%%: CalculatedAmount %s, BasisAmount x rate = %s (official tolerance < 1.00)"
                       % (fmt(rate), fmt(calc), fmt(expect)))
    out["BR-S-08"] = (ok08, "; ".join(d08) or "no standard-rated breakdown")
    out["BR-S-09"] = (ok09, "; ".join(d09) or "no standard-rated breakdown")

    # BR-CO-17: every breakdown; the rate is read only where TypeCode is VAT, as in the official rule
    ok17, d17 = True, []
    for t in breakdown:
        cat = text((kids(t, "CategoryCode") or [None])[0]) or "?"
        is_vat = text((kids(t, "TypeCode") or [None])[0]).upper() == "VAT"
        rate = a.num((kids(t, "RateApplicablePercent") or [None])[0]) if is_vat else None
        basis = a.num((kids(t, "BasisAmount") or [None])[0])
        calc = a.num((kids(t, "CalculatedAmount") or [None])[0])
        if calc is None:
            ok17 = False
            d17.append("%s: no VAT amount" % cat)
            continue
        if rate is None:  # third branch of the official rule: no VAT rate, so the amount must round to 0
            hold = _round0(calc) == 0
            d17.append("%s no rate: CalculatedAmount %s must round to 0" % (cat, fmt(calc)))
        elif _round0(rate) == 0:
            hold = _round0(calc) == 0
            d17.append("%s 0%%: CalculatedAmount %s must round to 0" % (cat, fmt(calc)))
        elif basis is None:
            hold = False
            d17.append("%s %s%%: no BasisAmount" % (cat, fmt(rate)))
        else:
            expect = a.r2(abs(basis) * (rate / 100))
            hold = abs(calc) - 1 <= expect <= abs(calc) + 1
            d17.append("%s %s%%: CalculatedAmount %s, BasisAmount x rate = %s (official tolerance <= 1.00)"
                       % (cat, fmt(rate), fmt(calc), fmt(expect)))
        ok17 = ok17 and hold
    out["BR-CO-17"] = (ok17, "; ".join(d17) or "no VAT breakdown")
    return out


def _round0(x):
    """round(x) to an integer, ties toward +infinity, for Decimal or float."""
    if isinstance(x, float):
        return math.floor(x + 0.5)
    return (x + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)


def strict_vat(root):
    """STRICT-VAT: [(category, rate, basis, declared, exact)] where the VAT amount of a breakdown is
    not basis x rate / 100 rounded to the cent under any common rounding (half up, half even, half toward +inf).
    When the taxable amount and the VAT amount are both whole numbers (currencies such as HUF are
    customarily invoiced in whole units), rounding to a whole unit is accepted too."""
    tt = (kids(root, "SupplyChainTradeTransaction") or [None])[0]
    st = (kids(tt, "ApplicableHeaderTradeSettlement") or [None])[0]
    found = []
    for t in kids(st, "ApplicableTradeTax"):
        cat = text((kids(t, "CategoryCode") or [None])[0]) or "?"
        vals = [_dec(text((kids(t, n) or [None])[0])) if kids(t, n) else None
                for n in ("RateApplicablePercent", "BasisAmount", "CalculatedAmount")]
        rate, basis, calc = vals
        if None in vals:
            continue
        exact = basis * rate / 100
        units = [CENT]
        if basis == basis.to_integral_value() and calc == calc.to_integral_value():
            units.append(Decimal(1))
        allowed = set()
        for u in units:
            allowed |= {exact.quantize(u, rounding=m) for m in (ROUND_HALF_UP, ROUND_HALF_EVEN)}
            allowed.add((exact / u + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR) * u)
        if calc not in allowed:
            found.append((cat, rate, basis, calc, exact))
    return found


# ---- per file -------------------------------------------------------------------------------

def check_root(root):
    """{"rules": {rule: (holds, detail)}, "split": [rules], "strict": [...]} or None."""
    results = [evaluate(root, a) for a in ARITHS]
    if results[0] is None:
        return None
    primary = results[0]
    split = [r for r in RULES if len({res[r][0] for res in results}) > 1]
    return {"rules": primary, "split": split, "strict": strict_vat(root)}


def check_file(path):
    """(result, status) where status is ok / fail / split / ubl / unreadable, and result may be None."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        return None, "unreadable", str(e)
    name = local(root)
    if name in ("Invoice", "CreditNote"):
        return None, "ubl", "UBL syntax; only CII is read"
    if name != "CrossIndustryInvoice":
        return None, "unreadable", "root element is %s, not CrossIndustryInvoice" % name
    res = check_root(root)
    if res is None:
        return None, "unreadable", "no SpecifiedTradeSettlementHeaderMonetarySummation"
    return res, "ok", ""


def exit_code(res, status, strict):
    if status == "unreadable":
        return 2
    if status == "ubl":
        return 3
    failed = [r for r in RULES if not res["rules"][r][0] and r not in res["split"]]
    if failed or (strict and res["strict"]):
        return 1
    if res["split"]:
        return 3
    return 0


def report(path, res, status, why, strict, tsv, out):
    code = exit_code(res, status, strict)
    if res is None:
        if tsv:
            out.write("%s\t-\t%s\t%s\n" % (path, status.upper(), why))
        else:
            out.write("%s  %s (%s)\n" % ({2: "UNREADABLE", 3: "UNCHECKED"}[code], path, why))
        return code
    if tsv:
        for r in RULES:
            ok, detail = res["rules"][r]
            state = "SPLIT" if r in res["split"] else ("ok" if ok else "FAIL")
            out.write("%s\t%s\t%s\t%s\n" % (path, r, state, detail))
        for cat, rate, basis, calc, exact in res["strict"]:
            out.write("%s\tSTRICT-VAT\t%s\t%s %s%%: CalculatedAmount %s, exact %s\n"
                      % (path, "FAIL" if strict else "note", cat, fmt(rate), fmt(calc), fmt(exact)))
        return code
    out.write("%s  %s\n" % ({0: "PASS", 1: "FAIL", 3: "UNCHECKED"}[code], path))
    for r in RULES:
        ok, detail = res["rules"][r]
        if r in res["split"]:
            out.write("  SPLIT     %s  %s  (comes out differently under decimal and double arithmetic "
                      "or the two tie rules; ask the official validator)\n" % (r, detail))
        elif not ok:
            out.write("  FAIL      %s  %s\n" % (r, detail))
    for cat, rate, basis, calc, exact in res["strict"]:
        out.write("  %s STRICT-VAT  %s %s%%: CalculatedAmount %s, BasisAmount %s x rate = %s "
                  "(passes the official tolerance if within 1.00; not an official rule)\n"
                  % ("FAIL     " if strict else "note     ", cat, fmt(rate), fmt(calc), fmt(basis), fmt(exact)))
    return code


def main(argv=None, out=None):
    out = out or sys.stdout
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("files", nargs="+")
    p.add_argument("--strict", action="store_true", help="a STRICT-VAT finding fails the file")
    p.add_argument("--tsv", action="store_true", help="one row per rule and file")
    args = p.parse_args(argv)
    worst = 0
    order = {0: 0, 3: 1, 1: 2, 2: 3}
    for f in args.files:
        res, status, why = check_file(f)
        code = report(f, res, status, why, args.strict, args.tsv, out)
        if order[code] > order[worst]:
            worst = code
    return worst


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    sys.exit(main())
