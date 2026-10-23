# 测试报告（2026-10-23，分支 review-001）

## 0. 架构审查 002 整改（第二轮）

审查意见：PR #13 上的 ARCHITECT REVIEW 002（审查时的提交 `9aa73d4`）。本节是第二轮结果，第 1–5 节是第一轮的原始记录，保留不改。
原始输出：`reports/2026-10-23-review-002/`。

### 0.1 修复与对应的回归测试

| 审查项 | 修复 | 回归测试（修复前的代码上会失败） |
|---|---|---|
| P0-1 预算闸门可能整笔超支 | 发请求前估算单次费用上限（输入按 UTF-8 字节数 + 64 token 格式开销，输出按 `max_tokens`），“本月已计 + 本次上限 > 预算”就拦截；请求前先写 pending 并按上限计入；用量缺失、调用失败、程序中断都按上限计入并标“待对账”；实际用量超过上限时照实记账并标出 | `test_budget_reserves_worst_case_before_calling`（已花 3.002 < 预算 5，但加上本次上限会超，必须拦截；旧代码放行）、`test_spend_never_exceeds_budget_in_worst_case`（每次都按最坏用量返回，累计不超预算） |
| P0-1 价格、预算、次数未校验 | 必须是有限的非负数（次数为非负整数）；NaN、Infinity、负数、非数字都拒绝调用，不发请求 | `test_invalid_price_budget_or_limit_refuses_call`（9 组） |
| P0-1 缺少用量时记成 0 | 用量缺失或格式不对（缺字段、字符串、负数、小数）时按上限计入，`usage_known=0`，`cost` 和简报显示“待对账” | `test_missing_usage_is_charged_at_estimate_and_flagged`（6 组）、`test_model_failure_is_recorded_and_degrades`（失败也按上限计入）、`test_interrupted_call_stays_reserved`、`test_usage_above_estimate_is_recorded_and_flagged` |
| P0-1 数据库结构变化 | 结构版本 2 → 3，`llm_calls` 新增 `est_cost_usd`、`usage_known`；版本 2 的库和备份打开时在一个事务里自动升级，旧的失败调用标为待对账 | `test_v2_database_is_upgraded` |
| P0-2 0 元、NaN、Infinity 回款可以满足成交条件 | 报价、合同、回款金额必须是大于 0 的有限数字；成本可以为 0 但必须有限；行动的金额预算必须有限；`won` 要求回款合计 > 0（只计正的有限金额，旧数据里的 0 和 Infinity 不算）；成交状态同样只认正金额 | `test_won_requires_positive_finite_payment`（0、-0、-5、nan、NaN、inf、-inf、Infinity 全部拒绝；旧数据 0 和 Infinity 不能成交；部分回款 500 可以成交）、`test_money_amounts_must_be_positive_and_finite` |
| 非阻塞：评分过期 | 简报中：评分后已核实证据有变化（按证据 id、强度、独立来源数比较，不受时间精度影响），或评分后修改了卡片内容（按时间比较），在警报和今日机会里标出“评分可能已过期”；状态变化不算 | `test_brief_flags_stale_score` |
| 非阻塞：独立来源 | 代码不变；`docs/SCORING.md` 写明只按对方代号和链接去重、不判断转载和同源，同源的只核实一条；#11 的核对步骤加入“是否同源” | 文档 |
| 非阻塞：API Key 输入 | README 和 `config.example.ps1` 改为 `Read-Host -AsSecureString` 再转换，输入不回显；写明环境变量的局限 | CI 中在 Windows PowerShell 5.1 上验证转换写法；本地 PowerShell 7.4 验证（apikey-snippet-pwsh74.txt）。交互输入本身无法自动测试 |
| 自查发现：测试工具缺陷 | 测试辅助方法 `fail` 覆盖了 `unittest.TestCase.fail`，断言失败时报错信息被吞掉、显示成命令行解析错误（测试仍然失败，不会误报通过）。改名为 `fails` | 本轮新增测试的失败信息恢复正常 |

修复中没有修改任何原有测试的预期来让测试通过。只有一处原有测试的断言改变了：`test_model_failure_is_recorded_and_degrades` 原来断言失败调用费用为 0，这正是审查指出的缺陷（失败调用是否计费未知），现在断言按上限计入并标记待对账。原 `test_budget_stops_new_paid_requests` 接受了 $1.80 花费超过 $1.00 预算，已被上面两项更严格的测试取代。

### 0.2 运行结果

| 命令 | 结果 | 日志 |
|---|---|---|
| `python -m unittest -v`（Python 3.10 / 3.11 / 3.12 / 3.13） | PASS，各 50 项 | unittest-py3.1x.txt |
| `python scripts/mutation_check.py`（变异抽查，脚本已入库） | 31/31 处破坏被测试发现（原有 16 处 + 本轮 15 处） | mutation-check.txt |
| `bash scripts/demo.sh` | PASS | demo-bash.txt |
| `pwsh -File scripts/demo.ps1`（PowerShell 7.4，Linux） | PASS | demo-pwsh74.txt |
| README 中 PowerShell 示例逐行执行（PowerShell 7.4，Linux） | PASS | readme-powershell-example.txt |
| BUG HUNTER 复现脚本（bash、PowerShell 7.4） | PASS | bughunter-bash.txt、bughunter-pwsh74.txt |
| README 的 API Key 转换写法（PowerShell 7.4） | PASS | apikey-snippet-pwsh74.txt |
| CI（Linux 3.10 / 3.13，Windows 3.12 + PowerShell 5.1 与 7） | 见 PR #13 上的复验说明 | — |
| 你自己的 Windows 电脑（#7）、真实模型（#9）、人工核实来源（#11） | NOT TESTED | 需要你本人操作，步骤见 docs/ACCEPTANCE_WINDOWS.md |

---

## 第一轮记录（审查 001 整改）

环境：Linux 容器（x86_64）；Python 3.10.20 / 3.11 / 3.12 / 3.13.16；PowerShell 7.4.6（Linux 版）。
Windows：GitHub Actions windows-latest（Windows Server 2025、Python 3.12.10）[运行记录](https://github.com/cxl88/world-os/actions/runs/39897300962)。**没有在你自己的 Windows 电脑上运行过**（#7）。
原始输出：`reports/2026-10-23/`（路径中的临时目录已替换为 `<临时目录>`）。

## 1. 总结果

| 命令 | 结果 | 日志 |
|---|---|---|
| `python -m unittest -v`（Python 3.10） | PASS，41 项 | unittest-py3.10.txt |
| `python -m unittest -v`（Python 3.11） | PASS，41 项 | unittest-py3.11.txt |
| `python -m unittest -v`（Python 3.12） | PASS，41 项 | unittest-py3.12.txt |
| `python -m unittest -v`（Python 3.13） | PASS，41 项 | unittest-py3.13.txt |
| `bash scripts/demo.sh` | PASS | demo-bash.txt |
| `pwsh -File scripts/demo.ps1`（PowerShell 7.4，Linux） | PASS | demo-pwsh74.txt |
| README 中 PowerShell 示例逐行执行（PowerShell 7.4，Linux） | PASS | readme-powershell-example.txt |
| `bash examples/bug_hunter_2026-10/run.sh` | PASS | bughunter-bash.txt |
| `pwsh -File examples/bug_hunter_2026-10/run.ps1` | PASS | bughunter-pwsh74.txt |
| CI ubuntu-latest：`python -m unittest -v`（Python 3.10、3.13）与 `bash scripts/demo.sh` | PASS（unittest 各 41 项） | [运行记录](https://github.com/cxl88/world-os/actions/runs/39897300962) |
| CI windows-latest：`python -m unittest -v`（Python 3.12） | PASS，41 项 | 同上 |
| CI windows-latest：`scripts\demo.ps1`（Windows PowerShell 5.1 与 PowerShell 7） | PASS，中文输出正常 | 同上 |
| CI windows-latest：`examples\bug_hunter_2026-10\run.ps1`（Windows PowerShell 5.1） | PASS，导入 16 条、生成 5 张待审核卡 | 同上 |
| 你自己的 Windows 电脑 | NOT TESTED | #7 |
| 真实模型端点调用 | NOT TESTED（无 API Key，测试中全部用 mock 替换网络请求） | #9 |

测试不联网、不产生费用，每个测试使用独立的临时目录（目录名含中文和空格）。

## 2. 按审查要求逐项对应

| 要求 | 测试 | 结果 |
|---|---|---|
| **A 无 AI 服务**：录入 → 手动建卡 → 证据 → 评分 → 行动 → 反馈 → 简报 | `test_a_manual_flow.ManualFlowTest.test_full_loop_without_model`：确认未配置模型、全流程走通、简报含机会/行动/过期提醒/开发超时警报、`llm_calls` 为 0 | PASS |
| A 补充：无模型时提取降级为提示词文件 | `test_extract_without_model_degrades_to_prompt_file` | PASS |
| **B AI 工作流（模拟适配器）**：输入 → 提取 → 解析 → 待审核 → 审核 → 评估 → 行动 | `test_b_ai_workflow.MockAiWorkflowTest.test_mock_pipeline`：卡片 origin=ai-mock、待审核；证据为 AI 推断且未核实、链接取自原始条目；调用记录 simulated=1、费用 0；审核前不能评分/进入研究/被推荐；审核+核实后评分（单一公开来源封顶 40）并建行动 | PASS |
| B 补充：模拟输出有明确标记 | `test_default_mock_output_is_labelled`：卡名含【模拟输出】，列表显示 [模拟]，详情显示“非研究结论” | PASS |
| **C 风险过滤** | `test_c_risk_filter`：illegal / unauthorized / harmful 三种标记逐一验证：变为 killed、从简报和推荐列表消失、不能评分、不能建行动、不能转任何状态、过滤不能撤销、不能加证据、不能记录客户推进、不能改字段，修改记录里有系统写入的淘汰原因；no_payer 暂停且不能进入研究，人工改回 ok 可恢复；行动结论 kill 会淘汰卡片 | PASS |
| **D 证据完整性**：AI 内容不能自动获得高等级证据 | `test_ai_evidence_cannot_become_customer_evidence`、`test_ai_origin_evidence_never_stored_as_verified` | PASS |
| D：未经人工核实不能算客户反馈 | `test_unverified_customer_statement_does_not_count`：未核实的客户自述不计入；客户类证据缺对方代号被拒绝 | PASS |
| D：报价、意向、合同、回款分别记录；证据强度≠成交状态 | `test_deal_records_are_separate`：四类记录分别入库、成交状态逐级推进；无回款不能 won；未带 --claim 的成交记录不提高证据强度；报价/合同/回款必须有金额和对方 | PASS |
| D：一条证据不能证明整个机会 | `test_single_evidence_cannot_prove_opportunity`、`test_tier_and_pain_caps`（6 组边界） | PASS |
| D：评分依据、来源、人工修订记录 | `test_score_requires_basis_and_revision_reason`：无依据拒绝；重评无原因拒绝；记录 prev_score_id、纳入的证据 id、人工填写分与实际采用分 | PASS |
| **E 成本控制**：预算检查、超预算停止收费请求 | `test_budget_stops_new_paid_requests`：第 3 次请求被拦截且没有发出网络请求，记录 blocked | PASS |
| E：调用次数限制 | `test_daily_call_limit`、`MockCostTest`（模拟调用同样受限） | PASS |
| E：模型不可用时降级、失败记录 | `test_model_failure_is_recorded_and_degrades`：记录 status=error 与错误原文、费用 0，生成提示词文件，信息未标记已处理，简报显示失败次数 | PASS |
| E：模型返回错误 JSON | `test_bad_model_json_saved_not_imported`：不导入、原文另存、信息未标记已处理 | PASS |
| E：不把模拟 token 当作账单 | `test_mock_usage_is_not_billed`：预算为 0 时模拟调用仍可运行；simulated=1、费用 0；本月真实花费 0 | PASS |
| E：未配置单价不发起收费请求 | `test_missing_price_refuses_paid_call` | PASS |
| **F 异常输入**：重复资料 | `test_duplicates`（链接大小写/空格归一；相似卡提示） | PASS |
| F：缺失来源 | `test_missing_source`（录入拒绝；批量导入跳过并计数；公开资料缺 url、一手资料缺出处被拒绝） | PASS |
| F：错误 JSON | `test_bad_json`（信息与卡片导入报错位置；一批中有坏卡时整批回滚；AI 导入缺 --items 拒绝；坏 RSS 报错） | PASS |
| F：无效评分 | `test_invalid_scores`（6、-1、abc、2.5、不存在的卡） | PASS |
| F：不合法状态转换 | `test_illegal_state_transitions`（跳级、终态、用 card-set 绕过、重复关闭行动；修改记录完整） | PASS |
| F：提示词注入 | `test_prompt_injection_in_external_text`、`test_format_item_neutralises_tags`：含注入的条目被标记并在简报提示；外部文本包在 `<item>` 内、伪造的结束标签被中和；被“带偏”的模型输出中 reviewed/status/total/send_email/evidence_type/越界 item_id 全部被丢弃并警告，卡片仍待审核，证据仍是 AI 推断，链接用原始条目的 | PASS |
| **G 数据安全**：导出一致 | `test_export_matches_database`（导出 JSON 与数据库逐表逐行相等） | PASS |
| G：备份与恢复一致 | `test_backup_and_restore_roundtrip`（恢复后与备份时逐表相等；覆盖前自动另存且保留了恢复前的数据）、`test_restore_into_new_location` | PASS |
| G：坏备份与旧结构 | `test_restore_rejects_garbage`、`test_old_schema_is_refused` | PASS |
| 平台：数据目录规则、GBK CSV、GBK 控制台、--porcelain、ID 列表传参 | `test_h_platform` 7 项（含演示数据文件导入） | PASS（Linux 与 windows-latest） |

## 3. 测试有效性抽查（变异测试）

为了确认测试不是“永远通过”，在副本里逐个故意破坏关键规则，再跑全部测试。16 处破坏全部被测试发现：

| 被破坏的规则 | 结果 |
|---|---|
| AI 证据入库时强制未核实 | 测试失败 ✔ |
| AI 证据入库时只能是 AI 推断 | 测试失败 ✔ |
| 月度预算闸门 | 测试失败 ✔ |
| 每日次数上限 | 测试失败 ✔ |
| 模拟调用费用为 0 且标记 simulated | 测试失败 ✔ |
| 状态流转白名单 | 测试失败 ✔ |
| 淘汰卡不能继续推进 | 测试失败 ✔ |
| 证据只能引用本批条目 | 测试失败 ✔ |
| 模型输出非法字段告警 | 测试失败 ✔ |
| 中和伪造的 `<item>` 标签 | 测试失败 ✔ |
| 独立来源 ≥2 才算达到某档 | 测试失败 ✔ |
| 支付意愿上限 | 测试失败 ✔ |
| 重评必须写原因 | 测试失败 ✔ |
| 恢复覆盖需要 --force | 测试失败 ✔ |
| 信息必须有来源 | 测试失败 ✔ |
| 简报只推荐已审核、通过过滤的研究/验证中卡片 | 测试失败 ✔ |

## 4. 失败与修复记录（本轮）

| # | 发现方式 | 问题 | 修复 | 状态 |
|---|---|---|---|---|
| 1 | 变异抽查 | 删掉“AI 证据入库强制未核实”这行后所有测试仍通过，说明缺测试 | 新增 `test_ai_origin_evidence_never_stored_as_verified` | 已修复 |
| 2 | 第 1 条新增的测试首次运行**失败** | 真实缺陷：`evidence.add` 允许 AI 来源的证据在入库时就标为“公开资料”（虽然未核实，但类型被误标） | AI 来源证据入库时只允许 `ai_inference`，否则报错 | 已修复，测试通过 |
| 3 | 运行 `run.ps1`（PowerShell 7.4）**失败**，退出码 1 | PowerShell 包装函数用 `@args` 转发时，未加引号的 `1,2,3` 被当成数组，传给 Python 变成 `System.Object[]` | 脚本和 README 中的 id 列表加引号；`--ids/--items` 同时接受逗号、空格和多个参数；新增 `test_id_lists_accept_commas_or_spaces` | 已修复，重跑通过 |
| 4 | 代码自查 | `run.ps1/run.sh` 会删除用户指定的已有目录，可能误删正式数据 | 只清理带 `.bughunter-sample` 标记的目录，否则拒绝；已实测拒绝路径 | 已修复 |
| 5 | 代码自查 | 只读打开备份时用字符串拼 `file:` URI，Windows 盘符和中文路径可能出错 | 改用 `pathlib.Path.as_uri()` | 已修复；Windows 实际效果待 CI |
| 6 | 代码自查 | 无控制台环境（CI）中设置 `[Console]::OutputEncoding` 可能抛异常 | 用 try/catch 包住 | 已修复；效果待 CI |
| 7 | 运行 `config.example.ps1`（Linux pwsh） | `$env:USERPROFILE` 在非 Windows 为空 | 改用 `[Environment]::GetFolderPath("UserProfile")` | 已修复 |
| 8 | 运行前自查 | 两处测试断言是我算错了期望值（66 写成 70，74 写成 75） | 改正断言 | 已修复 |
| 9 | 输出检查 | 封顶后的分数显示为整数（60），未封顶的显示小数（54.0） | 统一为浮点数 | 已修复 |

本轮最终代码上，全部 41 项测试在本地 4 个 Python 版本和 CI 的 Linux、Windows 上均通过，没有已知失败项。

CI 中的一处观察：Windows 上 `unittest -v` 打印的中文测试说明显示为 `?`。原因是 CI 中输出被重定向，Python 按运行器（英文版 Windows）的系统代码页编码，而该代码页没有中文。这是测试框架自身的输出，不影响结果；演示脚本设置了 UTF-8，中文显示正常。见 KNOWN_ISSUES.md L12。

## 5. 如何自己复现

```powershell
python -m unittest -v
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
powershell -ExecutionPolicy Bypass -File examples\bug_hunter_2026-10\run.ps1
```
