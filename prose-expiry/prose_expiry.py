#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prose-expiry: find the expiry dates that only exist as prose in your tree.

    python prose_expiry.py .
    python prose_expiry.py . --within 90
    python prose_expiry.py . --format paste        # counts only: no paths, no line text
    python prose_expiry.py . --ledger EXPIRY.tsv   # add the dates no file contains

Its sibling `key-expiry` reads the two kinds of credential that carry their own death
date inside them (a JWT `exp`, an X.509 `notAfter`) and says, correctly, that it can say
nothing about the rest. This is the rest. Almost every other deadline a team has -
end of support, a contract renewal, a migration cut-off, a certificate somebody else
holds - exists only as a sentence a human typed once, in a README, a ticket, a comment,
a table cell. Nothing reads those sentences again.

This does. It reports a date only when the same line (or the Markdown heading it sits
under) also carries an expiry cue, so a release date or a changelog stamp is not dragged
in. Every row names the cue that matched, because the judgement of whether a line is a
deadline belongs to the reader, not to a word list.

What it cannot do is the honest part, and README.md opens with it: a date nobody wrote
down is invisible here. That is what EXPIRY.tsv and `--ledger` are for.

Exit codes: 0 = nothing has passed and nothing falls inside the window / 1 = something
does, or already has / 2 = the scan did not happen (no target, or zero files read). A
scan that read nothing must not print a green check.

Standard library only. No network access.
"""
import argparse
import re
import sys
from datetime import date, datetime
from fnmatch import fnmatch
from pathlib import Path

VERSION = "0.1.0"

# A deadline is a sentence, not a payload. Anything past this is a build artefact, a
# dump or a minified bundle, and reading it costs more than the row it might contain.
MAX_BYTES = 4 * 1024 * 1024

# How many lines below a Markdown heading the heading still counts as the cue.
HEADING_REACH = 5

SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", ".tox", "dist", "build", ".next"}

# Only files a person writes sentences in. Scanning everything would mean printing lines
# out of key material, and this tool prints the line it matched.
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".org",
                 ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties",
                 ".json", ".tsv", ".csv",
                 ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".go", ".rb", ".rs",
                 ".java", ".kt", ".cs", ".c", ".h", ".cpp", ".php", ".swift",
                 ".sh", ".bash", ".zsh", ".ps1", ".bat", ".sql", ".tf", ".tfvars",
                 ".gradle", ".xml", ".html", ".htm", ".vue", ".svelte", ".gitignore"}

# Files whose whole purpose is to hold a secret. Never opened, even though the suffix
# rule would usually keep them out anyway.
SKIP_NAMES = {".env", ".env.local", ".netrc", "_netrc", "id_rsa", "id_ed25519",
              "credentials", "authorized_keys", ".npmrc", ".pypirc"}
SKIP_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".crt", ".cer", ".der", ".jks", ".keystore"}

# Full names and the usual abbreviations, listed rather than matched with a trailing
# `[a-z]*`: that shortcut read "Maybe 30 2026" as the thirtieth of May.
MONTH_NAMES = [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
               ("may", "may"), ("june", "jun"), ("july", "jul"), ("august", "aug"),
               ("september", "sep"), ("october", "oct"), ("november", "nov"),
               ("december", "dec")]
MONTHS = {}
for _i, (_full, _ab) in enumerate(MONTH_NAMES, 1):
    MONTHS[_full] = _i
    MONTHS[_ab] = _i
MONTHS["sept"] = 9
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

DATE_RES = [
    # 2026-09-30 / 2026-9-3. The separator must repeat, so 2026-09/30 is not a date.
    ("iso", re.compile(r"(?<![\d/-])(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?![\d/-])")),
    # 2026年9月30日
    ("jp", re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")),
    # September 30, 2026 / Sep 30 2026
    ("mdy", re.compile(r"\b(" + MONTH_ALT + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
    # 30 September 2026
    ("dmy", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + MONTH_ALT + r")\.?,?\s+(\d{4})\b", re.I)),
]

# Cues split in two tiers on one test: would a reader who saw this word next to a date
# agree, without further context, that a deadline was meant? "expires" passes. "renew"
# does not - a changelog says "renewed the contract on 2024-04-01" just as often as a
# plan says "renew by". Weak cues are counted and reported, never silently dropped, and
# --include-weak promotes them.
STRONG_CUES = [
    ("eol", re.compile(r"\beol\b|end[\s\-]of[\s\-](life|support|sale|service)|end of (life|support|sale|service)", re.I)),
    ("expires", re.compile(r"expir(?:e|es|ed|ing|y|ation)", re.I)),
    ("deadline", re.compile(r"\bdeadlines?\b", re.I)),
    ("sunset", re.compile(r"\bsunsets?\b|\bsunsetting\b", re.I)),
    ("deprecated", re.compile(r"deprecat(?:e|es|ed|ing|ion)", re.I)),
    ("retire", re.compile(r"retir(?:e|es|ed|ing|ement)", re.I)),
    ("valid-until", re.compile(r"valid\s+(?:until|through|thru|to)|not\s*after", re.I)),
    ("discontinued", re.compile(r"discontinu(?:e|es|ed|ing|ation)", re.I)),
    ("shutdown", re.compile(r"shut[\s-]?down|shuts down|switch(?:ed|es)? off", re.I)),
    ("last-day", re.compile(r"last day\b|final day\b", re.I)),
    ("期限", re.compile(r"期限|期日|締切|締め切り|移行期限")),
    ("提供終了", re.compile(r"提供終了|サポート終了|販売終了|終了予定|打ち切り|廃止")),
    ("失効", re.compile(r"失効|有効期限|満了")),
]
WEAK_CUES = [
    ("due", re.compile(r"\bdue\b", re.I)),
    ("until", re.compile(r"\buntil\b|\bthrough\b", re.I)),
    ("renew", re.compile(r"renew(?:s|al|ed|ing)?\b", re.I)),
    ("cutoff", re.compile(r"\bcut[\s-]?off\b", re.I)),
    ("migrate", re.compile(r"migrat(?:e|es|ed|ing|ion)", re.I)),
    ("remove", re.compile(r"remov(?:e|es|ed|al)", re.I)),
    ("terminate", re.compile(r"terminat(?:e|es|ed|ion)", re.I)),
    ("更新", re.compile(r"更新|解約|切替|切り替え")),
]

# A long run of token characters next to a date may be a credential, and this tool prints
# the line it matched. `looks_secret` decides; the first draft redacted on length alone and
# turned `key-expiry/trust_store_demo` into `[redacted]`, which is how the rule below got
# its two extra conditions.
SECRETISH = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
SECRET_PREFIX = re.compile(r"^(ghp_|gho_|ghs_|github_pat_|sk-|xox[abprs]-|AKIA|ASIA|AIza|ya29\.)", re.I)
HEXISH = re.compile(r"^[0-9a-f]{32,}$", re.I)


def to_date(kind, groups):
    """Turn one regex match into a real calendar date, or None if it is not one."""
    try:
        if kind == "iso":
            y, _, m, d = groups
            y, m, d = int(y), int(m), int(d)
        elif kind == "jp":
            y, m, d = (int(g) for g in groups)
        elif kind == "mdy":
            mon, d, y = groups
            y, m, d = int(y), MONTHS[mon.lower()], int(d)
        elif kind == "dmy":
            d, mon, y = groups
            y, m, d = int(y), MONTHS[mon.lower()], int(d)
        else:
            return None
        if not 1970 <= y <= 2100:
            return None
        return date(y, m, d)
    except (ValueError, KeyError):
        return None


def dates_in(line):
    """Every calendar date in one line as (start, end, date), de-duplicated by column."""
    found = {}
    for kind, rx in DATE_RES:
        for m in rx.finditer(line):
            d = to_date(kind, m.groups())
            if d is not None:
                found.setdefault(m.start(), (m.end(), d))
    return [(s, e, d) for s, (e, d) in sorted(found.items())]


def cue_in(text):
    """The first cue this text carries, and whether it was a weak one. Used for headings."""
    for name, rx in STRONG_CUES:
        if rx.search(text):
            return name, False
    for name, rx in WEAK_CUES:
        if rx.search(text):
            return name, True
    return None, False


def gap_between(a_start, a_end, b_start, b_end):
    if a_start < b_end and b_start < a_end:
        return 0
    return b_start - a_end if b_start >= a_end else a_start - b_end


def cue_near(line, start, end, near):
    """The cue that sits within `near` characters of the date at [start, end).

    Proximity is the whole of the precision. Without it, one sentence mentioning a
    deadline drags in every unrelated date on the same line - on the tree this tool was
    built in, that was 1,726 rows instead of 300, almost all of them a Japanese document
    that says 期限 once and cites four dates for other reasons.
    """
    best = None                                     # (weak, gap, name)
    for weak, tiers in ((False, STRONG_CUES), (True, WEAK_CUES)):
        for name, rx in tiers:
            for m in rx.finditer(line):
                gap = gap_between(start, end, m.start(), m.end())
                if gap <= near and (best is None or (weak, gap) < (best[0], best[1])):
                    best = (weak, gap, name)
    return (best[2], best[0]) if best else (None, False)


def looks_secret(s):
    """True for a run that is plausibly a credential rather than a path or a sentence."""
    if SECRET_PREFIX.match(s):
        return True
    if HEXISH.match(s):
        return True
    if "/" in s:                      # a path, and a path is not a finding worth hiding
        return False
    digits = sum(c.isdigit() for c in s)
    return digits >= 2 and any(c.isupper() for c in s) and any(c.islower() for c in s)


def redact(text):
    return SECRETISH.sub(lambda m: "[redacted]" if looks_secret(m.group(0)) else m.group(0), text)


def tidy(line, limit=100):
    """The matched line, made printable: markdown furniture off, one space between words."""
    s = re.sub(r"\s+", " ", line).strip()
    s = s.lstrip("#>-*|+ \t").strip()
    s = redact(s)
    if len(s) > limit:
        s = s[:limit - 1] + "…"
    return s


def heading_of(line):
    """The text of a Markdown ATX heading, or None. Used to reach the cue one line up."""
    m = re.match(r"\s{0,3}(#{1,6})\s+(.*)", line)
    return m.group(2).strip() if m else None


def wanted(path):
    if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_SUFFIXES


def excluded(path, patterns):
    s = path.as_posix()
    return any(fnmatch(s, pat) or fnmatch(path.name, pat) for pat in patterns)


def walk(target, exclude=()):
    if target.is_file():
        return [target] if wanted(target) and not excluded(target, exclude) else []
    out = []
    for p in sorted(target.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and wanted(p) and not excluded(p, exclude):
            out.append(p)
    return out


def scan_text(text, where, today, include_weak=False, near=40):
    """Rows for one file's text. `where` is printed as-is; this function never opens it."""
    rows, weak_seen = [], 0
    heading, heading_line = "", -HEADING_REACH
    for n, line in enumerate(text.splitlines(), 1):
        h = heading_of(line)
        if h is not None:
            heading, heading_line = h, n
        for start, end, d in dates_in(line):
            # The cue may sit beside the date, or in the Markdown heading the line sits
            # under - which is how "## End of support" over a bare date gets written. The
            # heading only reaches a few lines: letting it reach the whole section made one
            # heading that says 期限 claim every date below it, 167 rows on one tree.
            name, weak = cue_near(line, start, end, near)
            if name is None and n - heading_line <= HEADING_REACH:
                name, weak = cue_in(heading)
                if name is not None:
                    name += " (heading)"
            if name is None:
                continue
            if weak and not include_weak:
                weak_seen += 1
                continue
            rows.append({"days": (d - today).days, "date": d.isoformat(), "cue": name,
                         "what": tidy(line), "where": "%s:%d" % (where, n), "weak": weak})
    return rows, weak_seen


def read_ledger(path, today):
    """EXPIRY.tsv: the dates no file in the tree contains, typed by hand.

    kind / date / what_stops / how_you_found_out / days_late. Only the first three are
    read here; the last two are for the person filling it in and for the report template.
    """
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) < 2:
            continue
        # The header line needs no special case: "date" is not a date. A row whose second
        # cell says "soon" or "when the invoice lands" is not one either, and is dropped
        # here rather than guessed at.
        got = dates_in(cells[1])
        if not got:
            continue
        d = got[0][2]
        rows.append({"days": (d - today).days, "date": d.isoformat(),
                     "cue": (cells[0] or "ledger")[:24],
                     "what": tidy(cells[2]) if len(cells) > 2 else "",
                     "where": "%s:%d" % (path.name, n), "weak": False})
    return rows


def summarise(rows, within):
    passed = [r for r in rows if r["days"] < 0]
    soon = [r for r in rows if 0 <= r["days"] <= within]
    later = [r for r in rows if r["days"] > within]
    return passed, soon, later


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Find the expiry dates that only exist as prose.")
    ap.add_argument("target", nargs="?", help="file or directory to read")
    ap.add_argument("--within", type=int, default=90, help="window in days (default 90)")
    ap.add_argument("--format", choices=("tsv", "paste", "github"), default="tsv")
    ap.add_argument("--include-weak", action="store_true",
                    help="also count cues like 'due' and 'renew' that a changelog uses too")
    ap.add_argument("--near", type=int, default=40, metavar="CHARS",
                    help="how close the cue must sit to the date on the line (default 40)")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                    help="skip paths matching this glob (repeatable), e.g. --exclude 'test_*'")
    ap.add_argument("--ledger", help="an EXPIRY.tsv of dates no file contains")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing and for asking 'what had passed on'")
    ap.add_argument("--version", action="version", version="prose-expiry " + VERSION)
    a = ap.parse_args(argv)

    if not a.target and not a.ledger:
        ap.print_usage()
        print("nothing to read: give a file, a directory, or --ledger", file=sys.stderr)
        return 2
    today = datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else date.today()

    rows, files_read, skipped, weak_total = [], 0, 0, 0
    if a.target:
        target = Path(a.target)
        if not target.exists():
            print("no such target: %s" % a.target, file=sys.stderr)
            return 2
        for p in walk(target, a.exclude):
            try:
                if p.stat().st_size > MAX_BYTES:
                    skipped += 1
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue
            files_read += 1
            got, weak = scan_text(text, p.as_posix(), today, a.include_weak, a.near)
            rows.extend(got)
            weak_total += weak

    ledger_rows = 0
    if a.ledger:
        lp = Path(a.ledger)
        if not lp.exists():
            print("no such ledger: %s" % a.ledger, file=sys.stderr)
            return 2
        got = read_ledger(lp, today)
        ledger_rows = len(got)
        rows.extend(got)

    if files_read == 0 and ledger_rows == 0:
        print("read nothing: 0 files matched and the ledger added no rows", file=sys.stderr)
        return 2

    rows.sort(key=lambda r: (r["days"], r["where"]))
    passed, soon, later = summarise(rows, a.within)

    if a.format == "paste":
        # Safe to paste somewhere public: counts only. No paths, no file names, no line text.
        print("prose-expiry %s | read %s | files %d | ledger rows %d"
              % (VERSION, today.isoformat(), files_read, ledger_rows))
        print("  %d rows over %d distinct dates" % (len(rows), len({r["date"] for r in rows})))
        print("  already passed : %d%s" % (len(passed),
              "  (oldest by %d days)" % -min(r["days"] for r in passed) if passed else ""))
        print("  within %-8d: %d%s" % (a.within, len(soon),
              "  (soonest in %d days)" % min(r["days"] for r in soon) if soon else ""))
        print("  later          : %d" % len(later))
        by_cue = {}
        for r in rows:
            by_cue[r["cue"]] = by_cue.get(r["cue"], 0) + 1
        if by_cue:
            print("  by cue: " + ", ".join("%s %d" % (k, v) for k, v in
                                           sorted(by_cue.items(), key=lambda kv: -kv[1])))
        if weak_total:
            print("  weak cues not counted: %d  (--include-weak)" % weak_total)
    elif a.format == "github":
        for r in passed + soon:
            f, _, ln = r["where"].rpartition(":")
            print("::warning file=%s,line=%s::%s in %d days (%s, cue: %s)"
                  % (f, ln, r["date"], r["days"], r["what"], r["cue"]))
    else:
        print("# days\tdate\tcue\twhat\twhere")
        for r in rows:
            print("%d\t%s\t%s\t%s\t%s" % (r["days"], r["date"], r["cue"], r["what"], r["where"]))
        print()
        print("%d written expiry dates over %d distinct dates in %d files, read on %s"
              % (len(rows), len({r["date"] for r in rows}), files_read, today.isoformat()))
        print("  already passed : %d%s" % (len(passed),
              "  (oldest by %d days)" % -min(r["days"] for r in passed) if passed else ""))
        print("  within %-8d: %d" % (a.within, len(soon)))
        print("  later          : %d" % len(later))
        if ledger_rows:
            print("  of which from the ledger: %d" % ledger_rows)
        if weak_total:
            print("  weak cues not counted: %d  (--include-weak to see them)" % weak_total)
        if skipped:
            print("  files skipped (too big or unreadable): %d" % skipped)
        print("  a date nobody wrote down is not here. That is what EXPIRY.tsv is for.")

    return 1 if (passed or soon) else 0


if __name__ == "__main__":
    sys.exit(main())
