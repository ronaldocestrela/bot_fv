#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -x "${ROOT}/venv/bin/python" ]]; then
  PYTHON="${ROOT}/venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PYTHON" -m bot.main "$@"
