# -*- coding: utf-8 -*-
"""ハーネスのバックアップと復元の共通部(標準ライブラリのみ)。監査 audit/08 Step 0(2026-09-09)。

- マニフェスト tools/harness_paths.txt を読む(空行と # を飛ばす)
- タグの木にあるパスと無いパスを分ける(git ls-tree)
- 作業ツリーにあってタグの木に無い追加ファイルを列挙する(消せば戻る側)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "tools", "harness_paths.txt")


def git(args, check=True):
    r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + " failed: " + r.stderr.strip())
    return r.stdout


def read_manifest(text):
    """マニフェストの本文 → パスの一覧(順序を保つ。空行・# 行・末尾の / を除く)。"""
    paths = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        paths.append(s.rstrip("/"))
    return paths


def tag_exists(tag):
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", tag + "^{commit}"], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0


def files_in_tree(tag, path):
    """タグの木で path(ファイルかディレクトリ)に含まれるファイルの一覧。無ければ []。"""
    out = git(["ls-tree", "-r", "--name-only", "-z", tag, "--", path], check=False)
    return [p for p in out.split("\0") if p]


def split_present(tag, paths, lister=files_in_tree):
    """(タグにあるパス, タグに無いパス)。lister は検査で差し替える。"""
    present, missing = [], []
    for p in paths:
        (present if lister(tag, p) else missing).append(p)
    return present, missing


def tracked_files_now(path):
    """いまの索引(git ls-files)で path に含まれるファイルの一覧。"""
    out = git(["ls-files", "-z", "--", path], check=False)
    return [p for p in out.split("\0") if p]


def extra_files(tag, paths, tag_lister=files_in_tree, now_lister=tracked_files_now):
    """作業ツリー(索引)にあってタグの木に無いファイル(= 戻すときに残る追加ファイル)。"""
    in_tag = set()
    now = set()
    for p in paths:
        in_tag.update(tag_lister(tag, p))
        now.update(now_lister(p))
    return sorted(now - in_tag)


def load_paths():
    with open(MANIFEST, encoding="utf-8") as f:
        return read_manifest(f.read())


def fail(msg, code=1):
    sys.stderr.write(msg.rstrip("\n") + "\n")
    return code
