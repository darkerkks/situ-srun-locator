"""IP->用户 定位匹配引擎。

核心思路（针对 DHCP 动态分配导致的 IP 漂移）：
1. 态势感知发现某终端 IP=S 于时刻 T。
2. 在深澜记录（在线快照 + 上网明细历史）中找 IP==S 的所有认证会话。
3. 优先匹配“发现时刻精确在线”的会话（online_time <= T < offline_time，或仍在线）。
   历史精确匹配优先采用“上网明细”记录（含离线的历史会话，时间区间更可信），
   其次才是“在线实时”快照（仅含当前在线，对过去事件覆盖有限）。
4. 若无精确在线记录，则在 ±window 小时（默认±12h，覆盖 DHCP 续租/重分配误差）内取“上线时间最接近 T”的记录作近似匹配，并标注需人工核对 MAC。
5. 若同一 IP 在 ±window 内出现多个不同账号（DHCP 把地址重新分给别人），则置信度降为“低”，提示核对 MAC 以锁定真实终端与联系人。
"""
from . import timeutil


def normalize_ip(ip):
    if not ip:
        return ""
    s = str(ip).strip().lower()
    if "/" in s:  # 去掉掩码 1.2.3.4/24
        s = s.split("/")[0]
    return s


def session_active(rec, t):
    """会话在时刻 t 是否仍然在线。"""
    ot = timeutil.parse_time(rec.get("online_time"))
    if ot is None or ot > t:
        return False
    ft = timeutil.parse_time(rec.get("offline_time"))
    if ft is None:
        return True  # 仍在线（当前快照）
    return t < ft  # 严格小于下线时刻，边界归给下一会话


def within_window(online_time, t, wb_h, wa_h):
    ot = timeutil.parse_time(online_time)
    if ot is None:
        return False
    from datetime import timedelta

    return (t - timedelta(hours=wb_h)) <= ot <= (t + timedelta(hours=wa_h))


def _sort_by_online(records):
    valid = [r for r in records if timeutil.parse_time(r.get("online_time")) is not None]
    valid.sort(key=lambda r: timeutil.parse_time(r.get("online_time")), reverse=True)
    return valid


def match(situational, shenlan, cfg_match):
    wb = float(cfg_match.get("window_before_hours", 12))
    wa = float(cfg_match.get("window_after_hours", 12))
    ip_field = cfg_match.get("ip_field", "src_ip")

    by_ip = {}
    for r in shenlan:
        by_ip.setdefault(normalize_ip(r.get("ip")), []).append(r)

    results = []
    for s in situational:
        ip = normalize_ip(s.get(ip_field))
        t = timeutil.parse_time(s.get("time"))
        res = {
            "ip": ip,
            "time": s.get("time"),
            "matched_account": "",
            "matched_name": "",
            "matched_mac": "",
            "matched_contact": "",
            "matched_source": "",
            "online_time": "",
            "offline_time": "",
            "confidence": "",
            "note": "",
            "candidates": [],
            "candidates_count": 0,
            "raw": s.get("_raw", {}),
            "alert": s.get("alert", ""),
        }
        if not ip:
            res["confidence"] = "未匹配"
            res["note"] = "态势感知记录缺少 IP"
            results.append(res)
            continue
        if t is None:
            res["confidence"] = "未匹配"
            res["note"] = "态势感知记录时间无法解析: %s" % s.get("time")
            results.append(res)
            continue

        cands = by_ip.get(ip, [])
        if not cands:
            res["confidence"] = "未匹配"
            res["note"] = "深澜库中无该 IP(%s) 的认证记录（在线/上网明细均未收录）" % ip
            results.append(res)
            continue

        active = [r for r in cands if session_active(r, t)]
        near = [
            r
            for r in cands
            if (not session_active(r, t)) and within_window(r.get("online_time"), t, wb, wa)
        ]
        window_cands = active + near
        accounts = set(str(r.get("account")) for r in window_cands)
        macs = set(str(r.get("mac")) for r in window_cands)

        def _pick_best(pool):
            valid = [r for r in pool if timeutil.parse_time(r.get("online_time")) is not None]
            if not valid:
                valid = list(pool)
            # 优先“上网明细历史”记录；其次按上线时间从晚到早（最接近发现时刻 T）
            valid.sort(
                key=lambda r: (
                    0 if r.get("source") == "offline" else 1,
                    -(timeutil.parse_time(r.get("online_time")) or t).timestamp(),
                )
            )
            return valid[0]

        if active:
            off = [r for r in active if r.get("source") == "offline"]
            on = [r for r in active if r.get("source") != "offline"]
            pool = off if off else on
            best = _pick_best(pool)
            res["matched_account"] = best.get("account", "")
            res["matched_name"] = best.get("name", "")
            res["matched_mac"] = best.get("mac", "")
            res["matched_contact"] = best.get("contact", "")
            res["matched_source"] = "上网明细历史" if best.get("source") == "offline" else "在线实时"
            res["online_time"] = best.get("online_time", "")
            res["offline_time"] = best.get("offline_time", "") or ""
            if len(pool) == 1:
                res["confidence"] = "高"
                res["note"] = "发现时刻该 IP 精确%s，已定位到唯一用户" % (
                    "在历史上线（上网明细）" if best.get("source") == "offline" else "在线"
                )
            else:
                res["confidence"] = "低"
                res["note"] = "发现时刻该 IP 存在多个重叠会话，无法唯一判定，需核对 MAC"
            if len(accounts) > 1:
                res["note"] += (
                    "；该 IP 在 ±%dh 窗口内曾被 %d 个账号通过 DHCP 获取（重分配历史），"
                    "本次定位以覆盖发现时刻的会话为准，必要时核对 MAC" % (int(wb), len(accounts))
                )
        elif near:
            off = [r for r in near if r.get("source") == "offline"]
            on = [r for r in near if r.get("source") != "offline"]
            pool = off if off else on
            valid = _sort_by_online(pool)
            valid.sort(
                key=lambda r: abs(
                    (timeutil.parse_time(r.get("online_time")) - t).total_seconds()
                )
            )
            best = valid[0]
            res["matched_account"] = best.get("account", "")
            res["matched_name"] = best.get("name", "")
            res["matched_mac"] = best.get("mac", "")
            res["matched_contact"] = best.get("contact", "")
            res["matched_source"] = "上网明细历史" if best.get("source") == "offline" else "在线实时"
            res["online_time"] = best.get("online_time", "")
            res["offline_time"] = best.get("offline_time", "") or ""
            res["confidence"] = "中"
            res["note"] = (
                "发现时刻无精确在线记录，按 ±%dh 窗口内最近认证记录匹配，建议人工核对 MAC（来源：%s）"
                % (int(wb), res["matched_source"])
            )
            if len(accounts) > 1:
                res["confidence"] = "低"
                res["note"] += "；该 IP 在窗口内被 %d 个账号获取，存在地址重分配" % len(accounts)
        else:
            has_time = any(
                timeutil.parse_time(r.get("online_time")) is not None for r in cands
            )
            if not has_time:
                accts = set(str(r.get("account")) for r in cands)
                best = cands[0]
                res["matched_account"] = best.get("account", "")
                res["matched_name"] = best.get("name", "")
                res["matched_mac"] = best.get("mac", "")
                res["matched_contact"] = best.get("contact", "")
                res["matched_source"] = "上网明细历史" if best.get("source") == "offline" else "在线实时"
                res["online_time"] = best.get("online_time", "") or ""
                res["offline_time"] = best.get("offline_time", "") or ""
                if len(accts) == 1:
                    res["confidence"] = "中"
                    res["note"] = "数据源未提供时间，按当前记录匹配（历史时刻精确定位请用上网明细）"
                else:
                    res["confidence"] = "低"
                    res["note"] = "数据源未提供时间且该 IP 对应 %d 个账号，需核对 MAC 锁定终端" % len(accts)
                window_cands = list(cands)
            else:
                res["confidence"] = "未匹配"
                res["note"] = (
                    "该 IP 在 ±%dh 窗口内无认证记录，无法定位（事件过早/过晚，或未纳入认证）"
                    % int(wb)
                )

        res["candidates"] = [
            {
                "account": r.get("account"),
                "name": r.get("name"),
                "ip": r.get("ip"),
                "mac": r.get("mac"),
                "online_time": r.get("online_time"),
                "offline_time": r.get("offline_time"),
                "source": r.get("source", ""),
            }
            for r in window_cands
        ]
        res["candidates_count"] = len(window_cands)
        results.append(res)

    return results
