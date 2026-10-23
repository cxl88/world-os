# WORLD OS 配置示例（Windows PowerShell）
# 复制为 config.local.ps1（已被 .gitignore 排除）后修改，在每个新窗口里执行：  . .\config.local.ps1
# 不要把真实 API Key 写进任何会提交到仓库的文件。

# 中文输入输出统一用 UTF-8
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# 数据目录（数据库、提示词、简报、备份、导出都在这里）
$env:WORLDOS_HOME = Join-Path ([Environment]::GetFolderPath("UserProfile")) "worldos-data"
# 个人档案（可选，默认读取 数据目录\profile.md）
# $env:WORLDOS_PROFILE = "D:\私人\profile.md"

# 模型（可选；不设置时 extract 自动生成提示词文件，走手动模式）
# $env:WORLDOS_LLM_PROVIDER = "openai"
# $env:WORLDOS_LLM_BASE_URL = "https://api.deepseek.com"
# $env:WORLDOS_LLM_MODEL = "deepseek-flash"
# $env:WORLDOS_LLM_API_KEY = Read-Host "API Key"
# 单价：美元/百万 token，按官方价格页填写（以下为 2026-10-23 查询的 deepseek-flash 高峰价）
# $env:WORLDOS_PRICE_IN = "0.30"
# $env:WORLDOS_PRICE_OUT = "1.20"
# $env:WORLDOS_MONTHLY_BUDGET_USD = "25"
# $env:WORLDOS_MAX_CALLS_PER_DAY = "30"
