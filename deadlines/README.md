# `deadlines/` — the 2026 Microsoft support dates that are still ahead, one product per line

**A monthly-updated edition is planned at ¥3,000 / month. It does not exist yet, and there is currently no way to pay for it.** We are telling you the price before the thing exists, on purpose: a number you can react to now is worth more to us than a number we reveal once you are already invested.

**This file is updated on the 1st of every month.** Next update: 2026-10-01. If the 1st passes and nothing lands here, the promise was broken and you should read everything above accordingly.

---

## What this is

`eos-2026.tsv` — **43 rows, one product per row**, tab-separated, five columns:

| Column | Meaning |
|---|---|
| `product` | The product name as Microsoft writes it |
| `date` | ISO `YYYY-MM-DD` |
| `kind` | `retirement` / `end-of-servicing` / `end-of-support` / `mainstream-to-extended` |
| `source_url` | Where the date was read |
| `retrieved` | The day it was read |

Every row was read on **2026-09-17** from Microsoft's own 2026 end-of-support summary page, and the URL is on the row rather than in a footnote, so you can check any single line without trusting the file as a whole.

Dates covered: **2026-09-30 (2 rows), 2026-10-01 (3), 2026-10-13 (33), 2026-11-10 (5)**.

## What this is not

- **Not the full list.** It holds only the dates still in the future as of 2026-09-17, and it excludes Microsoft's separate table of Azure API / SDK / feature retirements, which is long and mostly matters to people already tracking it. **The authoritative list is [Microsoft's own page](https://learn.microsoft.com/en-us/lifecycle/end-of-support/end-of-support-2026), and this file is a convenience, not a substitute.**
- **Not cross-checked per product.** All 43 dates come from that one summary page. We did not open each product's own lifecycle page to confirm it. If those two ever disagree, Microsoft's product page wins and this file is wrong.
- **Not a monitor.** There is no script here, no schedule, nothing that will page you. It is a file.

## Why there is no "days remaining" column

Because it would be wrong the next morning, and the file gives you no way to notice. We shipped a tool in this repository ([`unbacked-numbers/`](../unbacked-numbers)) after finding that our own README stated a measured value that had silently drifted five times in one afternoon while the code it described never changed. **A number written into a document stops being a measurement and becomes a claim with no timestamp attached.** `date` and `retrieved` are both in the file so you can compute the gap yourself, against the day you are actually reading it.

## Who should not bother

If you run one laptop, or if your fleet is entirely on current Windows 11 and Microsoft 365 Apps, there is nothing here for you — the October 13 block is almost all 2021-vintage perpetual Office, LTSC/LTSB builds and Server 2012 ESU. If you already have a CMDB that tracks lifecycle dates, it is ahead of this file.

## If a line is missing or wrong

Open an issue. Missing products, a date that disagrees with the product's own lifecycle page, or a column you would actually use — all three are useful, and a correction is more useful to us than a star.
