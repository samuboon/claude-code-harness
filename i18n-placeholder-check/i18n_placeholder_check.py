# -*- coding: utf-8 -*-
"""Check Java .properties translations against their base file, the way java.text.MessageFormat reads them.

    python i18n_placeholder_check.py src/main/resources            # every bundle under a directory
    python i18n_placeholder_check.py Messages.properties Messages_fr.properties
    python i18n_placeholder_check.py DIR --always-messageformat     # every value goes through MessageFormat
    python i18n_placeholder_check.py DIR --key-as-base              # a key that is the source text is its own base
    python i18n_placeholder_check.py DIR --java 25                  # Java 25's MessageFormat (default: 21)
    python i18n_placeholder_check.py DIR --tsv                      # one row per finding

A bundle is a base file (Messages.properties) and the files next to it that add a locale suffix
(Messages_fr.properties, Messages_pt_BR.properties, Messages_zh_Hant_TW.properties).

What it reports (level in brackets):

  BROKEN   [error]   MessageFormat throws IllegalArgumentException on the value (unmatched brace,
                     "{}", "{x}", unknown format type, bad choice pattern). The code that formats it
                     gets the exception instead of a message.
  QUOTED   [error]   an apostrophe opened a quoted section that swallowed a placeholder the base uses:
                     "l'utilisateur {0}" prints "lutilisateur {0}" with a literal {0}.
  BADFILE  [error]   the file itself does not load (malformed \\uXXXX escape).
  APOS     [warning] a lone apostrophe in a value that goes through MessageFormat; it disappears
                     from the output ("n'existe" prints "nexiste").
  MISSING  [warning] the translation does not use a placeholder the base uses.
  EXTRA    [warning] the translation uses a placeholder the base does not; unless the code passes
                     more arguments than the base shows, it prints literally as "{2}".
  BOM      [warning] the file starts with a byte-order mark; Java keeps it as part of the first key.
  TYPE     [note]    the translation gives a placeholder a format type the base never does
                     ({0,choice,...} where the base has {0}). Fine for a number (plural forms);
                     throws "Cannot format given Object as a Number" if the argument is a string.
  ORPHAN   [note]    a key the base file does not have (its value is still checked by itself).
  DUP      [note]    the same key twice in one file (the later one wins).

Which values are read as MessageFormat patterns: by default, a key whose base value has at least one
placeholder (code usually calls MessageFormat.format only when it has arguments). With
--always-messageformat, every value (Jenkins and other code that formats every message).

Exit codes: 0 = no error (warnings do not fail unless --strict). 1 = an error (or, with --strict,
a warning). 2 = nothing readable was given. 3 = nothing failed, but some translation files had no
base file and were not compared (use --key-as-base or --base-locale). 3 is not a pass.

Standard library only. Reads files; writes nothing; no network.
"""
import argparse
import os
import re
import sys
from pathlib import Path

LEVEL = {"BROKEN": "error", "QUOTED": "error", "BADFILE": "error",
         "APOS": "warning", "MISSING": "warning", "EXTRA": "warning", "BOM": "warning",
         "TYPE": "note", "ORPHAN": "note", "DUP": "note"}
ORDER = ["BADFILE", "BROKEN", "QUOTED", "APOS", "MISSING", "EXTRA", "BOM", "TYPE", "ORPHAN", "DUP"]


# ---------------------------------------------------------------- .properties (java.util.Properties.load)

class PropertiesError(Exception):
    def __init__(self, line, msg):
        super().__init__(msg)
        self.line = line


def read_text(path):
    """PropertyResourceBundle (Java 9+) reads UTF-8 and falls back to ISO-8859-1 on malformed input."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "iso-8859-1"


def _logical_lines(text):
    """Yield (first natural line number, logical line) the way Properties.LineReader joins them."""
    nat = re.split(r"\r\n|\r|\n", text)
    i = 0
    while i < len(nat):
        start = i
        line = nat[i].lstrip(" \t\f")
        i += 1
        if not line or line[0] in "#!":
            continue
        buf = seg = line
        while True:
            # LineReader resets its backslash count at each continuation, so only the newly
            # appended piece decides; an empty piece (a blank line) ends the logical line
            bs = len(seg) - len(seg.rstrip("\\"))
            if bs % 2 == 0:
                break
            buf = buf[:-1]
            if i >= len(nat):
                break
            seg = nat[i].lstrip(" \t\f")
            buf += seg
            i += 1
        yield start + 1, buf


def _unescape(s, lineno):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(s):
            break
        c = s[i]
        i += 1
        if c == "u":
            hexpart = s[i:i + 4]
            if len(hexpart) < 4 or not all(h in "0123456789abcdefABCDEF" for h in hexpart):
                raise PropertiesError(lineno, "Malformed \\uxxxx encoding.")
            out.append(chr(int(hexpart, 16)))
            i += 4
        else:
            out.append({"t": "\t", "r": "\r", "n": "\n", "f": "\f"}.get(c, c))
    return "".join(out)


def parse_properties(text):
    """Return (entries, dups). entries: key -> (line, value) with the last duplicate winning."""
    entries = {}
    dups = []
    for lineno, line in _logical_lines(text):
        key_len, value_start, has_sep, prev_bs = 0, len(line), False, False
        while key_len < len(line):
            c = line[key_len]
            if c in "=:" and not prev_bs:
                value_start, has_sep = key_len + 1, True
                break
            if c in " \t\f" and not prev_bs:
                value_start = key_len + 1
                break
            prev_bs = (not prev_bs) if c == "\\" else False
            key_len += 1
        while value_start < len(line):
            c = line[value_start]
            if c not in " \t\f":
                if not has_sep and c in "=:":
                    has_sep = True
                else:
                    break
            value_start += 1
        key = _unescape(line[:key_len], lineno)
        value = _unescape(line[value_start:], lineno)
        if key in entries:
            dups.append((lineno, key, entries[key][0]))
        entries[key] = (lineno, value)
    return entries, dups


# ---------------------------------------------------------------- MessageFormat (java.text.MessageFormat.applyPattern)

class PatternError(Exception):
    pass


# Java 8 to 21 know four format types. Java 25 adds java.time formatters and lists; a pattern that
# uses them works on 25 and throws on 21 (checked against OpenJDK jdk21u and jdk25u, 2026-09-24).
TYPES_21 = ["", "number", "date", "time", "choice"]
TYPES_25 = TYPES_21 + ["dtf_date", "dtf_time", "dtf_datetime", "list", "basic_iso_date", "iso_local_date",
                       "iso_offset_date", "iso_date", "iso_local_time", "iso_offset_time", "iso_time",
                       "iso_local_date_time", "iso_offset_date_time", "iso_zoned_date_time", "iso_date_time",
                       "iso_ordinal_date", "iso_week_date", "iso_instant", "rfc_1123_date_time"]
JAVA = {"version": 21}
MAX_ARGUMENT_INDEX = 10000


def _find_keyword(s, words):
    if s in words:
        return s
    ls = s.strip().lower()
    return ls if ls in words else None


def _java_parse_int(s):
    """Integer.parseInt: optional sign, then digits (any Unicode decimal digit). No spaces."""
    if not s:
        raise PatternError("can't parse argument number: " + s)
    body = s[1:] if s[0] in "+-" else s
    if not body or not all(ch.isdecimal() for ch in body):
        raise PatternError("can't parse argument number: " + s)
    n = int("".join(str(int(ch)) for ch in body))
    if s[0] == "-":
        n = -n
    if not -2 ** 31 <= n < 2 ** 31:
        raise PatternError("can't parse argument number: " + s)
    return n


def _java_parse_double(s):
    if s == "\u221e":          # compared before Double.parseDouble trims, as the JDK does
        return float("inf")
    if s == "-\u221e":
        return float("-inf")
    t = s.strip("".join(chr(c) for c in range(33)))
    if t and t[-1] in "dDfF" and not t.lower().startswith(("0x", "-0x", "+0x")):
        t = t[:-1]
    try:
        if t.lower().lstrip("+-").startswith("0x"):
            return float.fromhex(t)
        if t.lstrip("+-") in ("Infinity", "NaN"):
            return float(t)
        if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", t):
            raise ValueError
        return float(t)
    except ValueError:
        raise PatternError("Choice Pattern incorrect: bad limit " + repr(s))


def _next_double(x):
    import math
    return math.nextafter(x, float("inf"))


def parse_choice(style):
    """ChoiceFormat.applyPattern. Return the list of branch texts (quotes already removed).

    Java 21 reads every unquoted '#', '<' and '≤' as the end of a limit, even inside a branch's
    text, and throws there; Java 25 keeps them as text and ignores a '|' that ends no branch."""
    j25 = JAVA["version"] >= 25
    seg = ["", ""]
    part = 0
    old = float("nan")
    start = 0.0
    in_quote = False
    texts = []
    i = 0
    while i < len(style):
        ch = style[i]
        if ch == "'":
            if i + 1 < len(style) and style[i + 1] == "'":
                seg[part] += ch
                i += 1
            else:
                in_quote = not in_quote
        elif in_quote:
            seg[part] += ch
        elif ch in "<#\u2264" and j25 and part == 1:
            seg[part] += ch
        elif ch in "<#\u2264":
            if seg[0] == "":
                raise PatternError("Choice Pattern incorrect: Each interval must contain a number before a format")
            start = _java_parse_double(seg[0])
            if ch == "<" and start not in (float("inf"), float("-inf")):
                start = _next_double(start)
            if start <= old:
                raise PatternError("Choice Pattern incorrect: Incorrect order of intervals, must be in ascending order")
            seg[0] = ""
            part = 1
        elif ch == "|" and j25 and part != 1:
            pass
        elif ch == "|":
            texts.append(seg[1])
            old = start
            seg[1] = ""
            part = 0
        else:
            seg[part] += ch
        i += 1
    if part == 1:
        texts.append(seg[1])
    return texts


class Parsed:
    """Arguments of one pattern: index -> list of (type, style); what MessageFormat prints, with each
    argument shown as <n> (so a literal "{0}" in the output is one that was not substituted)."""

    def __init__(self):
        self.args = {}
        self.literal = ""
        self.render = ""
        self.sections = []        # text of each quoted section ('...'), where a placeholder can hide
        self.branch_errors = []   # choice branches that would throw when chosen

    def add(self, idx, typ, style):
        self.args.setdefault(idx, []).append((typ, style))


def parse_pattern(p, depth=0):
    """java.text.MessageFormat.applyPattern, then the nested MessageFormat of each choice branch
    that contains '{' (MessageFormat.subformat does that at format time)."""
    res = Parsed()
    SEG_RAW, SEG_INDEX, SEG_TYPE, SEG_MOD = 0, 1, 2, 3
    segs = ["", None, None, None]
    part = SEG_RAW
    in_quote = False
    brace = 0
    i = 0
    while i < len(p):
        ch = p[i]
        if part == SEG_RAW:
            if ch == "'":
                if i + 1 < len(p) and p[i + 1] == "'":
                    segs[part] += ch
                    res.render += ch
                    if in_quote:
                        res.sections[-1] += ch
                    i += 1
                else:
                    in_quote = not in_quote
                    if in_quote:
                        res.sections.append("")
            elif ch == "{" and not in_quote:
                part = SEG_INDEX
                if segs[SEG_INDEX] is None:
                    segs[SEG_INDEX] = ""
            else:
                segs[part] += ch
                res.render += ch
                if in_quote:
                    res.sections[-1] += ch
        else:
            if in_quote:
                segs[part] += ch
                if ch == "'":
                    in_quote = False
            elif ch == ",":
                if part < SEG_MOD:
                    part += 1
                    if segs[part] is None:
                        segs[part] = ""
                else:
                    segs[part] += ch
            elif ch == "{":
                brace += 1
                segs[part] += ch
            elif ch == "}":
                if brace == 0:
                    part = SEG_RAW
                    idx = _make_format(res, [s if s is not None else "" for s in segs], depth)
                    res.render += "<%d>" % idx
                    segs[SEG_INDEX] = segs[SEG_TYPE] = segs[SEG_MOD] = None
                else:
                    brace -= 1
                    segs[part] += ch
            elif ch == " ":
                if part != SEG_TYPE or segs[SEG_TYPE]:
                    segs[part] += ch
            else:
                if ch == "'":
                    in_quote = True
                segs[part] += ch
        i += 1
    # the JDK's own condition: an unfinished argument with open inner braces is silently dropped
    if brace == 0 and part != SEG_RAW:
        raise PatternError("Unmatched braces in the pattern.")
    res.literal = segs[SEG_RAW]
    return res


def _make_format(res, segs, depth):
    idx = _java_parse_int(segs[1])
    if idx < 0:
        raise PatternError("negative argument number: %d" % idx)
    if idx >= MAX_ARGUMENT_INDEX:
        raise PatternError("%d exceeds the ArgumentIndex implementation limit" % idx)
    typ = _find_keyword(segs[2], TYPES_25 if JAVA["version"] >= 25 else TYPES_21)
    if typ is None:
        raise PatternError("unknown format type: " + segs[2])
    style = segs[3]
    res.add(idx, typ, style.strip() if typ != "choice" else style)
    if typ == "choice":
        branches = parse_choice(style)
        if depth < 8:
            for n, text in enumerate(branches):
                if "{" not in text:
                    continue
                try:
                    sub = parse_pattern(text, depth + 1)
                except PatternError as e:
                    res.branch_errors.append("choice branch %d of {%d}: %s" % (n + 1, idx, e))
                    continue
                for k, v in sub.args.items():
                    for t, s in v:
                        res.add(k, t, s)
                res.branch_errors.extend(sub.branch_errors)
                res.sections.extend(sub.sections)
    return idx


def arg_types(parsed):
    """index -> set of format types used for it (style ignored except the type word)."""
    return {k: {t for t, _ in v} for k, v in parsed.args.items()}


# ---------------------------------------------------------------- bundles

LOCALE = re.compile(r"[a-z]{2,3}(?:_[A-Z][a-z]{3})?(?:_(?:[A-Z]{2}|\d{3}))?(?:_[A-Za-z0-9]+)?")


def locale_splits(name):
    """For 'Messages_pt_BR.properties' yield ('Messages', 'pt_BR'), longest stem first."""
    stem = name[:-len(".properties")]
    cuts = [m.start() for m in re.finditer("_", stem)]
    for c in reversed(cuts):
        base, loc = stem[:c], stem[c + 1:]
        if base and LOCALE.fullmatch(loc):
            yield base, loc


def collect(paths):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for dirpath, _, names in os.walk(p):
                for n in names:
                    if n.endswith(".properties"):
                        files.append(Path(dirpath) / n)
        elif p.is_file() and p.name.endswith(".properties"):
            files.append(p)
    return sorted(set(files))


def group(files, base_locale=None):
    """Return (bundles, orphans). bundles: base path -> [(locale, path)]; orphans: translations without a base."""
    have = {(f.parent, f.name) for f in files}
    bundles, orphans, rest = {}, [], []
    for f in files:
        splits = list(locale_splits(f.name))
        if not splits:
            bundles.setdefault(f, [])
            continue
        for stem, loc in splits:
            if (f.parent, stem + ".properties") in have:
                bundles.setdefault(f.parent / (stem + ".properties"), []).append((loc, f))
                break
        else:
            rest.append((f, splits))
    # no NAME.properties: with --base-locale, NAME_<loc>.properties stands in for it
    for f, splits in rest:
        placed = False
        if base_locale:
            for stem, loc in splits:
                base = f.parent / ("%s_%s.properties" % (stem, base_locale))
                if loc == base_locale:
                    bundles.setdefault(f, [])
                    placed = True
                    break
                if (f.parent, base.name) in have:
                    bundles.setdefault(base, []).append((loc, f))
                    placed = True
                    break
        if not placed:
            orphans.append(f)
    return bundles, orphans


# ---------------------------------------------------------------- checks

def _fmt_args(types):
    if not types:
        return "none"
    return " ".join("{%d%s}" % (k, "" if types[k] == {""} else "," + "/".join(sorted(t or "-" for t in types[k])))
                    for k in sorted(types))


def check_value(path, lineno, key, value, as_mf, findings):
    """Checks on one value by itself. Return Parsed or None."""
    if not as_mf:
        return None
    try:
        parsed = parse_pattern(value)
    except PatternError as e:
        findings.append((path, lineno, "BROKEN", key, "%s  value: %s" % (e, _short(value))))
        return None
    for msg in parsed.branch_errors:
        findings.append((path, lineno, "BROKEN", key, "%s  value: %s" % (msg, _short(value))))
    # a quoted section with a brace in it is the documented way to print a brace; one without is an
    # apostrophe that was meant as text
    if any("{" not in sec and "}" not in sec for sec in parsed.sections):
        findings.append((path, lineno, "APOS", key,
                         "a lone apostrophe is eaten by MessageFormat; prints: %s" % _short(parsed.render)))
    return parsed


def _short(s, n=160):
    s = s.replace("\n", "\\n").replace("\t", "\\t")
    return s if len(s) <= n else s[:n - 3] + "..."


def load(path, findings):
    try:
        text, _enc = read_text(path)
    except OSError as e:
        findings.append((path, 0, "BADFILE", "", "cannot read: %s" % e))
        return None
    try:
        entries, dups = parse_properties(text)
    except PropertiesError as e:
        findings.append((path, e.line, "BADFILE", "", "%s (ResourceBundle refuses the whole file)" % e))
        return None
    for key in [k for k in entries if k.startswith("\ufeff")]:
        line = entries.pop(key)[0]
        rest = key[1:]
        if rest[:1] in ("#", "!", ""):
            continue          # a comment line behind the mark became a junk key; nothing real is lost
        findings.append((path, line, "BOM", rest, "the file starts with a byte-order mark and Properties.load "
                                                  "keeps it: this key is read as U+FEFF + key and never matches"))
    for lineno, key, first in dups:
        findings.append((path, lineno, "DUP", key, "also on line %d; this one wins" % first))
    return entries


def _looks_like_text(key):
    """A key that is the source text itself (Jelly's ${%Other Jenkins}), not an id like Foo.bar."""
    return bool(re.search(r"\s", key)) or "{" in key


def compare(base_entries, tpath, t_entries, always_mf, findings, key_as_base=False, has_base=True):
    checked = 0
    for key, (tline, tval) in t_entries.items():
        if key in base_entries:
            bval = base_entries[key][1]
        elif key_as_base and _looks_like_text(key):
            bval = key
        else:
            if has_base:
                findings.append((tpath, tline, "ORPHAN", key, "not in the base file"))
            check_value(tpath, tline, key, tval, always_mf, findings)
            continue
        checked += 1
        try:
            bparsed = parse_pattern(bval)
            btypes = arg_types(bparsed)
        except PatternError:
            bparsed, btypes = None, None
        as_mf = always_mf or bool(btypes)
        tparsed = check_value(tpath, tline, key, tval, as_mf, findings)
        if not as_mf:
            # the base has no placeholder and is not read as a pattern: only look for placeholders added
            try:
                lax = arg_types(parse_pattern(tval))
            except PatternError:
                lax = {}
            if lax and btypes is not None:
                findings.append((tpath, tline, "EXTRA", key,
                                 "base has no placeholder; translation uses %s" % _fmt_args(lax)))
            continue
        if tparsed is None or btypes is None:
            continue
        ttypes = arg_types(tparsed)
        missing = sorted(set(btypes) - set(ttypes))
        extra = sorted(set(ttypes) - set(btypes))
        hidden = "\n".join(tparsed.sections)
        quoted = [k for k in missing if re.search(r"\{\s*%d\s*[,}]" % k, hidden)]
        for k in quoted:
            findings.append((tpath, tline, "QUOTED", key,
                             "an apostrophe quoted {%d}; prints: %s" % (k, _short(tparsed.render))))
        rest = [k for k in missing if k not in quoted]
        if rest:
            findings.append((tpath, tline, "MISSING", key, "base uses %s, translation %s" %
                             (_fmt_args(btypes), _fmt_args(ttypes))))
        if extra:
            findings.append((tpath, tline, "EXTRA", key, "base uses %s, translation %s" %
                             (_fmt_args(btypes), _fmt_args(ttypes))))
        # {0} and {0,number} print a number the same way, so a translation that drops a type is not
        # reported. One that adds a type the base never applies can throw at format time
        # ("Cannot format given Object as a Number") when the argument is a string.
        for k in sorted(set(btypes) & set(ttypes)):
            added = (ttypes[k] - {""}) - (btypes[k] - {""})
            if added:
                findings.append((tpath, tline, "TYPE", key, "{%d}: translation formats it as %s, base only as %s" %
                                 (k, "/".join(sorted(added)),
                                  "/".join(sorted(t or "plain" for t in btypes[k])))))
    return checked


def run(paths, always_mf=False, key_as_base=False, base_locale=None):
    files = collect(paths)
    findings = []
    stats = {"files": len(files), "bundles": 0, "translations": 0, "compared": 0, "no_base": 0}
    if not files:
        return findings, stats, []
    bundles, orphans = group(files, base_locale)
    for base, trans in sorted(bundles.items()):
        bentries = load(base, findings)
        if bentries is None:
            continue
        stats["bundles"] += 1
        # a .properties file with no translation next to it is usually configuration, not messages;
        # with --always-messageformat the caller has said every value is a message
        for key, (line, val) in (bentries.items() if trans or always_mf else ()):
            try:
                has_args = bool(parse_pattern(val).args)
            except PatternError:
                has_args = True
            check_value(base, line, key, val, always_mf or has_args, findings)
        for _loc, t in sorted(trans, key=lambda x: str(x[1])):
            tentries = load(t, findings)
            if tentries is None:
                continue
            stats["translations"] += 1
            stats["compared"] += compare(bentries, t, tentries, always_mf, findings, key_as_base)
    unchecked = []
    for t in orphans:
        if key_as_base:
            tentries = load(t, findings)
            if tentries is None:
                continue
            stats["translations"] += 1
            stats["compared"] += compare({}, t, tentries, always_mf, findings, key_as_base=True, has_base=False)
        else:
            unchecked.append(t)
    stats["no_base"] = len(unchecked)
    return findings, stats, unchecked


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", help=".properties files or directories")
    ap.add_argument("--always-messageformat", action="store_true",
                    help="read every value as a MessageFormat pattern, not only those whose base has placeholders")
    ap.add_argument("--key-as-base", action="store_true",
                    help="a key that is the source text itself (it has a space or a brace, as Jelly's "
                         "${%Other Jenkins} does) is compared with itself when the base file lacks it or "
                         "there is no base file")
    ap.add_argument("--base-locale", metavar="LOC",
                    help="use NAME_LOC.properties as the base when NAME.properties does not exist")
    ap.add_argument("--java", type=int, choices=[21, 25], default=21,
                    help="MessageFormat of Java 8-21 (default) or of Java 25 (more format types; "
                         "'#' allowed inside a choice branch)")
    ap.add_argument("--strict", action="store_true", help="warnings fail too")
    ap.add_argument("--tsv", action="store_true", help="one tab-separated row per finding")
    ap.add_argument("--no-notes", action="store_true", help="do not print ORPHAN and DUP")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass

    JAVA["version"] = a.java
    findings, stats, unchecked = run(a.paths, a.always_messageformat, a.key_as_base, a.base_locale)
    if not stats["files"]:
        print("nothing to check: no .properties file under %s" % " ".join(a.paths))
        return 2
    counts = {c: 0 for c in ORDER}
    shown = []
    for f in findings:
        counts[f[2]] += 1
        if a.no_notes and LEVEL[f[2]] == "note":
            continue
        shown.append(f)
    shown.sort(key=lambda f: (str(f[0]), f[1], ORDER.index(f[2])))
    out = sys.stdout
    if a.tsv:
        out.write("level\tcode\tfile\tline\tkey\tdetail\n")
        for path, line, code, key, detail in shown:
            out.write("\t".join([LEVEL[code], code, str(path), str(line), key.replace("\t", "\\t"),
                                 detail.replace("\t", "\\t")]) + "\n")
    else:
        for path, line, code, key, detail in shown:
            out.write("%s:%d: %s %s %s: %s\n" % (path, line, LEVEL[code], code, key, detail))
    errors = sum(counts[c] for c in ORDER if LEVEL[c] == "error")
    warnings = sum(counts[c] for c in ORDER if LEVEL[c] == "warning")
    summary = "  ".join("%s %d" % (c, counts[c]) for c in ORDER if counts[c])
    sys.stderr.write("%d files, %d bundles, %d translations, %d keys compared; errors %d, warnings %d%s\n"
                     % (stats["files"], stats["bundles"], stats["translations"], stats["compared"],
                        errors, warnings, ("  (" + summary + ")") if summary else ""))
    if unchecked:
        sys.stderr.write("not compared: %d translation files have no base file (first: %s). "
                         "Use --key-as-base or --base-locale.\n" % (len(unchecked), unchecked[0]))
    if errors or (a.strict and warnings):
        return 1
    if unchecked:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
