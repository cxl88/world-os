"""测试 G：数据安全。导出、备份、从备份恢复的一致性。"""
import json
import os
import sqlite3

from worldos import db

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
        self.fail("restore", backup_path, contains="--force")
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
        self.fail("restore", bad, "--force", contains="SQLite")
        self.fail("restore", os.path.join(self.dir, "不存在.db"), contains="不存在")

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
