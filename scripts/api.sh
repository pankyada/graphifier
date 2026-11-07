#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/backend${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m uvicorn graphifier.api:app --host 127.0.0.1 --port "${GRAPHIFIER_API_PORT:-8787}" "$@"
