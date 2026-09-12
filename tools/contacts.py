# -*- coding: utf-8 -*-
"""市場接触の帳簿 state/CONTACTS.tsv(ハーネス v3・2026-09-11。標準ライブラリのみ)。

「見知らぬ人が見られる場所に置いたもの」を 1 行ずつ残し、反応(見知らぬ人の行動の数。表示や PV ではない)を後から埋める。
Stop フックは今週の置いた数を読む。配分(SKILL「仕事の進め方」)は rank を読む。週は月曜始まり。

列: 日時	経路	URL	種別	D+3反応	D+7反応	D+30円	備考

使い方:
    python tools/contacts.py add <経路> <URL> <種別> [備考]   # 置いたらすぐ 1 行(経路 = 面の名前(自分で決める))
    python tools/contacts.py react <URL> <D3|D7|D30> <値>      # 反応・円を埋める(同じ URL の行をすべて更新)
    python tools/contacts.py week [YYYY-MM-DD]                 # その日を含む週(月〜日)に置いた数
    python tools/contacts.py rank [YYYY-MM-DD]                 # 直近 14 日の 経路別「反応 ÷ 置いた数」(降順。配分の材料)
"""
import datetime as dt
import io
import os
import sys

HEADER = ['日時', '経路', 'URL', '種別', 'D+3反応', 'D+7反応', 'D+30円', '備考']
DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'state', 'CONTACTS.tsv')
REACT_COL = {'D3': 4, 'D7': 5, 'D30': 6}


def load(path=DEFAULT):
    if not os.path.exists(path):
        return []
    rows = []
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue
            cells = line.split('\t')
            if cells[0] == HEADER[0]:
                continue
            cells += [''] * (len(HEADER) - len(cells))
            rows.append(cells[:len(HEADER)])
    return rows


def save(rows, path=DEFAULT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(HEADER) + '\n')
        for r in rows:
            f.write('\t'.join(r) + '\n')


def parse_day(s):
    return dt.datetime.strptime(s[:10], '%Y-%m-%d').date()


def week_bounds(day):
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=7)


def week_count(path=DEFAULT, day=None):
    day = day or dt.date.today()
    a, b = week_bounds(day)
    n = 0
    for r in load(path):
        try:
            d = parse_day(r[0])
        except ValueError:
            continue
        if a <= d < b:
            n += 1
    return n


def add(route, url, kind, note='', path=DEFAULT, now=None):
    rows = load(path)
    now = now or dt.datetime.now()
    rows.append([now.strftime('%Y-%m-%d %H:%M'), route, url, kind, '', '', '', note])
    save(rows, path)
    return len(rows)


def react(url, col, value, path=DEFAULT):
    idx = REACT_COL[col.upper()]
    rows = load(path)
    hit = 0
    for r in rows:
        if r[2] == url:
            r[idx] = str(value)
            hit += 1
    save(rows, path)
    return hit


def rank(path=DEFAULT, day=None, days=14):
    """[(経路, 置いた数, 反応の合計, 反応 ÷ 置いた数)] を比の降順で。反応は D+7 を優先し、無ければ D+3。"""
    day = day or dt.date.today()
    since = day - dt.timedelta(days=days)
    agg = {}
    for r in load(path):
        try:
            d = parse_day(r[0])
        except ValueError:
            continue
        if d < since or d > day:
            continue
        placed, reacted = agg.get(r[1], (0, 0.0))
        val = r[5] or r[4]
        try:
            v = float(val) if val else 0.0
        except ValueError:
            v = 0.0
        agg[r[1]] = (placed + 1, reacted + v)
    out = [(route, p, s, (s / p if p else 0.0)) for route, (p, s) in agg.items()]
    out.sort(key=lambda x: (-x[3], -x[1], x[0]))
    return out


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == 'add' and len(args) >= 3:
        print('記録 %d 行目' % add(args[0], args[1], args[2], ' '.join(args[3:])))
        return 0
    if cmd == 'react' and len(args) == 3:
        n = react(args[0], args[1], args[2])
        print('更新 %d 行' % n)
        return 0 if n else 1
    if cmd == 'week':
        print(week_count(day=parse_day(args[0]) if args else None))
        return 0
    if cmd == 'rank':
        for route, placed, reacted, ratio in rank(day=parse_day(args[0]) if args else None):
            print('%s\t置いた %d\t反応 %g\t反応/置いた %.2f' % (route, placed, reacted, ratio))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
