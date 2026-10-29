"use strict";

let lastBatchId = null;
const CONF_FIELDS = ["account", "name", "ip", "mac", "online_time", "offline_time"];

function toggle(id) {
  const el = document.getElementById(id);
  el.style.display = el.style.display === "none" ? "block" : "none";
  const chev = el.previousElementSibling.querySelector(".chev");
  if (chev) chev.style.transform = el.style.display === "none" ? "rotate(-90deg)" : "rotate(0)";
}

async function api(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

function msg(id, text, kind) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = "msg" + (kind ? " " + kind : "");
}

// ---------------- 初始化 ----------------
async function init() {
  try {
    const cfg = await api("/api/settings");
    // 在线源
    document.getElementById("sl-host").value = cfg.shenlan.host || "";
    document.getElementById("sl-port").value = cfg.shenlan.port || 3306;
    document.getElementById("sl-db").value = cfg.shenlan.database || "";
    document.getElementById("sl-user").value = cfg.shenlan.user || "";
    document.getElementById("sl-pass").value = cfg.shenlan.password || "";
    document.getElementById("sl-interval").value = cfg.sync.interval_minutes || 0;
    const sqlEl = document.getElementById("sl-sql");
    if (sqlEl) sqlEl.value = cfg.shenlan.custom_sql || "";
    renderCols(cfg.shenlan.mapping || {});
    if (cfg.shenlan.table) document.getElementById("sl-table").value = cfg.shenlan.table;
    // 离线源
    const of = cfg.offline || {};
    document.getElementById("of-host").value = of.host || "";
    document.getElementById("of-port").value = of.port || 3306;
    document.getElementById("of-db").value = of.database || "";
    document.getElementById("of-user").value = of.user || "";
    document.getElementById("of-pass").value = of.password || "";
    document.getElementById("of-sql").value = of.custom_sql || "";
  } catch (e) { /* ignore */ }
  await refreshStatus();
}

async function refreshStatus() {
  try {
    const r = await api("/api/shenlan/records?limit=1");
    document.getElementById("sl-count").textContent = r.online_count || 0;
    document.getElementById("sl-sync").textContent = r.online_synced_at || "—";
    document.getElementById("of-count").textContent = r.offline_count || 0;
    document.getElementById("of-count2").textContent = r.offline_count || 0;
    document.getElementById("of-sync").textContent = r.offline_synced_at || "—";
  } catch (e) { /* ignore */ }
}

// ---------------- 在线源设置 ----------------
function collectShenlan() {
  return {
    host: document.getElementById("sl-host").value.trim(),
    port: parseInt(document.getElementById("sl-port").value) || 3306,
    database: document.getElementById("sl-db").value.trim(),
    user: document.getElementById("sl-user").value.trim(),
    password: document.getElementById("sl-pass").value.trim(),
    table: document.getElementById("sl-table").value,
    mapping: collectMapping(),
    custom_sql: (document.getElementById("sl-sql") || {}).value
      ? document.getElementById("sl-sql").value.trim() : "",
  };
}

function collectOffline() {
  return {
    host: document.getElementById("of-host").value.trim(),
    port: parseInt(document.getElementById("of-port").value) || 3306,
    database: document.getElementById("of-db").value.trim(),
    user: document.getElementById("of-user").value.trim(),
    password: document.getElementById("of-pass").value.trim(),
    custom_sql: (document.getElementById("of-sql") || {}).value
      ? document.getElementById("of-sql").value.trim() : "",
  };
}

function collectSettings() {
  return {
    shenlan: collectShenlan(),
    offline: collectOffline(),
    sync: { interval_minutes: parseInt(document.getElementById("sl-interval").value) || 0 },
  };
}

function collectMapping() {
  const m = {};
  CONF_FIELDS.forEach((f) => {
    const el = document.getElementById("map-" + f);
    m[f] = el ? el.value.trim() : f;
  });
  return m;
}

function renderCols(mapping) {
  const wrap = document.getElementById("sl-cols");
  wrap.innerHTML = "<div style='grid-column:1/-1;font-weight:600;color:var(--muted)'>列映射（深澜表字段 → 标准字段）</div>";
  const labels = { account: "账号", name: "用户姓名", ip: "IP地址", mac: "MAC地址", online_time: "上线时间", offline_time: "下线时间(可空)" };
  CONF_FIELDS.forEach((f) => {
    const label = document.createElement("label");
    label.textContent = labels[f] || f;
    const inp = document.createElement("input");
    inp.id = "map-" + f;
    inp.value = mapping[f] || f;
    label.appendChild(inp);
    wrap.appendChild(label);
  });
}

async function saveSettings() {
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectSettings()),
  });
}

document.getElementById("btn-save").onclick = async () => {
  try {
    await saveSettings();
    msg("sl-msg", "设置已保存", "ok");
  } catch (e) { msg("sl-msg", "保存失败：" + e.message, "err"); }
};

document.getElementById("btn-discover").onclick = async () => {
  try {
    await saveSettings();
    const r = await api("/api/shenlan/tables");
    const sel = document.getElementById("sl-table");
    sel.innerHTML = "<option value=''>— 选择表 —</option>";
    (r.tables || []).forEach((t) => {
      const o = document.createElement("option");
      o.value = t; o.textContent = t; sel.appendChild(o);
    });
    msg("sl-msg", "发现 " + r.tables.length + " 张表，请选择在线/认证表", "ok");
  } catch (e) { msg("sl-msg", "连接失败：" + e.message, "err"); }
};

async function onTableChange() {
  const table = document.getElementById("sl-table").value;
  if (!table) return;
  try {
    const r = await api("/api/shenlan/columns?table=" + encodeURIComponent(table));
    const guess = guessMapping(r.columns);
    renderCols(guess);
    msg("sl-msg", "已载入 " + r.columns.length + " 个字段，已尝试自动映射，请核对", "ok");
  } catch (e) { msg("sl-msg", "读取字段失败：" + e.message, "err"); }
}

function guessMapping(columns) {
  const norm = (s) => (s || "").toLowerCase().replace(/[_\s]/g, "");
  const map = {};
  const rules = {
    account: ["account", "user", "username", "账号", "userid", "user_id"],
    name: ["name", "姓名", "realname", "real_name", "username"],
    ip: ["ip", "ipaddr", "ip_address", "addr", "ip地址"],
    mac: ["mac", "macaddr", "mac_address", "mac地址"],
    online_time: ["online", "logintime", "starttime", "start_time", "上线", "onlinetime", "acctstarttime"],
    offline_time: ["offline", "stoptime", "endtime", "end_time", "下线", "offlinetime", "acctstoptime"],
  };
  CONF_FIELDS.forEach((f) => {
    const cn = norm(columns.find((c) => rules[f].some((k) => norm(c).includes(k))));
    map[f] = cn || f;
  });
  return map;
}

document.getElementById("btn-sync").onclick = async () => {
  try {
    await saveSettings();
    msg("sl-msg", "正在同步深澜在线数据…");
    const r = await api("/api/shenlan/sync", { method: "POST" });
    msg("sl-msg", "同步完成：共 " + r.count + " 条，时间 " + r.synced_at, "ok");
    await refreshStatus();
  } catch (e) { msg("sl-msg", "同步失败：" + e.message, "err"); }
};

// ---------------- 在线数据导入（CSV/XLSX，无需数据库直连） ----------------
document.getElementById("btn-sl-import").onclick = async () => {
  const file = document.getElementById("sl-file").files[0];
  if (!file) { msg("sl-imp-msg", "请先选择深澜导出文件", "err"); return; }
  const fd = new FormData();
  fd.append("file", file);
  try {
    msg("sl-imp-msg", "导入中…");
    const r = await fetch("/api/shenlan/import", { method: "POST", body: fd }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    const cols = Object.entries(r.columns || {}).map(([k, v]) => k + "←" + v).join("，");
    msg("sl-imp-msg", "已导入 " + r.count + " 条在线记录（时间 " + (r.synced_at || "") + "）。识别列：" + (cols || "（未识别到标准列）"), "ok");
    await refreshStatus();
  } catch (e) { msg("sl-imp-msg", "导入失败：" + e.message, "err"); }
};

// ---------------- 离线 / 上网明细 数据源 ----------------
document.getElementById("btn-of-import").onclick = async () => {
  const file = document.getElementById("of-file").files[0];
  if (!file) { msg("of-imp-msg", "请先选择上网明细导出文件", "err"); return; }
  const fd = new FormData();
  fd.append("file", file);
  try {
    msg("of-imp-msg", "导入并补全联系人中…");
    const r = await fetch("/api/offline/upload", { method: "POST", body: fd }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    const cols = Object.entries(r.columns || {}).map(([k, v]) => k + "←" + v).join("，");
    let extra = "";
    if (r.contact_enriched) extra = "；已按账号从 users 表补全 " + r.contact_enriched + " 条联系人";
    msg("of-imp-msg", "已导入 " + r.count + " 条上网明细记录（时间 " + (r.synced_at || "") + "）" + extra + "。识别列：" + (cols || "（未识别到标准列）"), "ok");
    await refreshStatus();
  } catch (e) { msg("of-imp-msg", "导入失败：" + e.message, "err"); }
};

document.getElementById("btn-of-dbsave").onclick = async () => {
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ offline: collectOffline() }),
    });
    msg("of-db-msg", "离线库设置已保存", "ok");
  } catch (e) { msg("of-db-msg", "保存失败：" + e.message, "err"); }
};

document.getElementById("btn-of-sync").onclick = async () => {
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ offline: collectOffline() }),
    });
    msg("of-db-msg", "正在从离线/历史数据库同步…");
    const r = await api("/api/offline/db/sync", { method: "POST" });
    msg("of-db-msg", "同步完成：共 " + r.count + " 条，时间 " + r.synced_at, "ok");
    await refreshStatus();
  } catch (e) { msg("of-db-msg", "同步失败：" + e.message, "err"); }
};

// ---------------- 态势感知上传 ----------------
document.getElementById("btn-upload").onclick = async () => {
  const file = document.getElementById("file").files[0];
  if (!file) { msg("up-msg", "请先选择文件", "err"); return; }
  const fd = new FormData();
  fd.append("file", file);
  try {
    msg("up-msg", "解析中…");
    const r = await fetch("/api/situational/upload", { method: "POST", body: fd }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    lastBatchId = r.batch_id;
    const cols = Object.entries(r.columns || {}).map(([k, v]) => k + "←" + v).join("，");
    msg("up-msg", "已上传 " + r.total + " 条。识别列：" + (cols || "（未识别到标准列，请检查表头）") + "。批次：" + r.batch_id, "ok");
  } catch (e) { msg("up-msg", "上传失败：" + e.message, "err"); }
};

// ---------------- 匹配 ----------------
document.getElementById("btn-match").onclick = async () => {
  try {
    msg("match-msg", "匹配中…");
    const r = await api("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: lastBatchId }),
    });
    renderResults(r.results || []);
    msg("match-msg", "匹配完成：共 " + r.count + " 条", "ok");
  } catch (e) { msg("match-msg", "匹配失败：" + e.message, "err"); }
};

function renderResults(results) {
  const tbody = document.querySelector("#result-table tbody");
  tbody.innerHTML = "";
  const filter = document.getElementById("f-confidence").value;
  const badgeClass = { "高": "b-high", "中": "b-mid", "低": "b-low", "未匹配": "b-none" };
  (results || []).forEach((r) => {
    if (filter && r.confidence !== filter) return;
    const tr = document.createElement("tr");
    tr.innerHTML =
      "<td>" + esc(r.time) + "</td>" +
      "<td>" + esc(r.ip) + "</td>" +
      "<td>" + esc(r.matched_account) + "</td>" +
      "<td>" + esc(r.matched_name) + "</td>" +
      "<td>" + esc(r.matched_mac) + "</td>" +
      "<td>" + esc(r.matched_contact) + "</td>" +
      "<td>" + esc(r.matched_source) + "</td>" +
      "<td>" + esc(r.online_time) + "</td>" +
      "<td><span class='badge " + (badgeClass[r.confidence] || "b-none") + "'>" + esc(r.confidence) + "</span></td>" +
      "<td>" + (r.candidates_count || 0) + "</td>" +
      "<td title='" + esc(r.note) + "'>" + esc(r.note) + "</td>";
    tbody.appendChild(tr);
  });
}

document.getElementById("f-confidence").onchange = () => {
  document.getElementById("btn-match").click();
};

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function attachBatch(href) {
  return lastBatchId ? href + "&batch=" + encodeURIComponent(lastBatchId) : href;
}
document.getElementById("btn-export-csv").onclick = (e) => { e.target.href = attachBatch("/api/match/export?fmt=csv"); };
document.getElementById("btn-export-xlsx").onclick = (e) => { e.target.href = attachBatch("/api/match/export?fmt=xlsx"); };

init();
