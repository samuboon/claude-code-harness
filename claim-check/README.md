**日本語: [README.ja.md](README.ja.md)**

# claim-check — milvus#27468 has been assigned for 631 days to someone who said "I would like to work on this issue". Two people have asked for it since

`milvus-io/milvus#27468` ("Improve milvus cli") is labelled `good first issue`. On 2024-12-31 a
volunteer wrote *"If nobody is working on this issue, I would like to work on this issue."*
Twenty-seven minutes later a maintainer answered `/assign @… please help on it`. That is the last
word from the volunteer on it. On 2026-05-28 someone asked *"Can I take a shot at it?"*; on
2026-06-24 someone else asked to be assigned *"or the last person, or else you may close it"*.
Neither got an answer. The issue has a second assignee, who asked for it in July 2024 and has not
been heard from either.

Nothing expires a claim. Because the issue is assigned, it is off every `no:assignee` list —
the filter a volunteer uses to find something free. A stale bot counts days since *any* activity,
and "can I take this?" is activity, so every new volunteer resets its clock. The only one who can see that the
claim is dead is someone who reads the whole thread.

`claim_check.py` reads it. For every person who claimed an open issue — *"I'd like to work on
this"*, *"can I take this?"*, *"please assign it to me"*, `/assign`, *"I'll look into it"* — it
asks one question: has that person done anything on it since?

```bash
python claim_check.py OWNER/NAME                     # every open issue
python claim_check.py OWNER/NAME --label "good first issue"
python claim_check.py OWNER/NAME --days 60           # quiet for 60 days, not 30
python claim_check.py OWNER/NAME --as-of 2026-03-24  # as the issues were on that day
python claim_check.py OWNER/NAME --json
```

A real run, without a token, on 2026-09-24 (user names replaced with `@…` here; the checker prints them):

```
$ python claim_check.py Ebazhanov/linkedin-skill-assessments-quizzes
Ebazhanov/linkedin-skill-assessments-quizzes#3731: error GONE @…: "i've been working on them and you can see the progress on the 'saves' branch." (2022-06-12) -- nothing from them in 1564 days; still assigned to them
Ebazhanov/linkedin-skill-assessments-quizzes#5250: error GONE @…: "assign me" (2023-05-15) -- nothing from them in 1227 days; still assigned to them; 2 other pull requests from them here since
Ebazhanov/linkedin-skill-assessments-quizzes#5392: error GONE @…: "assign me this task" (2023-05-15) -- nothing from them in 1227 days; still assigned to them; 2 other pull requests from them here since
Ebazhanov/linkedin-skill-assessments-quizzes#5733: error GONE @…: "assign me i know answer these questions" (2023-05-14) -- nothing from them in 1226 days; still assigned to them; 2 other pull requests from them here since
Ebazhanov/linkedin-skill-assessments-quizzes#6881: error GONE @…: "can you assign it to me?" (2023-11-02) -- nothing from them in 1056 days; still assigned to them; 1 other pull request from them here since
Ebazhanov/linkedin-skill-assessments-quizzes#5491: warning UNANSWERED @…: "please assign this issue to me." (2023-10-06) -- nothing from them in 1083 days; nobody from the project answered
16 open issues read; 5 GONE, 0 QUIET, 1 UNANSWERED (silent 30+ days)
```

The claims are case-folded and quoted as the checker read them — quotes, code and mentions out.
A run before the last fix called #6881 `UNANSWERED`: its claim ends in a question, and an
assignment was not yet counted as the answer.

Standard library only. It reads; it never comments, assigns or labels. Exit code 1 when there is a
`GONE`, 0 when there is none, **2 when a repository or an issue's timeline could not be read** — a
check that read nothing must not print a pass.

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `GONE` | error | The issue is still assigned to them, and nothing from them since. It is off every `no:assignee` list until someone notices. |
| `QUIET` | warning | Not assigned. A maintainer answered (or they are one), then nothing from them. Often the answer was "not yet" or "not this one" — read it. |
| `UNANSWERED` | warning | They offered and nobody from the project answered — or their last word was a question nobody answered. The silence may be the project's. |
| `UNCHECKED` | warning | An issue's timeline could not be read; its claims were not judged. |

A claim **ends** when the claimant delivers (a pull request of theirs that links or names the
issue), lets it go (*"I don't have time for this anymore, feel free to take it"*), or the project
moves on (they are unassigned, someone else is assigned, someone else's pull request links or
names the issue). A later comment, a commit or a cross-reference of theirs resets the clock. A claim
made while someone else holds the issue — who still does — is not reported. Quoted lines (`>`),
code, HTML comments and `/assign @someone-else` are not read as claims; neither are bots or
accounts that relay other trackers (`jenkins-infra-bot`, `swift-ci`). Every line says how many
other people asked to take the issue after the claimant fell silent.

**Pull requests the timeline does not show.** For each finding it runs two searches — the
claimant's pull requests in the repository since the claim, and pull requests that contain the
issue number — and drops the finding when one of them names the issue (`#N` or its URL). With a
token it also reads each issue's *closing* pull requests from GraphQL. The reason is below.

---

## How we know it is right

Everything was measured on 2026-09-24. We took the 333 repositories with at least 10 `good first
issue`s and 5,000 stars, and **halved them by a hash of the name before tuning the checker on any
of them**. For each, the open issues whose comments contain claim-like words (five searches, up to
100 issues each). We tuned on one half (164 repositories). From the other half we measured the
first version on the 80 with the most stars (79 were readable that day); then, because we read
those 80's mistakes to fix the checker, we measured the final version on **the other 83, which no
version had been run on** (six more we had glanced at were left out).

| | First version · 79 held out | Final version · 83 unseen |
|---|---:|---:|
| Open issues read | 16,849 | 13,844 |
| `GONE` from the timeline | 1,293 | 252 |
| …drawn at random / left after the searches / **real** | 320 / 185 / **95 (51%)** | 228 / 150 / **103 (69%)** |
| `QUIET` from the timeline | — | 662 |
| …drawn / left / **real** | — | 92 / 60 / **30 (50%)** |
| `UNANSWERED` from the timeline | 1,729 | 1,315 |
| …drawn / left / **real** | 160 / 89 / **69 (78%)** | 80 / 60 / **43 (72%)** |

"Left after the searches" is what the checker prints: the rest were dropped because a pull request
named the issue (for the first version's sample, also because closing pull requests had not yet
been read — 105 of the 320). **The searches drop a quarter to a third of what the timeline alone
reports** — 78 of 228 `GONE`, 32 of 92 `QUIET`, 20 of 80 `UNANSWERED` on the unseen 83.

*Real* is the verdict of a reader who saw the claim, everything on the timeline after it, and the
titles of every pull request the claimant opened in the repository since: the comment is a claim
on this issue; nothing shows they followed through; nothing shows the claim no longer matters
(declined, already fixed, handed to someone else, withdrawn); and, for `GONE` and `QUIET`, the
silence is theirs, not an unanswered question of theirs. The readers were separate model
sessions given only those rules and the record, not the checker's code. All 569 verdicts —
repository, issue, code, verdict, reason — are in [`judged.tsv`](judged.tsv) (no user names).

**The first version was wrong half the time on `GONE`.** Of 185 sampled, 95 were real. It called a
claim `GONE` whenever a maintainer had answered, and the answers were often *"one issue at a time
for new contributors"*, *"this needs a design decision first"*, *"this is already fixed"* (25
declined or moot), or a question back that nobody answered (15), or someone else was already on it
(15). Among the first version's `GONE`, the claims still assigned to the claimant were 66% real
(53 of 80); the ones where "a maintainer answered" were 38% (36 of 94). That is the split the final
version reports: `GONE` for the assigned ones, `QUIET` for the rest.

**On the 83 unseen repositories the final version's `GONE` is 69% real (103 of 150).** Of the 47
that were not, 21 are claimants whose pull request plainly does the work without naming the issue
— the line shows *"N other pull requests from them here since"*, which is where to look — and 14
are claimants waiting on the project (a dependency to merge, a review of their approach, a decision)
in words the checker does not read as an open question. `QUIET` is a coin
toss (30 of 60), which is why it is a warning: the maintainer's answer is often *"not yet"*.

Two things changed after that measurement, both from reading one issue in full: `/assign @someone`
(a maintainer assigning someone else) is no longer read as the maintainer's own claim, and being
assigned now counts as the answer to *"can I take this?"*. On the 83 unseen repositories the
second moves 35 findings from `UNANSWERED` to `GONE` (one more disappears); we drew those 35 and
judged the 25 the searches left: **21 real (84%)**. The published version reports **287 `GONE`** there
before the searches; weighting the two samples, about 71% of what it prints as `GONE` is real.

### A token can hide every pull request

The first thing we measured was wrong. Reading timelines with a fine-grained token that had not
been granted the repository, **not one cross-reference came back**: 41,780 issues in 206
repositories, 0 cross-referenced events (515 manually "connected" pull requests did come back).
The same request without a token shows them — `apache/airflow#9186` has two cross-referenced pull
requests anonymously and none with that token. So the checker was calling delivered work
abandoned. GraphQL's `closedByPullRequestsReferences` — the pull requests that say "fixes #N" — is
still readable with such a token; adding it removed **716 of 2,016 `GONE` (36%) and 1,110 of 2,851
`UNANSWERED` (39%)** from the first version's count on the 80 held-out repositories. What it
cannot supply is a pull request that names the issue without "fixes" — that is what the two
searches are for — or one in another repository. Two of the four examples we
re-read anonymously show both: `recharts/recharts#4438` is still assigned to someone silent since
April 2024, but in August 2026 a maintainer told someone else *"Go for it"*, and three pull requests
of theirs name the issue. The timeline read with the token showed none of them; the number search
finds all three, and the finding is dropped. `apache/dubbo#13861`'s claimant opened
`apache/dubbo-samples#1132` five days after the claim — a pull request in another repository — and
the checker, with the token, still reports them (with *"47 other pull requests from them here
since"*, which is the hint to look).

The checker now says so when it happens: if some issues have closing pull requests and no timeline
shows a single cross-reference, it prints that the token cannot see them.

### Six months later

`--as-of 2026-03-24` judges the issues as they were that day. We ran the final version that way on
the 80 held-out repositories (their issues open on 2026-03-24, including the ones closed since) and
looked at what happened in the six months after: did the claimant come back — a comment, a commit,
a pull request that links or names the issue?

| Silent on 2026-03-24 | Claims | Claimant came back by 2026-09-24 |
|---|---:|---:|
| 0–6 days | 74 | 20 (27%) |
| 7–13 days | 52 | 13 (25%) |
| 14–29 days | 125 | 19 (15%) |
| 30–59 days | 178 | 13 (7.3%) |
| 60–89 days | 166 | 4 (2.4%) |
| 90–179 days | 426 | 13 (3.1%) |
| 180–364 days | 337 | 11 (3.3%) |
| a year or more | 1,594 | 23 (1.4%) |

The first three rows are claims the checker does not report; the rest are ones it does. All 2,952
claims open that day are counted, from the timeline alone. **Under 30 days of silence, 1 in 5
claimants came back in the next six months. Past 30 days, 1 in 42 (64 of 2,701).** We also
applied the two pull-request searches to 663 of these claims (every one the first version had
under 30 days, and 400 of the rest drawn at random) and dropped the ones whose pull request had
already named the issue: under 30 days 37 of 199 came back (19%); past 30 days 9 of 326 (2.8%) —
6 of the 52 still assigned, none of the 91 `QUIET`, 3 of the 183 `UNANSWERED`.

### People who asked by hand

The same check is done by hand, one issue at a time: *"@someone, are you still working on this?"*
On the 80 held-out repositories we found 344 such comments that name a person who had commented
before. At the moment each was posted, the checker had that person's claim open in **173 (50%)**.
Of the other 171, 117 were asked of someone who had never written a claim sentence — assigned
directly, or the author of a pull request — and the rest had a claim the checker had already
closed (a pull request, a hand-over, or an issue someone else held).

People asked early: the median claimant had been silent **19 days**, and 64 of the 173 (37%) had
been silent 30 days or more — for those, a 30-day check would have listed the issue a median of
60 days before anyone asked. **And asking works while it is early.** The claimant answered within
30 days 78% of the time when asked within two weeks of their last word (60 of 77), 72% at 14–29
days (23 of 32), 70% at 30–89 days (21 of 30), and **38% past 90 days (13 of 34)**. These are the
claims somebody cared enough about to ask; the six-month table above is every claim. We do not
claim the asking caused the answers.

---

## What it does not do

- **English only.** A claim in another language is not read.
- **A claim without words is not read.** Someone assigned without ever saying anything is not a
  claimant here; actions that unassign after N days of assignment cover that case.
- **Two assignees.** When someone else is assigned after them, their claim is taken as handed over,
  even if they stay assigned. `milvus#27468`'s first assignee is not reported for that reason.
- **Pull requests in another repository**, when a token hides cross-references (`apache/dubbo#13861`
  above). Without a token they are on the timeline and are read.
- **A pull request that addresses the issue without naming it** counts as silence; the line says
  how many other pull requests the claimant opened in the repository since, so you can look. In the
  final version's unseen sample this was 21 of the 150 `GONE`.
- **It does not read what a maintainer's answer meant.** That is why `QUIET` is a warning.
- **It does not ask anyone anything.** What it prints is a list of people to ask.
- Two searches per finding: with a token GitHub allows 30 a minute, without one 10 (`--no-search`
  skips them, and the pull-request checks with them).

## In CI

```yaml
on:
  schedule: [{cron: "0 6 * * 1"}]
jobs:
  claims:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python tools/claim_check.py ${{ github.repository }} --label "good first issue"
        env:
          GITHUB_TOKEN: ${{ github.token }}
```

`claim_check.py` is one file; copy it to wherever the `run:` line points. We have not run this on
GitHub Actions ourselves, and do not know whether its token sees cross-references — the checker
will say if it does not.

## Tests

`python test_claim_check.py` — 44 tests. `python mutation_check.py` breaks the checker 47 ways, one
at a time, and fails if the tests do not notice: **all 47 are caught. The first run caught 33 of
35**: a typographic apostrophe in *"I don’t think I can take this on"* went unnoticed, and one
mutation could not change any result — writing the test that replaced it found a real bug (people
who asked for the issue *before* the claimant's last word were counted as asking *since*).
