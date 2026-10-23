# 工程报告：架构审查 001 / 指令 002 整改（2026-10-23）

## 0. 架构审查 002 整改（第二轮，v0.2.1）

审查意见见 PR #13 的 ARCHITECT REVIEW 002；逐项修复与回归测试见 TEST_REPORT.md 第 0 节。第 1–7 节为第一轮记录。

| 编号 | 审查项 | 状态 | 证据 |
|---|---|---|---|
| R002-P0-1 | 预算闸门按单次上限预留，不能整笔超支；配置值校验；缺用量标记待对账 | PASS | `worldos/llm.py`；test_e_cost 新增 6 项、改写 1 项；变异抽查 |
| R002-P0-2 | 0、NaN、Infinity 金额不能促成成交；`won` 需正的回款合计 | PASS | `records.py`、`cards.py`、`evidence.py`；test_d_evidence 新增 2 项 |
| R002-3 | 评分过期提醒 | PASS | `scoring.stale_reasons`、`brief.py`；test_brief_flags_stale_score |
| R002-4 | 独立来源计算方式与人工核实说明 | PASS（文档） | docs/SCORING.md 第 3 节、KNOWN_ISSUES L16、docs/ACCEPTANCE_WINDOWS.md（#11） |
| R002-5 | PowerShell API Key 不回显输入 | PASS（转换写法已在 PowerShell 7.4 与 CI 的 5.1 上验证）/ NOT TESTED（交互输入需要人在控制台） | README、config.example.ps1、CI 步骤 |
| R002-6 | 全部自动化测试 | PASS（本地 Python 3.10–3.13，各 50 项；[CI](https://github.com/cxl88/world-os/actions/runs/39903915562) 提交 `419a225` 在 Linux 3.10 / 3.13 与 Windows 3.12 + PowerShell 5.1 / 7 全部通过，各 50 项） | reports/2026-10-23-review-002/ |
| R002-7 | 不通过修改测试预期掩盖缺陷 | PASS | 唯一改变预期的原有测试正是审查指出的缺陷，见 TEST_REPORT 0.1 |
| R002-8 | 数据库升级不丢数据 | PASS | test_v2_database_is_upgraded |
| #7 / #9 / #11 | 本机实测、真实模型、人工核实来源 | NOT TESTED | 需要你本人操作，步骤见 docs/ACCEPTANCE_WINDOWS.md |
| D003-3 | #7、#9、#11 的 Windows PowerShell 验收步骤 | PASS（文档；步骤在 PowerShell 7.4 / Linux 上逐段试跑，Windows 路径写法未在本机验证） | docs/ACCEPTANCE_WINDOWS.md |
| D003-4 | Experiment 001 七天执行文件（事实与假设、需求来源、评估方案、隔离测试、访谈问题、成本模板、第 7 天决策规则） | PASS（文档；文中命令在 PowerShell 7.4 / Linux 上试跑）/ 实验本身 NOT TESTED | docs/experiments/EXP-001-minio-migration.md、#12 |
| D003-5 | 开发冻结规则 | PASS（文档，PR #13 合并后生效） | docs/DECISIONS.md ADR-009、.github/pull_request_template.md |


## 第一轮结论（审查 001 整改）

- 完整源码、测试、文档、演示数据都在仓库里，不是只有 README。
- 41 项自动化测试覆盖审查要求的测试 A–G，在 Python 3.10、3.11、3.12、3.13（本地 Linux）和 GitHub Actions 的 Linux、Windows 上实际运行全部通过；16 处故意破坏关键规则的变异抽查全部被测试发现。
- 证据模型按任务四重做：8 类证据，证据强度、支付意愿、成交状态三者分开，单条证据不能证明机会成立，评分有依据和修订记录。
- BUG HUNTER 用 16 条可追溯的真实公开信息试运行，产出 5 张候选卡；没有一张达到“已验证”，报告如实说明。
- 私有仓库 cxl88/world-os 已建立，首个审查 PR 是 [#13](https://github.com/cxl88/world-os/pull/13)，[CI](https://github.com/cxl88/world-os/actions/runs/39897300962) 在 Linux 与 Windows（PowerShell 5.1 和 7）全部通过。
- **未完成**：你自己的 Windows 电脑还没跑过（#7）；没有调用过真实模型（#9）；样本证据还没人工核实（#11）。详见第 5 节和 KNOWN_ISSUES.md。

## 1. 项目目录

```
world-os/
├── README.md                  Windows PowerShell 优先的使用教程
├── ENGINEERING_REPORT.md      本报告
├── TEST_REPORT.md             测试命令、结果、失败与修复记录
├── BUG_HUNTER_SAMPLE.md       真实公开信息试运行报告
├── KNOWN_ISSUES.md            未完成、无法验证、需要授权的事项
├── CHANGELOG.md               变更记录
├── config.example.ps1 / .sh   配置示例（不含任何密钥）
├── profile.example.md         个人资源档案模板
├── .github/
│   ├── workflows/tests.yml    PR 自动运行 python -m unittest -v（Linux + Windows）
│   ├── pull_request_template.md
│   └── ISSUE_TEMPLATE/task.md
├── docs/
│   ├── SCORING.md             评分与证据规则（长期资产）
│   ├── DECISIONS.md           架构决策记录 ADR-001~007
│   └── world-os-v1.html       V1.0 方案页（可行性、PRD、架构、30 天计划）
├── worldos/                   源码（约 1,700 行，零第三方依赖）
│   ├── __main__.py            python -m worldos 入口
│   ├── cli.py                 命令行（27 个命令）
│   ├── db.py                  数据目录规则、表结构（版本 2）、连接
│   ├── importers.py           信息入口：人工、JSON、CSV（UTF-8/GBK）、RSS；去重；注入标记
│   ├── cards.py               机会卡：字段修改、状态流转、审核、前置过滤、修改记录
│   ├── evidence.py            证据类型、独立来源、证据强度、支付意愿上限、成交状态
│   ├── scoring.py             100 分加权评分、证据封顶、评分记录
│   ├── records.py             验证记录：行动与反馈日志（访谈/报价/意向/合同/回款/成本/工时/认知/体验）
│   ├── prompts.py             提取提示词、外部文本隔离
│   ├── llm.py                 OpenAI 兼容适配器、模拟适配器、预算与次数闸门、失败记录
│   ├── extract.py             提取流程、模型输出白名单校验、事务导入、降级
│   ├── brief.py               规则生成每日简报
│   └── backup.py              导出、备份、恢复
├── tests/                     41 项测试（test_a ~ test_h）+ 模拟适配器夹具
├── scripts/demo.ps1 / demo.sh 全新演示库跑完整闭环
├── examples/
│   ├── demo/                  【演示数据】可直接导入
│   └── bug_hunter_2026-10/    真实公开信息样本、AI 提取输出、复现脚本
└── reports/2026-10-23/        本轮实际运行的原始输出
```

数据库、数据目录、`profile.md`、本地配置都被 `.gitignore` 排除。

## 2. 本轮改了什么

| 审查任务 | 做法 | 关键文件 |
|---|---|---|
| 任务一：完整交付包 | 复核源码完整；补齐配置示例、演示数据、测试、文档；打包 zip | 全部 |
| 任务二：Windows 文档 | README 改为 PowerShell 优先：单行命令、续行说明、编码、数据目录、API Key、测试；`--porcelain` 取 id，不假设 id=1；演示脚本用 UTF-8 BOM 兼容 PowerShell 5.1 | README.md、scripts/demo.ps1 |
| 任务三：端到端测试 | 测试拆为 A–H，共 41 项；网络请求全部 mock | tests/ |
| 任务四：证据模型 | 8 类证据；独立来源；支付意愿只认客户证据；成交状态单列；评分依据必填、修订原因必填、只追加；卡片修改记录 | evidence.py、scoring.py、cards.py、docs/SCORING.md |
| 任务五：BUG HUNTER 试运行 | 16 条真实公开信息 → 5 张候选卡 → 证据评估 → 筛选，并写两份研究报告 | BUG_HUNTER_SAMPLE.md、examples/bug_hunter_2026-10/ |
| 任务六：验收材料 | 本报告、TEST_REPORT、BUG_HUNTER_SAMPLE、README、KNOWN_ISSUES、zip | 根目录 |
| 指令 002：工程管理 | 本地 Git（基线 + 整改分支，提交历史完整）；Actions；PR/Issue 模板；ADR；CHANGELOG | .github/、docs/ |

## 3. 主要设计变化

- **数据目录**：默认 `%USERPROFILE%\worldos-data`，可用 `WORLDOS_HOME` 或 `--db` 改；不再散落在当前目录。
- **模型调用**：未配置 → 手动模式；配置不全（缺单价）→ 拒绝并降级；调用失败 → 记录错误并降级；超预算或超次数 → 拦截并记录；模拟适配器 → 费用 0、单独标记。
- **AI 输出隔离**：外部文本包在 `<item>` 数据区；模型输出只按白名单字段导入；AI 卡待审核、AI 证据未核实；整批事务导入。
- **状态机**：白名单流转；`killed`、`won` 为终态；淘汰卡只读；`won` 需要回款记录。

## 4. 验收清单

| 编号 | 验收项 | 状态 | 证据 |
|---|---|---|---|
| 001-1 | 完整 Python 源码、CLI 入口、数据模型、评分、AI 适配、导入、验证记录、简报 | PASS | `worldos/` 13 个模块 |
| 001-1 | 配置示例 | PASS | config.example.ps1 / .sh |
| 001-1 | 自动化测试 | PASS | 41 项，4 个 Python 版本 |
| 001-1 | 示例数据并标识为演示数据 | PASS | examples/demo/、演示脚本、测试夹具均标【演示数据】或【模拟输出】 |
| 001-1 | 项目目录树 | PASS | 本报告第 1 节 |
| 001-1 | worldos-v1-review.zip（不含 Key、私人数据、虚拟环境、缓存、数据库） | PASS | 打包后已逐项检查，见第 6 节 |
| 001-2 | README 在 PowerShell 下可执行 | PASS（PowerShell 7.4 / Linux 实测） | reports/…/readme-powershell-example.txt |
| 001-2 | Windows PowerShell 5.1 与 PowerShell 7（windows-latest） | PASS | [CI 运行](https://github.com/cxl88/world-os/actions/runs/39897300962)：Windows Server 2025、Python 3.12.10，unittest 41 项、demo.ps1（5.1 与 7）、BUG HUNTER run.ps1（5.1）均通过，中文输出正常 |
| 001-2 | 你自己的 Windows 电脑 | NOT TESTED | #7 |
| 001-2 | 示例不依赖 id=1 | PASS | `--porcelain` + 演示脚本 |
| 001-3 | 测试 A 无 AI 服务 | PASS | test_a_manual_flow |
| 001-3 | 测试 B AI 工作流（模拟） | PASS | test_b_ai_workflow |
| 001-3 | 测试 C 风险过滤 | PASS | test_c_risk_filter |
| 001-3 | 测试 D 证据完整性 | PASS | test_d_evidence |
| 001-3 | 测试 E 成本控制 | PASS | test_e_cost |
| 001-3 | 测试 F 异常输入 | PASS | test_f_bad_input |
| 001-3 | 测试 G 数据安全 | PASS | test_g_data_safety |
| 001-3 | 测试 A–G 在 GitHub Actions 运行 | PASS | Linux（3.10、3.13）与 Windows（3.12）各 41 项 |
| 001-3 | 真实模型端点 | NOT TESTED | 无 API Key；不产生费用（#9） |
| 001-4 | 证据模型区分 8 类、证据≠成交、单证据不足、评分依据与修订记录 | PASS | docs/SCORING.md、test_d_evidence |
| 001-5 | ≥10 条可追溯真实公开信息试运行 | PASS（16 条） | BUG_HUNTER_SAMPLE.md |
| 001-5 | 至少一份可供亲自验证的研究报告 | PASS（2 份） | BUG_HUNTER_SAMPLE.md |
| 001-5 | 证据经人工核实 | NOT TESTED | 需要你核对原文（#11） |
| 002-1 | 私有仓库 cxl88/world-os | PASS | 你在网页创建空仓库后由我推送 |
| 002-2 | 迁移代码并保留提交历史 | PASS | main = v0.1 基线；review-001 = 整改提交 |
| 002-3 | Issues 与 Milestones G1–G4 | PASS | Milestones G1–G4；Issues #1–#12，均含任务描述、优先级、实施范围、验收标准、当前状态 |
| 002-4 | GitHub Actions 运行 unittest | PASS | [PR #13 的 CI 运行](https://github.com/cxl88/world-os/actions/runs/39897300962) |
| 002-5 | 首个审查 PR | PASS | [#13](https://github.com/cxl88/world-os/pull/13) |
| 002-6 | 长期资产（目标、ADR、评分算法、提示词、已知问题、测试、合成数据、变更记录） | PASS | docs/、worldos/prompts.py、KNOWN_ISSUES.md、tests/、examples/、CHANGELOG.md |

## 5. 未解决的问题

见 KNOWN_ISSUES.md。最重要的三项：样本证据待你人工核实（#11）；你自己的 Windows 电脑待实测（#7）；真实模型待小额验证（#9）。

## 6. 交付包内容检查

`worldos-v1-review.zip` 由 `git archive` 从提交生成，只包含受版本控制的文件。打包后检查：不含 `.db`、`__pycache__`、虚拟环境、`profile.md`、`.env`、本地配置；全文搜索未发现 `sk-` 开头的密钥或 `API_KEY=` 赋值（`test-key-not-real` 是测试里的假值）。

## 7. 下一阶段计划

1. 总架构师审查 PR #13，验收后合并。
2. 你在自己的 Windows 电脑跑一次演示（#7），并人工核实样本证据（#11）。
3. 你亲自做 BUG_HUNTER_SAMPLE 中 MinIO 迁移缺口的 7 天验证（#12）；系统开发冻结，除非验证中暴露真实阻碍。
