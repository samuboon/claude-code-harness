#!/bin/sh
# Hand one hook over to a working Python 3, and get out of the way.
#
# Why this file exists at all: hook commands run through a shell (sh on macOS/Linux,
# Git Bash on Windows), and the interpreter is called "python" on some machines and
# "python3" on others. Without this, the plugin would work on one platform only.
#
# Two things are deliberate:
#   - exec: the Python process replaces this shell, so its exit code survives.
#     Exit code 2 is how a PreToolUse hook blocks a tool call. A wrapper that
#     returned its own status would silently turn every block into a pass.
#   - the WindowsApps skip: on Windows, "python3" often resolves to the Microsoft
#     Store stub, which is not Python and exits 9009. Running it would look like a
#     broken hook, and a broken hook does not block anything.
set -u

root=${CLAUDE_PLUGIN_ROOT:-$(dirname -- "$0")/..}
root=$(printf '%s' "$root" | tr '\\' '/')
script="$root/.claude/hooks/$1"
shift

if [ ! -f "$script" ]; then
  echo "harness-guard: hook script not found: $script" >&2
  exit 1
fi

for py in python3 python py; do
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in
    *WindowsApps*) continue ;;
  esac
  exec "$py" "$script" "$@"
done

echo "harness-guard: no Python found on PATH (tried python3, python, py). The hook did NOT run." >&2
exit 1
