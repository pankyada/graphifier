#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/backend${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m graphifier.worker "$@"
