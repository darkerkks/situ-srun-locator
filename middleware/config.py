"""配置文件读写：config.json 保存在项目根目录，含深澜连接、列映射、匹配窗口等。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # situ-middleware/
CONFIG_PATH = os.path.join(ROOT, "config.json")
DB_PATH = os.path.join(ROOT, "data.db")

def _shenlan_default():
    """深澜数据源默认配置（在线 / 离线共用同一套结构）。"""
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 3306,
        "user": "",
        "password": "",
        "database": "",
        "table": "",
        "mapping": {
            "account": "account",      # 账号
            "name": "name",            # 用户姓名
            "ip": "ip",                # IP地址
            "mac": "mac",              # MAC地址
            "online_time": "online_time",    # 上线时间
            "offline_time": "offline_time"   # 下线时间(可空)
        },
        "where": "",   # 可选的额外 WHERE 条件，例如只取某产品/分组
        "custom_sql": ""  # 自定义SQL（可选）。填写后覆盖"表+列映射"，用于 JOIN 等复杂查询；必须 SELECT 出别名 account,name,ip,mac,online_time,offline_time（可选 contact）。深澜在线表：MAC=user_mac，上线=add_time(Unix时间戳)，下线=drop_time(在线时为0)，联系人=users.phone
    }


DEFAULT_CONFIG = {
    # 在线数据源：直连深澜后台，取"当前在线"实时快照（online_radius）
    "shenlan": _shenlan_default(),
    # 离线 / 上网明细数据源：取"包含离线的历史会话"，可上传上网明细导出文件，
    # 或配置另一套直连（若你们有记账/历史表）。与在线源相互独立。
    "offline": _shenlan_default(),
    "match": {
        "window_before_hours": 12,
        "window_after_hours": 12,
        "ip_field": "src_ip",     # 态势感知中用来定位的IP列：src_ip(源) 或 dst_ip(目的)
        "also_match_dst": False
    },
    "sync": {
        "interval_minutes": 0    # 0=仅手动同步；>0 则后台定时同步(分钟)
    }
}


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return _deep_merge(DEFAULT_CONFIG, cfg)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
