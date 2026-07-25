"""数据接入可信度与运行保障工作台。

边界：
- 平台只消费学校数据，不在本模块维护教务主数据或修改源系统记录。
- 读取状态与证据需要system.manage；手动重跑还需etl.trigger。
- 白名单任务异步受理，页面通过运行详情轮询，不等待长任务完成。
"""
from __future__ import annotations

import csv
import importlib
import io
import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from ...data_collection_catalog import (
    CATALOG_VERSION,
    SOURCE_DEFINITIONS,
)
from ...etl import config as etl_config
from ...etl.run_log import RunConflictError, latest_run
from .. import db as dbm
from ..deps import get_current_user, get_db, get_db_rw, get_v2_db, require_admin
from ..envelope import ApiError, ok
from ..permission_context import has_action
from ..security_governance import write_audit

router = APIRouter(
    prefix="/api/admin/system/data-collection",
    tags=["data-collection"],
)

# 页面最多等待350毫秒。超过后立即返回running，由页面轮询结果。
TRIGGER_WAIT_SECONDS = 0.35
_TRIGGER_LOCK = threading.Lock()
_TRIGGER_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="etl-trigger")

# 只允许映射到具体loader/builder，绝不接受脚本名、模块名或命令参数。
TRIGGER_TASKS = {
    "v2_course_pass_builder": {
        "name": "课程结果统计重建",
        "description": "根据已接入成绩重建首次、补考和重修通过统计。",
        "callable": "backend.etl.v2_course_pass_builder:build_course_pass_stat",
        "needsSourceFiles": False,
        "sourceCodes": ["grade", "legacy_grade", "substitution"],
    },
    "v2_teaching_loader": {
        "name": "教学任务与师资关系采集",
        "description": "接入教师、班主任、导师和教学任务文件并重建排课聚合。",
        "callable": "backend.etl.v2_teaching_loader:load_teaching",
        "needsSourceFiles": True,
        "sourceCodes": ["teacher", "class_adviser", "student_adviser", "lesson"],
    },
    "v2_grade_loader": {
        "name": "成绩与课程替代采集",
        "description": "接入成绩和课程替代文件并重建学生有效课程结果。",
        "callable": "backend.etl.v2_grade_loader:load_grades",
        "needsSourceFiles": True,
        "sourceCodes": ["grade", "substitution"],
    },
}

TASK_NAMES = {
    **{task: spec["name"] for task, spec in TRIGGER_TASKS.items()},
    "v2_master_loader": "基础主数据采集",
    "v2_student_plan_loader": "学籍与培养方案采集",
    "v2_history_loader": "历史学籍与异动采集",
    "v2_legacy_grade_bridge": "历史成绩桥接",
    "room_occupancy_loader": "实际教室占用采集",
    "run_etl_full": "完整分析库重建",
}

CHECK_LABELS = {
    "rows": "生成记录数",
    "rule_version": "计算规则版本",
    "grade_attempts": "成绩尝试记录",
    "effective_results": "学生有效课程结果",
    "effective_failures": "明确未通过结果",
    "effective_unknown_pass": "通过状态待核验",
    "grade_orphan_students": "未关联学籍学生",
    "grade_only_student_stubs": "仅有成绩的学生存根",
    "grade_courses_missing_master": "未关联课程主数据",
    "approved_substitutions": "已生效课程替代",
    "substitution_orphan_students": "替代记录未关联学生",
    "teachers": "教师记录",
    "mentor_scopes": "导师学生关系",
    "class_adviser_scopes": "班主任学生关系",
    "lessons": "教学任务",
    "lesson_teachers": "教学任务教师关系",
    "meetings": "排课时段记录",
    "unparsed_schedule_lessons": "未解析排课文本",
}

WARNING_KEY_PARTS = (
    "missing", "orphan", "invalid", "failed", "unknown", "unparsed",
    "pending", "duplicate", "error", "without",
)


def _resolve_task(task: str):
    spec = TRIGGER_TASKS[task]
    module_name, func_name = spec["callable"].split(":")
    return getattr(importlib.import_module(module_name), func_name)


def _v2_rw_conn() -> sqlite3.Connection:
    path = etl_config.V2_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone())


def _decode_json(raw, fallback):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _basename(path: str | None) -> str:
    return re.split(r"[\\/]", path or "")[-1] or "—"


def _safe_error(raw: str | None) -> str:
    if not raw:
        return ""
    text = re.sub(r"[A-Za-z]:[\\/][^\r\n,;]+", "[服务器路径已隐藏]", str(raw))
    return text[:260]


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _definition_rows(v2: sqlite3.Connection) -> list[dict]:
    if _table_exists(v2, "data_source_definition"):
        rows = dbm.query(v2, """
            SELECT * FROM data_source_definition WHERE active=1
            ORDER BY sort_order,source_code
        """)
        for row in rows:
            row["downstream_modules"] = _decode_json(
                row.pop("downstream_modules_json"), [],
            )
        return rows
    # 迁移尚未执行时只读降级，不把“目录不可用”伪装成源数据缺失。
    return [{
        **item,
        "active": 1,
        "catalog_version": CATALOG_VERSION,
    } for item in SOURCE_DEFINITIONS]


def _mapping_issue_counts(v2: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(v2, "code_mapping"):
        return {}
    domain_to_source = {
        "room_building": "room",
        "course_organization": "course",
        "student_plan": "plan_course",
    }
    result: dict[str, int] = {}
    for row in dbm.query(v2, """
        SELECT domain,COUNT(*) issue_count FROM code_mapping
        WHERE mapping_status='pending' GROUP BY domain
    """):
        source = domain_to_source.get(row["domain"])
        if source:
            result[source] = result.get(source, 0) + int(row["issue_count"])
    return result


def _room_issue_count(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "etl_room_occupancy_batch"):
        return 0
    return int(dbm.scalar(conn, """
        SELECT COALESCE(pending_building_rows,0)
        FROM etl_room_occupancy_batch ORDER BY imported_at DESC LIMIT 1
    """) or 0)


def _latest_batches(v2: sqlite3.Connection) -> dict[str, dict]:
    if not _table_exists(v2, "data_batch"):
        return {}
    rows = dbm.query(v2, """
        WITH ranked AS (
          SELECT b.*,ROW_NUMBER() OVER(
            PARTITION BY source_code ORDER BY ingested_at DESC,batch_id DESC
          ) rn
          FROM data_batch b
        )
        SELECT * FROM ranked WHERE rn=1
    """)
    return {row["source_code"]: row for row in rows}


def _latest_runs_by_source(v2: sqlite3.Connection) -> dict[str, dict]:
    if not (_table_exists(v2, "etl_run_batch")
            and _table_exists(v2, "etl_run")):
        return {}
    rows = dbm.query(v2, """
        WITH ranked AS (
          SELECT b.source_code,r.run_id,r.task,r.status,r.started_at,
                 r.finished_at,r.duration_ms,r.error,
                 ROW_NUMBER() OVER(
                   PARTITION BY b.source_code ORDER BY r.run_id DESC
                 ) rn
          FROM etl_run r
          JOIN etl_run_batch rb ON rb.run_id=r.run_id
          JOIN data_batch b ON b.batch_id=rb.batch_id
        )
        SELECT * FROM ranked WHERE rn=1
    """)
    return {row["source_code"]: row for row in rows}


def _build_source_rows(v2: sqlite3.Connection,
                       conn: sqlite3.Connection) -> list[dict]:
    batches = _latest_batches(v2)
    runs = _latest_runs_by_source(v2)
    mapping_issues = _mapping_issue_counts(v2)
    mapping_issues["room_occupancy"] = (
        mapping_issues.get("room_occupancy", 0) + _room_issue_count(conn)
    )
    now = datetime.now(timezone.utc)
    result = []
    for definition in _definition_rows(v2):
        source_code = definition["source_code"]
        batch = batches.get(source_code)
        run = runs.get(source_code)
        issue_count = (
            int(mapping_issues.get(source_code, 0))
            + int((batch or {}).get("rejected_count") or 0)
        )
        quality = str((batch or {}).get("quality_status") or "").lower()
        failed_quality = quality in {"failed", "error", "rejected"}
        last_time = _parse_time((batch or {}).get("ingested_at"))
        freshness_days = int(definition.get("freshness_days") or 0)
        age_days = (now - last_time).days if last_time else None
        overdue = bool(last_time and freshness_days and age_days > freshness_days)
        if not batch:
            access_status, access_label = "missing", "尚未接入"
        elif (run or {}).get("status") == "failed" or failed_quality:
            access_status, access_label = "failed", "最近处理失败"
        elif (run or {}).get("status") == "running":
            access_status, access_label = "running", "正在更新"
        elif overdue:
            access_status, access_label = "overdue", "超过更新周期"
        else:
            access_status, access_label = "connected", "已接入"
        if failed_quality:
            validation_status, validation_label = "failed", "校验失败"
        elif issue_count or quality in {"warning", "partial"}:
            validation_status, validation_label = "warning", "有待核验项"
        elif batch:
            validation_status, validation_label = "passed", "基础校验通过"
        else:
            validation_status, validation_label = "unavailable", "尚无校验"
        source_rows = (batch or {}).get("row_count")
        loaded_rows = (batch or {}).get("accepted_count")
        count_explanation = (
            "写入数是展开后的关系或事实记录数，可大于源文件行数。"
            if source_rows is not None and loaded_rows is not None
            and int(loaded_rows) > int(source_rows)
            else "源行数与写入数统计对象不同，不用于直接推算拒绝行。"
        )
        result.append({
            **definition,
            "sourceCode": source_code,
            "sourceName": definition["source_name"],
            "domainCode": definition["domain_code"],
            "domainName": definition["domain_name"],
            "sourceSystem": definition["source_system"],
            "deliveryMode": definition["delivery_mode"],
            "updateCycle": definition["update_cycle"],
            "freshnessDays": freshness_days,
            "requiredFields": definition["required_fields"],
            "downstreamModules": definition["downstream_modules"],
            "managementUse": definition["management_use"],
            "accessStatus": access_status,
            "accessStatusLabel": access_label,
            "validationStatus": validation_status,
            "validationStatusLabel": validation_label,
            "attentionCount": issue_count,
            "lastIngestedAt": (batch or {}).get("ingested_at"),
            "lastCollectedAt": (batch or {}).get("collected_at"),
            "ageDays": age_days,
            "batchId": (batch or {}).get("batch_id"),
            "sourceFile": _basename((batch or {}).get("source_file")),
            "sourceRows": source_rows,
            "loadedRows": loaded_rows,
            "rejectedRows": (batch or {}).get("rejected_count"),
            "countExplanation": count_explanation,
            "lastRun": {
                **(run or {}),
                "taskName": TASK_NAMES.get((run or {}).get("task"),
                                           (run or {}).get("task")),
                "errorSummary": _safe_error((run or {}).get("error")),
            } if run else None,
        })
    return result


def _priority_issues(sources: list[dict]) -> list[dict]:
    issues = []
    for source in sources:
        status = source["accessStatus"]
        if status in {"missing", "failed", "overdue"}:
            reason = {
                "missing": "尚未形成可用接入批次",
                "failed": "最近一次处理或质量校验失败",
                "overdue": (
                    f"距最近接入已{source['ageDays']}天，超过"
                    f"{source['freshnessDays']}天更新边界"
                ),
            }[status]
            issues.append({
                "issueKey": f"{status}:{source['sourceCode']}",
                "severity": "high" if status in {"missing", "failed"} else "medium",
                "sourceCode": source["sourceCode"],
                "sourceName": source["sourceName"],
                "title": f"{source['sourceName']} · {source['accessStatusLabel']}",
                "reason": reason,
                "impact": "、".join(source["downstreamModules"]),
                "action": "核查数据源与最近运行证据",
            })
        if source["attentionCount"]:
            issues.append({
                "issueKey": f"mapping:{source['sourceCode']}",
                "severity": "medium",
                "sourceCode": source["sourceCode"],
                "sourceName": source["sourceName"],
                "title": f"{source['sourceName']}有{source['attentionCount']}项待核验",
                "reason": "存在代码映射、空间匹配或源记录校验问题。",
                "impact": "、".join(source["downstreamModules"]),
                "action": "查看问题证据并反馈源系统核查",
            })
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(issues, key=lambda x: (order[x["severity"]], x["sourceName"]))


@router.get("/overview")
def data_collection_overview(
        user: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db),
        conn: sqlite3.Connection = Depends(get_db)):
    sources = _build_source_rows(v2, conn)
    priorities = _priority_issues(sources)
    connected = sum(row["accessStatus"] != "missing" for row in sources)
    overdue = sum(row["accessStatus"] == "overdue" for row in sources)
    failed_or_running = sum(
        row["accessStatus"] in {"failed", "running"} for row in sources
    )
    attention = sum(int(row["attentionCount"]) for row in sources)
    last_time = max(
        (row["lastIngestedAt"] for row in sources if row["lastIngestedAt"]),
        default=None,
    )
    domains: dict[str, int] = {}
    for row in sources:
        domains[row["domainName"]] = domains.get(row["domainName"], 0) + 1
    return ok({
        "catalogVersion": CATALOG_VERSION,
        "expectedSources": len(sources),
        "connectedSources": connected,
        "overdueSources": overdue,
        "failedOrRunningTasks": failed_or_running,
        "attentionItems": attention,
        "lastIngestedAt": last_time,
        "priorities": priorities[:8],
        "domains": [{"label": key, "count": value}
                    for key, value in domains.items()],
        "canTrigger": has_action(user, "etl.trigger"),
        "tasks": [{
            "task": task,
            **{key: value for key, value in spec.items()
               if key != "callable"},
        } for task, spec in TRIGGER_TASKS.items()],
        "boundary": (
            "本页核验平台已消费数据的接入状态和运行证据；"
            "源数据修订仍在学校业务系统完成。"
        ),
    })


@router.get("/sources")
def list_data_sources(
        domain: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        _: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db),
        conn: sqlite3.Connection = Depends(get_db)):
    rows = _build_source_rows(v2, conn)
    if domain:
        rows = [row for row in rows if row["domainCode"] == domain]
    if status:
        allowed = {
            "connected", "missing", "overdue", "failed", "running",
            "attention", "unstable",
        }
        if status not in allowed:
            raise ApiError("不支持的数据源状态", code=400, status_code=400)
        if status == "attention":
            rows = [row for row in rows if row["attentionCount"]]
        elif status == "unstable":
            rows = [row for row in rows
                    if row["accessStatus"] in {"failed", "running"}]
        else:
            rows = [row for row in rows if row["accessStatus"] == status]
    if keyword:
        key = keyword.strip().lower()
        rows = [row for row in rows if key in " ".join([
            row["sourceCode"], row["sourceName"], row["domainName"],
            row["sourceSystem"], " ".join(row["downstreamModules"]),
        ]).lower()]
    total = len(rows)
    start = (page - 1) * page_size
    return ok({
        "sources": rows[start:start + page_size],
        "total": total,
        "page": page,
        "pageSize": page_size,
    })


@router.get("/sources/{source_code}")
def data_source_detail(
        source_code: str,
        _: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db),
        conn: sqlite3.Connection = Depends(get_db)):
    sources = _build_source_rows(v2, conn)
    source = next(
        (row for row in sources if row["sourceCode"] == source_code), None,
    )
    if not source:
        raise ApiError("数据源不存在", code=404, status_code=404)
    batches = dbm.query(v2, """
        SELECT batch_id,source_file,collected_at,ingested_at,row_count,
               accepted_count,rejected_count,quality_status
        FROM data_batch WHERE source_code=?
        ORDER BY ingested_at DESC,batch_id DESC LIMIT 20
    """, (source_code,))
    for batch in batches:
        batch["source_file"] = _basename(batch["source_file"])
        batch["qualityLabel"] = (
            "有待核验项" if batch["quality_status"] in {"warning", "partial"}
            else "基础校验通过"
            if batch["quality_status"] in {"accepted", "passed", "ok"}
            else "校验失败"
        )
    mapping_domains = {
        "room": "room_building",
        "course": "course_organization",
        "plan_course": "student_plan",
    }
    mappings = []
    mapping_domain = mapping_domains.get(source_code)
    if mapping_domain and _table_exists(v2, "code_mapping"):
        mappings = dbm.query(v2, """
            SELECT domain,source_code,mapping_status,note
            FROM code_mapping WHERE domain=? AND mapping_status='pending'
            ORDER BY source_code LIMIT 100
        """, (mapping_domain,))
    room_quality = None
    if source_code == "room_occupancy" and _table_exists(
            conn, "etl_room_occupancy_batch"):
        room_quality = dbm.query_one(conn, """
            SELECT semester_id,source_rows,loaded_rows,observed_rooms,
                   mapped_building_rows,pending_building_rows,
                   pii_redacted_rows,overlap_rows,invalid_rows,quality_json
            FROM etl_room_occupancy_batch
            ORDER BY imported_at DESC LIMIT 1
        """)
        if room_quality:
            room_quality["quality"] = _decode_json(
                room_quality.pop("quality_json"), {},
            )
    runs = []
    if _table_exists(v2, "etl_run_batch"):
        runs = dbm.query(v2, """
            SELECT DISTINCT r.run_id,r.task,r.status,r.started_at,r.finished_at,
                   r.duration_ms,r.rows_written,r.triggered_by,r.error
            FROM etl_run r
            JOIN etl_run_batch rb ON rb.run_id=r.run_id
            JOIN data_batch b ON b.batch_id=rb.batch_id
            WHERE b.source_code=?
            ORDER BY r.run_id DESC LIMIT 20
        """, (source_code,))
        for run in runs:
            run["taskName"] = TASK_NAMES.get(run["task"], run["task"])
            run["errorSummary"] = _safe_error(run.pop("error"))
    return ok({
        "source": source,
        "batches": batches,
        "mappings": mappings,
        "roomQuality": room_quality,
        "runs": runs,
        "governance": {
            "correctionBoundary": (
                "问题在源业务系统或数据交换平台核查修订；"
                "本平台不直接修改学校业务主数据。"
            ),
            "countBoundary": source["countExplanation"],
        },
    })


@router.get("/batches")
def list_data_batches(
        source: Optional[str] = None,
        quality: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        _: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db)):
    conds, params = ["1=1"], []
    if source:
        conds.append("b.source_code=?")
        params.append(source)
    if quality:
        conds.append("b.quality_status=?")
        params.append(quality)
    where = " AND ".join(conds)
    total = int(dbm.scalar(
        v2, f"SELECT COUNT(*) FROM data_batch b WHERE {where}", tuple(params),
    ) or 0)
    has_link = _table_exists(v2, "etl_run_batch")
    link_select = """
        (SELECT r.status FROM etl_run_batch rb JOIN etl_run r
          ON r.run_id=rb.run_id WHERE rb.batch_id=b.batch_id
          ORDER BY r.run_id DESC LIMIT 1) last_run_status
    """ if has_link else "NULL last_run_status"
    rows = dbm.query(v2, f"""
        SELECT b.batch_id,b.source_code,b.source_file,b.collected_at,
               b.ingested_at,b.row_count,b.accepted_count,b.rejected_count,
               b.quality_status,{link_select}
        FROM data_batch b WHERE {where}
        ORDER BY b.ingested_at DESC,b.batch_id DESC
        LIMIT ? OFFSET ?
    """, tuple(params) + (page_size, (page - 1) * page_size))
    for row in rows:
        row["source_file"] = _basename(row["source_file"])
    return ok({
        "batches": rows, "total": total, "page": page, "pageSize": page_size,
    })


@router.get("/runs")
def list_etl_runs(
        task: Optional[str] = None,
        status: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        _: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db)):
    if not _table_exists(v2, "etl_run"):
        return ok({"runs": [], "total": 0, "page": page, "pageSize": page_size})
    conds, params = ["1=1"], []
    if task:
        conds.append("r.task=?")
        params.append(task)
    if status:
        if status not in {"running", "success", "failed"}:
            raise ApiError(
                "status仅支持running/success/failed",
                code=400, status_code=400,
            )
        conds.append("r.status=?")
        params.append(status)
    where = " AND ".join(conds)
    total = int(dbm.scalar(
        v2, f"SELECT COUNT(*) FROM etl_run r WHERE {where}", tuple(params),
    ) or 0)
    has_link = _table_exists(v2, "etl_run_batch")
    link_select = """
        COUNT(DISTINCT rb.batch_id) batch_count,
        GROUP_CONCAT(DISTINCT d.source_name) source_names
    """ if has_link else "0 batch_count,NULL source_names"
    link_join = """
        LEFT JOIN etl_run_batch rb ON rb.run_id=r.run_id
        LEFT JOIN data_batch b ON b.batch_id=rb.batch_id
        LEFT JOIN data_source_definition d ON d.source_code=b.source_code
    """ if has_link else ""
    rows = dbm.query(v2, f"""
        SELECT r.run_id,r.task,r.batch_id,r.started_at,r.finished_at,
               r.duration_ms,r.status,r.rows_read,r.rows_written,r.error,
               r.triggered_by,r.source,{link_select}
        FROM etl_run r {link_join}
        WHERE {where}
        GROUP BY r.run_id
        ORDER BY r.run_id DESC LIMIT ? OFFSET ?
    """, tuple(params) + (page_size, (page - 1) * page_size))
    for row in rows:
        row["taskName"] = TASK_NAMES.get(row["task"], row["task"])
        row["sourceNames"] = (
            row.pop("source_names").split(",")
            if row.get("source_names") else []
        )
        row["errorSummary"] = _safe_error(row.pop("error"))
    return ok({"runs": rows, "total": total, "page": page, "pageSize": page_size})


def _check_items(raw: str | None) -> tuple[list[dict], object]:
    decoded = _decode_json(raw, raw or {})
    if not isinstance(decoded, dict):
        return [], decoded
    items = []
    for key, value in decoded.items():
        warning = (
            any(part in key.lower() for part in WARNING_KEY_PARTS)
            and ((isinstance(value, (int, float)) and value > 0)
                 or (isinstance(value, list) and len(value) > 0)
                 or (isinstance(value, str) and bool(value)))
        )
        items.append({
            "key": key,
            "label": CHECK_LABELS.get(key, key.replace("_", " ")),
            "value": value,
            "status": "warning" if warning else "passed",
        })
    return items, decoded


@router.get("/runs/{run_id}")
def etl_run_detail(
        run_id: int,
        _: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db)):
    run = dbm.query_one(v2, "SELECT * FROM etl_run WHERE run_id=?", (run_id,))
    if not run:
        raise ApiError("运行记录不存在", code=404, status_code=404)
    batches = []
    if _table_exists(v2, "etl_run_batch"):
        batches = dbm.query(v2, """
            SELECT b.batch_id,b.source_code,d.source_name,b.source_file,
                   b.ingested_at,b.row_count,b.accepted_count,b.quality_status,
                   rb.relation_type
            FROM etl_run_batch rb
            JOIN data_batch b ON b.batch_id=rb.batch_id
            LEFT JOIN data_source_definition d ON d.source_code=b.source_code
            WHERE rb.run_id=? ORDER BY d.sort_order,b.source_code
        """, (run_id,))
        for batch in batches:
            batch["source_file"] = _basename(batch["source_file"])
    check_items, raw_checks = _check_items(run.get("checks_json"))
    run["taskName"] = TASK_NAMES.get(run["task"], run["task"])
    run["errorSummary"] = _safe_error(run.get("error"))
    return ok({
        "run": run,
        "batches": batches,
        "checks": check_items,
        "technicalEvidence": {
            "checks": raw_checks,
            "rawError": run.get("error"),
            "taskCode": run["task"],
            "runId": run_id,
        },
        "boundary": (
            "主视图只解释管理可读结论；原始校验字段和错误仅作为受限技术证据。"
        ),
    })


@router.get("/checklist.csv")
def export_data_source_checklist(
        _: dict = Depends(require_admin),
        v2: sqlite3.Connection = Depends(get_v2_db),
        conn: sqlite3.Connection = Depends(get_db)):
    rows = _build_source_rows(v2, conn)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([
        "数据域", "数据源", "来源系统", "交付方式", "关键字段",
        "建议更新周期", "接入状态", "校验状态", "待核验项",
        "最近接入时间", "影响模块", "管理用途",
    ])
    for row in rows:
        writer.writerow([
            row["domainName"], row["sourceName"], row["sourceSystem"],
            row["deliveryMode"], row["requiredFields"], row["updateCycle"],
            row["accessStatusLabel"], row["validationStatusLabel"],
            row["attentionCount"], row["lastIngestedAt"] or "",
            "；".join(row["downstreamModules"]), row["managementUse"],
        ])
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                "attachment; filename=data-source-checklist.csv",
        },
    )


class TriggerIn(BaseModel):
    task: str


def _run_trigger(task: str, username: str):
    try:
        report = _resolve_task(task)(triggered_by=username)
        return "success", {"report": report}
    except RunConflictError as exc:
        return "conflict", {"error": str(exc)}
    except Exception as exc:
        return "failed", {"error": str(exc)[:500]}


@router.post("/trigger")
def trigger_collection_task(
        body: TriggerIn,
        user: dict = Depends(get_current_user),
        conn: sqlite3.Connection = Depends(get_db_rw)):
    if not has_action(user, "etl.trigger"):
        raise ApiError("无权限触发数据采集任务", code=403, status_code=403)
    task = (body.task or "").strip()
    if task not in TRIGGER_TASKS:
        raise ApiError(
            "任务不在受控白名单中：" + (task or "（空）"),
            code=400, status_code=400,
        )
    with _TRIGGER_LOCK:
        guard = _v2_rw_conn()
        try:
            running = dbm.query_one(guard, """
                SELECT run_id,started_at,triggered_by FROM etl_run
                WHERE task=? AND status='running'
            """, (task,))
        finally:
            guard.close()
        if running:
            raise ApiError(
                f"任务正在执行中（run_id={running['run_id']}），请勿重复触发",
                code=409, status_code=409,
            )
        future = _TRIGGER_POOL.submit(_run_trigger, task, user["username"])
        try:
            status, detail = future.result(timeout=TRIGGER_WAIT_SECONDS)
        except FutureTimeout:
            run = None
            peek = _v2_rw_conn()
            try:
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
            }, msg="任务已受理，可离开当前页面并稍后查看运行结果")

    if status == "conflict":
        raise ApiError(detail["error"], code=409, status_code=409)
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
            "error": _safe_error(detail["error"]),
        }, msg="任务执行失败，请查看运行证据")
    return ok({
        "task": task, "status": "success",
        "runId": (run or {}).get("run_id"),
        "durationMs": (run or {}).get("duration_ms"),
        "rowsWritten": (run or {}).get("rows_written"),
    }, msg="任务执行完成")
