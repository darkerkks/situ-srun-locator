#!/usr/bin/env bash
# 部署脚本：在 10.248.15.19 等 Linux 服务器上一键安装并注册 systemd 服务。
# 用法：把整个 situ-middleware 目录传到服务器后，sudo bash deploy/deploy.sh
#
# 抗造设计（适配内网/无外网服务器）：
#   - 若系统 python3 已自带 flask，则直接用系统 python，免 pip；
#   - 否则建 venv 并 pip 安装（需要能访问 PyPI 或内部镜像）。
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-5000}"

echo "==> 部署目录: $ROOT"
echo "==> 监听端口: $PORT"

# 1) 选择 python 解释器并准备依赖
if python3 -c "import flask" 2>/dev/null; then
  PYTHON="$(command -v python3)"
  echo "==> 使用系统 python3 (已具备 flask)，无需安装依赖"
else
  if python3 -m venv venv 2>/dev/null; then
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    PYTHON="$ROOT/venv/bin/python"
    echo "==> 已在 venv 安装依赖"
  else
    echo "==> 无法创建 venv（可能缺 python3-venv），尝试用系统 pip 安装"
    pip3 install -r requirements.txt -q || pip install -r requirements.txt -q
    PYTHON="$(command -v python3)"
  fi
fi

# 2) 初始化本地数据库
"$PYTHON" -c "from middleware import db; db.init_db()"

# 3) 注册并启动服务（优先 systemd；无权限/无 systemd 时降级为 nohup 后台运行）
USE_SYSTEMD=false
if [ "$(id -u)" -eq 0 ] && command -v systemctl >/dev/null 2>&1; then
  USE_SYSTEMD=true
fi

if [ "$USE_SYSTEMD" = true ]; then
  sed "s|__ROOT__|$ROOT|g; s|__PORT__|$PORT|g; s|__PYTHON__|$PYTHON|g" deploy/situ-middleware.service > /etc/systemd/system/situ-middleware.service
  systemctl daemon-reload
  systemctl enable situ-middleware
  systemctl restart situ-middleware
  sleep 2
  echo "==> 服务状态:"
  systemctl --no-pager status situ-middleware --lines=0 || true
  echo
  echo "✅ 部署完成（systemd 托管，开机自启）。访问: http://<本机IP>:$PORT/"
  echo "   日志: journalctl -u situ-middleware -f"
  echo "   启停: systemctl start|stop|restart situ-middleware"
else
  echo "==> 非 root 或无 systemd，使用 nohup 后台运行（重启后需手动启动）"
  pkill -f "$ROOT/app.py" 2>/dev/null || true
  nohup "$PYTHON" "$ROOT/app.py" > "$ROOT/server.log" 2>&1 &
  sleep 2
  if kill -0 %1 2>/dev/null || pgrep -f "$ROOT/app.py" >/dev/null; then
    echo "✅ 已在后台启动。访问: http://127.0.0.1:$PORT/  (或 http://<本机IP>:$PORT/)"
    echo "   日志: tail -f $ROOT/server.log"
    echo "   停止: pkill -f '$ROOT/app.py'"
  else
    echo "!! 启动失败，请查看日志: $ROOT/server.log"
    exit 1
  fi
fi
echo
echo "   配置深澜MySQL: 打开页面 -> ① 深澜数据源设置 -> 连接并发现表 -> 保存 -> 立即同步"
