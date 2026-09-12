# -*- coding: utf-8 -*-
"""このプロジェクト 権限ガード(PreToolUse フック)。**v2・2026-09-12 敵対的セルフレビュー 2 ラウンド後**。

本番は .claude/hooks/guard.py(保護対象。オーナーが .claude/unlock.md を手で作ったときだけ書ける)。
直すときは tools/guard_next.py(本番の写し)で直し、GUARD_PATH=tools/guard_next.py で
tools/test_guard.py(19 本)と tools/test_guard_attack.py(44 本)を通し、直近セッションの実コマンドを
リプレイして誤検知を数えてから、unlock 中に cp で移す(手順は README)。

オーナーの指示:
  2026-09-02  エージェントの権限範囲は プロジェクト配下のみ / AI 標的攻撃に掛からない
  2026-09-12  攻撃は避けようがない。**受けても大丈夫な環境**を作る。無駄な規約を増やさず、業務の品質を下げない
  2026-09-12  「100% は無い。でも大半の人間は事故を起こさない。**事故らない仕組みになっているか確認しろ**」

設計の前提(v2 で変えた):
  **エージェントが完全に乗っ取られた(取得物の指示に従ってしまった)としても、
  ①防御を外せない ②鍵を外に出せない ③私用端末のファイルを読めない ④オーナーの個人情報を外に書けない**
  —— 判断が破られても実行が破られない、という置き方にする。
  そのために「読む」は自由のままだが、**プロジェクトの外を読むこと**だけは止める(私用端末だから)。

検査(ツール別):
  全ツール   E 鍵そのもの(github_pat_ 等)が引数に現れたら拒否
  Edit/Write A 書き込み先はプロジェクト配下/scratchpad  B 防御ファイルは unlock.md が無いと書けない。unlock.md 自体は常に拒否
  Read/Glob/Grep  P プロジェクト・scratchpad・このプロジェクトのセッション記録の外は読めない
  Bash       B' 防御ファイル(.claude/hooks・settings・allowed_hosts・.git/config・unlock.md)が**書き込みの対象**なら拒否
                (読むだけ・公開用の木 public/ へ cp・文書の中の語、では止めない)
             C  導入・起動(起動は**コマンド位置**にあるときだけ。ファイル名の言及は起動ではない)
             X  パイプからシェルへ / eval / base64 復号 / EncodedCommand / ssh・scp・nc / git config --global /
                setx・reg・schtasks・netsh / PowerShell の ItemProperty・ScheduledTask(端末の設定そのもの)
             Y  python -c・python <<EOF・powershell の中の送信・鍵の読み出し・起動(**Python 自体は封じない**)
             P  プロジェクト外の絶対パス(scratchpad・リモート受付の一時領域・このプロジェクトのセッション記録は可)
             D  送る操作は宛先が allowed_hosts.txt に無ければ拒否。**宛先が文字列から読めない送信も拒否**(変数に隠せるため。
                remote 名だけの git push は remote の URL を引く)+ 送る本文に個人情報が無いか(パスは除く)
  CronCreate/CronDelete/RemoteTrigger  拒否(定期実行・遠隔起動はオーナー専権。自走は /loop)
  WebFetch/WebSearch  https のみ + URL・検索語に個人情報が無いか
  Artifact   公開系は拒否(読むだけの action は可)
  SendUserFile  private/ とプロジェクト外は送れない
  mcp__*     claude-in-chrome(オーナー個人の Chrome)は全部拒否 / mcp-registry(導入)・scheduled-tasks の作成は拒否
             navigate は https のみ / 打つ・送るツールは個人情報・鍵・許可外 URL を拒否
  記録       拒否・外部送信・外部取得を private/guard.log に 1 行(鍵はマスク)

個人情報のパターンは .claude/hooks/private_patterns.txt(保護対象。公開用の木には入れない。leak_scan が見張る)。
標準入力に JSON(tool_name / tool_input / cwd)が渡る。exit 2 でツール呼び出しが止まる。
"""
import json
import os
import re
import sys
import time

# ---- 鍵そのものの形。出どころを問わず、どのツールの引数に現れても止める ----
SECRET_PATTERNS = [
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub の fine-grained トークン"),
    (r"\bghp_[A-Za-z0-9]{30,}", "GitHub の classic トークン"),
    (r"\bgho_[A-Za-z0-9]{30,}", "GitHub の OAuth トークン"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "秘密鍵"),
    (r"\bsk-[A-Za-z0-9]{20,}", "API キー"),
]

# ---- 外部へ「送る」コマンド。これに当たったときだけ宛先と本文を見る(読むだけの curl は自由) ----
SEND_PATTERNS = [
    r"\bcurl\b.*(\s-d\b|--data|\s-F\b|--form|\s-T\b|--upload-file|-X\s*(POST|PUT|PATCH|DELETE))",
    r"\b(Invoke-RestMethod|irm)\b",
    r"\bInvoke-WebRequest\b.*(-Method\s*(Post|Put|Patch|Delete)|-Body)",
    r"\bwget\b.*(--post-data|--post-file)",
    r"\bgit\s+push\b",
]

# ---- 実行の迂回。シェルへの流し込みは中身が読めないので一律に止める。python/node への流し込みは中身を見る(Y) ----
EXEC_PATTERNS = [
    (r"(?<!\\)\|\s*(sh|bash|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b", "パイプからシェルへの流し込み"),  # grep の \| は除く
    (r"\b(sh|bash|zsh|dash|pwsh|powershell)\s*<<", "ヒアドキュメントのシェルへの流し込み"),
    (r"\beval\b|\bexec\s+[\"'$(]", "eval / exec"),
    (r"\bbase64\s+(-d|--decode)\b|FromBase64String|\bcertutil\b", "エンコードされた中身の復号(中身が見えない)"),
    (r"\bInvoke-Expression\b|\biex\b|-EncodedCommand\b|\s-enc\b|\s-e\s+[A-Za-z0-9+/=]{16,}", "PowerShell の見えない実行"),
    (r"\b(ssh|scp|sftp|ftp|nc|ncat|netcat|telnet|rsync|smbclient|Send-MailMessage)\b", "事業で使わない送信経路"),
    (r"\bgit\s+remote\s+(add|set-url|rename)\b", "remote の変更(宛先の付け替え。オーナー専権)"),
    # 第 2 ラウンド(2026-09-12): 端末の設定そのものを変える操作。プロジェクトの外に効くので一律に止める
    (r"\bgit\s+config\b[^;&|\n]*--(global|system)\b", "git の全体設定の変更(プロジェクト外)"),
    (r"\bsetx\b|\breg\s+(add|delete|import|load|restore)\b|\bschtasks\b|\bnet\s+user\b|\bnetsh\b|\bsc\s+(create|config|delete)\b", "端末の設定・自動起動の変更(オーナー専権)"),
    (r"\b(Set|New|Remove)-ItemProperty\b|\b(Register|New)-ScheduledTask\b|\bNew-Service\b|\bSet-ExecutionPolicy\b", "PowerShell からの端末の設定の変更"),
]

# 事業で使わない道具(MCP 以外)。定期実行の設定はオーナー専権、別セッションへの指示は injection の伝播経路
DENY_TOOLS = ("CronCreate", "CronDelete", "RemoteTrigger")

# ---- python -c / python - <<EOF / | python -c / powershell の中で止める語(通信・鍵・防御ファイル・起動) ----
# **Python を封じない**(オーナー 2026-09-12「python を一律に封じると仕事にならない」)。止めるのは通信・鍵・起動だけ。
# subprocess/os.system は外す —— その中の curl -d 等は raw 全体への SEND/EXEC 検査が捕まえる。
# 防御ファイルへの書き込みは B'(WRITE_FORMS + PROTECTED_RE)が捕まえるので、ここに .claude は要らない
# 語は「コードとして使う形」に絞る(英単語の requests / socket や、文書に書いた credstore という語では止めない)
PY_INLINE_DANGER = (r"import\s+(?:urllib|socket|http\.client|smtplib|ftplib|requests|httpx|aiohttp|webbrowser|credstore)\b"
                    r"|from\s+(?:urllib|http|credstore)\b|urllib\.|socket\.|smtplib\.|ftplib\.|requests\.(?:get|post|put|delete|Session)"
                    r"|httpx\.|webbrowser\.|os\.startfile|credstore\.read")
PS_DANGER = r"WebClient|HttpClient|WebRequest|Sockets|Net\.|Start-Process|Invoke-Item|Add-Type|credstore\.py"
# 本文の範囲: -c の直後の引用符の中 / ヒアドキュメントの本文(終端語まで)
PY_INLINE = re.compile(
    r"\b(?:python[0-9]?|py)\s+(?:-c\s+(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|(\S+))"
    r"|-?\s*<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\4\s*$)", re.S | re.M)

# ---- 起動と見なす形: 「コマンド位置」にある実行ファイル、または明示的な起動子(ファイル名の言及は起動ではない) ----
EXEC_EXT = r"(?:exe|msi|bat|cmd|ps1|vbs|scr|com)"
LAUNCH_PATTERNS = [
    r"\bStart-Process\b|\bcmd(\.exe)?\s+//?c\b|\bpowershell(\.exe)?\b[^\n]*\s-File\b|\b[wc]script\b",
    # コマンド位置 = 行頭 / ; & | の後 / $( の後。素の ( は入れない —— コミットメッセージや文書の括弧「(x.bat も追加)」で誤爆した(2026-09-12)
    r"(?:^|[;&|]\s*|&&\s*|\|\|\s*|\$\(\s*)[\"']?[^\s;&|\"']*\." + EXEC_EXT + r"\b",
]


def launch_view(cmd: str) -> str:
    """起動の判定に使う文字列。ヒアドキュメント本文と、git commit のメッセージ引数は「文」なので外す。"""
    v = strip_all_heredoc(cmd)
    return re.sub(r"\bgit\s+commit\b[^\n;&|]*", "git commit", v)

PROTECTED = (
    ".claude/hooks/",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/allowed_hosts.txt",
)
# Bash では「**書き込みの対象**が防御ファイル」のときだけ止める。
# 文書の中に .claude/hooks という語があるだけ、読むだけ、公開用の木(public/)へ cp するだけ、では止めない
_PROT = r"[^\s'\"();&|,]*(?:\.claude[/\\](?:hooks|settings|allowed_hosts)|allowed_hosts\.txt|private_patterns\.txt|\.git[/\\]config)[^\s'\"();&|,]*"
_UNLK = r"[^\s'\"();&|,]*(?:\.claude[/\\]unlock|unlock\.md)[^\s'\"();&|,]*"


def write_target_re(target: str):
    """target(防御ファイルのパスの形)が「書き込みの対象」になる形をすべて列挙する。"""
    t = "(?:" + target + ")"
    return re.compile(
        r"(?<![0-9])>{1,2}\s*['\"]?" + t                                              # > .claude/hooks/x
        + r"|\bsed\s+-i[^;&|\n]*\s['\"]?" + t                                          # sed -i ... x
        + r"|\btee\s+(?:-a\s+)?['\"]?" + t                                              # tee x
        + r"|\b(?:mv|rm|touch|truncate|del|rmdir|mkdir)\b[^;&|\n]*\s['\"]?" + t         # rm/mv/touch ... x
        + r"|\bcp\b(?:\s+[^\s;&|]+)*\s+['\"]?" + t + r"['\"]?\s*(?:$|[;&|])"            # cp ... x(宛先)
        + r"|open\(\s*['\"]" + t + r"['\"]\s*,\s*['\"][wa]"                             # open('x','w')
        + r"|Path\(\s*['\"]" + t + r"['\"]\s*\)\s*\.(?:write_text|write_bytes|unlink|touch|rename|replace)"  # Path('x').write_text
        + r"|(?:shutil\.(?:copy|copy2|copyfile|move)|os\.(?:rename|replace))\([^)]*,\s*['\"]" + t + r"['\"]"  # shutil.copy(src, 'x')
        + r"|(?:os\.remove|os\.unlink|os\.rmdir|shutil\.rmtree)\(\s*['\"]" + t + r"['\"]"  # os.remove('x')
        + r"|(?:Set-Content|Out-File|Add-Content|Copy-Item|Move-Item|Remove-Item|New-Item)\b[^;&|\n]*['\"]?" + t,
        re.IGNORECASE | re.M)


PROTECTED_WRITE = write_target_re(_PROT)
UNLOCK_WRITE = write_target_re(_UNLK)


def writes_protected(rx, raw: str) -> bool:
    """書き込みの対象に防御ファイルがあるか。public/ 配下(公開用の木)と、cd 先が public/ のときの相対パスは除く。"""
    cd_public = re.match(r"\s*cd\s+[\"']?[^\"';&|]*public[/\\]", raw) is not None
    for m in rx.finditer(raw):
        hit = m.group(0)
        if "public/" in hit or "public\\" in hit:
            continue
        if cd_public and not re.search(r"[A-Za-z]:[/\\]|(?<![A-Za-z0-9.])/[a-zA-Z]", hit):
            continue  # 公開用の木の中で相対パスを触っている
        return True
    return False

PROJECT_SESSION_KEY = "harness"  # ~/.claude/projects/ の中で、このプロジェクトの記録のディレクトリ名に含まれる語。使う人が変える
READ_TOOLS = ("Read", "Glob", "Grep")
MCP_DENY_PREFIX = (
    "mcp__claude-in-chrome__",          # オーナー個人のログイン済み Chrome。事業の操作は分離ブラウザ(内蔵ブラウザ)で行う
    "mcp__mcp-registry__",              # コネクタの導入(供給網)
    "mcp__scheduled-tasks__create",     # 自動実行の設定(オーナー専権)
    "mcp__scheduled-tasks__update",
    "mcp__scheduled-tasks__run",
    "mcp__ccd_session_mgmt__send_message",   # 別セッション(別のプロジェクト等)への指示 = injection の伝播経路
    "mcp__ccd_session_mgmt__stop_session",
    "mcp__ccd_session_mgmt__delete_session",
    "mcp__ccd_session_mgmt__clear_session",
)
MCP_SEND_TOOLS = ("form_input", "file_upload", "upload_image")
ARTIFACT_READ_ACTIONS = ("read", "list", "comments", "status", "list_files", "read_file", "list_assets", "read_asset", "read_db", "list_types")


def norm(p: str) -> str:
    p = os.path.expanduser(p)
    p = p.replace("\\", "/")
    p = re.sub(r"^/([a-zA-Z])/", lambda m: m.group(1).upper() + ":/", p)  # /c/Users → C:/Users
    return os.path.normcase(os.path.normpath(p)).replace("\\", "/")


def mask(text: str) -> str:
    for pat, _why in SECRET_PATTERNS:
        text = re.sub(pat, "<MASKED>", text)
    return text


def log(project: str, verdict: str, detail: str) -> None:
    if os.environ.get("GUARD_DRY"):  # 過去のコマンドを流して誤検知を測るとき、記録を汚さない
        return
    try:
        d = os.path.join(project, "private")
        os.makedirs(d, exist_ok=True)
        line = time.strftime("%Y-%m-%d %H:%M:%S") + "\t" + verdict + "\t" + mask(detail).replace("\n", " ")[:300]
        with open(os.path.join(d, "guard.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_lines(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    out.append(line)
    except OSError:
        pass
    return out


def load_allowed(project: str):
    """許可ホスト。**ファイルが無い・空なら「送る」操作をすべて拒否する**(開くほうへ倒さない)。"""
    return [h.lower() for h in load_lines(os.path.join(project, ".claude", "allowed_hosts.txt"))]


def load_private(project: str):
    """オーナーの識別子(ユーザー名・本名など)。外向きの操作の本文に現れたら止める。無ければ検査しない。
    GUARD_PRIVATE_FILE は検査・リプレイ用の差し替え(本番は .claude/hooks/private_patterns.txt で、保護対象)。"""
    return load_lines(os.environ.get("GUARD_PRIVATE_FILE") or os.path.join(project, ".claude", "hooks", "private_patterns.txt"))


def host_allowed(host: str, allowed) -> bool:
    host = (host or "").lower().strip().rstrip(".")
    if not host or not allowed:
        return False
    for a in allowed:
        if a.startswith("."):
            if host == a[1:] or host.endswith(a):
                return True
        elif host == a:
            return True
    return False


def urls_in(text: str):
    return re.findall(r"https?://([A-Za-z0-9._-]+)", text or "")


def find_secret(text: str):
    for pat, why in SECRET_PATTERNS:
        if re.search(pat, text or ""):
            return why
    return None


def find_private(text: str, patterns):
    low = (text or "").lower()
    for p in patterns:
        if p.lower() in low:
            return p
    return None


def allowed_roots(project: str):
    """読んでよい場所: プロジェクト / scratchpad / リモート受付の一時領域 / このプロジェクトのセッション記録。"""
    roots = [norm(project)]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.append(norm(os.path.join(local, "Temp", "claude")))
        roots.append(norm(os.path.join(local, "Temp", "harness_remote_control")))  # 遠隔起動の受付が使う(無ければ無視される)
    return roots


def _temp_dir():
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Temp") if local else os.environ.get("TEMP", "")


def path_ok(p: str, project: str) -> bool:
    n = norm(p)
    for r in allowed_roots(project):
        if n == r or n.startswith(r + "/"):
            return True
    # セッション記録: 一覧(~/.claude/projects)と、このプロジェクトの記録(名前に PROJECT_SESSION_KEY を含む)だけは読める。
    # 他のプロジェクトの記録は私用端末の中身なので読まない
    sess = norm(os.path.join(os.path.expanduser("~"), ".claude", "projects"))
    if n == sess:
        return True
    if n.startswith(sess + "/"):
        rest = n[len(sess) + 1:]
        top = rest.split("/", 1)[0]
        if PROJECT_SESSION_KEY in top:
            return True
    return False


ABS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[/\\]|~[/\\]|~$|\$HOME\b|\$USERPROFILE\b|%USERPROFILE%|\$LOCALAPPDATA\b|%LOCALAPPDATA%|\$APPDATA\b|%APPDATA%|\$TE?MP\b|%TE?MP%|(?<![A-Za-z0-9./])/[a-z]/)[^\s\"'|;&<>)]*")


def abs_paths_in(cmd: str):
    """コマンドの中の絶対パス。git commit のメッセージ引数は「文」なので見ない(2026-09-12: メッセージ中の ~/.cache/… で誤検知)。
    $USERPROFILE / $LOCALAPPDATA / $APPDATA も展開して判定する(2026-09-12: $USERPROFILE 配下の読み取りが素通りしていた)。"""
    out = []
    temp = _temp_dir()
    local = os.environ.get("LOCALAPPDATA", "").replace("\\", "/")
    roaming = os.environ.get("APPDATA", "").replace("\\", "/")
    view = re.sub(r"\bgit\s+commit\b[^\n;&|]*", "git commit", cmd or "")
    for m in ABS_PATH.finditer(view):
        p = m.group(0)
        p = re.sub(r"\$HOME\b|\$USERPROFILE\b|%USERPROFILE%", "~", p)
        p = re.sub(r"\$LOCALAPPDATA\b|%LOCALAPPDATA%", local, p)
        p = re.sub(r"\$APPDATA\b|%APPDATA%", roaming, p)
        p = re.sub(r"\$TE?MP\b|%TE?MP%", temp.replace("\\", "/"), p)
        out.append(p)
    return out


# ヒアドキュメント演算子の直前(head)の最後のコマンドがインタプリタか(head には << 自体は含まれない)
INTERP_HEREDOC = re.compile(r"(?:^|[;&|]\s*)(?:[A-Za-z_]+=\S+\s+)*(sh|bash|zsh|dash|pwsh|powershell|cmd|python[0-9]?|py|node|perl|ruby)(\.exe)?\b[^\n;&|<]*$")


def strip_file_heredoc(cmd: str) -> str:
    """インタプリタへ流すヒアドキュメント(bash <<EOF / python <<EOF)**以外**は、本文を検査から外す。
    cat > f / tee f / git commit -F - / の本文は文書やメッセージであってコマンドではない
    (2026-09-12: コミットメッセージの中の「git push」という語で送信と誤認し、エージェント自身のコミットを止めた)。"""
    def repl(m):
        head = m.group(1)
        if INTERP_HEREDOC.search(head):
            return m.group(0)  # インタプリタへ流す本文は残して検査する
        return head + "<<HEREDOC"
    return re.sub(r"([^\n]*?)<<-?\s*['\"]?(\w+)['\"]?\n.*?\n\2\s*$", repl, cmd, flags=re.S | re.M)


def strip_all_heredoc(cmd: str) -> str:
    """すべてのヒアドキュメント本文を外す(起動の判定用。本文の中の 'x.exe' という文字列は起動ではない)。"""
    return re.sub(r"<<-?\s*['\"]?(\w+)['\"]?\n.*?\n\1\s*$", "<<HEREDOC", cmd, flags=re.S | re.M)


def remote_hosts(project: str, cmd: str):
    """`git push <remote> ...` の remote 名から URL を引き、ホストを返す。引けなければ []。"""
    import subprocess
    m = re.search(r"\bgit\s+push\s+(?:-[^\s]+\s+)*([A-Za-z0-9_.-]+)", cmd)
    name = m.group(1) if m else "origin"
    try:
        r = subprocess.run(["git", "-C", project, "remote", "get-url", name], capture_output=True, text=True, timeout=5)
        url = (r.stdout or "").strip()
    except Exception:
        return []
    if not url:
        return []
    hosts = urls_in(url)
    if not hosts and "@" in url and ":" in url:      # git@github.com:x/y(ssh 形式)
        hosts = [url.split("@", 1)[1].split(":", 1)[0]]
    return hosts


def deny(project, why, how, detail=""):
    log(project, "DENY", why + " | " + detail)
    sys.stderr.write("BLOCKED(" + why + ")\n" + how + "\n")
    return 2


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
    blob = json.dumps(inp, ensure_ascii=False)
    unlocked = os.path.exists(os.path.join(project, ".claude", "unlock.md"))

    # ===== 事業で使わない道具 =====
    if tool in DENY_TOOLS:
        return deny(project, "使わない道具: " + tool, "定期実行の設定・遠隔起動はオーナー専権。自走は /loop(ScheduleWakeup)で行う。")

    # ===== E 鍵の流出(どのツールでも) =====
    why = find_secret(blob)
    if why:
        return deny(project, "鍵そのものがツールの引数に現れた: " + why,
                    "鍵を文字列として渡さない。使うときは tools/credstore.py から読み、値を画面・コマンド・投稿に出さない。", tool)

    # ===== A/B 書き込み =====
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        if not fp:
            return 0
        fp_n = norm(fp if os.path.isabs(fp) or re.match(r"^/[a-zA-Z]/", fp) else os.path.join(project, fp))
        if not path_ok(fp_n, project):
            return deny(project, "権限範囲外: " + fp, "エージェントの書き込み先は プロジェクト配下と scratchpad のみ(オーナー指示 2026-09-02)。")
        rel = fp_n[len(project_n) + 1:] if fp_n.startswith(project_n + "/") else ""
        if rel == ".claude/unlock.md":
            return deny(project, "解錠ファイルへの書き込み", "unlock.md は**オーナーが手で作る**もの。AI が自分で解錠することはできない(2026-09-12)。")
        if any(rel == p or rel.startswith(p) for p in PROTECTED) and not unlocked:
            return deny(project, "防御ファイルの変更: " + rel,
                        "ここは攻撃者が最初に狙う場所。変えるにはオーナーが .claude/unlock.md を手で作る(週次レビューの場で)。", rel)
        return 0

    # ===== P 読み取り(私用端末の外を読まない) =====
    if tool in READ_TOOLS:
        p = inp.get("file_path") or inp.get("path") or ""
        if p and not path_ok(p, project):
            return deny(project, "プロジェクト外の読み取り: " + p,
                        "読めるのは プロジェクト・scratchpad・このプロジェクトのセッション記録だけ(私用端末のため)。必要ならオーナーに頼む。")
        return 0

    # ===== Bash =====
    if tool == "Bash":
        raw = inp.get("command", "") or ""
        cmd = strip_file_heredoc(raw)

        # B' 防御ファイルが**書き込みの対象**になっているか(読むだけ・公開用の木へ cp・文書の中の語、では止めない)
        if writes_protected(UNLOCK_WRITE, raw):
            return deny(project, "解錠ファイルへの書き込み", "unlock.md はオーナーが手で作り、手で消す。AI は Bash からも触れない。", raw[:200])
        if not unlocked and writes_protected(PROTECTED_WRITE, raw):
            return deny(project, "防御ファイルへの Bash からの書き込み",
                        "guard.py・settings.json・allowed_hosts.txt は Bash からも書けない。読むのは自由。変えるならオーナーの unlock.md。", raw[:200])

        # C 供給網・起動
        rules = [
            (r"\b(pip3?|pipx|uv)\s+(install|add)\b", "Python パッケージの導入"),
            (r"\bnpm\s+(i|install|add|ci)\b|\bnpx\b|\bpnpm\s+(i|install|add)\b|\byarn\s+(add|install)\b", "Node パッケージの導入・実行"),
            (r"\bcargo\s+install\b|\bgo\s+install\b|\bgem\s+install\b|\bwinget\b|\bchoco\b|\bscoop\b", "ツールの導入"),
            (r"\b(curl|wget|iwr|Invoke-WebRequest|Invoke-RestMethod)\b.*\|\s*(sh|bash|pwsh|powershell|python|node)\b", "取得したスクリプトの直接実行"),
            (r"\b(curl|wget|iwr|Invoke-WebRequest)\b.*(\s-o\s|\s-O\b|--output|-OutFile)", "外部ファイルのダウンロード保存"),
            (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?(/|[A-Za-z]:|~|\$HOME|\.\.)", "プロジェクト外への削除"),
        ]
        for pat, why in rules:
            if re.search(pat, cmd, flags=re.IGNORECASE):
                return deny(project, why, "この操作はオーナーの承認が要る(供給網攻撃・権限範囲の防衛)。必要なら理由を添えてオーナーに依頼する。", raw[:200])
        # 起動: ヒアドキュメント本文と commit メッセージは見ない(その中の 'x.bat' は文であって起動ではない)。コマンド位置だけ
        lv = launch_view(cmd)
        for pat in LAUNCH_PATTERNS:
            if re.search(pat, lv, flags=re.IGNORECASE):
                return deny(project, "実行ファイル・スクリプトの起動", "起動はオーナーの承認が要る。ファイル名の言及(git add など)は起動ではないので通る。", raw[:200])

        # X 実行の迂回
        for pat, why in EXEC_PATTERNS:
            if re.search(pat, cmd, flags=re.IGNORECASE):
                return deny(project, why, "中身が見えない実行・事業で使わない経路は一律に止める。同じことはファイルに書いた Python(tools/*.py)で行う。", raw[:200])

        # Y python -c / python - <<EOF / | python -c の中身(通信・鍵・起動があれば止める。整形程度なら通る)
        for m in PY_INLINE.finditer(cmd):
            body = m.group(1) or m.group(2) or m.group(3) or m.group(5) or ""
            if re.search(PY_INLINE_DANGER, body):
                return deny(project, "python の 1 行コード/ヒアドキュメントの中に送信・鍵・起動",
                            "その場のコードでは通信・鍵・起動を扱わない。tools/ のスクリプト(git に残る)に書いて実行する。", raw[:200])
            # 変数経由の書き込み(p='.claude/settings.json'; open(p,'w'))は、文字列リテラルと書き込みの形が同居したら止める。
            # 文書の本文に .claude/hooks という語があるだけ(リテラルの先頭でない)なら止めない
            lit = re.search(r"['\"](?:\./)?\.claude(?:[/\\](?:hooks|settings|allowed_hosts|unlock)[^'\"]*)?['\"]", body)
            wr = re.search(r"open\([^)]*['\"][wa]b?['\"]|write_text|write_bytes|shutil\.|os\.(?:remove|unlink|rename|replace|rmdir)|\.unlink\(|\.rename\(|rmtree", body)
            if lit and wr and not unlocked:
                return deny(project, "python のコードの中で防御ファイルを書き込みの対象にしている: " + lit.group(0),
                            "guard.py・settings.json・allowed_hosts.txt・unlock.md は変数を経由しても書けない。変えるならオーナーの unlock.md。", raw[:200])
        if re.search(r"\b(powershell|pwsh)(\.exe)?\b", cmd, flags=re.IGNORECASE) and re.search(PS_DANGER, cmd, flags=re.IGNORECASE):
            return deny(project, "PowerShell の中に送信・起動・鍵への言及", "PowerShell から通信・起動を行わない。", raw[:200])

        # P プロジェクト外の絶対パス
        for p in abs_paths_in(cmd):
            if not path_ok(p, project):
                return deny(project, "プロジェクト外のパス: " + p,
                            "触れるのは プロジェクト・scratchpad・このプロジェクトのセッション記録だけ(私用端末のため)。", raw[:200])

        # D 送る操作: 宛先と本文。**宛先が文字列から読めない送信は止める**(変数や設定ファイルに隠せるため)
        if any(re.search(p, cmd, flags=re.IGNORECASE) for p in SEND_PATTERNS):
            allowed = load_allowed(project)
            hosts = urls_in(cmd)
            if not hosts and re.search(r"\bgit\s+push\b", cmd, flags=re.IGNORECASE):
                # `git push origin main` は remote の URL を引いて判定する(remote add/set-url と .git/config は止めているので、
                # remote はオーナーが置いたもの)。引けなければ宛先不明として止める
                hosts = remote_hosts(project, cmd)
            bad = [h for h in hosts if not host_allowed(h, allowed)]
            if bad or not hosts:
                return deny(project, "許可されていない宛先へ送ろうとした: " + (", ".join(bad) or "(宛先が読めない)"),
                            "送れるのは .claude/allowed_hosts.txt のホストだけ(承認範囲 docs/H* と 1 対 1)。宛先は URL で書く(変数に入れない)。"
                            "経路を増やすなら先に H を 1 枚書き、オーナーが unlock.md を置いてから足す。", raw[:200])
            # 個人情報は「送る本文」だけを見る。cwd や引数のパス(C:/Users/<ユーザー名>/…)は内向きの情報なので除く
            body = ABS_PATH.sub("", cmd)
            hit = find_private(body, load_private(project))
            if hit:
                return deny(project, "送る本文にオーナーの識別子: " + hit, "オーナー個人を指す語は外に出さない(失格条件 2-1)。", raw[:200])
            log(project, "SEND", " ".join(hosts) + " | " + raw[:120])
        return 0

    # ===== WebFetch / WebSearch =====
    if tool in ("WebFetch", "WebSearch"):
        text = str(inp.get("url", "")) + " " + str(inp.get("query", ""))
        if text.strip().startswith("http://"):
            return deny(project, "http の取得先", "取得先は https のみ。https で開き直す。")
        hit = find_private(text, load_private(project))
        if hit:
            return deny(project, tool + " にオーナーの識別子: " + hit, "URL や検索語に個人情報を載せない(送信になる)。")
        log(project, "FETCH", tool + " | " + text[:200])
        return 0

    # ===== Artifact(公開 = 外部送信) =====
    if tool == "Artifact":
        action = str(inp.get("action", "") or "publish")
        if action in ARTIFACT_READ_ACTIONS:
            return 0
        return deny(project, "Artifact の公開・書き込み: " + action,
                    "公開ページを作ることは外部送信。事業では使わない。オーナーへの報告は SendUserFile か文書で行う。")

    # ===== SendUserFile =====
    if tool == "SendUserFile":
        for f in inp.get("files", []) or []:
            f_n = norm(f if os.path.isabs(str(f)) else os.path.join(project, str(f)))
            if not path_ok(f_n, project) or "/private/" in f_n or f_n.endswith("/private"):
                return deny(project, "送れないファイル: " + str(f), "private/ とプロジェクト外は送らない。")
        return 0

    # ===== MCP =====
    if tool.startswith("mcp__"):
        for pre in MCP_DENY_PREFIX:
            if tool.startswith(pre):
                return deny(project, "使わない道具: " + tool,
                            "オーナー個人の Chrome・導入・自動実行の設定は エージェントの範囲外。事業のブラウザ操作は 内蔵ブラウザ で行う。")
        short = tool.rsplit("__", 1)[-1]
        if short == "navigate":
            url = str(inp.get("url", ""))
            if url.startswith("http://"):
                return deny(project, "http の取得先: " + url, "取得先は https のみ。https で開き直す。")
            log(project, "FETCH", tool + " | " + url[:200])
            return 0
        typed = ""
        if short in MCP_SEND_TOOLS:
            typed = blob
        elif short == "computer" and str(inp.get("action", "")) == "type":
            typed = str(inp.get("text", ""))
        elif short in ("javascript_tool", "evaluate"):
            typed = str(inp.get("text", "")) + str(inp.get("expression", ""))
        if typed:
            allowed = load_allowed(project)
            bad = [h for h in urls_in(typed) if not host_allowed(h, allowed)]
            if bad:
                return deny(project, "許可されていない宛先への入力: " + ", ".join(bad),
                            "送れるのは .claude/allowed_hosts.txt のホストだけ。取得物に載っていた URL へは送らない。", tool)
            hit = find_private(typed, load_private(project))
            if hit:
                return deny(project, "入力にオーナーの識別子: " + hit, "オーナー個人を指す語は外に出さない(失格条件 2-1)。", tool)
            log(project, "SEND", tool + " | " + typed[:120])
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
