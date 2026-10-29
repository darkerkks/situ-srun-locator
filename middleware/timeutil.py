"""时间与日期解析工具：把各种来源的时间字段统一成 'YYYY-MM-DD HH:MM:SS'。"""
from datetime import datetime

_COMMON_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y %H:%M:%S",
]


def normalize_time(v):
    """把数据库/Excel 出来的时间值规范成字符串，无法解析则原样返回字符串。

    兼容：datetime 对象、Unix 时间戳（int/float 秒，如 1793146516）、以及常见格式的字符串。
    深澜 online_radius 的 add_time/drop_time 即为 Unix 时间戳整数；在线用户 drop_time=0 视为“仍在在线”返回 None。
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v == 0:
            return None  # 0 时间戳 -> 仍在在线 / 无下线
        try:
            return datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    s = str(v).strip()
    if not s or s.upper() in ("NONE", "NAN"):
        return None
    # 形如 1793146516 的整数字符串（Unix 时间戳，秒）
    if s.isdigit() and 9 <= len(s) <= 11:
        try:
            return datetime.fromtimestamp(int(s)).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    for fmt in _COMMON_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return s  # 保留原始串，交由上层决定


def parse_time(v):
    """解析成 datetime 对象；失败返回 None。"""
    s = normalize_time(v)
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
