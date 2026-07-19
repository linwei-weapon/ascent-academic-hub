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
set ROOT=%~dp0..
cd /d "%ROOT%"

if not exist "backend\db\analytics.sqlite" (
  echo [X] 未找到分析库 backend\db\analytics.sqlite
  echo     请先双击 scripts\init.bat 初始化数据。
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
