#!/usr/bin/env bash
# ============================================================
#  智能学业分析平台 · 一键启动（macOS / Linux / Git-Bash）
#  同时拉起 后端 FastAPI(:8000) + 前端 Vite(:3006)
#  Ctrl-C 退出时自动结束两个子进程。
#  前置：已运行 scripts/init.sh 生成 analytics.sqlite，且前端已 pnpm install。
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f "backend/db/analytics.sqlite" ]; then
  echo "[X] 未找到分析库 backend/db/analytics.sqlite"
  echo "    请先运行 scripts/init.sh 初始化数据。"
  exit 1
fi

echo "[1/2] 启动后端 API  http://localhost:8000 ..."
PYTHONIOENCODING=utf-8 python -X utf8 -m uvicorn backend.api.main:app --port 8000 &
BACK=$!

echo "[2/2] 启动前端 Vite http://localhost:3006 ..."
( cd frontend && pnpm dev ) &
FRONT=$!

trap 'echo; echo "正在停止..."; kill $BACK $FRONT 2>/dev/null || true' INT TERM
echo
echo "后端健康检查: http://localhost:8000/api/health"
echo "前端访问地址: http://localhost:3006/   登录: dean / Demo@2026"
echo "数据核对:     python -X utf8 scripts/e2e_check.py"
echo "Ctrl-C 结束。"
wait
