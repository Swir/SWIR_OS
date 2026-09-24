#!/usr/bin/env bash
set -euo pipefail

STAGE_ROOT="${1:-/swir-stage}"
BINARY="$STAGE_ROOT/opt/swir/apps/konofix/konofix-chat"
[[ -x "$BINARY" ]] || { echo "staged Konofix binary is missing or not executable" >&2; exit 64; }
grep -Eq '^VERSION_ID="?13"?$' /etc/os-release || {
  echo "runtime smoke requires Debian 13 userspace" >&2
  cat /etc/os-release >&2
  exit 65
}

RUNTIME_ROOT=/tmp/swir-konofix-runtime
HOME_DIR="$RUNTIME_ROOT/home"
XDG_DIR="$RUNTIME_ROOT/xdg"
EVIDENCE="$RUNTIME_ROOT/window-tree.txt"
STDOUT="$RUNTIME_ROOT/stdout.log"
STDERR="$RUNTIME_ROOT/stderr.log"
install -d -m 0700 -o 65534 -g 65534 "$RUNTIME_ROOT" "$HOME_DIR" "$XDG_DIR"

setpriv --reuid=65534 --regid=65534 --clear-groups \
  env HOME="$HOME_DIR" XDG_RUNTIME_DIR="$XDG_DIR" \
  dbus-run-session -- xvfb-run -a -s "-screen 0 1366x768x24" \
  bash -eu -o pipefail -c '
    binary="$1"
    evidence="$2"
    stdout="$3"
    stderr="$4"
    "$binary" >"$stdout" 2>"$stderr" &
    pid=$!
    cleanup() {
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    }
    trap cleanup EXIT
    found=0
    for _ in $(seq 1 100); do
      if ! kill -0 "$pid" 2>/dev/null; then
        cat "$stderr" >&2 || true
        exit 21
      fi
      if xwininfo -root -tree >"$evidence" 2>&1 && grep -F "Konofix Chat" "$evidence" >/dev/null; then
        found=1
        break
      fi
      sleep 0.25
    done
    test "$found" -eq 1
    sleep 3
    kill -0 "$pid"
    grep -F "Konofix Chat" "$evidence"
  ' bash "$BINARY" "$EVIDENCE" "$STDOUT" "$STDERR"

echo "Konofix staged System binary mapped a real window in Debian 13 userspace."
