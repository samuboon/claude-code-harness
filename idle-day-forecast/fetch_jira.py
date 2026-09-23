# -*- coding: utf-8 -*-
"""Fetch the issues idle_day_forecast.py needs from a Jira site, with their full history.

    python fetch_jira.py --base https://issues.apache.org/jira --jql "project = DISPATCH" \
        --since 2025-09-23 -o dispatch.json

    # Jira Cloud (API v3, token paging). Credentials come from the environment only:
    #   JIRA_EMAIL / JIRA_API_TOKEN  -> basic auth
    python fetch_jira.py --base https://your-site.atlassian.net --api 3 --jql "project = TEAM" \
        --since 2026-03-01 -o team.json

What it writes (one JSON file):
  meta      base, jql, since, when it was fetched, how many issues the search said there were
  statuses  every status name on the site -> its category key (new / indeterminate / done;
            "ambiguous" when two statuses share the name with different categories)
  status_ids  every status name -> the ids that carry it (crosscheck.py needs them; see there)
  issues    every issue matching the JQL that is not Done or was updated since --since, with its full
            changelog (the search result is topped up per issue when the search truncated it)
  context   issues outside the JQL that one of those issues is (or was) "blocked by", with
            their own changelog, so the forecast can tell when each blocker was finished

Standard library only. Read-only: it sends GET requests and nothing else.

Run on 2026-09-23 against a Jira Data Center site (issues.apache.org, API v2, 10 projects) and
a Jira Cloud site (issues.redhat.com, API v3, 2 projects), anonymously. On Cloud,
/rest/api/3/search/jql reports no total, so "search said N" there is only the count received.
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BLOCKED_BY = re.compile(r"is blocked by", re.IGNORECASE)
PAGE = 100


class Jira:
    def __init__(self, base, api):
        self.base = base.rstrip("/")
        self.api = api
        self.headers = {"Accept": "application/json"}
        user, token = os.environ.get("JIRA_EMAIL"), os.environ.get("JIRA_API_TOKEN")
        if user and token:
            raw = ("%s:%s" % (user, token)).encode("utf-8")
            self.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        self.calls = 0

    def get(self, path, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(5):
            req = urllib.request.Request(url, headers=self.headers, method="GET")
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    wait = int(e.headers.get("Retry-After") or 10)
                    time.sleep(min(wait, 60))
                    continue
                body = e.read()[:300].decode("utf-8", "replace")
                raise SystemExit("GET %s -> HTTP %s: %s" % (path, e.code, body))
        raise SystemExit("GET %s kept failing" % path)


def fields_param(start_field):
    f = ["summary", "status", "assignee", "created", "resolutiondate", "issuelinks", "issuetype"]
    if start_field:
        f.append(start_field)
    return ",".join(f)


def search(j, jql, fields, expand="changelog"):
    """Every issue for the JQL, with changelog expanded. Returns (issues, total_reported)."""
    out = []
    if j.api == 2:
        start, total = 0, None
        while True:
            p = {"jql": jql, "fields": fields, "maxResults": PAGE, "startAt": start}
            if expand:
                p["expand"] = expand
            d = j.get("/rest/api/2/search", p)
            total = d.get("total")
            got = d.get("issues") or []
            out.extend(got)
            start += len(got)
            if not got or start >= total:
                return out, total
    token = None
    while True:
        p = {"jql": jql, "fields": fields, "maxResults": PAGE}
        if expand:
            p["expand"] = expand
        if token:
            p["nextPageToken"] = token
        d = j.get("/rest/api/3/search/jql", p)
        out.extend(d.get("issues") or [])
        token = d.get("nextPageToken")
        if not token or d.get("isLast"):
            # search/jql reports no total; the count we got is the only count there is
            return out, len(out)


def search_keys(j, jql):
    """Only the keys (used by crosscheck.py)."""
    return search(j, jql, "created", expand=None)


def complete_changelog(j, issue):
    """The search may cut the changelog short. Top it up so every history is present."""
    cl = issue.get("changelog") or {}
    hist = cl.get("histories") or []
    total = cl.get("total", len(hist))
    if len(hist) >= total:
        issue["changelog"] = {"histories": hist, "total": len(hist)}
        return 0
    key = issue["key"]
    if j.api == 2:
        d = j.get("/rest/api/2/issue/%s" % key, {"fields": "status", "expand": "changelog"})
        hist = (d.get("changelog") or {}).get("histories") or []
    else:
        hist, start = [], 0
        while True:
            d = j.get("/rest/api/3/issue/%s/changelog" % key, {"startAt": start, "maxResults": 100})
            vals = d.get("values") or []
            hist.extend(vals)
            start += len(vals)
            if not vals or d.get("isLast", start >= d.get("total", 0)):
                break
    issue["changelog"] = {"histories": hist, "total": len(hist)}
    return 1


def blocker_keys(issue):
    keys = set()
    for link in (issue["fields"].get("issuelinks") or []):
        t = link.get("type") or {}
        if "inwardIssue" in link and BLOCKED_BY.search(t.get("inward", "")):
            keys.add(link["inwardIssue"]["key"])
    for h in issue["changelog"]["histories"]:
        for it in h.get("items") or []:
            if (it.get("field") or "").lower() != "link":
                continue
            for k, s in ((it.get("to"), it.get("toString")), (it.get("from"), it.get("fromString"))):
                if k and s and BLOCKED_BY.search(s):
                    keys.add(k)
    return keys


def slim(issue, start_field):
    f = issue["fields"]
    keep = {k: f.get(k) for k in ("summary", "status", "assignee", "created", "resolutiondate",
                                   "issuelinks", "issuetype")}
    if start_field:
        keep[start_field] = f.get(start_field)
    if keep["assignee"]:
        a = keep["assignee"]
        keep["assignee"] = {"accountId": a.get("accountId") or a.get("key") or a.get("name")}
    hist = []
    for h in issue["changelog"]["histories"]:
        items = [{k: it.get(k) for k in ("field", "fieldId", "from", "fromString", "to", "toString")}
                 for it in (h.get("items") or [])
                 if (it.get("field") or "").lower() in ("status", "assignee", "link", "project")]
        if items:
            hist.append({"created": h["created"], "items": items})
    for h in hist:  # people are identified by id only; display names are not needed and not kept
        for it in h["items"]:
            if (it["field"] or "").lower() == "assignee":
                it["fromString"] = "x" if it.get("from") or it.get("fromString") else None
                it["toString"] = "x" if it.get("to") or it.get("toString") else None
    return {"key": issue["key"], "fields": keep,
            "changelog": {"histories": hist, "total": len(hist), "complete": True}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="site root, e.g. https://issues.apache.org/jira")
    ap.add_argument("--jql", required=True, help="the issues that make up the queue, e.g. 'project = ABC'")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD; issues resolved before this are skipped")
    ap.add_argument("--api", type=int, choices=(2, 3), default=2, help="2 = Server/DC (default), 3 = Cloud")
    ap.add_argument("--start-field", help="custom field id of a start date, e.g. customfield_10015")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    try:
        dt.date.fromisoformat(a.since)
    except ValueError:
        ap.error("--since must be YYYY-MM-DD")
    if not a.base.startswith("https://"):
        ap.error("--base must be https://")

    j = Jira(a.base, a.api)
    statuses, status_ids = {}, {}
    for s in j.get("/rest/api/%d/status" % a.api):
        status_ids.setdefault(s["name"], []).append(str(s.get("id")))
        cat = (s.get("statusCategory") or {}).get("key")
        # Cloud allows the same name in several team-managed projects with different categories
        if statuses.get(s["name"], cat) != cat:
            cat = "ambiguous"
        statuses[s["name"]] = cat

    fields = fields_param(a.start_field)
    # Everything not Done now, plus everything touched since --since. A Done issue untouched since
    # then was Done the whole time. (Filtering on the resolution date instead lost issues that are
    # still Open but carry an old resolution date - it happens after migrations.)
    jql = '(%s) AND (statusCategory != Done OR updated >= "%s")' % (a.jql, a.since)
    issues, total = search(j, jql, fields)
    topped = sum(complete_changelog(j, i) for i in issues)
    have = {i["key"] for i in issues}
    need = set()
    for i in issues:
        need |= blocker_keys(i)
    need -= have
    context = []
    need = sorted(need)
    for n in range(0, len(need), 50):
        chunk = need[n:n + 50]
        got, _ = search(j, "key in (%s)" % ",".join(chunk), fields)
        for i in got:
            complete_changelog(j, i)
        context.extend(got)
    missing_ctx = sorted(set(need) - {i["key"] for i in context})

    doc = {
        "meta": {"base": a.base, "api": a.api, "jql": a.jql, "since": a.since,
                 "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "search_total": total, "fetched": len(issues), "changelogs_topped_up": topped,
                 "start_field": a.start_field, "blockers_not_readable": missing_ctx,
                 "requests": j.calls},
        "statuses": statuses,
        "status_ids": {k: sorted(set(v)) for k, v in status_ids.items()},
        "issues": [slim(i, a.start_field) for i in issues],
        "context": [slim(i, a.start_field) for i in context],
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    print("%d issues (search said %s), %d changelogs topped up, %d blockers outside the JQL, "
          "%d unreadable, %d requests -> %s"
          % (len(issues), total, topped, len(context), len(missing_ctx), j.calls, a.out))
    return 0 if len(issues) == total and not missing_ctx else 2


if __name__ == "__main__":
    sys.exit(main())
