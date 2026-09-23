**日本語版: [README.ja.md](README.ja.md)**

# einvoice-total-check — an invoice with 27 cents too little VAT passed the official EN 16931 rules, and that is by design

From 2027 German businesses have to invoice each other electronically (from 2028 if their
turnover is up to 800,000 euro; ZUGFeRD / Factur-X or XRechnung),
and the rules everyone validates against are the CEN rule set for EN 16931, published as
Schematron in [ConnectingEurope/eInvoicing-EN16931](https://github.com/ConnectingEurope/eInvoicing-EN16931).
Two things about its arithmetic rules are easy to miss:

- **The VAT amount of a rate may be off by almost 1.00 and still pass.** BR-S-09 accepts
  `|declared - taxable x rate| < 1`, BR-CO-17 accepts `<= 1`. The EN text says "shall equal".
  The slack was added on purpose for software that rounds VAT per line
  ([#370](https://github.com/ConnectingEurope/eInvoicing-EN16931/issues/370), where it is
  pointed out that the slack is `1` in any currency, not 1 euro). In
  [#432](https://github.com/ConnectingEurope/eInvoicing-EN16931/issues/432) (2025) an invoice
  said 13.22 VAT on 64.26 at 21 % — the right figure is 13.49 — and passed; the answer was
  "The rule BR-CO-17 allows for a slack of 1."
  The rule files we read on 2026-09-23 still have it.
- **The rules run on a Java / XSLT stack.** If your invoices come out of Python, checking the
  totals means installing a JVM and a validator, or not checking them.

`einvoice_total_check.py` recomputes the totals and VAT amounts of a CII invoice with the
standard library, tells you which declared amount disagrees and what it should be, and reports
the VAT amounts the official slack lets through as a separate `STRICT-VAT` line.

```bash
python einvoice_total_check.py invoice.xml [more.xml ...]
python einvoice_total_check.py invoice.xml --strict    # STRICT-VAT fails the file
python einvoice_total_check.py invoice.xml --tsv       # one row per rule and file
```

```
FAIL  invoice.xml
  FAIL      BR-CO-16  DuePayableAmount 118.99, total with VAT - paid + rounding = 119.00
PASS  other.xml
  note      STRICT-VAT  S 21%: CalculatedAmount 13.22, BasisAmount 64.26 x rate = 13.4946 (passes the official tolerance if within 1.00; not an official rule)
```

Standard library only. No Java, no network.

---

## What it checks

The ten arithmetic rules below, each re-read from the official CII binding
(`cii/schematron/CII/EN16931-CII-model.sch`); all ten are `fatal` there.

| Rule | Declared amount | Recomputed as |
|---|---|---|
| BR-CO-10 | Sum of line net amounts | sum of the lines, rounded to the cent |
| BR-CO-11 / 12 | Sum of document-level allowances / charges | sum of the allowances / charges |
| BR-CO-13 | Total without VAT | lines - allowances + charges |
| BR-CO-14 | Total VAT (in the invoice currency) | sum of the VAT breakdown's amounts |
| BR-CO-15 | Total with VAT | total without VAT + total VAT |
| BR-CO-16 | Amount due | total with VAT - paid + rounding (no rounding, no slack) |
| BR-S-08 | Taxable amount per standard rate | lines + charges - allowances at that rate |
| BR-S-09 | VAT amount per standard rate | taxable x rate, **slack < 1** |
| BR-CO-17 | VAT amount of every breakdown | taxable x rate, **slack <= 1**; no rate or rate 0 means the amount must round to 0 |
| `STRICT-VAT` | *not an official rule* | taxable x rate rounded to the cent (half up, half even or half toward +infinity all accepted; whole units accepted when the taxable and VAT amounts are both whole numbers, as for HUF) |

**Exit codes:** 0 = all rules hold. 1 = a rule fails (or, with `--strict`, a STRICT-VAT line).
2 = not readable as a CII invoice. **3 = nothing failed, but something was not checked: the file
is UBL, or a rule came out `SPLIT`.** 3 is not a pass.

**`SPLIT`.** The official rules are XPath, where some sums are taken in binary floating point
and others in decimal, and `round()` has its own rule for ties. Rather than claim to know which
applies in every corner, the tool evaluates every rule three ways (decimal with ties toward
+infinity, decimal with ties away from zero, binary double) and reports a rule that does not
come out the same in all three as `SPLIT`, with the numbers. Line amounts with more than two
decimals are where this happens (`1.005` is 100.5 cents in decimal and 100.49999999999999 in a
double). On the 15 official examples, nothing split.

---

## Measured

**The 15 CII example invoices in the official repository** (fetched 2026-09-23 through the
GitHub API; every blob hash matched): **15 of 15 pass**, with `--strict` too, and nothing
splits. One of them is the Hungarian invoice from
[#325](https://github.com/ConnectingEurope/eInvoicing-EN16931/issues/325), whose VAT of 18,679
on 69,180 at 27 % is rounded to whole forint; that is why whole units are accepted.

**The same 15, broken on purpose** — one amount changed at a time, the way a generator bug
would change it:

| Change | Invoices it applies to | Caught by the rule it belongs to |
|---|---:|---:|
| line total +1 | 15 | 15 |
| allowance total +0.01 | 5 | 5 |
| charge total +0.01 | 7 | 7 |
| total without VAT +0.01 | 15 | 15 |
| total with VAT +0.01 | 15 | 15 |
| amount due +0.01 | 15 | 15 |
| standard-rate taxable amount +0.01 | 12 | 12 |
| standard-rate VAT +2 | 12 | 12 |
| **standard-rate VAT +0.99, with the totals moved to match** | 12 | **11 pass every official rule above; STRICT-VAT flags 12** |

The twelfth is the Hungarian invoice: its 0.40 of rounding had already used part of the slack.

**Our own mistake on the way.** The first run failed one official example, `CII_example7.xml`
(category O, "not subject to VAT", which has no rate), on BR-CO-17. The rule has a third branch
for exactly that case — no VAT rate, and the amount must round to 0 — and we had not seen it
because we printed the expression cut at 600 characters. Without the official examples we would
have shipped a checker that rejects every valid invoice outside the scope of VAT.

40 tests. `mutation_check.py` breaks the checker in 20 ways (the slack widened to 2, a SPLIT
counted as a pass, `--strict` ignored, whole-unit rounding accepted for every amount, a number
it cannot read counted as zero...) and checks the tests fail each time. **The first run caught
19 of 20.** The survivor was real: a line amount written `0,00` (a German-locale decimal comma)
was silently dropped from the sum. It now fails BR-CO-10, and there is a test.

---

## What it does not do

- **It is not the official validator.** It checks ten arithmetic rules out of roughly 780
  (plus the code lists and the schema). Mandatory fields, codes, dates, identifiers: none of that.
  National rule sets on top (XRechnung's own rules, for example) are not read at all.
- CII only. UBL files come back `UNCHECKED` (exit 3). A ZUGFeRD / Factur-X PDF has to have its
  XML taken out first.
- BR-S-08 is matched per tax element; the official expression tests the category and the rate
  as two separate conditions on a line, which can differ when a line carries two taxes.
- The whole-unit acceptance in STRICT-VAT is a heuristic: any breakdown whose taxable and VAT
  amounts are both whole numbers may be rounded to a whole unit, in any currency.
- Every invoice it has seen is an official example or one we built in the tests. None came
  from a real generator. One run on invoices your software actually produces would tell more
  than the table above.

The official example files are EUPL 1.2 and are not copied here. To reproduce both tables:

```bash
git clone --depth 1 https://github.com/ConnectingEurope/eInvoicing-EN16931
python einvoice_total_check.py eInvoicing-EN16931/cii/examples/*.xml --strict
python break_examples.py eInvoicing-EN16931/cii/examples
python -m unittest test_einvoice_total_check -v
python mutation_check.py
```

MIT, like the rest of this repository.
