"""FastAPI 应用入口。
启动：PYTHONIOENCODING=utf-8 python -X utf8 -m uvicorn backend.api.main:app --reload --port 8000
"""
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .envelope import ApiError, fail, ok
from . import settings
from .security import decode_token
from .routers import (auth, dashboard, alert, curriculum, reports,
                      operation, faculty, settings as settings_router, students,
                      admin_rbac, meta, teacher, ai)
from .routers import v2

app = FastAPI(title="高校学业BI · 平台管理端 API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Active-Identity"],
)

access_logger = logging.getLogger("uvicorn.error")


@app.middleware("http")
async def permission_access_log(request: Request, call_next):
    """API访问日志显式记录账号与工作身份，不记录令牌和学生敏感数据。"""
    started = time.perf_counter()
    auth_header = request.headers.get("authorization", "")
    payload = None
    if auth_header.lower().startswith("bearer "):
        payload = decode_token(auth_header.split(" ", 1)[1].strip())
    username = (payload or {}).get("sub") or "anonymous"
    identity = request.headers.get("x-active-identity")
    if not identity and payload:
        identity = f"UR:{username}:{payload.get('role') or 'unknown'}"
    try:
        response = await call_next(request)
    except Exception:
        access_logger.exception(
            "api_access username=%s identity=%s method=%s path=%s status=500 duration_ms=%.1f",
            username, identity or "-", request.method, request.url.path,
            (time.perf_counter() - started) * 1000,
        )
        raise
    access_logger.info(
        "api_access username=%s identity=%s method=%s path=%s status=%s duration_ms=%.1f",
        username, identity or "-", request.method, request.url.path,
        response.status_code, (time.perf_counter() - started) * 1000,
    )
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code,
                        content=fail(exc.msg, code=exc.code))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """兜底：未捕获异常统一返回 envelope，不向前端泄漏堆栈。"""
    import traceback
    traceback.print_exc()  # 仍打到服务端日志便于排查
    return JSONResponse(status_code=500,
                        content=fail("服务器内部错误", code=500))


@app.get("/api/health")
def health():
    return ok({"status": "up"})


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(alert.router)
app.include_router(curriculum.router)
app.include_router(reports.router)
app.include_router(operation.router)
app.include_router(faculty.router)
app.include_router(settings_router.router)
app.include_router(students.router)
app.include_router(admin_rbac.router)
app.include_router(meta.router)
app.include_router(ai.router)
app.include_router(teacher.router)  # V1.1新增：任课教师视图
app.include_router(v2.router)       # V2真实数据验证接口（只读）

# 生产构建由同一个后台服务托管，避免原型运行依赖 Vite 开发服务器。
# 前端使用 Hash 路由，因此根目录与静态资源可直接交由 StaticFiles 提供。
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
