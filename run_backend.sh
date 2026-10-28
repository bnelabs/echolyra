#!/usr/bin/env bash
# Start the Echolyra backend reachable from the iPhone on the same Wi-Fi.
#   ./run_backend.sh                 # uses python3
#   PYTHON=../prototype/.venv/bin/python ./run_backend.sh
set -euo pipefail

# Resolve the interpreter BEFORE cd, so relative PYTHON paths still work.
PYBIN="${PYTHON:-python3}"
if [[ "$PYBIN" == */* ]]; then
  PYBIN="$(cd "$(dirname "$PYBIN")" && pwd)/$(basename "$PYBIN")"
else
  PYBIN="$(command -v "$PYBIN")"
fi

cd "$(dirname "$0")/backend"

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and add META_API_KEY." >&2
  exit 1
fi
set -a && . ./.env && set +a

IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
[ -z "${IP:-}" ] && IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
[ -z "${IP:-}" ] && IP="127.0.0.1"

echo "=============================================="
echo " Echolyra backend"
echo "   Mac:     http://127.0.0.1:8080"
echo "   iPhone:  http://${IP}:8080"
echo "   Health:  http://${IP}:8080/api/health   <- open this in iPhone Safari FIRST"
echo "=============================================="
exec "$PYBIN" -m uvicorn app:app --host 0.0.0.0 --port 8080 "$@"
