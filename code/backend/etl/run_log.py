"""M4 ETL 运行历史落库：etl_run 公共 helper。

设计要点：
- etl_run 放 V2 库（与 data_batch 同库，便于按 batch_id 关联）。
- start_run 先插 status='running' 记录并立即提交；schema_v2.sql 的唯一部分索引
  uq_etl_run_running_task 保证同一任务同一时刻至多一条 running 记录，
  冲突时抛 RunConflictError（API 层映射为 409）。
- run_logged 上下文管理器：任务体抛异常也会落 failed 记录（含 error），
  不会因为是手动跑批脚本而丢失运行痕迹。
- 各 loader/builder 只在公共入口包一层，report dict 原样存入 checks_json。
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .init_v2 import init_v2

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


class RunConflictError(RuntimeError):
    """同一任务已有 running 记录，拒绝并发执行。"""

    def __init__(self, task: str):
        super().__init__(f"任务 {task} 正在执行中，请勿重复触发")
        self.task = task


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def should_skip_logging(db_path) -> bool:
    """:memory: 连接各自独立，无法跨连接落运行记录，跳过。"""
    return db_path is not None and str(db_path) == ":memory:"


def start_run(conn: sqlite3.Connection, task: str, batch_id: str | None = None,
              triggered_by: str = "manual", source: str = "etl") -> int:
    try:
        cursor = conn.execute(
            "INSERT INTO etl_run(task,batch_id,started_at,status,triggered_by,source)"
            " VALUES(?,?,?,'running',?,?)",
            (task, batch_id, _utc_now(), triggered_by, source),
        )
    except sqlite3.IntegrityError as exc:
        raise RunConflictError(task) from exc
    return int(cursor.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str,
               rows_read: int | None = None, rows_written: int | None = None,
               checks: dict | None = None, error: str | None = None,
               started_monotonic: float | None = None) -> None:
    duration_ms = (
        int((time.monotonic() - started_monotonic) * 1000)
        if started_monotonic is not None else None
    )
    conn.execute(
        "UPDATE etl_run SET finished_at=?,duration_ms=?,status=?,rows_read=?,"
        "rows_written=?,checks_json=?,error=? WHERE run_id=?",
        (
            _utc_now(), duration_ms, status, rows_read, rows_written,
            json.dumps(checks, ensure_ascii=False, default=str)
            if checks is not None else None,
            (str(error)[:500] if error else None),
            run_id,
        ),
    )


@contextmanager
def run_logged(task: str, db_path: Path | str | None = None,
               batch_id: str | None = None, triggered_by: str = "manual",
               source: str = "etl"):
    """包裹一次跑批：进入插 running，正常退出落 success，异常落 failed 并继续抛出。

    yield 的 dict 由任务体填写 rows_read / rows_written / checks，
    结束时连同耗时一起写回 etl_run。
    """
    conn = init_v2(db_path)
    started = time.monotonic()
    try:
        run_id = start_run(conn, task, batch_id, triggered_by, source)
        conn.commit()
    except Exception:
        conn.close()
        raise
    info: dict = {"run_id": run_id}
    try:
        yield info
    except Exception as exc:
        finish_run(conn, run_id, STATUS_FAILED, error=exc,
                   started_monotonic=started)
        conn.commit()
        raise
    else:
        finish_run(
            conn, run_id, STATUS_SUCCESS,
            rows_read=info.get("rows_read"),
            rows_written=info.get("rows_written"),
            checks=info.get("checks"),
            started_monotonic=started,
        )
        conn.commit()
    finally:
        conn.close()


def latest_run(conn: sqlite3.Connection, task: str) -> dict | None:
    cursor = conn.execute(
        "SELECT * FROM etl_run WHERE task=? ORDER BY run_id DESC LIMIT 1",
        (task,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip([col[0] for col in cursor.description], row))
