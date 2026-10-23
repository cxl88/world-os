"""测试 E：成本控制。
预算检查、调用次数限制、模型不可用时降级、失败记录、超预算停止收费请求、模拟用量不计入账单。
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


def fake_response(content, tin=1_000_000, tout=500_000):
    body = json.dumps({"choices": [{"message": {"content": content}}],
                       "usage": {"prompt_tokens": tin, "completion_tokens": tout}}).encode()
    m = mock.MagicMock()
    m.__enter__.return_value.read.return_value = body
    return m


class RealProviderCostTest(Base):
    env = REAL

    def _items(self, n):
        for i in range(n):
            self.new_id("item-add", "--title", f"条目{i}", "--source", "s", "--url", f"https://ex.com/{i}")

    def test_budget_stops_new_paid_requests(self):
        self._items(3)
        with mock.patch("urllib.request.urlopen", return_value=fake_response(CARDS)) as urlopen:
            self.ok("extract", "--ids", 1)
            self.assertAlmostEqual(llm.month_spend(self.conn), 0.9)   # 1M×0.3 + 0.5M×1.2
            self.ok("extract", "--ids", 2)                            # 0.9 < 1，允许；之后 1.8
            self.fail("extract", "--ids", 3, contains="已停止新的收费请求")
            self.assertEqual(urlopen.call_count, 2)                   # 超预算后没有再发请求
        statuses = [r[0] for r in self.q("SELECT status FROM llm_calls ORDER BY id")]
        self.assertEqual(statuses, ["ok", "ok", "blocked"])
        self.assertIsNone(self.scalar("SELECT processed_at FROM items WHERE id=3"))

    def test_daily_call_limit(self):
        os.environ["WORLDOS_MAX_CALLS_PER_DAY"] = "2"
        os.environ["WORLDOS_MONTHLY_BUDGET_USD"] = "100"
        self._items(3)
        with mock.patch("urllib.request.urlopen", return_value=fake_response(CARDS, 10, 10)) as urlopen:
            self.ok("extract", "--ids", 1)
            self.ok("extract", "--ids", 2)
            self.fail("extract", "--ids", 3, contains="上限")
            self.assertEqual(urlopen.call_count, 2)

    def test_model_failure_is_recorded_and_degrades(self):
        self._items(1)
        err = urllib.error.URLError("connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            o = self.ok("extract")
        self.assertIn("手动模式（模型调用失败", o)
        self.assertEqual(len(os.listdir(os.path.join(self.dir, "prompts"))), 1)
        row = self.q("SELECT * FROM llm_calls")[0]
        self.assertEqual((row["status"], row["cost_usd"], row["simulated"]), ("error", 0, 0))
        self.assertIn("connection refused", row["error"])
        self.assertIsNone(self.scalar("SELECT processed_at FROM items"))
        self.assertIn("失败或被拦截 1 次", self.ok("brief"))

    def test_bad_model_json_saved_not_imported(self):
        self._items(1)
        with mock.patch("urllib.request.urlopen", return_value=fake_response("这不是 JSON", 10, 10)):
            e = self.fail("extract", contains="原文已保存")
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
        self.fail("extract", "--ids", 3, contains="上限")   # 次数上限同样生效
