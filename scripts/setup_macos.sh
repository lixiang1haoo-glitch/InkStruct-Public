#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
    PYTHON_BIN="${INKSTRUCT_PYTHON:-python3.13}"
    "$PYTHON_BIN" -c 'import sys; assert (3, 12) <= sys.version_info[:2] < (3, 14), "需要 Python 3.12 或 3.13"'
    "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install -e '.[desktop,dev]'
printf '%s\n' '环境就绪。首次克隆还需恢复本地数据或运行 .venv/bin/inkstruct structures build。'
