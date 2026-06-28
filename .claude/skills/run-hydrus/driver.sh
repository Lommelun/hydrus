#!/usr/bin/env bash
# run-hydrus driver. One handle for building, testing, screenshotting, and
# launching the hydrus client from source. Tested on macOS (Darwin, arm64).
#
#   driver.sh setup            build venv/ (deps only) via uv  [~2-4 min, downloads]
#   driver.sh test [suite]     run a test suite headless (offscreen Qt). default: data
#   driver.sh shot [out.png]   boot the client and grab its main window, headless
#   driver.sh drive [shotdir]  drive the app in-process (type+click+assert), headless
#   driver.sh run [-- args]    launch the real GUI client (interactive; needs a display)
#   driver.sh stop             kill a GUI client started by `run`
#
# All commands are self-locating: run from anywhere.
set -euo pipefail

# --- locate repo root (dir containing hydrus_client.py) ---------------------
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$here"
while [ "$root" != "/" ] && [ ! -f "$root/hydrus_client.py" ]; do root="$(dirname "$root")"; done
[ -f "$root/hydrus_client.py" ] || { echo "could not find hydrus_client.py above $here" >&2; exit 1; }
cd "$root"

PY="$root/venv/bin/python"
[ -d "$root/venv/Scripts" ] && PY="$root/venv/Scripts/python"   # windows git-bash
TMP="${HYDRUS_TMP:-${TMPDIR:-/tmp}/run-hydrus}"
PIDFILE="$TMP/client.pid"
mkdir -p "$TMP"

need_venv() { [ -x "$PY" ] || { echo "no venv yet -- run: $0 setup" >&2; exit 1; }; }

cmd="${1:-help}"; shift || true
case "$cmd" in

  setup)
    command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/" >&2; exit 1; }
    uv venv venv --python 3.13
    # install pyproject deps, then drop the hydrus package itself so we run from
    # the source tree (the packaged copy ships a malformed static/ and shadows it)
    uv pip install --python "$PY" .
    uv pip uninstall --python "$PY" hydrus
    uv pip install --python "$PY" httmock   # test-only dep, not in pyproject
    echo "venv ready: $PY"
    ;;

  test)
    need_venv
    suite="${1:-data}"
    echo ">> QT_QPA_PLATFORM=offscreen $PY hydrus_test.py $suite"
    QT_QPA_PLATFORM=offscreen "$PY" hydrus_test.py "$suite"
    ;;

  shot)
    need_venv
    out="${1:-$TMP/hydrus_main.png}"
    db="$TMP/hydb"; mkdir -p "$db"
    echo ">> booting client headless, grabbing main window -> $out"
    HYDRUS_DB="$db" HYDRUS_SHOT="$out" HYDRUS_SHOT_DELAY="${HYDRUS_SHOT_DELAY:-22}" \
      QT_QPA_PLATFORM=offscreen "$PY" "$here/screenshot.py"
    echo "wrote $out"
    ;;

  drive)
    need_venv
    shots="${1:-$TMP}"; mkdir -p "$shots"
    db="$TMP/hydb"; mkdir -p "$db"
    echo ">> driving the client in-process (keyboard + mouse + asserts), headless"
    HYDRUS_DB="$db" DRIVE_SHOTS="$shots" DRIVE_OUT="$shots/drive.out" \
      QT_QPA_PLATFORM=offscreen "$PY" "$here/drive_example.py"
    echo "--- report ($shots/drive.out) ---"; cat "$shots/drive.out"
    ;;

  run)
    need_venv
    [ "${1:-}" = "--" ] && shift || true
    db="$TMP/hydb"; mkdir -p "$db"
    echo ">> launching GUI client (db=$db). Needs a real display; Ctrl-C or 'driver.sh stop' to quit."
    "$PY" hydrus_client.py -d "$db" "$@" &
    echo $! > "$PIDFILE"
    echo "pid $(cat "$PIDFILE")"
    ;;

  stop)
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null && echo "stopped $(cat "$PIDFILE")" || echo "nothing to stop"
    rm -f "$PIDFILE"
    ;;

  *)
    grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -n '1,11p'
    ;;
esac
