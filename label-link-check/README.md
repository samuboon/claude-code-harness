**日本語: [README.ja.md](README.ja.md)**

# label-link-check — Bootstrap's bug report form files every report under `bug`. Bootstrap has no label called `bug`

`twbs/bootstrap`'s `.github/ISSUE_TEMPLATE/bug_report.yml` says `labels: [bug]`, and the "Report bug"
link at the top of its README says `labels=bug`. The repository has 69 labels; `bug` is not one of
them (`browser-bug` and `confirmed` are). GitHub's issue-forms page says what happens next: *"If a
label does not already exist in the repository, it will not be automatically added to the issue."*
Searching Bootstrap's issues for `label:bug` returns 0. For `label:confirmed`, 1,199.

Nothing fails when this happens. A link to `github.com/OWNER/REPO/labels/NO-SUCH-LABEL` answers
**HTTP 200** — it is an issue list, and an empty issue list is a good page — so every link checker
passes it. The form still opens and the issue is still filed. The only symptom is a triage query
that comes back short, forever.

`label_link_check.py` reads the links and the issue templates, reads the repository's real label
list, and names every label that is not on it, with the closest one that is.

```bash
python label_link_check.py                       # the checkout you are in (repo from the origin remote)
python label_link_check.py docs/ --repo OWNER/NAME
python label_link_check.py . --labels labels.json --offline   # `gh label list --json name > labels.json`
python label_link_check.py . --json
```

On today's default branches (2026-09-24):

```
$ python label_link_check.py bootstrap
.github/ISSUE_TEMPLATE/bug_report.yml:4: error LABEL twbs/bootstrap: template label "bug" does not exist in twbs/bootstrap, so issues filed with this template never get it
README.md:15: error LABEL twbs/bootstrap: label "bug" does not exist in twbs/bootstrap

$ python label_link_check.py flutter
docs/about/Project-teams.md:29: error LABEL flutter/flutter: label "team: infra" does not exist in flutter/flutter (did you mean "team-infra"?)
docs/engine/Using-Sanitizers-with-the-Flutter-Engine.md:54: error LABEL flutter/flutter: label "sanitizer" does not exist in flutter/flutter (did you mean "from: sanitizer"?)

$ python label_link_check.py p5.js
contributor_docs/contributor_guidelines.md:78: error TEMPLATE processing/p5.js: template found-a-bug.yml is not in processing/p5.js/.github/ISSUE_TEMPLATE (did you mean 2-found-a-bug.yml?)
contributor_docs/ja/contributor_guidelines.md:78: error LABEL processing/p5.js: label "Bug\" does not exist in processing/p5.js (did you mean "Bug"?)
```

p5.js renamed its templates with a number in front; the contributor guide still links the old
names, **30 times across six translations**. The Japanese and Chinese copies also carry
`labels=Bug%5C` — a backslash that a translation step escaped into the URL, so the label GitHub is
asked for is `Bug\`.

Standard library only. It reads files and GitHub's label list; it runs nothing, writes nothing and
posts nothing. Exit code 1 when there is an error, 0 when there is none, **2 when the label list of
the repository itself could not be read** — a check that read nothing must not print a pass.

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `LABEL` | error | The label is not in the repository. Case is ignored, as GitHub's search ignores it. Read from `…/labels/NAME`, `issues?q=label:…`, `issues?labels=a,b`, `issues/new?labels=…`, `github.com/issues?q=repo:… label:…`, and the `labels:` of every issue template. |
| `TEMPLATE` | error | `issues/new?template=x.yml` names a file that is not in `.github/ISSUE_TEMPLATE/`. When the repository has no such folder, the owner's `.github` repository is asked, since that is where GitHub takes the defaults from. `template=BLANK_ISSUE` is GitHub's own name and is not a file. |
| `UNQUOTED` | error | `label:good first issue` — GitHub reads the label `good` and two words of text. Only `label:"good first issue"` is one label. Reported when the quoted form is a real label. |
| `QUOTED_PATH` | error | `…/labels/%22good%20first%20issue%22`. The label page puts the quotes **inside** the name: the page's own query is `label:"\"good first issue\""`. |
| `IS_VALUE` | error | `is:opened`, `state:all` — not values those qualifiers take; the query matches nothing. |
| `NO_REPO` | error | The repository in the link was not found (deleted, or private). A renamed repository redirects and is fine. |
| `CASE` | warning | The label exists, spelled with different case. |
| `OR_LABEL` | warning | `label:a,b` where only one exists. The link still shows the other one's issues. |
| `NEG_LABEL` | warning | `-label:x` for a label that does not exist excludes nothing. |
| `QUALIFIER` | warning | `lable:bug` — not a qualifier; GitHub searches it as text. |
| `PLUS_PATH` | warning | `…/labels/help+wanted`: in a path `+` is a plus sign. (The REST API returns 404 for `vuejs/core`'s `good+first+issue`.) |
| `UNCHECKED` | warning | A label or template list could not be read, so those links were not judged. |

Links into **other** repositories are checked against those repositories' labels (one API call
per 100 labels). A label list that runs past 100 pages is treated as unreadable rather than used
half-read — our own measurement first cut `elastic/kibana`'s 1,665 labels at 1,000 and turned four
real labels into four errors. Labels come from `--labels`, or the REST API with `GITHUB_TOKEN` /
`GH_TOKEN` if set (60 requests an hour without).

---

## How we know it is right

Everything below was measured on 2026-09-24. The two tests are the ones every tool in this
repository gets: **commits in which people fixed this by hand, replayed before and after**, and
**repositories set aside before any tuning**, on which the first version's precision is reported.

**Well-known repositories.** The 300 most-starred repositories above 30,000 stars and 200 between
5,000 and 30,000 that have good first issues — 486 once archived ones and duplicates are out. Their
READMEs, contributing guides, docs and `.github/`: **16,793 files, 2,614 links and template
labels**. Halved by a hash of the name before tuning.

| | Held out (245), first version | All 486, final version |
|---|---:|---:|
| `LABEL` errors | 97 | 150 |
| …confirmed | **93** | **150** |
| `TEMPLATE` errors | 43 | 54 |
| …confirmed | **43** | **54** |
| Repositories with at least one error | 45 | 86 |

*Confirmed* means, for a label: the label is not in the list **and** none of the issues and pull
requests GitHub's search returns for it (the first 30 of each) carries it today. For a template: the file is in neither the
repository's `.github/ISSUE_TEMPLATE/` nor the owner's `.github` repository. The **4** held-out
errors that were not confirmed are the `elastic/kibana` labels our harness had cut off at 1,000;
the checker itself read up to 3,000 then and now refuses a list it cannot finish. The one false
`TEMPLATE` error we found was on the tuning half (`scikit-learn`'s `template=BLANK_ISSUE`); it is
why that name is skipped. The held-out warnings were 14 `CASE`, 5 `NEG_LABEL` (true) and 1
`QUALIFIER` that was wrong — `title:` works as a search qualifier, and is now known.

Of the 366 repositories that have issue templates, **62 name at least one label that does not
exist — 100 labels in all**: `open-webui` (`triage`), `langchain` (`task`), `llama.cpp`
(`compilation`, `model evaluation`, `refactor` for `refactoring`), `github/spec-kit` (`bug`,
`agent-request`), Next.js's bug form (`type: example`, `template: bug`, and a link to
`2.example_bug_report.yml`, which is gone).

**The search index remembers deleted labels.** For 7 of the 150, GitHub's search still returns
issues — `facebook/docusaurus`'s `label:"help wanted"` returns 186, and **none of the first 30
carries the label now**. So for those, the link in CONTRIBUTING.md is not empty; it lists old issues under a
label that no longer exists. That is also why "confirmed" above asks whether a returned issue
*carries* the label, not whether the search returned anything: the first version of our own check
counted results, and called 6 real findings false.

**Commits that fixed it by hand.** Commit search for 46 phrasings ("fix good first issue link",
"fix issue template label", "nonexistent label" …) gave 4,769 commits with one parent and a
message about labels or templates; 606 removed a line with a GitHub issue link or a `labels:` key,
and **164 changed a label link or a template's `labels:`**. Halved by a hash of the commit before tuning. For each commit, the changed files as they
were before and after, today's labels, and the template folder at each of the two commits:

| | Held out (80), first version | All 164, final version |
|---|---:|---:|
| Error before, gone after (**caught**) | **36** | 72 |
| Same errors before and after | 9 | 17 |
| An error only after | 1 | 4 |
| A warning before, gone after | 0 | 1 |
| No error either side | 34 | 70 |

We read all 34 held-out commits with no error. **One should have been caught**:
`labels/good%20first%20issue!` — the checker strips a `!` after a link as punctuation, and here it
was part of the URL. **One more was caught by a change made on the tuning half** (a quote inside the
URL, `label%3A"good+first-issue"`). The other 32 were not a missing label or template: a link
switched to a different label that also exists, a link moved to a renamed repository that GitHub
redirects, a link widened to an organisation- or user-wide search (which it does not check),
checkbox `label:` keys inside form bodies, formatting and wording.

The "same errors after" rows are the commit fixing something else — every one of the 49 labels
still wrong after a commit is confirmed by search. **The "error only after" rows include one worth
knowing about**: vercel/next.js #80478, *"chore: fix link to good first issue … Link to
good-first-issue lacked some encoding"* (2025-06-13), turned `labels/good%20first%20issue` into
`labels/%22good%20first%20issue%22`. The label page's own query for that URL is
`label:"\"good first issue\""`. The link has since been put back.

`replay_fixes.py` replays the 164 commits in `replay_commits.tsv`. It is the one file here that reads
from GitHub beyond the label lists.

---

## What it does not do

- **It does not know what a label used to be called.** It says `sanitizer` is missing and suggests
  `from: sanitizer` because that is the only label ending in the same word; it cannot know the
  rename happened.
- **Organisation-wide and user-wide searches** (`org:`, `user:`) are not checked: labels belong to
  repositories.
- **Relative links** (`../../labels/bug`) are not read.
- **It does not know GitHub's rules beyond the documented ones.** A template `labels:` string is
  split at commas, as the syntax page says, so `labels: C-tracking-issue T-compiler A-lints` (in
  `rust-lang/rust`) is one label name and is reported. Whether GitHub splits a comma *inside* a YAML
  list item is not documented; we split it, so we never report a label GitHub may have applied.
- **A `!` or `.` at the end of a URL is taken as punctuation** — the one held-out miss above.
- **Issue types, projects and milestones** in templates and links are not checked.

## In CI

```yaml
- uses: actions/checkout@v4
- run: python tools/label_link_check.py .
  env:
    GITHUB_TOKEN: ${{ github.token }}
```

`label_link_check.py` is one file; copy it to wherever the `run:` line points. We have not run this
snippet on GitHub Actions ourselves.

## Tests

`python test_label_link_check.py` — 83 tests. `python mutation_check.py` breaks the checker 41
ways, one at a time, and fails if the tests do not notice: **all 41 are caught; the first run caught
27 of the first 29** (an `&amp;` left in an HTML link and grouping parentheses kept on a query
token both survived, because the tests were written so that neither mattered).

This repository's own five issue templates named six labels that did not exist
(`key-expiry-result`, `jira-apps` …). It was the first thing the checker found. The labels were
created on 2026-09-24; it now reports 0.
