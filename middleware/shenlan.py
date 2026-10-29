"""深澜(Srun)认证计费系统 MySQL 连接器。

直连深澜后台数据库，按可配置的表名与列映射拉取在线/认证记录到本地 SQLite。
列映射在 Web 设置页配置，默认字段名即常见命名；若深澜表字段不同，改 mapping 即可。
"""
import pymysql
from .config import load_config
from .db import replace_shenlan
from . import timeutil


def _connect_source(s):
    return pymysql.connect(
        host=s.get("host"),
        port=int(s.get("port") or 3306),
        user=s.get("user"),
        password=s.get("password"),
        database=s.get("database"),
        charset="utf8mb4",
        connect_timeout=10,
        cursorclass=pymysql.cursors.Cursor,
    )


def _connect(cfg):
    return _connect_source(cfg["shenlan"])


def list_tables(cfg=None):
    cfg = cfg or load_config()
    conn = _connect(cfg)
    try:
        c = conn.cursor()
        c.execute("SHOW TABLES")
        return [row[0] for row in c.fetchall()]
    finally:
        conn.close()


def list_columns(table, cfg=None):
    cfg = cfg or load_config()
    conn = _connect(cfg)
    try:
        c = conn.cursor()
        c.execute("SHOW COLUMNS FROM `%s`" % table)
        return [row[0] for row in c.fetchall()]
    finally:
        conn.close()


def _as_str(v):
    return "" if v is None else str(v).strip()


def _sync_source(source_cfg, replace_fn):
    """通用同步：查询某数据源(在线/离线) -> 规范化 -> 写入本地 -> 返回统计。"""
    s = source_cfg
    custom = (s.get("custom_sql") or "").strip()
    if not (s.get("host") and s.get("database") and (s.get("table") or custom)):
        raise ValueError("深澜连接未配置完整（host/database/table 必填，或填写自定义SQL）")
    m = s["mapping"]
    if custom:
        sql = custom
    else:
        if not s["table"]:
            raise ValueError("深澜连接未配置完整（host/database/table 必填，或填写自定义SQL）")
        cols = [m["account"], m["name"], m["ip"], m["mac"], m["online_time"]]
        if m.get("offline_time"):
            cols.append(m["offline_time"])
        sel = ",".join("`%s`" % c for c in cols)
        sql = "SELECT %s FROM `%s`" % (sel, s["table"])
        if s.get("where"):
            sql += " WHERE " + s["where"]

    conn = _connect_source(s)
    try:
        c = conn.cursor()
        c.execute(sql)
        rows = c.fetchall()
        desc = [d[0] for d in c.description]
    finally:
        conn.close()

    records = []
    for row in rows:
        if custom:
            d = dict(zip(desc, row))
            rec = {
                "account": _as_str(d.get("account")),
                "name": _as_str(d.get("name")),
                "ip": _as_str(d.get("ip")),
                "mac": _as_str(d.get("mac")),
                "online_time": timeutil.normalize_time(d.get("online_time")),
                "offline_time": timeutil.normalize_time(d.get("offline_time")),
                "contact": _as_str(d.get("contact")),
            }
        else:
            d = dict(zip(cols, row))
            rec = {
                "account": _as_str(d.get(m["account"])),
                "name": _as_str(d.get(m["name"])),
                "ip": _as_str(d.get(m["ip"])),
                "mac": _as_str(d.get(m["mac"])),
                "online_time": timeutil.normalize_time(d.get(m["online_time"])),
                "offline_time": (
                    timeutil.normalize_time(d.get(m["offline_time"]))
                    if m.get("offline_time")
                    else None
                ),
                "contact": (
                    _as_str(d.get(m["contact"])) if m.get("contact") else ""
                ),
            }
        if rec["ip"]:
            records.append(rec)

    from datetime import datetime

    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    replace_fn(records, synced_at)
    return {"count": len(records), "synced_at": synced_at, "sample": records[:5]}


def sync_now(cfg=None):
    """在线数据源同步（深澜当前在线快照）。"""
    cfg = cfg or load_config()
    return _sync_source(cfg["shenlan"], replace_shenlan)


def sync_offline(cfg=None):
    """离线 / 上网明细数据源同步（直连模式；也可改为上传文件）。"""
    cfg = cfg or load_config()
    return _sync_source(cfg["offline"], replace_shenlan_offline)


def _base_account(account):
    """账号可能带 @realm 后缀（如 2302111@Ncce），取 @ 之前的主账号用于关联 users 表。"""
    a = (account or "").strip()
    if "@" in a:
        return a.split("@", 1)[0]
    return a


def enrich_contacts_from_users(records, source_cfg=None):
    """用深澜 users 表按账号补全 真实姓名 / 联系人电话。

    离线明细(上网明细导出)通常只含账号/IP/MAC/上下线时间，不含电话；
    此处借助与在线源相同的深澜库（users 表）按账号关联 phone / user_real_name。
    返回 (records, enriched_count)。无数据库或查询失败时返回原记录、enriched=0。
    """
    if not records:
        return records, 0
    cfg = load_config()
    s = source_cfg or cfg["shenlan"]
    if not (s.get("host") and s.get("database") and s.get("user")):
        return records, 0
    # 收集所有主账号
    bases = set()
    for r in records:
        b = _base_account(r.get("account"))
        if b:
            bases.add(b)
    if not bases:
        return records, 0
    try:
        conn = _connect_source(s)
    except Exception:
        return records, 0
    try:
        c = conn.cursor()
        fmt = ",".join("%s" for _ in bases)
        c.execute(
            "SELECT user_name, user_real_name, phone FROM users WHERE user_name IN (%s)" % fmt,
            tuple(bases),
        )
        info = {row[0]: (row[1], row[2]) for row in c.fetchall()}
    except Exception:
        conn.close()
        return records, 0
    finally:
        try:
            conn.close()
        except Exception:
            pass

    enriched = 0
    for r in records:
        b = _base_account(r.get("account"))
        if b and b in info:
            real_name, phone = info[b]
            if not r.get("contact") and phone:
                r["contact"] = _as_str(phone)
                enriched += 1
            if not r.get("name") and real_name:
                r["name"] = _as_str(real_name)
                enriched += 1
    return records, enriched
