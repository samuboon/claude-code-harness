# -*- coding: utf-8 -*-
"""Rebuild jira_scopes.json from Atlassian's published OpenAPI definitions.

    python build_table.py            # fetch both definitions, write jira_scopes.json
    python build_table.py --diff     # fetch, compare with the shipped table, write nothing

Only the derived table is written (method + path -> scopes, deprecated flag), one
operation per line so a rebuild shows up in a diff as exactly the lines that changed.
The definitions themselves are read into memory and never saved.

How a scope is classified: a scope with three colon-separated parts
(`read:issue:jira`, `read:sprint:jira-software`) is granular; one with two
(`read:jira-work`, `manage:jira-configuration`) is classic. The Jira platform definition
also tags each list with `state: Current` (classic) or `state: Beta` (granular) in
`x-atlassian-oauth2-scopes`. Where a tag exists it wins, and every scope whose shape
disagrees with its tag is listed under "anomalies" (the definition has a few). The Jira
Software definition carries only granular scopes, in `security[].OAuth2`.

Standard library only.
"""
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "jira_scopes.json"
SPECS = {
    "platform": "https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json",
    "software": "https://developer.atlassian.com/cloud/jira/software/swagger.v3.json",
}
METHODS = ("get", "post", "put", "delete", "patch")
ANOMALIES = []


def is_granular(scope):
    return scope.count(":") >= 2


def fold(path):
    """/rest/api/3/issue/{issueIdOrKey} -> /rest/api/3/issue/{}"""
    out, depth = [], 0
    for c in path:
        if c == "{":
            depth += 1
            if depth == 1:
                out.append("{}")
            continue
        if c == "}":
            depth -= 1
            continue
        if depth == 0:
            out.append(c)
    return "".join(out)


def scopes_of(op, where):
    """Return (classic, granular) for one operation."""
    classic, granular = set(), set()
    tagged = op.get("x-atlassian-oauth2-scopes") or []
    for entry in tagged:
        state = entry.get("state")
        for s in entry.get("scopes") or []:
            if state == "Current":
                classic.add(s)
            elif state == "Beta":
                granular.add(s)
            else:
                raise SystemExit("unknown state %r at %s" % (state, where))
    for s in sorted(classic):
        if is_granular(s):
            ANOMALIES.append("%s: %s is tagged Current (classic) but looks granular" % (where, s))
    for s in sorted(granular):
        if not is_granular(s):
            ANOMALIES.append("%s: %s is tagged Beta (granular) but looks classic" % (where, s))
    if not tagged:
        for sec in op.get("security") or []:
            for s in sec.get("OAuth2") or []:
                (granular if is_granular(s) else classic).add(s)
    return sorted(classic), sorted(granular)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "forge-scope-check"})
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read().decode("utf-8"))


def build():
    table = {}
    source = {}
    for tag, url in SPECS.items():
        spec = fetch(url)
        source[tag] = {"url": url, "version": (spec.get("info") or {}).get("version")}
        for path, ops in sorted(spec["paths"].items()):
            for meth in METHODS:
                op = ops.get(meth)
                if not op:
                    continue
                key = meth.upper() + " " + fold(path)
                classic, granular = scopes_of(op, key)
                row = {"path": path, "classic": classic, "granular": granular,
                       "deprecated": bool(op.get("deprecated")),
                       "stated": bool(op.get("security") or op.get("x-atlassian-oauth2-scopes"))}
                if key in table and table[key] != row:
                    raise SystemExit("two operations fold to the same key: %s (%s / %s)"
                                     % (key, table[key]["path"], path))
                table[key] = row
    meta = {"built": date.today().isoformat(), "source": source, "anomalies": ANOMALIES}
    return {"meta": meta, "operations": table}


def dump(data):
    lines = ["{", '"meta": ' + json.dumps(data["meta"], ensure_ascii=False, sort_keys=True) + ",",
             '"operations": {']
    ops = data["operations"]
    keys = sorted(ops)
    for i, k in enumerate(keys):
        lines.append(json.dumps(k) + ": " + json.dumps(ops[k], sort_keys=True, separators=(",", ":"))
                     + ("," if i < len(keys) - 1 else ""))
    lines += ["}", "}"]
    return "\n".join(lines) + "\n"


def main(argv):
    new = build()
    ops = new["operations"]
    print("operations: %d (classic-only %d, granular-only %d, both %d, none stated %d, deprecated %d)" % (
        len(ops),
        sum(1 for r in ops.values() if r["classic"] and not r["granular"]),
        sum(1 for r in ops.values() if r["granular"] and not r["classic"]),
        sum(1 for r in ops.values() if r["classic"] and r["granular"]),
        sum(1 for r in ops.values() if not r["classic"] and not r["granular"]),
        sum(1 for r in ops.values() if r["deprecated"])))
    for a in new["meta"]["anomalies"]:
        print("anomaly:", a)
    if "--diff" in argv:
        old = json.loads(OUT.read_text(encoding="utf-8"))["operations"]
        changed = 0
        for key in sorted(set(old) | set(ops)):
            if old.get(key) != ops.get(key):
                changed += 1
                print("changed:", key)
        print("%d operations differ from the shipped table" % changed)
        return 1 if changed else 0
    OUT.write_bytes(dump(new).encode("utf-8"))
    print("wrote", OUT.name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
