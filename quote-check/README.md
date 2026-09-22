**日本語: [README.ja.md](README.ja.md)**

# quote-check — the quote is in the report, the source is cited, and one invisible character is different

A model reads a page and writes a report with the page's own words in quotation marks.
Somebody has to check that those words are the page's words. At scale that check becomes
`quote in source_text`, which answers yes or no.

**No is the useless answer.** A quote fails that test because it was invented, and it fails
because the page had an ideographic space where the report has an ASCII one. Those two
need opposite responses — throw the claim away, or change nothing — and the check cannot
tell them apart, so every no costs a human read of the page.

This matches the quote exactly first. Only for the quotes that did *not* match does it
relax **one typographic axis at a time** — invisible characters, whitespace, quotation-mark
shapes, dash and ellipsis shapes, character width, letter case — and name the axis that did
it. What survives all six is a difference in the letters and digits themselves, and that
one is printed with the code point of the first character that differs.

```
$ python quote_check.py demo/report.md --sources demo/pages
quotes      9
exact       3
formatting  4
substantive 1
unfound     1

formatting difference (space)
  demo/report.md line 14
    quote   Fees are quoted exclusive of tax
    source  demo/pages/seller-terms.txt
    found   Fees are quoted exclusive of tax
    first difference at character 16: quote ' ' (U+0020 SPACE) vs source '\xa0' (U+00A0 NO-BREAK SPACE)
    identical once space is relaxed; the letters and digits are the same

substantive difference
  demo/report.md line 18
    quote   a platform fee of 7.5% of each sale
    source  demo/pages/seller-terms.txt, closest 97%
    found   a platform fee of 7.0% of each sale
    first difference at character 21: quote '5' (U+0035 DIGIT FIVE) vs source '0' (U+0030 DIGIT ZERO)

not found in any source
  demo/report.md line 20
    quote   the seller may withdraw funds at any time without notice
    no stretch of any source resembles it
```

The two lines at the bottom are the ones that matter. The four above them are the noise a
yes/no checker buries them in.

Standard library only. No network. Exit **0 = every quote is verbatim** (formatting
differences are printed and, without `--strict`, allowed), **1 = a quote differs in
substance or is in no source**, **2 = the check did not happen**.

---

## Measured

**The day this became a tool (2026-09-11).** A worker brought back 29 verbatim quotes from
terms-of-service pages. Each was checked against the page reopened in a different browser:
**28 matched character for character. One did not, and the difference was a single
ideographic space inside a worked example — every digit in it was correct.** So the one
finding of that whole check was a finding that needed no action, and it cost a human read
to establish that. That is the shape of the problem: **the misses are nearly all
formatting, so a checker that only says "no" spends all its budget on the wrong quotes.**

The checker that produced that number was a one-line `innerText.includes()` typed into a
browser console, and it is gone. We have now recorded losing a measuring instrument five
times. **This file is that check, kept.**

**Extraction on this repository's own prose.** The top-level `README.ja.md` contains **108**
quoted strings by the raw regex; skipping fenced code, inline code spans and anything
under 8 characters leaves **61**. For the English `README.md` it is 61 → 57. Code is where
quotation marks live without quoting anything, and a checker that reads it will report
findings nobody can act on.

**Tests: 42. Mutations: 25, all caught** (`python mutation_check.py`).

**The first mutation run is worth writing down.** 22 mutations, 19 caught, 3 survived — and
**two of the three "survived" because the text they were supposed to edit was not in the
file.** The source had been written with *literal* invisible characters where escape
sequences were intended: 65 non-ASCII characters in the tool, 56 in the test file,
including zero-width spaces and no-break spaces sitting inside string literals where no
reviewer would ever see them. A tool for finding invisible characters had them in its own
source, and the thing that noticed was not the test suite — the tests were green — but a
mutation that could not find its own target. **Both files are ASCII-only now, on purpose:
every character this tool cares about appears in them as `\uXXXX`.**

---

## Using it

```bash
# a document and a directory of saved source pages
python quote_check.py report.md --sources pages/

# named sources, and fail the run on formatting differences as well
python quote_check.py report.md --source pages/terms.txt --source pages/fees.txt --strict

# markdown blockquotes count as quotations too
python quote_check.py report.md --sources pages/ --blockquote --json
```

| flag | |
|---|---|
| `--source FILE` | a source file; repeatable |
| `--sources DIR` | every readable text file under a directory |
| `--min-length N` | shortest quote to check (default 8 characters) |
| `--blockquote` | treat each run of markdown `>` lines as one quotation |
| `--strict` | formatting differences fail the run too |
| `--json` | one record per quote, for a pipeline |

Quotations are taken from `「...」`, `『...』`, `“...”` and `"..."`, outside fenced code
blocks and inline code spans. Files are decoded as UTF-8 and normalised to NFC on load, so
a quote that differs from its source only by Unicode decomposition is treated as the same
quote — on both sides, once, before anything is compared.

**The sources are files you saved, not URLs.** That is deliberate. A checker that fetches
the page itself checks the page as it is today against a quote taken some other day, and
quietly turns a changed page into a fabricated quote. Save what you read; check against
what you saved.

### In CI

`example-workflow.yml` runs it on every push and fails on substantive differences only.

---

## What it cannot do

- **It does not read meaning.** A quote that is verbatim and cut so that it inverts the
  source passes. So does a quote that is verbatim, correct, and irrelevant.
- **It does not know which source is the right one.** It reports the file a quote matched
  in; it cannot tell you that the report cited a different one.
- **It cannot see a claim that is not in quotation marks.** A paraphrase gives it nothing
  to check, which is why the honest use of it is upstream: quote, then check.
- **`unfound` is not proof of invention.** It means no stretch of any file you passed
  resembles the quote. The usual cause is a source you did not save.
- **Normalisation is per character**, so composed forms beyond the NFC pass at load are not
  folded. A quote that differs by an exotic decomposition will read as substantive.
- The axes are fixed. Six of them, in the order `invisible, space, quotes, punct, width,
  case`, and the first one that makes the quote match is the one reported.

---

## Where this came from

An AI runs a business whose goal is ten million yen of profit in twelve months, and most of
what it does is read other people's terms and write down what they say. Every number in
those reports is load-bearing — a fee, a payout delay, a notice period — and every one of
them arrives as a quotation that somebody has to believe.

**The failure this guards against is not a model inventing a quote.** It is a model getting
a quote 99% right, a checker saying "not found", and a human — the one resource the whole
operation is short of — spending ten minutes discovering that the missing character was a
space.

MIT. No network, no dependencies, no telemetry.

日本語版: [README.ja.md](README.ja.md)
