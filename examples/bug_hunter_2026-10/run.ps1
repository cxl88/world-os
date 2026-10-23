# 复现 BUG HUNTER 真实公开信息试运行（Windows PowerShell 5.1 / PowerShell 7）
# 用法：powershell -ExecutionPolicy Bypass -File examples\bug_hunter_2026-10\run.ps1
param([string]$DataDir = "")
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
$Here = $PSScriptRoot
$env:PYTHONPATH = Split-Path -Parent (Split-Path -Parent $Here)
$Python = "python"; if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $Python = "python3" }
if (-not $DataDir) { $DataDir = Join-Path ([System.IO.Path]::GetTempPath()) "worldos-bughunter-sample" }
if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }
$env:WORLDOS_HOME = $DataDir
Remove-Item Env:WORLDOS_DB, Env:WORLDOS_LLM_PROVIDER -ErrorAction SilentlyContinue
function W { & $Python -m worldos @args; if ($LASTEXITCODE -ne 0) { throw "命令失败：worldos $args" } }
W init
W item-import (Join-Path $Here "items.json")
W cards-import (Join-Path $Here "ai_output_batch1.json") --ai --items "1,2,3,5,6,7,8,11,12,13"
W cards-import (Join-Path $Here "ai_output_batch2.json") --ai --items "4,9,10,14,15,16"
W cards
W brief
