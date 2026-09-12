# -*- coding: utf-8 -*-
"""セッションを終えてよいかを機械で判定する(ハーネス v3・2026-09-11。標準ライブラリのみ)。

v2 までは STATUS の [停止] 行の書式(条件・残単位・検討した単位・ゴール欄)を 10 種類の検査で見ていた。
言い訳の書式を検査する門は、書式を満たす言い訳を生む(2026-09-10 に早すぎる停止が 7 回)。
v3 は言い訳の欄そのものを無くし、**終えてよいのは予算が尽きたときだけ**にした
(docs/audit/ハーネス見直し_2026-09-10_Fable.md §2 変更 1・§4 問 5)。

予算(どれか 1 つで「尽きた」):
  T  止まろうとした回数(表示のみ。出口にしない。2026-09-11 に外した —— 回数は判断の質を測らない。ISSUES BUG-26)
  H  起動からの経過 ≥ 上限(state/SESSION.lock の started と ttl_hours)
  C  自動圧縮 ≥ 2 回(state/RUN.md の「圧縮回数」。PreCompact フックが数える)
  S  停滞: STATUS.md と state/ の帳簿(RUN.md・RUNS.tsv・SESSION.lock・AUTORUN を除く)が 45 分以上更新されていない
     → 空回りの浪費を 1 起動分に限定する(憲章 §5.3)

予算が残っているなら止めない。理由に、今週の市場接触(state/CONTACTS.tsv)と
待ち行列の次の行(state/QUEUE.md)を添える。**行列の最後は常に生成型の発注なので空にならない。**

使い方:
    python tools/stop_check.py              # いまのリポジトリで判定。exit 0 = 終えてよい / 1 = 続ける
    python tools/stop_check.py --self-test  # わざと壊した入力で判定が反転することを見る
"""
import json
import os
import re
import sys
import time

RUN_T_RE = re.compile(r'この起動: 止まろうとした回数 / 上限 T \|[^|]*?(\d+)\s*/\s*(\d+)')
RUN_C_RE = re.compile(r'\| この起動: 圧縮回数 \|[^|\d]*(\d+)')
QUEUE_RE = re.compile(r'^- \[ \] (.*)$')
STALL_MINUTES = 45
COMPACT_CAP = 2
CONTACT_FLOOR = 3
STALL_EXCLUDE = ('RUN.md', 'RUNS.tsv', 'SESSION.lock', 'AUTORUN')
LOCK_TIME = '%Y-%m-%d %H:%M:%S'


def budget(run_text, lock_rec=None, now=None, newest_mtime=None):
    """(尽きた理由, 残っている予算の説明)。尽きた理由が 1 つでもあれば終えてよい。"""
    now = time.time() if now is None else now
    spent, left = [], []
    m = RUN_T_RE.search(run_text)
    if m:
        # T(止まろうとした回数)は数えて表示するだけで、出口にしない(2026-09-11 オーナー決定)。
        # 回数は判断の質と無関係に減る(報告のたびに 1 減り、4 h の予算のうち 1:53 で弁が開いた。ISSUES BUG-26)。
        # 出口は実測だけ: 時間(H)・文脈の喪失(圧縮)・手が止まった(無更新)。
        t, cap = int(m.group(1)), int(m.group(2))
        left.append('T=%d/%d(出口ではない)' % (t, cap))
    if lock_rec and lock_rec.get('started'):
        try:
            started = time.mktime(time.strptime(lock_rec['started'], LOCK_TIME))
            ttl = float(lock_rec.get('ttl_hours', 4.0))
            used = max(0.0, (now - started) / 3600.0)
            label = 'H=%d:%02d/%d:%02d' % (int(used), int(used * 60) % 60, int(ttl), int(round(ttl * 60)) % 60)
            (spent if used >= ttl else left).append(label)
        except (ValueError, TypeError, OverflowError):
            pass
    m = RUN_C_RE.search(run_text)
    if m:
        c = int(m.group(1))
        (spent if c >= COMPACT_CAP else left).append('圧縮=%d/%d' % (c, COMPACT_CAP))
    if newest_mtime is not None:
        idle = (now - newest_mtime) / 60.0
        if idle >= STALL_MINUTES:
            spent.append('停滞=%d 分' % int(idle))
        else:
            left.append('最終更新 %d 分前' % int(idle))
    return spent, left


def next_queue_line(queue_text):
    """待ち行列の最初の未完の行(`- [ ] …`)。`(待)` で始まる行はオーナー待ちなので飛ばす。無ければ None。"""
    for line in (queue_text or '').splitlines():
        m = QUEUE_RE.match(line.strip())
        if m and not m.group(1).lstrip().startswith('(待)'):
            return m.group(1).strip()
    return None


def status_lines(status_text):
    """STATUS.md の [ゴール] [財布] [市場接触] の 3 行を、記法(**・リンク)を落として返す。無ければ ''。"""
    import re as _re
    out = {}
    for line in (status_text or '').split(chr(10)):
        s = line.strip()
        for key in ('[ゴール]', '[財布]', '[市場接触]'):
            if s.startswith(key) and key not in out:
                body = s[len(key):].strip()
                body = _re.sub(r'\[([^\]]+)\]\([^)]*\)', lambda m: m.group(1), body).replace('**', '')
                out[key] = (key + ' ' + body)[:170]
    return out.get('[ゴール]', ''), out.get('[財布]', ''), out.get('[市場接触]', '')


def check(run_text, lock_rec=None, now=None, newest_mtime=None, contacts_week=None, queue_text='', status_text=''):
    """止めてはいけない理由のリスト。空なら終えてよい。

    v2 の Stop フック(check(status_text, run_text))から呼ばれたときは第 2 引数が RUN.md の本文なので、
    帳簿をリポジトリから読んで v3 と同じ判定を返す(フックの置換が済むまでの互換)。
    """
    if isinstance(lock_rec, str):
        root = os.environ.get('CLAUDE_PROJECT_DIR') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import contacts
        return check(lock_rec, read_lock(root), now, newest_state_mtime(root),
                     contacts.week_count(os.path.join(root, 'state', 'CONTACTS.tsv')),
                     read_text(root, 'state/QUEUE.md'), read_text(root, 'STATUS.md'))
    spent, left = budget(run_text, lock_rec, now, newest_mtime)
    if spent:
        return []
    # 返す文の順(2026-09-11 オーナー指示・IMP-15): 上流から。ゴール → 距離 → 3 つの問い → 次の行 → 予算。
    # 門は「次のタスク」を渡していた(下流)。止まろうとした瞬間に届くのは、まずゴールと距離でなければならない。
    goal, wallet, contact = status_lines(status_text)
    reasons = ['ゴール: ' + (goal or '(STATUS に [ゴール] の行が無い)')]
    dist = []
    if wallet:
        dist.append(wallet)
    if contacts_week is not None:
        dist.append('今週の市場接触 %d/%d(床)%s' % (
            contacts_week, CONTACT_FLOOR, '。床に届いていない' if contacts_week < CONTACT_FLOOR else ''))
    elif contact:
        dist.append(contact)
    reasons.append('距離: ' + (' / '.join(dist) if dist else '(STATUS に [財布][市場接触] の行が無い)'))
    reasons.append('止まる前に 1 行ずつ答える —— ①いまの計画で届くか ②届かないなら何が足りないか '
                   '③それを埋める仕事は待ち行列にあるか(無ければ、それを足すのが次の仕事)')
    nxt = next_queue_line(queue_text)
    reasons.append('待ち行列の次: ' + nxt if nxt else
                   '待ち行列に未完の行が無い。最後の行は常に生成型の発注でなければならない(state/QUEUE.md)')
    reasons.append('予算が残っている(' + ' ・ '.join(left) + ')。終えてよいのは予算切れだけ(参考。予算は出口であって理由ではない)')
    return reasons


def reset_budget(run_text):
    """起動時に T と圧縮回数を 0 に戻す(session_lock acquire が呼ぶ)。"""
    m = RUN_T_RE.search(run_text)
    if m:
        run_text = run_text[:m.start(1)] + '0' + run_text[m.end(1):]
    m = RUN_C_RE.search(run_text)
    if m:
        run_text = run_text[:m.start(1)] + '0' + run_text[m.end(1):]
    return run_text


# --- リポジトリを読む側 ---------------------------------------------------------

def read_text(root, rel):
    try:
        with open(os.path.join(root, rel), encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def read_lock(root):
    try:
        with open(os.path.join(root, 'state', 'SESSION.lock'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def newest_state_mtime(root):
    """STATUS.md と state/ の帳簿の最新更新時刻。門が自分で書く RUN.md 等は除く。"""
    paths = [os.path.join(root, 'STATUS.md')]
    sd = os.path.join(root, 'state')
    if os.path.isdir(sd):
        paths += [os.path.join(sd, n) for n in os.listdir(sd) if n not in STALL_EXCLUDE]
    ts = [os.path.getmtime(p) for p in paths if os.path.isfile(p)]
    return max(ts) if ts else None


def run_repo(root):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import contacts
    return check(read_text(root, 'state/RUN.md'), read_lock(root), None, newest_state_mtime(root),
                 contacts.week_count(os.path.join(root, 'state', 'CONTACTS.tsv')),
                 read_text(root, 'state/QUEUE.md'), read_text(root, 'STATUS.md'))


# --- 自己検査(わざと壊して判定が反転することを見る) -------------------------------

NOW = 1_800_000_000.0
RUN_OK = ('| この起動: 止まろうとした回数 / 上限 T | **3 / 8**(理由) | AI |\n'
          '| この起動: 圧縮回数 | 0 (直近 = 自動) | 機械 |\n')
STATUS_OK = chr(10).join(['# STATUS', '', '[ゴール] 目標まで あと 100 円 ・ 残り 10 日', '[財布] 残高 0 円', '[市場接触] 今週 0 / 3(床)', ''])
QUEUE_OK = ('- [x] 済んだ行\n'
            '- [ ] (待) 面A | 登録 | オーナー\n'
            '- [ ] 面B | 記事 1 本 | 生成 で下書き\n'
            '- [ ] 生成型 | 発注 1 本 | 毎週\n')


def lock_started(hours_ago, ttl=4.0):
    return {'started': time.strftime(LOCK_TIME, time.localtime(NOW - hours_ago * 3600)), 'ttl_hours': ttl}


def self_test():
    ok = True

    def report(tag, cond, msg):
        nonlocal ok
        print(('OK ' if cond else 'NG ') + tag + ': ' + msg)
        ok = ok and cond

    base = check(RUN_OK, lock_started(1), NOW, NOW - 600, 1, QUEUE_OK, STATUS_OK)
    report('予算あり', bool(base) and any(r.startswith('待ち行列の次: 面B') for r in base),
           '止めない。次の行は 面B(済と (待) を飛ばす)')
    report('G', base[0].startswith('ゴール: [ゴール] 目標まで あと 100 円') and base[-1].startswith('予算'),
           '返す文はゴールで始まり予算で終わる(IMP-15)')
    report('T', bool(check(RUN_OK.replace('**3 / 8**', '**8 / 8**'), lock_started(1), NOW, NOW - 600, 1, QUEUE_OK)),
           'T=8/8 でも終えない(T は出口ではない。BUG-26)')
    report('H', check(RUN_OK, lock_started(5), NOW, NOW - 600, 1, QUEUE_OK) == [], '起動から 5 h(上限 4 h)で終えてよい')
    report('C', check(RUN_OK.replace('圧縮回数 | 0', '圧縮回数 | 2'), lock_started(1), NOW, NOW - 600, 1, QUEUE_OK) == [],
           '自動圧縮 2 回で終えてよい')
    report('S', check(RUN_OK, lock_started(1), NOW, NOW - 50 * 60, 1, QUEUE_OK) == [], '50 分無更新(停滞)で終えてよい')
    q_empty = check(RUN_OK, lock_started(1), NOW, NOW - 600, 1, '- [x] 済\n- [ ] (待) 登録\n')
    report('Q', bool(q_empty) and any('未完の行が無い' in r for r in q_empty), '行列が空でも止めず、生成型が要ると言う')
    r = reset_budget(RUN_OK.replace('**3 / 8**', '**8 / 8**').replace('圧縮回数 | 0', '圧縮回数 | 2'))
    report('R', RUN_T_RE.search(r).group(1) == '0' and RUN_C_RE.search(r).group(1) == '0', 'reset で T と圧縮が 0 に戻る')
    return ok


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if '--self-test' in argv:
        return 0 if self_test() else 1
    reasons = run_repo(root)
    for r in reasons:
        print(r)
    if reasons:
        print('終えてはいけない(%d 件)。待ち行列の次の行を置く' % len(reasons))
        return 1
    print('終えてよい(予算切れ)')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
