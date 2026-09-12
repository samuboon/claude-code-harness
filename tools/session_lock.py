# -*- coding: utf-8 -*-
"""作業セッションの同時走行を 1 本に限る錠(監査 audit/05 §3・第 2 段-5。標準ライブラリのみ)。

錠は state/SESSION.lock(JSON 1 行)。git には入れない(.gitignore)。

使い方(AI の起動手順):
    python tools/session_lock.py acquire [--ttl-hours 4] [--label 任意の名前]
        → 空いていれば錠を書いて token を出す(exit 0)。
          先行が生きていれば(mtime が ttl 以内)先行の情報を出して exit 3 = 後発は測定だけして止まる。
          先行が古ければ(mtime が ttl 超)stale として乗っ取り、その旨を出す(exit 0)。
    python tools/session_lock.py heartbeat --token <token>   → 自分の錠の mtime を更新(exit 0 / 他人の錠なら exit 4)
    python tools/session_lock.py release --token <token>     → 自分の錠を消す(exit 0 / 他人の錠なら exit 4 / 無ければ exit 0)
    python tools/session_lock.py status                      → 空き(exit 0)/ 保持中(exit 3)/ stale(exit 0)
終了コード: 0 = 進んでよい / 3 = 先行あり(止まる)/ 4 = token 不一致 / 2 = 引数の誤り
"""
import json
import os
import secrets
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "state", "SESSION.lock")
DEFAULT_TTL_HOURS = 4.0


def read_lock(path=LOCK):
    """錠の中身と経過秒。無ければ (None, None)。壊れていれば ({"broken": True}, age)。"""
    if not os.path.exists(path):
        return None, None
    age = time.time() - os.path.getmtime(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "token" not in data:
            return {"broken": True}, age
        return data, age
    except Exception:
        return {"broken": True}, age


def is_fresh(age, ttl_hours, rec=None):
    """錠に書かれた ttl_hours を優先する(2026-09-10・BUG-13)。

    acquire は ttl_hours を錠に書き込むのに、status / acquire の判定は
    引数の既定値(4 h)しか見ていなかった。ttl 0.5 h で置かれた錠が
    47 分後も「保持中」と出て、後発が測定だけして止まる誤りにつながる。
    """
    if isinstance(rec, dict):
        try:
            ttl_hours = float(rec.get("ttl_hours", ttl_hours))
        except (TypeError, ValueError):
            pass
    return age is not None and age < ttl_hours * 3600.0


def acquire(ttl_hours=DEFAULT_TTL_HOURS, label="", path=LOCK, now=None):
    """(exit_code, message, token)。"""
    data, age = read_lock(path)
    if data is not None and is_fresh(age, ttl_hours, data) and not data.get("broken"):
        return 3, f"先行あり: label={data.get('label','')} started={data.get('started','')} age={age/60:.0f} 分(ttl {ttl_hours} h)。後発は測定だけして止まる", None
    token = secrets.token_hex(8)
    rec = {"token": token, "label": label, "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now or time.time())), "ttl_hours": ttl_hours}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, ensure_ascii=False)
        f.write("\n")
    note = ""
    if data is not None:
        note = f"(古い錠を乗っ取った: age={age/60:.0f} 分 > ttl {ttl_hours} h)" if not data.get("broken") else "(壊れた錠を上書きした)"
    return 0, f"取得 token={token} {note}".strip(), token


def heartbeat(token, path=LOCK):
    data, _ = read_lock(path)
    if data is None:
        return 4, "錠が無い"
    if data.get("token") != token:
        return 4, "token 不一致(他人の錠)"
    os.utime(path, None)
    return 0, "更新"


def release(token, path=LOCK):
    data, _ = read_lock(path)
    if data is None:
        return 0, "錠は無い(何もしない)"
    if data.get("token") != token and not data.get("broken"):
        return 4, "token 不一致(他人の錠は消さない)"
    os.remove(path)
    return 0, "解放"


def status(ttl_hours=DEFAULT_TTL_HOURS, path=LOCK):
    data, age = read_lock(path)
    if data is None:
        return 0, "空き"
    if data.get("broken"):
        return 0, f"壊れた錠(age={age/60:.0f} 分)。acquire で上書きできる"
    if is_fresh(age, ttl_hours, data):
        return 3, f"保持中: label={data.get('label','')} started={data.get('started','')} age={age/60:.0f} 分"
    return 0, f"stale: label={data.get('label','')} started={data.get('started','')} age={age/60:.0f} 分 > ttl {ttl_hours} h。acquire で乗っ取れる"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    args = argv[1:]
    ttl = DEFAULT_TTL_HOURS
    token = None
    label = ""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--ttl-hours":
            ttl = float(args[i + 1]); i += 2
        elif a == "--token":
            token = args[i + 1]; i += 2
        elif a == "--label":
            label = args[i + 1]; i += 2
        else:
            print("不明な引数: " + a)
            return 2
    if cmd == "acquire":
        rc, msg, _ = acquire(ttl, label)
        if rc == 0:
            # v3(2026-09-11): 起動のたびに RUN.md の T と圧縮回数を 0 に戻す(手書きしない)
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import stop_check
                run_path = os.path.join(ROOT, "state", "RUN.md")
                with open(run_path, encoding="utf-8") as f:
                    text = f.read()
                with open(run_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(stop_check.reset_budget(text))
                msg += "(RUN.md の T と圧縮回数を 0 に戻した)"
            except Exception as e:
                msg += "(RUN.md の初期化に失敗: %s)" % e
    elif cmd == "heartbeat":
        if not token:
            print("--token が要る"); return 2
        rc, msg = heartbeat(token)
    elif cmd == "release":
        if not token:
            print("--token が要る"); return 2
        rc, msg = release(token)
    elif cmd == "status":
        rc, msg = status(ttl)
    else:
        print("不明なコマンド: " + cmd)
        return 2
    print(msg)
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
