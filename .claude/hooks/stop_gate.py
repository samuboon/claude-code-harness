# -*- coding: utf-8 -*-
"""ターンを終えるときに必ず走る門(Stop フック。ハーネス v3・2026-09-11。標準ライブラリのみ)。

なぜ要るか: 早すぎる停止が 2 日で 7 回起きた(この設計の由来は README を参照)。呼ぶかどうかを AI 自身が決める道具は
効かないので、Claude Code がターン終端で必ず起動するこの門に置く(AI の意思を通らない)。
v3 の判定は tools/stop_check.py の 1 つだけ: **予算(T / H / 圧縮 / 停滞)が尽きていなければ止めない。**
旧 [停止] 行の書式と検査 A〜K は見ない(言い訳の書式を検査する門は、書式を満たす言い訳を生む)。

armed(効かせる)条件: state/SESSION.lock が生きていて label に "loop" か "自走" がある、または state/AUTORUN がある。
オーナーと対話しているセッションは素通り(相談のターンを止めるのは誤り)。失効した錠では効かない(BUG-13)。

判定:
  予算切れ(stop_check.check が空)→ 通す(exit 0)
  予算あり               → 止めない(exit 2)。理由(残り予算・今週の市場接触・待ち行列の次)を stderr に返す
  例外                   → 通す(exit 0)。壊れた門でセッションを人質にしない
毎回 RUN.md の T を +1 し、state/RUNS.tsv に 1 行(いつ・armed か・T・判定・理由)を残す。
"""
import json
import os
import re
import sys
import time

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN = os.path.join(ROOT, "state", "RUN.md")
LOCK = os.path.join(ROOT, "state", "SESSION.lock")
AUTORUN = os.path.join(ROOT, "state", "AUTORUN")
RUNS = os.path.join(ROOT, "state", "RUNS.tsv")
QUEUE = os.path.join(ROOT, "state", "QUEUE.md")
STATUS = os.path.join(ROOT, "STATUS.md")
CONTACTS = os.path.join(ROOT, "state", "CONTACTS.tsv")

T_LINE = re.compile(r"(この起動: 止まろうとした回数 / 上限 T \|[^|]*?)(\d+)(\s*/\s*)(\d+)")


def armed():
    """(効かせるか, 理由, 錠の中身)。錠は生きているものだけ見る(BUG-13)。"""
    rec, age = None, None
    try:
        age = time.time() - os.path.getmtime(LOCK)
        with open(LOCK, encoding="utf-8") as f:
            rec = json.load(f) or {}
    except Exception:
        rec = None
    if os.path.exists(AUTORUN):
        return True, "AUTORUN", rec
    if rec is None:
        return False, "錠なし", None
    label = rec.get("label", "")
    try:
        ttl_hours = float(rec.get("ttl_hours", 4.0))
    except (TypeError, ValueError):
        ttl_hours = 4.0
    if age >= ttl_hours * 3600.0:
        return False, "錠が失効(age=%.0f 分 > ttl %.1f h) label=%s" % (age / 60.0, ttl_hours, label), rec
    if "loop" in label.lower() or "自走" in label:
        return True, "錠 label=" + label, rec
    return False, "錠 label=" + label, rec


def bump_t(run_text):
    """RUN.md の T を +1 した本文と (新しい T, 上限) を返す。行が無ければ (原文, None, None)。"""
    m = T_LINE.search(run_text)
    if not m:
        return run_text, None, None
    used, cap = int(m.group(2)), int(m.group(4))
    new = run_text[:m.start()] + m.group(1) + str(used + 1) + m.group(3) + m.group(4) + run_text[m.end():]
    return new, used + 1, cap


def log(fields):
    try:
        new = not os.path.exists(RUNS)
        with open(RUNS, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write("時刻\tarmed\t理由\tT\t判定\t落ちた検査\n")
            f.write("\t".join(str(x) for x in fields) + "\n")
    except Exception:
        pass


def main():
    for stream in (sys.stdin, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        sys.stdin.read()  # 入力は読み捨てる(判定は帳簿だけで行う)
    except Exception:
        pass

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    on, why, rec = armed()
    if not on:
        log([now, 0, why, "", "素通り", ""])
        return 0

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import stop_check
    import contacts

    run = open(RUN, encoding="utf-8").read()
    new_run, t_used, t_cap = bump_t(run)
    if t_used is not None:
        open(RUN, "w", encoding="utf-8", newline="\n").write(new_run)
    queue = open(QUEUE, encoding="utf-8").read() if os.path.exists(QUEUE) else ""
    status = open(STATUS, encoding="utf-8").read() if os.path.exists(STATUS) else ""
    reasons = stop_check.check(new_run, rec, None, stop_check.newest_state_mtime(ROOT),
                               contacts.week_count(CONTACTS), queue, status)
    t_label = "%s/%s" % (t_used, t_cap)
    if not reasons:
        log([now, 1, why, t_label, "通す(予算切れ)", ""])
        return 0
    sys.stderr.write(
        "止まってはいけません。\n" + "\n".join("  - " + r for r in reasons)
        + "\n\n待ち行列(state/QUEUE.md)の次の行を置いてから終えてください。終えてよいのは予算切れだけです。\n")
    log([now, 1, why, t_label, "止めた", " / ".join(reasons)[:120]])
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 壊れた門でセッションを人質にしない
        try:
            sys.stderr.write("stop_gate が落ちました(通します): " + str(e) + "\n")
        except Exception:
            pass
        sys.exit(0)
