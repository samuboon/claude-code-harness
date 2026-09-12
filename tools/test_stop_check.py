# -*- coding: utf-8 -*-
"""stop_check.py と contacts.py の検査(ハーネス v3・2026-09-11。標準ライブラリのみ)。

v2 の 19 本(検査 A〜K・実際に起きた停止 5 件の回帰)は、[停止] 行の書式ごと廃止した。
v3 の門は「予算が尽きたか」しか見ない。ここでは予算の 4 種類が反転すること、待ち行列の読み方、
帳簿(CONTACTS)の週数えと順位付けを見る。python tools/test_stop_check.py
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import contacts  # noqa: E402
import stop_check as sc  # noqa: E402

NOW = sc.NOW
RUN = sc.RUN_OK
QUEUE = sc.QUEUE_OK


def lock(hours_ago, ttl=4.0):
    return sc.lock_started(hours_ago, ttl)


def test_budget_left_blocks():
    r = sc.check(RUN, lock(1), NOW, NOW - 600, 1, QUEUE, sc.STATUS_OK)
    assert r, '予算が残っているのに終えてよいと言った'
    # IMP-15: 返す文は上流から。ゴール → 距離 → 3 つの問い → 待ち行列の次 → 予算(参考)
    assert r[0].startswith('ゴール: [ゴール] 目標まで あと 100 円'), r[0]
    assert r[1].startswith('距離: '), r[1]
    assert r[2].startswith('止まる前に 1 行ずつ答える'), r[2]
    assert r[-1].startswith('予算が残っている('), r[-1]
    assert [i for i, x in enumerate(r) if x.startswith('待ち行列の次')][0] < len(r) - 1, r
    assert any('市場接触 1/3' in x and '床に届いていない' in x for x in r), r
    assert any(x == '待ち行列の次: 面B | 記事 1 本 | 生成 で下書き' for x in r), r


def test_T_spent_still_blocks():
    """T=8/8 でも止めない(2026-09-11 オーナー決定。回数は出口ではない。BUG-26)。表示には残る。"""
    r = sc.check(RUN.replace('**3 / 8**', '**8 / 8**'), lock(1), NOW, NOW - 600, 1, QUEUE)
    assert r, 'T=8/8 で終えてよいと言った(T は出口から外したはず)'
    assert 'T=8/8(出口ではない)' in r[-1], r[-1]   # 予算は最後の行(IMP-15)


def test_H_spent_allows():
    assert sc.check(RUN, lock(5), NOW, NOW - 600, 1, QUEUE) == []
    assert sc.check(RUN, lock(3.9), NOW, NOW - 600, 1, QUEUE), '3.9 h では終えてはいけない'


def test_compaction_allows():
    assert sc.check(RUN.replace('圧縮回数 | 0', '圧縮回数 | 2'), lock(1), NOW, NOW - 600, 1, QUEUE) == []
    assert sc.check(RUN.replace('圧縮回数 | 0', '圧縮回数 | 1'), lock(1), NOW, NOW - 600, 1, QUEUE), '1 回では終えてはいけない'


def test_stall_allows():
    assert sc.check(RUN, lock(1), NOW, NOW - 50 * 60, 1, QUEUE) == []
    assert sc.check(RUN, lock(1), NOW, NOW - 40 * 60, 1, QUEUE), '40 分では終えてはいけない'


def test_no_lock_and_no_mtime_uses_only_C():
    """錠も mtime も無い(対話の起動など)なら、出口になれるのは圧縮だけ。T=8/8 では終えない。"""
    assert sc.check(RUN, None, NOW, None, None, QUEUE)
    assert sc.check(RUN.replace('**3 / 8**', '**8 / 8**'), None, NOW, None, None, QUEUE)
    assert sc.check(RUN.replace('圧縮回数 | 0', '圧縮回数 | 2'), None, NOW, None, None, QUEUE) == []


def test_queue_skips_done_and_waiting():
    assert sc.next_queue_line(QUEUE) == '面B | 記事 1 本 | 生成 で下書き'
    assert sc.next_queue_line('- [x] 済\n- [ ] (待) 登録\n') is None
    assert sc.next_queue_line('') is None


def test_empty_queue_is_named_not_excused():
    r = sc.check(RUN, lock(1), NOW, NOW - 600, 0, '- [ ] (待) 登録\n')
    assert r and any('未完の行が無い' in x for x in r), r


def test_reset_budget():
    r = sc.reset_budget(RUN.replace('**3 / 8**', '**8 / 8**').replace('圧縮回数 | 0', '圧縮回数 | 2'))
    assert sc.RUN_T_RE.search(r).group(1) == '0', r
    assert sc.RUN_C_RE.search(r).group(1) == '0', r
    assert '/ 8' in r or '/8' in r, r


def test_contacts_week_and_rank():
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'state', 'CONTACTS.tsv')
        wed = dt.datetime(2026, 9, 16, 12, 0)          # 水曜
        contacts.add('note', 'https://note.com/a', '記事', '', path=p, now=wed)
        contacts.add('X', 'https://x.com/a/1', '投稿', '', path=p, now=wed - dt.timedelta(days=1))
        contacts.add('X', 'https://x.com/a/0', '投稿', '', path=p, now=wed - dt.timedelta(days=8))   # 先週
        assert contacts.week_count(p, wed.date()) == 2
        assert contacts.week_count(p, (wed - dt.timedelta(days=8)).date()) == 1
        assert contacts.react('https://note.com/a', 'D3', 12, path=p) == 1
        assert contacts.react('https://x.com/a/1', 'D7', 3, path=p) == 1
        r = contacts.rank(p, wed.date())
        assert r[0][0] == 'note' and r[0][3] == 12.0, r
        assert r[1][0] == 'X' and r[1][1] == 2 and r[1][2] == 3.0, r
        rows = contacts.load(p)
        assert len(rows) == 3 and rows[0][4] == '12' and rows[1][5] == '3', rows


def test_missing_contacts_file_is_zero():
    assert contacts.week_count(os.path.join(tempfile.gettempdir(), 'no_such_contacts.tsv')) == 0


def test_self_test_passes():
    assert sc.self_test() is True


def test_cli_self_test_exits_zero():
    r = subprocess.run([sys.executable, os.path.join(HERE, 'stop_check.py'), '--self-test'], capture_output=True)
    assert r.returncode == 0, r.stdout.decode('utf-8', 'replace')

def test_goal_first_even_without_status():
    """STATUS が無くても先頭はゴールの行(無いことを名指しする)。予算は最後。"""
    r = sc.check(RUN, lock(1), NOW, NOW - 600, 1, QUEUE, '')
    assert r[0].startswith('ゴール: (STATUS に [ゴール] の行が無い)'), r[0]
    assert r[-1].startswith('予算が残っている('), r[-1]


def test_status_lines_strips_markup():
    """[ゴール] 行の ** とリンク記法を落として渡す(門の文は生で読まれる)。"""
    s = chr(10).join(['# S', '[ゴール] **1,000 万円まで** あと [B79](docs/B79.md) ・ 残り 355 日', '[財布] 残高 0 円', ''])
    g, w, c = sc.status_lines(s)
    assert g == '[ゴール] 1,000 万円まで あと B79 ・ 残り 355 日', g
    assert w == '[財布] 残高 0 円', w
    assert c == '', c


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('OK', name)
            except AssertionError as e:
                print('NG', name, e)
                fails += 1
    print('失敗', fails, '件')
    sys.exit(1 if fails else 0)
