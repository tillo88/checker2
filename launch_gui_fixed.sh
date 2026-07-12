#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${SPYENGINE_PORT:-8501}"
URL="http://localhost:${PORT}"

echo ""
echo "=========================================="
echo "  SpyEngine Client GUI Launcher"
echo "=========================================="
echo ""
echo "Project: $SCRIPT_DIR"
echo "URL:     $URL"
echo ""

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

if [ ! -f "spy_gui_v3.py" ] && [ ! -f "scripts/run_gui.py" ]; then
  echo "ERRORE: non trovo spy_gui_v3.py o scripts/run_gui.py in:"
  echo "  $SCRIPT_DIR"
  exit 1
fi

(
  sleep 4
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v sensible-browser >/dev/null 2>&1; then
    sensible-browser "$URL" >/dev/null 2>&1 || true
  fi
) &

if [ -f "scripts/run_gui.py" ]; then
  python scripts/run_gui.py
else
  python -m streamlit run spy_gui_v3.py --server.port "$PORT" --server.address 0.0.0.0
fi
