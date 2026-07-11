"""后端配置：JWT 密钥/有效期、DB 路径。演示用，密钥可被环境变量覆盖。"""
import os

from backend.etl import config as etl_config

DB_PATH = str(etl_config.DB_PATH)

# JWT（演示密钥；生产应走环境变量/密钥管理）
JWT_SECRET = os.getenv("BI_JWT_SECRET", "bi-platform-demo-secret-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

# 学期常量（接口口径与 ETL 对齐）。时间序列改造后 9 学期全为真，
# CURRENT_SEMESTER = 当前在校快照所在学期(2025-2026-2)。
LATEST_REAL_SEMESTER = etl_config.LATEST_REAL_SEMESTER
SIM_SEMESTER = etl_config.SIM_SEMESTER
CURRENT_SEMESTER = etl_config.CURRENT_SEMESTER
