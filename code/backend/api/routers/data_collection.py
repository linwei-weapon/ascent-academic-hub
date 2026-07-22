"""M4 数据采集监控：批次台账、ETL运行历史、手动触发（白名单）、采集频率展示。

边界（与 docs/91 M4 一致）：
- 只读接口复用 require_admin（system.manage）；手动触发需 etl.trigger 动作权限。
- 触发仅白名单任务，绝不开放任意脚本执行；每次触发写 sys_security_audit。
- 同任务已有 running 记录时 409（DB 唯一部分索引兜底）。
- 原型期不内置调度器；采集频率仅展示 sys_system_parameter 中的说明参数。
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import db as dbm
from ..deps import get_current_user, get_db, get_db_rw, get_v2_db, require_admin
from ..envelope import ApiError, ok
from ..permission_context import has_action
from ..security_governance import write_audit
from ...etl import config as etl_config
from ...etl.run_log import RunConflictError, latest_run

router = APIRouter(prefix="/api/admin/system/data-collection",
                   tags=["data-collection"])

# 手动触发等待上限（秒）。超时不代表任务失败，运行记录会在任务结束后更新。
TRIGGER_WAIT_SECONDS = 120

# 白名单任务：仅允许映射到具体 builder/loader 函数，不接受任意代码。
TRIGGER_TASKS = {
    "v2_course_pass_builder": {
        "name": "课程通过率三分层聚合重建",
        "description": "grade_attempt → agg_course_pass_stat 全量重建（幂等，秒级）",
        "callable": "backend.etl.v2_course_pass_builder:build_course_pass_stat",
        "needsSourceFiles": False,
    },
    "v2_teaching_loader": {
        "name": "教职工与教学任务采集",
        "description": "正式教师/班主任/导师/教学任务 Excel → V2 事实与排课聚合",
        "callable": "backend.etl.v2_teaching_loader:load_teaching",
        "needsSourceFiles": True,
    },
    "v2_grade_loader": {
        "name": "成绩与课程替代采集",
        "description": "2021级成绩/课程替代 Excel → grade_attempt 与有效结果重建",
        "callable": "backend.etl.v2_grade_loader:load_grades",
        "needsSourceFiles": True,
    },
}

_TRIGGER_LOCK = threading.Lock()


def _resolve_task(task: str):
    spec = TRIGGER_TASKS[task]
    module_name, func_name = spec["callable"].split(":")
    return getattr(importlib.import_module(module_name), func_name)


def _v2_rw_conn() -> sqlite3.Connection:
    path = etl_config.V2_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone())


@router.get("/overview")
def data_collection_overview(_: dict = Depends(require_admin),
                             v2: sqlite3.Connection = Depends(get_v2_db),
                             conn: sqlite3.Connection = Depends(get_db)):
    batch_total = dbm.scalar(v2, "SELECT COUNT(*) FROM data_batch") or 0
    last_collected = dbm.scalar(v2, """
        SELECT MAX(COALESCE(collected_at, ingested_at)) FROM data_batch
    """)
    quality_pending = dbm.scalar(v2, """
        SELECT COUNT(*) FROM data_batch WHERE quality_status NOT IN ('passed','ok')
    """) or 0
    last_run = None
    if _table_exists(v2, "etl_run"):
        last_run = dbm.query_one(v2, """
            SELECT run_id,task,status,started_at,finished_at,duration_ms,
                   rows_written,triggered_by,error
            FROM etl_run ORDER BY run_id DESC LIMIT 1
        """)
    open_quality_issues = 0
    if _table_exists(conn, "data_quality_issue"):
        open_quality_issues = dbm.scalar(conn, """
            SELECT COUNT(*) FROM data_quality_issue WHERE status='open'
        """) or 0
    frequency = {}
    if _table_exists(conn, "sys_system_parameter"):
        for key in ("data.refresh_mode", "data.refresh_cron"):
            row = dbm.query_one(conn, """
                SELECT name,value_json,description,updated_at
                FROM sys_system_parameter WHERE parameter_key=?
            """, (key,))
            if row:
                try:
                    value = json.loads(row["value_json"])
                except (TypeError, ValueError):
                    value = row["value_json"]
                frequency[key] = {
                    "name": row["name"], "value": value,
                    "description": row["description"],
                    "updatedAt": row["updated_at"],
                }
    return ok({
        "lastCollectedAt": last_collected,
        "batchTotal": batch_total,
        "batchQualityPending": quality_pending,
        "lastRun": last_run,
        "openQualityIssues": open_quality_issues,
        "frequency": frequency,
        "tasks": [
            {"task": task, **{k: v for k, v in spec.items() if k != "callable"}}
            for task, spec in TRIGGER_TASKS.items()
        ],
        "boundary": "平台只消费学校数据；原型期不内置调度器，采集由学校数据交换平台触发。",
    })


@router.get("/batches")
def list_data_batches(_: dict = Depends(require_admin),
                      v2: sqlite3.Connection = Depends(get_v2_db)):
    has_run = _table_exists(v2, "etl_run")
    last_run_select = """
        (SELECT r.status FROM etl_run r
          WHERE r.batch_id=b.batch_id ORDER BY r.run_id DESC LIMIT 1
        ) last_run_status,
        (SELECT r.finished_at FROM etl_run r
          WHERE r.batch_id=b.batch_id ORDER BY r.run_id DESC LIMIT 1
        ) last_run_finished_at
    """ if has_run else "NULL last_run_status, NULL last_run_finished_at"
    rows = dbm.query(v2, f"""
        SELECT b.batch_id,b.source_code,b.source_file,b.file_hash,
               b.collected_at,b.ingested_at,b.row_count,b.accepted_count,
               b.rejected_count,b.quality_status,{last_run_select}
        FROM data_batch b ORDER BY b.ingested_at DESC,b.batch_id
    """)
    return ok({
        "batches": rows,
        "summary": {
            "total": len(rows),
            "lastIngestedAt": rows[0]["ingested_at"] if rows else None,
        },
    })


@router.get("/runs")
def list_etl_runs(task: Optional[str] = None, status: Optional[str] = None,
                  page: int = Query(1, ge=1),
                  pageSize: int = Query(20, ge=1, le=100),
                  _: dict = Depends(require_admin),
                  v2: sqlite3.Connection = Depends(get_v2_db)):
    if not _table_exists(v2, "etl_run"):
        return ok({"runs": [], "total": 0, "page": page, "pageSize": pageSize})
    conds, params = ["1=1"], []
    if task:
        conds.append("task=?")
        params.append(task)
    if status:
        if status not in {"running", "success", "failed"}:
            raise ApiError("status 仅支持 running/success/failed",
                           code=400, status_code=400)
        conds.append("status=?")
        params.append(status)
    where = " AND ".join(conds)
    total = dbm.scalar(v2, f"SELECT COUNT(*) FROM etl_run WHERE {where}",
                       tuple(params)) or 0
    rows = dbm.query(v2, f"""
        SELECT run_id,task,batch_id,started_at,finished_at,duration_ms,status,
               rows_read,rows_written,checks_json,error,triggered_by,source
        FROM etl_run WHERE {where}
        ORDER BY run_id DESC LIMIT ? OFFSET ?
    """, tuple(params) + (pageSize, (page - 1) * pageSize))
    return ok({"runs": rows, "total": total, "page": page, "pageSize": pageSize})


class TriggerIn(BaseModel):
    task: str


def _run_trigger(task: str, username: str):
    """同步执行白名单任务；返回 (status, detail)。失败不抛给调用方。"""
    try:
        fn = _resolve_task(task)
        report = fn(triggered_by=username)
        return "success", {"report": report}
    except RunConflictError as exc:
        return "conflict", {"error": str(exc)}
    except Exception as exc:  # 任务失败已落 etl_run(failed)，这里如实回报
        return "failed", {"error": str(exc)[:500]}


@router.post("/trigger")
def trigger_collection_task(body: TriggerIn,
                            user: dict = Depends(get_current_user),
                            conn: sqlite3.Connection = Depends(get_db_rw)):
    if not has_action(user, "etl.trigger"):
        raise ApiError("无权限触发数据采集任务", code=403, status_code=403)
    task = (body.task or "").strip()
    if task not in TRIGGER_TASKS:
        raise ApiError(
            "任务不在白名单中：" + (task or "（空）"),
            code=400, status_code=400,
        )
    with _TRIGGER_LOCK:
        guard = _v2_rw_conn()
        try:
            if not _table_exists(guard, "etl_run"):
                from ...etl.init_v2 import init_v2
                init_v2(etl_config.V2_DB_PATH).close()
            running = dbm.query_one(guard, """
                SELECT run_id,started_at,triggered_by FROM etl_run
                WHERE task=? AND status='running'
            """, (task,))
        finally:
            guard.close()
        if running:
            raise ApiError(
                f"任务正在执行中（run_id={running['run_id']}，"
                f"开始于 {running['started_at']}），请勿重复触发",
                code=409, status_code=409,
            )

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_run_trigger, task, user["username"])
        try:
            status, detail = future.result(timeout=TRIGGER_WAIT_SECONDS)
            pool.shutdown(wait=False)
        except FutureTimeout:
            # 等待超时但任务仍在执行：运行记录稍后由任务自身更新。
            pool.shutdown(wait=False)
            run = None
            peek = _v2_rw_conn()
            try:
                if _table_exists(peek, "etl_run"):
                    run = latest_run(peek, task)
            finally:
                peek.close()
            write_audit(
                conn, user["username"], "system.data_collection.trigger",
                "etl_run", str((run or {}).get("run_id") or ""),
                result="success",
                detail={"task": task, "outcome": "accepted_running"},
            )
            return ok({
                "task": task, "status": "running",
                "runId": (run or {}).get("run_id"),
                "waitSeconds": TRIGGER_WAIT_SECONDS,
            }, msg="任务已受理，仍在执行中，请稍后在运行历史查看结果")

    if status == "conflict":
        raise ApiError(detail["error"], code=409, status_code=409)

    run = None
    peek = _v2_rw_conn()
    try:
        run = latest_run(peek, task)
    finally:
        peek.close()
    write_audit(
        conn, user["username"], "system.data_collection.trigger",
        "etl_run", str((run or {}).get("run_id") or ""),
        result="success" if status == "success" else "failed",
        detail={
            "task": task, "outcome": status,
            "durationMs": (run or {}).get("duration_ms"),
            "error": detail.get("error"),
        },
    )
    if status == "failed":
        return ok({
            "task": task, "status": "failed",
            "runId": (run or {}).get("run_id"),
            "error": detail["error"],
        }, msg="任务执行失败，详情见运行历史")
    return ok({
        "task": task, "status": "success",
        "runId": (run or {}).get("run_id"),
        "durationMs": (run or {}).get("duration_ms"),
        "rowsWritten": (run or {}).get("rows_written"),
    }, msg="采集任务执行完成")
