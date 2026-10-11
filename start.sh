#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python="${PHOTOCLUSTER_PYTHON:-python3}"
if [[ -z "${PHOTOCLUSTER_PYTHON:-}" && -x .venv-linux/bin/python ]]; then
  python=.venv-linux/bin/python
fi
exec "$python" scripts/start.py "$@"
