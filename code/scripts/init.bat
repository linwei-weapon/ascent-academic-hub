@echo off
REM ============================================================
REM  智能学业分析平台 · 一键初始化分析库（Windows）
REM  从 datasource/构造数据 的 9 学期源库跑完整 ETL，
REM  在 code/backend/db/analytics.sqlite 重建星型分析库 + 初始化系统表。
REM  首次部署或换数据源后运行一次即可；输出已存在会被覆盖重建。
REM ============================================================
chcp 65001 >nul
setlocal
REM ROOT = code/（scripts 的上一级），backend 包从此处可导入
set ROOT=%~dp0..
cd /d "%ROOT%"

echo [1/2] 运行 ETL 重建分析库（约 1-3 分钟，取决于机器）...
set PYTHONIOENCODING=utf-8
python -X utf8 -m backend.etl.run_etl
if errorlevel 1 (
  echo.
  echo [X] ETL 失败。请确认：① 已 pip install -r backend/requirements.txt
  echo     ② datasource/构造数据 下有 9 个 *.db ③ datasource/培养方案docx 下有 2 个 .docx
  pause
  exit /b 1
)

echo [2/2] 同步菜单、规则、统一权限和系统管理迁移（幂等，可重复执行）...
python -X utf8 scripts\migrate_menu.py
python -X utf8 scripts\migrate_alert_rules.py
python -X utf8 scripts\migrate_permission_context.py
python -X utf8 scripts\migrate_staff_relationships.py
python -X utf8 scripts\migrate_etl_run.py
python -X utf8 scripts\migrate_system_management.py
python -X utf8 scripts\migrate_student_growth_indexes.py

echo.
echo [OK] 分析库已生成: code\backend\db\analytics.sqlite
echo 下一步: 双击 scripts\start.bat 启动前后端。
pause
