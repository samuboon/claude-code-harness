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
| `project` | no | project key (`ABC`) or ID; omitted, the first 50 visible projects are combined |

Usable on user fields (`assignee`, `reporter`, `creator`, user custom fields)
with `in` / `not in`. Inactive users are not counted. Projects you cannot see
and groups that no longer exist are skipped rather than failing the whole query.
Only values that match the account-ID format are placed into the generated JQL.

### Limits

Up to 1,000 members (the platform ceiling); above that, pass a project as the
second argument to narrow the query. Without a project argument, the first 50
visible projects are scanned. When a role contains a group, the members are the
ones expanded at evaluation time, so a very recent transfer can take up to seven
days to appear while a cached result is still in use.

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
Jira Cloud app. The permissions it requests are shown before installation and
are the ones listed under [What the apps read](PRIVACY.md#2-what-the-apps-read).

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
