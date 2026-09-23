**日本語版: [README.ja.md](README.ja.md)**

# idle-day-forecast — when will the team run out of work it can pick up? On Jira Cloud, Jira's own history search said four issues closed in 2020–21 were open all through 2026

A Kanban team notices it has nothing ready to pull on the morning it happens. The count of
"ready, nobody on it, not blocked" issues is on the board every day, but nobody keeps its
history, and Jira has no field for it. This folder rebuilds that count for **every past day**
from each issue's changelog, and says when it reaches 0 at the recent pace.

```bash
python fetch_jira.py --base https://your-site.atlassian.net --api 3 --jql "project = TEAM" \
    --since 2025-09-23 -o team.json          # read-only GETs; JIRA_EMAIL / JIRA_API_TOKEN from the environment
python idle_day_forecast.py team.json --ready "Ready,Selected for Development"
python idle_day_forecast.py team.json --backtest          # replay a year of weekly forecasts
python idle_day_forecast.py team.json --fail-within 10    # exit 1 if it is due within 10 days (for a cron job)
python crosscheck.py team.json --every 30                 # compare the rebuilt days with Jira's own WAS search
```

```
idle-day-forecast  project = YUNIKORN  (https://issues.apache.org/jira)
as of 2026-09-23, day ends at UTC; ready = every status in the To Do category (12 on this site)
pickable now: 67  (YUNIKORN-111, YUNIKORN-1185, YUNIKORN-1202, YUNIKORN-1488, YUNIKORN-1574, ...)
last 28 days: 14 became pickable, 43 stopped being pickable -> the count fell 1.04 a day
forecast: pickable reaches 0 around 2026-11-27 (in 65 days; fastest week -> 2026-10-21, slowest week -> 2027-02-27)
history 2025-09-23 .. 2026-09-23: 0 idle days
```

Standard library only. `idle_day_forecast.py` makes no network calls; `fetch_jira.py` and
`crosscheck.py` only send GET requests.

---

## What counts as "can be picked up"

At the end of a day (in `--tz`, default UTC), an issue counts when

- it exists in the queue (created, or moved in from another project, before that moment),
- its status is a ready status — every status in the To Do category by default, or the ones you
  name with `--ready`,
- nobody is assigned (`--ignore-assignee` for teams that assign on creation),
- every issue it **is blocked by** is in a Done-category status at that moment — the blocker's
  own changelog is read, so a blocker that was reopened blocks again,
- and its start date, if you fetched one with `--start-field`, is not in the future.

The forecast is arithmetic, not a model: pickable now ÷ how much the count fell per day over the
last `--window` days (28). The range comes from the fastest and the slowest single week in that
window. A flat or growing count gets "does not reach 0", not a date.

## It refuses instead of guessing (exit 2)

A forecast built on a partial history looks exactly like a correct one. So the script stops,
and says why, when:

- the search returned fewer issues than it reported, or a changelog was cut short,
- a status name in the history is not on the site (a renamed status) or is shared by statuses of
  different categories — `--status-map "Old name=done"` resolves it,
- a history does not lead to the issue's current state (a status or assignee change with no row),
- an issue is, or was, blocked by an issue that was not fetched — including ones your account
  cannot see; `--unreadable-blockers blocking|ignore` makes that choice explicit and prints it,
- `--ready` names a status the site does not have, or the history is shorter than the window.

The one Jira Cloud project we tried that has a ready column (Red Hat's COST, anonymously) was
refused: 27 blockers we could not read, status names `M8` / `M9` that are not in the site's status
list, and two issues whose assignee was removed with no history row.

## Checked against Jira's own history search

`crosscheck.py` asks Jira, for each sampled day, which issues **WAS** in a ready status and
**WAS** unassigned **ON** that day, and compares the keys with the rebuilt day. `WAS ... ON`
matches an issue that had the value at any moment of the day while the rebuild reads the end of
the day, so issues that changed during the day are listed apart, not counted as disagreements.
Blockers are left out of both sides (JQL keeps no history for links).

Run on 2026-09-23, anonymously, `--since 2025-09-23`, one day every 30:

| Site | Projects | Days compared | Issue-days rebuilt | Same in Jira | Jira only, changed that day | Disagreements |
|---|---:|---:|---:|---:|---:|---:|
| issues.apache.org (Data Center, API v2) | 10 | 130 | 9,907 | **9,907** | 55 | **0** |
| issues.redhat.com (Cloud, API v3), project WTO | 1 | 13 | 182 | 114 | 0 | 0 after the three Cloud behaviours below |

The ten Apache projects: CASSANALYTICS, CASSSIDECAR, CELEBORN, OPENNLP, RATIS, SYNCOPE, TOBAGO,
UNOMI, WW, YUNIKORN.

**On Jira Cloud, Jira's history search was the side that was wrong**, three ways. We read every
issue involved:

1. **`status WAS "Open"` returned 0 for an issue that has been Open since 2021** (WTO-108, no status
   change ever). `status WAS 1` — the same status by id — returned it. A site with many workflows
   has many statuses called Open; the name resolves to one of them. `crosscheck.py` asks by id.
2. **`assignee WAS EMPTY` missed every issue that had been unassigned since it was created** —
   68 of the 182 issue-days, e.g. WTO-81: created unassigned in 2021, first assigned 2026-08-10,
   yet `assignee WAS EMPTY` matched it on no day at all. Issues whose assignee was *removed* at
   some point (WTO-108) did match. These are reported as "unassigned since created".
3. **Four issues Closed in 2020–21 (by their own changelogs) were listed as Open and unassigned on
   every sampled day of 2025–26** (WTO-5, WTO-7, WTO-25, WTO-82). All four carry a 2022-12-19
   "Workflow" change. They are printed as "not in file" on every run.

If you use `WAS` searches on Jira Cloud for history — sprint reports, audits, SLA — the first two
are worth checking on your own site.

## The forecast itself has not been tested on a real idle day

**In the eleven queues above, over a year, the count never reached 0 even once.** Open-source
projects keep a long unassigned backlog, and the Red Hat project kept between 9 and 15. So the backtest
(`--backtest`: a forecast every week using only the 28 days before it, checked against the next
42) has scored only "no idle day, and none came": 43 of 43 per queue — which "always say no" would
also get. It has not yet been right or wrong about an actual idle day. The queues this is meant
for — a small ready column that a team empties — are on private sites. **If you run `--backtest`
on one, the table it prints is the number this README is missing.**

A bulk close shows the limit plainly: Apache's DISPATCH project went from 201 pickable to 0 on
2026-04-16, when 201 open, unassigned issues were closed on the same day. The weekly forecasts
before it said "does not reach 0", and the backtest scores those as `missed`. Nothing in a pace can see that coming.

## Tests

42 tests (`python -m unittest test_idle_day_forecast`), on synthetic changelogs: rebuilding
status / assignee / links / moved issues / blockers that reopen / start dates / time zones, every
refusal, the forecast arithmetic and the backtest scoring. `mutation_check.py` breaks the forecaster
23 ways (an assigned issue counted as free, a blocker judged by its state today, links unwound the
wrong way, the day rounded down, a false alarm scored as right, ...) and checks the tests fail.
**First run: 21 of 22 caught.** The survivor made the backtest look for an idle day starting on the
forecast day itself — which the backtest never reaches, because it skips days that are already idle.
It was not a hole, so it was replaced with a mutation that is (forecasting from the last day instead
of the cut, i.e. seeing the future). A 23rd mutation was added with the moved-issue rule. Now 23 of 23.
`fetch_jira.py` and `crosscheck.py` have no offline tests; the table above is their test.

## What it does not do

- Custom JQL is evaluated today, not historically: an issue that entered or left the JQL by a
  change of label, component or fix version is counted by its current membership. Moves between
  projects are read from the changelog.
- The start date is its current value, not its history.
- One team, one queue. It does not know who is on leave or how many people pull.
