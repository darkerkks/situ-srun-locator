"""态势感知 <-> 深澜 用户定位中间件 Web 服务 (Flask)。"""
import os
import json
import uuid
import time
import threading
from datetime import datetime

from flask import Flask, request, jsonify, send_file
from middleware import config, db, shenlan, parsers, matcher

app = Flask(__name__, static_folder="static", static_url_path="")
db.init_db()

_scheduler_started = False


# ---------------- 页面 ----------------
@app.route("/")
def index():
    return app.send_static_file("index.html")


# ---------------- 设置 ----------------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    cfg = config.load_config()
    sc = dict(cfg["shenlan"])
    oc = dict(cfg["offline"])
    if sc.get("password"):
        sc["password"] = "******"
    if oc.get("password"):
        oc["password"] = "******"
    return jsonify({"shenlan": sc, "offline": oc, "match": cfg["match"], "sync": cfg["sync"]})


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.get_json(force=True, silent=True) or {}
    cfg = config.load_config()
    if "shenlan" in data:
        cfg["shenlan"].update(data["shenlan"])
    if "offline" in data:
        cfg["offline"].update(data["offline"])
    if "match" in data:
        cfg["match"].update(data["match"])
    if "sync" in data:
        cfg["sync"].update(data["sync"])
    config.save_config(cfg)
    return jsonify({"ok": True})


# ---------------- 深澜 ----------------
@app.route("/api/shenlan/tables", methods=["GET"])
def shenlan_tables():
    try:
        return jsonify({"tables": shenlan.list_tables()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/shenlan/columns", methods=["GET"])
def shenlan_columns():
    table = request.args.get("table", "")
    try:
        return jsonify({"columns": shenlan.list_columns(table)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/shenlan/sync", methods=["POST"])
def shenlan_sync():
    try:
        res = shenlan.sync_now()
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/shenlan/records", methods=["GET"])
def shenlan_records():
    return jsonify(
        {
            "online_count": db.shenlan_count(),
            "online_synced_at": db.latest_sync_at(),
            "offline_count": db.offline_count(),
            "offline_synced_at": db.latest_offline_sync_at(),
        }
    )


@app.route("/api/shenlan/import", methods=["POST"])
def shenlan_import():
    """在线源兜底导入：直接导入深澜在线表/认证日志的 CSV/XLSX。"""
    if "file" not in request.files:
        return jsonify({"error": "缺少文件字段 file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "空文件名"}), 400
    tmp = os.path.join(config.ROOT, "uploads")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "shenlan_%s_%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), f.filename))
    f.save(path)
    try:
        parsed = parsers.parse_shenlan_file(path)
    except Exception as e:
        return jsonify({"error": "解析失败: %s" % e}), 400
    from datetime import datetime as _dt

    synced_at = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    db.replace_shenlan(parsed["records"], synced_at)
    return jsonify({"count": parsed["total"], "synced_at": synced_at, "columns": parsed["columns"]})


# ---------------- 离线 / 上网明细 数据源 ----------------
@app.route("/api/offline/upload", methods=["POST"])
def offline_upload():
    """离线源主入口：上传"上网明细"导出文件（Excel/CSV），解析 + 用 users 表补全联系人。"""
    if "file" not in request.files:
        return jsonify({"error": "缺少文件字段 file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "空文件名"}), 400
    tmp = os.path.join(config.ROOT, "uploads")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "offline_%s_%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), f.filename))
    f.save(path)
    try:
        parsed = parsers.parse_shenlan_file(path)
    except Exception as e:
        return jsonify({"error": "解析失败: %s" % e}), 400
    records = parsed["records"]
    # 用深澜 users 表按账号补全联系人 / 真实姓名（上网明细导出通常不含电话）
    try:
        records, enriched = shenlan.enrich_contacts_from_users(records)
    except Exception:
        enriched = 0
    from datetime import datetime as _dt

    synced_at = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    db.replace_shenlan_offline(records, synced_at)
    return jsonify(
        {
            "count": parsed["total"],
            "synced_at": synced_at,
            "columns": parsed["columns"],
            "contact_enriched": enriched,
        }
    )


@app.route("/api/offline/db/sync", methods=["POST"])
def offline_db_sync():
    try:
        res = shenlan.sync_offline()
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- 态势感知上传 ----------------
@app.route("/api/situational/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "缺少文件字段 file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "空文件名"}), 400
    tmp = os.path.join(config.ROOT, "uploads")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(
        tmp, "%s_%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), f.filename)
    )
    f.save(path)
    try:
        parsed = parsers.parse_situational_file(path)
    except Exception as e:
        return jsonify({"error": "解析失败: %s" % e}), 400
    batch_id = datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4]
    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.insert_situational(parsed["records"], batch_id, uploaded_at)
    return jsonify(
        {
            "batch_id": batch_id,
            "columns": parsed["columns"],
            "total": parsed["total"],
        }
    )


# ---------------- 匹配 ----------------
@app.route("/api/match", methods=["POST"])
def do_match():
    data = request.get_json(silent=True) or {}
    batch_id = data.get("batch_id")
    cfg = config.load_config()
    situ = db.get_situational(batch_id)
    shen = db.get_shenlan_combined()
    results = matcher.match(situ, shen, cfg["match"])
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bid = batch_id or ("match_" + datetime.now().strftime("%Y%m%d%H%M%S"))
    db.insert_match_results(results, bid, created_at)
    return jsonify({"batch_id": bid, "count": len(results), "results": results})


@app.route("/api/match/results", methods=["GET"])
def match_results():
    batch = request.args.get("batch")
    rows = db.get_match_results(batch)
    return jsonify({"count": len(rows), "results": rows})


@app.route("/api/match/export", methods=["GET"])
def export():
    fmt = request.args.get("fmt", "csv")
    batch = request.args.get("batch")
    rows = db.get_match_results(batch)
    flat = []
    for r in rows:
        cand = r.get("candidates")
        if isinstance(cand, str):
            try:
                cand = json.loads(cand)
            except Exception:
                cand = []
        flat.append(
            {
                "发现时间": r.get("time"),
                "终端IP": r.get("ip"),
                "匹配账号": r.get("matched_account"),
                "用户姓名": r.get("matched_name"),
                "终端MAC": r.get("matched_mac"),
                "联系人": r.get("matched_contact"),
                "数据来源": r.get("matched_source"),
                "上线时间": r.get("online_time"),
                "下线时间": r.get("offline_time"),
                "置信度": r.get("confidence"),
                "候选数": r.get("candidates_count"),
                "说明": r.get("note"),
            }
        )
    out_dir = os.path.join(config.ROOT, "exports")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    base_cols = ["发现时间", "终端IP", "匹配账号", "用户姓名", "终端MAC", "联系人", "数据来源", "上线时间", "下线时间", "置信度", "候选数", "说明"]
    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "匹配结果"
        cols = list(flat[0].keys()) if flat else base_cols
        ws.append(cols)
        for r in flat:
            ws.append([r.get(c, "") for c in cols])
        p = os.path.join(out_dir, "match_%s.xlsx" % stamp)
        wb.save(p)
        return send_file(p, as_attachment=True, download_name="match_%s.xlsx" % stamp)
    else:
        import csv

        p = os.path.join(out_dir, "match_%s.csv" % stamp)
        cols = list(flat[0].keys()) if flat else base_cols
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in flat:
                w.writerow(r)
        return send_file(p, as_attachment=True, download_name="match_%s.csv" % stamp)


# ---------------- 后台定时同步 ----------------
def _scheduler():
    while True:
        try:
            cfg = config.load_config()
            iv = int(cfg["sync"].get("interval_minutes", 0) or 0)
            if iv > 0:
                time.sleep(iv * 60)
                try:
                    shenlan.sync_now(cfg)
                except Exception:
                    pass
                continue
        except Exception:
            pass
        time.sleep(30)


def _start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    t = threading.Thread(target=_scheduler, daemon=True)
    t.start()


if __name__ == "__main__":
    _start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    # 生产部署请用 gunicorn/waitress + systemd；此处为本地调试入口
    app.run(host="0.0.0.0", port=port, debug=False)
