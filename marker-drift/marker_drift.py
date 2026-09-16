# -*- coding: utf-8 -*-
"""marker-drift - the lines your gate refuses to see, and the one character that did it.

    python marker_drift.py --marker "(unit {n})" --git .
    python marker_drift.py --marker "{w}-{n}" --file CHANGELOG.md
    git log --pretty=%s | python marker_drift.py --marker "(unit {n})"

Somewhere in a pipeline there is a gate that reads a marker out of a line somebody typed:
a ticket id in a commit subject, a release tag, a conventional-commit prefix, a run
number an agent is told to write. The gate matches the marker exactly, because that is
what `==` and a plain regex do. So a line with the space left out is not a near miss to
the gate. It is a line with no marker, and the work behind it is counted as not done.

This reads the same lines the gate reads, matches the marker exactly, and then - only for
the lines that did *not* match - relaxes one typographic axis at a time to see whether the
line would have matched a slightly kinder gate. It reports which axis did it. Five axes,
all of them things a keyboard produces by accident: full-width characters, bracket shapes,
dash shapes, letter case, and whitespace.

It cannot see a line where the marker was never written at all. That is a different
failure with the same symptom, and `--list-missing` prints those lines so a human can
tell the two apart. Nothing here guesses intent.

Standard library only. No network. Exit 0 = no drift, 1 = drift found,
2 = the scan did not happen.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 8_000_000
MAX_LINE = 4_000

# --- the five axes -----------------------------------------------------------------
# Every map below is one character for one character, so an offset computed on the
# normalised line still points at the same place in the original line. Whitespace is the
# exception: it deletes, and the index map carries the offsets instead.

_WIDTH = {}
for _a, _b in ((0xFF10, ord("0")), (0xFF21, ord("A")), (0xFF41, ord("a"))):
    for _i in range(10 if _a == 0xFF10 else 26):
        _WIDTH[chr(_a + _i)] = chr(_b + _i)
# Full-width punctuation and the two Japanese sentence marks. Brackets and dashes are
# deliberately not here: they get their own axis, so a report can name them separately.
_WIDTH.update({
    "：": ":", "；": ";", "，": ",", "．": ".", "！": "!", "？": "?", "、": ",", "。": ".",
    "＃": "#", "＠": "@", "＆": "&", "＊": "*", "＋": "+", "＝": "=", "／": "/",
    "＼": "\\", "｜": "|", "＿": "_", "％": "%", "＄": "$", "＂": '"', "＇": "'",
    "｀": "`", "＾": "^", "～": "~",
})

_BRACKET = {
    "（": "(", "）": ")", "［": "[", "］": "]", "｛": "{", "｝": "}",
    "〔": "[", "〕": "]", "【": "[", "】": "]", "〈": "<", "〉": ">",
    "《": "<", "》": ">", "＜": "<", "＞": ">",
}

# U+30FC is the Japanese long-vowel mark. It is not a dash, but it sits where a dash sits
# on a Japanese keyboard, which is exactly how it ends up inside an identifier.
_DASH = {c: "-" for c in "‐‑‒–—―−－ー⁃﹘﹣"}

AXES = ("width", "bracket", "dash", "case", "space")
AXIS_HELP = {
    "width": "full-width letters, digits and punctuation -> ASCII",
    "bracket": "bracket shapes -> ASCII ( ) [ ] { } < >",
    "dash": "dash and long-vowel shapes -> ASCII -",
    "case": "ASCII upper case -> lower case",
    "space": "any run of whitespace in the marker, including none at all",
}

# ASCII on purpose. Python's \d matches "３" and \w matches "単", so a gate written with
# \d already lets full-width digits through - and this tool exists to show what a gate
# turns away. The strict side has to be the strict one.
PLACEHOLDERS = {
    "{n}": r"[0-9]+",
    "{w}": r"[A-Za-z0-9_]+",
    "{any}": r".+?",
}
_SPACE_RX = r"\s*"


def normalize(text: str, axes) -> tuple[str, list[int]]:
    """Return (normalised text, index map). index[i] is the offset in `text` of out[i].

    The `space` axis is not here: it relaxes the marker rather than editing the line, so
    that "where the line starts" keeps its meaning. See compile_template.
    """
    axes = frozenset(axes)
    out: list[str] = []
    idx: list[int] = []
    do_width = "width" in axes
    do_bracket = "bracket" in axes
    do_dash = "dash" in axes
    do_case = "case" in axes
    for i, ch in enumerate(text):
        if do_width:
            ch = _WIDTH.get(ch, ch)
        if do_bracket:
            ch = _BRACKET.get(ch, ch)
        if do_dash:
            ch = _DASH.get(ch, ch)
        if do_case and "A" <= ch <= "Z":
            ch = ch.lower()
        out.append(ch)
        idx.append(i)
    return "".join(out), idx


def split_template(template: str) -> list:
    """Split "(unit {n})" into ['(unit ', ('n',), ')']. Unknown {...} stays literal."""
    parts: list = []
    pos = 0
    for m in re.finditer(r"\{[a-z]+\}", template):
        if m.group(0) not in PLACEHOLDERS:
            continue
        if m.start() > pos:
            parts.append(template[pos:m.start()])
        parts.append((m.group(0),))
        pos = m.end()
    if pos < len(template):
        parts.append(template[pos:])
    return parts


def compile_template(template: str, axes, at: str = "anywhere") -> re.Pattern:
    """Compile the marker, with the same axes relaxed on the pattern side.

    The literal parts of the template are normalised exactly like the line is. The `space`
    axis works differently: every run of whitespace in the marker becomes "any amount of
    whitespace, including none", and whitespace is allowed on either side of a
    placeholder. The line itself is left alone, so `--at start` still means the head of
    the line and not the head of the line with its words pushed together.
    """
    parts = split_template(template)
    if not parts:
        raise ValueError("the marker is empty")
    loose = "space" in frozenset(axes)
    chunks = []
    for part in parts:
        if isinstance(part, tuple):
            chunks.append(_SPACE_RX + PLACEHOLDERS[part[0]] + _SPACE_RX if loose
                          else PLACEHOLDERS[part[0]])
        else:
            norm, _ = normalize(part, axes)
            esc = re.escape(norm)
            if loose:
                esc = re.sub(r"(?:\\?\s)+", lambda _m: _SPACE_RX, esc)
            chunks.append(esc)
    body = re.sub(r"(?:\\s\*)+", lambda _m: _SPACE_RX, "".join(chunks))
    if not body or not body.replace(_SPACE_RX, ""):
        # Nothing is left but whitespace: a marker of only spaces, relaxed. Matching
        # everything here would call every line a drift.
        return re.compile(r"(?!)")
    if at == "start":
        body = ("^" + _SPACE_RX if loose else "^") + body
    elif at == "end":
        body = body + (_SPACE_RX + "$" if loose else "$")
    return re.compile(body)


def analyse(line: str, template: str, at: str = "anywhere") -> dict:
    """Classify one line: exact / drift / none."""
    strict = compile_template(template, (), at)
    m = strict.search(line)
    if m:
        return {"kind": "exact", "span": (m.start(), m.end()), "axes": (), "found": m.group(0)}

    everything = frozenset(AXES)
    norm, idx = normalize(line, everything)
    if not compile_template(template, everything, at).search(norm):
        return {"kind": "none", "span": None, "axes": None, "found": None}

    # Smallest set of axes that still lets the line through: drop one, keep the drop if it
    # still matches. Fixed order, so the answer does not depend on set iteration order.
    keep = set(everything)
    for axis in AXES:
        trial = keep - {axis}
        cand, _ = normalize(line, trial)
        if compile_template(template, trial, at).search(cand):
            keep = trial

    norm, idx = normalize(line, keep)
    m = compile_template(template, keep, at).search(norm)
    start = idx[m.start()] if m.end() > m.start() else idx[m.start()]
    end = idx[m.end() - 1] + 1 if m.end() > m.start() else start
    return {
        "kind": "drift",
        "span": (start, end),
        "axes": tuple(a for a in AXES if a in keep),
        "found": line[start:end],
    }


def scan_lines(lines, template: str, at: str = "anywhere") -> dict:
    rows = []
    missing = []
    exact = 0
    for no, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if len(line) > MAX_LINE:
            line = line[:MAX_LINE]
        if not line.strip():
            continue
        r = analyse(line, template, at)
        if r["kind"] == "exact":
            exact += 1
        elif r["kind"] == "drift":
            rows.append({"line_no": no, "line": line, **r})
        else:
            missing.append({"line_no": no, "line": line})
    return {"read": exact + len(rows) + len(missing), "exact": exact,
            "drift": rows, "missing": missing}


# --- input -------------------------------------------------------------------------

def git_subjects(repo: str, max_count: int | None) -> list[str]:
    cmd = ["git", "-C", repo, "log", "--pretty=%s", "--no-color"]
    if max_count:
        cmd += ["-n", str(max_count)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError("could not run git: %s" % e)
    if p.returncode != 0:
        raise RuntimeError("git log failed: %s" % (p.stderr or "").strip()[:200])
    return [ln for ln in (p.stdout or "").splitlines()]


def file_lines(paths) -> list[str]:
    out: list[str] = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise RuntimeError("not a file: %s" % p)
        if path.stat().st_size > MAX_BYTES:
            raise RuntimeError("file is larger than %d bytes: %s" % (MAX_BYTES, p))
        out.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return out


# --- output ----------------------------------------------------------------------

def caret_line(line: str, span) -> str:
    start, end = span
    width = sum(2 if ord(c) > 0x2E80 else 1 for c in line[:start])
    inner = max(1, sum(2 if ord(c) > 0x2E80 else 1 for c in line[start:end]))
    return " " * width + "^" * inner


def report(result: dict, template: str, out, show_missing: int = 0, fmt: str = "text") -> None:
    rows = result["drift"]
    if fmt == "tsv":
        out.write("line_no\taxes\tfound\tline\n")
        for r in rows:
            out.write("%d\t%s\t%s\t%s\n" % (r["line_no"], ",".join(r["axes"]),
                                            r["found"], r["line"]))
        return

    out.write("marker      %s\n" % template)
    out.write("lines read  %d\n" % result["read"])
    out.write("exact       %d\n" % result["exact"])
    out.write("drift       %d%s\n" % (len(rows), "" if rows else "  (the gate lost nothing)"))
    out.write("no marker   %d\n" % len(result["missing"]))
    if rows:
        by_axis: dict[str, int] = {}
        for r in rows:
            by_axis[",".join(r["axes"])] = by_axis.get(",".join(r["axes"]), 0) + 1
        out.write("\nrelaxing one axis would have admitted:\n")
        for axes, n in sorted(by_axis.items(), key=lambda kv: (-kv[1], kv[0])):
            out.write("  %-22s %d   (%s)\n" % (
                axes, n, "; ".join(AXIS_HELP[a] for a in axes.split(","))))
        out.write("\n")
        for r in rows:
            out.write("  line %d\n    %s\n    %s\n    found %r, relaxing %s\n" % (
                r["line_no"], r["line"], caret_line(r["line"], r["span"]),
                r["found"], ",".join(r["axes"])))
    if show_missing and result["missing"]:
        out.write("\nno marker at all (first %d of %d) - this tool cannot tell you whether\n"
                  "they should have had one:\n" % (
                      min(show_missing, len(result["missing"])), len(result["missing"])))
        for r in result["missing"][:show_missing]:
            out.write("  line %d  %s\n" % (r["line_no"], r["line"][:120]))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Find the lines a strict marker gate silently drops.")
    p.add_argument("--marker", required=True,
                   help="the marker as the gate spells it, e.g. \"(unit {n})\". "
                        "Placeholders: {n} digits, {w} word, {any} anything")
    p.add_argument("--git", nargs="?", const=".", metavar="REPO",
                   help="read commit subjects from a git repository (default .)")
    p.add_argument("--file", nargs="+", metavar="PATH", help="read lines from files")
    p.add_argument("--max", type=int, default=None, metavar="N",
                   help="with --git, read only the last N commits")
    p.add_argument("--at", choices=("anywhere", "start", "end"), default="anywhere",
                   help="where the marker must sit on the line (default anywhere). "
                        "Use start or end when the gate anchors: it also keeps a marker "
                        "quoted in the middle of a sentence out of the report")
    p.add_argument("--list-missing", type=int, default=0, metavar="N",
                   help="also print N lines that carry no marker at all")
    p.add_argument("--format", choices=("text", "tsv"), default="text")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        compile_template(args.marker, ())
    except (ValueError, re.error) as e:
        sys.stderr.write("marker-drift: bad marker: %s\n" % e)
        return 2

    try:
        if args.file:
            lines = file_lines(args.file)
        elif args.git:
            lines = git_subjects(args.git, args.max)
        elif not sys.stdin.isatty():
            lines = sys.stdin.read().splitlines()
        else:
            sys.stderr.write("marker-drift: nothing to read. Use --git, --file or a pipe.\n")
            return 2
    except RuntimeError as e:
        sys.stderr.write("marker-drift: %s\n" % e)
        return 2

    result = scan_lines(lines, args.marker, args.at)
    if result["read"] == 0:
        sys.stderr.write("marker-drift: read 0 lines. Not calling that a pass.\n")
        return 2
    report(result, args.marker, sys.stdout, args.list_missing, args.format)
    return 1 if result["drift"] else 0


if __name__ == "__main__":
    sys.exit(main())
