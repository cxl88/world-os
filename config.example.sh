# WORLD OS 配置示例（Bash）
# 复制为 config.local.sh（已被 .gitignore 排除）后修改，每个新终端执行：  source ./config.local.sh
# 不要把真实 API Key 写进任何会提交到仓库的文件。
export PYTHONIOENCODING=utf-8
export WORLDOS_HOME="$HOME/worldos-data"
# export WORLDOS_PROFILE="$HOME/private/profile.md"

# 模型（可选）
# export WORLDOS_LLM_PROVIDER=openai
# export WORLDOS_LLM_BASE_URL=https://api.deepseek.com
# export WORLDOS_LLM_MODEL=deepseek-flash
# read -rs -p "API Key: " WORLDOS_LLM_API_KEY && export WORLDOS_LLM_API_KEY
# export WORLDOS_PRICE_IN=0.30     # 美元/百万 token，按官方价格页填写
# export WORLDOS_PRICE_OUT=1.20
# export WORLDOS_MONTHLY_BUDGET_USD=25
# export WORLDOS_MAX_CALLS_PER_DAY=30
