# -*- coding: utf-8 -*-
"""Count what actually stopped your agent, split by which layer said no.

    python permission_gap.py scan
    python permission_gap.py scan --since 2026-09-01 --json

An unattended agent is stopped by four different things, and they are not
interchangeable:

    own-hook    your own PreToolUse hook - your code, your rules, you can fix it
    allowlist   your settings.json did not cover it - a human must grant it
    classifier  the platform's own permission model - not yours, no appeal
    human       somebody clicked "no"

Every one of them arrives at the model as the same thing: an error string on a
tool call. So a log that counts "failures" tells you nothing about whether the
fix is in your code, in your config, or nowhere you can reach. This reads the
Claude Code session transcripts you already have on disk and splits them.

It also measures three things that a total alone hides:

    flapping    the same command shape sometimes runs and sometimes is denied
    self-denied a shape your own allowlist explicitly permits, denied anyway
    collateral  an unrelated shape denied seconds after a denial

Standard library only. It reads transcripts and writes nothing.
Exit code: 0 = scanned (findings are not failures), 1 = bad input, 2 = nothing read.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

LAYERS = ("own-hook", "allowlist", "classifier", "human")

LAYER_LABEL = {
    "own-hook": "own hooks (your code)",
    "allowlist": "allowlist (needs a human)",
    "classifier": "platform classifier (not yours)",
    "human": "human said no",
}

_CLASSIFIER_PREFIX = "Permission for this action was denied by the Claude Code auto mode classifier"
_CLASSIFIER_REASON = re.compile(r"Reason:\s*(?:\[(?P<tag>[^\]]{1,80})\]|(?P<bare>[^.\n]{1,80}))")
_ALLOWLIST_RX = re.compile(
    r"^Permission to use (?P<tool>[A-Za-z_][\w-]*)"
    r"(?: with command (?P<cmd>.*?))?"
    r" ha(?:s|ve) (?:been denied|not been granted)",
    re.S,
)
_HUMAN_PREFIX = "The user doesn't want to proceed with this tool use"
_HOOK_RX = re.compile(r"^PreToolUse:(?P<tool>[A-Za-z_][\w-]*) hook error: \[(?P<hook>[^\]]*)\]:\s*(?P<msg>.*)", re.S)

# Anything that looks like a credential is masked before a command is ever printed.
_SECRET_RX = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{6,}|sk-[A-Za-z0-9-]{8,}|xox[baprs]-[A-Za-z0-9-]{6,}|[A-Fa-f0-9]{32,})"
)

_URL_RX = re.compile(r"^(?:https?|ftp|git)://", re.I)
_ASSIGN_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SUBCOMMAND_RX = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")
_CODE_FLAGS = {"-c", "-e", "--eval", "-Command", "-command"}
_INTERPRETERS = {"python", "python3", "py", "node", "deno", "bun", "sh", "bash", "ruby", "perl", "pwsh", "powershell"}
_CHAINERS = ("&&", "||", ";", "|")
_PREAMBLE = {"cd", "export", "set", "source", ".", "time", "env", "sudo", "nohup"}
MAX_SHAPE_TOKENS = 4
MAX_TEXT = 4000  # a tool_result can be megabytes; the verdict is always at the front


# --------------------------------------------------------------------------- #
# classifying one tool_result
# --------------------------------------------------------------------------- #
def classify_denial(text):
    """Return (layer, reason, tool, command) for a denial, or None if it is not one.

    `tool` and `command` are whatever the denial text itself carries; they stay None
    when it carries nothing, and the caller fills them in from the request.
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    if s.startswith(_CLASSIFIER_PREFIX):
        m = _CLASSIFIER_REASON.search(s[: len(_CLASSIFIER_PREFIX) + 200])
        if m and m.group("tag"):
            reason = m.group("tag").strip()
        elif m and m.group("bare"):
            reason = m.group("bare").strip()
        else:
            reason = "(no reason given)"
        return ("classifier", reason, None, None)
    m = _ALLOWLIST_RX.match(s)
    if m:
        return ("allowlist", "not granted", m.group("tool"), (m.group("cmd") or None))
    if s.startswith(_HUMAN_PREFIX):
        return ("human", "user rejected", None, None)
    m = _HOOK_RX.match(s)
    if m:
        msg = (m.group("msg") or "").strip().splitlines()
        reason = msg[0].strip() if msg else "(no message)"
        return ("own-hook", reason[:120], m.group("tool"), None)
    return None


def redact(text):
    """Mask credential-shaped strings. Called before any command reaches the screen."""
    if not isinstance(text, str):
        return text
    return _SECRET_RX.sub("<redacted>", text)


# --------------------------------------------------------------------------- #
# command shape
# --------------------------------------------------------------------------- #
def _split_tokens(cmd):
    """Whitespace split that keeps a quoted run together, returning (token, was_quoted).

    shlex chokes on the half-quoted shell one-liners a transcript is full of. The
    quoting matters beyond splitting: a quoted run is data the command acts on, so it
    never becomes part of the command's identity.
    """
    out, buf, quote, quoted = [], [], None, False
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'":
            quote = ch
            quoted = True
        elif ch.isspace():
            if buf:
                out.append(("".join(buf), quoted))
                buf, quoted = [], False
        else:
            buf.append(ch)
    if buf:
        out.append(("".join(buf), quoted))
    return out


def _first_real_stage(cmd):
    """Drop `cd X &&`, `VAR=1 ...` and friends, and return the tokens that do the work."""
    stages, cur, quote = [], [], None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
            i += 1
            continue
        hit = next((c for c in _CHAINERS if cmd.startswith(c, i)), None)
        if hit:
            stages.append("".join(cur))
            cur = []
            i += len(hit)
            continue
        cur.append(ch)
        i += 1
    stages.append("".join(cur))

    for stage in stages:
        toks = _split_tokens(stage)
        while toks and _ASSIGN_RX.match(toks[0][0]):
            toks = toks[1:]  # leading VAR=value, including values full of slashes
        if not toks:
            continue  # the stage only set variables
        if Path(toks[0][0]).name.lower() in _PREAMBLE:
            continue
        return toks
    return []


def _placeholder(tok, was_quoted=False):
    # the heredoc delimiter is normally quoted (`<<'EOF'`), so these two come first
    if tok.startswith("<<"):
        return "<heredoc>"
    if tok[:1] in (">", "<") or tok[:2] in (">>", "2>"):
        return "<redirect>"
    if was_quoted:
        return "<path>" if ("/" in tok or "\\" in tok) else "<arg>"
    if _URL_RX.match(tok):
        return "<url>"
    if tok == "-" or tok.startswith("-"):
        return tok.split("=", 1)[0]
    if "/" in tok or "\\" in tok or tok.startswith("$") or ":" in tok[1:3]:
        return "<path>"
    if _SUBCOMMAND_RX.match(tok):
        return tok  # `post`, `sync`, `graphql`: the word that decides what the call does
    return "<arg>"


def command_shape(cmd):
    """Reduce a shell command to the part that decides its verdict.

    `cd /x && python tools/gh_api.py post /repos/a/b/releases body.json`
        -> `python gh_api.py post <path>`

    A heuristic, on purpose: the point is that two invocations that a reviewer
    would call "the same action" land on the same string, so that a shape which
    is sometimes allowed and sometimes denied becomes visible.
    """
    if not isinstance(cmd, str) or not cmd.strip():
        return ""
    toks = _first_real_stage(cmd.strip())
    if not toks:
        return ""
    out = [Path(toks[0][0]).name.lower()]
    rest = toks[1:]
    if out[0] in _INTERPRETERS and rest:
        # the script is the identity of the command, not an argument
        while rest and rest[0][0].startswith("-") and rest[0][0] != "-":
            flag = rest[0][0].split("=", 1)[0]
            out.append(flag)
            rest = rest[1:]
            if flag in _CODE_FLAGS:
                # `python -c "<the whole program>"`: what follows is a body, not a name
                return " ".join(out + ["<code>"])
        if rest and not rest[0][0].startswith(("<", ">")):
            out.append("-" if rest[0][0] == "-" else Path(rest[0][0]).name)
            rest = rest[1:]
    for tok, was_quoted in rest:
        if len(out) >= MAX_SHAPE_TOKENS:
            break
        ph = _placeholder(tok, was_quoted)
        out.append(ph)
        if ph in ("<heredoc>", "<redirect>"):
            break  # everything after this is the body, not the command
    return " ".join(out)


def request_shape(tool, tool_input, embedded_cmd=None):
    """The shape of one tool call, whatever tool it was."""
    tool = tool or "(unknown tool)"
    inp = tool_input if isinstance(tool_input, dict) else {}
    cmd = inp.get("command") if isinstance(inp.get("command"), str) else None
    if cmd is None and isinstance(embedded_cmd, str):
        cmd = embedded_cmd
    if tool in ("Bash", "BashOutput") or cmd:
        shape = command_shape(cmd or "")
        return shape or tool
    for key in ("file_path", "notebook_path", "path"):
        val = inp.get(key)
        if isinstance(val, str) and val:
            ext = Path(val).suffix.lower() or "(no ext)"
            return "%s %s" % (tool, ext)
    url = inp.get("url")
    if isinstance(url, str) and url:
        host = re.sub(r"^\w+://", "", url).split("/")[0].split("?")[0]
        return "%s %s" % (tool, host or "<url>")
    return tool


# --------------------------------------------------------------------------- #
# allowlist matching
# --------------------------------------------------------------------------- #
def parse_allow_rules(settings_paths):
    """Collect `permissions.allow` entries out of settings files that exist."""
    rules = []
    for p in settings_paths:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        allow = ((data.get("permissions") or {}).get("allow")) or []
        for entry in allow:
            if isinstance(entry, str) and entry.strip():
                rules.append((entry.strip(), str(p)))
    return rules


def _rule_regex(pattern):
    """`python tools/gh_api.py post:*` -> prefix match. `*` -> anything."""
    pat = pattern[:-2] if pattern.endswith(":*") else pattern
    anchored_tail = pat is not pattern or pattern.endswith("*")
    body = "".join(".*" if ch == "*" else re.escape(ch) for ch in pat.rstrip("*"))
    return re.compile("^" + body + (".*" if anchored_tail else "") + "$", re.S)


def allow_match(rules, tool, command):
    """Return the allow rule that covers this exact call, or None.

    Two things this refuses to do, because both would inflate the headline number:
      - let a rule for one tool excuse another (`Read(*)` never covers a Bash call);
      - let `Bash(cd *)` cover `cd /x && rm -rf /y` just because the string starts
        with `cd`. A rule only covers the stage that does the work, so its first
        token has to be that stage's executable.
    """
    for entry, src in rules:
        m = re.match(r"^([A-Za-z_][\w-]*)\((.*)\)$", entry, re.S)
        if not m:
            if entry == tool:
                return (entry, src)
            continue
        rule_tool, pattern = m.group(1), m.group(2)
        if rule_tool != tool:
            continue
        target = (command or "").strip()
        if not target:
            if pattern in ("*", ":*"):
                return (entry, src)
            continue
        stage = _first_real_stage(target)
        if stage:
            head_toks = _split_tokens(pattern.lstrip("/"))
            rule_head = head_toks[0][0].split(":")[0] if head_toks else ""
            if rule_head not in ("", "*"):
                if Path(rule_head).name.lower() != Path(stage[0][0]).name.lower():
                    continue
            candidates = (" ".join(t for t, _ in stage), target)
        else:
            candidates = (target,)
        rx = _rule_regex(pattern)
        if any(rx.match(c) for c in candidates):
            return (entry, src)
    return None


# --------------------------------------------------------------------------- #
# reading transcripts
# --------------------------------------------------------------------------- #
def _content_text(content):
    if isinstance(content, str):
        return content[:MAX_TEXT]
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str)]
        return "".join(parts)[:MAX_TEXT]
    return ""


def _ts(rec):
    raw = rec.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def read_events(lines):
    """Turn transcript lines into (requests_by_id, results) with nothing else kept."""
    requests, results = {}, []
    for line in lines:
        if '"tool_use"' not in line and '"tool_result"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        when = _ts(rec)
        for item in content:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "tool_use":
                tid = item.get("id")
                if isinstance(tid, str):
                    requests[tid] = {
                        "tool": item.get("name"),
                        "input": item.get("input"),
                        "sidechain": bool(rec.get("isSidechain")),
                    }
            elif kind == "tool_result":
                results.append({
                    "id": item.get("tool_use_id"),
                    "text": _content_text(item.get("content")),
                    "is_error": bool(item.get("is_error")),
                    "when": when,
                    "session": rec.get("sessionId"),
                    "sidechain": bool(rec.get("isSidechain")),
                })
    return requests, results


def collect(files, since=None, until=None):
    """Walk transcript files once and pull out every denial plus every call that ran."""
    denials, ran = [], Counter()
    read_files = 0
    read_results = 0
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                requests, results = read_events(fh)
        except OSError:
            continue
        read_files += 1
        for res in results:
            when = res["when"]
            if since and when and when < since:
                continue
            if until and when and when > until:
                continue
            read_results += 1
            req = requests.get(res["id"]) or {}
            verdict = classify_denial(res["text"]) if res["is_error"] else None
            tool = req.get("tool") or (verdict[2] if verdict else None)
            raw_cmd = None
            if isinstance(req.get("input"), dict) and isinstance(req["input"].get("command"), str):
                raw_cmd = req["input"]["command"]
            elif verdict and verdict[3]:
                raw_cmd = verdict[3]
            shape = request_shape(tool, req.get("input"), raw_cmd)
            if verdict is None:
                ran[shape] += 1
                continue
            denials.append({
                "layer": verdict[0],
                "reason": verdict[1],
                "tool": tool or "(unknown tool)",
                "shape": shape,
                "command": raw_cmd,
                "when": when,
                "day": when.date().isoformat() if when else "(no date)",
                "session": res["session"],
                "sidechain": res["sidechain"] or bool(req.get("sidechain")),
                "source": str(path),
            })
    denials.sort(key=lambda d: (d["when"] or datetime.min.replace(tzinfo=timezone.utc), d["shape"]))
    return {"denials": denials, "ran": ran, "files": read_files, "results": read_results}


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #
def analyze(collected, allow_rules=(), window=120):
    denials = collected["denials"]
    ran = collected["ran"]

    by_layer = Counter(d["layer"] for d in denials)
    by_reason = Counter((d["layer"], d["reason"]) for d in denials)
    by_day = Counter(d["day"] for d in denials)
    shapes_by_layer = defaultdict(Counter)
    for d in denials:
        shapes_by_layer[d["layer"]][d["shape"]] += 1

    denied_shapes = Counter(d["shape"] for d in denials)
    flapping = []
    for shape, n in denied_shapes.items():
        if ran.get(shape):
            flapping.append({
                "shape": shape,
                "denied": n,
                "ran": ran[shape],
                "layers": sorted({d["layer"] for d in denials if d["shape"] == shape}),
            })
    flapping.sort(key=lambda f: (-f["denied"], f["shape"]))

    self_denied = []
    for d in denials:
        if d["layer"] == "own-hook":
            continue  # your own hook overriding your own allowlist is a design, not a gap
        hit = allow_match(allow_rules, d["tool"], d["command"])
        if hit:
            self_denied.append({"shape": d["shape"], "layer": d["layer"], "reason": d["reason"],
                                "rule": hit[0], "rule_source": hit[1], "day": d["day"]})

    collateral = []
    for prev, cur in zip(denials, denials[1:]):
        if not prev["when"] or not cur["when"]:
            continue
        gap = (cur["when"] - prev["when"]).total_seconds()
        if 0 <= gap <= window and cur["shape"] != prev["shape"] and cur["session"] == prev["session"]:
            collateral.append({"after": prev["shape"], "then": cur["shape"],
                               "seconds": round(gap, 1), "layer": cur["layer"], "reason": cur["reason"]})

    walls = []
    for shape, n in denied_shapes.items():
        if n >= 3 and not ran.get(shape):
            layers = sorted({d["layer"] for d in denials if d["shape"] == shape})
            days = sorted({d["day"] for d in denials if d["shape"] == shape})
            walls.append({"shape": shape, "denied": n, "layers": layers, "days": days})
    walls.sort(key=lambda w: (-w["denied"], w["shape"]))

    return {
        "totals": {
            "denials": len(denials),
            "files": collected["files"],
            "results": collected["results"],
            "calls_that_ran": sum(ran.values()),
            "distinct_denied_shapes": len(denied_shapes),
            "in_subagents": sum(1 for d in denials if d["sidechain"]),
        },
        "by_layer": {layer: by_layer.get(layer, 0) for layer in LAYERS},
        "by_reason": [{"layer": k[0], "reason": k[1], "count": v} for k, v in by_reason.most_common()],
        "by_day": [{"day": k, "count": v} for k, v in sorted(by_day.items())],
        "top_shapes": {layer: shapes_by_layer[layer].most_common(5) for layer in LAYERS},
        "flapping": flapping,
        "self_denied": self_denied,
        "collateral": collateral,
        "walls": walls,
        "window_seconds": window,
        "allow_rules": len(allow_rules),
    }


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def render(report, show_raw=False, denials=()):
    t = report["totals"]
    out = []
    out.append("permission-gap - what stopped the agent, by layer")
    out.append("read %d transcript file(s), %d tool results: %d denied, %d ran"
               % (t["files"], t["results"], t["denials"], t["calls_that_ran"]))
    if t["denials"] == 0:
        out.append("")
        out.append("no denials in this window. Nothing stopped the agent.")
        return "\n".join(out)
    out.append("")
    out.append("%-32s %8s  %s" % ("layer", "denials", "most denied shape"))
    for layer in LAYERS:
        n = report["by_layer"][layer]
        top = report["top_shapes"][layer]
        top_s = "%s (%d)" % (redact(top[0][0]), top[0][1]) if top else "-"
        out.append("%-32s %8d  %s" % (LAYER_LABEL[layer], n, top_s if n else "-"))
    out.append("")
    out.append("reasons given (the string the model was handed):")
    for row in report["by_reason"][:12]:
        out.append("  %-11s %-56s %d" % (row["layer"], redact(row["reason"])[:56], row["count"]))

    out.append("")
    if report["self_denied"]:
        out.append("YOUR OWN ALLOWLIST SAYS YES AND IT WAS DENIED ANYWAY: %d" % len(report["self_denied"]))
        seen = set()
        for row in report["self_denied"]:
            key = (row["shape"], row["reason"])
            if key in seen:
                continue
            seen.add(key)
            out.append("  %s  <- %s  [%s: %s]" % (redact(row["shape"]), row["rule"], row["layer"], redact(row["reason"])))
    elif report["allow_rules"]:
        out.append("no denial matched your own allow rules (%d rules read)" % report["allow_rules"])
    else:
        out.append("no allow rules were read, so the self-denied count is not measured (pass --settings)")

    out.append("")
    if report["flapping"]:
        out.append("FLAPPING - the same shape both ran and was denied (the verdict is not a rule):")
        for row in report["flapping"][:10]:
            out.append("  %-46s denied %d / ran %d  [%s]"
                       % (redact(row["shape"])[:46], row["denied"], row["ran"], ",".join(row["layers"])))
    else:
        out.append("no shape both ran and was denied: every verdict held.")

    if report["walls"]:
        out.append("")
        out.append("WALLS - denied 3+ times and never once ran:")
        for row in report["walls"][:10]:
            out.append("  %-46s denied %d  [%s]  %s"
                       % (redact(row["shape"])[:46], row["denied"], ",".join(row["layers"]),
                          row["days"][0] + (".." + row["days"][-1] if len(row["days"]) > 1 else "")))

    if report["collateral"]:
        out.append("")
        out.append("COLLATERAL - a different shape denied within %ds of a denial, same session: %d"
                   % (report["window_seconds"], len(report["collateral"])))
        for row in report["collateral"][:8]:
            out.append("  after %-30s -> %-30s %ss  [%s]"
                       % (redact(row["after"])[:30], redact(row["then"])[:30], row["seconds"], row["layer"]))
        out.append("  (a denial and the next call being unrelated does not prove one caused the other;")
        out.append("   it is the number to look at before blaming your own code for the second one.)")

    if show_raw and denials:
        out.append("")
        out.append("raw commands (credential-shaped strings masked - read before you paste this anywhere):")
        for d in denials[:20]:
            out.append("  %s  %-11s %s" % (d["day"], d["layer"], redact(d["command"] or d["shape"])[:160]))

    out.append("")
    out.append("What the split is for: own-hook is yours to fix, allowlist is one line of config,")
    out.append("classifier is a wall you route around, human is a conversation. A single")
    out.append("\"failures\" count sends you to the wrong one of those four.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def default_transcript_root():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "projects"


def find_files(roots, explicit):
    files = [Path(p) for p in explicit]
    for root in roots:
        root = Path(root)
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.jsonl")))
    seen, out = set(), []
    for f in files:
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def parse_date(text):
    if not text:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count what stopped your agent, by layer.")
    ap.add_argument("mode", nargs="?", default="scan", choices=["scan"])
    ap.add_argument("--dir", action="append", default=[],
                    help="transcript directory or file (default: ~/.claude/projects)")
    ap.add_argument("--file", action="append", default=[], help="one transcript file (repeatable)")
    ap.add_argument("--settings", action="append", default=[],
                    help="settings.json to read permissions.allow from (repeatable)")
    ap.add_argument("--since", help="ignore results before this date (YYYY-MM-DD)")
    ap.add_argument("--until", help="ignore results after this date (YYYY-MM-DD)")
    ap.add_argument("--window", type=int, default=120, help="collateral window in seconds (default 120)")
    ap.add_argument("--raw", action="store_true", help="also print the denied commands, credentials masked")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        since, until = parse_date(args.since), parse_date(args.until)
    except ValueError as exc:
        print("bad date: %s" % exc, file=sys.stderr)
        return 1

    roots = args.dir or ([] if args.file else [default_transcript_root()])
    files = find_files(roots, args.file)
    if not files:
        print("no transcripts found. Looked in: %s" % ", ".join(str(r) for r in roots) or "(nothing)",
              file=sys.stderr)
        return 2

    settings = args.settings
    if not settings:
        home = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        for cand in (Path(".claude/settings.json"), Path(".claude/settings.local.json"),
                     home / "settings.json", home / "settings.local.json"):
            if cand.is_file():
                settings.append(str(cand))
    rules = parse_allow_rules(settings)

    collected = collect(files, since=since, until=until)
    report = analyze(collected, allow_rules=rules, window=args.window)
    if collected["results"] == 0:
        print("read %d file(s) but no tool results in that window" % collected["files"], file=sys.stderr)
        return 2

    if args.json:
        payload = dict(report)
        payload["denials"] = [
            {k: (redact(v) if k in ("command", "shape", "reason") else v)
             for k, v in d.items() if k != "when"}
            for d in collected["denials"]
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render(report, show_raw=args.raw, denials=collected["denials"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
