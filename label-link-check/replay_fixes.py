# -*- coding: utf-8 -*-
"""Replay public commits that fixed a label link or an issue template's labels, before and after.

    python replay_fixes.py replay_commits.tsv [--limit N]

Each line of the file is `OWNER/REPO<TAB>SHA<TAB>PARENT<TAB>path[,path...]`. For each commit this
fetches every listed file as it was in the parent and in the commit (raw.githubusercontent.com),
reads the repository's labels today and its `.github/ISSUE_TEMPLATE/` at each of the two commits
(REST API), runs label_link_check on both sides and prints one verdict:

  caught     an error before the commit that is gone after it
  still      the same errors before and after (the commit fixed something else)
  new-after  an error after the commit that was not there before
  missed     no error on either side

Set GITHUB_TOKEN for more than a handful of commits (the API allows 60 unauthenticated requests an
hour). The labels are today's, not the commit's: a label deleted since then makes an old fix look
like a miss, and one created since makes an old error look fixed. This is the one part of the
folder that reads from GitHub.
"""
import argparse
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import label_link_check as L  # noqa: E402


def raw(repo, ref, path):
    url = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, ref, urllib.parse.quote(path))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "label-link-check"}),
                                    timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return None


def templates_at(src, repo, ref):
    st, data = src._get("/repos/%s/contents/%s?ref=%s" % (repo, L.TEMPLATE_DIR, ref))
    if st == 200 and isinstance(data, list):
        return [x.get("name", "") for x in data if x.get("type") == "file"]
    return [] if st == 404 else None


def errors(findings):
    return {(f.code, f.repo.lower(), f.subject) for f in findings if f.severity == "error"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("commits")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    src = L.ApiSource()
    rows = [l.rstrip("\n").split("\t") for l in Path(a.commits).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    if a.limit:
        rows = rows[:a.limit]
    tally = Counter()
    for repo, sha, parent, paths in rows:
        labels = src.labels(repo)
        if labels is None:
            print("unreadable  %s %s (labels could not be read)" % (repo, sha[:10]))
            tally["unreadable"] += 1
            continue
        before, after = [], []
        tb, ta = templates_at(src, repo, parent), templates_at(src, repo, sha)
        for p in paths.split(","):
            tpl = p.lower().startswith(L.TEMPLATE_DIR.lower() + "/") and \
                not p.rsplit("/", 1)[-1].lower().startswith("config.")
            b, t = raw(repo, parent, p), raw(repo, sha, p)
            if b is not None:
                L.scan_text(p, b, repo, L.Resolver(repo, labels, tb, src), before, tpl)
            if t is not None:
                L.scan_text(p, t, repo, L.Resolver(repo, labels, ta, src), after, tpl)
        kb, ka = errors(before), errors(after)
        v = "caught" if kb - ka else "still" if kb and kb == ka else "new-after" if ka - kb else "missed"
        tally[v] += 1
        shown = sorted(kb - ka or ka - kb or kb)[:3]
        print("%-10s %s %s  %s" % (v, repo, sha[:10], "; ".join("%s %s" % (c, s) for c, _, s in shown)))
    print("--", ", ".join("%s %d" % kv for kv in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
