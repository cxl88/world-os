# WORLD OS 演示脚本（Windows PowerShell 5.1 / PowerShell 7 均可）
# 在一个全新的演示数据目录里跑完整闭环。全部数据都是【演示数据】，不是真实商业信息。
# 用法（在项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
#   pwsh -File scripts/demo.ps1 -DataDir D:\temp\worldos-demo
param(
    [string]$DataDir = "",
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"

# 中文输出：让 Python 和 PowerShell 都用 UTF-8 交换文本
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }  # 无控制台的环境（如 CI）可能不允许设置
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = $Root

if (-not $Python) {
    foreach ($candidate in @("python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { $Python = $candidate; break }
    }
    if (-not $Python) { throw "找不到 python。请安装 Python 3.10+ 并勾选 Add python.exe to PATH" }
}

if (-not $DataDir) { $DataDir = Join-Path ([System.IO.Path]::GetTempPath()) "worldos-demo" }
if ((Split-Path -Leaf $DataDir) -ne "worldos-demo") { throw "为安全起见，演示目录名必须是 worldos-demo：$DataDir" }
if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }
$env:WORLDOS_HOME = $DataDir
Remove-Item Env:WORLDOS_DB, Env:WORLDOS_LLM_PROVIDER, Env:WORLDOS_LLM_API_KEY -ErrorAction SilentlyContinue

function W {
    & $Python -m worldos @args
    if ($LASTEXITCODE -ne 0) { throw "命令失败：worldos $args" }
}
function WId {
    $output = & $Python -m worldos --porcelain @args
    if ($LASTEXITCODE -ne 0) { throw "命令失败：worldos $args" }
    return [int](@($output)[-1])
}

& $Python --version
W init

Write-Host "`n== 1. 录入信息、手动建卡、加证据 =="
$item = WId item-add --title "【演示数据】某小型工厂仍每月人工抄表" --source "演示数据" --cred B --published 2026-10-01
$card = WId card-add --name "【演示数据】工厂抄表自动化" --bug-type 流程 --payers "中小工厂设备科（假设）" --kill-condition "5 家里少于 2 家愿意付费试点"
$null = WId evidence-add $card --type public --claim "演示：行业文章提到人工抄表普遍" --url https://example.com/demo --item $item --verified
$null = WId log interview --card $card --who 演示客户A --claim "演示：每月抄表约 2 人天"
$null = WId log interview --card $card --who 演示客户B --claim "演示：也在手工抄表"

Write-Host "`n== 2. 评分（证据规则会自动压分）=="
$null = WId score $card --pain 4 --access 3 --feasibility 4 --reuse 3 --risk 4 --basis "演示：两家客户自述，尚无报价"
W status $card researching

Write-Host "`n== 3. 验证行动与反馈 =="
$due = (Get-Date).AddDays(7).ToString("yyyy-MM-dd")
$action = WId action-add $card --title "【演示数据】拜访 3 家工厂" --hypothesis "愿付 3000 元试点" --acceptance "至少 1 家给出书面报价意向" --due $due --minutes 240
$null = WId log time --category outreach --minutes 60
$null = WId log quote --card $card --who 演示客户A --amount 3000 --note "演示报价"

Write-Host "`n== 4. 每日简报 =="
W brief --save

Write-Host "`n== 5. 模拟 AI 提取（仅测试流程，输出不是研究结论）=="
$env:WORLDOS_LLM_PROVIDER = "mock"
$null = WId item-add --title "【演示数据】小企业抱怨发票录入耗时" --source "演示数据"
W extract
Remove-Item Env:WORLDOS_LLM_PROVIDER
W cards

Write-Host "`n== 6. 导出与备份 =="
W export
$backupPath = & $Python -m worldos --porcelain backup
if ($LASTEXITCODE -ne 0) { throw "备份失败" }
Write-Host "备份文件：$backupPath"
W cost

Write-Host "`n演示完成。卡片 #$card，行动 #$action，数据目录：$DataDir"
