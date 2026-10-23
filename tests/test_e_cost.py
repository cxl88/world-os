"""测试 E：成本控制。
预算检查（按单次费用上限预留）、配置校验、调用次数限制、模型不可用时降级、失败与缺用量按上限计入并待对账、
模拟用量不计入账单。
真实网络请求一律用 mock 替换，测试不会产生任何费用。
"""
import json
import os
import urllib.error
from unittest import mock

from worldos import llm

from .helpers import Base

REAL = {"WORLDOS_LLM_PROVIDER": "openai", "WORLDOS_LLM_BASE_URL": "https://api.example.invalid",
        "WORLDOS_LLM_API_KEY": "test-key-not-real", "WORLDOS_LLM_MODEL": "test-model",
        "WORLDOS_PRICE_IN": "0.30", "WORLDOS_PRICE_OUT": "1.20", "WORLDOS_MONTHLY_BUDGET_USD": "1"}

CARDS = json.dumps([{"name": "测试卡", "evidence": [{"item_id": 1, "claim": "c", "kind": "fact"}]}])


def fake_response(content, tin=1000, tout=500, usage=True):
    data = {"choices": [{"message": {"content": content}}]}
    if usage is True:
        data["usage"] = {"prompt_tokens": tin, "completion_tokens": tout}
    elif usage is not None:
        data["usage"] = usage
    m = mock.MagicMock()
    m.__enter__.return_value.read.return_value = json.dumps(data).encode()
    return m


def worst_case_response(req, timeout=None):
    """按估算前提下的最坏情况返回用量：输入 = 字节数 + 格式开销，输出 = max_tokens。"""
    body = json.loads(req.data)
    tin = sum(len(m["content"].encode("utf-8")) for m in body["messages"]) + llm.MESSAGE_OVERHEAD_TOKENS
    return fake_response(CARDS, tin, body["max_tokens"])


class RealProviderCostTest(Base):
    env = REAL

    def _items(self, n):
        for i in range(n):
            self.new_id("item-add", "--title", f"条目{i}", "--source", "s", "--url", f"https://ex.com/{i}")

    def test_budget_reserves_worst_case_before_calling(self):
        """预算闸门按“已花 + 本次上限”判断，而不是只看已花是否超过预算。"""
        os.environ.update(WORLDOS_PRICE_IN="1", WORLDOS_PRICE_OUT="1000", WORLDOS_MONTHLY_BUDGET_USD="5")
        self._items(3)
        # 每次实际：1000×1/1e6 + 1500×1000/1e6 = $1.501；每次上限约 $2.00（输出 2000 token）
        with mock.patch("urllib.request.urlopen", return_value=fake_response(CARDS, 1000, 1500)) as urlopen:
            self.ok("extract", "--ids", 1)
            self.ok("extract", "--ids", 2)
            spent = llm.month_spend(self.conn)
            self.assertAlmostEqual(spent, 3.002)
            # 已花 3.002 < 5，但 3.002 + 上限约 2.00 > 5：旧规则会放行，新规则拦截
            self.fails("extract", "--ids", 3, contains="已停止新的收费请求")
            self.assertEqual(urlopen.call_count, 2)
        rows = self.q("SELECT status, est_cost_usd, error FROM llm_calls ORDER BY id")
        self.assertEqual([r["status"] for r in rows], ["ok", "ok", "blocked"])
        self.assertGreater(rows[2]["est_cost_usd"], 5 - spent)
        self.assertIn("超过预算", rows[2]["error"])
        self.assertLessEqual(llm.month_spend(self.conn), 5)
        self.assertIsNone(self.scalar("SELECT processed_at FROM items WHERE id=3"))

    def test_spend_never_exceeds_budget_in_worst_case(self):
        os.environ.update(WORLDOS_PRICE_IN="1", WORLDOS_PRICE_OUT="1000", WORLDOS_MONTHLY_BUDGET_USD="7",
                          WORLDOS_MAX_CALLS_PER_DAY="100")
        self._items(6)
        with mock.patch("urllib.request.urlopen", side_effect=worst_case_response) as urlopen:
            results = [self.cli("extract", "--ids", i)[0] for i in range(1, 7)]
        self.assertEqual(results, [0, 0, 0, 1, 1, 1])
        self.assertEqual(urlopen.call_count, 3)
        rows = self.q("SELECT cost_usd, est_cost_usd FROM llm_calls WHERE status='ok'")
        for r in rows:   # 最坏情况下实际费用正好等于预估上限
            self.assertAlmostEqual(r["cost_usd"], r["est_cost_usd"], places=6)
        self.assertLessEqual(llm.month_spend(self.conn), 7)

    def test_daily_call_limit(self):
        os.environ["WORLDOS_MAX_CALLS_PER_DAY"] = "2"
        os.environ["WORLDOS_MONTHLY_BUDGET_USD"] = "100"
        self._items(3)
        with mock.patch("urllib.request.urlopen", return_value=fake_response(CARDS, 10, 10)) as urlopen:
            self.ok("extract", "--ids", 1)
            self.ok("extract", "--ids", 2)
            self.fails("extract", "--ids", 3, contains="上限")
            self.assertEqual(urlopen.call_count, 2)

    def test_invalid_price_budget_or_limit_refuses_call(self):
        self._items(1)
        cases = [("WORLDOS_PRICE_IN", "nan"), ("WORLDOS_PRICE_IN", "-0.1"), ("WORLDOS_PRICE_OUT", "inf"),
                 ("WORLDOS_PRICE_OUT", "abc"), ("WORLDOS_MONTHLY_BUDGET_USD", "NaN"),
                 ("WORLDOS_MONTHLY_BUDGET_USD", "-1"), ("WORLDOS_MONTHLY_BUDGET_USD", "Infinity"),
                 ("WORLDOS_MAX_CALLS_PER_DAY", "-1"), ("WORLDOS_MAX_CALLS_PER_DAY", "1.5")]
        for name, value in cases:
            with self.subTest(name=name, value=value), mock.patch.dict(os.environ, {name: value}), \
                    mock.patch("urllib.request.urlopen") as urlopen:
                o = self.ok("extract")
                urlopen.assert_not_called()
                self.assertIn(name, o)
                self.assertIn("无效", o)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM llm_calls"), 0)

    def test_missing_usage_is_charged_at_estimate_and_flagged(self):
        bad_usage = [None, {}, {"prompt_tokens": 10}, {"prompt_tokens": "10", "completion_tokens": 5},
                     {"prompt_tokens": -1, "completion_tokens": 5}, {"prompt_tokens": 1.5, "completion_tokens": 5}]
        self._items(len(bad_usage))
        for i, usage in enumerate(bad_usage, start=1):
            with self.subTest(usage=usage), \
                    mock.patch("urllib.request.urlopen", return_value=fake_response(CARDS, usage=usage)):
                self.ok("extract", "--ids", i)
                r = self.q("SELECT * FROM llm_calls ORDER BY id DESC LIMIT 1")[0]
                self.assertEqual((r["status"], r["usage_known"]), ("ok", 0))
                self.assertGreater(r["cost_usd"], 0)
                self.assertEqual(r["cost_usd"], r["est_cost_usd"])   # 不是 0，而是按上限计入
                self.assertIn("待对账", r["error"])
        ledger = llm.ledger(self.conn)
        self.assertEqual((ledger["unknown_n"], ledger["confirmed"]), (len(bad_usage), 0))
        self.assertAlmostEqual(ledger["spend"], self.scalar("SELECT SUM(est_cost_usd) FROM llm_calls"))
        self.assertIn("待对账", self.ok("cost"))
        self.assertIn("待对账", self.ok("brief"))

    def test_usage_above_estimate_is_recorded_and_flagged(self):
        self._items(1)
        with mock.patch("urllib.request.urlopen", return_value=fake_response(CARDS, 10, 5000)):
            self.ok("extract")
        r = self.q("SELECT * FROM llm_calls")[0]
        self.assertEqual((r["status"], r["usage_known"], r["output_tokens"]), ("ok", 1, 5000))
        self.assertAlmostEqual(r["cost_usd"], 10 * 0.30 / 1e6 + 5000 * 1.20 / 1e6)
        self.assertIn("超过预估上限", r["error"])

    def test_interrupted_call_stays_reserved(self):
        """请求发出后程序被中断：这笔调用保持 pending，按上限计入预算，不会被当成 0。"""
        self._items(1)
        with mock.patch("urllib.request.urlopen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cli("extract")
        r = self.q("SELECT * FROM llm_calls")[0]
        self.assertEqual((r["status"], r["usage_known"]), ("pending", 0))
        self.assertGreater(r["cost_usd"], 0)
        self.assertEqual(llm.month_spend(self.conn), r["cost_usd"])
        self.assertEqual(llm.calls_today(self.conn), 1)

    def test_model_failure_is_recorded_and_degrades(self):
        self._items(1)
        err = urllib.error.URLError("connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            o = self.ok("extract")
        self.assertIn("手动模式（模型调用失败", o)
        self.assertEqual(len(os.listdir(os.path.join(self.dir, "prompts"))), 1)
        row = self.q("SELECT * FROM llm_calls")[0]
        self.assertEqual((row["status"], row["usage_known"], row["simulated"]), ("error", 0, 0))
        # 失败的请求是否被计费无法得知：按上限计入预算并标记待对账，而不是记 0
        self.assertGreater(row["cost_usd"], 0)
        self.assertEqual(row["cost_usd"], row["est_cost_usd"])
        self.assertIn("connection refused", row["error"])
        self.assertIn("待对账", row["error"])
        self.assertIsNone(self.scalar("SELECT processed_at FROM items"))
        self.assertIn("失败或被拦截 1 次", self.ok("brief"))

    def test_bad_model_json_saved_not_imported(self):
        self._items(1)
        with mock.patch("urllib.request.urlopen", return_value=fake_response("这不是 JSON", 10, 10)):
            e = self.fails("extract", contains="原文已保存")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM cards"), 0)
        self.assertIsNone(self.scalar("SELECT processed_at FROM items"))
        self.assertTrue(any(f.startswith("failed-response") for f in os.listdir(os.path.join(self.dir, "prompts"))))
        self.assertIn("JSON 格式错误", e)

    def test_missing_price_refuses_paid_call(self):
        os.environ.pop("WORLDOS_PRICE_IN")
        self._items(1)
        with mock.patch("urllib.request.urlopen") as urlopen:
            o = self.ok("extract")
            urlopen.assert_not_called()
        self.assertIn("WORLDOS_PRICE_IN", o)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM llm_calls"), 0)


class MockCostTest(Base):
    env = {"WORLDOS_LLM_PROVIDER": "mock", "WORLDOS_MONTHLY_BUDGET_USD": "0", "WORLDOS_MAX_CALLS_PER_DAY": "2"}

    def test_mock_usage_is_not_billed(self):
        for i in range(3):
            self.new_id("item-add", "--title", f"条目{i}", "--source", "s")
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.ok("extract", "--ids", 1)           # 预算为 0 也能跑：模拟调用不收费
            urlopen.assert_not_called()
        row = self.q("SELECT * FROM llm_calls")[0]
        self.assertEqual((row["simulated"], row["cost_usd"]), (1, 0))
        self.assertGreater(row["input_tokens"], 0)
        self.assertEqual(llm.month_spend(self.conn), 0)
        cost = self.ok("cost")
        self.assertIn("模拟(不计费)", cost)
        self.assertIn("本月真实花费合计 $0.0000", cost)
        self.assertIn("真实模型调用 0 次", self.ok("brief"))
        self.ok("extract", "--ids", 2)
        self.fails("extract", "--ids", 3, contains="上限")   # 次数上限同样生效
