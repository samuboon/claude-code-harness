# -*- coding: utf-8 -*-
"""Recompute the "Total" rows and columns of the Markdown tables in a file, and list the ones that disagree.

    python table_total_check.py README.md
    python table_total_check.py docs/            # every .md / .markdown / .mdx below
    python table_total_check.py docs/ --json
    python table_total_check.py README.md --why  # also say why each unjudged cell was left alone

What it checks, in a GitHub-flavoured pipe table:

  TOTAL     a row labelled Total / Sum / Subtotal / Grand total / 合計 / 小計 / 計 ... against the
            rows above it (or below it, when the total row comes first)
  ROWTOTAL  a column headed Total / Sum / 合計 ... against the columns next to it, row by row
  SHARE     a percentage column against count / total (when the table has a total row)

It never guesses. A cell it cannot read one way only -- text among the numbers, "~120", mixed
units (KB next to MB), a struck-through value -- is counted as "not judged", not flagged. A total
that is not a sum but is the mean, median, max or min of the rows, or the ratio or difference of
two other totals, is accepted as that (a "Total" row under a column of averages is common).

Integers and money are compared exactly. Decimals, percentages and measurements (ms, MB, h ...)
are allowed the rounding their own digits imply: n parts shown to 1 decimal can drift by n x 0.05.

Exit code: 1 if there is an error, 0 otherwise (2 = bad arguments). Nothing is written or sent.
Standard library only.
"""
import argparse
import json
import os
import re
import statistics
import sys
from decimal import Decimal, InvalidOperation

SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv", "venv",
             "site-packages", "__pycache__", ".tox", ".mypy_cache", "target"}
EXTS = (".md", ".markdown", ".mdx")

# ---------------------------------------------------------------- labels

TOTAL_RE = re.compile(
    r"(?:grand[\s-]*)?totals?|sub[\s-]*totals?|sum|"
    r"合計|小計|総計|総合計|計|合计|小计|总计|總計|總和|总和|"
    r"gesamt|summe|insgesamt|итого|всего|toplam|totaal|totale|σ",
    re.I)
SUB_RE = re.compile(r"sub|小計|小计", re.I)
# rows that summarise the rows above without being part of them
AGG_RE = re.compile(
    r"(?:average|avg\.?|mean|median|max(?:imum)?|min(?:imum)?|std\.?\s*dev\.?|stddev|"
    r"standard deviation|平均|中央値|最大|最小|標準偏差|平均值|中位数)", re.I)
# columns that hold names for numbers, not quantities
ID_HEAD_RE = re.compile(
    r"(?:#|no\.?|nr\.?|num\.?|rank|ranking|id|year|years|yr|version|ver\.?|v|date|"
    r"順位|番号|年|年度|版|日付|序号|排名|年份)", re.I)
PCT_HEAD_RE = re.compile(r"%|percent|percentage|share|割合|構成比|比率|シェア|占比|百分比", re.I)

MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\[[^\]]*\]")
HTML_TAG = re.compile(r"<[^>]+>")
FOOTNOTE = re.compile(r"(?:\[\^?[\w-]+\]|[*†‡§¹²³⁴⁵⁶⁷⁸⁹⁰]+)$")


def clean(cell):
    """The text of a cell as a reader sees it: no links, tags, emphasis or code ticks."""
    s = MD_LINK.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), cell)
    s = HTML_TAG.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&#124;", "|").replace("&amp;", "&")
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"(?<!\w)[*_]|[*_](?!\w)", "", s)
    return s.strip()


def label_text(cell):
    s = clean(cell).rstrip(":：").strip()
    s = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", s)     # "Total (USD)", "合計(税込)"
    s = s.strip().rstrip(":：").strip()
    return s


def is_total_label(cell):
    return bool(cell) and bool(TOTAL_RE.fullmatch(label_text(cell)))


def is_agg_label(cell):
    """Average / Avg Skills per Agent / Max ...: a row that summarises, and is not added."""
    # the word, then a space or the end: "Avg Skills/Agent" is one, the package "AVG-001" is not
    return bool(cell) and bool(re.match("(?:" + AGG_RE.pattern + r")(?=\s|$|[:(])", label_text(cell), re.I))


# "Batch 1 Subtotal", "部門A小計": a subtotal of the rows above it.
# "COMPONENTS MERCHANDISE TOTAL", "Section total", "部門A合計": a named total. It may add up the rows
# directly above it, or be a line of its own (a PCB's price called "PCB merchandise total").
SUB_NAMED_RE = re.compile(r".+?(?:\bsub[\s-]*totals?|小計|小计)", re.I)
NAMED_RE = re.compile(r".+?(?:\btotals?|合計|合计|总计|総計)", re.I)


def row_kind(cell):
    if is_total_label(cell):
        return "sub" if SUB_RE.search(label_text(cell)) else "total"
    lt = label_text(cell)
    if lt and len(lt) <= 60:
        if SUB_NAMED_RE.fullmatch(lt):
            return "sub"
        if NAMED_RE.fullmatch(lt):
            return "named"
    if is_agg_label(cell):
        return "agg"
    return "data"


# ---------------------------------------------------------------- numbers

MISSING = object()
UNKNOWN = object()      # "?", "TBD": a value exists but is not given
MISSING_WORDS = {"", "-", "—", "–", "−", "n/a", "na", "n.a.", "none", "nil", "×", "‐", "―", "ー", "－"}
ELIDED = {"...", "…", "⋮", "⋯", ". . .", "(...)", "[...]", "etc.", "…etc"}
UNKNOWN_WORDS = {"?", "??", "tbd", "tba", "unknown", "?", "不明", "未定", "…", "..."}
CURRENCY_PRE = ("US$", "R$", "A$", "C$", "HK$", "$", "€", "£", "¥", "￥", "₹", "₩", "₽", "CHF ", "¢")
# currency codes, written before the amount (IDR1,194,606 / USD 78.71) or after it
CODES = ("USD|EUR|JPY|GBP|CNY|RMB|IDR|INR|KRW|BRL|CAD|AUD|CHF|SEK|NOK|DKK|PLN|MXN|SGD|HKD|NZD|ZAR|"
         "TRY|RUB|THB|VND|PHP|MYR|CZK|HUF|ILS|AED|SAR|TWD|UAH|NGN|KES|EGP|PKR|BDT|ARS|CLP|COP")
CURRENCY_SUF = {"円", "元", "ドル", "€", "$", "万円", "千円", "億円"} | {c.lower() for c in CODES.split("|")}
COUNT_SUF = {"件", "個", "人", "名", "回", "本", "冊", "社", "点", "枚", "台", "票", "次", "個人", "files",
             "file", "items", "item", "pcs", "tests", "lines", "loc", "issues", "prs", "stars", "users",
             "commits", "repos", "x"}

NUM_RE = re.compile(
    r"(?P<neg1>[-−–(])?\s*(?P<cur>US\$|R\$|A\$|C\$|HK\$|\$|€|£|¥|￥|₹|₩|₽|¢|" + CODES + r"|Rp\.?|RM|Rs\.?)?\s*"
    r"(?P<neg2>[-−])?\s*"
    r"(?P<num>\d[\d,.   ']*\d|\d|[.,]\d+)"
    r"\s*(?P<suf>%|[^\d\s()][^\d()]{0,11}?)?\s*(?P<close>\))?")


class Num:
    __slots__ = ("value", "dec", "unit", "cur", "pct", "amb")

    def __init__(self, value, dec, unit, cur, pct, amb=False):
        self.value, self.dec, self.unit, self.cur, self.pct = value, dec, unit, cur, pct
        self.amb = amb          # 1.429: a decimal, or 1,429 written with a dot

    def __repr__(self):
        return "Num(%s)" % self.value


def comma_decimal_hint(texts):
    """True when the column writes decimals with a comma (12,5 / 1.234,56)."""
    for t in texts:
        c = clean(t)
        if re.search(r"(?<![\d,.])\d{1,3}(?:\.\d{3})+,\d+(?!\d)", c):
            return True
        if re.fullmatch(r"[^\d]*\d+,\d{1,2}(?!\d)[^\d]*", c) and not re.search(r"\d,\d{3}", c):
            return True
    return False


def parse_num(cell, comma_decimal=False):
    """A Num, MISSING, UNKNOWN, or None (not a number: text, a range, an approximate value)."""
    s = clean(cell)
    if "~~" in s or re.search(r"<(?:del|s|strike)[\s>]", cell, re.I):
        return None
    low = s.lower().strip()
    if low in MISSING_WORDS:
        return MISSING
    if low in UNKNOWN_WORDS:
        return UNKNOWN
    s = FOOTNOTE.sub("", s).strip()
    s = s.replace("−", "-")
    m = NUM_RE.fullmatch(s)
    if not m:
        return None
    raw = m.group("num")
    neg = bool(m.group("neg2")) or (m.group("neg1") in ("-", "−", "–"))
    if m.group("neg1") == "(":
        if not m.group("close"):
            return None
        neg = True
    elif m.group("close"):
        return None
    if m.group("suf") and m.group("suf").strip().endswith("+"):
        return None                                     # "100+"
    # thousands separators
    if re.fullmatch(r"\d{1,3}(?:[   ']\d{3})+(?:[.,]\d+)?", raw):
        raw = re.sub(r"[   ']", "", raw)
    if re.search(r"[   ']", raw):
        return None
    if comma_decimal:
        if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?|,\d+", raw):
            return None
        intpart, _, frac = raw.replace(".", "").partition(",")
    else:
        if not re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+", raw):
            return None
        intpart, _, frac = raw.replace(",", "").partition(".")
    try:
        v = Decimal((intpart or "0") + ("." + frac if frac else ""))
    except InvalidOperation:
        return None
    if neg:
        v = -v
    suf = (m.group("suf") or "").strip()
    cur = m.group("cur") or ""
    pct = suf == "%"
    unit = "" if pct else suf.lower()
    if unit in CURRENCY_SUF:
        cur, unit = cur or unit, ""
    amb = not comma_decimal and bool(re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+", raw))
    return Num(v, len(frac), unit, cur, pct, amb)


def ambiguous(nums):
    """1.429 next to whole numbers (300, 500 ...) may be 1,429 written the continental way."""
    return any(n.amb for n in nums) and any(n.dec == 0 for n in nums)


# ---------------------------------------------------------------- tables

DELIM_CELL = re.compile(r":?-+:?")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, in_code, i = [], [], False, 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "`":
            in_code = not in_code
        if c == "|" and not in_code:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    cells.append("".join(cur).strip())
    return cells


def is_delim(line):
    if "-" not in line:
        return False
    cells = split_row(line)
    return bool(cells) and all(DELIM_CELL.fullmatch(c.replace(" ", "")) for c in cells)


class Table:
    def __init__(self, line, header):
        self.line = line            # 1-based line number of the header
        self.header = header
        self.rows = []              # (line, cells)


def find_tables(text):
    lines = text.splitlines()
    out, i, fence, in_comment = [], 0, None, False
    while i < len(lines):
        s = lines[i]
        fm = FENCE.match(s)
        if fence:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            i += 1
            continue
        if fm:
            fence = fm.group(1)
            i += 1
            continue
        if in_comment:
            if "-->" in s:
                in_comment = False
            i += 1
            continue
        if s.lstrip().startswith("<!--") and "-->" not in s:
            in_comment = True
            i += 1
            continue
        if "|" in s and i + 1 < len(lines) and is_delim(lines[i + 1]):
            header = split_row(s)
            ncol = len(split_row(lines[i + 1]))
            if len(header) == ncol:
                t = Table(i + 1, header)
                j = i + 2
                while j < len(lines) and lines[j].strip() and "|" in lines[j] and not FENCE.match(lines[j]):
                    cells = split_row(lines[j])
                    cells = (cells + [""] * ncol)[:ncol]
                    t.rows.append((j + 1, cells))
                    j += 1
                out.append(t)
                i = j
                continue
        i += 1
    return out


# ---------------------------------------------------------------- checking

def unit_class(n):
    if n.pct:
        return "pct"
    if n.cur:
        return "money"
    if n.unit in COUNT_SUF or n.unit == "":
        return "count"
    return "measure"


def ulp(dec):
    return Decimal(1).scaleb(-dec) / 2


def trailing_zeros(v):
    """Zeros at the end of a whole number (0 counts as having all of them)."""
    if v == 0:
        return 99
    n, k = abs(int(v)), 0
    while n % 10 == 0:
        n //= 10
        k += 1
    return k


def tolerance(tv, nums):
    """Whole counts and money add up exactly; anything shown rounded may drift by its own rounding."""
    cls = {unit_class(n) for n in nums + [tv]}
    allv = nums + [tv]
    if cls == {"count"} and all(n.dec == 0 for n in allv) and all(trailing_zeros(n.value) >= 3 for n in allv):
        # 19,850,000 + 80,000 shown as 19,940,000: whole numbers that all end in 000 were rounded
        # (to three significant figures, or to the thousand); each may be off by half its last place
        return sum((Decimal(10) ** trailing_zeros(n.value) / 2 for n in allv if n.value), Decimal(0))
    if cls <= {"count", "money"} and ("money" in cls or all(n.dec == 0 for n in allv)):
        return Decimal(0)
    return ulp(tv.dec) + sum((ulp(n.dec) for n in nums), Decimal(0))


def fmt(v, dec):
    if dec <= 0:
        q = v.quantize(Decimal(1))
        return "{:,}".format(int(q))
    return "{:,.{}f}".format(v, dec)


class Checker:
    def __init__(self, path):
        self.path = path
        self.findings = []
        self.stats = {"tables": 0, "total_rows": 0, "total_cols": 0, "share_cols": 0,
                      "checked": 0, "ok": 0, "explained": 0}
        self.unjudged = {}
        self.unjudged_list = []
        self.lab = 0

    def skip(self, reason, line=None, what=""):
        self.unjudged[reason] = self.unjudged.get(reason, 0) + 1
        self.unjudged_list.append((line, what, reason))

    def add(self, level, code, line, msg):
        self.findings.append({"path": self.path, "line": line, "level": level, "code": code, "message": msg})

    # -- one table
    def table(self, t):
        self.stats["tables"] += 1
        ncol = len(t.header)
        rows = t.rows
        if not rows or ncol < 2:
            return
        # the label column: the first column that holds a total label, else column 0
        lab = 0
        for ln, cells in rows:
            for c in range(min(2, ncol)):
                if is_total_label(cells[c]):
                    lab = c
                    break
            else:
                continue
            break
        self.lab = lab
        hints = [comma_decimal_hint([r[1][c] for r in rows]) for c in range(ncol)]
        parsed = [[parse_num(cells[c], hints[c]) for c in range(ncol)] for _, cells in rows]
        kinds = [row_kind(cells[lab]) for ln, cells in rows]
        self.kinds = kinds
        # the label column and anything left of it (row numbers) are names, not quantities
        idcol = [c <= lab or bool(ID_HEAD_RE.fullmatch(label_text(t.header[c]) or "")) for c in range(ncol)]
        pcthead = [bool(PCT_HEAD_RE.search(clean(t.header[c]))) for c in range(ncol)]
        totcol = [c != lab and is_total_label(t.header[c]) for c in range(ncol)]
        self.column_totals(t, rows, parsed, kinds, idcol, pcthead, ncol)
        for c in range(ncol):
            if totcol[c]:
                self.row_totals(t, rows, parsed, kinds, idcol, pcthead, totcol, c, ncol)
        self.shares(t, rows, parsed, kinds, idcol, pcthead, ncol)

    def blocks(self, kinds):
        """[(total_row_index, [part row indices], [alternative part lists])]"""
        tot = [i for i, k in enumerate(kinds) if k in ("total", "sub")]
        if not tot:
            return []
        if len(tot) == 1 and all(k != "data" for k in kinds[:tot[0]]):
            # the only total row sits at the top: it sums the data rows below it
            return [(tot[0], [i for i in range(tot[0] + 1, len(kinds)) if kinds[i] == "data"], [], None)]
        out, subs = [], []
        seg_start = last_total = 0
        for i, k in enumerate(kinds):
            if k == "sub":
                parts = [j for j in range(seg_start, i) if kinds[j] == "data"]
                out.append((i, parts, [], None))
                subs.append(i)
                seg_start = i + 1
            elif k == "named":
                seg_start = i + 1
            elif k == "total":
                parts = [j for j in range(last_total, i) if kinds[j] == "data"]
                alts = []
                if subs:
                    tail = [j for j in range(seg_start, i) if kinds[j] == "data"]
                    alts.append(subs + tail)
                named = any(kinds[j] == "named" for j in range(last_total, i))
                out.append((i, parts, alts, (last_total, i) if named else None))
                subs = []
                seg_start = last_total = i + 1
        return out

    def column_totals(self, t, rows, parsed, kinds, idcol, pcthead, ncol):
        blocks = self.blocks(kinds)
        for ti, parts, alts, span in blocks:
            self.stats["total_rows"] += 1
            line = rows[ti][0]
            label = label_text(rows[ti][1][self.lab]) or "Total"
            if any(clean(x) in ELIDED for i in parts for x in rows[i][1]):
                # a "..." row: rows were left out of the table, so the ones shown need not add up
                self.skip("rows are left out (...)", line, "%s row" % label)
                continue
            for c in range(ncol):
                if idcol[c]:
                    continue
                tv = parsed[ti][c]
                head = clean(t.header[c]) or "column %d" % (c + 1)
                what = '"%s", %s row' % (head, label)
                if tv is MISSING or tv is None and not clean(rows[ti][1][c]):
                    continue
                if tv is None or tv is UNKNOWN:
                    if clean(rows[ti][1][c]) and re.search(r"\d", clean(rows[ti][1][c])):
                        self.skip("the total cell is not one number", line, what)
                    continue
                vals = [parsed[i][c] for i in parts]
                res = self.judge_sum(tv, vals, [rows[i][1][c] for i in parts], line, what)
                if res is None:
                    continue
                if res == "ok":
                    continue
                ok_alt = False
                if span:
                    alts = alts + [self.walk(parsed, span, c)]
                for alt in alts:
                    r2 = self.judge_sum(tv, [parsed[i][c] for i in alt], None, None, None, quiet=True)
                    if r2 == "ok":
                        ok_alt = True
                if ok_alt:
                    self.stats["ok"] += 1
                    continue
                s, n, blanks = res
                expl = self.explain(tv, vals, parsed, ti, c, parts, ncol)
                if expl:
                    self.stats["explained"] += 1
                    continue
                if tv.pct and s > 100 and tv.value <= 100:
                    # 90.4%, 99.0%, 90.5% ... under a subtotal of 77.2%: rates, not shares of a whole.
                    # Their total is some average, weighted in a way the table does not show
                    self.skip("percentages that are rates, not shares (they add up past 100%)", line, what)
                    continue
                diff = tv.value - s
                dec = max([tv.dec] + [v.dec for v in vals if isinstance(v, Num)])
                where = "above" if not parts or parts[0] < ti else "below"
                msg = "%s: the total says %s; the %d row%s %s add up to %s (%s%s)" % (
                    what, fmt(tv.value, tv.dec), n, "" if n == 1 else "s", where, fmt(s, dec),
                    "+" if diff > 0 else "", fmt(diff, dec))
                if blanks:
                    self.add("warning", "TOTAL?", line, msg + "; %d of them %s blank, which may be the difference"
                             % (blanks, "is" if blanks == 1 else "are"))
                else:
                    self.add("error", "TOTAL", line, msg)

    def walk(self, parsed, span, c):
        """The rows a grand total adds up when the block has named totals in it: a named total that
        equals the rows directly above it stands for them; one that does not is a line of its own."""
        items, run = [], []
        for i in range(*span):
            k = self.kinds[i]
            if k == "data":
                run.append(i)
            elif k == "sub":
                items.append(i)
                run = []
            elif k == "named":
                tv = parsed[i][c]
                if isinstance(tv, Num) and run and \
                        self.judge_sum(tv, [parsed[j][c] for j in run], None, None, None, quiet=True) == "ok":
                    items.append(i)
                else:
                    items += run + [i]
                run = []
        return items + run

    def judge_sum(self, tv, vals, raw, line, what, quiet=False):
        """'ok', None (not judged), or (sum, n, blanks) when it does not add up."""
        nums = [v for v in vals if isinstance(v, Num)]
        if any(v is None for v in vals):
            if not quiet:
                bad = [r for v, r in zip(vals, raw or []) if v is None]
                if any(re.search(r"\d", clean(b)) for b in bad) or len(bad) < len(vals):
                    self.skip("text or an approximate value among the rows", line, what)
            return None
        if any(v is UNKNOWN for v in vals):
            if not quiet:
                self.skip("a row says the value is unknown", line, what)
            return None
        if not nums:
            return None
        if ambiguous(nums + [tv]):
            if not quiet:
                self.skip("a dot that may separate thousands (1.429)", line, what)
            return None
        units = {(n.unit, n.cur, n.pct) for n in nums + [tv]}
        if len(units) > 1:
            # "12" in a column of "12 ms" is the same unit written once; a different unit is not
            u2 = {u for u in units if u != ("", "", False)}
            if len(u2) > 1:
                if not quiet:
                    self.skip("mixed units", line, what)
                return None
        if not quiet:
            self.stats["checked"] += 1
        s = sum((n.value for n in nums), Decimal(0))
        tol = tolerance(tv, nums)
        if abs(tv.value - s) <= tol:
            if not quiet:
                self.stats["ok"] += 1
            return "ok"
        return (s, len(nums), sum(1 for v in vals if v is MISSING))

    def explain(self, tv, vals, parsed, ti, c, parts, ncol):
        """Is the total something other than a sum -- the mean, median, max or min of the rows, or a
        mean weighted by another column (a pass rate under Passed / Run)? Returns the word, or None."""
        nv = [v for v in vals if isinstance(v, Num)]
        nums = [v.value for v in nv]
        if len(nums) < 2:
            return None
        t = tv.value
        rounded = tolerance(tv, nv) > 0
        # the parts' own rounding only counts when they are shown rounded
        part_err = sum((ulp(v.dec) for v in nv), Decimal(0)) / len(nv) if rounded else Decimal(0)
        tol = ulp(tv.dec) + part_err + Decimal("1e-9")
        if abs(t - sum(nums) / len(nums)) <= tol:
            return "mean"
        med = Decimal(statistics.median(nums))
        for name, v, d in (("median", med, max(x.dec for x in nv)),
                           ("max", max(nums), [x.dec for x in nv if x.value == max(nums)][0]),
                           ("min", min(nums), [x.dec for x in nv if x.value == min(nums)][0])):
            # a part shown to more digits than the total may round to it; otherwise they are equal
            if abs(t - v) <= (ulp(tv.dec) if tv.dec < d else (ulp(d) if rounded else 0)) + Decimal("1e-9"):
                return name
        for w in range(ncol):
            if w == c:
                continue
            ws = [parsed[i][w] for i in parts]
            if all(isinstance(x, Num) for x in ws) and all(isinstance(v, Num) for v in vals):
                tw = sum((x.value for x in ws), Decimal(0))
                if tw:
                    wm = sum((x.value * v.value for x, v in zip(ws, vals)), Decimal(0)) / tw
                    if abs(t - wm) <= tol:
                        return "weighted mean"
        return None

    def row_totals(self, t, rows, parsed, kinds, idcol, pcthead, totcol, c, ncol):
        """A column headed Total: which neighbouring columns does it add up, and which rows disagree."""
        self.stats["total_cols"] += 1
        head = clean(t.header[c])

        def numeric_col(j):
            vals = [parsed[i][j] for i in range(len(rows))]
            nums = [v for v in vals if isinstance(v, Num)]
            return (not idcol[j] and not totcol[j] and not pcthead[j] and len(nums) >= max(1, len(vals) // 2)
                    and not any(n.pct for n in nums))

        left = [j for j in range(c) if numeric_col(j)]
        right = [j for j in range(c + 1, ncol) if numeric_col(j)]
        cands = []
        # contiguous runs of numeric columns ending next to the total column (left) or starting after it
        run = []
        for j in range(c - 1, -1, -1):
            if j in left:
                run.insert(0, j)
                if len(run) >= 2:
                    cands.append(list(run))
            else:
                break
        run = []
        for j in range(c + 1, ncol):
            if j in right:
                run.append(j)
                if len(run) >= 2:
                    cands.append(list(run))
            else:
                break
        if len(left) >= 2 and left not in cands:
            cands.append(left)
        best = None
        for comp in cands:
            results = []
            for i in range(len(rows)):
                tv = parsed[i][c]
                if not isinstance(tv, Num) or kinds[i] == "agg":
                    continue            # "Avg Skills/Agent": its Total cell is an average
                vals = [parsed[i][j] for j in comp]
                if any(v is None or v is UNKNOWN for v in vals):
                    continue
                nums = [v for v in vals if isinstance(v, Num)]
                if ambiguous(nums + [tv]):
                    continue
                if len(nums) < 1:
                    continue
                units = {(n.unit, n.cur, n.pct) for n in nums + [tv]} - {("", "", False)}
                if len(units) > 1:
                    continue
                s = sum((n.value for n in nums), Decimal(0))
                tol = tolerance(tv, nums)
                results.append((i, abs(tv.value - s) <= tol, s, tv, max([tv.dec] + [n.dec for n in nums]),
                                sum(1 for v in vals if v is MISSING)))
            good = sum(1 for r in results if r[1])
            key = (good, len(comp))
            if results and (best is None or key > best[0]):
                best = (key, comp, results)
        if best is None:
            self.skip("no neighbouring columns to add up", t.line, '"%s" column' % head)
            return
        (good, _), comp, results = best
        if good < 2 or good * 2 < len(results):
            self.skip("no set of neighbouring columns adds up to it in most rows", t.line, '"%s" column' % head)
            return
        names = ", ".join('"%s"' % (clean(t.header[j]) or "column %d" % (j + 1)) for j in comp)
        for i, ok, s, tv, dec, blanks in results:
            self.stats["checked"] += 1
            if ok:
                self.stats["ok"] += 1
                continue
            diff = tv.value - s
            label = clean(rows[i][1][self.lab]) or "row %d" % (i + 1)
            msg = '"%s" on the %s row says %s; %s add up to %s (%s%s) -- %d of %d rows add up' % (
                head, label, fmt(tv.value, tv.dec), names, fmt(s, dec), "+" if diff > 0 else "", fmt(diff, dec),
                good, len(results))
            if blanks:
                self.add("warning", "ROWTOTAL?", rows[i][0], msg + "; %d blank" % blanks)
            else:
                self.add("error", "ROWTOTAL", rows[i][0], msg)

    def shares(self, t, rows, parsed, kinds, idcol, pcthead, ncol):
        """A percentage column in a table with one total row: is each row's share its count over the total?"""
        tots = [i for i, k in enumerate(kinds) if k in ("total", "sub")]
        if len(tots) != 1:
            return
        ti = tots[0]
        data = [i for i, k in enumerate(kinds) if k == "data"]
        if len(data) < 3 or any(clean(x) in ELIDED for i in data for x in rows[i][1]):
            return
        for p in range(ncol):
            if idcol[p]:
                continue
            pv = [parsed[i][p] for i in data]
            if not all(isinstance(v, Num) or v is MISSING for v in pv):
                continue
            nums = [v for v in pv if isinstance(v, Num)]
            if len(nums) < 3:
                continue
            is_pct = all(v.pct for v in nums) or (pcthead[p] and all(not v.unit and not v.cur for v in nums))
            if not is_pct:
                continue
            self.stats["share_cols"] += 1
            head = clean(t.header[p])
            best = None
            for c in range(ncol):
                if c == p or idcol[c]:
                    continue
                cv = [parsed[i][c] for i in data]
                tc = parsed[ti][c]
                if not all(isinstance(v, Num) for v in cv) or any(v.pct for v in cv):
                    continue
                dens = []
                if isinstance(tc, Num) and tc.value:
                    dens.append(tc.value)
                sc = sum((v.value for v in cv), Decimal(0))
                if sc and sc not in dens:
                    dens.append(sc)
                for den in dens:
                    for scale in (Decimal(100), Decimal(1)):
                        res = []
                        for i, v, x in zip(data, pv, cv):
                            if not isinstance(v, Num):
                                continue
                            want = x.value / den * scale
                            tol = ulp(v.dec) + Decimal("1e-9") + abs(want) * ulp(x.dec) / (abs(x.value) or 1)
                            res.append((i, abs(v.value - want) <= tol, want, v))
                        good = sum(1 for r in res if r[1])
                        key = (good, scale == 100, den == (tc.value if isinstance(tc, Num) else None))
                        if best is None or key > best[0]:
                            best = (key, c, den, scale, res)
            if best is None:
                self.skip("no count column the percentages could come from", t.line, '"%s" column' % head)
                continue
            (good, _, _), c, den, scale, res = best
            if good < 2 or good * 3 < len(res) * 2:
                self.skip("the percentages are not count / total in most rows", t.line, '"%s" column' % head)
                continue
            cname = clean(t.header[c]) or "column %d" % (c + 1)
            for i, ok, want, v in res:
                self.stats["checked"] += 1
                if ok:
                    self.stats["ok"] += 1
                    continue
                label = clean(rows[i][1][self.lab]) or "row %d" % (i + 1)
                self.add("error", "SHARE", rows[i][0],
                         '"%s" on the %s row says %s%s; "%s" / %s is %s%s -- %d of %d rows agree' % (
                             head, label, fmt(v.value, v.dec), "%" if scale == 100 else "", cname,
                             fmt(den, 0) if den == den.to_integral_value() else str(den),
                             fmt(want, v.dec), "%" if scale == 100 else "", good, len(res)))


def check_text(text, path="<text>"):
    ch = Checker(path)
    for t in find_tables(text):
        ch.table(t)
    return ch


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for f in sorted(files):
                    if f.lower().endswith(EXTS):
                        yield os.path.join(root, f)
        else:
            yield p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Recompute the Total rows and columns of Markdown tables.")
    ap.add_argument("paths", nargs="*", default=["."])
    ap.add_argument("--json", action="store_true", help="one JSON object on stdout")
    ap.add_argument("--why", action="store_true", help="list each cell it did not judge, with the reason")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    a = ap.parse_args(argv)
    findings, stats, unj, files = [], {}, {}, 0
    why = []
    for f in iter_files(a.paths):
        try:
            with open(f, encoding="utf-8-sig", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            print("%s: cannot read (%s)" % (f, e.strerror), file=sys.stderr)
            continue
        files += 1
        ch = check_text(text, f)
        findings += ch.findings
        for k, v in ch.stats.items():
            stats[k] = stats.get(k, 0) + v
        for k, v in ch.unjudged.items():
            unj[k] = unj.get(k, 0) + v
        why += [(f, ln, w, r) for ln, w, r in ch.unjudged_list]
    findings.sort(key=lambda x: (x["path"], x["line"]))
    errors = sum(1 for x in findings if x["level"] == "error")
    warnings = len(findings) - errors
    if a.json:
        print(json.dumps({"files": files, "stats": stats, "not_judged": unj, "findings": findings},
                         ensure_ascii=False, indent=1))
    else:
        for x in findings:
            print("%s:%d: %s %s  %s" % (x["path"], x["line"], x["level"], x["code"], x["message"]))
        if a.why:
            for f, ln, w, r in why:
                print("%s:%s: not judged  %s: %s" % (f, ln, w, r))
        print("%d file%s, %d table%s: %d total row%s, %d total column%s, %d percentage column%s; "
              "%d sums checked, %d add up, %d are not sums (mean, max, a ratio ...)" % (
                  files, "" if files == 1 else "s", stats.get("tables", 0), "" if stats.get("tables") == 1 else "s",
                  stats.get("total_rows", 0), "" if stats.get("total_rows") == 1 else "s",
                  stats.get("total_cols", 0), "" if stats.get("total_cols") == 1 else "s",
                  stats.get("share_cols", 0), "" if stats.get("share_cols") == 1 else "s",
                  stats.get("checked", 0), stats.get("ok", 0), stats.get("explained", 0)))
        print("%d error%s, %d warning%s" % (errors, "" if errors == 1 else "s", warnings, "" if warnings == 1 else "s"))
        if unj:
            print("not judged: " + "; ".join("%d %s" % (v, k) for k, v in sorted(unj.items(), key=lambda kv: -kv[1])))
    return 1 if errors or (a.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
