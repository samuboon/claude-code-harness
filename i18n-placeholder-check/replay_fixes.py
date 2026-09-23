# -*- coding: utf-8 -*-
"""Replay a project's own translation fixes: would the checker have flagged each changed message before the fix?

    python replay_fixes.py                                  # the 15 Jenkins commits in the README
    python replay_fixes.py --repo owner/name SHA [SHA ...]  # any other public repository
    python replay_fixes.py --default-mode                   # without --always-messageformat

For every commit it reads, through anonymous GitHub GETs, each changed .properties file and its
base file as they were in the parent commit and in the commit itself, runs the checker on both,
and prints, for every key whose value changed: the codes before, the codes after, both values.
Nothing is sent anywhere; the copies go to a temporary directory that is removed at the end.

The anonymous API allows 60 requests an hour; one commit costs one request (file contents come
from raw.githubusercontent.com, which is not counted).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n_placeholder_check as t  # noqa: E402

JENKINS = [
    # fixes of apostrophes that MessageFormat ate (commit subjects in the README)
    "e3a0be90cf", "70da17ed10", "754e553dd8", "13c2edfc4e", "3f061dfa6d", "c66de073fb", "8a8fbbaad6",
    "655601ebb3", "527c5935fd", "db7a19810d", "f73e15516f", "03750c92ee",
    # changes of style, where the value before was already correct
    "591c7407d6", "ca91d2063a", "b15ecb7533",
]
UA = {"User-Agent": "i18n-placeholder-check-replay", "Accept": "application/vnd.github+json"}
REAL = {c for c, lv in t.LEVEL.items() if lv != "note"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def raw(repo, ref, path):
    try:
        return get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, ref, path))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def base_of(path):
    d, n = os.path.split(path)
    for stem, _loc in t.locale_splits(n):
        return (d + "/" if d else "") + stem + ".properties"
    return None


def replay(repo, sha, work, always):
    c = json.loads(get("https://api.github.com/repos/%s/commits/%s" % (repo, sha)))
    full, parent = c["sha"], c["parents"][0]["sha"]
    changed_files = [f["filename"] for f in c["files"] if f["filename"].endswith(".properties")]
    wanted = set(changed_files) | {b for b in map(base_of, changed_files) if b}
    # one short folder per source folder: bundles stay together and Windows paths stay short
    folders = {d: str(i) for i, d in enumerate(sorted({os.path.dirname(f) for f in wanted}))}

    def local(root, f):
        return root / folders[os.path.dirname(f)] / os.path.basename(f)

    back = {}
    sides = {}
    for side, ref in (("before", parent), ("after", full)):
        root = Path(work) / full[:10] / side[0]
        for f in sorted(wanted):
            data = raw(repo, ref, f)
            if data is not None:
                dst = local(root, f)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                back[str(dst)] = f
        findings = t.run([root], always_mf=always, key_as_base=True)[0] if root.exists() else []
        values, flags = {}, {}
        for f in changed_files:
            p = local(root, f)
            if p.exists():
                entries = t.parse_properties(t.read_text(p)[0])[0]
                values[f] = {k: v for k, (_l, v) in entries.items()}
        for path, _line, code, key, _detail in findings:
            if code in REAL and str(path) in back:
                flags.setdefault((back[str(path)], key), set()).add(code)
        sides[side] = (values, flags)
    rows = []
    for f in changed_files:
        a = sides["before"][0].get(f, {})
        b = sides["after"][0].get(f, {})
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                rows.append((f, k, sorted(sides["before"][1].get((f, k), ())),
                             sorted(sides["after"][1].get((f, k), ())), a.get(k), b.get(k)))
    return c["commit"]["author"]["date"][:10], c["commit"]["message"].splitlines()[0], rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("shas", nargs="*")
    ap.add_argument("--repo", default="jenkinsci/jenkins")
    ap.add_argument("--default-mode", action="store_true", help="do not pass --always-messageformat")
    ap.add_argument("-q", "--quiet", action="store_true", help="one line per commit")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    shas = a.shas or (JENKINS if a.repo == "jenkinsci/jenkins" else [])
    if not shas:
        print("give at least one commit")
        return 2
    work = tempfile.mkdtemp(prefix="i18n-replay-")
    total = [0, 0, 0]
    try:
        for sha in shas:
            try:
                date, subject, rows = replay(a.repo, sha, work, not a.default_mode)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    print("stopped at %s: GitHub refused (%d %s). The anonymous limit is 60 requests an "
                          "hour; run again later." % (sha, e.code, e.reason))
                    return 2
                raise
            before = sum(1 for r in rows if r[2])
            after = sum(1 for r in rows if r[3])
            total[0] += len(rows)
            total[1] += before
            total[2] += after
            print("%s %s  changed %d  flagged before %d  still flagged after %d  %s"
                  % (sha[:10], date, len(rows), before, after, subject[:70]))
            if not a.quiet:
                for f, k, cb, ca, vb, va in rows:
                    print("    %s :: %s  before %s  after %s" % (f.rsplit("/", 1)[-1], k, ",".join(cb) or "-",
                                                                 ",".join(ca) or "-"))
                    print("        before: %s\n        after:  %s" % (t._short(vb or ""), t._short(va or "")))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("total: %d changed keys, %d flagged before, %d still flagged after" % tuple(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
