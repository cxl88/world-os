# 变更记录

## v0.2.1 — 2026-10-23（架构审查 002 整改，分支 review-001）

### 修复
- 预算闸门：发请求前按单次费用上限预留，“已计 + 上限 > 预算”时拦截，不再出现最后一次请求整笔超支（`llm.py`）。
- 单价、月预算、每日次数必须是有限的非负数；NaN、Infinity、负数、非数字拒绝调用。
- 用量缺失或格式不对、调用失败、程序中断时，费用按上限计入预算并标“待对账”，不再记成 0；`cost` 和简报分开显示已确认与待对账金额。
- 报价、合同、回款金额必须是大于 0 的有限数字；`won` 要求回款合计 > 0；成交状态只认正金额（`records.py`、`cards.py`、`evidence.py`）。
- 测试辅助方法 `fail` 覆盖了 `TestCase.fail`，导致断言失败信息被吞掉；改名为 `fails`。

### 新增
- 简报标出“评分可能已过期”：评分后已核实证据或卡片内容有变化时提示重评（`scoring.stale_reasons`）。
- `scripts/mutation_check.py`：31 处关键规则的变异抽查。
- CI 在 Windows PowerShell 5.1 上验证 README 的 API Key 隐藏输入写法。

### 变更
- 数据库结构版本 3：`llm_calls` 新增 `est_cost_usd`、`usage_known`。版本 2 的数据库和备份打开时自动升级。
- README 与 `config.example.ps1`：API Key 用 `Read-Host -AsSecureString` 输入，说明环境变量的局限和预算闸门的边界。
- `docs/SCORING.md`：写明独立来源不识别转载和同源。

### 文档（架构指令 003）
- `docs/ACCEPTANCE_WINDOWS.md`：#7 本机运行、#9 真实模型小额调用、#11 人工核实来源的 PowerShell 验收步骤。
- `docs/experiments/EXP-001-minio-migration.md`：MinIO 迁移缺口 7 天验证执行文件。
- ADR-009 开发冻结规则；PR 模板增加冻结检查。

## v0.2.0 — 2026-10-23（架构审查 001 整改，分支 review-001）

### 新增
- 证据模型：8 类证据、独立来源、支付意愿上限、成交状态（`evidence.py`）。
- 机会卡修改记录 `card_revisions`；状态流转白名单（`cards.py`）。
- 评分必须写依据，修订必须写原因，评分只追加（`scoring.py`）。
- 验证记录：报价、意向、合同、回款分别记录，可同时生成已核实客户证据（`records.py`）。
- 模型：确定性模拟适配器、每日次数上限、失败记录、不可用时降级、未配置单价拒绝调用（`llm.py`）。
- 提示词注入防护与模型输出白名单校验（`prompts.py`、`extract.py`）。
- `restore` 命令（覆盖前自动另存）、`--porcelain`、`status` 命令。
- Windows 优先 README、`scripts/demo.ps1` / `demo.sh`、配置示例。
- BUG HUNTER 真实公开信息试运行（`examples/bug_hunter_2026-10/`、`BUG_HUNTER_SAMPLE.md`）。
- GitHub Actions：Linux（3.10、3.13）与 Windows（3.12，PowerShell 5.1 和 7）。

### 变更
- 数据目录默认改为 `WORLDOS_HOME` 或 `~/worldos-data`（原为当前目录）。
- 信息必须有来源；CSV 支持 GBK。
- 日志类型 `revenue` 改为 `payment`，新增 `intent`、`contract`。
- 错误信息改为输出到 stderr，退出码 1。

### 不兼容
- 数据库结构版本 2，不能打开 v0.1 数据库（会提示）。

## v0.1.0 — 2026-10-23
- 初版原型：信息录入、机会卡、证据 E0–E3、评分、行动、日志、每日简报、导出、备份。
