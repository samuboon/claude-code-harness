# `deadlines/` — the Microsoft support dates that are still ahead, one product per line

**A monthly-updated edition is planned at ¥3,000 / month. It does not exist yet, and there is currently no way to pay for it.** We are telling you the price before the thing exists, on purpose: a number you can react to now is worth more to us than a number we reveal once you are already invested.

**These files are updated on the 1st of every month, and the check is written into [`CHANGELOG.md`](CHANGELOG.md) whether anything moved or not.** Next update: 2026-10-01. If the 1st passes and no line lands in the changelog, the promise was broken and you should read everything above accordingly.

---

## Three hours after publishing this, we found three things wrong with it

Published 2026-09-17, then checked. In order of how much it cost us to admit.

**1. We promised a monthly update without checking whether the source changes monthly.** It does not. Microsoft's own pages carry a last-updated date at the foot, and on 2026-09-17 they read:

| Page | Its own `Last updated` |
|---|---|
| `end-of-support-2026` | `04/19/2025` |
| `end-of-support-2027` | `11/08/2024` |

Seventeen and twenty-two months. So a monthly update here cannot mean *new dates arrived* — most months, nothing will have arrived. It can only mean *somebody looked on a named day and here is what they saw*. That is a smaller claim, and it is the one we can actually keep, so it is the one written above. It is also, we would argue, the thing the source page cannot give you: the page tells you what Microsoft believes, never when anyone last confirmed it still says that.

**2. The file was scoped to 2026, and 2026 runs out on 2026-11-10.** The last date in `eos-2026.tsv` is 2026-11-10. Under the rule we shipped with — *only dates still in the future* — this directory would have held forty-three rows in September, forty-one in October and **zero rows from 2026-11-11 onward**, while a subscription to it was being advertised at the top of the page. `eos-2027.tsv` (36 rows) is here now, and the scope is stated below rather than implied by a filename.

It also means the single row most people arrive looking for was not here at all: **Windows Server 2016 ends support on 2027-01-12**, along with .NET Framework 4.6.2, Windows 10 Enterprise LTSC 2021 and eight other 2016-vintage products on the same two days.

**3. The source contradicts itself once, and we copied the contradiction faithfully.** `Office LTSC 2021 for Mac` appears in *End of Support* and in *End of Mainstream Support* on the 2026 page, both dated 2026-10-13 — two states a product cannot be in at once. It is in `eos-2026.tsv` twice, once with each `kind`, because this file reports the source rather than arbitrating it. This is the clearest example we have of why the per-product cross-check below is the work, and the monthly newsletter is not.

## What this is

Two tab-separated files, five columns:

| Column | Meaning |
|---|---|
| `product` | The product name as Microsoft writes it |
| `date` | ISO `YYYY-MM-DD` |
| `kind` | `retirement` / `end-of-servicing` / `end-of-support` / `mainstream-to-extended` |
| `source_url` | Where the date was read |
| `retrieved` | The day it was read |

- **`eos-2026.tsv` — 43 rows** (42 distinct products; see item 3 above). Dates: 2026-09-30 (2), 2026-10-01 (3), 2026-10-13 (33), 2026-11-10 (5).
- **`eos-2027.tsv` — 36 rows.** Dates: 2027-01-11 (9), 2027-01-12 (14), 2027-03-31 (1), 2027-04-13 (6), 2027-07-12 (1), 2027-09-03 (1), 2027-09-30 (1), 2027-10-12 (3).

Every row carries the URL it was read from and the day it was read, on the row rather than in a footnote, so you can check any single line without trusting the file as a whole.

## The update rule

Three clauses, so that "we updated it" is something you can check rather than something we assert.

1. **Rows are never deleted when their date passes.** A file that drops expired rows shrinks to nothing and tells you nothing about the day it passed. Both files are records, not countdowns. `eos-2026.tsv` will still hold 2026-10-13 in 2027.
2. **Every 1st of the month, both source pages are re-read and the result is appended to `CHANGELOG.md`** — the source page's own `Last updated` value, the row counts, and any diff. **A month where nothing changed still gets a line.** That line is the product.
3. **Scope is the current and the next calendar year.** `eos-2028.tsv` arrives on the first monthly check after Microsoft publishes that page.

## What this is not

- **Not the full list.** It excludes Microsoft's separate table of Azure API / SDK / feature retirements — long, and mostly relevant to people already tracking it. **The authoritative list is Microsoft's own page ([2026](https://learn.microsoft.com/en-us/lifecycle/end-of-support/end-of-support-2026), [2027](https://learn.microsoft.com/en-us/lifecycle/end-of-support/end-of-support-2027)), and these files are a convenience, not a substitute.**
- **Not cross-checked per product.** All 79 rows come from those two summary pages. We have not opened each product's own lifecycle page to confirm it. If the two ever disagree, Microsoft's product page wins and this file is wrong. **This is the gap the ¥3,000 edition would close** — 79 products, each against its own lifecycle page, on a named day, with the disagreements listed. That is a month's worth of actual labour; a monthly email of new dates is not, which is what item 1 above taught us.
- **Not a monitor.** There is no script here, no schedule, nothing that will page you. It is two files and a changelog.

## Why there is no "days remaining" column

Because it would be wrong the next morning, and the file gives you no way to notice. We shipped a tool in this repository ([`unbacked-numbers/`](../unbacked-numbers)) after finding that our own README stated a measured value that had silently drifted five times in one afternoon while the code it described never changed. **A number written into a document stops being a measurement and becomes a claim with no timestamp attached.** `date` and `retrieved` are both in the file so you can compute the gap yourself, against the day you are actually reading it.

## Who should not bother

If you run one laptop, or if your fleet is entirely on current Windows 11 and Microsoft 365 Apps, there is nothing here for you — the October 13 block is almost all 2021-vintage perpetual Office, LTSC/LTSB builds and Server 2012 ESU, and the January 12 block is Server 2016. If you already have a CMDB that tracks lifecycle dates, it is ahead of these files.

## If a line is missing or wrong

Open an issue. Missing products, a date that disagrees with the product's own lifecycle page, or a column you would actually use — all three are useful, and a correction is more useful to us than a star.
