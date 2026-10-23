"""测试 A：无 AI 服务。
信息录入 → 手动创建 Bug → 添加证据 → 评分 → 创建行动 → 记录反馈 → 生成简报。
"""
import os

from worldos import llm

from .helpers import Base


class ManualFlowTest(Base):
    def test_full_loop_without_model(self):
        self.assertIsNone(llm.provider(), "测试环境不应配置任何模型")
        iid = self.new_id("item-add", "--title", "【演示数据】某工厂仍每月人工抄表", "--source", "演示：朋友口述",
                          "--cred", "B", "--published", "2026-10-01")
        cid = self.new_id("card-add", "--name", "【演示数据】抄表自动化", "--bug-type", "流程",
                          "--payers", "中小工厂设备科（假设）", "--kill-condition", "5 家里少于 2 家愿意付费试点")
        self.new_id("evidence-add", cid, "--type", "public", "--claim", "行业报告提到人工抄表普遍",
                    "--url", "https://example.com/report", "--item", iid, "--verified")
        self.new_id("log", "interview", "--card", cid, "--who", "工厂A", "--note", "演示",
                    "--claim", "设备科长说每月抄表 2 人天")
        self.new_id("log", "interview", "--card", cid, "--who", "工厂B", "--claim", "也在手工抄表")
        o = self.ok("score", cid, "--pain", 4, "--access", 3, "--feasibility", 4, "--reuse", 3, "--risk", 4,
                    "--basis", "两家工厂亲口确认手工抄表，尚无报价")
        # 两个独立客户自述 → T2 封顶 75；只有客户自述 → 痛点最多 3
        self.assertIn("痛点分由 4 降为 3", o)
        self.assertIn("记录 66.0 分", o)
        self.ok("status", cid, "researching")
        self.ok("status", cid, "validating")
        aid = self.new_id("action-add", cid, "--title", "拜访 3 家工厂", "--hypothesis", "愿付 3000 元试点",
                          "--acceptance", "至少 1 家给出书面报价意向", "--due", "2000-01-01", "--minutes", 240)
        self.new_id("log", "time", "--category", "build", "--minutes", 300)
        text = self.ok("brief")
        self.assertIn("抄表自动化", text)
        self.assertIn("拜访 3 家工厂", text)
        self.assertIn("已过期", text)
        self.assertIn("开发时间超过触达", text)
        self.assertIn("T2 一手资料或客户自述", text)
        self.assertIn("成交状态：未成交", text)
        self.ok("action-done", aid, "--result", "1 家愿意聊报价", "--decision", "continue")
        self.assertEqual(self.scalar("SELECT status FROM actions WHERE id=?", aid), "done")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM llm_calls"), 0)

    def test_extract_without_model_degrades_to_prompt_file(self):
        self.new_id("item-add", "--title", "x", "--source", "s", "--url", "https://ex.com/1")
        o = self.ok("extract")
        self.assertIn("手动模式（未配置模型）", o)
        files = os.listdir(os.path.join(self.dir, "prompts"))
        self.assertEqual(len(files), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM llm_calls"), 0)
        self.assertIsNone(self.scalar("SELECT processed_at FROM items"))
