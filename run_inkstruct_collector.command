#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/inkstruct-collector ]]; then
    printf '%s\n' '请先在项目目录执行 bash scripts/setup_macos.sh'
    read -r -p '按回车关闭窗口…' _
    exit 1
fi
exec .venv/bin/inkstruct-collector "$@"
