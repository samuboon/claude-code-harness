#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pjo_exit_check.py - count what your Project Online export is missing, before 2026-09-30.

Project Online retires on **9/30/2026 8:00:00 AM Pacific Time**. After that the
tenant data is gone, so the only thing that matters between now and then is
whether the export you already ran actually produced every file it was supposed
to produce. `ExportProjectUserContent.ps1` prints no manifest and no summary, so
"it finished" and "it is complete" are not the same statement.

This script reads a directory that the export script wrote and answers three
questions:

    deadline   how long is left, to the hour, in the timezone Microsoft uses
    check      which of the documented files are missing, empty, or unaccounted for
    checklist  what the export script does NOT produce, so you save it by hand

Standard library only. Python 3.8+. It never touches the network and never
writes to the directory it is checking.

    python pjo_exit_check.py deadline
    python pjo_exit_check.py check C:\\pwa1siteOutput
    python pjo_exit_check.py check out_userA out_userB --json
    python pjo_exit_check.py checklist

Exit codes: 0 = nothing missing / 1 = something missing or empty / 2 = bad usage.

--------------------------------------------------------------------------------
Where the expected file list comes from (all of it is public documentation; this
script contains no guesses about the *contents* of the files):

  [L] https://learn.microsoft.com/en-us/lifecycle/products/project-online
      | Project Online | 3/1/2013 8:00:00 AM | 9/30/2026 8:00:00 AM |
      "Support dates are shown in the Pacific Time Zone (PT) - Redmond, WA, USA."
  [E] https://learn.microsoft.com/en-us/projectonline/export-user-data-from-project-online
      Step 5 ("Review your exported content") and the -Options table in Step 4.

NOT CONFIRMED, and deliberately not guessed at anywhere below:
  * the internal structure of the exported project .xml files. This script does
    not parse them. It only parses *ProjectList.xml, and only for the property
    `Proj_Name`, which [E] states is present.
  * how the export script turns a project *name* into a *filename* when the name
    contains characters that are not legal in a filename. [E] does not say.
  * the file extension of the eight reporting files. [E] calls them ".json files"
    in prose but lists them without an extension. Both forms are accepted.
"""
import argparse
import datetime
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

# --- the deadline -------------------------------------------------------------
# [L] gives 9/30/2026 8:00:00 AM and states the table is in Pacific Time.
# 2026-09-30 is inside US daylight saving time (DST 2026 runs 03-08 to 11-01),
# so Pacific is UTC-7 that day. Fixed offset is used on purpose: zoneinfo needs
# the tzdata package on Windows, and this script has no dependencies.
RETIREMENT_UTC = datetime.datetime(2026, 9, 30, 15, 0, 0, tzinfo=datetime.timezone.utc)
RETIREMENT_TEXT = "9/30/2026 8:00:00 AM Pacific Time (= 2026-09-30 15:00 UTC)"

# --- the three project-list files [E, Step 5] ---------------------------------
PROJECT_LIST_FILES = ["DraftProjectList.xml", "PublishedProjectList.xml", "ReportingProjectList.xml"]

# --- per-project files [E, Step 5] --------------------------------------------
# Each entry: (label, [accepted suffixes, lowercase, appended to the project name])
# Seven of the eight reporting names differ between Step 5 and the -Options table
# only in capitalisation, so a case-insensitive match collapses them. One differs
# in the actual word: Step 5 says "Reporting_ProjectBaseline", the -Options table
# says "reporting_Baselines". Both are accepted, and `check` says which it found.
PER_PROJECT = [
    ("draft .xml", ["_draft.xml"]),
    ("published .xml", ["_published.xml"]),
    ("draft .mpp", ["_draft.mpp"]),
    ("published .mpp", ["_published.mpp"]),
    ("draft metadata .json", ["_draft.json"]),
    ("published metadata .json", ["_published.json"]),
    ("reporting metadata .json", ["_reporting.json"]),
    ("reporting Tasks", ["_reporting_tasks.json", "_reporting_tasks"]),
    ("reporting Assignments", ["_reporting_assignments.json", "_reporting_assignments"]),
    ("reporting Resources", ["_reporting_resources.json", "_reporting_resources"]),
    ("reporting ProjectBaseline", ["_reporting_projectbaseline.json", "_reporting_projectbaseline",
                                   "_reporting_baselines.json", "_reporting_baselines"]),
    ("reporting TaskTimephased", ["_reporting_tasktimephased.json", "_reporting_tasktimephased"]),
    ("reporting AssignmentTimephased", ["_reporting_assignmenttimephased.json",
                                        "_reporting_assignmenttimephased"]),
    ("reporting TaskBaselineTimephased", ["_reporting_taskbaselinetimephased.json",
                                          "_reporting_taskbaselinetimephased"]),
    ("reporting AssignmentBaselineTimephased", ["_reporting_assignmentbaselinetimephased.json",
                                                "_reporting_assignmentbaselinetimephased"]),
]

# [E, Step 5] says project-specific files are "prefixed with the specific project's
# Project Name". The -Options table in Step 4 writes the same files with a literal
# `Project_` in front (`Project_projName_draft.json`). Both are accepted.
NAME_PREFIXES = ["", "project_"]

# --- the 27 feature files [E, Step 5, "Feature-related files"] ----------------
# (canonical name, [accepted names, lowercase], paged?)
# Aliases are not invented: each one appears somewhere else in the same page.
FEATURE_FILES = [
    ("AdminAudit", ["adminaudit"], False),
    ("BusinessDrivers", ["businessdrivers", "drivers"], False),           # prose says "Drivers.json"
    ("Calendars", ["calendars"], False),
    ("CustomFields", ["customfields"], False),
    ("Delegations", ["delegations"], False),
    ("DriverPrioritizations", ["driverprioritizations"], False),
    ("Engagements", ["engagements"], True),
    ("LookupTables", ["lookuptables"], False),
    ("PortfolioAnalysis", ["portfolioanalysis", "portfolioanalyses"], False),  # -Options spelling
    ("QueueJobs", ["queuejobs"], False),
    ("ReminderEmails", ["reminderemails"], False),
    ("ReportingResource", ["reportingresource"], False),
    ("Resource", ["resource"], False),
    ("ResourcePlans", ["resourceplans"], True),
    ("Rules", ["rules"], False),
    ("Security", ["security"], False),
    ("StatusReports", ["statusreports"], False),
    ("SubscribedReminders", ["subscribedreminders"], False),
    ("TaskStatus_AssignmentsHistory",
     ["taskstatus_assignmentshistory", "taskstatus_assignmenthistory"], True),  # doc drops the "s"
    ("TaskStatus_AssignmentsSaved", ["taskstatus_assignmentssaved"], False),
    ("TaskStatus_AssignmentsSubmitted", ["taskstatus_assignmentssubmitted"], False),
    ("Timesheets", ["timesheets"], True),
    ("Timesheets_Reporting", ["timesheets_reporting"], False),
    ("UnsubscribedAlerts", ["unsubscribedalerts"], False),
    ("UserViewSettings", ["userviewsettings"], False),
    ("Workflow", ["workflow"], False),
    ("WorkspaceItems", ["workspaceitems"], False),
]

# Listed in the -Options table (ResourcePlans row) but absent from the table of 27.
# Treated as optional so its absence is not reported as a missing file.
OPTIONAL_FILES = [("ReportingResourcePlans", ["reportingresourceplans"])]

PAGE_RE = re.compile(r"_page\d+$")

# Things the export script does not produce [E, Step 6 and the two "Considerations"
# sections]. A file checker cannot verify these; it can only refuse to let you
# forget them.
MANUAL_ITEMS = [
    ('Custom views, custom filters, custom tables, attachments and macros. '
     '[E, Step 6]: "you will need to have the MPP and XML file for each project '
     'in which you want to search." They are not separate files in the export.'),
    ('Project Home favourites and recently-viewed projects. [E]: "Data for a '
     "user's favorite and recently viewed projects in Project Home can only be "
     'accessed directly in-app." The documented method is a screenshot.'),
    ('Projects the user was not part of. [E]: "the export script will only export '
     'projects that the user was a part of as an owner, has an assigned task, is '
     'an assignment owner of a task, or is the status manager of a task." One run '
     'per user per PWA site; a tenant is users x PWA sites, not one export.'),
    ('A way back in. [E]: "Saving the exported .mpp files back to Project Online '
     'or Project Server is not supported." Whatever you keep is the final copy.'),
    ('Inserted/master project pairs. [E]: "When the user is part of an inserted '
     'project, but not the master project, only the inserted project will be '
     'exported." Check both ends yourself.'),
]


# ------------------------------------------------------------------ deadline --
def time_left(now=None):
    """Return (timedelta, days, hours) remaining until retirement. Negative if past."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    delta = RETIREMENT_UTC - now
    total_hours = delta.total_seconds() / 3600.0
    return delta, int(total_hours // 24), total_hours


def cmd_deadline(args):
    delta, days, total_hours = time_left(_parse_now(args.now))
    past = delta.total_seconds() <= 0
    if args.json:
        print(json.dumps({
            "retirement": RETIREMENT_UTC.isoformat(),
            "retirement_text": RETIREMENT_TEXT,
            "seconds_left": int(delta.total_seconds()),
            "days_left": days,
            "hours_left": round(total_hours, 1),
            "past": past,
        }, indent=2))
    else:
        print("Project Online retirement : %s" % RETIREMENT_TEXT)
        print("  source : https://learn.microsoft.com/en-us/lifecycle/products/project-online")
        print("  row    : | Project Online | 3/1/2013 8:00:00 AM | 9/30/2026 8:00:00 AM |")
        if past:
            print("\n  PASSED %d days ago. The tenant data is no longer reachable." % abs(days))
        else:
            print("\n  %d days left (%.1f hours)." % (days, total_hours))
            print("  Note the time of day: it is 08:00 Pacific, not midnight local.")
    return 1 if past else 0


def _parse_now(text):
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise SystemExit("--now: use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS (UTC)")


# --------------------------------------------------------------- project list --
def project_names_from_list(path):
    """Pull Proj_Name values out of a *ProjectList.xml.

    [E] states only that each listed project carries SiteId, Proj_UID and
    Proj_Name. It does not document the element nesting, so this walks the whole
    tree and takes Proj_Name wherever it appears, as an element or an attribute.
    Returns (names, error_or_None).
    """
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return [], str(exc)
    names, seen = [], set()
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        if tag == "proj_name" and el.text and el.text.strip():
            value = el.text.strip()
            if value not in seen:
                seen.add(value)
                names.append(value)
        for attr, value in el.attrib.items():
            if attr.split("}")[-1].lower() == "proj_name" and value.strip():
                value = value.strip()
                if value not in seen:
                    seen.add(value)
                    names.append(value)
    return names, None


# ------------------------------------------------------------------- checking --
def _match(candidates, accepted, paged=False):
    """Return the first filename in `candidates` (lowercase->real map) that matches."""
    hits = []
    for low, real in candidates.items():
        stem = low[:-5] if low.endswith(".json") else low
        for name in accepted:
            if stem == name or low == name:
                hits.append(real)
                break
            if paged and PAGE_RE.sub("", stem) == name:
                hits.append(real)
                break
    return hits


def check_dir(path):
    """Check one -OutputDirectory. Returns a result dict."""
    res = {"dir": path, "missing": [], "empty": [], "unaccounted": [], "notes": [],
           "projects": [], "expected": 0, "found": 0}
    if not os.path.isdir(path):
        res["notes"].append("not a directory")
        res["missing"].append("(the whole directory)")
        res["expected"] = 1
        return res

    entries = {}
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            res["notes"].append("subdirectory ignored: %s (the export writes a flat directory)" % name)
            continue
        entries[name.lower()] = name
    remaining = dict(entries)

    def take(real):
        remaining.pop(real.lower(), None)
        res["found"] += 1
        if os.path.getsize(os.path.join(path, real)) == 0:
            return True
        return False

    # 1. the three project-list files
    names_by_list = {}
    for want in PROJECT_LIST_FILES:
        res["expected"] += 1
        real = entries.get(want.lower())
        if real is None:
            res["missing"].append(want)
            continue
        if take(real):
            res["empty"].append("%s  (a project list should never be empty)" % real)
        names, err = project_names_from_list(os.path.join(path, real))
        if err:
            res["notes"].append("%s could not be parsed: %s" % (real, err))
        elif not names:
            res["notes"].append("%s parsed but held no Proj_Name; NOT CONFIRMED whether this "
                                "means zero projects or a layout this script does not read" % real)
        names_by_list[want] = names

    # The union is used, because [E] says the three lists differ ("a user can save
    # the project but not publish"). A project in any list must have its files.
    projects, seen = [], set()
    for want in PROJECT_LIST_FILES:
        for n in names_by_list.get(want, []):
            if n not in seen:
                seen.add(n)
                projects.append(n)
    if not projects:
        # Fall back to whatever *_draft.xml is lying there, so the tool is still
        # useful when the lists are the files that went missing.
        for low, real in entries.items():
            if low.endswith("_draft.xml") and not low.endswith("projectlist.xml"):
                projects.append(real[: -len("_draft.xml")])
        if projects:
            res["notes"].append("project names were inferred from *_draft.xml because no "
                                "Proj_Name was read; a project whose export failed completely "
                                "cannot be detected this way")

    # 2. per-project files
    for proj in projects:
        prow = {"name": proj, "missing": [], "found": 0}
        low_proj = proj.lower()
        odd = re.search(r"[^a-z0-9 _.\-()]", low_proj)
        if odd:
            prow["note"] = ("name contains %r; NOT CONFIRMED how the export script maps such "
                            "names to filenames" % odd.group(0))
        for label, suffixes in PER_PROJECT:
            res["expected"] += 1
            accepted = [p + low_proj + s for p in NAME_PREFIXES for s in suffixes]
            hits = _match(remaining, accepted)
            if not hits:
                prow["missing"].append(label)
                res["missing"].append("%s : %s" % (proj, label))
                continue
            prow["found"] += 1
            for real in hits:
                if take(real):
                    res["empty"].append("%s  (%s : %s)" % (real, proj, label))
        res["projects"].append(prow)

    # 3. the 27 feature files
    for canon, accepted, paged in FEATURE_FILES:
        res["expected"] += 1
        hits = _match(remaining, accepted, paged=paged)
        if not hits:
            res["missing"].append("%s.json  (feature file)" % canon)
            continue
        empties = [r for r in hits if take(r)]
        if empties and len(empties) == len(hits):
            # [E]: "If the user has no data relating to the feature on the specific
            # PWA site, the file will contain no data." So this is not a failure.
            res["notes"].append("%s is empty - documented as expected when the user has no "
                                "data for that feature" % canon)

    for canon, accepted in OPTIONAL_FILES:
        for real in _match(remaining, accepted):
            take(real)

    res["unaccounted"] = sorted(remaining.values())
    return res


def print_result(res, verbose):
    print("\n=== %s" % res["dir"])
    for n in res["notes"]:
        print("  note        : %s" % n)
    print("  projects    : %d" % len(res["projects"]))
    print("  expected    : %d files" % res["expected"])
    print("  accounted   : %d" % res["found"])
    print("  MISSING     : %d" % len(res["missing"]))
    for m in res["missing"][: (None if verbose else 20)]:
        print("      - %s" % m)
    if not verbose and len(res["missing"]) > 20:
        print("      ... %d more (use --verbose)" % (len(res["missing"]) - 20))
    if res["empty"]:
        print("  ZERO BYTES  : %d" % len(res["empty"]))
        for e in res["empty"]:
            print("      - %s" % e)
    if res["unaccounted"]:
        print("  not accounted for : %d file(s) in the directory that the documentation "
              "does not describe" % len(res["unaccounted"]))
        if verbose:
            for u in res["unaccounted"]:
                print("      - %s" % u)


def cmd_check(args):
    results = [check_dir(d) for d in args.dirs]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        delta, days, _ = time_left(_parse_now(args.now))
        if delta.total_seconds() > 0:
            print("%d days left until %s" % (days, RETIREMENT_TEXT))
        else:
            print("PAST the retirement date (%s)" % RETIREMENT_TEXT)
        for res in results:
            print_result(res, args.verbose)
        total_missing = sum(len(r["missing"]) for r in results)
        total_empty = sum(len(r["empty"]) for r in results)
        print("\n--- %d director(y/ies): %d missing, %d zero-byte"
              % (len(results), total_missing, total_empty))
        if total_missing or total_empty:
            print("    Re-run ExportProjectUserContent.ps1 for the affected user/PWA site "
                  "while the service still exists.")
        else:
            print("    Nothing missing against the documented file list. That is not the same "
                  "as 'the contents are correct' - see `checklist` for what no file check covers.")
    bad = any(r["missing"] or r["empty"] for r in results)
    return 1 if bad else 0


def cmd_checklist(args):
    delta, days, _ = time_left(_parse_now(args.now))
    print("Project Online exit checklist - %d days left (%s)\n" % (days, RETIREMENT_TEXT))
    print("The export script produces the files this tool counts. It does NOT produce:\n")
    for i, item in enumerate(MANUAL_ITEMS, 1):
        print("  %d. %s\n" % (i, item))
    print("  [E] = https://learn.microsoft.com/en-us/projectonline/"
          "export-user-data-from-project-online")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("deadline", help="how long is left")
    d.add_argument("--json", action="store_true")
    d.add_argument("--now", help="pretend it is this UTC time (for testing)")
    d.set_defaults(func=cmd_deadline)

    c = sub.add_parser("check", help="count what an export directory is missing")
    c.add_argument("dirs", nargs="+", help="one or more -OutputDirectory paths")
    c.add_argument("--json", action="store_true")
    c.add_argument("--verbose", action="store_true")
    c.add_argument("--now", help="pretend it is this UTC time (for testing)")
    c.set_defaults(func=cmd_check)

    k = sub.add_parser("checklist", help="what the export script does not produce")
    k.add_argument("--now", help="pretend it is this UTC time (for testing)")
    k.set_defaults(func=cmd_checklist)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
