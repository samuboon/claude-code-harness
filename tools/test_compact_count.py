# -*- coding: utf-8 -*-
"""PreCompact フック `.claude/hooks/compact_count.py` の検査(標準ライブラリのみ)。

圧縮の計器は AI の手書きだった。機械に移した以上、機械が正しく数えることを見る。
偽の起動を組み立てて実際に走らせ、state/RUN.md の数字を読む。
一時フォルダは scratchpad の下に作り、finally で消す(web-safety 6)。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOOK = os.path.join(ROOT, ".claude", "hooks", "compact_count.py")
SCRATCH = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "Temp", "claude")
NL = chr(10)

RUN_TEMPLATE = ("| この起動: 止まろうとした回数 / 上限 T | **0 / 8**(理由) | AI |" + NL +
                "| この起動: 圧縮回数 | %s | AI |" + NL +
                "| クレジットモード | balanced | — |" + NL)


def make(tmp, count="0"):
    os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
    with open(os.path.join(tmp, "state", "RUN.md"), "w", encoding="utf-8", newline=NL) as f:
        f.write(RUN_TEMPLATE % count)


def fire(tmp, trigger="auto"):
    """フックを実際に走らせて (exit コード, 圧縮回数, RUN.md 全文) を返す。"""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp, PYTHONIOENCODING="utf-8")
    payload = ('{"trigger": "%s"}' % trigger).encode("utf-8")
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, env=env)
    with open(os.path.join(tmp, "state", "RUN.md"), encoding="utf-8") as f:
        run = f.read()
    m = re.search(r"\| この起動: 圧縮回数 \|[^|\d]*(\d+)", run)
    return r.returncode, (int(m.group(1)) if m else None), run


def case(fn):
    parent = SCRATCH if os.path.isdir(SCRATCH) else None
    tmp = tempfile.mkdtemp(prefix="compact_", dir=parent)
    try:
        return fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_counts_one_compaction():
    def go(tmp):
        make(tmp, "0")
        rc, n, run = fire(tmp, "auto")
        assert rc == 0, rc
        assert n == 1, (n, run)
        assert "自動" in run, run
    case(go)


def test_counts_repeatedly_without_stacking_notes():
    """2 回走らせたら 2 になり、注記が二重に積まれない(RUN.md が壊れない)。"""
    def go(tmp):
        make(tmp, "0")
        fire(tmp, "auto")
        rc, n, run = fire(tmp, "manual")
        assert n == 2, (n, run)
        assert run.count("PreCompact フックが機械で数える") == 1, run
        assert "手動" in run, run
        assert "クレジットモード" in run, run      # 後ろの行を食っていない
    case(go)


def test_never_blocks_compaction():
    """RUN.md が無い・壊れていても exit 0(圧縮そのものは絶対に止めない)。"""
    def go(tmp):
        os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
        r = subprocess.run([sys.executable, HOOK], input=b'{"trigger":"auto"}',
                           capture_output=True,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=tmp, PYTHONIOENCODING="utf-8"))
        assert r.returncode == 0, (r.returncode, r.stderr.decode("utf-8", "replace"))
    case(go)


def test_records_to_the_same_ledger():
    """Stop フックと同じ state/RUNS.tsv に残る(台帳を 2 つに割らない)。"""
    def go(tmp):
        make(tmp, "0")
        fire(tmp, "auto")
        with open(os.path.join(tmp, "state", "RUNS.tsv"), encoding="utf-8") as f:
            rows = [r for r in f.read().split(NL) if r.strip()]
        assert len(rows) == 2, rows           # 見出し + 1 行
        assert "圧縮(auto)" in rows[1], rows
        assert "圧縮回数=1" in rows[1], rows
    case(go)


def test_missing_count_column_is_survivable():
    """圧縮回数の欄が無い RUN.md でも落ちない(数えないだけ)。"""
    def go(tmp):
        os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
        with open(os.path.join(tmp, "state", "RUN.md"), "w", encoding="utf-8", newline=NL) as f:
            f.write("| 何か | 値 |" + NL)
        rc, n, run = fire(tmp, "auto")
        assert rc == 0, rc
        assert n is None, n
    case(go)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK", name)
            except AssertionError as e:
                print("NG", name, e)
                fails += 1
    print("失敗", fails, "件")
    sys.exit(1 if fails else 0)
