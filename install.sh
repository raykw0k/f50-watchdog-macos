#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
F50_PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$F50_PYTHON_BIN" ]]; then
  echo '请先安装 Python 3.9 或更新版本（已有 Homebrew 可运行 brew install python）。' >&2
  exit 1
fi
"$F50_PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,9), "需要 Python 3.9+"'
exec sudo "$F50_PYTHON_BIN" installer.py --python "$F50_PYTHON_BIN" "$@"
