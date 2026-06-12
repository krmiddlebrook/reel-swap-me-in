#!/bin/bash
# Launch the local VACE swap engine (WanGP), vendored by ./setup.sh --vace.
#   ./vace.sh ui                  — web UI (VACE 1.3B preselected) at :7860
#   ./vace.sh smoke               — headless smoke generation, timed (-l = peak RSS)
#   ./vace.sh process <file>      — headless run of a saved queue (.zip) or settings (.json)
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
PY="$ROOT/vendor/wangp-venv/bin/python"
WGP="$ROOT/vendor/wangp"
if [ ! -x "$PY" ] || [ ! -f "$WGP/wgp.py" ]; then
  echo "VACE engine not installed — run ./setup.sh --vace" >&2
  exit 1
fi
export PATH="$ROOT/bin:$PATH"   # vendored ffmpeg for moviepy/ffmpeg-python

cmd="${1:-ui}"
shift || true
cd "$WGP"   # wgp.py writes ckpts/, configs, and queues relative to cwd
case "$cmd" in
  ui)
    exec "$PY" wgp.py --vace-1-3B --attention sdpa "$@" ;;
  smoke)
    exec /usr/bin/time -l "$PY" wgp.py --process "$ROOT/assets/vace-smoke.json" \
      --output-dir "$ROOT/output" --attention sdpa "$@" ;;
  process)
    if [ $# -lt 1 ]; then
      echo "usage: ./vace.sh process <queue.zip|settings.json> [wgp args…]" >&2
      exit 1
    fi
    queue="$1"; shift
    case "$queue" in /*) ;; *) queue="$ROOT/$queue" ;; esac
    exec "$PY" wgp.py --process "$queue" --output-dir "$ROOT/output" --attention sdpa "$@" ;;
  *)
    echo "usage: ./vace.sh [ui|smoke|process <file>]" >&2
    exit 1 ;;
esac
