"""后端配置：JWT 密钥/有效期、DB 路径。演示用，密钥可被环境变量覆盖。"""
import os

from backend.etl import config as etl_config

DB_PATH = str(etl_config.DB_PATH)
V2_DB_PATH = str(etl_config.V2_DB_PATH)

# JWT（演示密钥；生产应走环境变量/密钥管理）
APP_ENV = os.getenv("BI_APP_ENV", "development").lower()
_DEMO_SECRET = "bi-platform-demo-secret-2026"
JWT_SECRET = os.getenv("BI_JWT_SECRET", _DEMO_SECRET)
if APP_ENV in {"production", "prod"} and JWT_SECRET == _DEMO_SECRET:
    raise RuntimeError("生产环境必须通过 BI_JWT_SECRET 配置独立 JWT 密钥")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12
JWT_ISSUER = "ascent-academic-hub"
JWT_AUDIENCE = "ascent-admin"

# CORS 默认仅允许本地前端；部署环境通过 BI_CORS_ORIGINS 传入逗号分隔白名单。
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "BI_CORS_ORIGINS",
    "http://localhost:3006,http://127.0.0.1:3006,http://localhost:3007,http://127.0.0.1:3007"
).split(",") if x.strip()]

# 学期常量（接口口径与 ETL 对齐）。时间序列改造后 9 学期全为真，
# CURRENT_SEMESTER = 当前在校快照所在学期(2025-2026-2)。
LATEST_REAL_SEMESTER = etl_config.LATEST_REAL_SEMESTER
SIM_SEMESTER = etl_config.SIM_SEMESTER
CURRENT_SEMESTER = etl_config.CURRENT_SEMESTER
GRADUATING_GRADE = etl_config.GRADUATING_GRADE
