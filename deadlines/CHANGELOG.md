# Changelog

One entry per check. **A check that found nothing still gets an entry** — that is the point of it. Each entry records the day we looked, what each source page said about its own last update, the row counts, and the diff.

Next scheduled check: **2026-10-01**.

---

## 2026-09-17 — second check, same day

| | |
|---|---|
| Checked | 2026-09-17 |
| `end-of-support-2026`, its own `Last updated` | `04/19/2025` |
| `end-of-support-2027`, its own `Last updated` | `11/08/2024` |
| `eos-2026.tsv` | 43 rows (unchanged) |
| `eos-2027.tsv` | **36 rows (new file)** |

**Diff: +36 rows, −0.** Added `eos-2027.tsv`, read from the 2027 page and verified twice against it — the second read was extracted independently and compared row by row, 36 of 36 matching, 0 differences.

**Why, three hours after the first publication:** the promise at the top of the README ("updated on the 1st of every month") had never been checked against the source's own rate of change, and both source pages turn out to state last-update dates more than a year old. A monthly update here cannot mean *new dates arrived*. The README now says what it can mean, and the 2027 rows are here because scoping the directory to 2026 alone would have emptied it on 2026-11-11 — including the row most readers come for, `Windows Server 2016`, `2027-01-12`.

**Also noted, not fixed:** `Office LTSC 2021 for Mac` is listed by Microsoft in both *End of Support* and *End of Mainstream Support* for 2026-10-13. `eos-2026.tsv` carries both rows. This file reports the source rather than arbitrating it.

## 2026-09-17 — first publication

| | |
|---|---|
| Checked | 2026-09-17 |
| `end-of-support-2026`, its own `Last updated` | not recorded at the time |
| `eos-2026.tsv` | 43 rows (new file) |

43 rows read from the 2026 end-of-support summary page: every date on that page still in the future as of 2026-09-17, excluding the separate Azure API / SDK / feature retirement table. A second pass re-read ten of the rows directly against the source page before publishing; all ten matched.
