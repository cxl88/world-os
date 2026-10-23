# 工程报告：架构审查 001 / 指令 002 整改（2026-10-23）

## 结论

- 完整源码、测试、文档、演示数据都在仓库里，不是只有 README。
- 41 项自动化测试覆盖审查要求的测试 A–G，在 Python 3.10、3.11、3.12、3.13 上实际运行全部通过；16 处故意破坏关键规则的变异抽查全部被测试发现。
- 证据模型按任务四重做：8 类证据，证据强度、支付意愿、成交状态三者分开，单条证据不能证明机会成立，评分有依据和修订记录。
- BUG HUNTER 用 16 条可追溯的真实公开信息试运行，产出 5 张候选卡；没有一张达到“已验证”，报告如实说明。
- **未完成**：GitHub 远程仓库等你创建空仓库后再推送；Windows 本机与 PowerShell 5.1 只能由 CI 验证；没有调用过真实模型。详见第 5 节和 KNOWN_ISSUES.md。

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
| 001-2 | Windows PowerShell 5.1 与 Windows 本机 | NOT TESTED | 已写入 CI；仓库建好后补链接 |
| 001-2 | 示例不依赖 id=1 | PASS | `--porcelain` + 演示脚本 |
| 001-3 | 测试 A 无 AI 服务 | PASS | test_a_manual_flow |
| 001-3 | 测试 B AI 工作流（模拟） | PASS | test_b_ai_workflow |
| 001-3 | 测试 C 风险过滤 | PASS | test_c_risk_filter |
| 001-3 | 测试 D 证据完整性 | PASS | test_d_evidence |
| 001-3 | 测试 E 成本控制 | PASS | test_e_cost |
| 001-3 | 测试 F 异常输入 | PASS | test_f_bad_input |
| 001-3 | 测试 G 数据安全 | PASS | test_g_data_safety |
| 001-3 | 真实模型端点 | NOT TESTED | 无 API Key；不产生费用 |
| 001-4 | 证据模型区分 8 类、证据≠成交、单证据不足、评分依据与修订记录 | PASS | docs/SCORING.md、test_d_evidence |
| 001-5 | ≥10 条可追溯真实公开信息试运行 | PASS（16 条） | BUG_HUNTER_SAMPLE.md |
| 001-5 | 至少一份可供亲自验证的研究报告 | PASS（2 份） | BUG_HUNTER_SAMPLE.md |
| 001-5 | 证据经人工核实 | NOT TESTED | 需要你核对原文 |
| 002-1 | 私有仓库 cxl88/world-os | BLOCKED | 等你创建空仓库（本会话不能调用建仓接口） |
| 002-2 | 迁移代码并保留提交历史 | PASS（本地） | 本地 Git：基线 v0.1 + review-001 分支多次提交 |
| 002-3 | Issues 与 Milestones G1–G4 | BLOCKED | 依赖远程仓库；Milestone 可能需要你在网页手动创建 |
| 002-4 | GitHub Actions 运行 unittest | PASS（配置完成）/ NOT TESTED（尚未在 GitHub 上运行） | .github/workflows/tests.yml |
| 002-5 | 首个审查 PR | BLOCKED | 依赖远程仓库 |
| 002-6 | 长期资产（目标、ADR、评分算法、提示词、已知问题、测试、合成数据、变更记录） | PASS | docs/、worldos/prompts.py、KNOWN_ISSUES.md、tests/、examples/、CHANGELOG.md |

## 5. 未解决的问题

见 KNOWN_ISSUES.md。最重要的三项：远程仓库待创建；Windows 本机与 PowerShell 5.1 待 CI 验证；样本证据待你人工核实。

## 6. 交付包内容检查

`worldos-v1-review.zip` 由 `git archive` 从提交生成，只包含受版本控制的文件。打包后检查：不含 `.db`、`__pycache__`、虚拟环境、`profile.md`、`.env`、本地配置；全文搜索未发现 `sk-` 开头的密钥或 `API_KEY=` 赋值（`test-key-not-real` 是测试里的假值）。

## 7. 下一阶段计划

1. 仓库建好后：推送 main（v0.1 基线）与 review-001，开 PR，等 CI 在 Windows 上跑完并补充结果。
2. 建 Milestone G1–G4 与对应 Issue，本轮工作关联到 G1/G2/G3。
3. 你亲自做 BUG_HUNTER_SAMPLE 中 MinIO 迁移缺口的 7 天验证；系统开发冻结，除非验证中暴露真实阻碍。
