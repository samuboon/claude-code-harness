# -*- coding: utf-8 -*-
"""自動圧縮が走った回数を機械で数える(PreCompact フック。標準ライブラリのみ)。

なぜ要るか(オーナー指摘 2026-09-10):
  「ずっと回してるとコンテキストウィンドウが圧迫されて品質は劣化するよね。
    そうなったら一回止めてチャットをリセットする必要があると思うんだけどそれは合っている？」
  合っている。そしてそれは `state/RUN.md` の「圧縮回数」で測ることになっているが、
  **その欄は AI の手書きだった**。AI は自分の文脈の残量を直接見られないので、
  圧縮が走ったこと自体を後から思い出して書く形になり、自己申告になっていた。
  BUG-12 で消したのは「測れない劣化」であり、**測れる劣化(文脈の喪失)は残す**。
  残す以上、計器は機械が持つ(誓約 2「計器を一度も甘く読まない」)。

入力: stdin に JSON。`trigger` が "auto"(自動)か "manual"(/compact)。
出力: 何も止めない(exit 0 固定)。圧縮を邪魔しないため。
副作用:
  - state/RUN.md の「この起動: 圧縮回数」を +1 し、自動/手動の内訳を書く
  - state/RUNS.tsv に 1 行(Stop フックと同じ台帳)
"""
import json
import os
import re
import sys
import time

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN = os.path.join(ROOT, "state", "RUN.md")
RUNS = os.path.join(ROOT, "state", "RUNS.tsv")

# 「| この起動: 圧縮回数 | 0 | AI |」の 0 を捕まえる
COUNT_RE = re.compile(r"(\| この起動: 圧縮回数 \|[^|\d]*)(\d+)")


def bump(run_text, trigger):
    """圧縮回数を +1 した本文と新しい値を返す。欄が無ければ (原文, None)。"""
    m = COUNT_RE.search(run_text)
    if not m:
        return run_text, None
    n = int(m.group(2)) + 1
    note = "(直近 = %s。**PreCompact フックが機械で数える**)" % (
        "自動" if trigger == "auto" else "手動 /compact")
    head, tail = run_text[:m.start()], run_text[m.end():]
    # 既にある注記を落としてから書き直す(同じ括弧が二重に積まれないように)
    tail = re.sub(r"^\s*\([^)]*\)", "", tail)
    return head + m.group(1) + str(n) + " " + note + tail, n


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
    trigger = "unknown"
    try:
        trigger = (json.loads(sys.stdin.read()) or {}).get("trigger", "unknown")
    except Exception:
        pass

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(RUN, encoding="utf-8") as f:
            run = f.read()
        new_run, n = bump(run, trigger)
        if n is not None:
            with open(RUN, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_run)
        log([now, "-", "圧縮(%s)" % trigger, "-", "圧縮回数=%s" % n, ""])
    except Exception as e:
        log([now, "-", "圧縮(%s)" % trigger, "-", "記録に失敗", str(e)[:60]])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # 圧縮そのものは絶対に止めない
