#!/bin/sh
set -eu

umask 077
UID_NOW="$(id -u)"
USER_NOW="$(id -un)"
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$UID_NOW}"
export XDG_RUNTIME_DIR
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=SWIR
export XDG_SESSION_DESKTOP=swir
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-swir}"
export GDK_BACKEND=wayland
BACKEND="${SWIR_WESTON_BACKEND:-drm}"
SHELL_MODE="${SWIR_WESTON_SHELL:-kiosk-shell.so}"
WESTON_LOG="$XDG_RUNTIME_DIR/swir-weston.log"
SHELL_EVIDENCE="$XDG_RUNTIME_DIR/swir-shell-evidence.json"

[ -d "$XDG_RUNTIME_DIR" ] || { echo "missing XDG_RUNTIME_DIR: $XDG_RUNTIME_DIR" >&2; exit 70; }
[ "$(stat -c '%u' "$XDG_RUNTIME_DIR")" = "$UID_NOW" ] || { echo "runtime directory owner mismatch" >&2; exit 71; }
[ -x /usr/bin/weston ] || { echo "weston is not installed" >&2; exit 72; }
[ -x /usr/local/bin/swir-shell ] || { echo "SWIR native shell is not installed" >&2; exit 72; }

rm -f "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" "$SHELL_EVIDENCE"
/usr/bin/weston \
  --no-config \
  --backend="$BACKEND" \
  --shell="$SHELL_MODE" \
  --renderer=pixman \
  --socket="$WAYLAND_DISPLAY" \
  --idle-time=0 \
  --log="$WESTON_LOG" &
WESTON_PID=$!
SHELL_PID=""
cleanup() {
  if [ -n "$SHELL_PID" ]; then kill "$SHELL_PID" 2>/dev/null || true; wait "$SHELL_PID" 2>/dev/null || true; fi
  kill "$WESTON_PID" 2>/dev/null || true
  wait "$WESTON_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ready=0
i=0
while [ "$i" -lt 80 ]; do
  if [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then ready=1; break; fi
  if ! kill -0 "$WESTON_PID" 2>/dev/null; then break; fi
  i=$((i + 1))
  sleep 0.25
done
[ "$ready" = "1" ] || { echo "weston Wayland socket did not become ready" >&2; exit 73; }

if [ "${SWIR_SESSION_E2E:-0}" = "1" ]; then
  SWIR_SHELL_EVIDENCE_PATH="$SHELL_EVIDENCE" /usr/local/bin/swir-shell &
else
  /usr/local/bin/swir-shell &
fi
SHELL_PID=$!

shell_ready=0
i=0
while [ "$i" -lt 80 ]; do
  if [ "${SWIR_SESSION_E2E:-0}" != "1" ]; then shell_ready=1; break; fi
  if [ -s "$SHELL_EVIDENCE" ]; then shell_ready=1; break; fi
  if ! kill -0 "$SHELL_PID" 2>/dev/null; then break; fi
  i=$((i + 1))
  sleep 0.25
done
[ "$shell_ready" = "1" ] || { echo "SWIR native shell did not map a Wayland window" >&2; exit 74; }

if [ "${SWIR_SESSION_E2E:-0}" = "1" ]; then
  WAYLAND_INFO="$XDG_RUNTIME_DIR/swir-wayland-info.txt"
  EVIDENCE="$XDG_RUNTIME_DIR/swir-graphical-session-evidence.json"
  rm -f "$EVIDENCE" "$WAYLAND_INFO"

  [ -x /usr/bin/wayland-info ] || { echo "wayland-info is not installed" >&2; exit 75; }
  WAYLAND_DISPLAY="$WAYLAND_DISPLAY" /usr/bin/wayland-info > "$WAYLAND_INFO"
  grep -q 'interface:.*wl_compositor' "$WAYLAND_INFO" || grep -q 'wl_compositor' "$WAYLAND_INFO" || { echo "Wayland compositor global was not observed" >&2; exit 76; }

  /usr/bin/python3 - "$SHELL_EVIDENCE" <<'PY'
import json, sys
shell = json.load(open(sys.argv[1], encoding='utf-8'))
assert shell.get('schema') == 'swir.native-shell-runtime-evidence/0.1'
assert shell.get('passed') is True
assert shell.get('applicationId') == 'dev.swir.Shell'
assert shell.get('nativeToolkit') == 'gtk4'
assert shell.get('displayProtocol') == 'wayland'
assert shell.get('windowMapped') is True
assert shell.get('fullscreenRequested') is True
assert shell.get('privilegedOperationsInShell') is False
assert {'Files', 'Terminal', 'Settings', 'Install SWIR OS'} <= set(shell.get('launcherEntries', []))
PY

  SESSION_ID="${XDG_SESSION_ID:-}"
  if [ -z "$SESSION_ID" ]; then
    SESSION_ID="$(/usr/bin/loginctl list-sessions --no-legend 2>/dev/null | awk -v uid="$UID_NOW" '$2 == uid { print $1; exit }')"
  fi
  [ -n "$SESSION_ID" ] || { echo "logind session id not found" >&2; exit 77; }
  SESSION_SHOW="$(/usr/bin/loginctl show-session "$SESSION_ID" -p Id -p User -p Name -p Remote -p Active -p State -p Class -p Type -p Service -p Seat -p Leader 2>/dev/null)"
  printf '%s\n' "$SESSION_SHOW" | grep -q "^User=$UID_NOW$" || { echo "logind user mismatch" >&2; exit 78; }
  printf '%s\n' "$SESSION_SHOW" | grep -q '^Remote=no$' || { echo "session unexpectedly remote" >&2; exit 79; }
  printf '%s\n' "$SESSION_SHOW" | grep -q '^Service=greetd$' || { echo "session was not created by greetd" >&2; exit 80; }

  export SWIR_EVIDENCE_PATH="$EVIDENCE"
  export SWIR_EVIDENCE_USER="$USER_NOW"
  export SWIR_EVIDENCE_UID="$UID_NOW"
  export SWIR_EVIDENCE_SESSION="$SESSION_ID"
  export SWIR_EVIDENCE_BACKEND="$BACKEND"
  export SWIR_EVIDENCE_SOCKET="$WAYLAND_DISPLAY"
  export SWIR_EVIDENCE_WESTON_PID="$WESTON_PID"
  export SWIR_EVIDENCE_SHELL_PID="$SHELL_PID"
  export SWIR_EVIDENCE_SHELL_PATH="$SHELL_EVIDENCE"
  export SWIR_EVIDENCE_SESSION_SHOW="$SESSION_SHOW"
  /usr/bin/python3 - <<'PY'
import json, os, pathlib
props = {}
for line in os.environ['SWIR_EVIDENCE_SESSION_SHOW'].splitlines():
    if '=' in line:
        k, v = line.split('=', 1)
        props[k] = v
shell = json.loads(pathlib.Path(os.environ['SWIR_EVIDENCE_SHELL_PATH']).read_text(encoding='utf-8'))
out = {
    'schema': 'swir.graphical-session-runtime-evidence/0.1',
    'passed': True,
    'user': os.environ['SWIR_EVIDENCE_USER'],
    'uid': int(os.environ['SWIR_EVIDENCE_UID']),
    'sessionId': os.environ['SWIR_EVIDENCE_SESSION'],
    'logind': {
        'service': props.get('Service'),
        'remote': props.get('Remote'),
        'active': props.get('Active'),
        'state': props.get('State'),
        'class': props.get('Class'),
        'type': props.get('Type'),
        'seat': props.get('Seat'),
        'leader': props.get('Leader'),
    },
    'wayland': {
        'compositor': 'weston',
        'backend': os.environ['SWIR_EVIDENCE_BACKEND'],
        'socket': os.environ['SWIR_EVIDENCE_SOCKET'],
        'socketObserved': True,
        'clientHandshakePassed': True,
        'westonPid': int(os.environ['SWIR_EVIDENCE_WESTON_PID']),
    },
    'shell': {
        'applicationId': shell['applicationId'],
        'nativeToolkit': shell['nativeToolkit'],
        'displayProtocol': shell['displayProtocol'],
        'windowMapped': shell['windowMapped'],
        'fullscreenRequested': shell['fullscreenRequested'],
        'launcherEntries': shell['launcherEntries'],
        'privilegedOperationsInShell': shell['privilegedOperationsInShell'],
        'pid': int(os.environ['SWIR_EVIDENCE_SHELL_PID']),
    },
    'desktopShellClaim': True,
}
path = pathlib.Path(os.environ['SWIR_EVIDENCE_PATH'])
path.write_text(json.dumps(out, sort_keys=True) + '\n', encoding='utf-8')
PY
  chmod 0600 "$EVIDENCE"

  while kill -0 "$WESTON_PID" 2>/dev/null && kill -0 "$SHELL_PID" 2>/dev/null; do sleep 1; done
  wait "$SHELL_PID"
  exit $?
fi

# A shell crash returns the authenticated session to the greeter instead of
# silently leaving the user on an empty compositor.
while kill -0 "$WESTON_PID" 2>/dev/null && kill -0 "$SHELL_PID" 2>/dev/null; do sleep 1; done
if ! kill -0 "$SHELL_PID" 2>/dev/null; then
  wait "$SHELL_PID"
  exit $?
fi
wait "$WESTON_PID"
