# -*- coding: utf-8 -*-
"""Replay public commits that fixed setup instructions: was each fixed line flagged before the fix?

    python replay_fixes.py                          # the commits listed in the README
    python replay_fixes.py owner/name@SHA ...       # any other public commits
    python replay_fixes.py --head owner/name ...    # the default branch today, whole repository

For every commit it reads the diff from github.com's `.patch` view, lists the repository's files
in the parent commit and in the commit from codeload's tarballs (held in memory, never unpacked
to disk; a tarball over 300 MB falls back to the anonymous tree API, one call per side), runs
setup_doc_check on both sides, and prints:

  fixed      a finding before the commit, gone after, in a document the commit rewrote
             (`*` marks one on a line the commit itself removed or changed)
  gone       a finding before the commit, gone after, in a document the commit did not touch
             (the repository was changed to match the document)
  kept       a finding before and after (same code and message)
  new        a finding only after the commit

Nothing is written to disk and nothing is sent anywhere. Neither view is counted against the
anonymous API limit of 60 calls an hour; `--head` costs one call for the default branch.
"""
import argparse
import email.header
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_doc_check as t  # noqa: E402

# (repository, commit, what the commit did) — the README's replay table. Found with GitHub's
# commit search on words like "fix README script", "wrong script name", "make target".
FIXES = [
    # the document was fixed to match the repository
    ("tiffanyfan1015/toefl_writing_assistant", "a99285eca672", "npm script renamed"),
    ("lari98/priceguard-ai", "c45d7b7ae4bb", "npm script renamed"),
    ("dmrobbi/stig-baselines", "39e1dc8e843c", "make target renamed"),
    ("mdbtq/svgify", "62e49602015d", "make targets renamed"),
    ("saufi-opi/lybrix", "0979c0c74b70", "make targets that never existed"),
    ("rippere/tribe-social", "859be66dcbda", "cd into the wrong folder"),
    ("QuantumLogicsLabs/QuantumLearningWorkspace-Chatbot", "7b45a5726b3d", "requirements file renamed"),
    ("DevPranavJad700/healthbuddy-ai-assistant", "8a0d504de665", "script renamed"),
    ("suiheilibe/STEP_mid", "7619bf8057cb", "script renamed (readme.txt)"),
    ("agent-substrate/substrate", "9774393d6075", "the other of two scripts that both exist"),
    ("redis/node-redis", "7dff63f33de3", "npm script removed"),
    ("apache/teaclave-trustzone-sdk", "bb1647d33336", "example folder moved"),
    ("sno-ai/sno-station", "bbb01afeb56a", "script missing in some workspaces"),
    ("giovanni-marchisio/kamiwaza60fps", "438cd945a0a8", "script renamed"),
    ("from-es/linkclump-plus", "c5caee5ef17e", "npm scripts renamed"),
    ("ermesjoandreas/praetrace", "57bf95a63b28", "README renamed before package.json did"),
    ("mondragon-developer/hebrew-english-spanish-helper", "f2b8f063f4da", "npm script renamed"),
    ("nabbi/route-summarization", "7f6ff21f600f", "script renamed"),
    ("eaterofpies/trimrouter", "18d62b7fcac2", "make target split, Makefile changed too"),
    ("ridhosirunsurinta/webpack-5", "298ed32b5b86", "npm script removed"),
    ("Kirillr-Sibirski/strikeline", "8f9dab8b812d", "make target added"),
    ("apache/incubator-seata-go", "81701e3386f0", "go install path"),
    ("apache/kafka", "373f4ea5ed17", "gradle task names"),
    ("apache/ranger", "74d1ff8b910e", "chmod arguments"),
    ("apache/datafusion", "3767e88ec449", "cargo arguments"),
    ("apache/arrow-java", "6e73f7f563b2", "wording"),
    ("vercel/turborepo", "db8f89a512b0", "a script's body, not its name"),
    # the repository was fixed to match the document
    ("pruhnav/sponsorscan", "e8d38f8f62b0", "requirements files added"),
    ("wcalhoun516/digital-dad", "db7f7eac2338", "make targets added"),
    ("iamvisheshsrivastava/AirKube", "678db5cefdd4", "a dependency added"),
    ("dcouch440/gh-agents", "d2d274fd766d", "Makefile recipes fixed"),
    ("emersongideon/arsenal-eras", "b208dd2167f3", "requirements file added with the step"),
    ("darkspaz-v1/racing-ml-lab", "26a040105844", "requirements file added with the step"),
]
UA = {"User-Agent": "setup-doc-check-replay", "Accept": "application/vnd.github+json"}
CALLS = [0]


def get(url):
    if "api.github.com" in url:
        CALLS[0] += 1
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def api(path):
    return json.loads(get("https://api.github.com" + path))


KEEP = re.compile(r"(\.md|\.markdown|\.mk|\.toml|\.cfg|\.json|\.gradle|\.kts|\.xml|\.txt|"
                  r"(^|/)(GNUmakefile|[Mm]akefile|Gemfile|setup\.py|go\.mod|\.gitignore|\.nvmrc|"
                  r"\.node-version|\.tool-versions|\.python-version|\.java-version|\.sdkmanrc|"
                  r"\.ruby-version|rust-toolchain))$")
MAX_TAR = 300 * 1024 * 1024


def tarball(repo, sha):
    """List the files at a commit from codeload's tarball (not counted against the API limit),
    keeping in memory the small text files the checker may read. Returns (paths, texts) or None."""
    url = "https://codeload.github.com/%s/tar.gz/%s" % (repo, sha)
    paths, texts, seen = [], {}, [0]

    class Capped:
        def __init__(self, r):
            self.r = r

        def read(self, n=-1):
            b = self.r.read(n)
            seen[0] += len(b)
            if seen[0] > MAX_TAR:
                raise OverflowError("tarball larger than %d MB" % (MAX_TAR >> 20))
            return b

    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
            with tarfile.open(fileobj=Capped(r), mode="r|gz") as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    name = m.name.split("/", 1)[1] if "/" in m.name else ""
                    if not name:
                        continue
                    paths.append(name)
                    if m.size <= 2 * 1024 * 1024 and KEEP.search(name):
                        f = tf.extractfile(m)
                        texts[name] = f.read().decode("utf-8", "replace") if f else None
    except (OverflowError, urllib.error.URLError, tarfile.TarError):
        return None
    return paths, texts


def tree(repo, sha):
    d = api("/repos/%s/git/trees/%s?recursive=1" % (repo, sha))
    paths = [e["path"] for e in d.get("tree", []) if e.get("type") == "blob"]
    return paths, bool(d.get("truncated"))


def reader(repo, sha):
    def read(path):
        try:
            return get("https://raw.githubusercontent.com/%s/%s/%s"
                       % (repo, sha, urllib.request.quote(path))).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
    return read


def changed_lines(patch):
    """Old-file line numbers that a unified diff removes (or replaces)."""
    out, old = set(), 0
    for line in (patch or "").splitlines():
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
        if m:
            old = int(m.group(1))
            continue
        if line.startswith("-") and not line.startswith("---"):
            out.add(old)
            old += 1
        elif line.startswith("+") and not line.startswith("+++"):
            continue
        else:
            old += 1
    return out


def side(repo, sha, docs):
    got = tarball(repo, sha)
    if got is not None:
        paths, texts = got
        raw_read = reader(repo, sha)
        view = t.TreeRepo(paths, lambda p: texts[p] if p in texts else raw_read(p), name=repo.split("/")[1])
        truncated = False
    else:
        paths, truncated = tree(repo, sha)
        view = t.TreeRepo(paths, reader(repo, sha), name=repo.split("/")[1])
    use = [d for d in docs if d in view.files] if docs else None
    findings, stats = t.check_repo(view, use)
    return findings, stats, truncated


def commit_patch(repo, sha):
    """(full sha, subject, {new path: (old path, patch text)}) from github.com's .patch view,
    which is not counted against the API limit."""
    text = get("https://github.com/%s/commit/%s.patch" % (repo, sha)).decode("utf-8", "replace")
    m = re.match(r"From ([0-9a-f]{40}) ", text)
    full = m.group(1) if m else sha
    s = re.search(r"^Subject: (?:\[PATCH[^\]]*\] )?(.*(?:\n [^\n]*)*)", text, re.M)
    subject = re.sub(r"\n ", " ", s.group(1)).strip() if s else ""
    try:
        subject = str(email.header.make_header(email.header.decode_header(subject)))
    except (ValueError, LookupError):
        pass
    files = {}
    for part in re.split(r"^(?=diff --git )", text, flags=re.M)[1:]:
        h = re.match(r"diff --git a/(.+?) b/(.+?)\n", part)
        if not h:
            continue
        old, new = h.group(1), h.group(2)
        r_from = re.search(r"^rename from (.+)$", part, re.M)
        if r_from:
            old = r_from.group(1)
        files[new] = (old, part)
    return full, subject, files


def replay(repo, sha):
    full, subject, files = commit_patch(repo, sha)
    md = {n: v for n, v in files.items() if re.search(r"\.(md|markdown)$", n, re.I)}
    olds = {v[0]: n for n, v in md.items()}
    before, sb, tb = side(repo, full + "~1", sorted(olds) or None)
    after, sa, ta = side(repo, full, sorted(md) or None)
    touched = {old: changed_lines(md[new][1]) for old, new in olds.items()}
    key = lambda f: (f[2], re.sub(r"\s+", " ", f[3]))
    after_keys = {key(f) for f in after}
    before_keys = {key(f) for f in before}
    rows = []
    for f in before:
        if key(f) in after_keys:
            rows.append(("kept", f))
        elif touched.get(f[0]):
            rows.append(("fixed", f))      # gone, and the commit rewrote that document
        else:
            rows.append(("gone", f))       # gone, and the document was not touched
    for f in after:
        if key(f) not in before_keys:
            rows.append(("new", f))
    return subject, rows, (sb, sa), (tb or ta), touched


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("commits", nargs="*", help="owner/name@SHA")
    ap.add_argument("--head", action="append", default=[], help="owner/name: scan the default branch")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    todo = [c.split("@", 1) for c in a.commits] or ([] if a.head else [(r, s) for r, s, _ in FIXES])
    total = {"fixed": 0, "kept": 0, "gone": 0, "new": 0}
    try:
        for repo in a.head:
            info = api("/repos/%s" % repo)
            findings, stats, truncated = side(repo, info["default_branch"], None)
            print("## %s @ %s  (%d docs, %d commands, %d checked)%s" % (
                repo, info["default_branch"], stats["docs"], stats["commands"], stats["checked"],
                "  TREE TRUNCATED" if truncated else ""))
            for doc, line, code, msg in findings:
                print("    %s:%d: %s %s %s" % (doc, line, t.LEVEL[code], code, msg))
        for repo, sha in todo:
            subject, rows, stats, truncated, touched = replay(repo, sha)
            counts = {k: sum(1 for r in rows if r[0] == k) for k in total}
            for k in total:
                total[k] += counts[k]
            print("%s@%s  fixed %d  kept %d  gone %d  new %d  %s%s" % (
                repo, sha[:10], counts["fixed"], counts["kept"], counts["gone"], counts["new"],
                subject[:80], "  TREE TRUNCATED" if truncated else ""))
            for kind, (doc, line, code, msg) in rows:
                star = "*" if kind == "fixed" and line in touched.get(doc, ()) else " "
                print("    %-5s%s %s:%d: %s %s" % (kind, star, doc, line, code, msg))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            print("stopped: GitHub refused (%d %s) after %d API calls. The anonymous limit is 60 an "
                  "hour; run again later." % (e.code, e.reason, CALLS[0]))
            return 2
        raise
    if todo:
        print("total: fixed %(fixed)d  kept %(kept)d  gone %(gone)d  new %(new)d" % total)
    print("%d API calls" % CALLS[0], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
