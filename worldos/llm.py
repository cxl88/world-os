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

预算闸门（本地，不是供应商侧的硬上限）：
  - 发请求前按“输入 UTF-8 字节数 + 消息格式开销”和 max_tokens 估算单次费用上限，
    本月已计费用 + 这次上限 > 预算时拦截，不发请求；
  - 请求发出前先记一条 pending，按上限计入预算；返回后按实际用量改写；
  - 供应商没有返回用量、或调用失败（可能已被计费），按上限计入并标记“待对账”；
  - 实际用量超过上限时照实记账并标出，说明供应商没有遵守 max_tokens 或估算前提不成立。
"""
import json
import math
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


# 计入预算的状态：已发出的请求都可能产生费用；blocked 没有发出
BILLABLE = ("pending", "ok", "error")
# 每次请求的消息格式开销（角色标记等）按 64 个 token 预留
MESSAGE_OVERHEAD_TOKENS = 64


def month_spend(conn, month=None):
    """本月计入预算的真实花费（美元），含按上限预估、待对账的部分。模拟调用不计入。"""
    return ledger(conn, month)["spend"]


def ledger(conn, month=None):
    """本月账本：已确认的实际费用与按上限预估的待对账费用分开统计。"""
    month = month or db.now()[:7]
    rows = conn.execute(
        "SELECT status, usage_known, cost_usd FROM llm_calls WHERE simulated=0 AND substr(created_at,1,7)=?",
        (month,)).fetchall()
    billed = [r for r in rows if r["status"] in BILLABLE]
    known = [r["cost_usd"] or 0 for r in billed if r["usage_known"]]
    unknown = [r["cost_usd"] or 0 for r in billed if not r["usage_known"]]
    return {"ok": sum(r["status"] == "ok" for r in rows), "confirmed": sum(known),
            "unknown_n": len(unknown), "unknown": sum(unknown), "spend": sum(known) + sum(unknown)}


def calls_today(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE status IN ('pending','ok','error') "
        "AND substr(created_at,1,10)=substr(?,1,10)", (db.now(),)).fetchone()[0]


def _record(conn, task, prov, model, status, error=None, tin=0, tout=0, cost=0.0, simulated=False,
            est=None, usage_known=True):
    return db.insert(conn, "llm_calls", {
        "task": task, "provider": prov, "model": model, "status": status, "error": error,
        "input_tokens": tin, "output_tokens": tout, "cost_usd": cost, "simulated": int(simulated),
        "created_at": db.now(), "est_cost_usd": est, "usage_known": int(usage_known)})


def _update(conn, call_id, **fields):
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE llm_calls SET {sets} WHERE id=?", [*fields.values(), call_id])
    conn.commit()


def _number(name, default=None):
    """读取非负有限数。缺失、非数字、负数、NaN、Infinity 都拒绝调用。"""
    raw = (os.environ.get(name) or "").strip() or default
    if raw is None:
        raise ModelUnavailable(f"未设置 {name}（美元/百万 token），为避免把真实账单记成 0，拒绝调用")
    try:
        v = float(raw)
    except ValueError:
        v = math.nan
    if not math.isfinite(v) or v < 0:
        raise ModelUnavailable(f"{name}={raw!r} 无效：必须是不小于 0 的有限数字，已拒绝调用")
    return v


def _call_limit():
    raw = os.environ.get("WORLDOS_MAX_CALLS_PER_DAY", "30")
    try:
        v = int(raw)
    except ValueError:
        v = -1
    if v < 0:
        raise ModelUnavailable(f"WORLDOS_MAX_CALLS_PER_DAY={raw!r} 无效：必须是不小于 0 的整数，已拒绝调用")
    return v


def estimate_cost(system, user, max_tokens, price_in, price_out):
    """单次调用的费用上限（美元）和输入 token 上限。

    输入按 UTF-8 字节数计：字节级分词（GPT、DeepSeek、Qwen 等）每个 token 至少 1 个字节，
    所以字节数不会少于 token 数；中文约高估 2–4 倍，宁可多算。输出按 max_tokens 计。
    """
    tin = len(system.encode("utf-8")) + len(user.encode("utf-8")) + MESSAGE_OVERHEAD_TOKENS
    return tin / 1e6 * price_in + max_tokens / 1e6 * price_out, tin


def _usage(data):
    """返回 (输入, 输出) token；缺失或格式不对时返回 None（用量未知）。"""
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None
    tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (tin, tout)):
        return None
    return tin, tout


def chat(conn, task, system, user, max_tokens=2000):
    prov = provider()
    if prov is None:
        raise ModelUnavailable("未配置模型")
    if prov not in ("openai", "mock"):
        raise ModelUnavailable(f"未知的 WORLDOS_LLM_PROVIDER={prov}")
    model = os.environ.get("WORLDOS_LLM_MODEL", "mock-deterministic" if prov == "mock" else "deepseek-flash")
    simulated = prov == "mock"
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("max_tokens 必须是正整数")
    limit = _call_limit()

    if not simulated:
        # 配置先全部校验，任何一项无效都不发请求
        pin, pout = _number("WORLDOS_PRICE_IN"), _number("WORLDOS_PRICE_OUT")
        budget = _number("WORLDOS_MONTHLY_BUDGET_USD", "25")
        try:
            url = os.environ["WORLDOS_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
            key = os.environ["WORLDOS_LLM_API_KEY"]
        except KeyError as e:
            raise ModelUnavailable(f"缺少环境变量 {e.args[0]}")
        est, tin_max = estimate_cost(system, user, max_tokens, pin, pout)
        spent = month_spend(conn)
        if spent + est > budget:
            _record(conn, task, prov, model, "blocked",
                    f"本月已计 ${spent:.4f} + 本次上限 ${est:.4f} 超过预算 ${budget:.2f}", est=est)
            raise BudgetExceeded(f"本月模型花费已计 ${spent:.4f}，本次调用最多 ${est:.4f}，"
                                 f"合计会超过预算 ${budget:.2f}，已停止新的收费请求")
    if calls_today(conn) >= limit:
        _record(conn, task, prov, model, "blocked", f"今日调用次数已达上限 {limit}")
        raise CallLimitExceeded(f"今日模型调用已达 {limit} 次上限，已停止调用")

    if simulated:
        text = _mock_response(user)
        tin, tout = len(system + user) // 2, len(text) // 2   # 粗略字符估算，仅供测试观察，不是账单
        _record(conn, task, prov, model, "ok", tin=tin, tout=tout, cost=0.0, simulated=True)
        return text

    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "temperature": 0.2,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    # 先按上限记账再发请求：程序中途退出时，这笔钱仍计入预算，状态留在 pending 待对账
    call_id = _record(conn, task, prov, model, "pending", cost=est, est=est, usage_known=False)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str):
            raise TypeError("choices[0].message.content 不是文本")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
        msg = f"{type(e).__name__}: {e}"
        # 请求可能已经被供应商处理并计费，无法得知：按上限计入预算，待对账
        _update(conn, call_id, status="error", error=(msg + "；是否计费未知，已按上限计入预算，待对账")[:500])
        raise ModelUnavailable(f"模型调用失败：{msg}")
    usage = _usage(data)
    if usage is None:
        _update(conn, call_id, status="ok", error="响应没有有效的 usage 用量，已按上限计入预算，待对账")
        return text
    tin, tout = usage
    cost = round(tin / 1e6 * pin + tout / 1e6 * pout, 6)
    note = None
    if tin > tin_max or tout > max_tokens:
        note = (f"实际用量（输入 {tin} / 输出 {tout}）超过预估上限（输入 {tin_max} / 输出 {max_tokens}），"
                "请核对供应商的计费方式")
    _update(conn, call_id, status="ok", input_tokens=tin, output_tokens=tout, cost_usd=cost, usage_known=1,
            error=note)
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
