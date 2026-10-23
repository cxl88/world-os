# WORLD OS V1

个人机会验证账本：信息录入 → 候选 Bug（人工或 AI）→ 证据核查 → 评分 → 验证行动 → 现实反馈 → 每日简报。

- 只用 Python 标准库 + SQLite，不需要安装任何依赖，不需要服务器。
- 不配置任何模型也能完整使用；配置后可接任何 OpenAI 兼容端点（如 DeepSeek）。
- 数据只存在本机。真实商业数据和个人资料不要提交到仓库（`.gitignore` 已排除数据库和数据目录）。

相关文档：[评分与证据规则](docs/SCORING.md) · [架构决策](docs/DECISIONS.md) · [已知问题](KNOWN_ISSUES.md) · [测试报告](TEST_REPORT.md) · [变更记录](CHANGELOG.md) · [Windows 本机验收](docs/ACCEPTANCE_WINDOWS.md) · [Experiment 001](docs/experiments/EXP-001-minio-migration.md)

---

## 1. 环境要求

| 项目 | 要求 | 验证情况 |
|---|---|---|
| Python | 3.10 及以上 | 3.10 / 3.11 / 3.12 / 3.13 在 Linux 上实测通过；Windows 由 GitHub Actions（windows-latest）验证，见 TEST_REPORT |
| 系统 | Windows 10/11、macOS、Linux | |
| PowerShell | Windows PowerShell 5.1 或 PowerShell 7 | 两者都在 GitHub Actions 的 windows-latest 上跑通演示脚本 |
| 依赖 | 无 | |

Windows 安装 Python 时勾选 **Add python.exe to PATH**。如果输入 `python` 打开了微软商店，说明命中的是商店占位程序：到“设置 → 应用 → 高级应用设置 → 应用执行别名”里关闭 `python.exe` 和 `python3.exe` 的别名，或改用 `py` 启动器（把下文的 `python` 换成 `py -3`）。

## 2. Windows PowerShell 快速开始

以下命令都在**项目根目录**（含 `worldos` 文件夹的那一层）执行。每条命令写在一行里，不需要续行符。

```powershell
# 0) 检查 Python 版本（需要 3.10+）
python --version

# 1) 让中文输入输出统一走 UTF-8（每个新开的 PowerShell 窗口执行一次；只看屏幕输出时可省略）
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 2) 首次初始化：显示数据库和数据目录的位置
python -m worldos init
```

**数据保存在哪里**：默认是 `%USERPROFILE%\worldos-data\worldos.db`（例如 `C:\Users\你的用户名\worldos-data\worldos.db`）。提示词文件、简报、备份、导出也都在这个目录下。想换位置：

```powershell
# 只对当前窗口生效
$env:WORLDOS_HOME = "D:\WorldOS数据"
# 永久生效（写入当前用户的环境变量，新开窗口后生效）
[Environment]::SetEnvironmentVariable("WORLDOS_HOME", "D:\WorldOS数据", "User")
# 临时指定某个数据库文件（数据目录 = 该文件所在目录）
python -m worldos --db "D:\测试 目录\test.db" init
```

路径里有空格或中文时用双引号括起来即可。

### 用 `--porcelain` 取 id，不要假设 id 等于 1

新建类命令加上 `--porcelain`（写在子命令前面）只输出新记录的 id，可以直接存进变量：

```powershell
$item = python -m worldos --porcelain item-add --title "本地羽毛球馆仍靠微信群接龙订场" --source "自己观察" --cred A --published 2026-10-20
$card = python -m worldos --porcelain card-add --name "球馆订场与对账流程" --bug-type 流程 --payers "中小球馆老板（假设）" --kill-condition "5 家中少于 2 家愿为试用付费"
python -m worldos --porcelain evidence-add $card --type primary --claim "现场看到用接龙表订场" --who 球馆A --item $item --verified
python -m worldos --porcelain log interview --card $card --who 球馆A --claim "老板说每晚对账约 40 分钟"
python -m worldos --porcelain log interview --card $card --who 球馆B --claim "也在手工对账"
python -m worldos score $card --pain 4 --access 4 --feasibility 5 --reuse 3 --risk 4 --basis "两家球馆亲口确认对账耗时，尚未问价"
python -m worldos status $card researching
$due = (Get-Date).AddDays(7).ToString("yyyy-MM-dd")
$action = python -m worldos --porcelain action-add $card --title "走访 3 家球馆" --hypothesis "馆主愿付每月 99 元" --acceptance "至少 1 家同意付费试用" --due $due --minutes 240
python -m worldos log time --category outreach --minutes 90
python -m worldos brief --save
python -m worldos card $card
```

一条命令太长想换行时，PowerShell 用行尾的反引号 `` ` ``（前面留一个空格），Bash 用行尾的 `\`。

### 一键演示（全新演示库，不碰你的数据）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
# 或 PowerShell 7：
pwsh -File scripts/demo.ps1
```

脚本会在系统临时目录下新建 `worldos-demo` 目录，跑完 录入 → 建卡 → 证据 → 评分 → 行动 → 反馈 → 简报 → 模拟 AI 提取 → 导出 → 备份 全流程。所有数据都标为【演示数据】。

## 3. Bash（macOS / Linux / Git Bash）

```bash
export PYTHONIOENCODING=utf-8
python3 -m worldos init
item=$(python3 -m worldos --porcelain item-add --title "本地羽毛球馆仍靠微信群接龙订场" --source "自己观察" --cred A)
card=$(python3 -m worldos --porcelain card-add --name "球馆订场与对账流程" --bug-type 流程)
python3 -m worldos --porcelain log interview --card "$card" --who 球馆A --claim "老板说每晚对账约 40 分钟"
python3 -m worldos score "$card" --pain 3 --access 4 --feasibility 5 --reuse 3 --risk 4 --basis "一家球馆亲口确认"
python3 -m worldos brief
```

数据目录默认 `~/worldos-data`，用 `export WORLDOS_HOME=/path` 修改。一键演示：`bash scripts/demo.sh`。

## 4. 接入模型（可选）

不配置时，`extract` 会把提示词写到 `数据目录\prompts\` 下，你粘贴到已有的聊天工具里，把返回的 JSON 存成文件后导入：

```powershell
python -m worldos extract
python -m worldos cards-import "D:\下载\结果.json" --ai --items "3,4,5"
```

配置 OpenAI 兼容端点（以 DeepSeek 为例，单价请按官方价格页填写，单位：美元/百万 token）：

```powershell
$env:WORLDOS_LLM_PROVIDER = "openai"
$env:WORLDOS_LLM_BASE_URL = "https://api.deepseek.com"
$env:WORLDOS_LLM_MODEL = "deepseek-flash"
$k = Read-Host "API Key" -AsSecureString            # 输入不回显，也不进命令历史
$env:WORLDOS_LLM_API_KEY = [System.Net.NetworkCredential]::new("", $k).Password; Remove-Variable k
$env:WORLDOS_PRICE_IN = "0.30"
$env:WORLDOS_PRICE_OUT = "1.20"
$env:WORLDOS_MONTHLY_BUDGET_USD = "25"
$env:WORLDOS_MAX_CALLS_PER_DAY = "30"
python -m worldos extract --limit 5
python -m worldos cost
```

Bash 对应写法：`read -rs -p "API Key: " WORLDOS_LLM_API_KEY && export WORLDOS_LLM_API_KEY`（输入不回显），其余用 `export 名称=值`。

**API Key：**
- 只放环境变量，不要写进任何文件、脚本或仓库，也不要直接写在命令行里（会进命令历史）。
- 环境变量的局限：只在当前窗口有效，关闭窗口就没了；这个窗口启动的所有程序、以及以你的账户运行的其他程序都能读到它；开着 `Start-Transcript` 时输入的内容不会被记录，但之后打印变量会被记录。
- 不建议用 `setx` 或 `SetEnvironmentVariable(..., "User")` 持久化：会以明文存在当前用户的注册表里。

**费用控制（本地闸门，不是供应商侧的硬上限）：**
- 单价、月预算、每日次数没填或无效（负数、NaN、Infinity、不是数字）时，拒绝真实调用。
- 每次请求前按“输入字节数 + 格式开销”和 `max_tokens` 估算这次最多花多少钱；本月已计费用加上这次的上限超过预算时，不发请求并记录。
- 请求发出前先按上限记账，返回后按供应商给的实际用量改写。供应商没有返回用量、调用失败（可能已经计费）、或程序中途被关掉时，这笔按上限计入预算并标为“待对账”。
- 每月用 `cost` 看“待对账”的笔数和金额，与供应商账单核对。待对账金额是上限，实际通常更低；它只计入当月预算。
- 这个闸门只管本程序发出的请求，并假设供应商遵守 `max_tokens`；实际用量超过上限时会照实记账并在记录里标出。如果供应商支持，请在其后台设置消费上限，或只充值小额余额。
- 模型调用失败会记录错误原文，并自动降级为手动模式（生成提示词文件）。
- `WORLDOS_LLM_PROVIDER=mock` 是测试用的确定性模拟适配器：输出标记为【模拟输出】，费用恒为 0，不能当作研究结论。

## 5. 命令一览

| 环节 | 命令 |
|---|---|
| 初始化 | `init` |
| 信息入口 | `item-add`（必须 `--source`）、`item-import 文件.json/.csv/.xml`（CSV 支持 UTF-8 和 GBK）、`rss URL`、`items` |
| Bug 提取 | `extract [--ids 1,2] [--manual]`、`cards-import 文件.json [--ai --items 1,2]`、`card-template` |
| 机会卡 | `card-add`、`cards`、`card ID`、`card-set ID 字段 值 [--reason]`、`status ID 新状态 [--reason]`、`review ID`、`filter ID 标记` |
| 证据 | `evidence-add ID --type 类型 --claim ...`、`evidence-verify 证据ID --type 类型` |
| 评分 | `score ID --pain --access --feasibility --reuse --risk --basis 依据 [--reason 修订原因]` |
| 行动 | `action-add`、`action-done ID --result --decision continue/adjust/pause/kill`、`actions` |
| 反馈 | `log interview/quote/intent/contract/payment/cost/time/insight/experience` |
| 输出与安全 | `brief [--save]`、`export [--out 目录]`、`backup`、`restore 备份文件 [--force]`、`cost` |

`python -m worldos 命令 -h` 查看每个命令的参数。

### 证据类型（详见 docs/SCORING.md）

`ai_inference` AI 推断 · `public` 公开资料（需 url）· `primary` 经人工核实的一手资料 · `customer_statement` 客户自述 · `quote` 报价 · `intent` 合作意向 · `contract` 合同 · `payment` 实际回款（客户类需 `--who`）。

只有加了 `--verified` 或经 `evidence-verify` 的证据参与评分。AI 产生的证据只能核实为 `public` 或 `primary`，不能变成客户证据。

### 状态流转

`candidate → researching → validating → won`，任一非终态可转 `paused` / `killed`；`killed` 和 `won` 是终态。AI 生成的卡审核前不能进入研究；`filter` 标记为 illegal / unauthorized / harmful 的卡直接淘汰，之后不能评分、建行动或改状态；`won` 需要有 `log payment` 记录。

## 6. 个人档案

把 `profile.example.md` 复制为 `数据目录\profile.md` 并填写（或用 `WORLDOS_PROFILE` 指定路径）。`extract` 会把它放进提示词，所以只写与机会匹配有关的内容，不写财务明细和他人隐私。

## 7. 运行测试

```powershell
python -m unittest -v
```

测试不联网、不产生费用、不读写你的真实数据目录（每个测试使用独立的临时目录）。

## 8. 备份与恢复

```powershell
python -m worldos backup                                  # 生成 数据目录\backups\worldos-时间.db
python -m worldos restore "C:\Users\你\worldos-data\backups\worldos-20261023-101500-000000.db" --force
```

恢复前会先校验备份文件，并把当前数据库另存为 `worldos.db.before-restore-时间`。
