# -*- coding: utf-8 -*-
"""moved-path-check -- find the file paths in a repository's docs that git itself says were
moved or deleted, and say where they went.

    python moved_path_check.py [PATH ...] [--since REF] [--json] [--all-docs]

A README that says "run `scripts/bootstrap.sh`" keeps saying it after `scripts/` becomes
`tools/`. Link checkers only read links, and a path in backticks or in a shell block is not a
link. Grepping for paths that do not exist finds hundreds -- example paths, the reader's own
project, build output -- so nobody does it. The repository's history separates the two: a path
that never existed here is somebody else's, and a path that existed until a commit removed it is
a stale sentence. This reads the docs, looks every path up in `git log`, and reports only the
second kind -- with the commit, the date and, when git knows, the new path.

What it reads (Markdown, MDX, reStructuredText, AsciiDoc, and plain-text READMEs)
  * relative links and images: `[x](../src/a.py)`, `![](img/a.png)`, `[id]: path`, `src="..."`
  * links to this repository on GitHub on the branch checked out: `github.com/OWNER/REPO/blob/main/x`
  * inline code that is a path with a slash: `src/a.py`, `docs/` (``src/a.py`` in rst)
  * words with a slash in sh / bash / console / powershell blocks: `python scripts/build.py`
  * rst / AsciiDoc directives: `.. include:: x`, `.. image:: x`, `include::x[]`, `image::x[]`

Findings (`error` makes the exit status 1; `warning` does not)
  MOVED        error    the path was renamed; git's history says it is now at <new path>
  MOVED_DIR    error    the directory was renamed; most of its files are now under <new dir>
  DELETED      error    the path was deleted by <commit> on <date>, and git saw no rename
                        (when exactly one file of that name exists now, it is named as a hint)
  DELETED_DIR  error    every file under the directory was deleted (the last by <commit>)
  HISTORICAL   warning  one of the above, but the sentence itself says renamed / removed /
                        formerly / deprecated -- it is probably describing the change
  SHORTENED    warning  the new path ends with the old one: the doc may name it from that folder
  ELSEWHERE    warning  deleted here, but a file with the same path ending exists at <path>
  SPLIT_DIR    warning  the directory's files went to several places

Not reported: a path that exists; a path that never existed in this repository's history (an
example, the reader's project, another repository); a path that is `.gitignore`d today (it
became a local or generated file); a bare name in backticks (`.env`: usually the reader's);
`.claude/`-style folders that do not exist here; code blocks in other languages and output;
and records -- changelogs, release notes, migration guides, blog posts, RFCs, ADRs, work items,
versioned docs, docs with a date in their path or marked superseded -- whose job is to name the
paths of their day. `--all-docs` reads the records too.

`--since REF` only counts paths that disappeared after REF: "what did we move since v2.0 that
the docs still name?" Exit status: 0 = no errors, 1 = errors, 2 = nothing could be judged (not a
git repository, no docs, or a shallow clone with missing paths it cannot look up -- run
`git fetch --unshallow`; in GitHub Actions, `fetch-depth: 0`). Standard library only; it runs
`git` read-only and writes nothing.
"""
import argparse
import bisect
import collections
import json
import os
import posixpath
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

DOC_EXT = {".md", ".markdown", ".mdx", ".rst", ".adoc", ".asciidoc", ".txt"}
# plain-text files are read only when they are prose (README.txt, INSTALL.txt, docs/*.txt)
TXT_NAMES = re.compile(r"^(readme|install|installing|contributing|hacking|building|development|"
                       r"developing|getting[-_]?started|usage|faq)\b", re.I)
TXT_SKIP = re.compile(r"^(requirements|constraints|cmakelists|license|licence|copying|notice|"
                      r"robots|authors|dependencies|version|manifest)\b", re.I)
# files whose job is to name old paths
HISTORY_FILE = re.compile(r"^(change[-_ ]?log|changes|history|news|release[-_ ]?notes?|releases?|"
                          r"upgrad(e|ing)|migrat\w*|breaking[-_ ]?changes|deprecat\w*|whats[-_ ]?new|"
                          r"authors|contributors|credits|thanks|acknowledg\w*|evidence|handoff|"
                          r"retro(spective)?|post[-_]?mortem|work[-_]?log|dev[-_]?log|journal)([-_. ]|$)",
                          re.I)
HISTORY_DIR = {"changelog", "changelogs", "changes", "release-notes", "release_notes", "releasenotes",
               "releases", "release", "news", "blog", "blogs", "_posts", "posts", "history",
               "upgrade", "upgrading", "upgrade-guides", "migration", "migrations", "migrating",
               "migration-guides", "changesets", ".changeset", "rfc", "rfcs", "adr", "adrs",
               "decisions", "proposals", "design-docs", "archive", "archived", "archives",
               "old", "legacy", "deprecated", "versioned_docs", "versioned_sidebars", "versions",
               "whatsnew", "whats-new", "retrospectives", "meetings", "meeting-notes", "minutes",
               "notes", "postmortems", "incidents", "announcements",
               # work records: a plan or evidence for one piece of work, done when it is done
               "plans", "work-items", "workitems", "work_items", "work-packages", "work_packages",
               "slices", "sprints", "iterations", "handoff", "handoffs", "journal", "journals",
               "worklog", "worklogs", "devlog", "devlogs", "logs", "reports", "retros"}
VERSION_DIR = re.compile(r"^(v|version-|release-)?\d+(\.\d+)*(\.x|\.\*)?$", re.I)
# old_files/, legacy-docs/, docs_archive/, README_OLD.md
OLD_PART = re.compile(r"(^|[-_. ])(old|legacy|deprecated|archived?|obsolete|outdated|backup|bak)([-_. ]|$)",
                      re.I)
# a date in the doc's path: plans, meeting notes, reports and posts are records of their day
DATED_RE = re.compile(r"(?<!\d)(19|20)\d\d([-_.]?)(0[1-9]|1[0-2])(\2(0[1-9]|[12]\d|3[01]))?(?!\d)")
# a doc that says at the top that it is no longer current
SUPERSEDED_RE = re.compile(r"\b(superseded|obsolete|out of date|outdated|no longer (maintained|current|"
                           r"accurate|valid|up to date)|historical (record|document|note)|this (document|"
                           r"page|file) is (deprecated|archived))\b|^\s*(status|state)\s*[:=]\s*\**\s*"
                           r"(deprecated|archived|superseded|rejected|withdrawn|implemented|done|completed)",
                           re.I | re.M)
# folders of fragments that other pages include: their relative links resolve from the includer
FRAGMENT_DIR = {"macros", "_includes", "includes", "partials", "_partials", "snippets", "_snippets",
                "fragments", "_fragments", "reuse", "_reuse", "shared", "_shared", "common"}
# languages of fenced blocks whose words are commands run in the repository
SHELL_LANGS = {"sh", "bash", "shell", "zsh", "fish", "console", "shell-session", "shellsession",
               "terminal", "powershell", "ps", "ps1", "pwsh", "cmd", "bat", "batch", "dos", "ksh",
               "csh", "tcsh", "nu", "nushell"}
SKIP_DIR = {".git", "node_modules", "vendor", "third_party", "third-party", "thirdparty",
            "bower_components", ".venv", "venv", "site-packages", "__pycache__", ".tox", "external",
            "extern", "deps", "submodules"}
MAX_BYTES = 2_000_000
PROBE = "/.moved-path-check-probe"

# a sentence that is itself about the change
HISTORICAL_RE = re.compile(
    r"\b(renam\w*|moved?|moving|formerly|previously|used to|no longer|deprecat\w*|removed?|removing|"
    r"deleted?|deleting|replac\w*|legacy|obsolete|old|older|migrat\w*|instead of|superseded|"
    r"retired|dropped|prior to|before v?\d|until v?\d|since v?\d|in v?\d+\.\d+)\b", re.I)

BRANCHES = {"main", "master", "develop", "dev", "trunk", "head", "default", "stable", "next",
            "canary"}

PATH_CHAR = r"[\w.@+~\-/]"
TOKEN_RE = re.compile(r"^(?:\./|\.\./)*[\w.@+~\-]+(?:/[\w.@+~\-]*)*$", re.UNICODE)
EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
LINE_SUFFIX_RE = re.compile(r"(?::\d+(?:[:-]\d+)?|#L\d+(?:C\d+)?(?:-L\d+(?:C\d+)?)?)$")
INLINE_MD_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
MD_LINK_RE = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]*>|[^\s)]+(?:\([^\s)]*\)[^\s)]*)*)"
                        r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
MD_REFDEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
HTML_ATTR_RE = re.compile(r"\b(?:src|href|srcset)\s*=\s*[\"']([^\"']+)[\"']", re.I)
RST_DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+(include|literalinclude|image|figure|csv-table|"
                              r"code-block|program-output|mdinclude)::\s*(\S+)", re.I)
RST_LINK_RE = re.compile(r"`[^`<]*<([^>`]+)>`__?")
ADOC_RE = re.compile(r"\b(include|image|link|xref)::?([^\s\[\]]+)\[")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
GH_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)/"
                       r"(?:blob|tree|raw)/([^/\s]+)/([^\s)\"'<>\]`]+)", re.I)
GH_RAW_RE = re.compile(r"https?://raw\.githubusercontent\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)/"
                       r"([^/\s]+)/([^\s)\"'<>\]`]+)", re.I)
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# system and home paths, and things that only look like paths
NOT_REPO_RE = re.compile(r"^(/|~|\$|%|[A-Za-z]:[\\/]|\\\\)")


class GitError(Exception):
    pass


def git(root, args, input_text=None, check=True, env=None):
    cmd = ["git", "-c", "core.quotepath=off", "-C", str(root)] + args
    try:
        r = subprocess.run(cmd, input=input_text, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
    except FileNotFoundError:
        raise GitError("git is not installed")
    if check and r.returncode != 0:
        raise GitError((r.stderr or "").strip() or "git %s failed" % args[0])
    return r


def unquote_git(p):
    """git quotes paths with unusual bytes in C style even with core.quotepath=off."""
    if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
        b = p[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        try:
            return b.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return b
    return p


Event = collections.namedtuple("Event", "kind new sha date")  # kind: "moved" | "deleted"


class History:
    """What disappeared from the tree, newest disappearance first.

    Built from `git log --raw --no-renames`, which needs no file contents (so it works on a
    `--filter=blob:none` clone). A deletion and an addition in the same commit are paired as a
    rename when they have the same blob, or the same file name, or when the commit deletes one
    file and adds one file with the same extension. A deletion left unpaired is asked of git's
    own rename detection (`git show -M`) before it is reported as deleted.
    """

    def __init__(self, root, since=None, rev="HEAD"):
        self.root = root
        self.gone = {}        # path -> Event (the newest disappearance)
        self.ever = set()     # every path seen added or deleted in the history read
        rng = rev if not since else "%s..%s" % (since, rev)
        r = git(root, ["log", "--no-renames", "--raw", "--no-abbrev", "--diff-filter=AD",
                       "--format=%x01%H %cs", rng])
        sha = date = None
        dels, adds = {}, {}

        def flush():
            if sha is not None:
                self._commit(sha, date, dels, adds)

        for line in r.stdout.splitlines():
            if line.startswith("\x01"):
                flush()
                sha, date = line[1:].split(" ", 1)
                dels, adds = {}, {}
                continue
            if not line.startswith(":"):
                continue
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) < 5:
                continue
            status = parts[4][0]
            path = unquote_git(path)
            if status == "D":
                dels[path] = parts[2]
            elif status == "A":
                adds[path] = parts[3]
        flush()
        self._paths = sorted(self.gone)
        self._git_renames = {}

    def _commit(self, sha, date, dels, adds):
        self.ever.update(dels)
        self.ever.update(adds)
        if not dels:
            return
        pairs = {}
        by_oid = collections.defaultdict(list)
        by_name = collections.defaultdict(list)
        for p, oid in adds.items():
            by_oid[oid].append(p)
            by_name[posixpath.basename(p)].append(p)
        used = set()
        for p, oid in dels.items():
            cand = [a for a in by_oid.get(oid, []) if a not in used]
            if len(cand) > 1:  # the same blob added in several places: take the nearest name
                same = [a for a in cand if posixpath.basename(a) == posixpath.basename(p)]
                cand = same or cand
            if cand:
                pairs[p] = cand[0]
                used.add(cand[0])
        for p in dels:
            if p in pairs:
                continue
            cand = [a for a in by_name.get(posixpath.basename(p), []) if a not in used]
            if len(cand) == 1:
                pairs[p] = cand[0]
                used.add(cand[0])
        # same folder, same name, other extension: a.ts -> a.js
        by_stem = collections.defaultdict(list)
        for a in adds:
            if a not in used:
                by_stem[posixpath.splitext(a)[0]].append(a)
        for p in dels:
            if p in pairs:
                continue
            cand = [a for a in by_stem.get(posixpath.splitext(p)[0], []) if a not in used]
            if len(cand) == 1:
                pairs[p] = cand[0]
                used.add(cand[0])
        # one file out, one file in, same folder and extension: a renamed file
        rest_d = [p for p in dels if p not in pairs]
        if len(rest_d) == 1:
            d0, ext = posixpath.dirname(rest_d[0]), posixpath.splitext(rest_d[0])[1]
            rest_a = [a for a in adds if a not in used and posixpath.splitext(a)[1] == ext
                      and posixpath.dirname(a) == d0]
            if ext and len(rest_a) == 1:
                pairs[rest_d[0]] = rest_a[0]
        for p in dels:
            if p in self.gone:
                continue  # an older disappearance of a path that came back and went again
            if p in pairs:
                self.gone[p] = Event("moved", pairs[p], sha, date)
            else:
                self.gone[p] = Event("deleted", None, sha, date)

    def git_rename(self, sha, path):
        """Ask git's content-based rename detection about one commit (fetches blobs if needed)."""
        if sha not in self._git_renames:
            m = {}
            r = git(self.root, ["show", "-M40%", "-l2000", "--name-status", "--format=", sha],
                    check=False)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) == 3 and parts[0].startswith("R"):
                        m[unquote_git(parts[1])] = unquote_git(parts[2])
            self._git_renames[sha] = m
        return self._git_renames[sha].get(path)

    def under(self, prefix):
        """Every disappeared path under directory `prefix/`."""
        pre = prefix.rstrip("/") + "/"
        i = bisect.bisect_left(self._paths, pre)
        out = []
        while i < len(self._paths) and self._paths[i].startswith(pre):
            out.append(self._paths[i])
            i += 1
        return out


class Tree:
    def __init__(self, root, rev=None):
        self.root = root
        if rev:
            r = git(root, ["ls-tree", "-r", "--name-only", "--full-tree", rev])
        else:
            r = git(root, ["ls-files", "--cached"])
        self.files = set(unquote_git(p) for p in r.stdout.splitlines() if p)
        self.dirs = set()
        for f in self.files:
            d = posixpath.dirname(f)
            while d and d not in self.dirs:
                self.dirs.add(d)
                d = posixpath.dirname(d)
        self.on_disk = rev is None
        self._by_tail = None

    def exists(self, p):
        p = p.rstrip("/")
        if p == "" or p in self.files or p in self.dirs:
            return True
        if self.on_disk:
            # an untracked file counts (generated in CI); an empty folder left behind by a move does not
            return os.path.isfile(os.path.join(str(self.root), p))
        return False

    def tail_match(self, p):
        """A tracked file whose path ends with `/p` (same path ending, other place)."""
        if self._by_tail is None:
            self._by_tail = collections.defaultdict(list)
            for f in self.files:
                self._by_tail[posixpath.basename(f)].append(f)
        for f in self._by_tail.get(posixpath.basename(p), []):
            if f.endswith("/" + p):
                return f
        return None

    def same_name(self, p):
        """The one tracked file with the same file name as `p`, if there is exactly one."""
        self.tail_match(p)  # builds the index
        found = self._by_tail.get(posixpath.basename(p), [])
        return found[0] if len(found) == 1 else None


def is_doc(path, all_docs=False):
    parts = path.split("/")
    name = parts[-1]
    ext = posixpath.splitext(name)[1].lower()
    if ext not in DOC_EXT:
        return False
    for d in parts[:-1]:
        dl = d.lower()
        if dl in SKIP_DIR:
            return False
        if not all_docs and (dl in HISTORY_DIR or VERSION_DIR.match(d) or OLD_PART.search(d)):
            return False
    if not all_docs and (HISTORY_FILE.match(name) or DATED_RE.search(path) or
                         OLD_PART.search(posixpath.splitext(name)[0])):
        return False
    if ext == ".txt":
        if TXT_SKIP.match(name):
            return False
        in_docs = any(d.lower() in ("doc", "docs", "documentation") for d in parts[:-1])
        if not (TXT_NAMES.match(name) or in_docs):
            return False
    return True


def clean_token(tok):
    """Strip what surrounds a path in prose; return None if it does not look like one."""
    t = tok.strip().strip("\"'")
    t = t.rstrip(".,;:!?)]}>") if not t.endswith("/") else t
    t = LINE_SUFFIX_RE.sub("", t)
    if len(t) < 3 or len(t) > 240 or "://" in t or "//" in t:
        return None
    if NOT_REPO_RE.match(t) or t.startswith("-") or t.startswith("@") and t.count("/") == 1:
        return None
    if not TOKEN_RE.match(t):
        return None
    body = t
    while body.startswith("./") or body.startswith("../"):
        body = body[2:] if body.startswith("./") else body[3:]
    if not body or body in (".", ".."):
        return None
    has_slash = "/" in body.rstrip("/")
    if not has_slash and not body.endswith("/") and not EXT_RE.search(body):
        return None
    if re.match(r"^[\d.]+$", body.replace("/", "")):
        return None  # 1.2.3, 10/20
    if not re.search(r"[A-Za-z]", body):
        return None
    return t


def resolve_link(target, doc_dir):
    """A relative link target -> repository path, or None."""
    t = target.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1]
    if not t or t.startswith("#") or SCHEME_RE.match(t) or t.startswith("//"):
        return None
    if "{{" in t or "{%" in t or "${" in t or "<" in t:
        return None
    t = t.split("#", 1)[0].split("?", 1)[0]
    if not t:
        return None
    t = urllib.parse.unquote(t)
    if t.startswith("/"):
        p = posixpath.normpath(t.lstrip("/"))
    else:
        p = posixpath.normpath(posixpath.join(doc_dir, t))
    if p.startswith("..") or p == ".":
        return None
    return p


Mention = collections.namedtuple("Mention", "line kind text candidates")


def mentions(text, doc_path, repo_slug=None, branches=BRANCHES):
    """Every path mention in one doc: (line, kind, text as written, candidate repo paths)."""
    doc_dir = posixpath.dirname(doc_path)
    ext = posixpath.splitext(doc_path)[1].lower()
    rst = ext == ".rst"
    adoc = ext in (".adoc", ".asciidoc")
    out = []
    in_fence = None
    fence_lang = ""
    in_comment = False
    ancestors = []
    d = doc_dir
    while True:
        ancestors.append(d)
        if not d:
            break
        d = posixpath.dirname(d)

    def code_candidates(tok):
        body = tok
        if body.startswith("./") or body.startswith("../"):
            p = posixpath.normpath(posixpath.join(doc_dir, body))
            return [p] if not p.startswith("..") else []
        body = body.rstrip("/") if len(body) > 1 else body
        # nearest first: the doc's own folder, then each folder above it, then the root
        return [posixpath.normpath(posixpath.join(a, body)) for a in ancestors]

    for n, line in enumerate(text.splitlines(), 1):
        m = FENCE_RE.match(line)
        if in_fence is not None:
            s = line.strip()
            if len(s) >= len(in_fence) and s == in_fence[0] * len(s):
                in_fence = None
                continue
            if fence_lang not in SHELL_LANGS:
                continue  # code, output, trees: their paths are relative to something we cannot know
            if fence_lang in ("console", "shell-session", "shellsession", "terminal"):
                pm = re.match(r"^\s*(?:\(\S+\)\s*)?(?:[\w.@-]*[$%#>]|PS[^>]*>)\s+(.*)$", line)
                if not pm:
                    continue  # output, not a command
                line = pm.group(1)
            elif line.lstrip().startswith("#"):
                continue  # a comment
            for raw in re.split(r"[\s=\"'`(),;|&<>]+", line):
                tok = clean_token(raw)
                if tok and "/" in tok.rstrip("/"):
                    out.append(Mention(n, "fence", tok, code_candidates(tok)))
            continue
        if m:
            in_fence = m.group(1)
            info = line.strip()[len(in_fence):].strip().lstrip("{.").lower()
            fence_lang = re.split(r"[\s,}{]+", info)[0] if info else ""
            continue
        # HTML comments in Markdown are not shown to the reader
        if not rst and not adoc:
            if in_comment:
                if "-->" in line:
                    in_comment = False
                    line = line.split("-->", 1)[1]
                else:
                    continue
            line = re.sub(r"<!--.*?-->", "", line)
            if "<!--" in line:
                line = line.split("<!--", 1)[0]
                in_comment = True
        seen_spans = []
        # links
        link_targets = []
        if not rst:
            for lm in MD_LINK_RE.finditer(line):
                link_targets.append(lm.group(1))
                seen_spans.append(lm.span())
            rm = MD_REFDEF_RE.match(line)
            if rm:
                link_targets.append(rm.group(1))
        for hm in HTML_ATTR_RE.finditer(line):
            for part in hm.group(1).split(","):
                link_targets.append(part.strip().split(" ")[0])
        if rst:
            dm = RST_DIRECTIVE_RE.match(line)
            if dm and dm.group(1).lower() not in ("code-block", "program-output"):
                link_targets.append(dm.group(2))
            for lm in RST_LINK_RE.finditer(line):
                link_targets.append(lm.group(1))
        if adoc:
            for am in ADOC_RE.finditer(line):
                if am.group(1).lower() != "xref":
                    link_targets.append(am.group(2))
        for t in link_targets:
            if SCHEME_RE.match(t.strip("<>")):
                continue
            p = resolve_link(t, doc_dir)
            if p:
                out.append(Mention(n, "link", t.strip("<>"), [p]))
        # links to this repository on GitHub, on a branch (a commit or tag link is permanent)
        if repo_slug:
            for rx in (GH_URL_RE, GH_RAW_RE):
                for gm in rx.finditer(line):
                    owner, name, ref, path = gm.groups()
                    if ("%s/%s" % (owner, name)).lower() != repo_slug.lower():
                        continue
                    if ref.lower() not in branches:
                        continue
                    path = urllib.parse.unquote(path.split("#", 1)[0].split("?", 1)[0])
                    path = path.rstrip(".,;:!")
                    p = posixpath.normpath(path)
                    if p and not p.startswith(".."):
                        out.append(Mention(n, "url", gm.group(0), [p]))
        # inline code
        if rst:
            spans = re.finditer(r"``([^`]+)``", line)
            codes = [s.group(1) for s in spans]
            codes += [s.group(1) for s in re.finditer(r":file:`([^`]+)`", line)]
        else:
            stripped = line
            for a, b in reversed(seen_spans):
                stripped = stripped[:a] + " " * (b - a) + stripped[b:]
            codes = [s.group(2).strip() for s in INLINE_MD_RE.finditer(stripped)]
        for c in codes:
            if " " in c.strip():
                continue
            tok = clean_token(c)
            # a bare name (`.env`, `requirements.txt`) is usually the reader's file, not ours
            if tok and "/" in tok:
                out.append(Mention(n, "code", tok, code_candidates(tok)))
    return out


Finding = collections.namedtuple("Finding", "doc line level code text path target sha date kind")


class Checker:
    def __init__(self, root, since=None, rev=None, repo_slug=None, all_docs=False):
        self.root = Path(root)
        self.since = since
        self.rev = rev
        self.all_docs = all_docs
        self.tree = Tree(self.root, rev)
        self.hist = History(self.root, since, rev or "HEAD")
        shallow = git(self.root, ["rev-parse", "--is-shallow-repository"], check=False)
        self.shallow = shallow.stdout.strip() == "true"
        self.repo_slug = repo_slug if repo_slug is not None else self._slug()
        # a link to github.com/OWNER/REPO/blob/<branch>/path is judged only for the branch we read:
        # `tree/dev/...` in vuejs/vue still works, on a dev branch nobody has touched since 2022
        cur = git(self.root, ["rev-parse", "--abbrev-ref", "HEAD"], check=False).stdout.strip()
        self.branches = {"head", cur.lower()} if cur and cur != "HEAD" else set(BRANCHES)
        self.unjudged = 0
        self.docs_read = 0
        self._ignored = None

    def _slug(self):
        r = git(self.root, ["remote", "get-url", "origin"], check=False)
        m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", r.stdout.strip())
        return "%s/%s" % m.groups() if m else None

    def ignored(self, paths):
        paths = sorted(set(paths))
        if not paths:
            return set()
        if self.rev:
            return set()
        # NUL-separated: in text mode on Windows a "\n" reaches git as "\r\n", and "x\r" matches nothing
        # the repository's .gitignore files only: not the user's global excludes, which differ per machine
        nowhere = os.path.join(str(self.root), ".git", "moved-path-check-no-such-file")
        r = git(self.root, ["-c", "core.excludesFile=" + nowhere, "check-ignore", "--no-index", "--stdin", "-z"],
                input_text="\0".join(paths) + "\0", check=False,
                env=dict(os.environ, XDG_CONFIG_HOME=nowhere))
        return set(p for p in r.stdout.split("\0") if p)

    def read_doc(self, path):
        if self.rev:
            r = git(self.root, ["show", "%s:%s" % (self.rev, path)], check=False)
            return r.stdout if r.returncode == 0 else None
        f = self.root / path
        if os.name == "nt" and len(str(f)) > 240:
            f = Path("\\\\?\\" + os.path.abspath(str(f)))  # Windows' 260-character limit
        try:
            if f.stat().st_size > MAX_BYTES:
                return None
            return f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def judge(self, path):
        """None when fine / unknown; else (code, target, event)."""
        if self.tree.exists(path):
            return None
        ev = self.hist.gone.get(path)
        if ev is not None:
            return self._chase(path, ev)
        # a directory that no longer exists
        under = self.hist.under(path)
        if under:
            return self._dir(path, under)
        if path not in self.hist.ever:
            return ("NEVER", None, None)
        return None

    def _chase(self, path, ev):
        first = ev
        cur = path
        for _ in range(64):
            if ev.kind == "deleted":
                alt = self.hist.git_rename(ev.sha, cur)
                if alt:
                    ev = Event("moved", alt, ev.sha, ev.date)
                else:
                    return ("DELETED", None, ev)
            nxt = ev.new
            if self.tree.exists(nxt):
                return ("MOVED", nxt, first)
            ev2 = self.hist.gone.get(nxt)
            if ev2 is None:
                return ("DELETED", None, ev)
            cur, ev = nxt, ev2
        return ("DELETED", None, ev)

    def _dir(self, prefix, under):
        pre = prefix.rstrip("/") + "/"
        news = collections.Counter()
        moved = deleted = 0
        last = None
        for p in under:
            res = self._chase(p, self.hist.gone[p])
            ev = res[2]
            if last is None or (ev and ev.date > last.date):
                last = ev
            if res[0] == "MOVED":
                rest = p[len(pre):]
                tgt = res[1]
                if tgt.endswith("/" + rest):
                    news[tgt[:-len(rest) - 1]] += 1
                else:
                    news[posixpath.dirname(tgt)] += 1
                moved += 1
            else:
                deleted += 1
        if moved == 0:
            return ("DELETED_DIR", None, last)
        top, cnt = news.most_common(1)[0]
        if cnt * 2 >= len(under):
            return ("MOVED_DIR", top, last)
        return ("SPLIT_DIR", "%d places (most to %s)" % (len(news), top), last)

    def docs(self, paths=None):
        files = sorted(self.tree.files)
        if paths:
            sel = []
            for p in paths:
                p = p.strip("/").replace("\\", "/")
                if p in ("", "."):
                    return [f for f in files if is_doc(f, self.all_docs)]
                sel += [f for f in files if f == p or f.startswith(p + "/")]
            # a file named on the command line is read even if it is a changelog
            named = set(q.strip("/").replace("\\", "/") for q in paths)
            return sorted(set(f for f in sel if f in named or is_doc(f, self.all_docs)))
        return [f for f in files if is_doc(f, self.all_docs)]

    def run(self, paths=None):
        findings = []
        pending = []
        for doc in self.docs(paths):
            text = self.read_doc(doc)
            if text is None:
                continue
            self.docs_read += 1
            if not self.all_docs and SUPERSEDED_RE.search("\n".join(text.splitlines()[:25])):
                continue  # the doc says at the top that it is not current
            fragment = any(d.lower() in FRAGMENT_DIR for d in doc.split("/")[:-1])
            for m in mentions(text, doc, self.repo_slug, self.branches):
                if not m.candidates:
                    continue
                if fragment and m.kind == "link":
                    continue  # included elsewhere; the link resolves from the page that includes it
                top = m.candidates[-1].split("/", 1)[0]
                if m.kind in ("code", "fence") and top.startswith(".") and top not in self.tree.dirs:
                    # `.claude/settings.json`, `.cursor/mcp.json`: with no such folder here today,
                    # these are the reader's config files, not ours
                    continue
                if any(self.tree.exists(c) for c in m.candidates):
                    continue
                verdicts = []
                for c in m.candidates:
                    v = self.judge(c)
                    if v and v[0] != "NEVER":
                        verdicts.append((c, v))
                        break
                if not verdicts:
                    if self.shallow or self.since:
                        if m.kind in ("link", "url"):
                            self.unjudged += 1
                    continue
                c, (code, target, ev) = verdicts[0]
                pending.append((doc, m, c, code, target, ev, text.splitlines()[m.line - 1]))
        # a path that is .gitignored today became a local or generated file (a build output, a
        # clone of another repository): the doc is right to name it. A folder is asked about
        # through a file inside it, so that `evals/` matches -- asking git about `evals/` itself
        # lets an empty line of a CRLF .gitignore match every folder (seen in the wild)
        asked = []
        for (_, _, c, code, _, _, _) in pending:
            asked += [c, c + PROBE] if code.endswith("_DIR") else [c]
        ign = self.ignored(asked)
        for doc, m, c, code, target, ev, line in pending:
            if c in ign or c + PROBE in ign:
                continue
            level = "error"
            if code == "SPLIT_DIR":
                level = "warning"
            if code == "DELETED" and m.kind != "link":
                tm = self.tree.tail_match(c)
                if tm:
                    code, target, level = "ELSEWHERE", tm, "warning"
            if code == "DELETED" and not target:
                # git saw no rename, but one file of that name exists now: say where, as a hint
                # (Bindu's tests/unit/test_applications.py left in one commit and came back in
                # tests/unit/server/ in another)
                same = self.tree.same_name(c)
                if same:
                    target = same
            body = re.sub(r"^(\./|\.\./)+", "", m.text).rstrip("/")
            if code in ("MOVED", "MOVED_DIR") and m.kind != "link" and target and \
                    target.rstrip("/").endswith("/" + body):
                # `packages/core/x.ts` after everything went under `plugin/`: the doc may be
                # naming it from that folder, as people do once they work inside it
                code, level = "SHORTENED:" + code, "warning"
            # the words of the sentence, not of the path (`old/` is a folder, not a remark)
            if level == "error" and HISTORICAL_RE.search(line.replace(m.text, " ")):
                code, level = "HISTORICAL:" + code, "warning"
            target_show = target
            if target and m.kind == "link" and code.split(":")[-1] in ("MOVED", "MOVED_DIR"):
                # a relative link is fixed with a relative path
                target_show = posixpath.relpath(target, posixpath.dirname(doc) or ".")
            findings.append(Finding(doc, m.line, level, code, m.text, c, target_show,
                                    ev.sha[:12] if ev else None, ev.date if ev else None, m.kind))
        return findings


def message(f):
    code = f.code.split(":")[-1]
    when = " by %s on %s" % (f.sha, f.date) if f.sha else ""
    if code == "MOVED":
        s = "`%s` was moved%s; it is now `%s`" % (f.text, when, f.target)
    elif code == "MOVED_DIR":
        s = "directory `%s` was moved; its files are now under `%s/`" % (f.text, f.target)
    elif code == "DELETED":
        s = "`%s` was deleted%s" % (f.text, when)
        if f.target:
            s += "; the only file of that name now is `%s`" % f.target
    elif code == "DELETED_DIR":
        s = "every file under `%s` was deleted (the last%s)" % (f.text, when)
    elif code == "SPLIT_DIR":
        s = "the files under `%s` went to %s" % (f.text, f.target)
    elif code == "ELSEWHERE":
        s = "`%s` was deleted%s; a file with the same path ending is at `%s`" % (f.text, when, f.target)
    else:
        s = f.text
    if f.code.startswith("HISTORICAL:"):
        s += " (the sentence itself talks about the change)"
    if f.code.startswith("SHORTENED:"):
        s += " (the new path ends with the old one: the doc may be naming it from inside that folder)"
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", help="files or folders inside one git repository (default: all docs)")
    ap.add_argument("--since", help="only paths that disappeared after this commit, tag or branch")
    ap.add_argument("--rev", help="read the docs and tree at this commit instead of the checkout")
    ap.add_argument("--repo", help="OWNER/NAME for github.com links (default: the origin remote)")
    ap.add_argument("--all-docs", action="store_true",
                    help="also read changelogs, release notes, blog posts, RFCs and versioned docs")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    start = a.paths[0] if a.paths else "."
    start_dir = start if os.path.isdir(start) else (os.path.dirname(start) or ".")
    if not os.path.isdir(start_dir):
        start_dir = "."  # with --rev, the doc named need not be checked out
    try:
        top = git(start_dir, ["rev-parse", "--show-toplevel"]).stdout.strip()
    except GitError as e:
        print("moved-path-check: not a git repository (%s)" % e, file=sys.stderr)
        return 2
    rel = []
    for p in a.paths:
        ap_ = os.path.relpath(os.path.abspath(p), top).replace("\\", "/")
        rel.append("" if ap_ == "." else ap_)
    try:
        ck = Checker(top, since=a.since, rev=a.rev, repo_slug=a.repo, all_docs=a.all_docs)
        found = ck.run(rel or None)
    except GitError as e:
        print("moved-path-check: %s" % e, file=sys.stderr)
        return 2
    errors = [f for f in found if f.level == "error"]
    if a.json:
        print(json.dumps({"docs": ck.docs_read, "unjudged": ck.unjudged, "shallow": ck.shallow,
                          "findings": [dict(f._asdict(), message=message(f)) for f in found]},
                         ensure_ascii=False, indent=1))
    else:
        for f in found:
            print("%s:%d: %s %s %s" % (f.doc, f.line, f.level, f.code.split(":")[0], message(f)))
        print("moved-path-check: %d docs, %d errors, %d warnings%s" % (
            ck.docs_read, len(errors), len(found) - len(errors),
            ", %d links not judged (%s)" % (ck.unjudged, "shallow clone" if ck.shallow else "--since")
            if ck.unjudged else ""), file=sys.stderr)
    if ck.docs_read == 0:
        print("moved-path-check: no docs were read", file=sys.stderr)
        return 2
    if ck.shallow and ck.unjudged:
        print("moved-path-check: the clone is shallow, so %d missing links could not be looked up; "
              "run `git fetch --unshallow` (Actions: fetch-depth: 0)" % ck.unjudged, file=sys.stderr)
        return 2
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
