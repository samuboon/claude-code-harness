# -*- coding: utf-8 -*-
"""Name the limits a document set for itself, and say which ones nobody can count.

    python stated_limits.py CLAUDE.md .claude/rules/ --root .

A rule file said "no more than 1-3 pushes per week". The loop it governs pushes once
per unit of work, so the rule was broken on day one and stayed broken, unnoticed, while
every other line in the same file kept being quoted as binding. A limit nobody counts
is not a weak rule -- it is a rule that teaches the reader which lines are decorative.

This reads prose, pulls out the quantities a document declares as its own ceiling,
resolves the files each one is talking about, measures them, and prints the ones that
are over. Limits it cannot resolve are printed too, under the reason it failed, because
"we found 17 ceilings and only 9 of them point at anything measurable" is the finding.

Standard library only. No network. Nothing is imported or executed from what it reads.
Output is pure ASCII so that a console codec cannot turn a clean run into a failure.

Exit: 0 = nothing over, 1 = at least one limit breached, 2 = the scan did not happen.
"""
import argparse
import fnmatch
import json
import re
import sys
import unicodedata
from pathlib import Path

__version__ = "1.0.0"

# Units that can be measured by looking at a file. Anything else is reported, not judged.
_UNIT_LINES = "lines"
_UNIT_CHARS = "chars"
_UNIT_BYTES = "bytes"
_UNIT_EVENTS = "events"  # times / posts / items -- a file cannot tell you.

# Surface form -> (canonical unit, byte multiplier). Longest forms first when matching.
_UNIT_WORDS = (
    ("lines", _UNIT_LINES, 1), ("line", _UNIT_LINES, 1),
    ("characters", _UNIT_CHARS, 1), ("character", _UNIT_CHARS, 1),
    ("chars", _UNIT_CHARS, 1), ("char", _UNIT_CHARS, 1),
    ("bytes", _UNIT_BYTES, 1), ("byte", _UNIT_BYTES, 1),
    ("KiB", _UNIT_BYTES, 1024), ("MiB", _UNIT_BYTES, 1024 ** 2), ("GiB", _UNIT_BYTES, 1024 ** 3),
    ("KB", _UNIT_BYTES, 1000), ("MB", _UNIT_BYTES, 1000 ** 2), ("GB", _UNIT_BYTES, 1000 ** 3),
    ("kB", _UNIT_BYTES, 1000),
    ("times", _UNIT_EVENTS, 0), ("time", _UNIT_EVENTS, 0),
    ("posts", _UNIT_EVENTS, 0), ("post", _UNIT_EVENTS, 0),
    ("items", _UNIT_EVENTS, 0), ("item", _UNIT_EVENTS, 0),
    ("files", _UNIT_EVENTS, 0), ("commits", _UNIT_EVENTS, 0), ("pushes", _UNIT_EVENTS, 0),
    # Japanese
    ("行", _UNIT_LINES, 1),                       # gyou  - line
    ("文字", _UNIT_CHARS, 1),                 # moji  - character
    ("字", _UNIT_CHARS, 1),                       # ji    - character
    ("バイト", _UNIT_BYTES, 1),           # baito - byte
    ("回", _UNIT_EVENTS, 0),                      # kai   - times
    ("本", _UNIT_EVENTS, 0),                      # hon   - counter
    ("点", _UNIT_EVENTS, 0),                      # ten   - counter
    ("件", _UNIT_EVENTS, 0),                      # ken   - counter
    ("枚", _UNIT_EVENTS, 0),                      # mai   - counter
)

# The word that turns a quantity into a ceiling. Japanese always trails it; English can
# do either ("no more than 80 lines" / "80 lines or under"), and a tool that only knows
# the leading form silently reports zero limits on an English rule file.
_SUFFIX_CAP = (
    "以内",              # inai    - within
    "以下",              # ika     - at most
    "未満",              # miman   - under
    "まで",              # made    - up to
    "を超えない",  # koenai - not exceeding
    "が上限",        # ga jougen - is the ceiling
    "が限度",        # ga gendo  - is the limit
)
_SCOPE_WORD = re.compile(
    r"^(?:combined|in\s+total|total|together|each|apiece|per\s+file|all\s+told)[,\s]*")
_SUFFIX_CAP_EN = (
    "or under", "or fewer", "or less", "or below", "or under.",
    "at most", "at the most", "maximum", "max.", "max ", "max,", "max.", "max\n",
    "hard cap", "ceiling",
)
_PREFIX_CAP = re.compile(
    r"(?:no more than|not more than|at most|fewer than|less than|under|within|up to"
    r"|max(?:imum)?(?:\s+of)?|cap(?:ped)?\s+at|limit(?:ed)?\s+to|stay\s+under"
    r"|keep\s+(?:\S+\s+){0,4}?to|budget\s+of)\s*$",
    re.IGNORECASE,
)

# "1 line 200 characters" / "each file 30 lines" -- the ceiling is per line / per file.
# The trailing class matters: prose writes "1 line (200 chars or under)", so an opening
# bracket or a comma sits between the scope word and the number it governs.
# The tail class matters: prose writes "1 line (200 chars or under)" and "each line under
# 200 chars", so the scope word and the number it governs are separated by anything except
# another number -- a digit in between means a different quantity claimed the scope first.
_PER_LINE = re.compile(
    r"(?:1\s*行|一行|each\s+line|per\s+line|(?:any\s+)?one\s+line)"
    r"[^0-9]{0,40}$",
    re.IGNORECASE,
)
_PER_FILE = re.compile(
    r"(?:1\s*本|1\s*枚|1\s*ファイル|各|それぞれ"
    r"|each\s+(?:file|one|document)|per\s+(?:file|document)|apiece)[^0-9]{0,60}$",
    re.IGNORECASE,
)
_COMBINED = re.compile(
    r"(?:合計|あわせて|合わせて|総計"
    r"|combined|in\s+total|together|all\s+told|sum\s+of)",
    re.IGNORECASE,
)

# "this file" -- only resolved when --self is given. Guessing is how false alarms start.
_SELF_REF = re.compile(
    r"(?:this\s+(?:file|document|page|rule|skill)"
    r"|このファイル|この文書|この規約"
    r"|本ファイル|この 1 枚|この1枚)",
    re.IGNORECASE,
)

_PATH_EXT = (
    "md", "markdown", "txt", "py", "js", "ts", "tsx", "json", "yml", "yaml", "toml",
    "tsv", "csv", "ini", "cfg", "sh", "rst", "go", "rs", "rb", "java",
)
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_BACKTICK = re.compile(r"`([^`]+)`")
# The trailing star in the lookahead matters: without it, "keep `docs/*.md` short" hands
# back "docs/" and the whole directory gets measured against a rule about some of it.
_BARE_PATH = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:" + "|".join(_PATH_EXT) + r"))(?![\w/*])"
)
_BARE_DIR = re.compile(r"(?<![\w.-])((?:[\w.-]+/){1,6})(?![\w*])")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_RANGE = re.compile(r"(?:" + _NUM + r")\s*(?:[-~〜～]|to)\s*$")

# Reasons a limit is reported but not judged.
R_NO_TARGET = "no-target"
R_UNMEASURABLE = "unmeasurable-unit"
R_AMBIGUOUS = "ambiguous-targets"
R_MISSING = "missing-target"
R_SELF = "self-reference"


class ScanError(Exception):
    """The scan could not be performed. Say so; do not report a clean tree."""


def _ascii_safe(text):
    """Make any quoted prose printable on any console. A report must survive its own run."""
    out = []
    for ch in text:
        if ch == "\n":
            out.append(ch)  # a report is lines; turning them into <U+000A> is not safety
        elif ch == "\t":
            out.append(" ")
        elif " " <= ch <= "~":
            out.append(ch)
        else:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = None
            out.append("<U+%04X>" % ord(ch) if name is None else "<%s>" % _short(ch, name))
    return "".join(out)


def _short(ch, name):
    """CJK runs would drown the report in names, so they collapse to a single marker."""
    if "CJK" in name or "HIRAGANA" in name or "KATAKANA" in name:
        return "JP"
    return "U+%04X" % ord(ch)


def collapse_jp(text):
    """Collapse runs of <JP> so a quoted Japanese sentence stays one readable line."""
    return re.sub(r"(?:<JP>)+", lambda m: "<JP x%d>" % (len(m.group(0)) // 4), _ascii_safe(text))


# --------------------------------------------------------------------------- parsing


def strip_emphasis(text):
    """Blank out markdown emphasis without moving any other character."""
    return "".join(" " if ch in "*~" else ch for ch in text)


def iter_sentences(text):
    """Yield (line_number, sentence) pairs. Fenced code blocks are skipped entirely.

    A sentence never spans a line: prose in these files is written one claim per line or
    one claim per table cell, and joining lines invents adjacency that is not there.
    """
    fenced = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = strip_emphasis(raw)
        for cell in line.split("|"):
            for part in _split_sentences(cell):
                if part.strip():
                    yield lineno, part


def _split_sentences(cell):
    """Split on a Japanese full stop, or an English period that clearly ends a sentence."""
    parts = re.split(r"。", cell)
    out = []
    for part in parts:
        out.extend(re.split(r"(?<=[a-z\)\"\'])\.\s+(?=[A-Z])", part))
    return out


def find_quantities(sentence):
    """Return [(value, unit, multiplier, start, end)] for every number with a unit."""
    found = []
    for m in re.finditer(_NUM, sentence):
        rest = sentence[m.end():]
        gap = re.match(r"\s*", rest).group(0)
        tail = rest[len(gap):]
        for word, unit, mult in _UNIT_WORDS:
            if tail.startswith(word):
                # "3 lines" inside "line 3 of" style noise is filtered by the cap check.
                try:
                    value = float(m.group(0).replace(",", ""))
                except ValueError:
                    continue
                found.append((value, unit, mult, m.start(), m.end() + len(gap) + len(word)))
                break
    return found


def find_limits(sentence):
    """Return the quantities in this sentence that are declared as ceilings.

    Japanese puts the cap word after ("250 lines or fewer"); English puts it before
    ("no more than 250 lines"). A chain joined by a separator shares one trailing cap
    word -- "250 lines / 50 KB or under" is two ceilings, not one.
    """
    qtys = find_quantities(sentence)
    if not qtys:
        return []
    capped = []
    for value, unit, mult, start, end in qtys:
        tail = sentence[end:]
        head = sentence[:start]
        is_cap = False
        trimmed = tail.lstrip()
        for word in _SUFFIX_CAP:
            if trimmed.startswith(word):
                is_cap = True
                break
        if not is_cap:
            # "250 lines combined or under" puts a scope word between the quantity and
            # the cap word. Step over the scope word, not over arbitrary prose.
            lowered = _SCOPE_WORD.sub("", trimmed.lower(), count=1)
            for word in _SUFFIX_CAP_EN:
                if not lowered.startswith(word):
                    continue
                # "at most" reads both ways. In "250 lines at most 80 lines" it belongs
                # to the 80, not the 250, so a digit after it means this is not our cap.
                if not lowered[len(word):].lstrip()[:1].isdigit():
                    is_cap = True
                break
        if not is_cap and _PREFIX_CAP.search(head):
            is_cap = True
        span = _RANGE.search(head)
        if not is_cap and span:
            # "no more than 1-3 pushes": the cap word sits before the low end of a range,
            # and the ceiling is the high end -- the number matched here.
            if _PREFIX_CAP.search(head[:span.start()]):
                is_cap = True
            elif unit == _UNIT_EVENTS:
                # "1-3 pushes a week", with no cap word at all, is still a declared
                # ceiling. Accepted only for event units, which are always reported as
                # unverifiable -- so a range in prose ("lines 3-5") can never become a
                # verdict about a file. This is the rule the tool was built from: the
                # sentence that started it does not contain the word "at most".
                is_cap = True
        if is_cap:
            capped.append((value, unit, mult, start, end))
    if not capped:
        return _build(sentence, [])
    # Walk left from each capped quantity across separators to pick up the chain.
    chain = list(capped)
    known = {(c[3], c[4]) for c in capped}
    for value, unit, mult, start, end in capped:
        cursor = start
        while True:
            prev = [q for q in qtys if q[4] <= cursor]
            if not prev:
                break
            cand = max(prev, key=lambda q: q[4])
            between = sentence[cand[4]:cursor]
            if not re.fullmatch(r"[\s・,、/ー-]*", between):
                break
            if (cand[3], cand[4]) not in known:
                known.add((cand[3], cand[4]))
                chain.append(cand)
            cursor = cand[3]
    return _build(sentence, chain)


def _build(sentence, chain):
    """Attach the per-line / per-file scope to each ceiling found in this sentence."""
    out = []
    for value, unit, mult, start, end in sorted(chain, key=lambda c: c[3]):
        head = sentence[:start]
        scope = "per-line" if _PER_LINE.search(head) else (
            "per-file" if _PER_FILE.search(head) else "whole")
        out.append({"value": value, "unit": unit, "mult": mult, "scope": scope,
                    "start": start, "end": end,
                    "as_written": sentence[start:end].strip()})
    return out


def find_targets(sentence):
    """Return the file and directory references this sentence names, in order."""
    seen, out = set(), []

    def add(raw):
        raw = raw.strip().strip("<>").strip()
        if not raw or raw.startswith(("http://", "https://", "#", "mailto:")):
            return
        if "*" in raw or " " in raw or raw.startswith("-"):
            return
        if raw not in seen:
            seen.add(raw)
            out.append(raw)

    for m in _MD_LINK.finditer(sentence):
        add(m.group(1).split("#")[0])
    for m in _BACKTICK.finditer(sentence):
        text = m.group(1)
        if text.endswith("/") or _BARE_PATH.fullmatch(text) or "/" in text:
            add(text)
    for m in _BARE_PATH.finditer(sentence):
        add(m.group(1))
    for m in _BARE_DIR.finditer(sentence):
        add(m.group(1))
    return out


# ------------------------------------------------------------------------- measuring


def _read_text(path):
    """Decode, and normalise line endings so a character count is not a platform count.

    A CRLF file is two bytes per line longer than the same file with LF, and a rule that
    says "200 characters per line" does not mean "198 on Windows". Byte ceilings are
    measured from disk and keep the real size.
    """
    data = path.read_bytes()
    for codec in ("utf-8", "utf-8-sig", "cp932", "latin-1"):
        try:
            return data.decode(codec).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise ScanError("cannot decode %s" % path)


def _files_under(path, excludes):
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        rel = child.as_posix()
        if "/.git/" in rel or rel.endswith("/.git"):
            continue
        if any(fnmatch.fnmatch(child.name, g) or fnmatch.fnmatch(rel, g) for g in excludes):
            continue
        yield child


def _rel(path, root):
    """Report paths the way the reader typed them, not as absolute noise."""
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def measure(path, unit, scope, excludes, root=None):
    """Return (actual, detail) for one path under one unit. Raises ScanError if unreadable."""
    root = root or Path(".").resolve()
    if path.is_dir():
        targets = list(_files_under(path, excludes))
        if not targets:
            raise ScanError("no files under %s" % _rel(path, root))
        if scope == "per-file":
            worst, where = -1, None
            for f in targets:
                got, _ = measure(f, unit, "whole", excludes, root)
                if got > worst:
                    worst, where = got, f
            return worst, "largest of %d files: %s" % (len(targets), _rel(where, root))
        total = sum(measure(f, unit, "whole", excludes, root)[0] for f in targets)
        return total, "%d files" % len(targets)

    if unit == _UNIT_BYTES:
        return float(path.stat().st_size), "on disk"
    text = _read_text(path)
    if unit == _UNIT_LINES:
        return float(len(text.splitlines())), "splitlines"
    if unit == _UNIT_CHARS:
        if scope == "per-line":
            lines = text.splitlines()
            if not lines:
                return 0.0, "empty"
            worst = max(range(len(lines)), key=lambda i: len(lines[i]))
            return float(len(lines[worst])), "longest line is line %d" % (worst + 1)
        return float(len(text)), "characters incl. newlines"
    raise ScanError("unit %s is not measurable" % unit)


def _resolve(raw, doc, root):
    """Markdown links are relative to their document; bare paths are usually from root."""
    candidates = []
    if not raw.startswith("/"):
        candidates.append((doc.parent / raw).resolve())
    candidates.append((root / raw.lstrip("/")).resolve())
    for cand in candidates:
        if cand.exists():
            return cand
    return None


# --------------------------------------------------------------------------- scanning


def scan(docs, root, excludes=(), allow_self=False, kb_mode="both", inherit=True):
    """Return (rows, stats). One row per ceiling found, judged or explained."""
    rows = []
    stats = {"documents": 0, "sentences": 0}
    for doc in docs:
        text = _read_text(doc)
        stats["documents"] += 1
        carried, carried_line = [], None
        for lineno, sentence in iter_sentences(text):
            stats["sentences"] += 1
            if lineno != carried_line:
                carried, carried_line = [], lineno
            targets = find_targets(sentence)
            inherited = False
            if targets:
                carried = targets
            elif carried and inherit:
                # Prose names the files, then sets the ceiling in the next clause:
                # "Layer 1 = A.md / B.md. Keep it to 250 lines combined." Carry forward
                # inside one line only -- across lines the adjacency is not real.
                targets, inherited = carried, True
            limits = find_limits(sentence)
            for limit in limits:
                row = _judge(doc, lineno, sentence, limit, targets, root,
                             excludes, allow_self, kb_mode)
                if inherited and row["targets"]:
                    row["inherited"] = True
                rows.append(row)
    return rows, stats


def _judge(doc, lineno, sentence, limit, targets, root, excludes, allow_self, kb_mode):
    row = {
        "document": _rel(doc, root), "line": lineno, "sentence": sentence.strip(),
        "limit": limit["value"], "unit": limit["unit"], "scope": limit["scope"],
        "as_written": limit["as_written"],
        "status": None, "reason": None, "targets": list(targets),
    }
    if limit["unit"] == _UNIT_EVENTS:
        row["status"] = "unverifiable"
        row["reason"] = R_UNMEASURABLE
        return row
    if not targets:
        if allow_self and _SELF_REF.search(sentence):
            targets = [doc.name]
            row["targets"] = targets
            row["resolved_by"] = "self"
        else:
            row["status"] = "unverifiable"
            row["reason"] = R_SELF if _SELF_REF.search(sentence) else R_NO_TARGET
            return row

    resolved, missing = [], []
    for raw in targets:
        got = _resolve(raw, doc, root)
        (resolved if got else missing).append(got or raw)
    if not resolved:
        row["status"] = "unverifiable"
        row["reason"] = R_MISSING
        row["missing"] = missing
        return row
    if len(resolved) > 1 and limit["scope"] == "whole" and not _COMBINED.search(sentence):
        row["status"] = "unverifiable"
        row["reason"] = R_AMBIGUOUS
        return row

    try:
        if len(resolved) > 1 and limit["scope"] == "per-file":
            actual, detail, worst = -1.0, "", None
            for path in resolved:
                got, why = measure(path, limit["unit"], "whole", excludes, root)
                if got > actual:
                    actual, detail, worst = got, why, path
            detail = "largest of %d: %s (%s)" % (len(resolved), _rel(worst, root), detail)
        elif len(resolved) > 1:
            parts = [measure(p, limit["unit"], "whole", excludes, root)[0] for p in resolved]
            actual = sum(parts)
            detail = "combined: " + " + ".join("%g" % p for p in parts)
        else:
            actual, detail = measure(resolved[0], limit["unit"], limit["scope"],
                                     excludes, root)
    except ScanError as exc:
        row["status"] = "unverifiable"
        row["reason"] = R_MISSING
        row["detail"] = str(exc)
        return row

    row["actual"] = actual
    row["detail"] = detail
    row["measured"] = [_rel(p, root) for p in resolved]
    if missing:
        row["missing"] = missing

    ceilings = _ceilings(limit, kb_mode)
    over = [name for name, ceiling in ceilings if actual > ceiling]
    if len(over) == len(ceilings):
        row["status"] = "breach"
    elif over:
        row["status"] = "borderline"
        row["over_under"] = over
    else:
        row["status"] = "ok"
    row["ceiling"] = ceilings[0][1]
    row["ceilings"] = {name: ceiling for name, ceiling in ceilings}
    return row


def _ceilings(limit, kb_mode):
    """A "50 KB" ceiling is two different numbers. Judge under both unless told not to."""
    if limit["unit"] != _UNIT_BYTES or limit["mult"] in (1, 1024, 1024 ** 2, 1024 ** 3):
        return [("as written", limit["value"] * max(limit["mult"], 1))]
    power = {1000: 1, 1000 ** 2: 2, 1000 ** 3: 3}[limit["mult"]]
    si = limit["value"] * (1000 ** power)
    iec = limit["value"] * (1024 ** power)
    if kb_mode == "1000":
        return [("SI 1000", si)]
    if kb_mode == "1024":
        return [("binary 1024", iec)]
    return [("SI 1000", si), ("binary 1024", iec)]


# ----------------------------------------------------------------------------- output


_UNIT_LABEL = {_UNIT_LINES: "lines", _UNIT_CHARS: "chars", _UNIT_BYTES: "bytes",
               _UNIT_EVENTS: "events"}


def _fmt(value, unit):
    if unit == _UNIT_BYTES:
        return "%d B" % round(value)
    return "%g %s" % (value, _UNIT_LABEL.get(unit, unit))


def _fmt_limit(row):
    """Quote the ceiling as the document wrote it, unless that quote is not ASCII."""
    written = _ascii_safe(row["as_written"])
    return written if "<" not in written else _fmt(row["limit"], row["unit"])


def render(rows, stats, show_all=False, width=110):
    """Build the report. Pure ASCII by construction -- see collapse_jp."""
    out = []
    counts = {k: 0 for k in ("breach", "borderline", "ok", "unverifiable")}
    for row in rows:
        counts[row["status"]] += 1
    checkable = counts["breach"] + counts["borderline"] + counts["ok"]
    out.append("documents      %d" % stats["documents"])
    out.append("sentences      %d" % stats["sentences"])
    out.append("limits found   %d" % len(rows))
    out.append("  checkable    %d" % checkable)
    out.append("  unverifiable %d" % counts["unverifiable"])
    out.append("breached       %d" % counts["breach"])
    if counts["borderline"]:
        out.append("borderline     %d  (over under one reading of KB/MB/GB, not the other)"
                   % counts["borderline"])
    order = {"breach": 0, "borderline": 1, "unverifiable": 2, "ok": 3}
    shown = [r for r in rows if show_all or r["status"] != "ok"]
    for row in sorted(shown, key=lambda r: (order[r["status"]], r["document"], r["line"])):
        out.append("")
        head = "%s:%d  %s %s" % (row["document"], row["line"],
                                 _fmt_limit(row), row["status"].upper())
        if row["scope"] != "whole":
            head += "  [%s]" % row["scope"]
        if row.get("inherited"):
            head += "  [target from the previous clause]"
        out.append(head)
        if row["status"] == "unverifiable":
            out.append("  reason   %s%s" % (row["reason"], _reason_hint(row)))
        else:
            delta = row["actual"] - row["ceiling"]
            out.append("  actual   %s  (%s%s)" % (
                _fmt(row["actual"], row["unit"]),
                "over by " if delta > 0 else "under by ",
                _fmt(abs(delta), row["unit"])))
            out.append("  measured %s  -- %s" % (", ".join(row["measured"]), row["detail"]))
            if row["status"] == "borderline":
                out.append("  note     over under %s only" % ", ".join(row["over_under"]))
        out.append("  said     %s" % _clip(collapse_jp(row["sentence"]), width))
    # Every line goes through the transcoder once more. A report about text that a
    # console refuses must not be the thing that a console refuses -- see print-codec,
    # where a link checker passed every check and then died printing its own summary.
    return collapse_jp("\n".join(out))


def _reason_hint(row):
    if row["reason"] == R_UNMEASURABLE:
        return "  (a ceiling on events; no file can be counted to check it)"
    if row["reason"] == R_NO_TARGET:
        return "  (the sentence names no file to measure)"
    if row["reason"] == R_AMBIGUOUS:
        return "  (%d files named; the sentence does not say each or combined)" % len(row["targets"])
    if row["reason"] == R_MISSING:
        return "  (named %s; not found)" % ", ".join(str(m) for m in row.get("missing", row["targets"]))
    if row["reason"] == R_SELF:
        return "  (says \"this file\"; pass --self to resolve it)"
    return ""


def _clip(text, width):
    return text if len(text) <= width else text[:width - 3] + "..."


_REWRITE_HINT = """A ceiling that nobody counts is decoration. Three rewrites that make one countable:

  before  "keep the rule files short -- 30 lines or under"
  after   "each file under `.claude/rules/` is 30 lines or under"
          (names a path, and says 'each', so a tool knows what to measure)

  before  "1-3 pushes per week"
  after   "one push per unit of work; `state/RUNS.tsv` holds one row per push"
          (an event ceiling nothing can check, traded for a rule about a file)

  before  "this document stays under 12 KB"
  after   "`.claude/skills/sam/SKILL.md` stays under 12 KiB"
          (says which file, and which KB -- 12 KB and 12 KiB are 288 bytes apart)"""


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Find the limits a document set for itself and check them.")
    parser.add_argument("paths", nargs="*", default=["."],
                        help="documents or directories of documents to read")
    parser.add_argument("--root", default=".", help="repository root paths resolve against")
    parser.add_argument("--glob", default="*.md", help="which files count as documents")
    parser.add_argument("--exclude", action="append", default=[],
                        help="glob excluded when measuring directories (repeatable)")
    parser.add_argument("--self", dest="allow_self", action="store_true",
                        help='resolve "this file" to the document it appears in')
    parser.add_argument("--kb", choices=("1000", "1024", "both"), default="both",
                        help="how to read KB/MB/GB (default: both, and say when they disagree)")
    parser.add_argument("--no-inherit", dest="inherit", action="store_false",
                        help="do not carry a target from the previous clause of a line")
    parser.add_argument("--all", action="store_true", help="also print the limits that pass")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--rewrite-hint", action="store_true",
                        help="print how to make an unverifiable limit checkable")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.rewrite_hint:
        print(_REWRITE_HINT)
        return 0

    root = Path(args.root).resolve()
    docs = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            docs.extend(sorted(p for p in path.rglob(args.glob)
                               if p.is_file() and "/.git/" not in p.as_posix()))
        elif path.is_file():
            docs.append(path)
        else:
            print("stated-limits: no such path: %s" % raw, file=sys.stderr)
            return 2
    if not docs:
        print("stated-limits: no documents matched %s" % args.glob, file=sys.stderr)
        return 2

    try:
        rows, stats = scan(docs, root, tuple(args.exclude), args.allow_self, args.kb,
                           args.inherit)
    except ScanError as exc:
        print("stated-limits: %s" % exc, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"stats": stats, "rows": rows}, ensure_ascii=True, indent=2))
    else:
        print(render(rows, stats, args.all))
    return 1 if any(r["status"] == "breach" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
