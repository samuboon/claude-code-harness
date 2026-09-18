# Jira Cloud apps — documentation

Documentation for five Forge apps for Jira Cloud. Each one adds a small,
specific capability that Jira's own search or issue view does not have, and
every one of them exists because a long-standing request on Atlassian's public
issue tracker asked for it.

All five run entirely on Atlassian Forge: no server, no database and no
analytics service outside your Atlassian site. See [PRIVACY.md](PRIVACY.md).

**Status (2026-09-18):** the apps are built and tested; the Marketplace
listings are being prepared. This page is the documentation URL those listings
point at, and it is updated as each app ships.

| App | What it adds | Public request it answers |
|---|---|---|
| [Consistent Date Format Fields](#consistent-date-format-fields) | Read-only fields that show a date in one site-wide format | JRACLOUD-76814 |
| [Search Remote Links in JQL](#search-remote-links-in-jql) | Five JQL functions over the web links attached to issues | JRACLOUD-28064 |
| [JQL Functions for Sprint Dates](#jql-functions-for-sprint-dates) | Filter by sprint start/end/complete dates; find issues pulled out mid-sprint | JRACLOUD-72007, JRACLOUD-75868 |
| [membersOf for Project Roles](#membersof-for-project-roles) | `membersOf()` for project roles, not just groups | JRACLOUD-77746 |
| [Business Days in JQL](#business-days-in-jql) | Count in working days instead of calendar days | JRACLOUD-22506 |

---

## Consistent Date Format Fields

Jira renders a date using the profile of the person looking at it. The same due
date can read `18/Sep/26`, `Sep 18, 2026` or `2026/09/18`, and a date-time field
can land on a different calendar day for a colleague in another time zone. This
app adds up to three read-only fields that render a date in **one format chosen
for the site**, so every person, every list and every export sees the same
string.

### Configuration

Admin → Apps → *Fixed date format*. One field per line:

```
# source field | pattern [| offset in minutes for this line]
duedate  | yyyy-MM-dd (EEE)
created  | yyyy-MM-dd HH:mm ZZ
customfield_10030 | yyyy'年'M'月'd'日'
```

The fields then appear on the issue as **Fixed date 1 / 2 / 3**.

| Source | Jira default (varies per viewer) | This field (same for everyone) |
|---|---|---|
| `duedate` = 2026-09-18 | `18/Sep/26`, `Sep 18, 2026`, `2026/09/18` | `2026-09-18 (Fri)` |
| `created` = 2026-09-18T00:30Z | `17/Sep/26 4:30 PM` for a viewer further west | `2026-09-18 09:30 +0900` |

### Pattern characters

| Characters | Output | Example |
|---|---|---|
| `yyyy` / `yy` | year | `2026` / `26` |
| `MMMM` / `MMM` / `MM` / `M` | month | `September` / `Sep` / `09` / `9` |
| `dd` / `d` | day | `08` / `8` |
| `EEEE` / `EEE` | weekday | `Friday` / `Fri` |
| `HH` / `H` / `hh` / `h` / `a` | hour | `13` / `13` / `01` / `1` / `PM` |
| `mm` / `ss` / `SSS` | minute, second, millisecond | `05` / `09` / `042` |
| `XXX` / `ZZ` | offset | `+09:00` / `+0900` (`XXX` renders UTC as `Z`) |

- Literal text goes in single quotes: `yyyy'年'M'月'd'日'` → `2026年9月18日`. `''`
  is a literal quote.
- A run of letters that is not in the table is **rejected when you save** rather
  than silently treated as literal text, so a typo cannot quietly produce a
  strange string.
- Month and weekday names come from a table inside the app (`en` and `ja`). The
  runtime locale is never consulted — consulting it would reintroduce the exact
  problem the app exists to remove.

### Time zones

- Date-time fields (`created`, `updated`, …) are rendered with the site offset
  set on the admin page; a line can override it.
- Date-only fields (`duedate`, …) get **no** offset. `2026-09-18` is a calendar
  day, not an instant, and adding an offset to it is what shifts a due date by
  one day.
- If a pattern asks for a time on a date-only field, the time is `00:00` and the
  offset characters render empty.

### Limits

Three fields per site (they are declared statically in the manifest). The site
offset is a fixed number of minutes, so a region observing daylight saving time
is off by an hour for part of the year. If the source field is empty or
unreadable the app's field is empty — it never shows a guessed date. Month and
weekday names are available in English and Japanese.

---

## Search Remote Links in JQL

Jira's built-in JQL only sees links between issues. Remote links — a GitHub pull
request, a Confluence page, an external design document — are visible only by
opening each issue one at a time. This app indexes the host, title, URL, link
relationship and application name of every remote link into a searchable issue
property, and adds five JQL functions over that index.

```jql
-- issues with a remote link to GitHub
issue in remoteLinkHost("github.com")

-- several hosts at once
issue in remoteLinkHost("github.com, gitlab.com")

-- issues with no remote link at all (finding what was missed before a release)
issue not in hasRemoteLink()

-- issues with three or more remote links
issue in hasRemoteLink("3")

-- by the linking application (exact match)
issue in remoteLinkApp("GitHub")

-- by words in the link title, or a fragment of the URL
issue in remoteLinkTitle("release notes")
issue in remoteLinkUrl("/pull/")
```

The index can also be queried directly, without learning the functions:

```jql
remoteLinkHostName = "github.com" AND remoteLinkCount >= 2
issue.property['otk-remotelink'].titles ~ "postmortem"
```

### How it works, and why it is indexed

Remote links can only be read one issue at a time, and a JQL function has 25
seconds to answer, so reading them during a search is not possible. Instead the
app maintains an index:

1. Host, application, relationship, titles, URLs and a count are written to the
   `otk-remotelink` issue property and declared as searchable entity properties.
2. The functions return a JQL fragment that points at that index, so no list of
   issue keys is returned and the 1,000-value ceiling never applies.

The index is refreshed when an issue is created or updated, and by an hourly
scheduled job that re-indexes recently updated issues and sweeps the rest of the
site page by page.

### Limits

A newly installed app starts with an empty index, so results appear as the sweep
progresses; touching an issue re-indexes it immediately. Ordinary Jira
permissions still decide which issues a search returns. Query arguments are
matched against the indexed host, title, URL and application values; `www.` is
normalised away, and only `http` and `https` links are indexed.

---

## JQL Functions for Sprint Dates

Two functions that answer questions standard JQL cannot express: which issues
belong to sprints that started, ended or completed inside a date window, and
which issues were pulled out of a sprint while it was running.

```jql
-- issues in sprints that started in September
issue in sprintsByDate("start", "2026-09-01", "2026-09-30")

-- unfinished issues from sprints that ended in the last two weeks
issue in sprintsByDate("end", "-2w", "now") AND statusCategory != Done

-- sprints completed this month on board 12 only
issue in sprintsByDate("complete", "2026-09-01", "2026-09-30", "12")

-- issues removed from sprint 42 while it was running
issue in removedFromSprint("42")

-- by sprint name; "any" ignores the sprint's own date window
issue in removedFromSprint("Sprint 7", "any")
```

### `sprintsByDate(dateField, from, to, board)`

| Argument | Required | Accepts |
|---|---|---|
| `dateField` | yes | `start` / `end` / `complete` (aliases such as `startDate` also work) |
| `from` | yes | `YYYY-MM-DD` (or `YYYY/MM/DD`), `now`, or relative: `-2w`, `+30d`, `-3M`, `-1y` |
| `to` | no | same; omit for "from that date onwards" |
| `board` | no | board ID; omit to search sprints on all boards |

Operators: `in` / `not in`. Comparison is in UTC; an absolute `from` means
00:00:00.000 of that day and an absolute `to` means 23:59:59.999, both inclusive.
Sprints with no start or end date are skipped.

### `removedFromSprint(sprint, when)`

| Argument | Required | Accepts |
|---|---|---|
| `sprint` | yes | sprint ID (number) or sprint name |
| `when` | no | `during` (default — only removals inside the sprint's own window) or `any` |

Removal is read from the issue changelog: a change to the Sprint field where the
sprint is present before and absent after. The Sprint field is located by its
schema (`com.pyxis.greenhopper.jira:gh-sprint`) rather than by name, so renamed
and translated fields still work; the name is only a fallback.

### Limits

The changelog can only be read for issues that are still on the board, so an
issue that left the sprint *and* the board (moved to another project, for
example) is not found. Most removed issues return to the backlog and stay on the
board. When a function matches nothing, it returns a fragment that is always
false rather than an empty `in ()`, which is not valid JQL.

If Jira returns the board's issues but no change history with them,
`removedFromSprint` reports an error instead of answering. "No issue was removed"
and "the history could not be read" look identical from the outside, and the
second one is not an answer worth trusting.

Both functions read Jira through paged APIs, and both stop early when they have
to: at the platform's 25-second budget, or after 1,000 issues on a single board.
**If a limit is reached before the board has been read to the end, the function
returns an error naming the limit instead of an answer assembled from the part it
managed to read.** See [Partial results](#partial-results). Looking a sprint up by
name reads boards until it finds one; if it runs out of budget first it says so,
rather than reporting that the sprint does not exist.

---

## membersOf for Project Roles

Jira's `membersOf()` understands groups only. This app adds the same thing for
project roles — Developers, Administrators, Service Desk Team and any custom
role — and expands groups that sit inside a role, so a stack of OR'd
`membersOf()` calls is no longer needed.

```jql
-- issues assigned to anyone in the Developers role of project ABC
assignee in membersOfProjectRole("Developers", "ABC")

-- issues reported by anyone who is NOT in that role
reporter not in membersOfProjectRole("Developers", "ABC")

-- roles can be given by ID; omit the project to scan visible projects
assignee in membersOfProjectRole("10002")
```

### `membersOfProjectRole(role, project)`

| Argument | Required | Accepts |
|---|---|---|
| `role` | yes | role name (case and surrounding spaces ignored) or role ID |
| `project` | no | project key (`ABC`) or ID; omitted, up to 50 visible projects are combined |

Usable on user fields (`assignee`, `reporter`, `creator`, user custom fields)
with `in` / `not in`. Inactive users are not counted. Projects and groups that no
longer exist are skipped, because "not there" and "no members" are the same
answer. Projects and groups that exist but the app is not permitted to read are
**not** skipped — see below. Only values that match the account-ID format are
placed into the generated JQL.

### Limits

Up to 1,000 members (the platform ceiling); above that, pass a project as the
second argument to narrow the query. Without a project argument the app combines
visible projects up to a ceiling of 50. When a role contains a group, the members
are the ones expanded at evaluation time, so a very recent transfer can take up
to seven days to appear while a cached result is still in use.

**If the app cannot finish the scan, it returns an error instead of a shorter
list of members** — when the site has more than 50 projects and no project
argument was given, when the 25-second budget runs out, or when a group in the
role cannot be read with the permissions the app was granted. A member list with
people missing from it quietly drops their issues out of the search result, and
nothing in the result says so. See [Partial results](#partial-results).

---

## Business Days in JQL

`-5d` and `startOfWeek()` count calendar days. These three functions count
working days, skipping weekends and the holidays you enter on the admin page.

```jql
-- in progress and untouched for five working days
status = "In Progress" AND updated <= businessDaysAgo(5)

-- due within ten working days
duedate <= businessDaysFromNow(10) AND duedate >= businessDaysAgo(0)

-- due on one of the next ten working days
duedate in businessDayRange(0, 10)

-- created on a working day in the last twenty
created in businessDayRange(-20, 0)
```

### `businessDaysAgo(days)` / `businessDaysFromNow(days)`

| Argument | Required | Accepts |
|---|---|---|
| `days` | yes | integer `0`–`750`. `0` is today, even if today is a non-working day |

Usable on date fields (`duedate`, `created`, `updated`, date custom fields) with
`=`, `!=`, `>`, `>=`, `<`, `<=`. Returns a single date.

### `businessDayRange(from, to)`

| Argument | Required | Accepts |
|---|---|---|
| `from` / `to` | yes | integers `-750`–`750`; negative is in the past, order does not matter |

Usable with `in` / `not in`. Returns the working days themselves, so a range
covering no working day becomes a fragment that is always false rather than an
empty `in ()`.

### Holiday calendar

Admin → Apps → *Business day calendar*.

| Field | Contents |
|---|---|
| Holidays | one per line: `2027-01-01`, or `2027-01-01 New Year` (text after the space is a note). Lines starting with `#` and blank lines are ignored |
| Non-working weekdays | `sat,sun` / `0,6` / `none`. Default is Saturday and Sunday, so a Friday–Saturday week is configured here |
| Site offset (minutes) | `540` for Tokyo. Forge functions run in UTC, so without this "today" can be a whole day out |

The app works with no calendar at all (weekends only). If a line cannot be read,
the valid lines are still saved and the bad ones are reported with their line
numbers — one typo does not discard the calendar. If storage is unavailable or
holds a damaged value, the functions fall back to the defaults and keep working,
because a failed search is worse for the user than a missing holiday.

### Limits

`businessDayRange` lists at most 1,000 working days (about four years). One
calendar per site; per-project calendars are not supported. "Today" follows the
site offset entered on the admin page.

---

## Installing

Each app is installed from its Atlassian Marketplace listing, like any other
Jira Cloud app. The permissions it requests are shown before installation, and
they are listed in full under [Permissions](#permissions) below.

## Licensing

These are paid apps, so the question worth answering before you install one is
not what happens while you are paying — it is **what happens on the day you stop**.
Here is the whole answer, per app.

| App | What stops when the licence lapses | What still works |
|---|---|---|
| Consistent Date Format Fields | Nothing stops inside the app | The fields keep rendering; access is controlled by the Marketplace subscription only |
| Search Remote Links in JQL | The index stops being refreshed, so web links added or removed after that day stop being findable | Existing JQL queries still run against the index as it stood |
| JQL Functions for Sprint Dates | Stored results stop being refreshed, so issues that move in or out of a sprint after that day stop showing up | Queries keep returning the last refreshed answer, until Jira drops it |
| membersOf for Project Roles | Stored results stop being refreshed, so people added to or removed from a role after that day stop being reflected | Queries keep returning the last refreshed answer, until Jira drops it |
| Business Days in JQL | Stored results stop being refreshed, so date-relative answers stop advancing with the calendar | The admin page and the holiday calendar you configured are untouched |

Three things follow from that table, and they are worth stating plainly:

- **Nothing is deleted and nothing is locked.** Your holiday calendar, your
  stored index and your saved filters stay where they are. If the subscription
  resumes, the hourly refresh picks up again on its next run and the answers are
  current within the hour.
- **Answers do not silently freeze forever.** Jira discards a custom JQL
  function's stored result after seven days without use, so a stale answer ages
  out rather than sitting there indefinitely looking correct.
- **The apps never ask Atlassian whether you have paid.** The gate is declared in
  the manifest (`filter.appIsLicensed`), which is Atlassian's own switch: the
  platform simply does not invoke the refresh on an unlicensed site. There is no
  licence check in the app's code, which means there is no code path that can
  mistake a rate-limited or failed lookup for "this customer has not paid" and
  break a site that is paying. Atlassian's licence lookup is capped at one
  request every five minutes per installation and shared across every app on
  your site — which is exactly why we do not call it from a function that runs
  on every search.

Trials, renewals, refunds and the user tiers themselves are handled by the
Atlassian Marketplace, not by these apps.

## Permissions

Every app asks for the smallest set of scopes that lets it answer the request
being made, and no app asks for a scope that none of its calls require. The
table below is the complete list, per app, checked against each app's manifest.

| App | Scopes it requests | Why |
|---|---|---|
| Consistent Date Format Fields | `read:jira-work`, `storage:app` | Read the source date off the issue being displayed; store the format you configure |
| Search Remote Links in JQL | `read:jira-work`, `write:jira-work`, `storage:app` | Read the web links on an issue; write the search index back onto that same issue as an issue property; store the sweep's bookkeeping |
| JQL Functions for Sprint Dates | `read:board-scope:jira-software`, `read:sprint:jira-software`, `read:project:jira`, `read:issue-details:jira`, `read:jira-work`, `read:app-data:jira`, `write:app-data:jira` | Read boards, sprints and the change history that says when an issue left a sprint; refresh this app's own stored query results |
| membersOf for Project Roles | `read:project-role:jira`, `read:project:jira`, `read:project-category:jira`, `read:project-version:jira`, `read:project.component:jira`, `read:project.property:jira`, `read:issue-type:jira`, `read:issue-type-hierarchy:jira`, `read:application-role:jira`, `read:group:jira`, `read:user:jira`, `read:avatar:jira`, `read:app-data:jira`, `write:app-data:jira` | Read project roles, the projects they sit on, and the members of groups inside those roles; refresh this app's own stored query results. Only the last one writes anything, and it writes to this app's own storage |
| Business Days in JQL | `storage:app`, `read:app-data:jira`, `write:app-data:jira` | Store the holiday calendar you configure; refresh this app's own stored query results. **It does not read your issues at all** |

Three of these deserve a plain explanation, because the list and the names both
read broader than what the apps do with them.

- **The long list on *membersOf for Project Roles*** is deliberate, and it used
  to be short. Until 2026-09-18 that app asked for four scopes, one of which was
  `manage:jira-configuration` — the classic scope Jira attaches to
  `GET /rest/api/3/group/member`, the call that expands a group sitting inside a
  project role. Atlassian describes that scope as "Take Jira administration
  actions (for example, create projects and custom fields, view workflows, and
  manage issue link types)". The app takes none of those actions; it creates,
  changes and deletes nothing. Rather than ask you to take our word for that, we
  moved the app onto granular scopes, which name each thing it reads. Fourteen
  lines instead of four, and the only one of the fourteen that can write is
  `write:app-data:jira`, which rewrites the app's own stored answers and is
  explained below. The list is long because of one call: the project list the
  app walks when you leave the `project` argument off carries eleven of the
  fourteen in Atlassian's granular mapping, and six of those eleven are needed
  by nothing else in the app. Ask for the argument to be required and that call
  goes away.
- **`write:jira-work`** on *Search Remote Links in JQL* is used for exactly one
  thing: writing the app's own index onto an issue as an issue property, so that
  JQL can search it. The app does not edit issue fields, comments or worklogs.
- **`read:app-data:jira` / `write:app-data:jira`** let an app read and rewrite
  *its own* stored query results. Jira evaluates a custom JQL function once and
  reuses the answer for up to seven days; an answer that depends on today's date
  or on who is in a role goes stale the moment it is stored. These scopes are
  how the app keeps its own answers honest. They give no access to your issues.

None of these scopes send anything out of your Atlassian site. See
[PRIVACY.md](PRIVACY.md).

## REST endpoints

A scope list tells you what an app is *allowed* to touch. It does not tell you
whether the app will still work next year. Atlassian retires REST endpoints on a
published schedule, and an app that keeps calling a retired one stops on the day
it goes — usually quietly, as an empty result rather than an error.

So here is the other half: every Jira REST endpoint each app calls. You can take
this list to Atlassian's own [API changelog](https://developer.atlassian.com/changelog/)
and check it without asking us.

**As of 2026-09-18, no app on this page calls an endpoint that Atlassian's API
definition marks as deprecated.** Two did until that date, and both were
replaced:

- *Search Remote Links in JQL* kept `GET /rest/api/3/search` as a fallback for
  its index sweep. Atlassian's definition says of it: "Endpoint is currently
  being removed." The fallback is gone; the app uses `GET /rest/api/3/search/jql`
  only.
- *JQL Functions for Sprint Dates* read board issues through
  `GET /rest/agile/1.0/board/{boardId}/issue`, which is deprecated along with the
  rest of the `/rest/agile/1.0/` issue listings. It now uses the enhanced
  `GET /rest/software/1.0/board/{boardId}/issue`. That one is not only a
  deprecation: `removedFromSprint` needs each issue's change history, and
  Atlassian's definition says of the old endpoint's `expand` parameter, "This
  parameter is currently not used" — so the history would have been dropped and
  the function would have answered "nothing was removed" whatever the truth was.
  `removedFromSprint` now refuses to answer at all if issues come back without
  their change history, rather than returning a confident empty result.

Neither replacement asks for a different permission, so neither changes anything
you have to approve.

| App | Endpoints it calls | What for |
|---|---|---|
| Business Days in JQL | `GET /rest/api/3/jql/function/computation`, `POST /rest/api/3/jql/function/computation` | Re-evaluate this app's own stored query results. It never reads an issue |
| Consistent Date Format Fields | `GET /rest/api/3/issue/{issueIdOrKey}` | Read the source date off the issue being displayed |
| JQL Functions for Sprint Dates | `GET /rest/agile/1.0/board`, `GET /rest/agile/1.0/board/{boardId}/sprint`, `GET /rest/agile/1.0/sprint/{sprintId}`, `GET /rest/software/1.0/board/{boardId}/issue`, `GET /rest/api/3/field`, `GET /rest/api/3/jql/function/computation`, `POST /rest/api/3/jql/function/computation` | Find boards and sprints, read the change history that says when an issue left a sprint, locate the Sprint field, re-evaluate stored results |
| Search Remote Links in JQL | `GET /rest/api/3/search/jql`, `GET /rest/api/3/issue/{issueIdOrKey}/remotelink`, `GET /rest/api/3/issue/{issueIdOrKey}/properties/{propertyKey}`, `PUT /rest/api/3/issue/{issueIdOrKey}/properties/{propertyKey}` | Walk the issues in batches, read the web links on each one, compare with the index already stored there, write it back only if it changed |
| membersOf for Project Roles | `GET /rest/api/3/project/search`, `GET /rest/api/3/project/{projectIdOrKey}/role`, `GET /rest/api/3/project/{projectIdOrKey}/role/{id}`, `GET /rest/api/3/group/member`, `GET /rest/api/3/jql/function/computation`, `POST /rest/api/3/jql/function/computation` | Find projects and their roles, expand a group that sits inside a role, re-evaluate stored results |

This table is checked against the source before every release, the same way the
[Permissions](#permissions) table is checked against each app's manifest. If an
app called an endpoint that is not listed here, or stopped calling one that is,
the check fails and the release does not go out.

## Partial results

Jira does not call a custom JQL function on every search. It calls it once, saves
the JQL fragment that comes back, and reuses that saved fragment — for every user
on the site — until the app updates it. Atlassian's documentation puts it plainly:
"Jira evaluates each custom function once and saves the result to the database."

That changes what a short answer costs. Three of the functions here answer by
reading Jira through paged APIs — `sprintsByDate`, `removedFromSprint` and
`membersOfProjectRole` — and each has a stopping point: the platform's 25-second
budget for a single invocation, a ceiling on how many pages one call will walk
(1,000 issues for a board), and, for `membersOfProjectRole`, a ceiling of 50
projects when no project is named. The business-day functions compute from their
arguments and a holiday calendar, and the remote-link functions return a fragment
that points at an index kept up to date by a scheduled job, so neither reads pages
while answering.

**When one of those is reached before the data has been read to the end, the
function returns an error naming the limit. It does not return the part it
managed to read.** A fragment built from a partial scan is valid JQL. It returns
issues. It looks exactly like a correct answer — there is no marker on it, no
warning in the search bar, and no count to compare against — and it would then be
cached and served to everyone for up to seven days.

The errors name what ran out and what to pass to get an answer: a board ID for the
sprint functions, a project key for `membersOfProjectRole`. Errors from these
functions are never stored as a cached result, so the next search retries.

Two cases are deliberately *not* treated as partial, because nothing is missing
from the answer:

- A board with no sprints (a Kanban board answers `400`) contributes no sprints.
- A project or group that no longer exists contributes no members.

A project or group that *does* exist but that the app has not been granted
permission to read is treated as partial, not as empty.

## Support

There are two forms, and picking the right one saves a round trip:

- **[It got something wrong](https://github.com/samuboon/claude-code-harness/issues/new?template=jira-app-problem.yml)**
  — a JQL function, field or admin page did not do what this page says it does.
- **[It does not cover my case](https://github.com/samuboon/claude-code-harness/issues/new?template=jira-app-gap.yml)**
  — the app is close but stops short, or you are deciding whether it would help.

Neither form fits? [Open a plain issue](https://github.com/samuboon/claude-code-harness/issues/new),
or use the support contact on the app's Marketplace listing if you would rather
not write in public.

**Please do not paste real data into a public issue.** These apps are built so
that nothing leaves your Jira site, and an issue here would be the one place it
went. Rewrite issue keys as `ABC-1` and people as `Alice`, and leave the site
URL out — a JQL query with the names changed still reproduces almost every bug
worth reporting.

## Privacy

[PRIVACY.md](PRIVACY.md) — what the apps read, what they store, and what leaves
your site (nothing).
