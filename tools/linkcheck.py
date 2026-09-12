# -*- coding: utf-8 -*-
"""リポジトリ内の Markdown 相対リンクが実在するかを検査する。標準ライブラリのみ。

``` で囲まれたコードブロックの中は検査しない(発注書に貼る正規表現が
`](...)` と同じ形になり誤検出するため。2026-09-06)。

使い方: python tools/linkcheck.py [ルート]
戻り値: 壊れたリンクが 1 本でもあれば 1、無ければ 0
"""
import io
import os
import re
import sys
from urllib.parse import unquote

LINK = re.compile(r"\]\(([^)]+)\)")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".claude"}


def is_external(target):
    return target.startswith(("http://", "https://", "mailto:", "#"))


def check(root):
    broken = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            text = io.open(path, encoding="utf-8", errors="replace").read()
            in_fence = False
            for lineno, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                for target in LINK.findall(line):
                    target = target.strip()
                    if is_external(target) or not target:
                        continue
                    total += 1
                    rel = unquote(target.split("#", 1)[0])
                    if not rel:
                        continue
                    resolved = os.path.normpath(os.path.join(dirpath, rel))
                    if not os.path.exists(resolved):
                        broken.append((path, lineno, target))
    return total, broken


DECISIONS_ROW_MAX = 200  # v3(2026-09-11): 1 行 200 字を超えたら理由は archives/decisions/ へ


def long_decisions(root):
    """DECISIONS.md の表の行(| 日付 | …)で 200 字を超えるものを [(行番号, 字数)] で返す。"""
    path = os.path.join(root, "DECISIONS.md")
    if not os.path.exists(path):
        return []
    out = []
    for lineno, line in enumerate(io.open(path, encoding="utf-8", errors="replace").read().splitlines(), 1):
        if line.startswith("| 20") and len(line) > DECISIONS_ROW_MAX:
            out.append((lineno, len(line)))
    return out


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    total, broken = check(root)
    for path, lineno, target in broken:
        print("壊れ: {}:{} -> {}".format(path.replace(os.sep, "/"), lineno, target))
    long_rows = long_decisions(root)
    for lineno, n in long_rows:
        print("長すぎ: DECISIONS.md:{} は {} 字(上限 {}。理由は archives/decisions/ へ)".format(lineno, n, DECISIONS_ROW_MAX))
    print("検査した相対リンク {} 本 / 壊れ {} 本 / DECISIONS の長すぎる行 {} 本".format(total, len(broken), len(long_rows)))
    return 1 if (broken or long_rows) else 0


if __name__ == "__main__":
    sys.exit(main())
