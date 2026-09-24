# -*- coding: utf-8 -*-
"""Read a changelog the way a lab reads a patient's results: against the entry next to it.

    python changelog_check.py path/to/repo              # CHANGELOG*, CHANGES*, HISTORY*, NEWS* ...
    python changelog_check.py CHANGELOG.md              # one file
    python changelog_check.py . --as-of 2024-01-15      # "today", for dates in the future
    python changelog_check.py . --explain               # also list every release entry it read

A clinical lab does not re-check every result by hand. It compares each one with the same
patient's previous value, and a difference no body can produce is held back as a probable
mix-up (a "delta check"). A specimen it cannot measure is returned as unfit, not guessed.

A changelog has the same shape. Each release entry has a version and usually a date, and the
entry below it is the previous release. So a version dated before the release it follows, the
Unreleased link still comparing from two versions ago, or `[1.4.0]: .../compare/v1.3.0...v1.3.1`
is a value that cannot be right next to its neighbour. This script reports those, and only
those: it does not judge the prose, and a date it cannot read unambiguously (03/04/2024) is
counted as unreadable, never guessed.

Standard library only. Reads files; runs nothing, writes nothing, sends nothing.
Exit code: 0 = no errors (warnings fail only with --strict), 1 = errors, 2 = no changelog found.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

NAMES = re.compile(r"(?i)^(changelog|changes|history|news|releases?|release[-_ ]notes)"
                   r"(\.(md|markdown|mdown|rst|txt|adoc))?$")
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "third-party", "dist", "build",
             "target", ".venv", "venv", "site-packages", "bower_components", "__pycache__",
             "fixtures", "testdata", "__fixtures__", "test_fixtures", ".tox", ".cache"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"])}
for _k, _v in list(MONTHS.items()):
    MONTHS[_k[:3]] = _v
MONTHS["sept"] = 9
MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

VERSION = re.compile(r"(?<![\w.\-/])[vV]?(\d+(?:\.\d+){1,3})((?:-[0-9A-Za-z][0-9A-Za-z.\-]*)?(?:\+[0-9A-Za-z.\-]+)?)(?![\w.])")
# words that make a heading a section about versions, not a release of one
NOT_RELEASE = re.compile(r"(?i)\b(upgrad\w*|migrat\w*|from|since|before|after|prior|compat\w*|"
                         r"support\w*|requir\w*|until|through|older|breaking|deprecat\w*|to)\b")
PLACEHOLDER = re.compile(r"(?i)\b(yyyy[-/.]mm[-/.]dd|xxxx[-/.]xx[-/.]xx|tbd|tba|unreleased|not released|"
                         r"upcoming|in progress|wip|\?\?\?\?)\b")
LINKDEF = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*<?(\S+?)>?(?:\s+[\"'(].*)?\s*$")
INLINE_URL = re.compile(r"\]\((https?://[^)\s]+)\)")
COMPARE = re.compile(r"/compare/([^/?#]+?)\.{2,3}([^/?#]+?)(?:[?#].*)?$")
TAGURL = re.compile(r"/(?:releases/tag|tree|-/tags|tags)/([^/?#]+)/?$")
FENCE = re.compile(r"^ {0,3}(```|~~~)")
PREWORD = re.compile(r"(?i)^[ \t]*[-_]?[ \t]*(alpha|beta|rc|pre|preview|dev)[ \t.\-_]?(\d*)(?![\w.])")
EDITION = re.compile(r"(?i)^[ \t]*[-_(]?[ \t]*(enterprise|ent|lts|community|ce|ee)\b")


class Finding:
    def __init__(self, path, line, level, code, msg):
        self.path, self.line, self.level, self.code, self.msg = path, line, level, code, msg

    def __str__(self):
        return "%s:%d: %s %s %s" % (self.path, self.line, self.level, self.code, self.msg)

    def as_dict(self):
        return {"path": self.path, "line": self.line, "level": self.level, "code": self.code,
                "message": self.msg}


class Entry:
    def __init__(self, line, raw_version, key, date, date_text, placeholder, heading, ref_label, inline_url):
        self.line = line
        self.raw = raw_version                  # "1.2.3-rc.1"
        self.key = key                          # package prefix ("" for most files)
        self.v = parse_version(raw_version)
        self.build = raw_version.split("+", 1)[1].lower() if "+" in raw_version else ""
        self.edition = ""
        self.date = date                        # datetime.date or None
        self.date_text = date_text              # the text it was read from
        self.placeholder = placeholder          # "YYYY-MM-DD", "TBD" ...
        self.heading = heading
        self.ref_label = ref_label              # "[1.2.3]" used as a reference link
        self.inline_url = inline_url            # "## [1.2.3](https://.../compare/...)"

    @property
    def line_of_release(self):
        return self.v[0][:2]

    @property
    def special(self):
        """A re-release of a version (1.2.1+security-01, 2.0.2 Enterprise), not the next release."""
        return bool(self.build or self.edition)

    @property
    def ident(self):
        return (self.v, self.build, self.edition)


def parse_version(raw):
    m = re.match(r"(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.\-]+))?", raw)
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    pre = m.group(2)
    # a release sorts after its prereleases; prereleases compare part by part
    if pre is None:
        pkey = (1,)
    else:
        parts = []
        # "alpha11" after "alpha9": letters and digits compared apart
        for p in re.findall(r"\d+|[A-Za-z]+", pre):
            parts.append((0, int(p), "") if p.isdigit() else (1, 0, p.lower()))
        pkey = (0, tuple(parts))
    return (tuple(nums), pkey)


def vcmp(a, b):
    return (a > b) - (a < b)


# ---------------------------------------------------------------- dates

def _mkdate(y, m, d):
    try:
        return dt.date(y, m, d), None
    except ValueError:
        return None, "%04d-%02d-%02d" % (y, m, d)


def find_date(text, dmy_hint=None):
    """Return (date, matched_text, status). status: 'ok' / 'bad' (not a calendar date) /
    'ambiguous' (03/04/2024) / None (no date). Month-only dates are day 1 with status 'month'."""
    t = text
    m = re.search(r"(?<!\d)((?:19|20)\d{2})([-/.])(\d{1,2})\2(\d{1,2})(?!\d)", t)
    if m:
        d, bad = _mkdate(int(m.group(1)), int(m.group(3)), int(m.group(4)))
        return (d, m.group(0), "ok") if d else (None, m.group(0), "bad")
    m = re.search(r"(?<!\d)(\d{1,2})([-/.])(\d{1,2})\2((?:19|20)\d{2})(?!\d)", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        sep = m.group(2)
        if a > 12 and b <= 12:
            order = "dmy"
        elif b > 12 and a <= 12:
            order = "mdy"
        elif a == b:
            order = "dmy"
        elif sep == "." or (dmy_hint or {}).get(sep):
            order = (dmy_hint or {}).get(sep) or "dmy"   # 01.02.2024 is day-first wherever it is written
        else:
            return None, m.group(0), "ambiguous"
        dd, mm = (a, b) if order == "dmy" else (b, a)
        d, bad = _mkdate(y, mm, dd)
        return (d, m.group(0), "ok") if d else (None, m.group(0), "bad")
    m = re.search(r"(?i)\b" + MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{2})\b", t)
    if m:
        d, bad = _mkdate(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        return (d, m.group(0), "ok") if d else (None, m.group(0), "bad")
    m = re.search(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON + r"\.?,?\s+((?:19|20)\d{2})\b", t)
    if m:
        d, bad = _mkdate(int(m.group(3)), MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        return (d, m.group(0), "ok") if d else (None, m.group(0), "bad")
    m = re.search(r"(?i)\b" + MON + r"\.?,?\s+((?:19|20)\d{2})\b", t)
    if m:
        return dt.date(int(m.group(2)), MONTHS[m.group(1).lower()[:3]], 1), m.group(0), "month"
    m = re.search(r"(?<![\d.\-])((?:19|20)\d{2})-(\d{1,2})(?![\d\-.])", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return dt.date(int(m.group(1)), int(m.group(2)), 1), m.group(0), "month"
    return None, None, None


def dmy_hints(lines):
    """Which separators this file writes day-first or month-first, from dates only one way can read."""
    votes = {}
    for ln in lines:
        for m in re.finditer(r"(?<!\d)(\d{1,2})([-/.])(\d{1,2})\2((?:19|20)\d{2})(?!\d)", ln):
            a, b, sep = int(m.group(1)), int(m.group(3)), m.group(2)
            if a > 12 >= b:
                votes.setdefault(sep, [0, 0])[0] += 1
            elif b > 12 >= a:
                votes.setdefault(sep, [0, 0])[1] += 1
    out = {}
    for sep, (dmy, mdy) in votes.items():
        if dmy and not mdy:
            out[sep] = "dmy"
        elif mdy and not dmy:
            out[sep] = "mdy"
    return out


# ---------------------------------------------------------------- reading a file

def headings(lines):
    """Yield (index, level, text) for ATX and setext/rst headings outside code fences and comments."""
    in_fence = None
    in_comment = False
    n = len(lines)
    for i, ln in enumerate(lines):
        s = ln.rstrip("\n")
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        fm = FENCE.match(s)
        if fm:
            if in_fence is None:
                in_fence = fm.group(1)
            elif s.strip().startswith(in_fence):
                in_fence = None
            continue
        if in_fence:
            continue
        if s.lstrip().startswith("<!--"):
            if "-->" not in s:
                in_comment = True
            continue
        m = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if m:
            yield i, len(m.group(1)), m.group(2)
            continue
        if i + 1 < n and s.strip() and not s.startswith((" ", "\t", "-", "*", "+", ">", "|")):
            u = lines[i + 1].rstrip("\n")
            um = re.match(r"^([=\-~^*+#`'\"])\1{2,}\s*$", u)
            if um and len(u.strip()) >= min(3, len(s.strip())):
                yield i, {"=": 1, "-": 2}.get(um.group(1), 3), s.strip()


def plain_line_entries(lines):
    """NEWS-style files: '1.2.3 (2024-01-05)' at column 0 with no heading markup."""
    for i, ln in enumerate(lines):
        s = ln.rstrip("\n")
        if re.match(r"^[vV]?\d+\.\d+", s) and len(s) < 120:
            d, txt, st = find_date(s)
            if st:
                yield i, 2, s.strip()


def strip_md(text):
    t = re.sub(r"\]\([^)]*\)", "]", text)          # inline link targets
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"(?<![\w])[*_](?=\S)|(?<=\S)[*_](?![\w])", "", t)
    return t


def read_entry(idx, text, lines, hint):
    """Return an Entry, or None if the heading is not a release entry."""
    clean = strip_md(text)
    m = VERSION.search(clean)
    # "2013.08.21, Version 0.11.7": the first dotted number is the date
    if m and re.match(r"^(19|20)\d{2}\.\d{1,2}\.\d{1,2}$", m.group(1)) and not m.group(2):
        m2 = VERSION.search(clean, m.end())
        if m2:
            m = m2
    if not m:
        return None
    prefix = clean[:m.start()]
    if len(prefix) > 50 or NOT_RELEASE.search(prefix):
        return None
    # "## 1.x and 2.0 differences" / "## Node 18 support (1.2.0)" -- the version is not the subject
    rest = clean[m.end():]
    if NOT_RELEASE.search(rest.split("(")[0].split(" - ")[0].split(" – ")[0]) and not find_date(rest)[2]:
        return None
    raw = m.group(1) + (m.group(2) or "")
    edition = ""
    if not m.group(2):
        # "Version 1.3 beta3", "2.0.0 rc2", "1.0 RC 1": a prerelease written with a space
        qm = PREWORD.match(rest)
        if qm:
            raw += "-" + qm.group(1).lower() + (("." + qm.group(2)) if qm.group(2) else "")
            rest = rest[qm.end():]
    em = EDITION.match(rest)
    if em:
        edition = em.group(1).lower()
    key = re.sub(r"(?i)\b(version|release|v)\b", " ", prefix)
    key = re.sub(r"[\[\]()<>:#*_`\"'\s]+", " ", key).strip().rstrip("@-_ /").lower()
    if key in ("v", "ver", "rel"):
        key = ""
    if not prefix.strip() and clean[:m.start()].strip() == "":
        key = ""
    # the date: in the heading after the version, else on the line right below it
    date_src = re.sub(r"\((https?://[^)]*)\)", " ", text[text.find(m.group(1)) + len(m.group(1)):] if m.group(1) in text else rest)
    d, dtext, st = find_date(date_src, hint)
    if st is None:
        # "2013.08.21, Version 0.11.7": the date before the version
        pd = find_date(clean[:m.start()], hint)
        if pd[2] in ("ok", "bad"):
            d, dtext, st = pd
    placeholder = None
    if st is None:
        pm = PLACEHOLDER.search(date_src)
        if pm:
            placeholder = pm.group(0)
        else:
            for j in range(idx + 1, min(idx + 4, len(lines))):
                nxt = lines[j].strip()
                if not nxt or re.match(r"^[=\-~^*+#]{3,}$", nxt):
                    continue
                if re.match(r"(?i)^[_*>\s(]*(released?|release date|date|published|shipped)\b", nxt):
                    d, dtext, st = find_date(nxt, hint)
                else:
                    # a line that is only a date: "_2009-04-01_"
                    nd = find_date(nxt, hint)
                    if nd[1] and not re.sub(r"[\s_*()\[\]>.,:-]", "", nxt.replace(nd[1], "")):
                        d, dtext, st = nd
                break
    ref = None
    rm = re.search(r"\[([^\]]*" + re.escape(m.group(1)) + r"[^\]]*)\](?!\()", text)
    if rm and "](" not in text[rm.start():rm.end() + 1]:
        ref = rm.group(1)
    um = INLINE_URL.search(text)
    e = Entry(idx + 1, raw, key, d if st in ("ok", "month") else None, dtext, placeholder, text.strip(),
              ref, um.group(1) if um else None)
    e.date_status = st
    e.edition = edition
    return e


def read_file(path, text):
    lines = text.splitlines()
    hint = dmy_hints(lines)
    entries = []
    for idx, level, htext in headings(lines):
        e = read_entry(idx, htext, lines, hint)
        if e:
            e.level = level
            entries.append(e)
    if not entries:
        for idx, level, htext in plain_line_entries(lines):
            e = read_entry(idx, htext, lines, hint)
            if e:
                e.level = level
                entries.append(e)
    # keep the entries at the level most release entries use (a "## 2.0" above "### 2.0.1" both count;
    # a version mentioned in a "#### Fixed in 1.2" sub-heading two levels down does not)
    if entries:
        levels = {}
        for e in entries:
            levels[e.level] = levels.get(e.level, 0) + 1
        top = max(levels.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        entries = [e for e in entries if e.level <= top + 1 and (e.level >= top - 1)]
    kept = []
    for e in entries:
        parent = next((o for o in reversed(kept) if o.level < e.level), None)
        if parent is not None and parent.ident == e.ident and parent.key == e.key:
            continue
        kept.append(e)
    entries = kept
    # "## 4.4" over "## 4.4.1" ... "## 4.4.0": a two-part heading is the section for its line
    # when the file also has three-part releases of that line
    three = {e.line_of_release for e in entries if re.match(r"^\d+\.\d+\.\d+", e.raw)}
    entries = [e for e in entries if not (re.match(r"^\d+\.\d+$", e.raw) and e.line_of_release in three
                                          and not e.date)]
    defs = {}
    dup_defs = []
    in_fence = None
    for i, ln in enumerate(lines):
        fm = FENCE.match(ln)
        if fm:
            in_fence = None if in_fence else fm.group(1)
            continue
        if in_fence:
            continue
        m = LINKDEF.match(ln)
        if m:
            label = m.group(1).strip().lower()
            if label in defs:
                if defs[label][1] != m.group(2):
                    dup_defs.append((i + 1, label, defs[label]))
            else:
                defs[label] = (i + 1, m.group(2))
    return entries, defs, dup_defs, lines


# ---------------------------------------------------------------- the rules

def version_in(s):
    """The version a tag or compare side names ('v1.2.3', 'pkg@1.2.3', 'release-1.2.3')."""
    m = VERSION.search(re.sub(r"%40", "@", s))
    if not m:
        m = re.search(r"(\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.\-]+)?)$", s)
        if not m:
            return None
        return parse_version(m.group(1))
    return parse_version(m.group(1) + (m.group(2) or ""))


def check_entries(path, entries, defs, dup_defs, as_of, strict_future=False):
    f = []
    groups = {}
    for e in entries:
        groups.setdefault(e.key, []).append(e)
    stats = {"entries": len(entries), "dated": 0, "undated": 0, "unreadable": 0, "not_reported": 0}
    for e in entries:
        if e.date:
            stats["dated"] += 1
        elif e.date_status in ("ambiguous",):
            stats["unreadable"] += 1
        elif e.date_status != "bad":
            stats["undated"] += 1
    version_labels = {lab for lab in defs if VERSION.search(lab)}

    for key, g in groups.items():
        # which way the file runs: count adjacent pairs going down and up
        down = sum(1 for a, b in zip(g, g[1:]) if vcmp(a.v, b.v) > 0)
        up = sum(1 for a, b in zip(g, g[1:]) if vcmp(a.v, b.v) < 0)
        seq = list(g) if down >= up else list(reversed(g))       # newest first
        ascending = up > down
        # re-releases (1.2.1+security-01, 2.0.2 Enterprise) come out after newer versions on purpose;
        # they are read, counted and checked for duplicates, but they are nobody's neighbour
        plain = [e for e in seq if not e.special]

        # BADDATE: a date that is not on the calendar
        for e in g:
            if e.date_status == "bad":
                f.append(Finding(path, e.line, "error", "BADDATE",
                                 "%s is dated %s, which is not a date" % (e.raw, e.date_text)))

        # DUPVER: one version, two entries
        by = {}
        for e in g:
            by.setdefault(e.ident, []).append(e)
        for v, es in by.items():
            if len(es) > 1:
                for e in es[1:]:
                    f.append(Finding(path, e.line, "error", "DUPVER",
                                     "%s has a second entry (first at line %d)" % (e.raw, es[0].line)))

        # FUTURE: released after "today"
        top_v = max((e.v for e in g), default=None)
        for e in g:
            if not e.date or as_of is None:
                continue
            ahead = (e.date - as_of).days
            if e.date_status == "month":
                ahead = (e.date - as_of.replace(day=1)).days
                if ahead <= 0:
                    continue
            if ahead > 2:
                is_top = e.v == top_v
                if is_top and ahead <= 60 and not strict_future:
                    f.append(Finding(path, e.line, "warning", "FUTURE?",
                                     "%s is dated %s, %d days after %s (a planned date?)"
                                     % (e.raw, e.date.isoformat(), ahead, as_of.isoformat())))
                else:
                    f.append(Finding(path, e.line, "error", "FUTURE",
                                     "%s is dated %s, %d days after %s" % (e.raw, e.date.isoformat(), ahead, as_of.isoformat())))

        # PLACEHOLDER: a released version below others still waiting for its date
        for i, e in enumerate(seq):
            if e.placeholder and i > 0 and any(o.date for o in seq[:i]):
                f.append(Finding(path, e.line, "warning", "PLACEHOLDER",
                                 "%s still says '%s', and a newer release is dated"
                                 % (e.raw, e.placeholder)))

        reported = set()

        # ORDER: within one release line, versions must fall as the file goes down (newest first)
        lines_of = {}
        for e in plain:
            lines_of.setdefault(e.line_of_release, []).append(e)
        for rl, es in lines_of.items():
            finals = [e for e in es if e.v[1] == (1,)]      # prereleases interleave in date order
            for a, b in zip(finals, finals[1:]):
                if vcmp(a.v, b.v) < 0:
                    if a.date and b.date and a.date > b.date:
                        continue      # a date-ordered file listing a fix-up above? consistent by date
                    f.append(Finding(path, (b if ascending else a).line, "error", "ORDER",
                                     "%s is listed %s %s, in the same release line"
                                     % (a.raw, "below" if ascending else "above", b.raw)))
                    reported.add(id(a))

        # DATE (same line): a newer version dated before an older one of the same line
        for rl, es in lines_of.items():
            es = [e for e in es if e.date]
            for a, b in zip(es, es[1:]):
                if vcmp(a.v, b.v) > 0 and a.date < b.date and not (
                        a.date_status == "month" or b.date_status == "month") and id(a) not in reported:
                    hint = ""
                    for x, other in ((a, b), (b, a)):
                        for dy in (1, -1):
                            try:
                                alt = x.date.replace(year=x.date.year + dy)
                            except ValueError:
                                continue
                            if (x is a and alt >= b.date) or (x is b and alt <= a.date):
                                if abs((alt - other.date).days) <= 200:
                                    hint = "; %s in %d would fit" % (x.raw, alt.year)
                                    break
                        if hint:
                            break
                    f.append(Finding(path, a.line, "error", "DATE",
                                     "%s is dated %s, before %s (%s) in the same release line%s"
                                     % (a.raw, a.date.isoformat(), b.raw, b.date.isoformat(), hint)))
                    reported.add(id(a))
                    reported.add(id(b))

        # DATE (a year off): the date sits outside the dates of the entries on either side of it,
        # and one year either way puts it between them. Neighbours are by position in the file.
        dated = [e for e in plain if e.date and e.date_status != "month"]
        for i, e in enumerate(dated):
            if id(e) in reported:
                continue
            below = dated[i + 1] if i + 1 < len(dated) else None
            above = dated[i - 1] if i > 0 else None
            if below is None:
                continue
            lo = below.date
            hi = above.date if above else as_of
            if hi is None:
                continue          # no upper bound
            # (when the neighbours disagree with each other, hi < lo, no shifted date fits between
            # them below, so this entry is never made the odd one)
            if lo <= e.date <= hi:
                continue
            for dy in (1, -1):
                try:
                    alt = e.date.replace(year=e.date.year + dy)
                except ValueError:
                    continue
                if not (lo <= alt <= hi):
                    continue
                if e.date < lo:
                    side, other = "before %s (%s), the entry below it" % (below.raw, below.date.isoformat()), below
                else:
                    side = ("after %s (%s), the entry above it" % (above.raw, above.date.isoformat())) if above \
                        else "after today"
                    other = above
                msg = "%s is dated %s, %s; %d would put it between its neighbours" % (
                    e.raw, e.date.isoformat(), side, alt.year)
                # A patch release of an older line, listed by version, can come out after a newer
                # line: that is the one explanation that is not a typo. It needs the later-dated of
                # the two to be a patch release (x.y.1 and up) of the other line.
                later = below if e.date < lo else e
                backport = any(x > 0 for x in later.v[0][2:]) and other is not None and \
                    other.line_of_release != e.line_of_release
                if above is None or not backport:
                    f.append(Finding(path, e.line, "error", "DATE", msg))
                else:
                    # a release of an older line listed by version can be dated after a newer one
                    f.append(Finding(path, e.line, "warning", "DATE?", msg + " (or a backport listed by version)"))
                reported.add(id(e))
                break

        # across release lines: counted, not reported
        for a, b in zip(dated, dated[1:]):
            if id(a) in reported or id(b) in reported:
                continue
            if vcmp(a.v, b.v) > 0 and a.date < b.date and a.line_of_release != b.line_of_release:
                stats["not_reported"] += 1

        # LINK: reference definitions and inline compare links against the neighbouring entry
        ordered = seq
        for i, e in enumerate(ordered):
            prev = ordered[i + 1] if i + 1 < len(ordered) else None
            targets = []
            if e.ref_label is not None:
                d = defs.get(e.ref_label.strip().lower())
                if d:
                    targets.append((d[0], d[1], "[%s]" % e.ref_label))
                elif version_labels:
                    # a file that links none of its versions writes [1.2.3] as plain text on purpose
                    f.append(Finding(path, e.line, "warning", "LINKDEF",
                                     "[%s] has no link definition (it shows as plain text)" % e.ref_label))
            if e.inline_url:
                targets.append((e.line, e.inline_url, "the heading's link"))
            for ln, url, what in targets:
                cm = COMPARE.search(url)
                tm = TAGURL.search(url)
                if cm:
                    base_s, head_s = cm.group(1), cm.group(2)
                    hv = version_in(head_s)
                    if hv is not None and hv != e.v:
                        f.append(Finding(path, ln, "error", "LINK",
                                         "%s for %s compares up to %s" % (what, e.raw, head_s)))
                        continue
                    bv = version_in(base_s)
                    if bv is None or prev is None:
                        continue
                    if vcmp(bv, e.v) >= 0:
                        f.append(Finding(path, ln, "error", "LINK",
                                         "%s for %s compares from %s, which is not older"
                                         % (what, e.raw, base_s)))
                        continue
                    # a release between the base and this one that came out before this one.
                    # Prereleases are not counted: comparing from the last stable release is a
                    # convention (vue's 3.5.0-beta.1 from v3.4.37), not a skipped release.
                    between = [o for o in plain if o is not e and vcmp(bv, o.v) < 0 and vcmp(o.v, e.v) < 0
                               and o.v[1][0] != 0]
                    skipped = None
                    for o in between:
                        if o.date and e.date:
                            if o.date <= e.date:
                                skipped = o
                                break
                        elif o.line_of_release == e.line_of_release:
                            skipped = o
                            break
                    if skipped is not None:
                        f.append(Finding(path, ln, "error", "LINK",
                                         "%s for %s compares from %s, but %s%s came out in between"
                                         % (what, e.raw, base_s, skipped.raw,
                                            (" (%s)" % skipped.date.isoformat()) if skipped.date else "")))
                elif tm:
                    tv = version_in(tm.group(1))
                    if tv is not None and tv != e.v:
                        f.append(Finding(path, ln, "error", "LINK",
                                         "%s for %s points at the tag %s" % (what, e.raw, tm.group(1))))
        # the Unreleased link should compare from the newest release
        if key == "" and plain:
            for label in ("unreleased", "head", "main", "master", "next"):
                d = defs.get(label)
                if not d:
                    continue
                cm = COMPARE.search(d[1])
                if not cm:
                    continue
                bv = version_in(cm.group(1))
                released = [e for e in plain if not e.placeholder] or plain
                newest = max(released, key=lambda e: e.v)
                if bv is not None and vcmp(bv, newest.v) < 0 and bv in {o.v for o in plain}:
                    f.append(Finding(path, d[0], "error", "LINK",
                                     "[%s] compares from %s, but the newest release is %s"
                                     % (label.capitalize() if label == "unreleased" else label, cm.group(1), newest.raw)))

    for ln, label, first in dup_defs:
        if VERSION.search(label):
            f.append(Finding(path, ln, "warning", "DUPLINK",
                             "[%s] is defined again; Markdown uses the first one (line %d)" % (label, first[0])))
    f.sort(key=lambda x: (x.line, x.code))
    return f, stats


def check_text(path, text, as_of=None, strict_future=False):
    entries, defs, dup_defs, lines = read_file(path, text)
    f, st = check_entries(path, entries, defs, dup_defs, as_of, strict_future)
    return f, st, entries


# ---------------------------------------------------------------- files

def find_changelogs(root):
    if os.path.isfile(root):
        return [root]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if NAMES.match(fn):
                out.append(os.path.join(dirpath, fn))
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", default=["."])
    ap.add_argument("--as-of", help="the date to call today (YYYY-MM-DD); default: today")
    ap.add_argument("--explain", action="store_true", help="also list every release entry read")
    ap.add_argument("--strict", action="store_true", help="warnings fail too")
    ap.add_argument("--json", action="store_true", help="findings as JSON")
    a = ap.parse_args(argv)
    as_of = dt.date.fromisoformat(a.as_of) if a.as_of else dt.date.today()
    files = []
    for p in a.paths:
        files.extend(find_changelogs(p))
    allf = []
    tot = {"files": 0, "entries": 0, "dated": 0, "undated": 0, "unreadable": 0, "not_reported": 0}
    base = a.paths[0] if len(a.paths) == 1 and os.path.isdir(a.paths[0]) else None
    for fp in files:
        try:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as ex:
            print("%s: cannot read (%s)" % (fp, ex))
            continue
        shown = os.path.relpath(fp, base).replace(os.sep, "/") if base else fp
        f, st, entries = check_text(shown, text, as_of)
        if not entries:
            continue
        tot["files"] += 1
        for k in ("entries", "dated", "undated", "unreadable", "not_reported"):
            tot[k] += st[k]
        allf.extend(f)
        if a.explain:
            for e in entries:
                print("%s:%d: entry %s%s %s" % (shown, e.line, (e.key + " ") if e.key else "", e.raw,
                                                 e.date.isoformat() if e.date else
                                                 ("(%s)" % (e.placeholder or e.date_status or "no date"))))
    errors = sum(1 for x in allf if x.level == "error")
    warnings = len(allf) - errors
    if a.json:
        print(json.dumps({"findings": [x.as_dict() for x in allf], "totals": tot,
                          "errors": errors, "warnings": warnings}, indent=1))
    else:
        for x in allf:
            print(x)
        extra = []
        if tot["unreadable"]:
            extra.append("%d dates not read (day and month could be either way)" % tot["unreadable"])
        if tot["not_reported"]:
            extra.append("%d dates out of order across release lines not reported (backports?)" % tot["not_reported"])
        print("%d changelogs, %d release entries read (%d dated, %d undated)%s; %d errors, %d warnings"
              % (tot["files"], tot["entries"], tot["dated"], tot["undated"],
                 ("; " + "; ".join(extra)) if extra else "", errors, warnings))
    if tot["files"] == 0:
        if not a.json:
            print("no changelog with release entries found under %s" % ", ".join(a.paths))
        return 2
    if errors or (a.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
