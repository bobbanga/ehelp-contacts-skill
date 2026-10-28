#!/usr/bin/env bash
# macOS / Linux 运行入口：使用 scripts/.venv 中的 Python 运行本地联系人工作台 CLI。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "尚未安装运行环境，请先运行 ./install.sh。"
  exit 1
fi

exec "$ROOT/.venv/bin/python" -B -m cli "$@"
