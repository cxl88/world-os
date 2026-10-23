# Windows 本机验收步骤（#7、#9、#11）

这三项只能由你本人在自己的电脑上完成。你把结果贴回对应的 Issue 之前，它们的状态一直是 **NOT TESTED**。

通用约定：
- 在 **PowerShell** 窗口里逐段复制执行（Windows PowerShell 5.1 或 PowerShell 7 都可以）。
- 合并 PR #13 之前用 `review-001` 分支，合并之后用 `main`。
- **API Key、真实姓名、客户信息不要贴到 Issue 里。** 贴之前看一眼输出，路径里的 Windows 用户名可以打码。

## 0. 准备（一次）

```powershell
python --version                       # 需要 3.10 或更高；如果打开了微软商店，见 README 第 1 节
git clone https://github.com/cxl88/world-os.git "$HOME\world-os"   # 私有仓库，会弹出 GitHub 登录
cd "$HOME\world-os"
git checkout review-001                 # 合并后改成：git checkout main; git pull
```

没装 Git：在 GitHub 网页切到 `review-001` 分支，点 Code → Download ZIP，解压后 `cd` 到解压出的目录。

## #7 本机运行验收

```powershell
cd "$HOME\world-os"
python -m unittest
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
"Windows: " + (Get-CimInstance Win32_OperatingSystem).Caption
"PowerShell: " + $PSVersionTable.PSVersion
python --version
```

通过标准：
- `unittest` 最后两行是 `Ran 50 tests ...` 和 `OK`；
- 演示脚本最后一行是“演示完成”，中间的中文没有乱码；
- 演示只写 `%TEMP%\worldos-demo`，不会碰你的正式数据。

贴回 #7：最后 6 行版本信息、`Ran 50 tests` 那一行、演示脚本最后一行。失败就贴报错原文。

## #9 真实模型小额调用验收

前提：PR #13 的预算修复已经在你的代码里（`review-001` 或合并后的 `main`）。全程只调用 **1 次** 真实模型，预算上限 0.10 美元。用独立的临时数据目录，不影响正式数据。

**第 1 步：设置（单价按供应商官方价格页填写，单位：美元/百万 token，记下查询日期）**

```powershell
cd "$HOME\world-os"
$env:WORLDOS_HOME = Join-Path $env:TEMP "worldos-model-test"
$env:WORLDOS_LLM_PROVIDER = "openai"
$env:WORLDOS_LLM_BASE_URL = "https://api.deepseek.com"   # 换成你用的供应商
$env:WORLDOS_LLM_MODEL = "deepseek-flash"                  # 换成你用的模型
$env:WORLDOS_PRICE_IN = "0.30"                             # 按官方价格页改
$env:WORLDOS_PRICE_OUT = "1.20"                            # 按官方价格页改
$env:WORLDOS_MAX_CALLS_PER_DAY = "2"
$k = Read-Host "API Key" -AsSecureString                   # 输入不回显
$env:WORLDOS_LLM_API_KEY = [System.Net.NetworkCredential]::new("", $k).Password; Remove-Variable k
python -m worldos init
python -m worldos item-import examples\bug_hunter_2026-10\items.json
```

**第 2 步：先验证预算闸门（不花钱）**

```powershell
$env:WORLDOS_MONTHLY_BUDGET_USD = "0"
python -m worldos extract --ids 9        # 期望：报错“已停止新的收费请求”，没有发出请求
python -m worldos cost                   # 期望：一行 blocked、“未发出”、$0.0000
```

**第 3 步：真实调用 1 次**

```powershell
$env:WORLDOS_MONTHLY_BUDGET_USD = "0.10"
python -m worldos extract --ids 9        # 期望：生成若干张“AI 生成，待人工审核”的卡
python -m worldos cost
python -m worldos cards
Remove-Item Env:WORLDOS_LLM_API_KEY      # 用完立即清除
```

**第 4 步：对账**：在供应商后台找到这次调用，对比输入/输出 token 数和扣费金额。

通过标准：
- 第 2 步被拦截，而且供应商后台没有这次请求；
- 第 3 步成功，或者失败了但有明确的错误记录，并降级为提示词文件；
- `cost` 里的 token 数与供应商后台一致。如果显示“待对账”，说明供应商没返回用量，需要记下来；
- 总花费低于 0.10 美元。

贴回 #9：`cost` 的输出、供应商后台的 token 数和金额、你用的模型名、单价和查询日期。**不要贴 API Key。** AI 生成的卡只是候选，不是研究结论。

## #11 人工核实 BUG HUNTER 样本来源

16 条来源见 `BUG_HUNTER_SAMPLE.md` 的“信息来源”表，样本里所有证据都是“AI 推断、未核实”。

**第 1 步：逐条打开原文，填下面这张表**（贴到 #11）

| # | 链接能打开 | 日期一致 | 摘要与原文一致 | 原始出处（是否转载或引用同一来源） | 结论：核实 / 不核实 / 有误 |
|---|---|---|---|---|---|
| 1 | | | | | |

判断“是否同源”：程序只按链接去重，不知道两篇报道是不是来自同一份公告。比如 #9（Blocks & Files）和 #10（InfoQ）都在报道 MinIO 自己的变化。打开原文看它们引用的是什么：引用同一个源头的，只核实其中一条。

**第 2 步（可选）：在样本库里标记核实结果**

```powershell
cd "$HOME\world-os"
powershell -ExecutionPolicy Bypass -File examples\bug_hunter_2026-10\run.ps1
$env:WORLDOS_HOME = Join-Path $env:TEMP "worldos-bughunter-sample"
python -m worldos cards                  # MinIO 是 #4
python -m worldos card 4                 # “证据”一节方括号里是证据编号，样本里 MinIO 的证据是 15–19
python -m worldos evidence-verify 15 --type public   # 只核实你对过原文的；同源的只核实一条
python -m worldos card 4                 # 独立来源数增加；有 2 个独立来源后证据强度才升到 T1
```

样本库在临时目录，重跑 `run.ps1` 会被重置，所以核实结论以 #11 里的表格为准。

通过标准：16 条都有结论，不一致或同源的地方写清楚。
