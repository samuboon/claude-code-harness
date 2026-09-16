# -*- coding: utf-8 -*-
"""Name the printed characters that the console codec cannot encode.

    python print_codec.py tools/ --codec cp932

A checker finished every check, printed a green circle at the end, and died there:
UnicodeEncodeError, exit status 1. The checks had passed. The gate reading the exit
status could not tell "nothing is broken" from "the reporter fell over".

This reads Python source without running it, collects the string literals that reach
stdout/stderr, and lists the characters a given console codec refuses. Files that pin
their own output encoding are reported as protected and are not counted at risk.

Standard library only. No network. Nothing is imported from the files it reads.

Exit: 0 = nothing at risk, 1 = at least one line at risk, 2 = the scan did not happen.
"""
import argparse
import ast
import fnmatch
import json
import sys
import unicodedata
from pathlib import Path

# Calls whose string arguments land on the console.
_STREAMS = ("stdout", "stderr")
_LOG_METHODS = ("debug", "info", "warning", "warn", "error", "exception", "critical", "log")
_LOG_OWNERS = ("logging", "log", "logger", "LOG", "LOGGER", "_log", "_logger")

# Ways a file can pin its own output encoding. Order matters only for the label.
_PROTECTIONS = (
    ("reconfigure", ("sys.stdout.reconfigure(", "sys.stderr.reconfigure(",
                     "stdout.reconfigure(", "stderr.reconfigure(")),
    ("TextIOWrapper", ("TextIOWrapper(sys.stdout.buffer", "TextIOWrapper(sys.stderr.buffer",
                       "TextIOWrapper(stdout.buffer", "TextIOWrapper(stderr.buffer")),
    ("PYTHONIOENCODING", ("PYTHONIOENCODING",)),
)


class ScanError(Exception):
    """The file could not be read or parsed. The scan says so instead of guessing."""


def encodable(ch, codec, _cache={}):
    """True if one character survives the codec. Cached: the same few thousand repeat."""
    key = (codec, ch)
    hit = _cache.get(key)
    if hit is None:
        try:
            ch.encode(codec)
            hit = True
        except UnicodeEncodeError:
            hit = False
        except LookupError:
            raise
        _cache[key] = hit
    return hit


def char_name(ch):
    """A printable identity for a character the console cannot show."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        name = "unnamed"
    return "U+{:04X} {}".format(ord(ch), name)


def safe(text, codec):
    """The same text with every character this codec refuses replaced by <U+XXXX>.

    A report about characters the console cannot print must not print them. Quoting the
    offending source line verbatim is exactly how this tool would die of the bug it
    reports.
    """
    if not text:
        return text
    out = []
    for ch in text:
        out.append(ch if encodable(ch, codec) else "<U+{:04X}>".format(ord(ch)))
    return "".join(out)


def detect_protection(text):
    """The label of the mechanism this file uses to pin its output encoding, or None."""
    for label, needles in _PROTECTIONS:
        for needle in needles:
            if needle in text:
                return label
    return None


def module_constants(tree):
    """Module-level NAME = "literal" bindings, one level deep.

    print(BANNER) is common enough to be worth resolving; anything assigned twice is
    dropped rather than guessed at.
    """
    found = {}
    twice = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id in found:
                    twice.add(target.id)
                found[target.id] = node.value.value
    for name in twice:
        found.pop(name, None)
    return found


def _stream_of(node):
    """'stdout'/'stderr' if the node names one of them, else None."""
    if isinstance(node, ast.Attribute) and node.attr in _STREAMS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in _STREAMS:
        return node.id
    return None


def classify_call(node, include_logging):
    """What kind of console write this call is, or None if it is not one."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "print":
        for kw in node.keywords:
            if kw.arg == "file" and _stream_of(kw.value) is None:
                return None  # print(..., file=open(...)) does not touch the console
        return "print"
    if isinstance(func, ast.Attribute) and func.attr == "write":
        stream = _stream_of(func.value)
        if stream is not None:
            return "sys." + stream + ".write"
    if include_logging and isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS:
        owner = func.value
        if isinstance(owner, ast.Name) and owner.id in _LOG_OWNERS:
            return "logging." + func.attr
    return None


def literal_text(node, constants, depth=0):
    """The statically known text of one argument. Unknown parts contribute nothing."""
    if depth > 8:
        return ""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):  # f-string: only the literal halves are known
        return "".join(literal_text(p, constants, depth + 1) for p in node.values)
    if isinstance(node, ast.FormattedValue):
        return ""
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return (literal_text(node.left, constants, depth + 1)
                    + literal_text(node.right, constants, depth + 1))
        if isinstance(node.op, ast.Mod):  # "%s done" % value
            return literal_text(node.left, constants, depth + 1)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in ("format", "join"):
            return literal_text(node.func.value, constants, depth + 1)
    return ""


def arg_nodes(call):
    """The arguments of a console write whose text can reach the console."""
    out = list(call.args)
    for kw in call.keywords:
        if kw.arg in ("sep", "end"):
            out.append(kw.value)
    return out


def scan_source(text, codec, include_logging=False, filename="<source>"):
    """Every console write in one file that carries a character this codec refuses."""
    try:
        tree = ast.parse(text, filename=filename)
    except SyntaxError as exc:
        raise ScanError("{}: {}".format(filename, exc))
    constants = module_constants(tree)
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind = classify_call(node, include_logging)
        if kind is None:
            continue
        bad = []
        for arg in arg_nodes(node):
            for ch in literal_text(arg, constants):
                if not encodable(ch, codec) and ch not in bad:
                    bad.append(ch)
        if bad:
            rows.append({"line": getattr(node, "lineno", 0), "call": kind, "chars": bad})
    rows.sort(key=lambda r: (r["line"], r["call"]))
    return rows


def is_entry_point(text):
    """Does this file decide an exit status? Those are the ones that lie to a gate."""
    return "sys.exit(" in text or '__name__ == "__main__"' in text or "__name__ == '__main__'" in text


def source_line(text, lineno):
    lines = text.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def iter_targets(paths, excludes):
    """Every .py file under the given paths, in a stable order, minus the excluded."""
    seen = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = sorted(q for q in p.rglob("*.py"))
        elif p.is_file():
            found = [p]
        else:
            raise ScanError("not found: {}".format(raw))
        for q in found:
            posix = q.as_posix()
            if any(fnmatch.fnmatch(posix, pat) or fnmatch.fnmatch(q.name, pat) for pat in excludes):
                continue
            if q not in seen:
                seen.append(q)
    return seen


def scan_paths(paths, codec, include_logging=False, excludes=()):
    """Scan a tree. Returns (files, skipped) where files carry their own verdict."""
    files, skipped = [], []
    for path in iter_targets(paths, list(excludes)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            skipped.append({"path": path.as_posix(), "why": str(exc)})
            continue
        try:
            rows = scan_source(text, codec, include_logging, path.as_posix())
        except ScanError as exc:
            skipped.append({"path": path.as_posix(), "why": str(exc)})
            continue
        protection = detect_protection(text)
        files.append({
            "path": path.as_posix(),
            "protected": protection,
            "entry_point": is_entry_point(text),
            "rows": rows,
            "text": text,
        })
    return files, skipped


FIX_HINT = '''\
# put this above the first print, and the codec stops deciding your exit status
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except AttributeError:  # Python < 3.7
        pass
'''


def report(files, skipped, codec, limit=20, show_all=False, fix_hint=False, out=None):
    out = sys.stdout if out is None else out  # bound late: tests replace sys.stdout
    at_risk = [f for f in files if f["rows"] and not f["protected"]]
    protected_hits = [f for f in files if f["rows"] and f["protected"]]
    lines = sum(len(f["rows"]) for f in at_risk)
    chars = set()
    for f in at_risk:
        for row in f["rows"]:
            chars.update(row["chars"])
    write = out.write
    write("codec          {}\n".format(codec))
    write("files read     {}\n".format(len(files)))
    write("protected      {}\n".format(len([f for f in files if f["protected"]])))
    write("at risk        {} file(s)\n".format(len(at_risk)))
    write("lines          {}\n".format(lines))
    write("characters     {} distinct\n".format(len(chars)))
    if skipped:
        write("not scanned    {}\n".format(len(skipped)))
    if not at_risk:
        write("\nnothing printed here needs a character {} cannot encode.\n".format(codec))
        return
    write("\n")
    shown = 0
    for f in sorted(at_risk, key=lambda f: (not f["entry_point"], f["path"])):
        tag = "  (decides an exit status)" if f["entry_point"] else ""
        write("{}{}\n".format(safe(f["path"], codec), tag))
        for row in f["rows"]:
            if not show_all and shown >= limit:
                write("  ... {} more line(s); pass --all\n".format(lines - shown))
                if fix_hint:
                    write("\n" + FIX_HINT)
                return
            write("  line {:<5} {}\n".format(row["line"], row["call"]))
            src = safe(source_line(f["text"], row["line"]), codec)
            if src:
                write("    {}\n".format(src[:120]))
            for ch in row["chars"]:
                write("    {}\n".format(char_name(ch)))
            shown += 1
        write("\n")
    if protected_hits:
        write("{} file(s) print those characters but pin their own encoding first:\n".format(
            len(protected_hits)))
        for f in protected_hits:
            write("  {}  ({})\n".format(safe(f["path"], codec), f["protected"]))
        write("\n")
    if fix_hint:
        write(FIX_HINT)


def as_json(files, skipped, codec):
    return {
        "codec": codec,
        "files": [{k: v for k, v in f.items() if k != "text"} for f in files],
        "skipped": skipped,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Name the printed characters the console codec cannot encode.")
    ap.add_argument("paths", nargs="*", default=["."],
                    help="files or directories (default: the current one)")
    ap.add_argument("--codec", default="cp932",
                    help="console codec to test against (default: cp932)")
    ap.add_argument("--include-logging", action="store_true",
                    help="also read logging.info(...) and friends (handler-dependent)")
    ap.add_argument("--exclude", action="append", default=[],
                    help="glob to skip; repeatable")
    ap.add_argument("--all", action="store_true", help="print every line, not the first 20")
    ap.add_argument("--fix-hint", action="store_true", help="print the three lines that fix it")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if not args.paths:
        args.paths = ["."]
    try:
        encodable("a", args.codec)
    except LookupError:
        sys.stderr.write("unknown codec: {}\n".format(args.codec))
        return 2
    try:
        files, skipped = scan_paths(args.paths, args.codec, args.include_logging, args.exclude)
    except ScanError as exc:
        sys.stderr.write("{}\n".format(safe(str(exc), args.codec)))
        return 2
    if args.json:
        json.dump(as_json(files, skipped, args.codec), sys.stdout, ensure_ascii=True, indent=2)
        sys.stdout.write("\n")
    else:
        report(files, skipped, args.codec, show_all=args.all, fix_hint=args.fix_hint)
    return 1 if any(f["rows"] and not f["protected"] for f in files) else 0


if __name__ == "__main__":
    sys.exit(main())
