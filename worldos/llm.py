"""模型调用：一个 OpenAI 兼容的 HTTP 适配器 + 手动模式 + 成本记录。

不依赖任何厂商 SDK。没有配置 API Key 时进入“手动模式”：
把提示词写到文件，你粘贴到任意已有的聊天工具（零边际成本），
再把返回的 JSON 存成文件，用 `worldos cards-import` 导入。

环境变量：
  WORLDOS_LLM_BASE_URL   例如 https://api.deepseek.com （任何 OpenAI 兼容端点）
  WORLDOS_LLM_API_KEY
  WORLDOS_LLM_MODEL      例如 deepseek-flash
  WORLDOS_PRICE_IN       每百万输入 token 美元单价（自己按官方价格填写）
  WORLDOS_PRICE_OUT      每百万输出 token 美元单价
  WORLDOS_MONTHLY_BUDGET_USD  月度模型预算上限，默认 25（约等于 200 元人民币以内）
"""
import json
import os
import re
import urllib.request

from . import db


class BudgetExceeded(RuntimeError):
    pass


def configured():
    return bool(os.environ.get("WORLDOS_LLM_API_KEY") and os.environ.get("WORLDOS_LLM_BASE_URL"))


def month_spend(conn):
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) AS s FROM llm_calls WHERE substr(created_at,1,7)=substr(?,1,7)",
        (db.now(),),
    ).fetchone()
    return row["s"]


def cost_of(input_tokens, output_tokens):
    pin = float(os.environ.get("WORLDOS_PRICE_IN", "0"))
    pout = float(os.environ.get("WORLDOS_PRICE_OUT", "0"))
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


def chat(conn, task, system, user, max_tokens=2000):
    budget = float(os.environ.get("WORLDOS_MONTHLY_BUDGET_USD", "25"))
    spent = month_spend(conn)
    if spent >= budget:
        raise BudgetExceeded(f"本月模型花费 ${spent:.2f} 已达到上限 ${budget:.2f}，已停止调用")
    model = os.environ.get("WORLDOS_LLM_MODEL", "deepseek-flash")
    url = os.environ["WORLDOS_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ["WORLDOS_LLM_API_KEY"],
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    usage = data.get("usage", {})
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    db.insert(conn, "llm_calls", {
        "task": task, "model": model, "input_tokens": tin, "output_tokens": tout,
        "cost_usd": cost_of(tin, tout), "created_at": db.now(),
    })
    return data["choices"][0]["message"]["content"]


def parse_json(text):
    """容忍模型在 JSON 外包一层 ```json 代码块。"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return json.loads(m.group(1) if m else text)
