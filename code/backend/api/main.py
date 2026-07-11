"""FastAPI 应用入口。
启动：PYTHONIOENCODING=utf-8 python -X utf8 -m uvicorn backend.api.main:app --reload --port 8000
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .envelope import ApiError, fail, ok
from .routers import (auth, dashboard, alert, curriculum, reports,
                      operation, faculty, settings as settings_router, students,
                      admin_rbac, meta, teacher)

app = FastAPI(title="高校学业BI · 平台管理端 API", version="0.3.0")

# 演示环境放开跨域（前端 vite dev / 任意来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
app.include_router(teacher.router)  # V1.1新增：任课教师视图
