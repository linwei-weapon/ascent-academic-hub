@echo off
REM ============================================================
REM  智能学业分析平台 · 一键启动（Windows）
REM  同时拉起 后端 FastAPI(:8000) + 前端 Vite(:3006)
REM  双击本文件即可；两个服务各自独立窗口，关闭窗口即停止。
REM  前置：已运行 scripts\init.bat 生成 analytics.sqlite，
REM        且前端已 pnpm install。
REM ============================================================
chcp 65001 >nul
setlocal
REM ROOT = code/
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

set SETUP_REQUIRED=0
set MISSING_PYTHON=0
set MISSING_BACKEND=0
set MISSING_DATABASE=0
set MISSING_PNPM=0
set MISSING_FRONTEND=0

where python >nul 2>nul
if errorlevel 1 (
  set SETUP_REQUIRED=1
  set MISSING_PYTHON=1
) else (
  python -c "import fastapi, uvicorn" >nul 2>nul
  if errorlevel 1 (
    set SETUP_REQUIRED=1
    set MISSING_BACKEND=1
  )
)
if not exist "backend\db\analytics.sqlite" (
  set SETUP_REQUIRED=1
  set MISSING_DATABASE=1
)
where pnpm >nul 2>nul
if errorlevel 1 (
  set SETUP_REQUIRED=1
  set MISSING_PNPM=1
)
if not exist "frontend\node_modules\.bin\vite.cmd" (
  set SETUP_REQUIRED=1
  set MISSING_FRONTEND=1
)

if "%SETUP_REQUIRED%"=="1" (
  echo.
  echo [首次启动准备尚未完成]
  echo GitHub 仓库只保存程序、迁移脚本和脱敏演示数据生成程序，不直接保存：
  echo   1. Python / Node.js 第三方运行依赖，避免仓库体积过大及不同操作系统依赖冲突；
  echo   2. 学校业务数据库，避免敏感数据进入代码仓库；
  echo   3. 本机生成的分析库，因为它必须通过初始化脚本按当前版本创建菜单、权限和报表口径。
  echo.
  echo 因此，首次从 GitHub 克隆后，请按以下顺序操作：
  echo   1. 安装后端依赖：
  echo      cd /d "%ROOT%\backend"
  echo      python -m pip install -r requirements.txt
  echo   2. 初始化分析库：双击 "%ROOT%\scripts\init.bat"
  echo      未提供正式教务源库时，将自动生成可查看九张基础报表的脱敏演示数据。
  echo   3. 安装前端依赖：
  echo      cd /d "%ROOT%\frontend"
  echo      pnpm install
  echo   4. 再次双击 "%ROOT%\scripts\start.bat" 启动服务。
  echo.
  echo 当前缺失项：
  if "%MISSING_PYTHON%"=="1" echo   - 未检测到 Python，请先安装 Python 3.11 或更高版本
  if "%MISSING_BACKEND%"=="1" echo   - 后端 Python 依赖未安装完整
  if "%MISSING_DATABASE%"=="1" echo   - 分析库尚未初始化
  if "%MISSING_PNPM%"=="1" echo   - 未检测到 pnpm，请先执行 npm install -g pnpm
  if "%MISSING_FRONTEND%"=="1" echo   - 前端依赖尚未安装
  pause
  exit /b 1
)

echo [1/2] 启动后端 API  http://localhost:8000 ...
start "学业平台-后端:8000" cmd /k "cd /d %ROOT% && set PYTHONIOENCODING=utf-8 && python -X utf8 -m uvicorn backend.api.main:app --port 8000"

echo [2/2] 启动前端 Vite http://localhost:3006 ...
start "学业平台-前端:3006" cmd /k "cd /d %ROOT%\frontend && pnpm dev"

echo.
echo 已在两个新窗口分别启动后端与前端。
echo   后端健康检查: http://localhost:8000/api/health
echo   前端访问地址: http://localhost:3006/   登录: dean / Demo@2026
echo.
echo 数据核对（需后端已起）: python -X utf8 scripts\e2e_check.py
pause
