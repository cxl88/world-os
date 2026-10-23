# WORLD OS V1 本地原型

一个只用 Python 标准库 + SQLite 的命令行工具，覆盖 MVP 的 P0 闭环：
信息录入 → 候选 Bug（AI 或手动）→ 证据核查 → 评分 → 验证行动 → 反馈记录 → 每日简报。

不需要安装任何依赖，不需要服务器。Windows / macOS / Linux 都能跑（Python 3.10+）。

## 快速开始（Windows PowerShell 同样适用）

```bash
cd worldos
python -m worldos init
python -m worldos item-add --title "本地羽毛球馆仍靠微信群接龙订场" --source "自己观察" --cred A
python -m worldos card-add --name "球馆订场与对账流程" --bug-type 流程 --payers "中小球馆老板" \
    --min-validation "走访5家球馆" --kill-condition "5家中少于2家愿为试用付费"
python -m worldos evidence-add 1 --claim "馆主说每晚对账约40分钟" --level 2 --verified
python -m worldos score 1 --pain 3 --access 4 --feasibility 5 --reuse 3 --risk 4
python -m worldos card-set 1 status validating
python -m worldos action-add 1 --title "走访3家球馆" --hypothesis "馆主愿付每月99元" \
    --acceptance "至少1家同意付费试用" --due 2026-10-30 --minutes 240
python -m worldos log interview --card 1 --who 球馆A --note "对账痛，但已在用某小程序订场"
python -m worldos log time --category outreach --minutes 90
python -m worldos brief --save
```

数据库默认是当前目录的 `worldos.db`，可用 `--db` 或环境变量 `WORLDOS_DB` 指定。

## 命令一览

| 环节 | 命令 |
|---|---|
| 信息入口 | `item-add`、`item-import 文件.json/.csv/.xml`、`rss URL`、`items` |
| Bug 提取 | `extract`（有 API Key 自动调用；没有则生成提示词文件，粘贴到你已有的聊天工具）、`cards-import 结果.json --ai --mark-items 1,2` |
| 机会卡 | `card-template`、`card-add`、`cards`、`card ID`、`card-set ID 字段 值`、`review ID`、`filter ID 标记` |
| 证据 | `evidence-add`、`evidence-verify ID --level N` |
| 评分 | `score ID --pain --access --feasibility --reuse --risk` |
| 行动 | `action-add`、`action-done ID --result --decision`、`actions` |
| 反馈 | `log interview/quote/cost/revenue/time/insight/experience` |
| 输出 | `brief [--save]`、`export`、`backup`、`cost` |

## 评分规则（scoring.py）

- 五维 0-5 分，权重 30/20/20/20/10，换算成 100 分。
- 证据等级取“已人工核实”证据的最高级：E0 仅 AI 推断（封顶 40）、E1 公开二手（封顶 60）、E2 一手/客户亲述（封顶 85）、E3 报价/付款/意向书（不封顶）。
- 没有 E2 以上证据时，“痛点与支付意愿”最多记 2 分。
- `filter` 标记 illegal/unauthorized/harmful 直接淘汰且不能评分；no_payer/over_budget 暂缓。
- AI 生成的卡和证据一律从 E0、待审核开始；不 `review` 不能进入研究/验证。

## 接入模型（可选）

任何 OpenAI 兼容端点都可以，例如 DeepSeek：

```bash
set WORLDOS_LLM_BASE_URL=https://api.deepseek.com
set WORLDOS_LLM_API_KEY=你的key
set WORLDOS_LLM_MODEL=deepseek-flash
set WORLDOS_PRICE_IN=0.30      # 美元/百万输入token，按官方价格自己填（高峰价更保守）
set WORLDOS_PRICE_OUT=1.20
set WORLDOS_MONTHLY_BUDGET_USD=25
```

每次调用的 token 和费用记在 `llm_calls` 表，`cost` 查看；本月超过预算自动停止调用。
API Key 只放环境变量，不要写进文件或仓库。

## 个人档案

复制 `profile.example.md` 为 `profile.md` 并填写。`extract` 会把它放进提示词，
所以只写与机会匹配有关的内容，不写财务明细和他人隐私。

## 测试

```bash
python -m unittest -v
```
