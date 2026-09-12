# -*- coding: utf-8 -*-
"""Stop フック `.claude/hooks/stop_gate.py` の検査(ハーネス v3・2026-09-11。標準ライブラリのみ)。

門は「AI の意思を通らない」ことに意味がある。だから検査も AI が書いた文ではなく
**偽の起動を組み立てて実際に走らせる**(exit コードを見る)。一時フォルダは finally で消す。

exit 2 = 止めない(ターンを続けさせる) / exit 0 = 通す
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = os.path.join(ROOT, ".claude", "hooks", "stop_gate.py")
SCRATCH = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "Temp", "claude")
NL = chr(10)
LOCK_TIME = "%Y-%m-%d %H:%M:%S"
QUEUE = "- [ ] (待) 面A | 登録 | オーナー" + NL + "- [ ] 面B | 記事 1 本 | 生成" + NL + "- [ ] 生成型 | 発注 1 本 |" + NL


def make(tmp, label, t_used=6, t_cap=8, compact=0, autorun=False, ttl_hours=4.0, age_seconds=0,
         started_hours_ago=None, queue=QUEUE, stale_minutes=None):
    os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "tools"), exist_ok=True)
    for name in ("stop_check.py", "contacts.py"):
        shutil.copy(os.path.join(HERE, name), os.path.join(tmp, "tools", name))

    def w(rel, text):
        with open(os.path.join(tmp, rel), "w", encoding="utf-8", newline=NL) as f:
            f.write(text)

    w("STATUS.md", "# STATUS" + NL + NL + "[ゴール] 目標まで あと 100 円 ・ 残り 10 日" + NL + "[財布] 残高 0 円" + NL)
    w(os.path.join("state", "RUN.md"),
      "| この起動: 止まろうとした回数 / 上限 T | **%d / %d**(理由) | AI |%s"
      "| この起動: 圧縮回数 | %d (直近 = 自動) | 機械 |%s" % (t_used, t_cap, NL, compact, NL))
    w(os.path.join("state", "QUEUE.md"), queue)
    if label is not None:
        lock = os.path.join(tmp, "state", "SESSION.lock")
        started = time.time() - (started_hours_ago or 0) * 3600.0
        w(os.path.join("state", "SESSION.lock"),
          json.dumps({"token": "x", "label": label, "ttl_hours": ttl_hours,
                      "started": time.strftime(LOCK_TIME, time.localtime(started))}, ensure_ascii=False))
        if age_seconds:
            old = time.time() - age_seconds
            os.utime(lock, (old, old))
    if autorun:
        w(os.path.join("state", "AUTORUN"), "on" + NL)
    if stale_minutes:
        old = time.time() - stale_minutes * 60
        for rel in ("STATUS.md", os.path.join("state", "QUEUE.md")):
            os.utime(os.path.join(tmp, rel), (old, old))


def fire(tmp):
    """門を実際に走らせて (exit コード, stderr, 走ったあとの T) を返す。"""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, GATE], input=b'{"stop_hook_active": false}', capture_output=True, env=env)
    with open(os.path.join(tmp, "state", "RUN.md"), encoding="utf-8") as f:
        run = f.read()
    m = re.search(r"上限 T \|[^|]*?(\d+)\s*/\s*(\d+)", run)
    return r.returncode, r.stderr.decode("utf-8", "replace"), (int(m.group(1)) if m else None)


def case(fn):
    parent = SCRATCH if os.path.isdir(SCRATCH) else None
    tmp = tempfile.mkdtemp(prefix="stopgate_", dir=parent)
    try:
        return fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_disarmed_when_not_autorun():
    """オーナーと対話しているセッション(label に loop が無い)は素通り。T も動かさない。"""
    def go(tmp):
        make(tmp, "2026-09-11 オーナー同席")
        rc, err, t = fire(tmp)
        assert rc == 0, (rc, err)
        assert t == 6, t
    case(go)


def test_blocks_while_budget_remains():
    """予算が残っていれば、何を書いていようと止めない。理由に次の行と市場接触が出る。T は +1。"""
    def go(tmp):
        make(tmp, "2026-09-11 loop 自走", t_used=1)
        rc, err, t = fire(tmp)
        assert rc == 2, (rc, err)
        assert "予算が残っている" in err and "待ち行列の次: 面B" in err and "市場接触 0/3" in err, err
        # IMP-15: ゴールが先頭、待ち行列の次、予算が最後
        assert "ゴール: [ゴール] 目標まで あと 100 円" in err, err
        assert err.index("ゴール:") < err.index("待ち行列の次") < err.index("予算が残っている"), err
        assert t == 2, t
    case(go)


def test_blocks_even_when_T_is_spent():
    """T=8/8 でも止めない(2026-09-11 オーナー決定。回数は出口ではない。BUG-26)。T は +1 され記録には残る。"""
    def go(tmp):
        make(tmp, "loop 自走", t_used=7, t_cap=8)   # この呼び出しで 8/8 に達する
        rc, err, t = fire(tmp)
        assert rc == 2, (rc, err)
        assert "T=8/8(出口ではない)" in err, err
        assert t == 8, t
    case(go)


def test_allows_when_compacted_twice():
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, compact=2)
        rc, err, t = fire(tmp)
        assert rc == 0, (rc, err)
    case(go)


def test_allows_when_stalled():
    """STATUS と帳簿が 50 分更新されていなければ通す(空回りを 1 起動分に限定)。"""
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, stale_minutes=50)
        rc, err, t = fire(tmp)
        assert rc == 0, (rc, err)
    case(go)


def test_blocks_when_recently_updated():
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, stale_minutes=10)
        rc, err, t = fire(tmp)
        assert rc == 2, (rc, err)
    case(go)


def test_allows_when_H_is_spent_by_started():
    """錠の started から 4 時間を超えていれば通す(錠の mtime はまだ新しくても)。"""
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, started_hours_ago=4.2)
        rc, err, t = fire(tmp)
        assert rc == 0, (rc, err)
    case(go)


def test_empty_queue_still_blocks_and_names_it():
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, queue="- [x] 済" + NL + "- [ ] (待) 登録" + NL)
        rc, err, t = fire(tmp)
        assert rc == 2, (rc, err)
        assert "未完の行が無い" in err, err
    case(go)


def test_autorun_file_arms_it():
    def go(tmp):
        make(tmp, "対話のセッション", t_used=1, autorun=True)
        rc, err, t = fire(tmp)
        assert rc == 2, (rc, err)
    case(go)


def test_fails_open_when_broken():
    """RUN.md が無いなど、門自身が壊れたときは通す(セッションを人質にしない)。"""
    def go(tmp):
        make(tmp, "loop 自走", t_used=1)
        os.remove(os.path.join(tmp, "state", "RUN.md"))
        r = subprocess.run([sys.executable, GATE], input=b"{}", capture_output=True,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=tmp, PYTHONIOENCODING="utf-8"))
        assert r.returncode == 0, r.stderr
    case(go)


def test_records_every_firing():
    def go(tmp):
        make(tmp, "loop 自走", t_used=1)
        fire(tmp)
        fire(tmp)
        with open(os.path.join(tmp, "state", "RUNS.tsv"), encoding="utf-8") as f:
            rows = [r for r in f.read().split(NL) if r.strip()]
        assert len(rows) == 3, rows
        assert all("止めた" in r for r in rows[1:]), rows
    case(go)


def test_a_stale_lock_does_not_arm_it():
    """失効した錠では効かない(BUG-13)。T も動かさない。"""
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, ttl_hours=0.5, age_seconds=40 * 60)
        rc, err, t = fire(tmp)
        assert rc == 0, (rc, err)
        assert t == 1, t
    case(go)


def test_a_fresh_autorun_lock_still_arms_it():
    def go(tmp):
        make(tmp, "loop 自走", t_used=1, ttl_hours=4.0, age_seconds=10 * 60)
        rc, err, t = fire(tmp)
        assert rc == 2, (rc, err)
        assert t == 2, t
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
