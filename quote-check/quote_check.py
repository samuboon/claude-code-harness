# -*- coding: utf-8 -*-
"""quote-check - the quote is in the document, the source is cited, and one invisible character is different.

    python quote_check.py report.md --sources pages/
    python quote_check.py report.md --source pages/terms.txt --strict
    python quote_check.py report.md --sources pages/ --blockquote --json

A model writes a report and puts the source's own words in quotation marks. Checking that
by hand does not scale, so it gets checked with `quote in source_text`, which answers yes
or no. No is the useless answer: a quote can fail that test because it was invented, and
it can fail because the page had an ideographic space where the report has an ASCII one.
Those two need opposite responses and the check cannot tell them apart, so every no costs
a human read.

This matches the quote exactly first. Only for the quotes that did *not* match does it
relax one typographic axis at a time - invisible characters, whitespace, quotation-mark
shapes, dash and ellipsis shapes, character width, letter case - and report which axis
did it. What survives all six is a difference in the letters and digits themselves, and
that one is printed with the code point of the first character that differs.

It cannot tell you whether the source page is honest, whether the quote was cut in a way
that inverts its meaning, or whether the sentence you quoted is the sentence that matters.
Nothing here reads meaning. It reads characters.

Standard library only. No network. Exit 0 = every quote is verbatim (formatting
differences are printed and, without --strict, allowed), 1 = a quote differs in substance
or is not in any source, 2 = the check did not happen.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

AXES = ("invisible", "space", "quotes", "punct", "width", "case")

INVISIBLE = "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad"
SPACE = "\t\n\r\f\v \u00a0\u3000\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f"
QUOTE_MAP = {"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"', "\uff02": '"',
             "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "\uff07": "'"}
PUNCT_MAP = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
             "\u2212": "-", "\u2500": "-", "\ufe63": "-", "\uff0d": "-",
             "\u2026": "...", "\u22ef": "...", "\u30fb": "\u30fb"}

FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r"\u300c([^\u300c\u300d]*(?:\u300c[^\u300c\u300d]*\u300d[^\u300c\u300d]*)*)\u300d"
                    r"|\u300e([^\u300e\u300f]+)\u300f"
                    r"|\u201c([^\u201c\u201d]+)\u201d"
                    r'|"([^"\n]+)"')


def read_text(path):
    """Read a file as UTF-8 and normalise it to NFC.

    NFC is applied to both sides at load time on purpose: a quote that differs from its
    source only by Unicode decomposition is the same quote, and saying so here keeps every
    character position below in one coordinate system.
    """
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ValueError("binary file")
    return unicodedata.normalize("NFC", data.decode("utf-8", errors="strict")).replace("\r\n", "\n")


def normalize(s, axes):
    """Return (normalised text, index map). index map[i] = position of i in the input."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(s):
        if "invisible" in axes and ch in INVISIBLE:
            continue
        if "space" in axes and ch in SPACE:
            if not prev_space:
                out.append(" ")
                idx.append(i)
                prev_space = True
            continue
        prev_space = False
        c = ch
        if "quotes" in axes:
            c = QUOTE_MAP.get(c, c)
        if "punct" in axes:
            c = PUNCT_MAP.get(c, c)
        if "width" in axes:
            c = unicodedata.normalize("NFKC", c)
        if "case" in axes:
            c = c.casefold()
        for cc in c:
            out.append(cc)
            idx.append(i)
    if "space" in axes:
        while out and out[0] == " ":
            out.pop(0)
            idx.pop(0)
        while out and out[-1] == " ":
            out.pop()
            idx.pop()
    return "".join(out), idx


def extract(text, min_length, blockquote):
    """Pull quoted strings out of a document. Returns [(line number, quote)]."""
    found, in_fence, block = [], False, None
    for n, line in enumerate(text.split("\n"), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if blockquote:
            if line.lstrip().startswith(">"):
                body = line.lstrip()[1:].lstrip()
                if block is None:
                    block = [n, []]
                block[1].append(body)
                continue
            if block is not None:
                joined = " ".join(x for x in block[1] if x).strip()
                if len(joined) >= min_length:
                    found.append((block[0], joined))
                block = None
        for m in QUOTED.finditer(INLINE_CODE.sub(" ", line)):
            q = next(g for g in m.groups() if g is not None)
            if len(q.strip()) >= min_length:
                found.append((n, q.strip()))
    if block is not None:
        joined = " ".join(x for x in block[1] if x).strip()
        if len(joined) >= min_length:
            found.append((block[0], joined))
    return found


CONTROL_NAMES = {"\n": "LINE FEED", "\r": "CARRIAGE RETURN", "\t": "CHARACTER TABULATION",
                 "\f": "FORM FEED", "\v": "LINE TABULATION", "\x00": "NULL"}


def describe(ch):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        # the control characters have no Unicode name, and a line break is the difference
        # that turns up most often in text copied out of a web page
        name = CONTROL_NAMES.get(ch, "unnamed")
    shown = ch if ch.isprintable() and not ch.isspace() else repr(ch)[1:-1]
    return "'%s' (U+%04X %s)" % (shown, ord(ch), name)


def first_difference(a, b):
    """Index of the first position where a and b differ, or None."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def locate(quote, source, axes):
    """Find the quote in the source under `axes`. Returns the raw source slice, or None."""
    qn, _ = normalize(quote, axes)
    sn, smap = normalize(source, axes)
    if not qn:
        return None
    pos = sn.find(qn)
    if pos < 0:
        return None
    start = smap[pos]
    end = smap[pos + len(qn) - 1] + 1
    return source[start:end]


def anchor_window(quote, source):
    """The stretch of source that looks most like the quote, for reporting a real miss."""
    axes = AXES
    qn, _ = normalize(quote, axes)
    sn, smap = normalize(source, axes)
    if not qn or not sn:
        return None
    size = max(4, min(12, len(qn) // 3))
    best = None
    for i in range(0, max(1, len(qn) - size + 1)):
        pos = sn.find(qn[i:i + size])
        if pos < 0:
            continue
        start = max(0, pos - i)
        end = min(len(sn), start + len(qn))
        same = sum(1 for x, y in zip(sn[start:end], qn) if x == y)
        score = same / max(len(qn), 1)
        if best is None or score > best[0]:
            best = (score, start, end)
    if best is None:
        return None
    _, start, end = best
    raw = source[smap[start]:smap[min(end, len(smap)) - 1] + 1]
    return best[0], raw, sn[start:end], qn


def check_one(quote, sources):
    """Classify one quote against every source. Returns a finding dict."""
    for name, text in sources:
        if quote in text:
            return {"verdict": "exact", "source": name}
    for axis in AXES:
        for name, text in sources:
            raw = locate(quote, text, (axis,))
            if raw is not None:
                return {"verdict": "formatting", "axis": axis, "source": name, "found": raw}
    for name, text in sources:
        raw = locate(quote, text, AXES)
        if raw is not None:
            return {"verdict": "formatting", "axis": "multiple", "source": name, "found": raw}
    best = None
    for name, text in sources:
        got = anchor_window(quote, text)
        if got and (best is None or got[0] > best[1][0]):
            best = (name, got)
    if best is None:
        return {"verdict": "unfound"}
    name, (score, raw, sn_slice, qn) = best
    return {"verdict": "substantive", "source": name, "found": raw, "score": round(score, 3),
            "at": first_difference(qn, sn_slice), "a": qn, "b": sn_slice}


def oneline(s):
    """Show a stretch of text on one line: a line break in a source is a difference."""
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def report(findings, out):
    counts = {"exact": 0, "formatting": 0, "substantive": 0, "unfound": 0}
    for f in findings:
        counts[f["verdict"]] += 1
    out.write("quotes      %d\n" % len(findings))
    for k in ("exact", "formatting", "substantive", "unfound"):
        out.write("%-11s %d\n" % (k, counts[k]))
    for f in findings:
        if f["verdict"] == "exact":
            continue
        out.write("\n%s\n" % {"formatting": "formatting difference (%s)" % f.get("axis", ""),
                              "substantive": "substantive difference",
                              "unfound": "not found in any source"}[f["verdict"]])
        out.write("  %s line %d\n" % (f["doc"], f["line"]))
        out.write("    quote   %s\n" % oneline(f["quote"]))
        if f["verdict"] == "unfound":
            out.write("    no stretch of any source resembles it\n")
            continue
        out.write("    source  %s%s\n" % (f["source"],
                                          "" if f["verdict"] == "formatting" else ", closest %.0f%%" % (f["score"] * 100)))
        out.write("    found   %s\n" % oneline(f["found"]))
        if f["verdict"] == "formatting":
            i = first_difference(f["quote"], f["found"])
            if i is not None and i < len(f["quote"]) and i < len(f["found"]):
                out.write("    first difference at character %d: quote %s vs source %s\n"
                          % (i + 1, describe(f["quote"][i]), describe(f["found"][i])))
            out.write("    %s\n" % ("identical once every axis is relaxed at once, so more than one differs"
                                    if f["axis"] == "multiple" else
                                    "identical once %s is relaxed; the letters and digits are the same" % f["axis"]))
        else:
            i = f["at"]
            a, b = f["a"], f["b"]
            if i is not None and i < len(a) and i < len(b):
                out.write("    first difference at character %d: quote %s vs source %s\n"
                          % (i + 1, describe(a[i]), describe(b[i])))
            else:
                out.write("    the quote runs past the matching stretch of the source\n")
    return counts


def main(argv=None):
    p = argparse.ArgumentParser(description="check that quoted text appears verbatim in its source")
    p.add_argument("docs", nargs="+", help="documents containing quotations")
    p.add_argument("--source", action="append", default=[], help="a source file (repeatable)")
    p.add_argument("--sources", action="append", default=[], help="a directory of source files")
    p.add_argument("--min-length", type=int, default=8, help="shortest quote to check (default 8)")
    p.add_argument("--blockquote", action="store_true", help="also treat markdown blockquotes as quotes")
    p.add_argument("--strict", action="store_true", help="formatting differences fail too")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)

    sources = []
    paths = [Path(s) for s in a.source]
    for d in a.sources:
        paths.extend(sorted(x for x in Path(d).rglob("*") if x.is_file()))
    for path in paths:
        try:
            sources.append((str(path), read_text(path)))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            if path in [Path(s) for s in a.source]:
                sys.stderr.write("cannot read source %s: %s\n" % (path, e))
                return 2
    if not sources:
        sys.stderr.write("no readable sources; pass --source FILE or --sources DIR\n")
        return 2

    findings = []
    for doc in a.docs:
        try:
            text = read_text(Path(doc))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            sys.stderr.write("cannot read document %s: %s\n" % (doc, e))
            return 2
        for line, quote in extract(text, a.min_length, a.blockquote):
            f = check_one(quote, sources)
            f.update({"doc": doc, "line": line, "quote": quote})
            findings.append(f)

    if a.json:
        print(json.dumps([{k: v for k, v in f.items() if k not in ("a", "b")} for f in findings],
                         ensure_ascii=False, indent=2))
        counts = {k: sum(1 for f in findings if f["verdict"] == k)
                  for k in ("exact", "formatting", "substantive", "unfound")}
    else:
        counts = report(findings, sys.stdout)
    bad = counts["substantive"] + counts["unfound"] + (counts["formatting"] if a.strict else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
