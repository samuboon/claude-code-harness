**日本語: [README.ja.md](README.ja.md)**

# changelog-delta-check — rack's changelog dates 2.2.9 four months before 2.2.8. RubyGems has it a year later

`rack/rack`'s CHANGELOG.md says 2.2.8 came out on 2023-07-31 and 2.2.9 on 2023-03-21. RubyGems
published 2.2.9 on 2024-03-21: the year is off by one. `rust-lang/mdBook` has the same slip on 0.2.3
(2018-01-18 for 2019-01-18, per crates.io). Textual's `[7.0.0]` link compares from `v6.11.0`, so
the diff it opens silently includes 6.12.0, which PyPI shows was released the day before.
Flutter's heading for 3.19.3 links to the 3.16.3 release page.

None of those is visible from the line itself. `2023-03-21` is a date, `v6.11.0...v7.0.0` is a
working URL. What gives each one away is **the entry next to it** — a later version dated earlier
than the version below it, a compare link that starts behind the entry below it.

A clinical lab works the same way. It does not re-check each result by hand; it compares the
result with the same patient's previous value, and a difference no body can produce is held back
as a probable mix-up (a *delta check*). A specimen it cannot measure is returned as unfit, never
guessed. `changelog_check.py` does that for a changelog: it reads every release entry — version,
date, link — and compares each with its neighbours. A date it cannot read one way only
(`03/04/2024`) is counted as unreadable and not used.

```bash
python changelog_check.py path/to/repo              # CHANGELOG*, CHANGES*, HISTORY*, NEWS*, RELEASES* in the tree
python changelog_check.py CHANGELOG.md              # one file
python changelog_check.py . --as-of 2024-01-15      # the date to call "today" (default: today)
python changelog_check.py . --explain               # also list every release entry it read
python changelog_check.py . --json                  # findings as JSON
```

On copies of `rack/rack`, `Textualize/textual` and `flutter/flutter` taken on 2026-09-24:

```
$ python changelog_check.py rack
CHANGELOG.md:672: error DATE 2.2.9 is dated 2023-03-21, before 2.2.8 (2023-07-31) in the same release line
1 changelogs, 135 release entries read (135 dated, 0 undated); 3 dates out of order across release lines not reported (backports?); 1 errors, 0 warnings

$ python changelog_check.py textual
CHANGELOG.md:222: warning LINKDEF [6.12.0] has no link definition (it shows as plain text)
CHANGELOG.md:443: error DATE 5.1.1 is dated 2025-07-21, before 5.1.0 (2025-07-31) in the same release line
CHANGELOG.md:1145: warning LINKDEF [0.79.1] has no link definition (it shows as plain text)
CHANGELOG.md:1612: warning LINKDEF [0.56.4] has no link definition (it shows as plain text)
CHANGELOG.md:2898: error DUPVER 0.15.0 has a second entry (first at line 2891)
CHANGELOG.md:3501: error LINK [7.0.0] for 7.0.0 compares from v6.11.0, but 6.12.0 (2026-01-02) came out in between
CHANGELOG.md:3561: error LINK [0.80.0] for 0.80.0 compares from v0.79.0, but 0.79.1 (2024-08-31) came out in between
CHANGELOG.md:3598: error LINK [0.57.0] for 0.57.0 compares from v0.56.3, but 0.56.4 (2024-04-09) came out in between
1 changelogs, 226 release entries read (223 dated, 3 undated); 1 dates out of order across release lines not reported (backports?); 5 errors, 3 warnings

$ python changelog_check.py flutter
CHANGELOG.md:548: error LINK the heading's link for 3.19.3 points at the tag 3.16.3
CHANGELOG.md:848: error LINK the heading's link for 3.3.7 points at the tag 3.3.6
1 changelogs, 175 release entries read (107 dated, 68 undated); 2 errors, 0 warnings
```

(PyPI has Textual 5.1.1 on 2025-07-31, the same day as 5.1.0 — the 21 is the typo. The three
`LINKDEF` warnings are the three releases the `[7.0.0]`, `[0.80.0]` and `[0.57.0]` links skip:
their headings have no link either.)

Standard library only. It reads files; it runs nothing, writes nothing and sends nothing
(`replay_fixes.py` below is the one part that reads from GitHub). The last line always says how
many changelogs and entries it read. A tree with no changelog it recognises exits 2 and says so,
instead of passing.

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `DATE` | error | Within one release line (same major.minor), a later version is dated before an earlier one. The message adds "… in 2019 would fit" when a one-year shift of either date puts the pair in order. |
| `DATE` | error | An entry's date lies outside the dates of the entries on either side of it, and moving it one year either way puts it between them — for the newest entry, "above it" is today. Neighbours are by position in the file. |
| `DATE?` | warning | The same, when the later-dated one of the pair is a patch release of an older line (4.0.1 under 4.1.0): a backport listed by version is dated after newer releases on purpose. Sinatra's 4.0.1 is one (RubyGems has it on 2025-05-23, a day before its changelog date). |
| `FUTURE` | error | Dated more than 2 days after today (`--as-of`), or, for the newest entry, more than 60 days. |
| `FUTURE?` | warning | The newest entry is dated 3 to 60 days ahead: a planned date? |
| `BADDATE` | error | A date that is not on the calendar (`2024-02-30`, `2024-13-01`). |
| `DUPVER` | error | Two entries for one version. `1.3` and `1.3 beta3`, `2.0.2` and `2.0.2 Enterprise`, `13.0.1` and `13.0.1+security-01` are different releases; a `### 1.9.0 Changes` sub-heading under `## 1.9.0` is not an entry. |
| `ORDER` | error | Within one release line, a final release listed above a later one (`1.2.3` above `1.2.4`) in a file that runs newest-first — or the other way in a file that runs oldest-first. Which way a file runs is counted, not assumed. Prereleases are not ordered against finals (date-ordered files interleave them). |
| `LINK` | error | A compare link (`[1.2.0]: …/compare/v1.1.0...v1.2.0`, or the link in a `## [1.2.0](https://github.com/o/r/compare/v1.1.0...v1.2.0)` heading) whose head is not this version; whose base is not older than it; or whose base skips a final release that the file dates on or before this one (Textual's `[7.0.0]` from `v6.11.0` past 6.12.0). A base that skips only prereleases, or only releases dated after this one (Composer's `[2.10.0-RC1]` from `2.9.5`: 2.9.6–2.9.8 came out after the RC), is not reported. A tag link (`…/releases/tag/v1.2.0`, `…/tree/v1.2.0`) that names another version. An `[Unreleased]` link that compares from a version older than the newest release (a `TBD` entry is not a release). |
| `LINKDEF` | warning | `## [1.2.0]` with no `[1.2.0]:` definition, in a file that defines links for other versions — it renders as the plain text `[1.2.0]`. A file that links none of its versions is left alone. |
| `DUPLINK` | warning | A version's link defined twice with different URLs; Markdown uses the first. |
| `PLACEHOLDER` | warning | A release below a dated one still says `YYYY-MM-DD`, `TBD` … |

**Read as release entries:** Markdown `#` headings and setext / reStructuredText underlined
headings (fenced code and HTML comments skipped); plain `1.2.3 (2024-01-05)` lines in a file that
has no headings. The version is the first dotted number in the heading, after an optional name
(`pkg@`, `pkg-v`, `Version`, `Release`), and entries with different names (`pkg-a@2.0.0`,
`pkg-b@1.0.5`) are compared only with their own kind. `2013.08.21, Version 0.11.7` is read as the
date and then the version. A two-part heading (`## 4.4`) above three-part releases of that line
(`## 4.4.1`, `## 4.4.0`) is a section, not a release. Headings about versions rather than of one
(`Upgrading from 1.9 to 2.0`, `Migrating from …`) are skipped.

**Dates:** `2024-01-05`, `2024/01/05`, `2024.01.05`, `5 January 2024`, `January 5th, 2024`,
`Jan. 5, 2024`, `25/12/2023`, `12/25/2023`, `January 2024` (month only: never compared by day),
in the heading or on the first line below it (`_Released 2024-05-01_`, or a line that is only a
date). `03/04/2024` is ambiguous and unread — unless another date in the same file with the same
separator can only be day-first (or only month-first), or the separator is a dot.

**Exit code:** 0 = no errors (warnings fail only with `--strict`). 1 = errors. 2 = no changelog with
release entries found. Folders named `node_modules`, `vendor`, `third_party`, `dist`, `build`,
`target`, `fixtures`, `testdata` and dot-folders are not searched.

### In CI

```yaml
# .github/workflows/changelog.yml
on: pull_request
jobs:
  changelog:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: curl -fsSLO https://raw.githubusercontent.com/samuboon/claude-code-harness/main/changelog-delta-check/changelog_check.py
      - run: python3 changelog_check.py .
```

This has not been run on GitHub by us. (It is here and not in `.github/workflows/` because the
key that publishes this folder has no workflow permission.)

---

## Measured

### Commits that fixed a changelog, replayed (`replay_fixes.py`)

GitHub's commit search for the words people use when they fix one — "fix changelog date",
"changelog wrong year", "fix compare links changelog", "fix unreleased link", "changelog version
typo", 18 queries in all — gave 1,343 commits. **313 of them were kept because the patch itself —
read before the checker ran — changes the date of a release heading while keeping its version,
the version while keeping the date, or the URL of a version's link** (`replay_fixes.py --classify`).
For each, the checker ran on the changelog just before the commit and at the commit, with "today"
set to the commit's own date. The file before is rebuilt by undoing the commit's patch on the file
after it, read from raw.githubusercontent.com.

**They were split in two by commit id before any tuning: 157 to tune on, 156 held out.**

| | Tuning half (157) | Held out (156) — first run, before tuning |
|---|---:|---:|
| An error before the fix on what the commit changed, none after | 34 | **46** |
| An error before, and one still there after (the commit fixed part of it) | 7 | 6 |
| Only a warning before | 3 | 5 |
| Nothing before | 113 | 99 |

Held out, by what the commit changed: **links 36 of 66, dates 12 of 88, versions 1 of 10**. Of
the findings that were fixed, most are one kind: an `[Unreleased]` link still comparing from a
release or two ago after a new version was added above it (66 of the 71 `LINK` findings fixed
across all 313). The rest are dates — a newer patch dated before the older one
(`0.5.1` dated 2025-04-26, a year before the `0.5.0` below it, 2026-04-20), `2026-02-30`, `0.6.2`
dated 2033 — and links to the wrong version (a heading link for 0.2.0 that compared up to
`v0.1.0`).

After the fixes the held-out half and the tuning half prompted, all 313 again: **81 flagged before
the fix and clean after, 12 partly, 7 only as a warning, 213 not** (held out: 47; that is no longer
a held-out number). On one commit the fix itself added an error: ManoptExamples.jl's Changelog.md
has two `## [0.1.3]` headings after it, and none before.

### What it cannot see

Most of the 220 not caught (213, plus the 7 caught only as a warning) are not something a
changelog can show about itself. Sorted by the patch alone:

| What the commit changed | Commits |
|---|---:|
| A date moved by 14 days or less — to the day the release actually went out (`0.2.1 - 2026-08-22` to `2026-08-23`) | 94 |
| A date moved by 15 to 62 days (`7 April 2026` to `7 May 2026`) | 15 |
| A date moved by exactly a year | 9 |
| A date moved further, or filled in, or reformatted | 20 |
| A link's URL changed but not its versions: a renamed owner or repository, a fork, a typo in the repository name (`opernai-image-api`), a tag-name style (`16.4.0.rc.10` to `v16.4.0.rc.10`) | 35 |
| A release added, with the Unreleased link moved along — the link was right before | 27 |
| A version changed | 8 |
| More than one of the above | 12 |

**The one-year moves are the case this checker was built for, and it caught none of the nine.** In
the eight we opened, the wrong year was not odd next to its neighbours: every entry had moved
together (five entries of `lukasNebr/stream-web-provider` from 2024 to 2025, two of
`internetarchive/heritrix3`), or the entry was the only or the oldest one. A delta check needs a
neighbour that is right. What would catch these is the date of each version's git tag; this does
not read git (see Limits).

### 112 well-known repositories on 2026-09-24

The changelog at the root of 112 well-known repositories (React, Vue, ESLint, requests, Flask,
rack, Terraform, Grafana, ripgrep, Laravel, OkHttp, Flutter …, listed in `replay_fixes.py`),
split in half alphabetically before any tuning.

| | Held out (56) — first run, before tuning | All 112, after the fixes |
|---|---:|---:|
| Changelogs with release entries | 52 | 102 |
| Release entries read | 8,655 | 15,617 |
| Errors | 97 | **29** |
| … true | **13** | **29** |
| Warnings | 175 | 26 |

**Held out, the first run was mostly wrong: 84 of its 97 errors were not real.** 54 were Grafana's
security re-releases (`13.0.1+security-01` read as a second `13.0.1`), 12 Consul's Enterprise
editions (`2.0.2 Enterprise`, `2.0.4+ent`), 4 prereleases written with a space (`Version 1.3 beta3`,
`2.0.0 rc1`) read as the release, 1 a sub-heading repeating the version (pydantic). 7 dates: Grafana's
re-releases and backports again (5); Sinatra's 4.0.1, a backport — RubyGems has it on 2025-05-23;
Consul's 1.20.2, which is eleven days off its GitHub release, not a year. 1 `ORDER` on fzf's
`0.17.0-2`. 5 links: Composer's release candidates compare from the branch point, which is
right (3); yargs' 18.1.0 compares from 18.0.0 with a 17.x backport between them in the file (1); a
link made to look wrong by a duplicate heading (1). Of the 175 warnings, 135 were rack, whose
style is `## [3.2.4]` as plain text with no version linked anywhere, and 12 were author links in
highlight.js. Each of those became a test and a fix.

**After the fixes, all 29 errors on the 112 are true.** 17 we checked against the package registry
or the release page:

- rack 2.2.9 (RubyGems: 2024-03-21), mdBook 0.2.3 (crates.io: 2019-01-18), Rich 10.16.2 (PyPI:
  2022-01-02) — a year off
- requests 0.10.2 (PyPI: 2012-02-15, changelog 2012-01-15), Poetry 0.6.1 (2018-03-18, changelog
  02-18), Tailwind CSS 0.6.2 (npm: 2018-07-11, changelog 03-11), Textual 5.1.1 (2025-07-31,
  changelog 07-21), Mongoose 1.1.9 (2011-03-23, changelog 03-02) — a month or a digit off
- Tailwind CSS 1.7.1 dated 2020-08-28, below 1.7.2 dated 2020-08-19; npm has both on 08-19
- Textual's `[7.0.0]`, `[0.80.0]`, `[0.57.0]`, Rich's `[11.0.0]`, TypeORM's 0.3.14 and 0.3.9, HTTPie's
  3.2.1 and 0.2.7 — compare links that skip a release the registry shows came out first

The other 12 can be read off the file: Flutter's 3.19.3 → `tag/3.16.3` and 3.3.7 → `tag/3.3.6`,
Traefik's `v3.0.0-rc5` heading linked to `tree/v3.0.0-rc4` and two `v2.9.0-rc1` headings (the first
linked to `rc2`), Traefik's `v2.1.0-rc2` → `tree/v2.0.4`, Commander's
`[15.0.0]: …/compare/v15.0.0...v14.0.3`, clap's two `v2.24.0` and three `v2.4.3`, Alacritty's two
`0.11.0`, Textual's two `0.15.0`. The 26 warnings: 25 headings with no link in files that link
their other versions (Tailwind's alphas, Textual's three skipped releases), and Sinatra's 4.0.1 as
`DATE?` — "or a backport listed by version", which it is.

On the replayed commits, the checker also reported errors on lines the commits did not touch: 17 in
the held-out half after the fixes. We checked one against a release page (terraform-provider-google
6.41.0 dated 2024-06-24; GitHub has 2025-06-24). The others we have not checked one by one.

---

## Limits

- **It reads the file, not the history.** A date that fits between its neighbours is not checked
  against anything, so a release dated a day before or after it was published — the most common
  fix above — passes. So does a changelog in which every date is a year off together. Comparing
  each entry with the date of its git tag would catch both; this does not read git.
- A compare link is checked against the versions the file itself lists. A link that points at
  another repository (a rename, a fork, a typo in the owner) is not checked.
- `DATE` across release lines is reported only when a one-year shift explains it. A project that
  lists backports by version and dates them honestly produces no finding — and one whose backport
  is also mis-dated produces none either; the last line counts those pairs as "not reported".
- Dates in languages other than English month names are read only in numeric form.
- AsciiDoc headings (`== 1.2.0`) and changelogs kept outside Markdown / reStructuredText / plain
  text (YAML, JSON release files) are not read.

## Files

| File | What |
|---|---|
| `changelog_check.py` | the checker |
| `test_changelog_check.py` | 67 tests; most of the later ones are a false finding from the runs above, named after the project |
| `mutation_check.py` | 43 ways to break the checker on purpose. **The first run caught 39.** Three were gaps in the tests (a line that is only a date, a heading that starts "Migrating from", a link whose base is newer than its head) and got a test each; one could never change a result, so the condition was taken out of the code |
| `replay_fixes.py` | the replays above: `--search`, `--classify`, the 313 commits (`--half`), `--repos` |
