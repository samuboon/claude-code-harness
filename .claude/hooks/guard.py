# -*- coding: utf-8 -*-
"""このプロジェクト 権限ガード(PreToolUse フック)。

オーナーの指示(2026-09-02):
  1. AI の権限範囲は プロジェクト 配下のみ。他のフォルダに手を出さない
  2. AI を標的にした攻撃(プロンプトインジェクション・サプライチェーン)に掛からない

検査:
  - Edit / Write / MultiEdit / NotebookEdit: file_path がプロジェクト配下か
    セッションの scratchpad(AppData/Local/Temp/claude 配下)でなければ拒否(exit 2)
  - Bash: パッケージ導入・外部ファイルの取得と実行・プロジェクト外への破壊的操作を拒否
標準入力に JSON(tool_name / tool_input / cwd)が渡る。exit 2 でツール呼び出しが止まる。
"""
import json
import os
import re
import sys


def norm(p: str) -> str:
    p = p.replace("\\", "/")
    p = re.sub(r"^/([a-zA-Z])/", lambda m: m.group(1).upper() + ":/", p)  # /c/Users → C:/Users
    return os.path.normcase(os.path.normpath(p)).replace("\\", "/")


def main() -> int:
    for stream in (sys.stdin, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        sys.stderr.write("BLOCKED(フック入力が読めない): " + str(e) + chr(10) + "防衛は手前で行う。guard.py を確認すること。" + chr(10))
        return 2

    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    project_n = norm(project)
    scratch_n = norm(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "claude"))

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        if not fp:
            return 0
        fp_n = norm(fp if os.path.isabs(fp) or re.match(r"^/[a-zA-Z]/", fp) else os.path.join(project, fp))
        if fp_n.startswith(project_n + "/") or fp_n == project_n or (scratch_n and fp_n.startswith(scratch_n + "/")):
            return 0
        sys.stderr.write(
            f"BLOCKED(権限範囲外): {fp}\n"
            f"AI の書き込み先は プロジェクト 配下と scratchpad のみ(オーナー指示 2026-09-02)。\n"
        )
        return 2

    if tool == "Bash":
        cmd = inp.get("command", "") or ""
        # ヒアドキュメントの本文(cat > file <<'EOF' ... EOF)は文書の中身であり、コマンドではないので検査から外す
        cmd = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?\n.*?\n\1\s*$", "<<HEREDOC", cmd, flags=re.S | re.M)
        rules = [
            (r"\b(pip3?|pipx|uv)\s+(install|add)\b", "Python パッケージの導入"),
            (r"\bnpm\s+(i|install|add|ci)\b|\bnpx\b|\bpnpm\s+(i|install|add)\b|\byarn\s+(add|install)\b", "Node パッケージの導入・実行"),
            (r"\bcargo\s+install\b|\bgo\s+install\b|\bgem\s+install\b|\bwinget\b|\bchoco\b|\bscoop\b", "ツールの導入"),
            (r"\b(curl|wget|iwr|Invoke-WebRequest|Invoke-RestMethod)\b.*\|\s*(sh|bash|pwsh|powershell|python|node)\b", "取得したスクリプトの直接実行"),
            (r"\b(curl|wget|iwr|Invoke-WebRequest)\b.*(\s-o\s|\s-O\b|--output|-OutFile)", "外部ファイルのダウンロード保存"),
            (r"\b(Start-Process|\.exe\b|\.msi\b|\.bat\b|\.ps1\b)", "実行ファイル・スクリプトの起動"),
            (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?(/|[A-Za-z]:|~|\$HOME|\.\.)", "プロジェクト外への削除"),
            (r"\b(git\s+push|git\s+remote\s+add)\b", "push(オーナーの専権)"),
        ]
        for pat, why in rules:
            if re.search(pat, cmd, flags=re.IGNORECASE):
                sys.stderr.write(
                    f"BLOCKED({why}): この操作はオーナーの承認が要る(供給網攻撃・権限範囲の防衛)。\n"
                    f"必要なら理由を添えてオーナーに依頼し、オーナー自身が実行する。\n"
                )
                return 2
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
