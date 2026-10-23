#!/usr/bin/env bash
# 复现 BUG HUNTER 真实公开信息试运行：全新数据目录 → 导入 16 条信息 → 导入两批 AI 输出 → 简报
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
export PYTHONPATH="$ROOT" PYTHONIOENCODING=utf-8
PY="${PYTHON:-$(command -v python3 || command -v python)}"
DATA="${1:-${TMPDIR:-/tmp}/worldos-bughunter-sample}"
# 安全保护：只清理本脚本自己创建过的目录（含标记文件），绝不删除你的正式数据目录
if [ -e "$DATA" ] && [ ! -e "$DATA/.bughunter-sample" ]; then
  echo "目录已存在且不是本脚本创建的，为避免误删请换一个目录：$DATA" >&2; exit 1
fi
rm -rf "$DATA"; mkdir -p "$DATA"; touch "$DATA/.bughunter-sample"; export WORLDOS_HOME="$DATA"; unset WORLDOS_DB WORLDOS_LLM_PROVIDER || true
"$PY" -m worldos init
"$PY" -m worldos item-import "$HERE/items.json"
"$PY" -m worldos cards-import "$HERE/ai_output_batch1.json" --ai --items 1,2,3,5,6,7,8,11,12,13
"$PY" -m worldos cards-import "$HERE/ai_output_batch2.json" --ai --items 4,9,10,14,15,16
"$PY" -m worldos cards
"$PY" -m worldos brief
