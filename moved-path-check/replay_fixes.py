# -*- coding: utf-8 -*-
"""Replay public commits in which somebody fixed a stale path in a doc by hand, before and after.

    python replay_fixes.py replay_commits.tsv [--cache DIR] [--limit N] [--checker FILE]

Each line of the file is `OWNER/REPO<TAB>SHA<TAB>PARENT<TAB>doc[,doc...]<TAB>path[,path...]`: the
docs the commit changed, and the repository paths it removed from them. For each commit this makes
a partial clone (`--filter=blob:none`: history and trees, and only the blobs of the docs it reads),
runs the checker on those docs at the parent and at the commit (`--rev`), and prints one verdict:

  not-stale  every path the commit removed still existed at the parent: the file was renamed in
             the same commit and the doc updated with it (nothing was stale; not counted)
  typo       the missing paths never existed in the history: a typo, which this checker leaves
             to link checkers by design (not counted)
  caught     every stale path (missing at the parent, present earlier in the history) was an
             error before the commit, and none is after it
  partly     some of the stale paths were flagged before, some were not
  still      a flagged stale path is still flagged after the commit
  missed     none of the stale paths was flagged before the commit
  unread     the clone or the checker failed

and the counts at the end. With `--rev`, `.gitignore` is not consulted (it lives in the checkout),
so a path that later became ignored can be flagged here and not in a checkout. The clones go to
`--cache` (kept, so a second run is fast) or to a temporary folder that is removed at the end.
This is the one file here that reads from the network (`git clone` from github.com).
"""
import argparse
import collections
import importlib.util
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_checker(path):
    spec = importlib.util.spec_from_file_location("moved_path_check_under_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clone(repo, dest):
    if (dest / ".git").exists():
        return True
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        # the second -c is kept in the clone's config: the blobs it fetches later need long paths too
        r = subprocess.run(["git", "-c", "core.longpaths=true", "clone", "-c", "core.longpaths=true", "-q",
                            "--filter=blob:none", "--no-checkout",
                            "https://github.com/%s.git" % repo, str(dest)], capture_output=True, text=True,
                           env=env, timeout=300)
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        return False
    return r.returncode == 0


def norm(p):
    p = p.strip().rstrip("/")
    while p.startswith("./"):
        p = p[2:]
    return p


def candidates(p, docs):
    """Where a path written in one of `docs` can point: from the root, or from each doc's folder."""
    out = [posixpath.normpath(p)]
    for d in docs:
        q = posixpath.normpath(posixpath.join(posixpath.dirname(d), p))
        if not q.startswith(".."):
            out.append(q)
    return [c for c in out if c and not c.startswith("..")]


def flagged(M, root, rev, docs):
    """Every path flagged as an error, as written in the doc and as resolved in the repository."""
    ck = M.Checker(str(root), rev=rev)
    out = set()
    for f in ck.run(docs):
        if f.level == "error":
            out.add(("", norm(f.path)))
            out.add(("", norm(M.LINE_SUFFIX_RE.sub("", f.text))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv")
    ap.add_argument("--cache")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--checker", default=str(HERE / "moved_path_check.py"))
    a = ap.parse_args(argv)
    M = load_checker(a.checker)
    rows = [l.rstrip("\n").split("\t") for l in open(a.tsv, encoding="utf-8") if l.strip() and not l.startswith("#")]
    if a.limit:
        rows = rows[:a.limit]
    tmp = None
    cache = Path(a.cache) if a.cache else Path(tempfile.mkdtemp(prefix="mpc-replay-"))
    if not a.cache:
        tmp = cache
    counts = collections.Counter()
    try:
        for repo, sha, parent, docs, removed in rows:
            docs = docs.split(",")
            removed = set(norm(p) for p in removed.split(",") if p)
            dest = cache / repo.replace("/", "__")
            if not clone(repo, dest):
                verdict, detail = "unread", "clone failed"
            else:
                try:
                    before = flagged(M, dest, parent, docs)
                    after = flagged(M, dest, sha, docs)
                except Exception as e:  # a commit gone from the history, a checker crash
                    before = after = None
                    verdict, detail = "unread", repr(e)[:120]
                if before is not None:
                    # which removed paths were already missing at the parent, and had existed before
                    tree = M.Tree(str(dest), parent)
                    hist = M.History(str(dest), rev=parent)
                    stale, typo = set(), set()
                    for p in removed:
                        cands = candidates(p, docs)
                        if any(tree.exists(c) for c in cands):
                            continue  # still there: renamed in this same commit, not a stale doc
                        if any(c in hist.gone or hist.under(c) for c in cands):
                            stale.add(p)
                        else:
                            typo.add(p)
                    hit = set(p for (_, p) in before) & stale
                    left = set(p for (_, p) in after) & hit
                    if not stale:
                        verdict = "typo" if typo else "not-stale"
                    elif not hit:
                        verdict = "missed"
                    elif left:
                        verdict = "still"
                    elif hit == stale:
                        verdict = "caught"
                    else:
                        verdict = "partly"
                    detail = "flagged %d of %d stale (%d removed, %d never existed)" % (
                        len(hit), len(stale), len(removed), len(typo))
                    if verdict in ("missed", "partly"):
                        detail += " missed: " + ", ".join(sorted(stale - hit)[:5])
            counts[verdict] += 1
            print("%s\t%s\t%s\t%s" % (verdict, repo, sha[:12], detail), flush=True)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "  ".join("%s %d" % kv for kv in sorted(counts.items())), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
