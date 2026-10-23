"""模型调用：OpenAI 兼容适配器、模拟适配器、预算与次数闸门、失败记录。

不依赖任何厂商 SDK。三种情况：
  - 未配置模型：抛 ModelUnavailable，调用方降级为“手动模式”（生成提示词文件）；
  - provider=openai：任何 OpenAI 兼容端点（DeepSeek 等），必须配置单价，否则拒绝调用，避免账单记成 0；
  - provider=mock：确定性模拟适配器，仅用于测试和演示。记录 simulated=1、费用 0，不计入真实花费。

环境变量：
  WORLDOS_LLM_PROVIDER        openai / mock（未设置且有 KEY+URL 时视为 openai）
  WORLDOS_LLM_BASE_URL        例如 https://api.deepseek.com
  WORLDOS_LLM_API_KEY         只放环境变量，不要写进文件
  WORLDOS_LLM_MODEL           例如 deepseek-flash
  WORLDOS_PRICE_IN / WORLDOS_PRICE_OUT   美元/百万 token，按官方价格填写
  WORLDOS_MONTHLY_BUDGET_USD  月度预算，默认 25
  WORLDOS_MAX_CALLS_PER_DAY   每日调用次数上限，默认 30
  WORLDOS_MOCK_RESPONSE       模拟适配器返回内容所在文件（可选）
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import db


class ModelUnavailable(RuntimeError):
    """模型不可用：未配置、配置不完整或调用失败。调用方应降级为手动模式。"""


class BudgetExceeded(RuntimeError):
    pass


class CallLimitExceeded(RuntimeError):
    pass


def provider():
    p = os.environ.get("WORLDOS_LLM_PROVIDER", "").strip().lower()
    if p:
        return p
    if os.environ.get("WORLDOS_LLM_API_KEY") and os.environ.get("WORLDOS_LLM_BASE_URL"):
        return "openai"
    return None


def month_spend(conn):
    """本月真实花费（美元）。模拟调用和失败调用不计入。"""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls WHERE simulated=0 AND status='ok' "
        "AND substr(created_at,1,7)=substr(?,1,7)", (db.now(),)).fetchone()
    return row[0]


def calls_today(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE status IN ('ok','error') AND substr(created_at,1,10)=substr(?,1,10)",
        (db.now(),)).fetchone()[0]


def _record(conn, task, prov, model, status, error=None, tin=0, tout=0, cost=0.0, simulated=False):
    db.insert(conn, "llm_calls", {
        "task": task, "provider": prov, "model": model, "status": status, "error": error,
        "input_tokens": tin, "output_tokens": tout, "cost_usd": cost, "simulated": int(simulated),
        "created_at": db.now()})


def _price(name):
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        raise ModelUnavailable(f"未设置 {name}（美元/百万 token），为避免把真实账单记成 0，拒绝调用")
    return float(v)


def chat(conn, task, system, user, max_tokens=2000):
    prov = provider()
    if prov is None:
        raise ModelUnavailable("未配置模型")
    if prov not in ("openai", "mock"):
        raise ModelUnavailable(f"未知的 WORLDOS_LLM_PROVIDER={prov}")
    model = os.environ.get("WORLDOS_LLM_MODEL", "mock-deterministic" if prov == "mock" else "deepseek-flash")
    simulated = prov == "mock"

    budget = float(os.environ.get("WORLDOS_MONTHLY_BUDGET_USD", "25"))
    spent = month_spend(conn)
    if not simulated and spent >= budget:
        _record(conn, task, prov, model, "blocked", f"预算已用完 ${spent:.4f}/${budget:.2f}")
        raise BudgetExceeded(f"本月模型花费 ${spent:.4f} 已达到上限 ${budget:.2f}，已停止新的收费请求")
    limit = int(os.environ.get("WORLDOS_MAX_CALLS_PER_DAY", "30"))
    if calls_today(conn) >= limit:
        _record(conn, task, prov, model, "blocked", f"今日调用次数已达上限 {limit}")
        raise CallLimitExceeded(f"今日模型调用已达 {limit} 次上限，已停止调用")

    if simulated:
        text = _mock_response(user)
        tin, tout = len(system + user) // 2, len(text) // 2   # 粗略字符估算，仅供测试观察，不是账单
        _record(conn, task, prov, model, "ok", tin=tin, tout=tout, cost=0.0, simulated=True)
        return text

    try:
        pin, pout = _price("WORLDOS_PRICE_IN"), _price("WORLDOS_PRICE_OUT")
        url = os.environ["WORLDOS_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
        key = os.environ["WORLDOS_LLM_API_KEY"]
    except KeyError as e:
        raise ModelUnavailable(f"缺少环境变量 {e.args[0]}")
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "temperature": 0.2,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
        msg = f"{type(e).__name__}: {e}"
        # 失败的请求是否被计费取决于供应商；没有返回 usage 时无法得知，费用记 0 并保留错误原文
        _record(conn, task, prov, model, "error", msg[:500])
        raise ModelUnavailable(f"模型调用失败：{msg}")
    tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    cost = round(tin / 1e6 * pin + tout / 1e6 * pout, 6)
    _record(conn, task, prov, model, "ok", tin=tin, tout=tout, cost=cost)
    return text


def _mock_response(user):
    """确定性模拟输出：优先读 WORLDOS_MOCK_RESPONSE 文件；否则为每个条目生成一张标注为模拟的卡。"""
    path = os.environ.get("WORLDOS_MOCK_RESPONSE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    ids = [int(x) for x in re.findall(r'<item id="(\d+)"', user)][:3]
    return json.dumps([{
        "name": f"【模拟输出】条目{i}的候选问题",
        "bug_type": "未分类",
        "problem": "模拟适配器生成的占位内容，不是研究结论",
        "payers": "未知",
        "min_validation": "（模拟）联系 3 个潜在付费方",
        "kill_condition": "（模拟）无人愿意付费",
        "evidence": [{"item_id": i, "claim": "模拟主张", "kind": "inference"}],
    } for i in ids], ensure_ascii=False)


def parse_json(text):
    """解析模型输出的 JSON，容忍外层 ```json 代码块。格式错误抛 ValueError。"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 格式错误：第 {e.lineno} 行第 {e.colno} 列，{e.msg}")
