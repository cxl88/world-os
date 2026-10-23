"""导出、备份、恢复。"""
import json
import os
import shutil
import sqlite3
from datetime import datetime

from . import db


def export(conn, out_dir, card_markdown):
    os.makedirs(os.path.join(out_dir, "cards"), exist_ok=True)
    data = db.dump(conn)
    with open(os.path.join(out_dir, "worldos.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    for c in conn.execute("SELECT * FROM cards ORDER BY id"):
        with open(os.path.join(out_dir, "cards", f"{c['id']:04d}.md"), "w", encoding="utf-8") as f:
            f.write(card_markdown(conn, c) + "\n")
    return {t: len(rows) for t, rows in data.items()}


def backup(conn, data_dir):
    folder = os.path.join(data_dir, "backups")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"worldos-{datetime.now():%Y%m%d-%H%M%S-%f}.db")
    dst = sqlite3.connect(path)
    with dst:
        conn.backup(dst)
    dst.close()
    return path


def restore(backup_path, db_path, force=False):
    """用备份覆盖当前数据库。覆盖前先把当前库另存一份。返回 (恢复后的行数统计, 覆盖前的安全副本路径)。"""
    if not os.path.isfile(backup_path):
        raise ValueError(f"备份文件不存在：{backup_path}")
    src = sqlite3.connect(f"file:{os.path.abspath(backup_path)}?mode=ro", uri=True)
    try:
        ok = src.execute("PRAGMA integrity_check").fetchone()[0]
        version = src.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as e:
        src.close()
        raise ValueError(f"不是有效的 SQLite 备份：{e}")
    if ok != "ok" or version != db.SCHEMA_VERSION:
        src.close()
        raise ValueError(f"备份校验失败（integrity={ok}，版本={version}）")
    safety = None
    if os.path.exists(db_path):
        if not force:
            src.close()
            raise ValueError(f"{db_path} 已存在。确认覆盖请加 --force（会先自动另存一份当前数据库）")
        safety = db_path + f".before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}"
        shutil.copy2(db_path, safety)
    dst = sqlite3.connect(db_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    conn = db.connect(db_path)
    counts = {t: len(rows) for t, rows in db.dump(conn).items()}
    conn.close()
    return counts, safety
