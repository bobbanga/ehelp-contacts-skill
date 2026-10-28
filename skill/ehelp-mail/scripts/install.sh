#!/usr/bin/env bash
# macOS / Linux 安装脚本：在 scripts/.venv 中创建虚拟环境并安装依赖（仅 pydantic）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/"
  exit 1
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  "$PYTHON" -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check "pydantic==2.13.5"
"$ROOT/.venv/bin/python" -B -m cli --help >/dev/null
echo "安装完成。请让 Agent 运行 ./run.sh --json doctor。"
