"""Bug 提取：组装提示词、调用模型或降级为手动模式、校验并导入模型输出。

模型输出只被当作“候选数据”：
  - 只保留机会卡的已知字段，其他字段（审核状态、评分、证据等级、状态、发送动作等）一律丢弃；
  - 证据必须引用本次提供的 item_id，链接取自原始条目，不信任模型给的链接；
  - 证据类型一律记为 AI 推断、未核实；卡片一律待人工审核；
  - 校验全部通过才写库，任何错误整体回滚。
"""
import os
from datetime import datetime

from . import cards, db, evidence, llm, prompts

MAX_CARDS = 3
MAX_FIELD_LEN = 2000


def select_items(conn, ids=None, limit=10):
    if ids:
        rows = conn.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id",
                            ids).fetchall()
        missing = set(ids) - {r["id"] for r in rows}
        if missing:
            raise ValueError(f"信息不存在：{sorted(missing)}")
        return rows
    return conn.execute("SELECT * FROM items WHERE processed_at IS NULL ORDER BY id LIMIT ?", (limit,)).fetchall()


def build_prompt(rows, profile):
    return prompts.EXTRACT_SYSTEM, prompts.EXTRACT_USER.format(
        profile=profile, items="\n\n".join(prompts.format_item(r) for r in rows))


def write_manual_prompt(data_dir, system, user):
    folder = os.path.join(data_dir, "prompts")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"extract-{datetime.now():%Y%m%d-%H%M%S-%f}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"## 系统提示\n\n{system}\n\n## 用户输入\n\n{user}\n")
    return path


def validate(raw, allowed_item_ids):
    """返回 (干净的卡片列表, 警告列表)。结构错误抛 ValueError。"""
    warnings = []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("模型输出必须是 JSON 数组")
    if len(raw) > MAX_CARDS:
        warnings.append(f"模型返回 {len(raw)} 张卡，只保留前 {MAX_CARDS} 张")
        raw = raw[:MAX_CARDS]
    clean = []
    for n, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            raise ValueError(f"第 {n} 张卡不是 JSON 对象")
        extra = sorted(set(c) - set(cards.FIELDS) - {"evidence"})
        if extra:
            warnings.append(f"第 {n} 张卡含非法字段，已忽略：{', '.join(extra)}")
        card = {}
        for k in cards.FIELDS:
            v = c.get(k)
            if v is None:
                continue
            if not isinstance(v, (str, int, float)):
                warnings.append(f"第 {n} 张卡字段 {k} 不是文本，已忽略")
                continue
            card[k] = str(v).strip()[:MAX_FIELD_LEN]
        if not card.get("name"):
            raise ValueError(f"第 {n} 张卡缺少 name")
        if card.get("bug_type") not in cards.BUG_TYPES:
            if card.get("bug_type"):
                warnings.append(f"第 {n} 张卡 bug_type「{card['bug_type']}」不在允许范围，改为未分类")
            card["bug_type"] = "未分类"
        evs = c.get("evidence") or []
        if not isinstance(evs, list):
            raise ValueError(f"第 {n} 张卡的 evidence 必须是数组")
        card["evidence"] = []
        for e in evs:
            if not isinstance(e, dict) or not str(e.get("claim") or "").strip():
                warnings.append(f"第 {n} 张卡有一条证据缺少 claim，已丢弃")
                continue
            try:
                item_id = int(e.get("item_id"))
            except (TypeError, ValueError):
                item_id = None
            if item_id not in allowed_item_ids:
                warnings.append(f"第 {n} 张卡有证据引用了未提供的 item_id={e.get('item_id')!r}，已丢弃")
                continue
            ignored = sorted(set(e) - {"item_id", "claim", "kind"})
            if ignored:
                warnings.append(f"第 {n} 张卡证据含字段 {', '.join(ignored)}，已忽略（证据类型与核实状态只能由人设定）")
            kind = e.get("kind") if e.get("kind") in evidence.KINDS else "inference"
            card["evidence"].append({"item_id": item_id, "claim": str(e["claim"]).strip()[:MAX_FIELD_LEN],
                                     "kind": kind})
        clean.append(card)
    return clean, warnings


def import_cards(conn, raw, allowed_item_ids, origin):
    """校验并在一个事务里导入。返回 (新卡 id 列表, 警告)。"""
    clean, warnings = validate(raw, set(allowed_item_ids))
    ids = []
    try:
        for c in clean:
            cid = cards.create(conn, c, origin=origin, commit=False)
            for e in c["evidence"]:
                item = conn.execute("SELECT url, published_at FROM items WHERE id=?", (e["item_id"],)).fetchone()
                evidence.add(conn, cid, "ai_inference", e["claim"], kind=e["kind"], url=item["url"],
                             item_id=e["item_id"], observed_at=item["published_at"], origin=origin, commit=False)
            ids.append(cid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ids, warnings


def mark_processed(conn, ids):
    conn.executemany("UPDATE items SET processed_at=? WHERE id=?", [(db.now(), i) for i in ids])
    conn.commit()


def run(conn, data_dir, profile, ids=None, limit=10, manual=False):
    """返回 dict(mode=manual|model, prompt_path?, card_ids?, warnings, reason?)。"""
    rows = select_items(conn, ids, limit)
    if not rows:
        return {"mode": "none", "warnings": []}
    system, user = build_prompt(rows, profile)
    item_ids = [r["id"] for r in rows]
    if manual:
        return {"mode": "manual", "prompt_path": write_manual_prompt(data_dir, system, user),
                "item_ids": item_ids, "warnings": [], "reason": "手动模式"}
    try:
        text = llm.chat(conn, "extract", system, user)
    except llm.ModelUnavailable as e:
        return {"mode": "manual", "prompt_path": write_manual_prompt(data_dir, system, user),
                "item_ids": item_ids, "warnings": [], "reason": str(e)}
    origin = "ai-mock" if llm.provider() == "mock" else "ai"
    try:
        parsed = llm.parse_json(text)
        card_ids, warnings = import_cards(conn, parsed, item_ids, origin)
    except ValueError as e:
        folder = os.path.join(data_dir, "prompts")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"failed-response-{datetime.now():%Y%m%d-%H%M%S-%f}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        raise ValueError(f"模型输出无法导入（{e}），原文已保存到 {path}，信息未标记为已处理")
    mark_processed(conn, item_ids)
    return {"mode": "model", "card_ids": card_ids, "item_ids": item_ids, "warnings": warnings, "origin": origin}
