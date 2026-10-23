# 变更记录

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
