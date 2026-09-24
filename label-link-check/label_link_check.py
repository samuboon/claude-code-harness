# -*- coding: utf-8 -*-
"""label-link-check -- find the GitHub issue links and issue templates that point at a label
the repository does not have.

    python label_link_check.py [PATH ...] [--repo OWNER/NAME] [--labels FILE] [--offline] [--json]

A link to `https://github.com/OWNER/REPO/labels/good-first-issue` answers HTTP 200 whether or not
that label exists -- the page is an issue list, and an empty issue list is a perfectly good page.
So is `issues?q=label:good first issue` (unquoted: GitHub reads the label `good` and two words of
text) and `issues?q=lable:bug`. Link checkers pass all three. An issue form with
`labels: ["Bug"]` in a repository whose label is called `type: bug` files every report without it
("If a label does not already exist in the repository, it will not be automatically added to the
issue" -- GitHub's issue-forms syntax page), so the triage query that looks for it comes back
short, forever, without an error anywhere.

This reads the links and templates, reads the repository's real label list, and names every
label that is not on it -- with the closest one that is.

What it reads
  * every `github.com/OWNER/REPO/labels/NAME`, `.../issues?q=...`, `.../pulls?q=...`,
    `.../issues?labels=a,b`, `.../issues/new?labels=...&template=...` and
    `github.com/issues?q=...repo:OWNER/REPO...` link in the text files under PATH
  * the `labels:` of every issue template under `.github/ISSUE_TEMPLATE/`
    (issue forms `.yml` / `.yaml`, and the front matter of Markdown templates)

Findings (`error` makes the exit status 1; `warning` does not)
  LABEL        error    the label is not in the repository (case is ignored, as GitHub does)
  UNQUOTED     error    `label:good first issue` -- only `label:"good first issue"` is one label
  QUOTED_PATH  error    `/labels/%22good%20first%20issue%22` -- quotes in a path are part of the name
  TEMPLATE     error    `issues/new?template=x.md` names a file not in .github/ISSUE_TEMPLATE/
  NO_REPO      error    the repository in the link does not exist (or is not readable)
  IS_VALUE     error    `is:opened`, `state:all` -- a value the qualifier does not take (0 results)
  CASE         warning  the label exists, but spelled with different case
  NEG_LABEL    warning  `-label:x` for a label that does not exist excludes nothing
  OR_LABEL     warning  `label:a,b` where only one of them exists -- the link still shows the other
  QUALIFIER    warning  `lable:bug` -- not a qualifier GitHub knows; searched as text
  PLUS_PATH    warning  `/labels/good+first+issue` -- `+` in a path is a plus sign, not a space
  UNCHECKED    warning  a label list could not be read, so the links into it were not checked

Labels come from `--labels FILE` (a JSON list of names or of objects with "name", as
`gh label list --json name` or the REST API prints them, or one name per line), or, when absent,
from the REST API (`GITHUB_TOKEN` / `GH_TOKEN` are used if set). Links into other repositories are
checked against those repositories' labels, fetched the same way, unless `--offline`.

Exit status: 0 = no errors, 1 = errors, 2 = nothing was checked (no files, or no label list for
the repository itself -- a check that read nothing must not print a pass).
Standard library only.
"""
import argparse
import difflib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TEXT_EXT = {".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc", ".asciidoc", ".html", ".htm",
            ".yml", ".yaml", ".json", ".toml", ".org", ".tex", ".jsx", ".tsx", ".vue", ".svelte", ""}
SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build",
             "target", ".tox", "site-packages", "third_party", "bower_components"}
MAX_BYTES = 2_000_000

# `[` ends a URL: AsciiDoc writes links as url[text] (openshift/origin's CONTRIBUTING.adoc)
URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[^\s<>\"'`\[\]\)\}|\\]+", re.I)
MD_TARGET_RE = re.compile(r"\]\((https?://(?:www\.)?github\.com/[^\s)]+)(?:\s+\"[^\"]*\")?\)", re.I)
OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
NAME = r"[A-Za-z0-9._-]{1,100}"
PATH_RE = re.compile(r"^/(%s)/(%s)(/.*)?$" % (OWNER, NAME))
# GitHub's own top-level paths: github.com/issues, /search, /pulls are not OWNER/REPO
RESERVED_OWNERS = {"issues", "pulls", "search", "orgs", "settings", "notifications", "marketplace",
                   "topics", "collections", "trending", "features", "sponsors", "about", "login",
                   "join", "explore", "apps", "users", "enterprise", "pricing", "site", "security",
                   "codespaces", "discussions", "new", "organizations", "account", "contact",
                   "customer-stories", "readme", "team", "events", "stars", "watching", "dashboard"}

# qualifiers the issue / pull request search accepts (docs.github.com, "Searching issues and pull
# requests", and "Filtering and searching issues and pull requests", read 2026-09-24)
KNOWN_QUALIFIERS = {
    "is", "state", "type", "in", "user", "org", "repo", "author", "assignee", "mentions", "team",
    "commenter", "involves", "linked", "label", "milestone", "project", "status", "head", "base",
    "language", "comments", "interactions", "reactions", "draft", "review", "reviewed-by",
    "review-requested", "user-review-requested", "team-review-requested", "created", "updated",
    "closed", "merged", "archived", "no", "sort", "reason", "parent-issue", "sub-issue",
    "has", "field", "blocked-by", "blocking", "sha", "app", "author-app", "title", "body",
}
IS_VALUES = {"open", "closed", "issue", "pr", "pull-request", "merged", "unmerged", "draft",
             "locked", "unlocked", "public", "private", "archived", "queued", "blocked", "blocking",
             "discussion", "answered", "unanswered"}
STATE_VALUES = {"open", "closed"}
TEMPLATE_DIR = ".github/ISSUE_TEMPLATE"
MAX_LABEL_PAGES = 100  # 10,000 labels; elastic/kibana has more than 1,000


class Finding:
    __slots__ = ("path", "line", "severity", "code", "repo", "subject", "message", "suggest")

    def __init__(self, path, line, severity, code, repo, subject, message, suggest=""):
        self.path, self.line, self.severity, self.code = path, line, severity, code
        self.repo, self.subject, self.message, self.suggest = repo, subject, message, suggest

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __str__(self):
        s = "%s:%d: %s %s %s: %s" % (self.path, self.line, self.severity, self.code, self.repo,
                                      self.message)
        if self.suggest:
            s += " (did you mean %s?)" % self.suggest
        return s


# --------------------------------------------------------------------------- labels

def norm_key(name):
    """A key for "the same label, spelled differently": case, spaces, dashes, underscores,
    colons, slashes and emoji do not count."""
    return re.sub(r"[\W_]+", "", name.lower(), flags=re.UNICODE)


class LabelSet:
    def __init__(self, names):
        self.names = list(dict.fromkeys(n for n in names if n))
        self.lower = {}
        for n in self.names:
            self.lower.setdefault(n.lower(), n)
        self.keys = {}
        for n in self.names:
            self.keys.setdefault(norm_key(n), []).append(n)

    def has(self, name):
        return name.lower() in self.lower

    def exact(self, name):
        return name in self.names

    def suggest(self, name):
        k = norm_key(name)
        if k and k in self.keys:
            return self.keys[k][0]
        # plural / singular ("bugs" for "bug")
        for cand in (k + "s", k[:-1] if k.endswith("s") else None):
            if cand and cand in self.keys:
                return self.keys[cand][0]
        m = difflib.get_close_matches(name.lower(), list(self.lower), n=1, cutoff=0.82)
        if m:
            return self.lower[m[0]]
        # the same word under a prefix the repository added later ("sanitizer" -> "from: sanitizer")
        if len(k) >= 4:
            tails = [n for n in self.names if norm_key(re.split(r"[:/]", n)[-1]) == k]
            if len(tails) == 1:
                return tails[0]
        return ""


def parse_label_file(text):
    text = text.strip()
    if not text:
        return []
    if text[0] in "[{":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("labels", [])
        out = []
        for x in data:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict) and isinstance(x.get("name"), str):
                out.append(x["name"])
        return out
    return [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]


class ApiSource:
    """Labels and template file names from the REST API. None = could not read."""

    def __init__(self, offline=False):
        self.offline = offline
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        self._labels, self._templates, self._exists = {}, {}, {}

    def _get(self, path):
        req = urllib.request.Request("https://api.github.com" + path)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "label-link-check")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, OSError, ValueError):
            return 0, None

    def labels(self, repo):
        key = repo.lower()
        if key in self._labels:
            return self._labels[key]
        if self.offline:
            self._labels[key] = None
            return None
        names, page = [], 1
        while True:
            if page > MAX_LABEL_PAGES:
                # a partial list would turn every label on the unread pages into a false error
                self._labels[key] = None
                return None
            st, data = self._get("/repos/%s/labels?per_page=100&page=%d" % (repo, page))
            if st == 404 and page == 1:
                self._exists[key] = False
                self._labels[key] = None
                return None
            if st != 200 or not isinstance(data, list):
                self._labels[key] = None
                return None
            names += [x.get("name", "") for x in data]
            if len(data) < 100:
                break
            page += 1
        self._exists[key] = True
        self._labels[key] = names
        return names

    def exists(self, repo):
        """True / False / None (unknown). Set by labels()."""
        return self._exists.get(repo.lower())

    def templates(self, repo):
        key = repo.lower()
        if key in self._templates:
            return self._templates[key]
        if self.offline:
            self._templates[key] = None
            return None
        st, data = self._get("/repos/%s/contents/%s" % (repo, TEMPLATE_DIR))
        if st == 404:
            self._templates[key] = []
        elif st == 200 and isinstance(data, list):
            self._templates[key] = [x.get("name", "") for x in data if x.get("type") == "file"]
        else:
            self._templates[key] = None
        return self._templates[key]

    def org_templates(self, owner):
        """Templates in OWNER/.github (the account-wide defaults). [] if there are none."""
        key = "org:" + owner.lower()
        if key in self._templates:
            return self._templates[key]
        if self.offline:
            self._templates[key] = None
            return None
        out = []
        for path in (TEMPLATE_DIR, "ISSUE_TEMPLATE"):
            st, data = self._get("/repos/%s/.github/contents/%s" % (owner, path))
            if st == 200 and isinstance(data, list):
                out = [x.get("name", "") for x in data if x.get("type") == "file"]
                break
            if st not in (404, 200):
                out = None
                break
        self._templates[key] = out
        return out


class Resolver:
    """Answers "what labels / templates does REPO have" for the repository being checked (from
    the local tree and --labels) and for any other repository (from the source)."""

    def __init__(self, repo, own_labels, own_templates, source):
        self.repo = (repo or "").lower()
        self.own_labels = own_labels
        self.own_templates = own_templates
        self.source = source
        self._sets = {}

    def is_own(self, repo):
        return bool(self.repo) and repo.lower() == self.repo

    def label_set(self, repo):
        key = repo.lower()
        if key not in self._sets:
            names = self.own_labels if self.is_own(repo) and self.own_labels is not None else None
            if names is None and self.source is not None:
                names = self.source.labels(repo)
            self._sets[key] = LabelSet(names) if names is not None else None
        return self._sets[key]

    def templates(self, repo):
        if self.is_own(repo) and self.own_templates is not None:
            names = self.own_templates
        else:
            names = self.source.templates(repo) if self.source is not None else None
        if names == [] and self.source is not None and hasattr(self.source, "org_templates"):
            # a repository with no template folder of its own uses its owner's .github repository
            names = self.source.org_templates(repo.split("/")[0])
        return names

    def missing_repo(self, repo):
        if self.is_own(repo) or self.source is None:
            return False
        return self.source.exists(repo) is False


# --------------------------------------------------------------------------- search queries

def tokenize(q):
    """Split a search query the way GitHub does: whitespace separates, double quotes group.
    Returns (token, unquoted_value_follows) pairs as plain strings with quotes kept."""
    toks, cur, inq = [], "", False
    for ch in q:
        if ch == '"':
            inq = not inq
            cur += ch
        elif ch.isspace() and not inq:
            if cur:
                toks.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        toks.append(cur)
    return toks


def split_values(v):
    """`bug,"good first issue"` -> ["bug", "good first issue"] (comma = OR)."""
    out, cur, inq, quoted = [], "", False, []
    was_quoted = False
    for ch in v:
        if ch == '"':
            inq = not inq
            was_quoted = True
        elif ch == "," and not inq:
            out.append(cur)
            quoted.append(was_quoted)
            cur, was_quoted = "", False
        else:
            cur += ch
    out.append(cur)
    quoted.append(was_quoted)
    return [(x, qd) for x, qd in zip(out, quoted) if x != "" or qd]


def strip_parens(tok):
    """`(label:bug` / `label:bug)` -> `label:bug` (grouping in the new issue search). A `)` that
    closes a `(` inside the token (`label:bug(minor)`) is kept."""
    while tok.startswith("("):
        tok = tok[1:]
    while tok.endswith(")") and tok.count(")") > tok.count("("):
        tok = tok[:-1]
    return tok


QUAL_RE = re.compile(r"^(-?)([A-Za-z][A-Za-z-]*):(.*)$", re.S)


def check_query(q, default_repo, emit, res):
    """Check one search query string. `emit(severity, code, repo, subject, message, suggest)`."""
    toks = [strip_parens(t) for t in tokenize(q)]
    repos = []
    for t in toks:
        m = QUAL_RE.match(t)
        if m and m.group(2).lower() == "repo" and not m.group(1):
            r = m.group(3).strip('"')
            if re.fullmatch(r"%s/%s" % (OWNER, NAME), r):
                repos.append(r)
    target = repos[0] if len(repos) == 1 else (default_repo if not repos else None)
    for i, t in enumerate(toks):
        m = QUAL_RE.match(t)
        if not m:
            continue
        neg, qual, val = m.group(1), m.group(2).lower(), m.group(3)
        if qual in ("http", "https"):
            continue
        if qual not in KNOWN_QUALIFIERS:
            emit("warning", "QUALIFIER", target or "-", t,
                 "`%s:` is not a search qualifier; GitHub searches `%s` as text" % (qual, t), "")
            continue
        if qual == "is":
            for v, _ in split_values(val):
                if v.lower() not in IS_VALUES:
                    emit("error", "IS_VALUE", target or "-", t,
                         "`is:%s` is not a value `is:` takes, so the query matches nothing" % v, "")
            continue
        if qual == "state":
            for v, _ in split_values(val):
                if v.lower() not in STATE_VALUES:
                    emit("error", "IS_VALUE", target or "-", t,
                         "`state:%s` is not open or closed, so the query matches nothing" % v, "")
            continue
        if qual != "label":
            continue
        if not target:
            continue
        ls = res.label_set(target)
        if ls is None:
            if res.missing_repo(target):
                emit("error", "NO_REPO", target, target, "repository %s was not found (deleted, or private)" % target, "")
            else:
                emit("warning", "UNCHECKED", target, t, "label list of %s could not be read" % target, "")
            continue
        vals = split_values(val)
        for j, (v, quoted) in enumerate(vals):
            if ls.has(v):
                if not ls.exact(v):
                    emit("warning", "CASE", target, v,
                         'label "%s" is spelled "%s" in %s' % (v, ls.lower[v.lower()], target), "")
                continue
            # unquoted multi-word label: `label:good first issue`
            if not quoted and j == len(vals) - 1:
                words, found = [], ""
                for k in range(i + 1, min(i + 6, len(toks))):
                    if QUAL_RE.match(toks[k]) or toks[k].upper() in ("AND", "OR", "NOT"):
                        break
                    words.append(toks[k])
                    cand = " ".join([v] + words)
                    if ls.has(cand):
                        found = cand
                        break
                if found:
                    real = ls.lower[found.lower()]
                    emit("error", "UNQUOTED", target, found,
                         'label:%s searches the label "%s" and the text "%s"; the label "%s" '
                         "needs quotes" % (found, v, " ".join(words), real), 'label:"%s"' % real)
                    continue
            sug = ls.suggest(v)
            if neg:
                emit("warning", "NEG_LABEL", target, v,
                     'excludes label "%s", which %s does not have, so it excludes nothing' % (v, target),
                     '"%s"' % sug if sug else "")
            elif len(vals) > 1 and any(ls.has(x) for x, _ in vals):
                # label:a,b is a OR b: the link still shows the issues under the label that exists
                emit("warning", "OR_LABEL", target, v,
                     'label "%s" does not exist in %s; the other labels in this OR still match' % (v, target),
                     '"%s"' % sug if sug else "")
            else:
                emit("error", "LABEL", target, v, 'label "%s" does not exist in %s' % (v, target),
                     '"%s"' % sug if sug else "")


# --------------------------------------------------------------------------- links

def clean_url(u):
    u = html.unescape(u)
    while u and u[-1] in ".,;:!?*_~'\"":
        if u[-1] in "'\"" and u.count(u[-1]) % 2 == 0:
            break  # a closing quote that belongs to the URL: labels/"good first issue"
        u = u[:-1]
    # markdown emphasis or a closing bracket glued on
    return u


def check_url(u, emit, res):
    u = clean_url(u)
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return False
    path = p.path
    qs = urllib.parse.parse_qs(p.query, keep_blank_values=True)
    if path.rstrip("/") in ("/issues", "/pulls", "/search"):
        for q in qs.get("q", []):
            if "label:" in q.lower() or "is:" in q.lower() or "state:" in q.lower():
                check_query(q, None, emit, res)
                return True
        return False
    m = PATH_RE.match(path)
    if not m:
        return False
    owner, name, rest = m.group(1), m.group(2), m.group(3) or ""
    if owner.lower() in RESERVED_OWNERS:
        return False
    if name.endswith(".git"):
        name = name[:-4]
    repo = "%s/%s" % (owner, name)
    rest_dec = rest
    if rest.startswith("/labels/"):
        raw = rest[len("/labels/"):].split("/")[0]
        if not raw:
            return False
        label = urllib.parse.unquote(raw)
        ls = res.label_set(repo)
        if ls is None:
            if res.missing_repo(repo):
                emit("error", "NO_REPO", repo, repo, "repository %s was not found (deleted, or private)" % repo, "")
            else:
                emit("warning", "UNCHECKED", repo, label, "label list of %s could not be read" % repo, "")
            return True
        if ls.has(label):
            if not ls.exact(label):
                emit("warning", "CASE", repo, label,
                     'label "%s" is spelled "%s" in %s' % (label, ls.lower[label.lower()], repo), "")
            return True
        if '"' in label:
            # the label page puts the quotes inside the name: state:open label:"\"good first issue\""
            bare = label.replace('"', "")
            emit("error", "QUOTED_PATH", repo, label,
                 "quotes in a /labels/ path become part of the label name, and %s has no label "
                 "named %s" % (repo, label),
                 "labels/" + urllib.parse.quote(ls.lower[bare.lower()]) if ls.has(bare) else "")
            return True
        if "+" in label and ls.has(label.replace("+", " ")):
            emit("warning", "PLUS_PATH", repo, label,
                 '"+" in a path is a plus sign; the label is "%s" (write %%20)' % label.replace("+", " "),
                 "labels/" + urllib.parse.quote(ls.lower[label.replace("+", " ").lower()]))
            return True
        sug = ls.suggest(label)
        emit("error", "LABEL", repo, label, 'label "%s" does not exist in %s' % (label, repo),
             '"%s"' % sug if sug else "")
        return True
    base = rest.rstrip("/")
    if base in ("/issues", "/pulls", "/issues/new", "/issues/new/choose", "/discussions"):
        touched = False
        for q in qs.get("q", []):
            check_query(q, repo, emit, res)
            touched = True
        if base != "/discussions":
            for lv in qs.get("labels", []):
                touched = True
                names = [x.strip() for x in lv.split(",") if x.strip()]
                ls = res.label_set(repo) if names else None
                if names and ls is None:
                    if res.missing_repo(repo):
                        emit("error", "NO_REPO", repo, repo, "repository %s was not found (deleted, or private)" % repo, "")
                    else:
                        emit("warning", "UNCHECKED", repo, lv, "label list of %s could not be read" % repo, "")
                    continue
                for n in names:
                    if ls.has(n):
                        if not ls.exact(n):
                            emit("warning", "CASE", repo, n,
                                 'label "%s" is spelled "%s" in %s' % (n, ls.lower[n.lower()], repo), "")
                        continue
                    sug = ls.suggest(n)
                    emit("error", "LABEL", repo, n, 'label "%s" does not exist in %s' % (n, repo),
                         '"%s"' % sug if sug else "")
        if base == "/issues/new":
            for tv in qs.get("template", []):
                if not tv or tv == "BLANK_ISSUE":  # GitHub's own name for the blank form (scikit-learn)
                    continue
                touched = True
                names = res.templates(repo)
                if names is None:
                    emit("warning", "UNCHECKED", repo, tv, "template list of %s could not be read" % repo, "")
                    continue
                if tv not in names:
                    lower = {n.lower(): n for n in names}
                    stem = {n.rsplit(".", 1)[0].lower(): n for n in names}
                    sug = lower.get(tv.lower()) or stem.get(tv.rsplit(".", 1)[0].lower(), "")
                    if not sug:
                        # renamed with an ordering prefix: found-a-bug.yml -> 2-found-a-bug.yml
                        ts = tv.rsplit(".", 1)[0].lower()
                        hits = [n for n in names if len(ts) >= 4 and
                                n.rsplit(".", 1)[0].lower().endswith(ts)]
                        sug = hits[0] if len(hits) == 1 else ""
                    emit("error", "TEMPLATE", repo, tv,
                         "template %s is not in %s/%s" % (tv, repo, TEMPLATE_DIR), sug)
        return touched
    return False


# --------------------------------------------------------------------------- issue templates

def _unq(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return s


def _strip_comment(s):
    out, inq = "", None
    for i, ch in enumerate(s):
        if inq:
            if ch == inq:
                inq = None
        elif ch in "'\"":
            inq = ch
        elif ch == "#" and (i == 0 or s[i - 1].isspace()):
            break
        out += ch
    return out.rstrip()


def template_labels(text, markdown):
    """[(line_no, label)] from an issue template's top-level `labels:`."""
    lines = text.splitlines()
    start, end = 0, len(lines)
    if markdown:
        if not lines or lines[0].strip() != "---":
            return []
        for k in range(1, len(lines)):
            if lines[k].strip() in ("---", "..."):
                end = k
                break
        else:
            return []
        start = 1
    out = []
    k = start
    while k < end:
        line = lines[k]
        m = re.match(r"^labels\s*:(.*)$", line)
        if not m:
            k += 1
            continue
        rest = _strip_comment(m.group(1)).strip()
        if rest.startswith("["):
            buf, kk = rest, k
            while "]" not in buf and kk + 1 < end:
                kk += 1
                buf += " " + _strip_comment(lines[kk]).strip()
            inner = buf[1:buf.index("]")] if "]" in buf else buf[1:]
            for part in re.findall(r'"[^"]*"|\'[^\']*\'|[^,]+', inner):
                v = _unq(part)
                if v.strip():
                    out.append((k + 1, v.strip()))
            k = kk + 1
            continue
        if rest and rest not in ("|", ">", "|-", ">-"):
            v = _unq(rest)
            for part in v.split(","):
                if part.strip():
                    out.append((k + 1, _unq(part.strip())))
            k += 1
            continue
        kk = k + 1
        while kk < end and (lines[kk].startswith((" ", "\t")) or not lines[kk].strip()):
            mm = re.match(r"^\s+-\s+(.*)$", lines[kk])
            if mm:
                v = _unq(_strip_comment(mm.group(1)))
                # `- area/datasource,type/new-plugin-request` (grafana): whether GitHub splits a
                # list item at its comma is not documented; we split, so we never report a label
                # that GitHub may well have applied
                for part in v.split(","):
                    if part.strip():
                        out.append((kk + 1, _unq(part.strip())))
            kk += 1
        k = kk
    return out


def check_template(rel, text, repo, res, emit_at):
    markdown = rel.lower().endswith((".md", ".markdown"))
    items = template_labels(text, markdown)
    if not items:
        return 0
    ls = res.label_set(repo) if repo else None
    for line, lab in items:
        if ls is None:
            emit_at(line, "warning", "UNCHECKED", repo or "-", lab,
                    "label list of %s could not be read" % (repo or "this repository"), "")
            continue
        if ls.has(lab):
            if not ls.exact(lab):
                emit_at(line, "warning", "CASE", repo, lab,
                        'template label "%s" is spelled "%s" in %s' % (lab, ls.lower[lab.lower()], repo), "")
            continue
        sug = ls.suggest(lab)
        emit_at(line, "error", "LABEL", repo, lab,
                'template label "%s" does not exist in %s, so issues filed with this template '
                "never get it" % (lab, repo), '"%s"' % sug if sug else "")
    return len(items)


# --------------------------------------------------------------------------- walking

def iter_files(paths):
    for p in paths:
        p = Path(p)
        if p.is_file():
            yield p, p.parent
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not
                                 (d.startswith(".") and d != ".github"))
            for f in sorted(filenames):
                fp = Path(dirpath) / f
                if fp.suffix.lower() in TEXT_EXT:
                    yield fp, p


def repo_from_git(root):
    root = Path(root).resolve()
    for d in [root] + list(root.parents):
        cfg = d / ".git" / "config"
        if cfg.is_file():
            try:
                text = cfg.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', text, re.S)
            if m:
                mm = re.search(r"github\.com[:/](%s)/(%s?)(?:\.git)?/?$" % (OWNER, NAME), m.group(1))
                if mm:
                    name = mm.group(2)
                    return "%s/%s" % (mm.group(1), name[:-4] if name.endswith(".git") else name)
            return None
    return None


def local_templates(root):
    """Template file names in the checkout. [] when this is a repository root with no template
    folder; None when root is not a repository root (then the API is asked)."""
    root = Path(root)
    d = root / TEMPLATE_DIR
    if d.is_dir():
        return sorted(x.name for x in d.iterdir() if x.is_file())
    if (root / ".git").exists() or (root / ".github").is_dir():
        return []
    return None


def scan_text(rel, text, repo, res, findings, in_template_dir=False):
    """Check one file's text. Returns the number of links + template labels examined."""
    n = 0

    def emit_at(line):
        def emit(sev, code, rrepo, subject, message, suggest):
            findings.append(Finding(rel, line, sev, code, rrepo, subject, message, suggest))
        return emit

    for i, line in enumerate(text.splitlines(), 1):
        if "github.com" not in line.lower():
            continue
        spans = []
        # a Markdown link target runs to its closing parenthesis, quotes included
        # (starship's README had `labels/"🌱%20good%20first%20issue"`)
        for m in MD_TARGET_RE.finditer(line):
            spans.append((m.start(1), m.end(1)))
            if check_url(m.group(1), emit_at(i), res):
                n += 1
        for m in URL_RE.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            if check_url(m.group(0), emit_at(i), res):
                n += 1
    if in_template_dir:
        def emit2(line, *a):
            emit_at(line)(*a)
        n += check_template(rel, text, repo, res, emit2)
    return n


def run(paths, repo=None, labels=None, source=None, root=None):
    """Returns (findings, files_read, items_checked)."""
    root = Path(root or (paths[0] if paths else "."))
    if Path(root).is_file():
        root = Path(root).parent
    repo = repo or repo_from_git(root)
    res = Resolver(repo, labels, local_templates(root), source)
    findings, files, items = [], 0, 0
    for fp, base in iter_files(paths):
        try:
            if fp.stat().st_size > MAX_BYTES:
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files += 1
        try:
            rel = fp.relative_to(root).as_posix()
        except ValueError:
            rel = fp.as_posix()
        in_tpl = ("/" + rel.lower()).find("/" + TEMPLATE_DIR.lower() + "/") >= 0 and \
            fp.suffix.lower() in (".yml", ".yaml", ".md", ".markdown")
        items += scan_text(rel, text, repo, res, findings, in_tpl and not fp.name.lower().startswith("config."))
    seen, out = set(), []
    for f in findings:  # a markdown link that shows its own URL as its text is one finding, not two
        k = (f.path, f.line, f.code, f.repo.lower(), f.subject)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out, files, items, repo, res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", default=["."])
    ap.add_argument("--repo", help="OWNER/NAME of the repository the files belong to "
                                   "(default: the origin remote, or GITHUB_REPOSITORY)")
    ap.add_argument("--labels", help="file with the repository's labels (JSON or one per line)")
    ap.add_argument("--offline", action="store_true", help="never call the API")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except AttributeError:
        pass
    repo = a.repo or None
    root = Path(a.paths[0])
    if not repo:
        repo = repo_from_git(root if root.is_dir() else root.parent) or os.environ.get("GITHUB_REPOSITORY") or None
    labels = None
    if a.labels:
        try:
            labels = parse_label_file(Path(a.labels).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            print("label-link-check: cannot read --labels %s: %s" % (a.labels, e), file=sys.stderr)
            return 2
    source = ApiSource(offline=a.offline)
    findings, files, items, repo, res = run(a.paths, repo, labels, source)
    if files == 0:
        print("label-link-check: no files read under %s -- nothing was checked" % " ".join(a.paths),
              file=sys.stderr)
        return 2
    own_unreadable = any(f.code == "UNCHECKED" and (f.repo == "-" or (repo and f.repo.lower() == repo.lower()))
                         for f in findings)
    errors = [f for f in findings if f.severity == "error"]
    if a.json:
        print(json.dumps({"repo": repo, "files": files, "checked": items,
                          "findings": [f.as_dict() for f in findings]}, ensure_ascii=False, indent=1))
    else:
        for f in findings:
            print(f)
        print("label-link-check: %d files, %d links and template labels checked, %d errors, %d warnings"
              % (files, items, len(errors), len(findings) - len(errors)))
    if errors:
        return 1
    if own_unreadable:
        print("label-link-check: the label list of %s could not be read (pass --repo and --labels, "
              "or set GITHUB_TOKEN) -- those labels were NOT checked" % (repo or "this repository"),
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
