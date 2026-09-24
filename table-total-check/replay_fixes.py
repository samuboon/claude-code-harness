# -*- coding: utf-8 -*-
"""Replay public commits that corrected a "Total" in a Markdown table: was it flagged before the fix?

    python replay_fixes.py                              # the commits in FIXES (--half "held out")
    python replay_fixes.py --updates                    # the commits in UPDATES
    python replay_fixes.py --files list.jsonl --half tune   # files pinned at a commit (see below)
    python replay_fixes.py owner/name@SHA ...           # any other public commits
    python replay_fixes.py --search all > cands.jsonl   # the commit-search queries in QUERIES
    python replay_fixes.py --classify cands.jsonl       # keep those whose patch shows a total fix
    python replay_fixes.py --checker old/table_total_check.py ...   # replay with another version
    python replay_fixes.py --show owner/name@SHA        # print the table rows the commit changed

For each commit it reads the patch from github.com (`<sha>.patch`), reads each Markdown file at the
commit from raw.githubusercontent.com, rebuilds the file as it was just before by undoing the
patch, and runs table_total_check on both.

What the commit fixed is read from the diff and the file alone, before the checker runs. A table
the commit touched is one of:

  row      only rows labelled Total / Subtotal / 合計 ... changed, and only in their numbers
           (the rows being added up did not change, so the old total was wrong by construction)
  column   only cells under a column headed Total / 合計 ... changed, and only in their numbers
  update   rows being added up changed as well (a row added, a count bumped) -- nothing says the
           table was wrong, so an error after the commit is either a false alarm or a mistake the
           commit left in; each one is read by hand ("flagged" below)

and per fix it prints:

  caught   an error before the fix on a row the commit changed, none after
  partly   an error before on what it changed, and still one after
  warned   only a warning before on what it changed
  missed   nothing before on what it changed (the reason it left the cell alone, if it gave one)

and per update: clean (the sums it judged add up after the commit), flagged (an error after it),
not judged (nothing in the table it could add up).

Nothing is written to disk and nothing is sent anywhere. The patch and the raw file are not API
calls; --search is one call per query (GitHub allows 10 a minute without a key).
"""
import argparse
import email.utils
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import table_total_check as t  # noqa: E402

UA = {"User-Agent": "table-total-check-replay"}

# (repository, commit, kind, half) -- the README's replay table: found with the queries below, kept
# only when the patch shows a total-only fix, split in two by commit id before any tuning.
FIXES = [
    ("maraulsav/Qbot", "354b8ab35221", "row", "tune"),
    ("clankanoid/gaming-pc-build-2026", "54eea980117c", "row", "held out"),
    ("MasOsby/EECS-581-G17", "81ada1cc5bdd", "row", "tune"),
    ("ernestngenest/nez-harness", "9763e6eaa379", "row", "held out"),
    ("abhinay-sambherao/HeatScanAI", "9fd51f376159", "row+update", "tune"),
    ("Juwan-Hwang/moon-certified", "a638386eeb40", "row", "held out"),
]

# (repository, commit, half) -- commits that changed the rows and the total together.
UPDATES = [
    ("fulgur-rs/flpdf", "01a01aee4185", "tune"),
    ("tripodxu/captrue_recognizer", "039a226766a3", "held out"),
    ("tsujimoto-mdc/zaico-yayoi-dashboard", "07aafc7ab9ba", "tune"),
    ("darkraider01/rust-compile-time-instrumentation-", "0a5b7b872fd9", "held out"),
    ("mohit-nagaraj/sentinel", "0fdcac5dc568", "tune"),
    ("CS3227-2610-MP2-NUSynapxe/CS3227-2610-MP2", "1493566ac296", "held out"),
    ("lightspeedwp/.github", "14977f25c3fb", "tune"),
    ("gleiston-guerrero/MediCita", "190c0f32e555", "held out"),
    ("mraysmit/raftlog", "1c01bd6fa6bf", "tune"),
    ("cloudshare360/aws-cloud-engineer-with-nodejs", "1d64deff050d", "held out"),
    ("gleiston-guerrero/MediCita", "1ea45026e507", "tune"),
    ("ptigasis-Alexander/MediCita_ISR401_C", "1ea45026e507", "held out"),
    ("notadix/AI_Driven_Data_Center_Cooling_Cloud_Project_2026", "239440d653ae", "tune"),
    ("khojiakbarr/data-table", "2930c03b361c", "held out"),
    ("gurudhiman75-hash/Functional-Interface", "2d2af2d7286e", "tune"),
    ("Greg-T8/LearningAzure", "2f5e2b1516d4", "held out"),
    ("docxology/steganographer", "31c037293623", "tune"),
    ("tinyhumansai/openhuman", "332d1687314b", "held out"),
    ("pirl-unc/mhcseqs", "334e4090db5c", "tune"),
    ("VaradSinghal/payasyoumaintain", "3d484c473e6e", "held out"),
    ("Greg-T8/LearningAzure", "4813eac51687", "tune"),
    ("amakalarry/Synthetic-Crime-Scene-Research", "4981662145ba", "held out"),
    ("qsmtco/Phosphor", "51bbc837deea", "tune"),
    ("fulgur-rs/flpdf", "5306e8313641", "held out"),
    ("Tenshi1308/aios-glm", "59005193ff0b", "tune"),
    ("laurenchenarides/dare_research", "5d40d922d153", "held out"),
    ("rtrlpz/MIS-COLLECTIONS", "62e30f324da3", "tune"),
    ("jedarden/drawrace", "71d95fb11784", "held out"),
    ("sgveasypunto-ia/PArkOS", "730cd31bc691", "tune"),
    ("linusx7/SAS821S_T09_eGov_Portal_Protection", "78484b49bd73", "held out"),
    ("kemiller2002/vigila", "804601bfea6b", "tune"),
    ("eshu-hq/eshu", "84d24a5f3cfe", "held out"),
    ("shivkottur04/LeetCode-Solutions", "8c8e29866631", "tune"),
    ("leonampa/netpuck", "8d2f81868db5", "held out"),
    ("Annicat3/Timer-Dongle", "99441722a025", "tune"),
    ("steveramos21/ai-dba", "9ac7fe975c9a", "held out"),
    ("Tattzy25/ucp-git", "9bd6ed648d2f", "tune"),
    ("netplus/leetcode", "a1ed1a068060", "held out"),
    ("VELARJUN0201/HACKERRANK", "a7dbe72a745b", "tune"),
    ("qamarsobhy7-source/Smart-Knowledge-Gap-System", "a7dcc638dd83", "held out"),
    ("JasonMomanyi/EO-AI_Crop_Intelligence_Platform", "ae96f8f51c90", "tune"),
    ("OriginalSoseji/grookai_vault", "b251b0205e8c", "held out"),
    ("shrird2010-beep/The-real-goated-goal", "b7796eaa7adc", "tune"),
    ("ishadowland/iswiki", "b95e4fc2de9f", "held out"),
    ("lijianqii/rbox", "bd41c1b9e56f", "tune"),
    ("gleiston-guerrero/MediCita", "bdaf0e4fa964", "held out"),
    ("fasisandhu/squatchscout", "be5dd9ccd617", "tune"),
    ("Rabieulawal/alarmpcb", "c8174898e26f", "held out"),
    ("Rabieulawal/alarmpcb", "d4385bcae1f5", "tune"),
    ("0xPabloLI/inside-china-ai", "d87d41129fda", "held out"),
    ("tougoumajudith-droid/Risk-Analyst-Portfolio-Lab1-AD-Healthcare", "deb9881d0267", "tune"),
    ("venjiang/quicz", "e0c9386dda45", "held out"),
    ("Prakeya/Nivara", "e0ffe640f9ef", "tune"),
    ("sardorbek-suyunov/nordbank-data-platform", "e6b68dba6c57", "held out"),
    ("teja05-45/ios-storage-cleaner", "e77d3277c2cb", "tune"),
    ("raz34900/SecureSign", "ed637c94c2c5", "held out"),
    ("Gingernut08/eGuitar", "edb4024807db", "tune"),
    ("az-said/Interlock", "edf6c2270e7b", "held out"),
    ("alleyneja/mediahub-configs", "f0396c8eb48e", "tune"),
    ("qppd/umbrella-dryer-v2", "f13d367b4e72", "held out"),
    ("sayan629/Leet_Code", "fcf7ea1c7883", "tune"),
]

QUERIES = [
    "fix total", "fix totals", "fix total count", "correct total", "correct totals", "fix sum",
    "wrong total", "fix table total", "fix the total", "total was wrong", "fix totals in readme",
    "recalculate total", "fix total in readme", "update totals", "fix total row", "fix summary table",
    "fix total number", "incorrect total", "fix count in table", "fix total in table", "total typo",
    "update total count", "fix totals table", "correct sum",
    # a second pass, after the first 24 turned up 2 total-only fixes in 1,029 commits: aimed at docs
    "total readme", "totals readme", "readme total count", "fix readme table", "fix table readme",
    "fix count readme", "fix counts readme", "fix totals docs", "fix table arithmetic",
    "table arithmetic", "fix the sums", "sum mismatch", "does not add up", "totals add up",
]
QUERIES_FIRST = 24


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429) and i + 1 < tries:
                time.sleep(20)
                continue
            if i + 1 == tries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i + 1 == tries:
                raise
            time.sleep(3)
    return None


def search(query, pages=1):
    out = []
    for page in range(1, pages + 1):
        u = ("https://api.github.com/search/commits?per_page=100&page=%d&q=" % page) + urllib.parse.quote(query)
        req = urllib.request.Request(u, headers=dict(UA, Accept="application/vnd.github+json"))
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 422, 429):
                time.sleep(65)
                with urllib.request.urlopen(req, timeout=40) as r:
                    d = json.load(r)
            else:
                raise
        for it in d.get("items", []):
            if len(it.get("parents", [])) > 1:
                continue            # merge commits: the patch is empty; the fix is in a parent
            out.append((it["repository"]["full_name"], it["sha"], it["commit"]["message"].splitlines()[0]))
        time.sleep(7)
    return out


# ---------------------------------------------------------------- patches

def split_patch(text):
    """(date, {path: [hunks]}) for the first commit in a .patch. A hunk is
    (old_start, old_len, new_start, new_len, [lines with their ' ', '-', '+' marks])."""
    date = None
    m = re.search(r"^Date: (.+)$", text, re.M)
    if m:
        try:
            date = email.utils.parsedate_to_datetime(m.group(1).strip()).date()
        except (TypeError, ValueError):
            date = None
    files, cur, hunk = {}, None, None
    for ln in text.split("\n"):
        if ln.startswith("diff --git "):
            cur = hunk = None
            continue
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = p[2:] if p.startswith("b/") else (None if p == "/dev/null" else p)
            if cur is not None:
                files.setdefault(cur, [])
            continue
        if ln.startswith("--- "):
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", ln)
        if m and cur is not None:
            hunk = [int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), []]
            files[cur].append(hunk)
            continue
        if hunk is not None and ln[:1] in (" ", "-", "+", "\\"):
            if not ln.startswith("\\"):
                hunk[4].append(ln)
        elif ln.startswith("-- ") or ln == "--":
            hunk = None          # the mail signature at the end of a .patch
    return date, files


def undo(after, hunks):
    """The file before the commit, from the file after it and the commit's hunks."""
    new = after.split("\n")
    out, pos = [], 0
    for os_, ol, ns, nl, body in hunks:
        start = ns - 1 if nl > 0 else ns
        out.extend(new[pos:start])
        out.extend(ln[1:] for ln in body if ln[:1] in (" ", "-"))
        pos = start + sum(1 for ln in body if ln[:1] in (" ", "+"))
    out.extend(new[pos:])
    return "\n".join(out)


def change_blocks(hunks):
    """Runs of removed-then-added lines: [([(old_no, text)], [(new_no, text)])]."""
    out = []
    for os_, ol, ns, nl, body in hunks:
        o, n = os_, ns
        rem, add = [], []
        for ln in body + [" "]:
            k = ln[:1]
            if k == "-":
                if add:
                    out.append((rem, add))
                    rem, add = [], []
                rem.append((o, ln[1:]))
                o += 1
            elif k == "+":
                add.append((n, ln[1:]))
                n += 1
            else:
                if rem or add:
                    out.append((rem, add))
                    rem, add = [], []
                o += 1
                n += 1
    return out


def is_row(text):
    return "|" in text and not t.is_delim(text) and len(t.split_row(text)) >= 2


DIGITS = re.compile(r"\d[\d,.  ]*")


def numbers_only(a, b):
    """The columns where two versions of a row differ, if every difference is in a number.

    Read without the checker's number parser (so what counts as a fix does not depend on what the
    checker can read): the two cells must be the same once their digit runs are blanked out, and
    both must hold digits."""
    if len(a) != len(b):
        return None
    cols = []
    for j, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        if not (DIGITS.search(x) and DIGITS.search(y)) or DIGITS.sub("#", x) != DIGITS.sub("#", y):
            return None
        cols.append(j)
    return cols


def table_at(tables, line):
    for tb in tables:
        if tb.line <= line <= (tb.rows[-1][0] if tb.rows else tb.line):
            return tb
    return None


def classify_file(before, after, hunks):
    """[(kind, table_line_after, old line numbers of changed rows, new line numbers)] -- from the diff alone."""
    tb_after = t.find_tables(after)
    per = {}
    for rem, add in change_blocks(hunks):
        rrows = [(o, x) for o, x in rem if is_row(x)]
        arows = [(n, x) for n, x in add if is_row(x)]
        if not rrows and not arows:
            continue
        anchor = arows[0][0] if arows else None
        tb = table_at(tb_after, anchor) if anchor else None
        if tb is None:
            continue
        # only tables that have a total: a Total row, or a column headed Total
        if not (any(t.is_total_label(h) for h in tb.header[1:]) or
                any(t.is_total_label(c) for _, cells in tb.rows for c in cells[:2])):
            continue
        rec = per.setdefault(tb.line, {"tb": tb, "old": [], "new": [], "kinds": set()})
        rec["old"] += [o for o, _ in rrows]
        rec["new"] += [n for n, _ in arows]
        if len(rrows) != len(arows) or len(rrows) != len(rem) or len(arows) != len(add):
            rec["kinds"].add("update")
            continue
        totcols = {j for j, h in enumerate(tb.header) if t.is_total_label(h)}
        for (o, x), (n, y) in zip(rrows, arows):
            a, b = t.split_row(x), t.split_row(y)
            cols = numbers_only(a, b)
            if cols is None:
                rec["kinds"].add("update")
                continue
            if not cols:
                continue
            lab = next((c for c in b[:2] if c), "")
            if t.is_total_label(lab):
                rec["kinds"].add("row")
            elif totcols and set(cols) <= totcols:
                rec["kinds"].add("column")
            else:
                rec["kinds"].add("update")
    out = []
    for line, rec in sorted(per.items()):
        k = rec["kinds"]
        if not k:
            continue
        kind = "update" if "update" in k else "+".join(sorted(k))
        out.append((kind, line, rec["old"], rec["new"]))
    return out


def md(path):
    return path.lower().endswith(t.EXTS)


def replay(repo, sha, checker=t):
    patch = get("https://github.com/%s/commit/%s.patch" % (repo, sha))
    if not patch:
        return {"repo": repo, "sha": sha[:12], "result": "unreadable", "why": "no patch"}
    date, files = split_patch(patch)
    res = {"repo": repo, "sha": sha[:12], "date": date.isoformat() if date else None, "tables": []}
    order = ["caught", "partly", "warned", "missed", "flagged", "clean", "not judged"]
    worst = None
    for path, hunks in files.items():
        if not md(path):
            continue
        after = get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, urllib.parse.quote(path)))
        if after is None:
            continue
        before = undo(after, hunks)
        tabs = classify_file(before, after, hunks)
        if not tabs:
            continue
        cb, ca = checker.check_text(before, path), checker.check_text(after, path)
        tb_before, tb_after = checker.find_tables(before), checker.find_tables(after)
        for kind, tline, old, new in tabs:
            tbb = table_at(tb_before, old[0]) if old else None
            tba = table_at(tb_after, tline)
            span_b = (tbb.line, tbb.rows[-1][0]) if tbb and tbb.rows else (0, -1)
            span_a = (tba.line, tba.rows[-1][0]) if tba and tba.rows else (0, -1)
            fb = [f for f in cb.findings if span_b[0] <= f["line"] <= span_b[1]]
            fa = [f for f in ca.findings if span_a[0] <= f["line"] <= span_a[1]]
            eb = [f for f in fb if f["level"] == "error" and f["line"] in old]
            wb = [f for f in fb if f["level"] == "warning" and f["line"] in old]
            ea = [f for f in fa if f["level"] == "error" and f["line"] in new]
            # how many sums the checker could judge in this table, after the commit
            lines_a = after.split("\n")
            judged = checker.check_text("\n".join(lines_a[span_a[0] - 1:span_a[1]]), path).stats["checked"] \
                if span_a[1] >= span_a[0] > 0 else 0
            if kind == "update":
                errs_b = [f for f in fb if f["level"] == "error"]
                errs_a = [f for f in fa if f["level"] == "error"]
                r = "flagged" if errs_a else ("clean" if judged else "not judged")
                rec = {"path": path, "line": tline, "kind": kind, "result": r, "judged": judged,
                       "before": [fmt(f) for f in errs_b], "after": [fmt(f) for f in errs_a]}
            else:
                if eb and not ea:
                    r = "caught"
                elif eb:
                    r = "partly"
                elif wb:
                    r = "warned"
                else:
                    r = "missed"
                why = [w for ln, what, w in cb.unjudged_list if ln in old or (tbb and ln == tbb.line)]
                rec = {"path": path, "line": tline, "kind": kind, "result": r, "judged": judged,
                       "before": [fmt(f) for f in eb + wb], "after": [fmt(f) for f in ea],
                       "after_other": [fmt(f) for f in fa if f not in ea and f["level"] == "error"],
                       "not_judged": why[:3]}
            res["tables"].append(rec)
            if worst is None or order.index(r) < order.index(worst):
                worst = r
    res["result"] = worst or "no table total changed"
    res["kinds"] = sorted({x["kind"] for x in res["tables"]})
    return res


def fmt(f):
    return "%d: %s %s  %s" % (f["line"], f["level"], f["code"], f["message"])


def classify(repo, sha):
    patch = get("https://github.com/%s/commit/%s.patch" % (repo, sha))
    if not patch:
        return None
    date, files = split_patch(patch)
    kinds = []
    for path, hunks in files.items():
        if not md(path):
            continue
        # the patch alone first: skip files where no removed/added line is a table row
        if not any(is_row(ln[1:]) for h in hunks for ln in h[4] if ln[:1] in "+-"):
            continue
        after = get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, urllib.parse.quote(path)))
        if after is None:
            continue
        before = undo(after, hunks)
        kinds += [k for k, _, _, _ in classify_file(before, after, hunks)]
    return sorted(set(kinds)), (date.isoformat() if date else None)


def classify_cands(path, workers=8):
    from concurrent.futures import ThreadPoolExecutor
    cands, seen = [], set()
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if not ln.strip() or ln.startswith("#"):
                continue
            d = json.loads(ln)
            if (d["repo"], d["sha"]) not in seen:
                seen.add((d["repo"], d["sha"]))
                cands.append(d)

    def one(d):
        try:
            return d, classify(d["repo"], d["sha"])
        except Exception as ex:          # an unreadable patch is left out and counted
            return d, ("error", repr(ex)[:80])

    n = {"fix": 0, "update": 0, "error": 0}
    with ThreadPoolExecutor(workers) as ex:
        for d, r in ex.map(one, cands):
            if r is None or r[0] == "error":
                n["error"] += 1
                continue
            if r[0]:
                n["update" if r[0] == ["update"] else "fix"] += 1
                print(json.dumps({"repo": d["repo"], "sha": d["sha"], "kinds": r[0], "date": r[1],
                                  "msg": d.get("msg")}, ensure_ascii=False))
                sys.stdout.flush()
    print("# %d candidates: %d show a total-only fix, %d only an update, %d unreadable"
          % (len(cands), n["fix"], n["update"], n["error"]), file=sys.stderr)


def show(repo, sha):
    patch = get("https://github.com/%s/commit/%s.patch" % (repo, sha))
    date, files = split_patch(patch or "")
    print("%s@%s %s" % (repo, sha[:12], date))
    for path, hunks in files.items():
        if not md(path):
            continue
        for rem, add in change_blocks(hunks):
            if any(is_row(x) for _, x in rem + add):
                for o, x in rem:
                    print("   -%5d %s" % (o, x[:170]))
                for n, x in add:
                    print("   +%5d %s" % (n, x[:170]))


def files_from_code_search(paths):
    """Turn saved GitHub code-search responses (JSON) into a file list, halved by a hash of repo/path.

    The half is fixed by the name alone, before anything is read, so the "held out" half cannot
    be chosen after seeing what the checker says about it."""
    import zlib
    seen = set()
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        for it in d.get("items", []):
            repo = it["repository"]["full_name"]
            m = re.search(r"/blob/([0-9a-f]{40})/", it.get("html_url", ""))
            if not m or (repo, it["path"]) in seen:
                continue
            seen.add((repo, it["path"]))
            half = "held out" if zlib.crc32(("%s/%s" % (repo, it["path"])).encode("utf-8")) % 2 else "tune"
            print(json.dumps({"repo": repo, "path": it["path"], "ref": m.group(1), "half": half}))


def run_files(listing, checker=t, half=None, workers=8):
    """Check each listed file at its pinned commit; print one JSON line per file that has a total."""
    from concurrent.futures import ThreadPoolExecutor
    todo = []
    with open(listing, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                d = json.loads(ln)
                if not half or d["half"] == half:
                    todo.append(d)

    def one(d):
        try:
            txt = get("https://raw.githubusercontent.com/%s/%s/%s" % (d["repo"], d["ref"], urllib.parse.quote(d["path"])))
        except Exception as ex:
            return d, None, repr(ex)[:80]
        if txt is None:
            return d, None, "missing"
        return d, checker.check_text(txt, "%s/%s" % (d["repo"], d["path"])), None

    n = {"files": 0, "with_totals": 0, "errors": 0, "warnings": 0, "unreadable": 0}
    with ThreadPoolExecutor(workers) as ex:
        for d, ch, err in ex.map(one, todo):
            if ch is None:
                n["unreadable"] += 1
                continue
            n["files"] += 1
            st = ch.stats
            if not (st["total_rows"] or st["total_cols"] or st["share_cols"]):
                continue
            n["with_totals"] += 1
            e = sum(1 for f in ch.findings if f["level"] == "error")
            n["errors"] += e
            n["warnings"] += len(ch.findings) - e
            print(json.dumps({"repo": d["repo"], "path": d["path"], "ref": d["ref"][:12], "half": d["half"],
                              "stats": st, "not_judged": ch.unjudged,
                              "findings": [fmt(f) for f in ch.findings]}, ensure_ascii=False))
            sys.stdout.flush()
    print("# %(files)d files read (%(unreadable)d unreadable), %(with_totals)d with a total: "
          "%(errors)d errors, %(warnings)d warnings" % n, file=sys.stderr)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("commits", nargs="*", help="owner/name@SHA")
    ap.add_argument("--half", help='only the commits in this half: "tune" or "held out"')
    ap.add_argument("--updates", action="store_true", help="replay the UPDATES list instead of FIXES")
    ap.add_argument("--search", action="append", help="a commit-search query (repeatable); 'all' = QUERIES")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--checker", help="path to another table_total_check.py (to replay an earlier version)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--classify", help="a file of --search output: keep the commits whose patch shows a fix")
    ap.add_argument("--from-code-search", nargs="+", metavar="JSON",
                    help="saved code-search responses -> a file list with its halves")
    ap.add_argument("--lines", help="owner/name@ref:path:start-end -- print those lines of a file at a commit")
    ap.add_argument("--files", help="a file list (from --from-code-search): check each file at its commit")
    a = ap.parse_args(argv)
    checker = t
    if a.checker:
        import importlib.util
        spec = importlib.util.spec_from_file_location("checker_alt", a.checker)
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
    if a.classify:
        classify_cands(a.classify)
        return 0
    if a.from_code_search:
        files_from_code_search(a.from_code_search)
        return 0
    if a.files:
        run_files(a.files, checker, a.half)
        return 0
    if a.search:
        qs = {"all": QUERIES, "first": QUERIES[:QUERIES_FIRST],
              "second": QUERIES[QUERIES_FIRST:]}.get(a.search[0]) if len(a.search) == 1 else None
        qs = qs or a.search
        seen = set()
        for q in qs:
            for repo, sha, msg in search(q, a.pages):
                if (repo, sha) not in seen:
                    seen.add((repo, sha))
                    print(json.dumps({"repo": repo, "sha": sha, "msg": msg, "query": q}, ensure_ascii=False))
                    sys.stdout.flush()
        return 0
    if a.lines:
        # owner/name@ref:path:start-end -- print those lines of the file at that commit
        spec, rng = a.lines.rsplit(":", 1)
        repo_ref, path = spec.split(":", 1)
        repo, ref = repo_ref.split("@")
        lo, hi = (int(x) for x in rng.split("-"))
        txt = get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, ref, urllib.parse.quote(path))) or ""
        for i, ln in enumerate(txt.split("\n")[lo - 1:hi], lo):
            print("%5d %s" % (i, ln[:240]))
        return 0
    if a.show:
        for c in a.commits:
            show(*c.split("@"))
        return 0
    if a.commits:
        todo = [tuple(c.split("@")) for c in a.commits]
    elif a.updates:
        todo = [(r, s) for r, s, h in UPDATES if not a.half or h == a.half]
    else:
        todo = [(r, s) for r, s, k, h in FIXES if not a.half or h == a.half]
    tally = {}
    for repo, sha in todo:
        try:
            r = replay(repo, sha, checker)
        except Exception as ex:          # one unreadable commit does not stop the table
            r = {"repo": repo, "sha": sha[:12], "result": "unreadable", "why": repr(ex)[:120]}
        tally[r["result"]] = tally.get(r["result"], 0) + 1
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print("%-11s %s@%s %s" % (r["result"], r["repo"], r["sha"], ",".join(r.get("kinds", []))))
            for tb in r.get("tables", []):
                for x in tb["before"][:2]:
                    print("    before " + x[:220])
                for x in tb["after"][:2]:
                    print("    after  " + x[:220])
                for x in tb.get("not_judged", [])[:2]:
                    print("    not judged: " + x)
        sys.stdout.flush()
    if not a.json:
        print("; ".join("%s %d" % kv for kv in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
