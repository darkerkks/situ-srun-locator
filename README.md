# 态势感知 ↔ 深澜 用户定位中间件

> 将态势感知平台发现的终端 IP，按"发现时间"关联到深澜(Srun)认证会话，
> 消除 DHCP 动态分配导致的 IP 漂移，快速定位真实终端 MAC 与对应联系人。

## ✨ 特性
- 🕒 **时间锚定匹配**：发现时刻精确在线 / ±12h 窗口近似，自动识别 DHCP 重分配歧义
- 🔀 **双数据源**：在线实时（直连 MySQL）+ 离线上网明细（历史可回溯、可上传导出）
- 🖥️ **Web 可视化**：上传 → 匹配 → 导出，结果按置信度着色并标注数据来源
- 🚀 **一键部署**：Windows（`run.bat`）/ Linux（`deploy.sh` + systemd）双版本

架构：
situ-middleware/
├── app.py                 # Flask 服务与 API
├── requirements.txt
├── middleware/
│   ├── config.py          # 配置读写
│   ├── db.py              # 本地 SQLite 存储
│   ├── timeutil.py        # 时间解析
│   ├── shenlan.py         # 深澜 MySQL 连接器 + 同步
│   ├── parsers.py         # 态势感知/深澜 导出表解析
│   └── matcher.py         # IP->用户 匹配引擎（核心）
├── static/                # 前端 index.html / app.js / style.css
├── deploy/
│   ├── situ-middleware.service   # systemd 单元模板
│   └── deploy.sh
└── sample_data/           # 示例数据（虚拟账号/IP，无真实信息，用于演示/自测）

演示：
<img width="2552" height="1282" alt="image" src="https://github.com/user-attachments/assets/9774f9ee-6ec5-40e5-87c0-08ba4a0acde5" />
<img width="2552" height="1282" alt="image" src="https://github.com/user-attachments/assets/61f4bcbd-0abd-45d8-9020-9a00e22e1db9" />
<img width="2552" height="1282" alt="image" src="https://github.com/user-attachments/assets/95f9536e-3f0c-47ad-9ad0-8cca5099d129" />

