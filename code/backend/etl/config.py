"""ETL 全局配置：路径、常量。阶段2 各脚本统一引用。

【交接包版】路径已改为「包内相对路径」，自包含可直接重建分析库：
  交接包根/
  ├── code/backend/        ← BACKEND_DIR=此处, PKG_ROOT=交接包根
  └── datasource/
      ├── 构造数据/         ← TS_DIR（9 学期源库，ETL 主输入）
      └── 培养方案docx/      ← DATA_DIR（2 份培养方案，ETL 步骤③）
也可用环境变量 TS_DIR / DATA_DIR 覆盖，便于把数据源放到别处。
"""
import os
from pathlib import Path

# backend/ 根
BACKEND_DIR = Path(__file__).resolve().parent.parent
# 项目根（code/）
PROJECT_DIR = BACKEND_DIR.parent
# 交接包根（含 datasource/）
PKG_ROOT = PROJECT_DIR.parent

# 数据源目录（可被环境变量覆盖）
DATA_DIR = Path(os.environ.get("DATA_DIR", PKG_ROOT / "datasource" / "培养方案docx"))
TS_DIR = Path(os.environ.get("TS_DIR", PKG_ROOT / "datasource" / "构造数据"))

# 原始脱敏 Excel（交接包未随附原始 Excel，仅旧 extract.py 的 __main__ 自测用；
# run_etl 走 extract_ts 读 9 学期源库，不依赖这些 Excel 路径）
GRADE_XLSX = DATA_DIR / "成绩数据-脱敏.xlsx"
TASK_XLS = DATA_DIR / "教学任务-脱敏.xls"
COURSE_XLSX = DATA_DIR / "课程信息.xlsx"
ENROLL_XLSX = DATA_DIR / "2022届选课数据-脱敏.xlsx"
PLAN_DOCX = {
    "安全工程": DATA_DIR / "2022级安全工程专业培养方案.docx",
    "海洋油气工程": DATA_DIR / "2022级海洋油气工程培养方案.docx",
}

# 分析库产物（ETL 输出，重建后生成）
DB_PATH = Path(os.environ.get("DB_PATH", BACKEND_DIR / "db" / "analytics.sqlite"))
SCHEMA_SQL = BACKEND_DIR / "etl" / "schema.sql"

# V2 真实数据接入验证库。默认与现有演示库完全隔离，可分别通过环境变量覆盖。
V2_DB_PATH = Path(os.environ.get("V2_DB_PATH", BACKEND_DIR / "db" / "analytics_v2.sqlite"))
V2_SCHEMA_SQL = BACKEND_DIR / "etl" / "schema_v2.sql"
V2_SOURCE_ROOT = Path(os.environ.get(
    "V2_SOURCE_ROOT", r"D:\AI教育\AI学业助手\15-原始数据\数据"
))

# 当前学期（真当前，时间序列数据中最新学期）。
# 历史遗留：LATEST_REAL_SEMESTER/SIM_SEMESTER 在单 Excel + simulate 时代区分
# “真实最新”与“模拟下一学期”；时间序列改造后 9 学期全为真，统一以
# CURRENT_SEMESTER 表示当前在校快照所在学期。两个旧名保留为别名以兼容引用。
CURRENT_SEMESTER = "2025-2026-2"
LATEST_REAL_SEMESTER = CURRENT_SEMESTER
SIM_SEMESTER = CURRENT_SEMESTER

# 毕业届年级（当前学期在校且年级=此值 → 应届毕业生群体）
GRADUATING_GRADE = 2022

# 随机种子（合成业务事实表可复现）
SEED = 20260624
