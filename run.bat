@echo off
chcp 65001 >nul
setlocal
:: 态势感知 <-> 深澜 用户定位中间件 —— Windows 一键启动
:: 用法：双击本文件即可（首次运行会自动建虚拟环境并安装依赖）
cd /d "%~dp0"

echo ============================================
echo  态势感知 / 深澜 用户定位中间件  (Windows)
echo ============================================

:: 1) 选择 Python 解释器（优先 py -3，否则 python）
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY set "PY=python"
%PY% --version || (echo [错误] 未找到 Python，请先安装 Python 3.9+ 并勾选 "Add to PATH" & pause & exit /b 1)

echo [1/3] 准备虚拟环境...
if not exist "venv" (
  %PY% -m venv venv
)
call venv\Scripts\activate.bat

echo [2/3] 安装依赖 (Flask / PyMySQL / openpyxl)...
pip install -r requirements.txt -q
if errorlevel 1 (echo [警告] 依赖安装失败，请检查网络是否可访问 PyPI & pause)

echo [3/3] 启动服务，稍后自动打开浏览器...
echo.
echo   访问地址:  http://localhost:5000
echo   关闭方法:  关闭下方弹出的 "SituMiddleware" 命令行窗口即可停止
echo.

:: 在独立窗口启动服务（保留日志），3 秒后打开浏览器
start "SituMiddleware" /min python app.py
timeout /t 3 >nul
start "" http://localhost:5000

:: 保持本窗口不闪退，方便查看提示
pause
endlocal
