"""Versioned metric catalog used by system governance.

The customer-facing confirmation document remains the readable catalogue during
the prototype stage.  This module turns its structured metric tables into a
queryable registry and overlays implementation evidence that is owned by code.
It deliberately does not execute formula text or allow UI-authored SQL.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


METRIC_CODE_RE = re.compile(r"^[A-Z]+-\d{2}$")

DOMAIN_BY_PREFIX = {
    "O": "教学数据总览",
    "G": "成绩与修读结果",
    "A": "学业预警监控",
    "P": "培养质量分析",
    "C": "课程质量分析",
    "T": "开课与教学运行",
    "L": "教室资源分析",
    "S": "调停课分析",
    "H": "历史排课规律",
    "F": "师资保障分析",
    "D": "学生成长与学业分析",
    "Q": "排课策略优化",
    "R": "管理决策专题",
}

CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS sys_metric_definition (
    metric_id TEXT PRIMARY KEY,
    technical_kpi_id TEXT,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    formula TEXT NOT NULL,
    boundary TEXT,
    management_value TEXT,
    definition_status TEXT NOT NULL DEFAULT 'pending_confirmation',
    implementation_status TEXT NOT NULL DEFAULT 'unverified',
    data_source TEXT,
    grain TEXT,
    update_cycle TEXT,
    version TEXT NOT NULL DEFAULT '1.0',
    source_kind TEXT NOT NULL DEFAULT 'definition',
    definition_source TEXT NOT NULL,
    page_refs TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_metric_definition_domain_status
ON sys_metric_definition(domain,definition_status,implementation_status);
CREATE INDEX IF NOT EXISTS idx_metric_definition_technical
ON sys_metric_definition(technical_kpi_id);

CREATE TABLE IF NOT EXISTS sys_metric_page_binding (
    binding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_id TEXT NOT NULL,
    page_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    implementation_version TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    evidence_note TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(metric_id,page_path)
);
CREATE INDEX IF NOT EXISTS idx_metric_page_binding_page
ON sys_metric_page_binding(page_path,verification_status);
"""


# Only bindings with explicit calculation/page evidence are marked verified.
# Unmapped catalogue rows remain "unverified", which means "not yet bound to
# implementation evidence", not necessarily that the feature is absent.
IMPLEMENTED_METRICS = {
    "O-01": {
        "technical_kpi_id": "student_count",
        "status": "published",
        "data_source": "dim_student",
        "grain": "学生",
        "update_cycle": "学籍同步后",
        "version": "2.0",
        "pages": [("/admin/dashboard", "在籍学生数")],
    },
    "O-10": {
        "technical_kpi_id": "current_fail_rate",
        "status": "published",
        "data_source": "fact_grade",
        "grain": "学生×学期",
        "update_cycle": "成绩发布后",
        "version": "2.0",
        "pages": [("/admin/dashboard", "当前挂科学生率")],
    },
    "O-13": {
        "technical_kpi_id": "alert_count",
        "status": "published",
        "data_source": "fact_alert / alert_event",
        "grain": "学生×计算批次",
        "update_cycle": "预警重算后",
        "version": "2.0",
        "pages": [
            ("/admin/dashboard", "当前有效预警学生数"),
            ("/admin/alert", "当前预警学生数"),
        ],
    },
    "G-08": {
        "technical_kpi_id": "history_fail_rate",
        "status": "published",
        "data_source": "fact_grade / grade_attempt",
        "grain": "学生×观察期",
        "update_cycle": "成绩发布后",
        "version": "2.0",
        "pages": [
            ("/admin/dashboard", "历史挂科经历率"),
            ("/admin/students/analysis", "历史挂科经历率"),
        ],
    },
    "G-13": {
        "technical_kpi_id": "course_makeup_pass_rate",
        "status": "published",
        "data_source": "agg_course_pass_stat",
        "grain": "课程×学期",
        "update_cycle": "成绩发布后",
        "version": "1.1",
        "pages": [("/admin/operation/course-quality", "课程补考通过率")],
    },
    "G-16": {
        "technical_kpi_id": "course_retake_pass_rate",
        "status": "published",
        "data_source": "agg_course_pass_stat",
        "grain": "课程×学期",
        "update_cycle": "成绩发布后",
        "version": "1.1",
        "pages": [("/admin/operation/course-quality", "课程重修通过率")],
    },
    "C-05": {
        "technical_kpi_id": "course_first_pass_rate",
        "status": "published",
        "data_source": "agg_course_pass_stat",
        "grain": "课程×学期",
        "update_cycle": "成绩发布后",
        "version": "1.1",
        "pages": [("/admin/operation/course-quality", "课程首次通过率")],
    },
    "C-18": {
        "technical_kpi_id": "public_required_first_pass_rate",
        "status": "published",
        "data_source": "agg_course_pass_stat",
        "grain": "课程组×学期",
        "update_cycle": "成绩发布后",
        "version": "1.1",
        "pages": [
            ("/admin/dashboard", "公共必修首次通过率"),
            ("/admin/operation/course-quality", "公共必修首次通过率"),
        ],
    },
    "T-01": {
        "technical_kpi_id": "course_count",
        "status": "published",
        "data_source": "fact_lesson / teaching_lesson",
        "grain": "课程×学期",
        "update_cycle": "教学任务同步后",
        "version": "2.0",
        "pages": [
            ("/admin/dashboard", "本学期开课门数"),
            ("/admin/operation/courses", "开课课程数"),
        ],
    },
}


TECHNICAL_ONLY_METRICS = (
    {
        "metric_id": "CTX-TEACHER-COUNT",
        "technical_kpi_id": "teacher_count",
        "domain": "分析范围背景",
        "name": "相关授课教师数",
        "formula": "当前授权学生范围内有授课关系的教师去重；全校范围按有效教师主数据去重",
        "boundary": "仅作为分析范围背景，不作为教师个人或学院绩效指标。",
        "management_value": "说明当前分析所覆盖的教师规模。",
        "definition_status": "context",
        "implementation_status": "verified",
        "data_source": "dim_teacher / fact_lesson",
        "grain": "教师×学期",
        "update_cycle": "教师主数据和教学任务同步后",
        "version": "2.0",
        "source_kind": "context",
        "definition_source": "代码实现登记",
        "pages": [("/admin/dashboard", "相关授课教师数")],
    },
    {
        "metric_id": "LEGACY-GRAD-RATE",
        "technical_kpi_id": "grad_rate",
        "domain": "历史兼容",
        "name": "应届毕业率（已停用）",
        "formula": "按期毕业人数÷应届毕业审核范围人数",
        "boundary": "原型当前只有合成毕业结果，不进入正式管理结论。",
        "management_value": "保留历史兼容和迁移证据，不在现行页面展示。",
        "definition_status": "deprecated",
        "implementation_status": "retired",
        "data_source": "fact_graduation",
        "grain": "学生×毕业年度",
        "update_cycle": "毕业审核数据同步后",
        "version": "1.0",
        "source_kind": "legacy",
        "definition_source": "历史兼容登记",
        "pages": [],
    },
    {
        "metric_id": "LEGACY-DEGREE-RATE",
        "technical_kpi_id": "degree_rate",
        "domain": "历史兼容",
        "name": "学位授予率（已停用）",
        "formula": "获得学位人数÷学位审核范围人数",
        "boundary": "原型当前只有合成学位结果，不进入正式管理结论。",
        "management_value": "保留历史兼容和迁移证据，不在现行页面展示。",
        "definition_status": "deprecated",
        "implementation_status": "retired",
        "data_source": "fact_graduation",
        "grain": "学生×毕业年度",
        "update_cycle": "学位审核数据同步后",
        "version": "1.0",
        "source_kind": "legacy",
        "definition_source": "历史兼容登记",
        "pages": [],
    },
)


def default_confirmation_doc() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / (
        "本科教学分析与学业决策支持平台需求调研及指标口径确认书V2.md"
    )


def parse_confirmation_metrics(path: Path | None = None) -> list[dict]:
    source = path or default_confirmation_doc()
    if not source.exists():
        return []
    metrics: dict[str, dict] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not METRIC_CODE_RE.fullmatch(cells[0]):
            continue
        metric_id, name, formula, boundary, management_value = cells[:5]
        metrics[metric_id] = {
            "metric_id": metric_id,
            "domain": DOMAIN_BY_PREFIX.get(metric_id.split("-", 1)[0], "其他"),
            "name": name,
            "formula": formula,
            "boundary": boundary,
            "management_value": management_value,
        }
    return list(metrics.values())


def ensure_metric_catalog(conn, document_path: Path | None = None) -> int:
    conn.executescript(CATALOG_DDL)
    for item in parse_confirmation_metrics(document_path):
        conn.execute(
            """INSERT INTO sys_metric_definition(
                metric_id,domain,name,formula,boundary,management_value,
                definition_status,implementation_status,definition_source
            ) VALUES(?,?,?,?,?,?,'pending_confirmation','unverified',?)
            ON CONFLICT(metric_id) DO UPDATE SET
                domain=excluded.domain,name=excluded.name,formula=excluded.formula,
                boundary=excluded.boundary,management_value=excluded.management_value,
                definition_source=excluded.definition_source,
                updated_at=datetime('now','localtime')
            """,
            (
                item["metric_id"], item["domain"], item["name"], item["formula"],
                item["boundary"], item["management_value"],
                "需求调研及指标口径确认书V2",
            ),
        )

    for metric_id, evidence in IMPLEMENTED_METRICS.items():
        conn.execute(
            """UPDATE sys_metric_definition SET
                technical_kpi_id=?,definition_status=?,
                implementation_status='verified',data_source=?,grain=?,
                update_cycle=?,version=?,source_kind='formal',
                updated_at=datetime('now','localtime')
               WHERE metric_id=?""",
            (
                evidence["technical_kpi_id"], evidence["status"],
                evidence["data_source"], evidence["grain"],
                evidence["update_cycle"], evidence["version"], metric_id,
            ),
        )
        if conn.execute(
            "SELECT 1 FROM sys_metric_definition WHERE metric_id=?", (metric_id,)
        ).fetchone():
            _replace_page_bindings(
                conn, metric_id, evidence["version"], evidence["pages"]
            )

    for item in TECHNICAL_ONLY_METRICS:
        conn.execute(
            """INSERT INTO sys_metric_definition(
                metric_id,technical_kpi_id,domain,name,formula,boundary,
                management_value,definition_status,implementation_status,
                data_source,grain,update_cycle,version,source_kind,
                definition_source,page_refs
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')
            ON CONFLICT(metric_id) DO UPDATE SET
                technical_kpi_id=excluded.technical_kpi_id,
                domain=excluded.domain,name=excluded.name,formula=excluded.formula,
                boundary=excluded.boundary,management_value=excluded.management_value,
                definition_status=excluded.definition_status,
                implementation_status=excluded.implementation_status,
                data_source=excluded.data_source,grain=excluded.grain,
                update_cycle=excluded.update_cycle,version=excluded.version,
                source_kind=excluded.source_kind,
                definition_source=excluded.definition_source,
                updated_at=datetime('now','localtime')""",
            tuple(item[key] for key in (
                "metric_id", "technical_kpi_id", "domain", "name", "formula",
                "boundary", "management_value", "definition_status",
                "implementation_status", "data_source", "grain", "update_cycle",
                "version", "source_kind", "definition_source",
            )),
        )
        _replace_page_bindings(conn, item["metric_id"], item["version"], item["pages"])

    conn.execute(
        """UPDATE sys_metric_definition SET page_refs=COALESCE((
            SELECT json_group_array(page_path)
            FROM sys_metric_page_binding b
            WHERE b.metric_id=sys_metric_definition.metric_id
        ),'[]')"""
    )
    return conn.execute("SELECT COUNT(*) FROM sys_metric_definition").fetchone()[0]


def _replace_page_bindings(
    conn, metric_id: str, version: str, pages: Iterable[tuple[str, str]]
) -> None:
    conn.execute("DELETE FROM sys_metric_page_binding WHERE metric_id=?", (metric_id,))
    for path, display_name in pages:
        conn.execute(
            """INSERT INTO sys_metric_page_binding(
                metric_id,page_path,display_name,definition_version,
                implementation_version,verification_status,evidence_note
            ) VALUES(?,?,?,?,?,'verified',?)""",
            (
                metric_id, path, display_name, version, version,
                "指标定义、页面引用与当前代码实现已建立显式绑定。",
            ),
        )
