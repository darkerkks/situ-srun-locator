"""本地 SQLite 存储：深澜快照、态势感知上传、匹配结果。"""
import sqlite3
import json
import os
from .config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS shenlan_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT, name TEXT, ip TEXT, mac TEXT,
            online_time TEXT, offline_time TEXT, contact TEXT,
            raw TEXT, synced_at TEXT
        );
        CREATE TABLE IF NOT EXISTS shenlan_offline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT, name TEXT, ip TEXT, mac TEXT,
            online_time TEXT, offline_time TEXT, contact TEXT,
            raw TEXT, synced_at TEXT
        );
        CREATE TABLE IF NOT EXISTS situational_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT, src_ip TEXT, dst_ip TEXT, time TEXT,
            alert TEXT, threat TEXT, result TEXT, src_port TEXT, dst_port TEXT,
            status TEXT, raw TEXT, uploaded_at TEXT
        );
        CREATE TABLE IF NOT EXISTS match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT, ip TEXT, time TEXT,
            matched_account TEXT, matched_name TEXT, matched_mac TEXT,
            matched_contact TEXT, matched_source TEXT,
            online_time TEXT, offline_time TEXT,
            confidence TEXT, note TEXT, candidates TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_shenlan_ip ON shenlan_records(ip);
        CREATE INDEX IF NOT EXISTS idx_situ_batch ON situational_records(batch_id);
        CREATE INDEX IF NOT EXISTS idx_match_batch ON match_results(batch_id);
        """
    )
    conn.commit()
    _ensure_columns()
    conn.close()


def _ensure_columns():
    """为已存在的库表补充新增列（contact / matched_contact）。"""
    conn = get_conn()
    c = conn.cursor()
    for table, col in (
        ("shenlan_records", "contact"),
        ("match_results", "matched_contact"),
        ("match_results", "matched_source"),
    ):
        names = [r[1] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()]
        if col not in names:
            c.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (table, col))
    conn.commit()
    conn.close()


def replace_shenlan(records, synced_at):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM shenlan_records")
    for r in records:
        c.execute(
            "INSERT INTO shenlan_records (account,name,ip,mac,online_time,offline_time,contact,raw,synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r.get("account"),
                r.get("name"),
                r.get("ip"),
                r.get("mac"),
                r.get("online_time"),
                r.get("offline_time"),
                r.get("contact", ""),
                json.dumps(r, ensure_ascii=False),
                synced_at,
            ),
        )
    conn.commit()
    conn.close()


def insert_situational(records, batch_id, uploaded_at):
    conn = get_conn()
    c = conn.cursor()
    for r in records:
        c.execute(
            "INSERT INTO situational_records "
            "(batch_id,src_ip,dst_ip,time,alert,threat,result,src_port,dst_port,status,raw,uploaded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                r.get("src_ip"),
                r.get("dst_ip"),
                r.get("time"),
                r.get("alert"),
                r.get("threat"),
                r.get("result"),
                r.get("src_port"),
                r.get("dst_port"),
                r.get("status"),
                json.dumps(r, ensure_ascii=False),
                uploaded_at,
            ),
        )
    conn.commit()
    conn.close()


def insert_match_results(results, batch_id, created_at):
    conn = get_conn()
    c = conn.cursor()
    for r in results:
        c.execute(
            "INSERT INTO match_results "
            "(batch_id,ip,time,matched_account,matched_name,matched_mac,matched_contact,matched_source,online_time,offline_time,confidence,note,candidates,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                r.get("ip"),
                r.get("time"),
                r.get("matched_account"),
                r.get("matched_name"),
                r.get("matched_mac"),
                r.get("matched_contact"),
                r.get("matched_source"),
                r.get("online_time"),
                r.get("offline_time"),
                r.get("confidence"),
                r.get("note"),
                json.dumps(r.get("candidates", []), ensure_ascii=False),
                created_at,
            ),
        )
    conn.commit()
    conn.close()


def get_shenlan():
    conn = get_conn()
    rows = conn.execute(
        "SELECT account,name,ip,mac,online_time,offline_time,contact FROM shenlan_records"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- 离线 / 上网明细 数据源 ----------------
def replace_shenlan_offline(records, synced_at):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM shenlan_offline")
    for r in records:
        c.execute(
            "INSERT INTO shenlan_offline (account,name,ip,mac,online_time,offline_time,contact,raw,synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r.get("account"),
                r.get("name"),
                r.get("ip"),
                r.get("mac"),
                r.get("online_time"),
                r.get("offline_time"),
                r.get("contact", ""),
                json.dumps(r, ensure_ascii=False),
                synced_at,
            ),
        )
    conn.commit()
    conn.close()


def get_shenlan_offline():
    conn = get_conn()
    rows = conn.execute(
        "SELECT account,name,ip,mac,online_time,offline_time,contact FROM shenlan_offline"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def offline_count():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM shenlan_offline").fetchone()[0]
    conn.close()
    return n


def latest_offline_sync_at():
    conn = get_conn()
    r = conn.execute("SELECT MAX(synced_at) FROM shenlan_offline").fetchone()
    conn.close()
    return r[0] if r else None


def get_shenlan_combined():
    """合并在线 + 离线两份数据源，并打上 source 标签供匹配引擎区分。"""
    out = []
    for r in get_shenlan():
        r = dict(r)
        r["source"] = "online"
        out.append(r)
    for r in get_shenlan_offline():
        r = dict(r)
        r["source"] = "offline"
        out.append(r)
    return out


def get_situational(batch_id=None):
    conn = get_conn()
    if batch_id:
        rows = conn.execute(
            "SELECT * FROM situational_records WHERE batch_id=? ORDER BY id", (batch_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM situational_records ORDER BY id DESC LIMIT 5000"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_match_results(batch_id=None):
    conn = get_conn()
    if batch_id:
        rows = conn.execute(
            "SELECT * FROM match_results WHERE batch_id=? ORDER BY id", (batch_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM match_results ORDER BY id DESC LIMIT 5000"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def distinct_batches():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT batch_id FROM situational_records ORDER BY batch_id DESC"
    ).fetchall()
    conn.close()
    return [r["batch_id"] for r in rows]


def shenlan_count():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM shenlan_records").fetchone()[0]
    conn.close()
    return n


def latest_sync_at():
    conn = get_conn()
    r = conn.execute("SELECT MAX(synced_at) FROM shenlan_records").fetchone()
    conn.close()
    return r[0] if r else None
