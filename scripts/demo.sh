#!/usr/bin/env bash
# WORLD OS 演示脚本（macOS / Linux / Git Bash）
# 在一个全新的演示数据目录里跑完整闭环。全部数据都是【演示数据】，不是真实商业信息。
# 用法（在项目根目录）：bash scripts/demo.sh [演示目录]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONIOENCODING=utf-8
PY="${PYTHON:-$(command -v python3 || command -v python)}"
DATA_DIR="${1:-${TMPDIR:-/tmp}/worldos-demo}"
if [ "$(basename "$DATA_DIR")" != "worldos-demo" ]; then
  echo "为安全起见，演示目录名必须是 worldos-demo：$DATA_DIR" >&2; exit 1
fi
rm -rf "$DATA_DIR"
export WORLDOS_HOME="$DATA_DIR"
unset WORLDOS_DB WORLDOS_LLM_PROVIDER WORLDOS_LLM_API_KEY || true

w() { "$PY" -m worldos "$@"; }
wid() { "$PY" -m worldos --porcelain "$@" | tail -n 1; }

"$PY" --version
w init

echo; echo "== 1. 录入信息、手动建卡、加证据 =="
item=$(wid item-add --title "【演示数据】某小型工厂仍每月人工抄表" --source "演示数据" --cred B --published 2026-10-01)
card=$(wid card-add --name "【演示数据】工厂抄表自动化" --bug-type 流程 --payers "中小工厂设备科（假设）" --kill-condition "5 家里少于 2 家愿意付费试点")
wid evidence-add "$card" --type public --claim "演示：行业文章提到人工抄表普遍" --url https://example.com/demo --item "$item" --verified >/dev/null
wid log interview --card "$card" --who 演示客户A --claim "演示：每月抄表约 2 人天" >/dev/null
wid log interview --card "$card" --who 演示客户B --claim "演示：也在手工抄表" >/dev/null

echo; echo "== 2. 评分（证据规则会自动压分）=="
wid score "$card" --pain 4 --access 3 --feasibility 4 --reuse 3 --risk 4 --basis "演示：两家客户自述，尚无报价" >/dev/null
w status "$card" researching

echo; echo "== 3. 验证行动与反馈 =="
due=$("$PY" -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=7))")
action=$(wid action-add "$card" --title "【演示数据】拜访 3 家工厂" --hypothesis "愿付 3000 元试点" --acceptance "至少 1 家给出书面报价意向" --due "$due" --minutes 240)
wid log time --category outreach --minutes 60 >/dev/null
wid log quote --card "$card" --who 演示客户A --amount 3000 --note "演示报价" >/dev/null

echo; echo "== 4. 每日简报 =="
w brief --save

echo; echo "== 5. 模拟 AI 提取（仅测试流程，输出不是研究结论）=="
wid item-add --title "【演示数据】小企业抱怨发票录入耗时" --source "演示数据" >/dev/null
WORLDOS_LLM_PROVIDER=mock w extract
w cards

echo; echo "== 6. 导出与备份 =="
w export
echo "备份文件：$(wid backup)"
w cost

echo; echo "演示完成。卡片 #$card，行动 #$action，数据目录：$DATA_DIR"
