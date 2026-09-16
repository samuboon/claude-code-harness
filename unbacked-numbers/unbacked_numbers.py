# -*- coding: utf-8 -*-
"""unbacked-numbers - the numbers in a report that nothing in the report backs.

    python unbacked_numbers.py REPORT.md
    python unbacked_numbers.py docs/ --min 10 --drift 5
    python unbacked_numbers.py . --format paste

A report - written by a person or by a model - is full of numbers. Some of them sit next
to the quote they came from. The rest were typed from memory, and a reader cannot tell
the two apart by looking. This walks a file, splits it into *quoted evidence* (fenced
blocks, block quotes, inline code, "..." and the Japanese quote marks) and *prose*, and
lists every number in the prose that appears in no quote in the same file.

It has no idea whether a number is true. It only knows whether the document carries the
evidence for it, which is a different and much cheaper question.

Standard library only. No network. Exit 0 = nothing unbacked, 1 = findings,
2 = the scan did not happen.
"""
from __future__ import annotations

import argparse
import bisect
import fnmatch
import re
import sys
from pathlib import Path

MAX_BYTES = 2_000_000
# Below this, a 5% window is one unit wide: 19 next to a quoted 20 is not evidence of a
# mistyped number, it is arithmetic. Small numbers are reported, but never as near-misses.
NEAR_MISS_FLOOR = 100
SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".org"}
NEVER_NAMES = {".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
NEVER_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".jks"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}

# Full-width digits and punctuation -> ASCII. One character for one character, so every
# offset computed after this still points at the same place in the original file.
FULLWIDTH = {ord(a): ord(b) for a, b in zip("０１２３４５６７８９，．％", "0123456789,.%")}

FENCE = re.compile(r"^[ \t]*(```+|~~~+)")
# A number alone in backticks is typography, not a citation: `184` in a sentence is the
# writer emphasising their own claim. Inline code counts as a quote only when it contains
# something besides digits and punctuation - `files=184`, `notAfter`, a command.
DIGITS_ONLY = re.compile(r"^[\s\d.,%+\-–—/:]*$")
INLINE_EVIDENCE = [
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\"[^\"\n]{1,400}\""),
    re.compile(r"“[^”\n]{1,400}”"),      # “ ”
    re.compile(r"「[^」\n]{1,400}」"),      # 「 」
    re.compile(r"『[^』\n]{1,400}』"),      # 『 』
]

UNIT_AFTER = re.compile(
    r"\s{0,2}(%|件|本|回|人|円|分|時間|日|週|枚|個|点|"
    r"ヶ月|か月|名|台|冊|行|文字|字|倍|割|"
    r"kB|KB|MB|GB|TB|px|ms|hours?|minutes?|days?|weeks?|months?|years?|times|files?|tests?|rows?|"
    r"lines?|items?|stars?|people|users?|cases?|points?|seconds?)(?![A-Za-z])",
    re.I,
)
CURRENCY_BEFORE = re.compile(r"[¥$€£￥]\s{0,1}$")
MAGNITUDE = {"万": 10_000, "億": 100_000_000}   # 万 億

URL_ON_LINE = re.compile(r"https?://")

# Things that look like numbers but are names: dates, times, versions, section numbers,
# issue refs, hashes, paths, identifiers. Masked out of the prose before extraction.
IDENTIFIER_MASKS = [
    re.compile(r"https?://\S+"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{4}/\d{1,2}/\d{1,2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    re.compile(r"(?<!\d)\d{1,2}-\d{1,2}(?!\d)"),                       # 09-16
    re.compile(r"\d{4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"),
    re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)"),
    re.compile(r"\bv\.?\s?\d+(?:\.\d+)*\b", re.I),
    re.compile(r"(?<!\d)\d+\.\d+\.\d+(?!\d)"),                         # semver
    re.compile(r"§\s*\d+(?:[.\-]\d+)*"),                          # §2
    re.compile(r"#\d+"),
    re.compile(r"\bNo\.\s*\d+", re.I),
    re.compile(r"第\s*\d+"),                                       # 第3
    re.compile(r"\[\^\d+\]"),
    re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"),               # commit hashes
    re.compile(r"\S*[\\/]\S*"),                                        # paths
    re.compile(r"^[ \t]*\d+[.)]\s", re.M),                             # ordered list marker
    re.compile(r"\b[A-Za-z]+[-_]?\d+[A-Za-z]*\b"),                     # IMP-45, K1, x5, GPT5
]
BARE_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)"
                       r"(?!\s{0,2}(?:%|件|本|回|人|円|枚|個|点|行|字))")

NUMBER = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


# ---------------------------------------------------------------- text splitting

def normalize(text: str) -> str:
    return text.translate(FULLWIDTH)


def evidence_spans(text: str):
    """Offsets of everything a reader would accept as quoted from somewhere else."""
    spans = []
    in_fence = False
    mark = ""
    off = 0
    for line in text.splitlines(keepends=True):
        m = FENCE.match(line)
        if m:
            this = m.group(1)[:3]
            if not in_fence:
                in_fence, mark = True, this
            elif this == mark:
                in_fence = False
            spans.append((off, off + len(line)))
            off += len(line)
            continue
        if in_fence or line.lstrip().startswith(">"):
            spans.append((off, off + len(line)))
            off += len(line)
            continue
        for rx in INLINE_EVIDENCE:
            for mm in rx.finditer(line):
                if DIGITS_ONLY.match(mm.group(0)[1:-1]):
                    continue
                spans.append((off + mm.start(), off + mm.end()))
        off += len(line)
    return spans


def blank_out(text: str, spans) -> str:
    """Replace the spans with spaces, keeping every other offset where it was."""
    out = list(text)
    for s, e in spans:
        for i in range(max(s, 0), min(e, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def keep_only(text: str, spans) -> str:
    out = ["\n" if c == "\n" else " " for c in text]
    for s, e in spans:
        for i in range(max(s, 0), min(e, len(out))):
            out[i] = text[i]
    return "".join(out)


def mask_identifiers(text: str, include_years: bool) -> str:
    masks = list(IDENTIFIER_MASKS)
    if not include_years:
        masks.append(BARE_YEAR)
    for rx in masks:
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


# ---------------------------------------------------------------- numbers

def numbers_in(text: str, offset_base: int = 0, both: bool = True):
    """[(value, start_offset, raw_text, has_unit)] for every number in `text`.

    `both=True` (used on the quoted side) records 3万 as both 3 and 30000, so either
    spelling in the prose is backed. `both=False` (the prose side) records only 30000,
    because the bare 3 in 3万 is not a claim anybody made.
    """
    found = []
    for m in NUMBER.finditer(text):
        whole, frac = m.group(1), m.group(2)
        try:
            value = float(whole.replace(",", "") + ("." + frac if frac else ""))
        except ValueError:
            continue
        tail = text[m.end():m.end() + 8]
        head = text[max(0, m.start() - 2):m.start()]
        mag = MAGNITUDE.get(tail[:1]) if tail else None
        has_unit = bool(
            frac
            or "," in whole
            or mag
            or UNIT_AFTER.match(tail)
            or CURRENCY_BEFORE.search(head)
        )
        if not mag or both:
            found.append((value, offset_base + m.start(), m.group(0), has_unit))
        if mag:
            found.append((value * mag, offset_base + m.start(), m.group(0) + tail[:1], True))
    return found


def line_index(text: str):
    starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            starts.append(i + 1)
    return starts


def line_of(starts, offset: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def nearest(value: float, quoted_sorted):
    """The quoted number closest to `value`, and the relative gap between them."""
    if not quoted_sorted:
        return None, 1.0
    i = bisect.bisect_left(quoted_sorted, value)
    best, gap = None, 1.0
    for j in (i - 1, i):
        if 0 <= j < len(quoted_sorted):
            q = quoted_sorted[j]
            scale = max(abs(q), abs(value))
            g = 1.0 if scale == 0 else abs(q - value) / scale
            if g < gap:
                best, gap = q, g
    return best, gap


def looks_like_secret(token: str) -> bool:
    s = token.strip("\"'`,.;:()[]{}*|")
    if len(s) < 24:
        return False
    if "/" in s:                      # a path, and a path is not a finding worth hiding
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", s):   # prose, not a token
        return False
    digits = sum(c.isdigit() for c in s)
    return digits >= 2 and any(c.isupper() for c in s) and any(c.islower() for c in s)


def redact(line: str) -> str:
    return " ".join("[redacted]" if looks_like_secret(t) else t for t in line.split(" "))


def fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else ("%g" % value)


# ---------------------------------------------------------------- scan

def scan_text(text: str, path: str, min_value: float, drift: float,
              strict: bool, include_years: bool):
    """(rows, stats) for one document."""
    text = normalize(text)
    spans = evidence_spans(text)
    evidence = keep_only(text, spans)
    quoted = sorted({v for v, _o, _r, _u in numbers_in(evidence)})
    stats = {"below_min": 0, "no_evidence": 0}

    if not quoted and not strict:
        stats["no_evidence"] = 1
        return [], stats

    prose = mask_identifiers(blank_out(text, spans), include_years)
    starts = line_index(text)
    lines = text.splitlines()
    rows = []
    for value, offset, raw, has_unit in numbers_in(prose, both=False):
        if value in quoted:
            continue
        if not has_unit and value == int(value) and value < min_value:
            stats["below_min"] += 1
            continue
        n = line_of(starts, offset)
        line_text = lines[n - 1].strip() if n - 1 < len(lines) else ""
        near, gap = nearest(value, quoted)
        if near is not None and 0 < gap <= drift and max(abs(near), abs(value)) >= NEAR_MISS_FLOOR:
            kind, note = "near-miss", fmt(near)
        elif URL_ON_LINE.search(line_text):
            kind, note = "link-only", ""
        else:
            kind, note = "unbacked", ""
        rows.append({"kind": kind, "value": value, "raw": raw, "note": note,
                     "path": path, "line": n, "text": line_text})
    return rows, stats


def walk(target: Path, excludes):
    if target.is_file():
        candidates = [target]
    else:
        candidates = sorted(p for p in target.rglob("*") if p.is_file())
    for p in candidates:
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in NEVER_NAMES or p.suffix.lower() in NEVER_SUFFIXES:
            continue
        if p.suffix.lower() not in SUFFIXES:
            continue
        rel = p.as_posix()
        if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(p.name, g) for g in excludes):
            continue
        yield p


ORDER = {"near-miss": 0, "unbacked": 1, "link-only": 2}


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="numbers in the prose that no quote in the same file backs")
    ap.add_argument("target", help="a file or a directory")
    ap.add_argument("--min", type=float, default=10.0,
                    help="ignore bare integers below this (numbers with a unit are always kept). default 10")
    ap.add_argument("--drift", type=float, default=5.0,
                    help="percent: how close a quoted number must be to count as a near-miss. default 5")
    ap.add_argument("--strict", action="store_true",
                    help="also scan files that quote nothing at all")
    ap.add_argument("--include-years", action="store_true",
                    help="treat a bare 1900-2100 as a number rather than a year")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    ap.add_argument("--format", choices=["tsv", "paste", "github"], default="tsv")
    args = ap.parse_args(argv)
    try:                                  # a cp932 console must not crash the scan
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    target = Path(args.target)
    if not target.exists():
        print("nothing to scan at %s" % target, file=sys.stderr)
        return 2

    rows, files_read, below_min, no_evidence, skipped = [], 0, 0, 0, 0
    for p in walk(target, args.exclude):
        try:
            if p.stat().st_size > MAX_BYTES:
                skipped += 1
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        files_read += 1
        r, stats = scan_text(text, p.as_posix(), args.min, args.drift / 100.0,
                             args.strict, args.include_years)
        rows.extend(r)
        below_min += stats["below_min"]
        no_evidence += stats["no_evidence"]

    if files_read == 0:
        print("read 0 files - a clean report over an empty scan is worse than an error", file=sys.stderr)
        return 2

    rows.sort(key=lambda r: (ORDER[r["kind"]], r["path"], r["line"], r["value"]))
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in ORDER}

    if args.format == "github":
        for r in rows:
            msg = "%s %s is not quoted anywhere in this file" % (r["kind"], r["raw"])
            if r["note"]:
                msg += " (the closest quoted number is %s)" % r["note"]
            print("::warning file=%s,line=%d::%s" % (r["path"], r["line"], msg))
    elif args.format == "tsv":
        if rows:
            print("kind\tnumber\tclosest quoted\twhere\tline")
            for r in rows:
                print("%s\t%s\t%s\t%s:%d\t%s"
                      % (r["kind"], r["raw"], r["note"] or "-", r["path"], r["line"],
                         redact(r["text"])[:160]))
            print()

    print("%d unbacked numbers in %d files" % (len(rows), files_read))
    tail = "  (--strict to scan them)" if no_evidence and not args.strict else ""
    summary = [
        ("near-miss (a quoted number is within %g%%)" % args.drift, "%d" % counts["near-miss"]),
        ("unbacked", "%d" % counts["unbacked"]),
        ("link-only (a URL on the line, no quote)", "%d" % counts["link-only"]),
        ("below --min %g (not counted)" % args.min, "%d" % below_min),
        ("files that quote nothing at all", "%d%s" % (no_evidence, tail)),
    ]
    if skipped:
        summary.append(("unread (too large or unreadable)", "%d" % skipped))
    width = max(len(label) for label, _ in summary)
    for label, count in summary:
        print("  %-*s : %s" % (width, label, count))
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(run())
