"""测试 G：数据安全。导出、备份、从备份恢复的一致性。"""
import json
import os
import sqlite3

from worldos import backup, db

from .helpers import Base


class DataSafetyTest(Base):
    def _populate(self):
        iid = self.new_id("item-add", "--title", "【演示数据】中文标题", "--source", "演示", "--url", "https://a.com")
        cid = self.new_id("card-add", "--name", "【演示数据】卡片", "--problem", "含换行\n和引号\"'")
        self.new_id("evidence-add", cid, "--type", "public", "--claim", "c", "--url", "https://a.com",
                    "--item", iid, "--verified")
        self.new_id("score", cid, "--pain", 2, "--access", 3, "--feasibility", 4, "--reuse", 3, "--risk", 2,
                    "--basis", "演示")
        self.new_id("action-add", cid, "--title", "行动")
        self.new_id("log", "quote", "--card", cid, "--who", "客户甲", "--amount", 1234.5)
        return cid

    def test_export_matches_database(self):
        cid = self._populate()
        out = os.path.join(self.dir, "导出")
        self.ok("export", "--out", out)
        with open(os.path.join(out, "worldos.json"), encoding="utf-8") as f:
            exported = json.load(f)
        self.assertEqual(exported, json.loads(json.dumps(db.dump(self.conn))))
        with open(os.path.join(out, "cards", f"{cid:04d}.md"), encoding="utf-8") as f:
            self.assertIn("【演示数据】卡片", f.read())

    def test_backup_and_restore_roundtrip(self):
        self._populate()
        before = db.dump(self.conn)
        backup_path = self._porcelain("backup")[1].strip()
        self.assertTrue(os.path.isfile(backup_path))
        self.assertTrue(backup_path.startswith(os.path.join(self.dir, "backups")))
        # 备份后继续写入，再恢复：应回到备份时的状态
        self.new_id("item-add", "--title", "备份后新增", "--source", "s")
        self.fails("restore", backup_path, contains="--force")
        o = self.ok("restore", backup_path, "--force")
        self.assertIn("原数据库已另存为", o)
        self.conn.close()
        self.conn = db.connect(self.path)
        self.assertEqual(db.dump(self.conn), before)
        safety = [f for f in os.listdir(self.dir) if ".before-restore-" in f]
        self.assertEqual(len(safety), 1)
        # 安全副本里保留了恢复前的那条新增数据
        s = sqlite3.connect(os.path.join(self.dir, safety[0]))
        self.assertEqual(s.execute("SELECT COUNT(*) FROM items WHERE title='备份后新增'").fetchone()[0], 1)
        s.close()

    def test_restore_into_new_location(self):
        self._populate()
        backup_path = self._porcelain("backup")[1].strip()
        target = os.path.join(self.dir, "新机器", "worldos.db")
        os.makedirs(os.path.dirname(target))
        from worldos import cli
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--db", target, "restore", backup_path]), 0)
        c2 = db.connect(target)
        self.assertEqual(db.dump(c2), db.dump(self.conn))
        c2.close()

    def test_restore_rejects_garbage(self):
        bad = os.path.join(self.dir, "坏文件.db")
        with open(bad, "wb") as f:
            f.write(b"not a database" * 100)
        self.fails("restore", bad, "--force", contains="SQLite")
        self.fails("restore", os.path.join(self.dir, "不存在.db"), contains="不存在")

    def test_old_schema_is_refused(self):
        old = os.path.join(self.dir, "old.db")
        c = sqlite3.connect(old)
        c.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
        c.commit(); c.close()
        from worldos import cli
        import io
        from contextlib import redirect_stderr
        e = io.StringIO()
        with redirect_stderr(e):
            self.assertEqual(cli.main(["--db", old, "cards"]), 1)
        self.assertIn("旧版结构", e.getvalue())

    def test_v2_database_is_upgraded(self):
        """版本 2 的数据库（上一轮 v0.2.0 测试版）打开时自动升级到当前版本，原有数据保留。"""
        v2_llm_calls = """CREATE TABLE llm_calls (
          id INTEGER PRIMARY KEY, task TEXT, provider TEXT, model TEXT, status TEXT NOT NULL, error TEXT,
          input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0,
          simulated INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);"""
        old = os.path.join(self.dir, "v2.db")
        c = sqlite3.connect(old)
        c.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS llm_calls")[0] + v2_llm_calls)
        c.executemany("INSERT INTO llm_calls (task, provider, model, status, cost_usd, created_at) "
                      "VALUES ('extract', 'openai', 'm', ?, ?, '2026-10-01T00:00:00+08:00')",
                      [("ok", 0.01), ("error", 0)])
        c.execute("INSERT INTO items (title, source, added_at) VALUES ('旧条目', 's', '2026-10-01')")
        c.execute("PRAGMA user_version = 2")
        c.commit(); c.close()
        # 备份文件可以是版本 2，恢复后同样升级
        restored = os.path.join(self.dir, "restored.db")
        counts, _ = backup.restore(old, restored)
        self.assertEqual((counts["items"], counts["llm_calls"]), (1, 2))
        for path in (old, restored):
            conn = db.connect(path)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            rows = conn.execute("SELECT status, usage_known, est_cost_usd FROM llm_calls ORDER BY id").fetchall()
            # 旧版失败调用记的 0 元不可信：升级后标为用量未知、待对账
            self.assertEqual([tuple(r) for r in rows], [("ok", 1, None), ("error", 0, None)])
            self.assertEqual(conn.execute("SELECT title FROM items").fetchone()[0], "旧条目")
            conn.close()
