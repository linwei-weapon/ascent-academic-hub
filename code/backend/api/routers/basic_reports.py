"""基础报表查询与 Excel 导出接口。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..basic_reports.catalog import REPORTS, get_report
from ..basic_reports.exporter import build_workbook
from ..basic_reports.service import build_report, options, validate_token
from ..deps import get_current_user, get_db, get_v2_db
from ..envelope import ApiError, ok
from ..permission_context import has_action

router = APIRouter(prefix="/api/admin/basic-reports", tags=["basic-reports"])


def _report(slug: str):
    try:
        return get_report(slug)
    except KeyError:
        raise ApiError("基础报表不存在", code=404, status_code=404)


def _filters(semester_id: str, entry_grade: int | None, organization_id: str | None,
             major_code: str | None, class_code: str | None) -> dict:
    return {"semesterId": semester_id, "entryGrade": entry_grade,
            "organizationId": organization_id, "majorCode": major_code,
            "classCode": class_code}


def _normalize_class_code(report, class_code: str | None) -> str | None:
    """RPT-02、RPT-04A、RPT-05 不提供班级筛选；直接 API 请求同样忽略该参数。"""
    return None if report.report_id in {"RPT-02", "RPT-04A", "RPT-05"} else class_code


def _normalize_major_code(report, major_code: str | None) -> str | None:
    """RPT-02 按学院展示各专业，直接 API 请求同样忽略专业参数。"""
    return None if report.report_id == "RPT-02" else major_code


@router.get("/options")
def report_options(v2: sqlite3.Connection = Depends(get_v2_db),
                   user: dict = Depends(get_current_user)):
    menus = set((user.get("permission_context") or {}).get("menuPermissions") or [])
    if not menus.intersection(item.menu_path for item in REPORTS.values()):
        raise ApiError("当前工作身份没有基础报表权限", code=403, status_code=403)
    return ok(options(v2, user))


@router.get("/{slug}/export")
def export_report(
    slug: str,
    semester_id: str = Query(..., alias="semesterId"),
    entry_grade: int | None = Query(None, alias="entryGrade", ge=2000, le=2100),
    snapshot_token: str = Query(..., alias="snapshotToken"),
    organization_id: str | None = Query(None, alias="organizationId"),
    major_code: str | None = Query(None, alias="majorCode"),
    class_code: str | None = Query(None, alias="classCode"),
    v1: sqlite3.Connection = Depends(get_db), v2: sqlite3.Connection = Depends(get_v2_db),
    user: dict = Depends(get_current_user),
):
    report = _report(slug)
    major_code = _normalize_major_code(report, major_code)
    class_code = _normalize_class_code(report, class_code)
    if not has_action(user, "export.authorized"):
        raise ApiError("当前工作身份没有授权导出权限", code=403, status_code=403)
    token_filters = _filters(semester_id, entry_grade, organization_id, major_code, class_code)
    validate_token(snapshot_token, report, user, token_filters)
    payload = build_report(v1, v2, user, report, semester_id=semester_id,
                           entry_grade=entry_grade, organization_id=organization_id,
                           major_code=major_code, class_code=class_code)
    if payload["status"] in {"source_unavailable", "detail_forbidden"}:
        raise ApiError("当前报表状态没有可导出的正式结果", code=409, status_code=409)
    content = build_workbook(payload, user)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    grade_label = f"{entry_grade}级" if entry_grade is not None else "全部年级"
    filename = f"{report.report_id}_{report.title}_{semester_id}_{grade_label}_{timestamp}.xlsx"
    return StreamingResponse(iter([content]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                                      "X-Report-Row-Count": str(payload["total"]),
                                      "X-Report-Snapshot": payload["snapshotToken"]})


@router.get("/{slug}")
def query_report(
    slug: str,
    semester_id: str = Query(..., alias="semesterId"),
    entry_grade: int | None = Query(None, alias="entryGrade", ge=2000, le=2100),
    organization_id: str | None = Query(None, alias="organizationId"),
    major_code: str | None = Query(None, alias="majorCode"),
    class_code: str | None = Query(None, alias="classCode"),
    v1: sqlite3.Connection = Depends(get_db), v2: sqlite3.Connection = Depends(get_v2_db),
    user: dict = Depends(get_current_user),
):
    report = _report(slug)
    major_code = _normalize_major_code(report, major_code)
    class_code = _normalize_class_code(report, class_code)
    return ok(build_report(v1, v2, user, report, semester_id=semester_id,
                           entry_grade=entry_grade, organization_id=organization_id,
                           major_code=major_code, class_code=class_code))
