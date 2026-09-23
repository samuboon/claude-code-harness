# -*- coding: utf-8 -*-
"""Tests for einvoice_total_check.py. Every invoice here is built in code; no official example
files are stored in this repository (fetch them yourself, see README)."""
import io
import os
import tempfile
import unittest
from decimal import Decimal, ROUND_HALF_UP

import einvoice_total_check as etc

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def c2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def tax_xml(tag, cat, rate, extra=""):
    r = "<ram:RateApplicablePercent>%s</ram:RateApplicablePercent>" % rate if rate is not None else ""
    return "<ram:%s>%s<ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>%s</ram:CategoryCode>%s</ram:%s>" % (
        tag, extra, cat, r, tag)


def build(lines=(("100.00", "S", "19"),), allowances=(), charges=(), header=None, breakdown=None,
          currency="EUR", extra_header="", drop=()):
    """A CII invoice whose totals are consistent unless header / breakdown override them.
    lines / allowances / charges: (amount, category, rate or None)."""
    header = dict(header or {})
    groups = {}
    for amt, cat, rate in lines:
        groups.setdefault((cat, rate), [Decimal(0)] * 3)[0] += Decimal(amt)
    for amt, cat, rate in charges:
        groups.setdefault((cat, rate), [Decimal(0)] * 3)[1] += Decimal(amt)
    for amt, cat, rate in allowances:
        groups.setdefault((cat, rate), [Decimal(0)] * 3)[2] += Decimal(amt)
    bd = []
    for (cat, rate), (l, c, a) in groups.items():
        basis = c2(l) + c2(c) - c2(a)
        calc = c2(basis * Decimal(rate) / 100) if rate is not None else Decimal("0.00")
        bd.append({"cat": cat, "rate": rate, "basis": str(basis), "calc": str(calc)})
    for i, over in (breakdown or {}).items():
        bd[i].update(over)
    LT = c2(sum((Decimal(x[0]) for x in lines), Decimal(0)))
    AT = c2(sum((Decimal(x[0]) for x in allowances), Decimal(0)))
    CT = c2(sum((Decimal(x[0]) for x in charges), Decimal(0)))
    TB = LT - AT + CT
    TT = sum((Decimal(b["calc"]) for b in bd), Decimal(0))
    h = {"LineTotalAmount": str(LT), "ChargeTotalAmount": str(CT) if charges else None,
         "AllowanceTotalAmount": str(AT) if allowances else None, "TaxBasisTotalAmount": str(TB),
         "TaxTotalAmount": str(TT), "GrandTotalAmount": str(TB + TT), "DuePayableAmount": str(TB + TT)}
    h.update(header)
    for k in drop:
        h[k] = None
    out = ['<rsm:CrossIndustryInvoice xmlns:rsm="%s" xmlns:ram="%s" xmlns:udt="%s">' % (RSM, RAM, UDT),
           "<rsm:ExchangedDocument><ram:ID>T-1</ram:ID></rsm:ExchangedDocument>",
           "<rsm:SupplyChainTradeTransaction>"]
    for amt, cat, rate in lines:
        out.append("<ram:IncludedSupplyChainTradeLineItem><ram:SpecifiedLineTradeSettlement>%s"
                   "<ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>%s</ram:LineTotalAmount>"
                   "</ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>"
                   "</ram:IncludedSupplyChainTradeLineItem>" % (tax_xml("ApplicableTradeTax", cat, rate), amt))
    out.append("<ram:ApplicableHeaderTradeSettlement><ram:InvoiceCurrencyCode>%s</ram:InvoiceCurrencyCode>" % currency)
    for b in bd:
        rate = "<ram:RateApplicablePercent>%s</ram:RateApplicablePercent>" % b["rate"] if b["rate"] is not None else ""
        out.append("<ram:ApplicableTradeTax><ram:CalculatedAmount>%s</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>"
                   "<ram:BasisAmount>%s</ram:BasisAmount><ram:CategoryCode>%s</ram:CategoryCode>%s</ram:ApplicableTradeTax>"
                   % (b["calc"], b["basis"], b["cat"], rate))
    for flag, items in (("false", allowances), ("true", charges)):
        for amt, cat, rate in items:
            out.append("<ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>%s</udt:Indicator>"
                       "</ram:ChargeIndicator><ram:ActualAmount>%s</ram:ActualAmount>%s</ram:SpecifiedTradeAllowanceCharge>"
                       % (flag, amt, tax_xml("CategoryTradeTax", cat, rate)))
    out.append("<ram:SpecifiedTradeSettlementHeaderMonetarySummation>")
    for k in ("LineTotalAmount", "ChargeTotalAmount", "AllowanceTotalAmount", "TaxBasisTotalAmount",
              "TaxTotalAmount", "RoundingAmount", "GrandTotalAmount", "TotalPrepaidAmount", "DuePayableAmount"):
        v = h.get(k)
        if v is None:
            continue
        attr = ' currencyID="%s"' % currency if k == "TaxTotalAmount" else ""
        out.append("<ram:%s%s>%s</ram:%s>" % (k, attr, v, k))
    out.append(extra_header)
    out.append("</ram:SpecifiedTradeSettlementHeaderMonetarySummation></ram:ApplicableHeaderTradeSettlement>"
               "</rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>")
    return "".join(out)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, f))
        os.rmdir(self.dir)

    def write(self, xml, name="inv.xml"):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(xml)
        return p

    def run_tool(self, *args):
        buf = io.StringIO()
        code = etc.main(list(args), out=buf)
        return code, buf.getvalue()

    def failed(self, xml):
        res, status, _ = etc.check_file(self.write(xml))
        self.assertEqual(status, "ok")
        return {r for r in etc.RULES if not res["rules"][r][0]}, res


class Consistent(Base):
    def test_simple_invoice_passes(self):
        code, out = self.run_tool(self.write(build()))
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("PASS"))

    def test_mixed_rates_allowances_charges_pass(self):
        xml = build(lines=(("100.00", "S", "19"), ("33.33", "S", "7"), ("10.00", "Z", "0"), ("20.00", "S", "19")),
                    allowances=(("5.00", "S", "19"),), charges=(("2.50", "S", "7"),))
        failed, res = self.failed(xml)
        self.assertEqual(failed, set(), res["rules"])
        self.assertEqual(res["split"], [])

    def test_no_total_vat_and_grand_total_equal_to_basis(self):
        # BR-CO-15 second branch: without a TaxTotalAmount, the total with VAT equals the total without
        xml = build(lines=(("100.00", "O", None),), drop=("TaxTotalAmount",))
        self.assertEqual(self.failed(xml)[0], set())

    def test_prepaid_and_rounding(self):
        xml = build(header={"TotalPrepaidAmount": "50.00", "RoundingAmount": "0.01", "DuePayableAmount": "69.01"})
        self.assertEqual(self.failed(xml)[0], set())

    def test_prepaid_ignored_is_caught(self):
        xml = build(header={"TotalPrepaidAmount": "50.00"})  # DuePayable still 119.00
        self.assertIn("BR-CO-16", self.failed(xml)[0])


class EachRuleFails(Base):
    """One broken amount per rule; the rule it belongs to must be among the failures."""

    def test_line_total(self):
        self.assertIn("BR-CO-10", self.failed(build(header={"LineTotalAmount": "101.00"}))[0])

    def test_allowance_total(self):
        xml = build(allowances=(("5.00", "S", "19"),), header={"AllowanceTotalAmount": "5.01"})
        self.assertIn("BR-CO-11", self.failed(xml)[0])

    def test_allowance_total_missing_while_allowances_exist(self):
        xml = build(allowances=(("5.00", "S", "19"),), drop=("AllowanceTotalAmount",))
        self.assertIn("BR-CO-11", self.failed(xml)[0])

    def test_charge_total(self):
        xml = build(charges=(("2.50", "S", "19"),), header={"ChargeTotalAmount": "2.49"})
        self.assertIn("BR-CO-12", self.failed(xml)[0])

    def test_basis_total(self):
        self.assertEqual(self.failed(build(header={"TaxBasisTotalAmount": "100.01", "GrandTotalAmount": "119.01",
                                                   "DuePayableAmount": "119.01"}))[0], {"BR-CO-13"})

    def test_basis_total_with_allowance_and_charge(self):
        xml = build(allowances=(("5.00", "S", "19"),), charges=(("2.00", "S", "19"),),
                    header={"TaxBasisTotalAmount": "103.00"})  # 100 - 5 + 2 = 97
        self.assertIn("BR-CO-13", self.failed(xml)[0])

    def test_total_vat(self):
        self.assertIn("BR-CO-14", self.failed(build(header={"TaxTotalAmount": "19.01"}))[0])

    def test_total_vat_in_other_currency_is_not_compared(self):
        extra = '<ram:TaxTotalAmount currencyID="SEK">999.00</ram:TaxTotalAmount>'
        self.assertEqual(self.failed(build(extra_header=extra))[0], set())

    def test_grand_total(self):
        self.assertEqual(self.failed(build(header={"GrandTotalAmount": "119.01", "DuePayableAmount": "119.01"}))[0],
                         {"BR-CO-15"})

    def test_due_payable(self):
        self.assertEqual(self.failed(build(header={"DuePayableAmount": "118.99"}))[0], {"BR-CO-16"})

    def test_standard_basis(self):
        xml = build(breakdown={0: {"basis": "100.01"}})
        self.assertIn("BR-S-08", self.failed(xml)[0])

    def test_standard_basis_counts_allowance_of_same_rate_only(self):
        xml = build(lines=(("100.00", "S", "19"), ("50.00", "S", "7")), allowances=(("10.00", "S", "7"),))
        self.assertEqual(self.failed(xml)[0], set())
        wrong = build(lines=(("100.00", "S", "19"), ("50.00", "S", "7")), allowances=(("10.00", "S", "7"),),
                      breakdown={0: {"basis": "90.00", "calc": "17.10"}, 1: {"basis": "50.00", "calc": "3.50"}},
                      header={"TaxTotalAmount": "20.60", "GrandTotalAmount": "160.60", "DuePayableAmount": "160.60"})
        self.assertIn("BR-S-08", self.failed(wrong)[0])

    def test_standard_vat_beyond_tolerance(self):
        xml = build(breakdown={0: {"calc": "20.50"}}, header={"TaxTotalAmount": "20.50", "GrandTotalAmount": "120.50",
                                                              "DuePayableAmount": "120.50"})
        self.assertEqual(self.failed(xml)[0], {"BR-S-09", "BR-CO-17"})

    def test_bs09_is_strictly_less_than_one_and_bco17_is_at_most_one(self):
        xml = build(breakdown={0: {"calc": "20.00"}}, header={"TaxTotalAmount": "20.00", "GrandTotalAmount": "120.00",
                                                              "DuePayableAmount": "120.00"})
        self.assertEqual(self.failed(xml)[0], {"BR-S-09"})

    def test_decimal_comma_in_a_line_is_not_read_as_zero(self):
        # "12,50" is what a German locale writes; it is not a number here, and the line must not vanish
        xml = build(lines=(("12.50", "S", "19"), ("0.00", "S", "19"))).replace(
            "<ram:LineTotalAmount>0.00</ram:LineTotalAmount>", "<ram:LineTotalAmount>0,00</ram:LineTotalAmount>", 1)
        self.assertIn("BR-CO-10", self.failed(xml)[0])

    def test_missing_totals_block_is_unreadable(self):
        xml = build().replace("SpecifiedTradeSettlementHeaderMonetarySummation", "Something")
        code, out = self.run_tool(self.write(xml))
        self.assertEqual(code, 2, out)


class OfficialTolerance(Base):
    def test_vat_99_cents_too_high_passes_every_official_rule(self):
        xml = build(breakdown={0: {"calc": "19.99"}}, header={"TaxTotalAmount": "19.99", "GrandTotalAmount": "119.99",
                                                              "DuePayableAmount": "119.99"})
        code, out = self.run_tool(self.write(xml))
        self.assertEqual(code, 0, out)
        self.assertIn("STRICT-VAT", out)
        code, out = self.run_tool(self.write(xml), "--strict")
        self.assertEqual(code, 1, out)

    def test_the_numbers_from_upstream_issue_432(self):
        # 64.26 at 21 % is 13.4946; the invoice said 13.22 and passed the official rules
        xml = build(lines=(("64.26", "S", "21"),), breakdown={0: {"calc": "13.22"}},
                    header={"TaxTotalAmount": "13.22", "GrandTotalAmount": "77.48", "DuePayableAmount": "77.48"})
        failed, res = self.failed(xml)
        self.assertEqual(failed, set())
        self.assertEqual(len(res["strict"]), 1)
        self.assertEqual(res["strict"][0][3], Decimal("13.22"))

    def test_exact_cent_is_not_flagged(self):
        xml = build(lines=(("100.50", "S", "19"),))  # 19.095 -> 19.10
        self.assertEqual(self.failed(xml)[1]["strict"], [])

    def test_half_even_rounding_is_accepted(self):
        xml = build(lines=(("100.50", "S", "19"),), breakdown={0: {"calc": "19.09"}},
                    header={"TaxTotalAmount": "19.09", "GrandTotalAmount": "119.59", "DuePayableAmount": "119.59"})
        # 19.095 half-even is 19.10 too, so 19.09 is off by a cent under every rule we accept
        self.assertEqual(len(self.failed(xml)[1]["strict"]), 1)

    def test_whole_units_accepted_when_amounts_are_whole(self):
        xml = build(lines=(("69180", "S", "27"),), breakdown={0: {"calc": "18679"}}, currency="HUF",
                    header={"TaxTotalAmount": "18679", "GrandTotalAmount": "87859", "DuePayableAmount": "87859"})
        failed, res = self.failed(xml)
        self.assertEqual(failed, set())
        self.assertEqual(res["strict"], [])

    def test_whole_unit_not_accepted_when_basis_has_cents(self):
        xml = build(lines=(("100.50", "S", "19"),), breakdown={0: {"calc": "19"}},
                    header={"TaxTotalAmount": "19", "GrandTotalAmount": "119.50", "DuePayableAmount": "119.50"})
        self.assertEqual(len(self.failed(xml)[1]["strict"]), 1)


class OtherCategories(Base):
    def test_not_subject_to_vat_without_rate(self):
        xml = build(lines=(("2500", "O", None), ("700", "O", None)))
        self.assertEqual(self.failed(xml)[0], set())

    def test_not_subject_to_vat_with_an_amount_fails_bco17(self):
        xml = build(lines=(("100.00", "O", None),), breakdown={0: {"calc": "5.00"}},
                    header={"TaxTotalAmount": "5.00", "GrandTotalAmount": "105.00", "DuePayableAmount": "105.00"})
        self.assertIn("BR-CO-17", self.failed(xml)[0])

    def test_zero_rate_rounds_to_zero(self):
        ok = build(lines=(("100.00", "Z", "0"),), breakdown={0: {"calc": "0.40"}},
                   header={"TaxTotalAmount": "0.40", "GrandTotalAmount": "100.40", "DuePayableAmount": "100.40"})
        self.assertEqual(self.failed(ok)[0], set())
        bad = build(lines=(("100.00", "Z", "0"),), breakdown={0: {"calc": "0.60"}},
                    header={"TaxTotalAmount": "0.60", "GrandTotalAmount": "100.60", "DuePayableAmount": "100.60"})
        self.assertIn("BR-CO-17", self.failed(bad)[0])

    def test_reduced_rate_beyond_tolerance_fails_bco17_only(self):
        xml = build(lines=(("100.00", "AA", "7"),), breakdown={0: {"calc": "8.50"}},
                    header={"TaxTotalAmount": "8.50", "GrandTotalAmount": "108.50", "DuePayableAmount": "108.50"})
        self.assertEqual(self.failed(xml)[0], {"BR-CO-17"})


class Split(Base):
    def test_negative_tie_splits_between_rounding_rules(self):
        # -0.005 rounds to 0.00 with ties toward +inf and to -0.01 with ties away from zero
        xml = build(lines=(("0.005", "Z", "0"), ("-0.010", "Z", "0")), header={
            "LineTotalAmount": "0.00", "TaxBasisTotalAmount": "0.00", "GrandTotalAmount": "0.00",
            "DuePayableAmount": "0.00"})
        res, status, _ = etc.check_file(self.write(xml))
        self.assertIn("BR-CO-10", res["split"])
        code, out = self.run_tool(self.write(xml))
        self.assertEqual(code, 3, out)
        self.assertIn("SPLIT", out)

    def test_decimal_and_double_disagree(self):
        # 1.005 * 100 is 100.5 in decimal and 100.49999999999999 in binary floating point
        xml = build(lines=(("1.005", "Z", "0"),), header={"LineTotalAmount": "1.01"})
        res, status, _ = etc.check_file(self.write(xml))
        self.assertIn("BR-CO-10", res["split"])

    def test_split_where_the_primary_reading_fails_is_not_a_failure(self):
        # decimal: 1.005 -> 1.01, so 1.00 fails; double: 1.00, so it holds. That is a SPLIT, exit 3
        xml = build(lines=(("1.005", "Z", "0"),), header={"LineTotalAmount": "1.00", "TaxBasisTotalAmount": "1.00",
                                                          "GrandTotalAmount": "1.00", "DuePayableAmount": "1.00"})
        code, out = self.run_tool(self.write(xml))
        self.assertEqual(code, 3, out)
        self.assertNotIn("  FAIL", out)

    def test_split_does_not_hide_a_real_failure(self):
        xml = build(lines=(("0.005", "Z", "0"), ("-0.010", "Z", "0")),
                    header={"LineTotalAmount": "0.00", "TaxBasisTotalAmount": "0.00", "GrandTotalAmount": "0.00",
                            "DuePayableAmount": "5.00"})
        code, out = self.run_tool(self.write(xml))
        self.assertEqual(code, 1, out)


class Files(Base):
    def test_ubl_is_unchecked_not_passed(self):
        p = self.write('<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>')
        code, out = self.run_tool(p)
        self.assertEqual(code, 3)
        self.assertIn("UNCHECKED", out)

    def test_not_xml(self):
        code, out = self.run_tool(self.write("not xml at all"))
        self.assertEqual(code, 2)

    def test_worst_code_wins(self):
        good = self.write(build(), "a.xml")
        split = self.write(build(lines=(("1.005", "Z", "0"),), header={"LineTotalAmount": "1.01"}), "b.xml")
        bad = self.write(build(header={"DuePayableAmount": "1.00"}), "c.xml")
        junk = self.write("x", "d.xml")
        self.assertEqual(self.run_tool(good, split)[0], 3)
        self.assertEqual(self.run_tool(split, bad, good)[0], 1)
        self.assertEqual(self.run_tool(bad, junk)[0], 2)

    def test_tsv_has_one_row_per_rule(self):
        code, out = self.run_tool(self.write(build()), "--tsv")
        rows = [r.split("\t") for r in out.strip().splitlines()]
        self.assertEqual([r[1] for r in rows], etc.RULES)
        self.assertTrue(all(r[2] == "ok" for r in rows))

    def test_failure_message_names_both_numbers(self):
        code, out = self.run_tool(self.write(build(header={"DuePayableAmount": "118.99"})))
        self.assertIn("DuePayableAmount 118.99", out)
        self.assertIn("= 119.00", out)


if __name__ == "__main__":
    unittest.main()
