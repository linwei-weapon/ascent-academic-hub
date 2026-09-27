"""Unified, versioned and read-only-at-runtime metric catalog.

Writes are deliberately confined to :func:`migrate_metric_catalog_v2`.
Runtime repository functions only issue SELECT statements and fail closed when
the migration has not been applied.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

from .metric_catalog import ensure_metric_catalog, parse_confirmation_metrics
from .metric_catalog_verified import (
    VERIFIED_ALIASES,
    VERIFIED_DEPENDENCIES,
    VERIFIED_ISSUES,
    VERIFIED_RULE_BINDINGS,
    VERIFIED_USAGE_POINTS,
    iter_verified_metric_seeds,
)
from .metric_catalog_specification import (
    ensure_specification_schema,
    parse_specification,
    refresh_specifications,
)


SCHEMA_VERSION = "metric-catalog-v2.1"

V2_REQUIRED_TABLES = {
    "sys_metric_candidate",
    "sys_metric_registry",
    "sys_metric_version",
    "sys_metric_alias",
    "sys_metric_tag",
    "sys_metric_tag_link",
    "sys_metric_module",
    "sys_metric_feature_point",
    "sys_metric_usage",
    "sys_metric_dependency",
    "sys_metric_rule_binding",
    "sys_metric_evidence",
    "sys_metric_issue",
    "sys_metric_snapshot",
    "sys_metric_spec_override",
    "sys_metric_spec_override_revision",
}

CATALOG_V2_DDL = """
CREATE TABLE IF NOT EXISTS sys_metric_candidate (
    candidate_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    metric_code TEXT,
    name TEXT NOT NULL,
    domain TEXT,
    formula TEXT,
    description TEXT,
    boundary TEXT,
    candidate_status TEXT NOT NULL DEFAULT 'pending_verification',
    payload_json TEXT NOT NULL DEFAULT '{}',
    specification_json TEXT NOT NULL DEFAULT '{}',
    specification_status TEXT NOT NULL DEFAULT 'needs_review',
    specification_source TEXT NOT NULL DEFAULT 'deterministic_normalization',
    specification_updated_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(source_kind,source_key)
);
CREATE INDEX IF NOT EXISTS idx_metric_candidate_status
ON sys_metric_candidate(candidate_status,domain,name);

CREATE TABLE IF NOT EXISTS sys_metric_registry (
    metric_id TEXT PRIMARY KEY,
    metric_code TEXT NOT NULL UNIQUE,
    technical_kpi_id TEXT,
    current_version_id TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    source_kind TEXT NOT NULL DEFAULT 'formal',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_metric_registry_technical
ON sys_metric_registry(technical_kpi_id);

CREATE TABLE IF NOT EXISTS sys_metric_version (
    version_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    version_no TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    formula TEXT NOT NULL,
    boundary TEXT,
    management_value TEXT,
    domain TEXT NOT NULL,
    unit TEXT,
    value_type TEXT,
    grain TEXT,
    data_source TEXT,
    update_cycle TEXT,
    definition_status TEXT NOT NULL,
    implementation_status TEXT NOT NULL,
    effective_status TEXT NOT NULL DEFAULT 'current',
    source_ref TEXT NOT NULL,
    specification_json TEXT NOT NULL DEFAULT '{}',
    specification_status TEXT NOT NULL DEFAULT 'needs_review',
    specification_source TEXT NOT NULL DEFAULT 'deterministic_normalization',
    specification_updated_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(metric_id,version_no),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id)
);
CREATE INDEX IF NOT EXISTS idx_metric_version_search
ON sys_metric_version(domain,name,definition_status,implementation_status);

CREATE TABLE IF NOT EXISTS sys_metric_alias (
    alias_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'display',
    source_ref TEXT,
    UNIQUE(metric_id,alias,alias_type),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id)
);
CREATE INDEX IF NOT EXISTS idx_metric_alias_value ON sys_metric_alias(alias);

CREATE TABLE IF NOT EXISTS sys_metric_tag (
    tag_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tag_type TEXT NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sys_metric_tag_link (
    metric_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    source_ref TEXT,
    PRIMARY KEY(metric_id,tag_id),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id),
    FOREIGN KEY(tag_id) REFERENCES sys_metric_tag(tag_id)
);

CREATE TABLE IF NOT EXISTS sys_metric_module (
    module_id TEXT PRIMARY KEY,
    parent_id TEXT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    module_level INTEGER NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(parent_id) REFERENCES sys_metric_module(module_id)
);
CREATE TABLE IF NOT EXISTS sys_metric_feature_point (
    feature_point_id TEXT PRIMARY KEY,
    module_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    source_ref TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(module_id,name),
    FOREIGN KEY(module_id) REFERENCES sys_metric_module(module_id)
);
CREATE TABLE IF NOT EXISTS sys_metric_usage (
    usage_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    feature_point_id TEXT NOT NULL,
    usage_type TEXT NOT NULL DEFAULT 'display',
    occurrence_key TEXT NOT NULL,
    display_name TEXT,
    source_ref TEXT NOT NULL,
    UNIQUE(metric_id,feature_point_id,usage_type,occurrence_key),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id),
    FOREIGN KEY(feature_point_id) REFERENCES sys_metric_feature_point(feature_point_id)
);
CREATE INDEX IF NOT EXISTS idx_metric_usage_metric ON sys_metric_usage(metric_id);
CREATE INDEX IF NOT EXISTS idx_metric_usage_feature ON sys_metric_usage(feature_point_id);

CREATE TABLE IF NOT EXISTS sys_metric_dependency (
    dependency_id TEXT PRIMARY KEY,
    source_metric_id TEXT NOT NULL,
    target_metric_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'calculation_input',
    description TEXT,
    source_ref TEXT NOT NULL,
    UNIQUE(source_metric_id,target_metric_id,relation_type),
    CHECK(source_metric_id<>target_metric_id),
    FOREIGN KEY(source_metric_id) REFERENCES sys_metric_registry(metric_id),
    FOREIGN KEY(target_metric_id) REFERENCES sys_metric_registry(metric_id)
);
CREATE INDEX IF NOT EXISTS idx_metric_dependency_target
ON sys_metric_dependency(target_metric_id);

CREATE TABLE IF NOT EXISTS sys_metric_rule_binding (
    binding_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'input',
    description TEXT,
    source_ref TEXT NOT NULL,
    UNIQUE(metric_id,rule_type,rule_id,role),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id)
);
CREATE TABLE IF NOT EXISTS sys_metric_evidence (
    evidence_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    description TEXT,
    verification_status TEXT NOT NULL DEFAULT 'verified',
    verified_at TEXT,
    UNIQUE(metric_id,evidence_type,source_ref),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id)
);
CREATE TABLE IF NOT EXISTS sys_metric_issue (
    issue_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    status TEXT NOT NULL DEFAULT 'open',
    description TEXT NOT NULL,
    source_ref TEXT,
    UNIQUE(metric_id,issue_type,description),
    FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id)
);
CREATE TABLE IF NOT EXISTS sys_metric_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    source_digest TEXT NOT NULL UNIQUE,
    candidate_count INTEGER NOT NULL,
    metric_count INTEGER NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


MODULE_SEEDS: tuple[tuple[str, str | None, str, str, int, int], ...] = (
    ("/admin/analysis", None, "教学管理分析", "/admin/analysis", 1, 100),
    ("/admin/dashboard", "/admin/analysis", "教学数据总览", "/admin/dashboard", 2, 101),
    ("/admin/alert", "/admin/analysis", "学业预警监控", "/admin/alert", 2, 102),
    ("/admin/operation/courses", "/admin/analysis", "教学运行分析", "/admin/operation/courses", 2, 103),
    ("/admin/operation/schedule-analysis", "/admin/operation/courses", "排课策略分析", "/admin/operation/schedule-analysis", 3, 1031),
    ("/admin/operation/classroom", "/admin/operation/courses", "教室占用分析", "/admin/operation/classroom", 3, 1032),
    ("/admin/operation/teacher-load", "/admin/operation/courses", "教师负荷分析", "/admin/operation/teacher-load", 3, 1033),
    ("/admin/operation/schedule-changes", "/admin/operation/courses", "调停课分析", "/admin/operation/schedule-changes", 3, 1034),
    ("/admin/operation/course-quality", "/admin/operation/courses", "课程质量", "/admin/operation/course-quality", 3, 1035),
    ("/admin/curriculum", "/admin/analysis", "培养质量分析", "/admin/curriculum", 2, 104),
    ("/admin/curriculum?tab=progress", "/admin/curriculum", "学生培养进度", "/admin/curriculum?tab=progress", 3, 1041),
    ("/admin/curriculum?tab=graduation-readiness", "/admin/curriculum", "毕业准备核查", "/admin/curriculum?tab=graduation-readiness", 3, 1042),
    ("/admin/faculty", "/admin/analysis", "师资保障分析", "/admin/faculty", 2, 105),
    ("/admin/students/analysis", "/admin/analysis", "学生成长与学业分析", "/admin/students/analysis", 2, 106),
    ("/admin/basic-reports", None, "基础报表", "/admin/basic-reports", 1, 200),
    ("/admin/basic-reports/failure-overview", "/admin/basic-reports", "年级总体挂科情况", "/admin/basic-reports/failure-overview", 2, 201),
    ("/admin/basic-reports/major-makeup-comparison", "/admin/basic-reports", "各专业补考前后挂科率比较", "/admin/basic-reports/major-makeup-comparison", 2, 202),
    ("/admin/basic-reports/major-gender-failure", "/admin/basic-reports", "各专业整体与男女挂科率比较", "/admin/basic-reports/major-gender-failure", 2, 203),
    ("/admin/basic-reports/class-failure-count", "/admin/basic-reports", "各班级挂科门数具体情况", "/admin/basic-reports/class-failure-count", 2, 204),
    ("/admin/basic-reports/class-score-distribution", "/admin/basic-reports", "各班级成绩分布", "/admin/basic-reports/class-score-distribution", 2, 205),
    ("/admin/basic-reports/course-makeup-comparison", "/admin/basic-reports", "补考前后课程通过情况对比", "/admin/basic-reports/course-makeup-comparison", 2, 206),
    ("/admin/basic-reports/cet4-pass", "/admin/basic-reports", "各班大学英语四级通过情况", "/admin/basic-reports/cet4-pass", 2, 207),
    ("/admin/basic-reports/focus-students", "/admin/basic-reports", "重点关注学生名单", "/admin/basic-reports/focus-students", 2, 208),
    ("/admin/basic-reports/academic-warning-roster", "/admin/basic-reports", "校级学业警示学生名单", "/admin/basic-reports/academic-warning-roster", 2, 209),
)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _as_dict(row: sqlite3.Row | tuple | None) -> dict | None:
    return dict(row) if row is not None else None


def _query(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def _scalar(conn: sqlite3.Connection, sql: str, params: Iterable = ()):
    row = conn.execute(sql, tuple(params)).fetchone()
    return row[0] if row else None


def is_metric_catalog_v2_ready(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sys_metric_%'"
    ).fetchall()
    names = {row[0] for row in rows}
    return V2_REQUIRED_TABLES.issubset(names)


def _tags_for(seed: dict) -> list[tuple[str, str, str]]:
    domain = seed.get("domain") or "其他"
    result = [(f"domain:{domain}", domain, "业务域")]
    haystack = " ".join((
        domain, seed.get("name", ""), seed.get("description", ""),
        seed.get("formula", ""), seed.get("boundary", ""),
        seed.get("grain", ""), seed.get("data_source", ""),
    ))
    classifiers = (
        ("object:course", "课程", "业务对象", ("课程", "开课", "修读")),
        ("object:student", "学生", "业务对象", ("学生", "学业", "成绩", "毕业", "预警")),
        ("object:teacher", "教师", "业务对象", ("教师", "师资", "教职工")),
        ("object:class", "班级", "业务对象", ("行政班", "班级")),
        ("object:college", "学院", "业务对象", ("学院", "院系")),
        ("object:major", "专业", "业务对象", ("专业",)),
        ("object:classroom", "教室", "业务对象", ("教室", "楼宇")),
        ("object:curriculum", "培养方案", "业务对象", ("培养方案", "培养要求", "模块规则")),
        ("object:alert", "预警事件", "业务对象", ("预警事件", "规则命中", "预警记录")),
        ("form:rate", "比例", "统计形态", ("率", "占比", "比例")),
        ("form:count", "数量", "统计形态", ("人数", "人次", "门数", "次数", "记录数", "总数", "课程数", "教学班数")),
        ("form:average", "均值", "统计形态", ("平均", "人均", "均值")),
        ("form:median", "中位数", "统计形态", ("中位", "P50")),
        ("form:rank", "排名", "统计形态", ("排名", "排行", "分位", "P90")),
        ("form:distribution", "分布", "统计形态", ("分布", "分档", "区间", "档位")),
        ("form:change", "变化", "统计形态", ("变化", "增减", "波动", "趋势")),
        ("form:score", "评分", "统计形态", ("得分", "评分", "关注分")),
        ("form:status", "状态", "统计形态", ("状态", "是否", "候选")),
        ("theme:gpa", "GPA", "业务主题", ("GPA", "绩点")),
        ("theme:failure", "未通过", "业务主题", ("挂科", "未通过", "失败")),
        ("theme:makeup", "补考", "业务主题", ("补考",)),
        ("theme:retake", "重修", "业务主题", ("重修",)),
        ("theme:credit", "学分", "业务主题", ("学分",)),
        ("theme:schedule", "排课运行", "业务主题", ("排课", "调课", "停课", "教学班", "时段")),
        ("theme:faculty", "师资保障", "业务主题", ("师资", "教师结构", "职称", "授课教师")),
        ("theme:graduation", "毕业准备", "业务主题", ("毕业", "培养方案", "必修未通过", "到期缺")),
        ("theme:cet4", "大学英语四级", "业务主题", ("四级", "CET4")),
        ("theme:quality", "质量", "管理主题", ("质量", "通过率", "挂科", "覆盖率", "完整率")),
        ("theme:risk", "风险预警", "管理主题", ("风险", "预警", "异常")),
        ("use:comparison", "横向比较", "管理用途", ("比较", "对比", "横向", "排名")),
        ("use:trend", "趋势监控", "管理用途", ("趋势", "跨学期", "变化")),
        ("use:priority", "优先核查", "管理用途", ("优先", "重点关注", "核查队列", "关注分")),
        ("use:evidence", "证据下钻", "管理用途", ("证据", "详情", "下钻")),
        ("use:resource", "资源配置", "管理用途", ("资源", "容量", "教室", "排课", "供给")),
        ("time:current", "当前快照", "时间口径", ("当前", "本学期", "当期")),
        ("time:semester", "学期", "时间口径", ("学期",)),
        ("time:cross-term", "跨学期", "时间口径", ("跨学期", "最近两学期", "连续", "历史")),
        ("time:cumulative", "累计", "时间口径", ("累计", "截至")),
        ("nature:quality-gate", "质量门槛", "数据性质", ("覆盖率", "完整率", "证据率", "样本要求", "数据质量")),
        ("nature:candidate", "候选核查", "数据性质", ("候选", "待核验", "待确认")),
    )
    for tag_id, label, tag_type, words in classifiers:
        if any(word in haystack for word in words):
            result.append((tag_id, label, tag_type))
    for raw in seed.get("tags", ()):
        if isinstance(raw, str):
            label, tag_type = raw, "自定义分类"
            tag_id = _stable_id("tag", tag_type, label)
        else:
            label = raw.get("name") or raw.get("label")
            if not label:
                continue
            tag_type = raw.get("tag_type") or raw.get("type") or "自定义分类"
            tag_id = raw.get("tag_id") or raw.get("id") or _stable_id(
                "tag", tag_type, label
            )
        result.append((tag_id, label, tag_type))
    deduplicated = {tag_id: (tag_id, label, tag_type)
                    for tag_id, label, tag_type in result}
    return list(deduplicated.values())


def migrate_metric_catalog_v2(
    conn: sqlite3.Connection, document_path: Path | None = None
) -> dict:
    """Apply the idempotent V2 migration and seed only code-verified metrics."""
    # Preserve the existing tables and their callers during the transition.
    legacy_count = ensure_metric_catalog(conn, document_path)
    conn.executescript(CATALOG_V2_DDL)
    # CREATE TABLE IF NOT EXISTS cannot add columns to an existing V2 database.
    # The explicit ALTER migration keeps deployments upgraded in place.
    ensure_specification_schema(conn)
    documented = parse_confirmation_metrics(document_path)
    seeds = iter_verified_metric_seeds(documented)
    verified_ids = {item["metric_id"] for item in seeds}

    # Reconcile the migration-owned catalog instead of accumulating rows that
    # disappeared from the current document or verified seed packs.
    conn.execute("""
        UPDATE sys_metric_candidate SET candidate_status='removed_from_source'
        WHERE source_kind='markdown'
    """)
    conn.execute("""
        UPDATE sys_metric_registry SET lifecycle_status='retired',
               updated_at=datetime('now','localtime')
        WHERE source_kind IN ('formal','context','legacy')
    """)

    for item in documented:
        candidate_id = _stable_id("candidate", "confirmation-v2", item["metric_id"])
        payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
        conn.execute("""
            INSERT INTO sys_metric_candidate(
                candidate_id,source_kind,source_key,source_ref,metric_code,name,
                domain,formula,description,boundary,candidate_status,payload_json
            ) VALUES(?, 'markdown', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind,source_key) DO UPDATE SET
                source_ref=excluded.source_ref,metric_code=excluded.metric_code,
                name=excluded.name,domain=excluded.domain,formula=excluded.formula,
                description=excluded.description,boundary=excluded.boundary,
                candidate_status=excluded.candidate_status,
                payload_json=excluded.payload_json,
                updated_at=datetime('now','localtime')
        """, (
            candidate_id, item["metric_id"], "需求调研及指标口径确认书V2",
            item["metric_id"], item["name"], item["domain"], item["formula"],
            item.get("management_value", ""), item.get("boundary", ""),
            "linked_formal" if item["metric_id"] in verified_ids else "pending_verification",
            payload,
        ))

    for module_id, parent_id, name, path, level, order in MODULE_SEEDS:
        conn.execute("""
            INSERT INTO sys_metric_module(
                module_id,parent_id,name,path,module_level,description,sort_order
            ) VALUES(?,?,?,?,?, ?,?)
            ON CONFLICT(module_id) DO UPDATE SET
                parent_id=excluded.parent_id,name=excluded.name,path=excluded.path,
                module_level=excluded.module_level,
                description=excluded.description,sort_order=excluded.sort_order,
                status='active'
        """, (module_id, parent_id, name, path, level, f"{name}指标使用位置", order))

    # Definitions and relationships are code-governed.  Rebuild the derived
    # links atomically so removed aliases, dependencies, usages or issues do
    # not survive a later idempotent migration.
    for table in (
        "sys_metric_usage", "sys_metric_dependency", "sys_metric_rule_binding",
        "sys_metric_evidence", "sys_metric_issue", "sys_metric_alias",
        "sys_metric_tag_link",
    ):
        conn.execute(f"DELETE FROM {table}")

    for seed in seeds:
        metric_id = seed["metric_id"]
        lifecycle = "retired" if seed.get("implementation_status") == "retired" else "active"
        conn.execute("""
            INSERT INTO sys_metric_registry(
                metric_id,metric_code,technical_kpi_id,lifecycle_status,source_kind
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(metric_id) DO UPDATE SET
                metric_code=excluded.metric_code,
                technical_kpi_id=excluded.technical_kpi_id,
                lifecycle_status=excluded.lifecycle_status,
                source_kind=excluded.source_kind,
                updated_at=datetime('now','localtime')
        """, (
            metric_id, seed.get("metric_code", metric_id),
            seed.get("technical_kpi_id"), lifecycle,
            seed.get("source_kind", "formal"),
        ))
        version_no = str(seed.get("version", "1.0"))
        version_id = f"{metric_id}@{version_no}"
        conn.execute("""
            UPDATE sys_metric_version SET effective_status='superseded'
            WHERE metric_id=? AND version_no<>?
        """, (metric_id, version_no))
        conn.execute("""
            INSERT INTO sys_metric_version(
                version_id,metric_id,version_no,name,description,formula,boundary,
                management_value,domain,unit,value_type,grain,data_source,
                update_cycle,definition_status,implementation_status,
                effective_status,source_ref
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'current',?)
            ON CONFLICT(metric_id,version_no) DO UPDATE SET
                name=excluded.name,description=excluded.description,
                formula=excluded.formula,boundary=excluded.boundary,
                management_value=excluded.management_value,domain=excluded.domain,
                unit=excluded.unit,value_type=excluded.value_type,
                grain=excluded.grain,data_source=excluded.data_source,
                update_cycle=excluded.update_cycle,
                definition_status=excluded.definition_status,
                implementation_status=excluded.implementation_status,
                effective_status='current',source_ref=excluded.source_ref,
                updated_at=datetime('now','localtime')
        """, (
            version_id, metric_id, version_no, seed["name"],
            seed.get("description", ""), seed.get("formula", ""),
            seed.get("boundary", ""), seed.get("management_value", ""),
            seed.get("domain", "其他"), seed.get("unit"), seed.get("value_type"),
            seed.get("grain"), seed.get("data_source"), seed.get("update_cycle"),
            seed.get("definition_status", "published"),
            seed.get("implementation_status", "verified"), seed["source_ref"],
        ))
        conn.execute(
            "UPDATE sys_metric_registry SET current_version_id=? WHERE metric_id=?",
            (version_id, metric_id),
        )

        aliases = set()
        if seed.get("technical_kpi_id"):
            aliases.add((seed["technical_kpi_id"], "technical_key"))
        for page in seed.get("pages", []):
            if page["feature_name"] != seed["name"]:
                aliases.add((page["feature_name"], "display"))
        for alias, alias_type in aliases:
            conn.execute("""
                INSERT INTO sys_metric_alias(alias_id,metric_id,alias,alias_type,source_ref)
                VALUES(?,?,?,?,?)
                ON CONFLICT(metric_id,alias,alias_type) DO UPDATE SET
                    source_ref=excluded.source_ref
            """, (
                _stable_id("alias", metric_id, alias, alias_type), metric_id, alias,
                alias_type, seed["source_ref"],
            ))

        for tag_id, tag_name, tag_type in _tags_for(seed):
            conn.execute("""
                INSERT INTO sys_metric_tag(tag_id,name,tag_type,description)
                VALUES(?,?,?,?)
                ON CONFLICT(tag_id) DO UPDATE SET
                    name=excluded.name,tag_type=excluded.tag_type,
                    description=excluded.description
            """, (tag_id, tag_name, tag_type, f"按{tag_type}归类：{tag_name}"))
            conn.execute("""
                INSERT OR IGNORE INTO sys_metric_tag_link(metric_id,tag_id,source_ref)
                VALUES(?,?,?)
            """, (metric_id, tag_id, seed["source_ref"]))

        for page in seed.get("pages", []):
            module_id = page["module_path"]
            if not conn.execute(
                "SELECT 1 FROM sys_metric_module WHERE module_id=?", (module_id,)
            ).fetchone():
                conn.execute("""
                    INSERT INTO sys_metric_module(
                        module_id,parent_id,name,path,module_level,description,sort_order
                    ) VALUES(?,NULL,?,?,1,?,9999)
                """, (module_id, module_id, module_id, "迁移发现的页面模块"))
            feature_id = _stable_id("feature", module_id, page["feature_name"])
            conn.execute("""
                INSERT INTO sys_metric_feature_point(
                    feature_point_id,module_id,name,description,source_ref
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(module_id,name) DO UPDATE SET
                    description=excluded.description,source_ref=excluded.source_ref,
                    status='active'
            """, (
                feature_id, module_id, page["feature_name"],
                page.get("feature_description", ""), page["source_ref"],
            ))
            usage_id = _stable_id(
                "usage", metric_id, feature_id, page.get("usage_type", "display"),
                page.get("occurrence_key", page["feature_name"]),
            )
            conn.execute("""
                INSERT INTO sys_metric_usage(
                    usage_id,metric_id,feature_point_id,usage_type,occurrence_key,
                    display_name,source_ref
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(metric_id,feature_point_id,usage_type,occurrence_key)
                DO UPDATE SET display_name=excluded.display_name,
                              source_ref=excluded.source_ref
            """, (
                usage_id, metric_id, feature_id, page.get("usage_type", "display"),
                page.get("occurrence_key", page["feature_name"]),
                page["feature_name"], page["source_ref"],
            ))

        conn.execute("""
            INSERT INTO sys_metric_evidence(
                evidence_id,metric_id,evidence_type,source_ref,description,
                verification_status,verified_at
            ) VALUES(?,?,'code_registry',?,?,'verified',datetime('now','localtime'))
            ON CONFLICT(metric_id,evidence_type,source_ref) DO UPDATE SET
                description=excluded.description,verification_status='verified'
        """, (
            _stable_id("evidence", metric_id, seed["source_ref"]), metric_id,
            seed["source_ref"], "该指标已由代码侧正式种子登记并绑定实现证据。",
        ))

    for alias in VERIFIED_ALIASES:
        if alias["metric_id"] not in verified_ids:
            continue
        conn.execute("""
            INSERT OR IGNORE INTO sys_metric_alias(
                alias_id,metric_id,alias,alias_type,source_ref
            ) VALUES(?,?,?,?,?)
        """, (
            _stable_id("alias", alias["metric_id"], alias["alias"], alias.get("alias_type", "display")),
            alias["metric_id"], alias["alias"], alias.get("alias_type", "display"),
            alias.get("source_ref", "verified seed"),
        ))

    for dependency in VERIFIED_DEPENDENCIES:
        if {dependency["source_metric_id"], dependency["target_metric_id"]} <= verified_ids:
            conn.execute("""
                INSERT INTO sys_metric_dependency(
                    dependency_id,source_metric_id,target_metric_id,relation_type,
                    description,source_ref
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(source_metric_id,target_metric_id,relation_type)
                DO UPDATE SET description=excluded.description,
                              source_ref=excluded.source_ref
            """, (
                _stable_id("dependency", dependency["source_metric_id"], dependency["target_metric_id"], dependency.get("relation_type", "calculation_input")),
                dependency["source_metric_id"], dependency["target_metric_id"],
                dependency.get("relation_type", "calculation_input"),
                dependency.get("description", ""), dependency["source_ref"],
            ))

    for binding in VERIFIED_RULE_BINDINGS:
        if binding["metric_id"] not in verified_ids:
            continue
        conn.execute("""
            INSERT OR IGNORE INTO sys_metric_rule_binding(
                binding_id,metric_id,rule_type,rule_id,role,description,source_ref
            ) VALUES(?,?,?,?,?,?,?)
        """, (
            _stable_id("rule", binding["metric_id"], binding["rule_type"], binding["rule_id"], binding.get("role", "input")),
            binding["metric_id"], binding["rule_type"], binding["rule_id"],
            binding.get("role", "input"), binding.get("description", ""),
            binding["source_ref"],
        ))

    for issue in VERIFIED_ISSUES:
        if issue["metric_id"] not in verified_ids:
            continue
        conn.execute("""
            INSERT INTO sys_metric_issue(
                issue_id,metric_id,issue_type,severity,status,description,source_ref
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(metric_id,issue_type,description) DO UPDATE SET
                severity=excluded.severity,status=excluded.status,
                source_ref=excluded.source_ref
        """, (
            _stable_id("issue", issue["metric_id"], issue["issue_type"], issue["description"]),
            issue["metric_id"], issue["issue_type"],
            issue.get("severity", "warning"), issue.get("status", "open"),
            issue["description"], issue.get("source_ref"),
        ))

    # The extension list uses the same normalized usage shape as page seeds.
    for usage in VERIFIED_USAGE_POINTS:
        if usage["metric_id"] not in verified_ids:
            continue
        module_id = usage["module_path"]
        feature_id = _stable_id("feature", module_id, usage["feature_name"])
        if not conn.execute(
            "SELECT 1 FROM sys_metric_module WHERE module_id=?", (module_id,)
        ).fetchone():
            continue
        conn.execute("""
            INSERT OR IGNORE INTO sys_metric_feature_point(
                feature_point_id,module_id,name,description,source_ref
            ) VALUES(?,?,?,?,?)
        """, (feature_id, module_id, usage["feature_name"], usage.get("feature_description", ""), usage["source_ref"]))
        occurrence = usage.get("occurrence_key", usage["feature_name"])
        conn.execute("""
            INSERT OR IGNORE INTO sys_metric_usage(
                usage_id,metric_id,feature_point_id,usage_type,occurrence_key,
                display_name,source_ref
            ) VALUES(?,?,?,?,?,?,?)
        """, (
            _stable_id("usage", usage["metric_id"], feature_id, usage.get("usage_type", "display"), occurrence),
            usage["metric_id"], feature_id, usage.get("usage_type", "display"),
            occurrence, usage.get("display_name", usage["feature_name"]),
            usage["source_ref"],
        ))

    conn.execute("""
        DELETE FROM sys_metric_feature_point
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_metric_usage u
            WHERE u.feature_point_id=sys_metric_feature_point.feature_point_id
        )
    """)
    conn.execute("""
        DELETE FROM sys_metric_tag
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_metric_tag_link l
            WHERE l.tag_id=sys_metric_tag.tag_id
        )
    """)

    refresh_specifications(
        conn,
        formal_sources=seeds,
        candidate_sources=documented,
        dependencies=VERIFIED_DEPENDENCIES,
    )

    candidate_count = _scalar(conn, """
        SELECT COUNT(*) FROM sys_metric_candidate
        WHERE candidate_status<>'removed_from_source'
    """) or 0
    metric_count = len(verified_ids)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "candidates": sorted(documented, key=lambda item: item["metric_id"]),
        # Keep the complete governed payload in the snapshot.  A formula,
        # boundary, usage point or relationship change must produce a new
        # digest even when the metric id and version label are unchanged.
        "formalMetrics": sorted(
            (dict(seed) for seed in seeds), key=lambda item: item["metric_id"]
        ),
        "modules": [list(item) for item in MODULE_SEEDS],
        "aliases": list(VERIFIED_ALIASES),
        "dependencies": list(VERIFIED_DEPENDENCIES),
        "ruleBindings": list(VERIFIED_RULE_BINDINGS),
        "usagePoints": list(VERIFIED_USAGE_POINTS),
        "issues": list(VERIFIED_ISSUES),
        "specifications": [
            dict(row) for row in conn.execute("""
                SELECT 'formal' subject_kind,metric_id subject_id,
                       specification_json,specification_status,
                       specification_source,value_type
                FROM sys_metric_version WHERE effective_status='current'
                UNION ALL
                SELECT 'candidate',candidate_id,specification_json,
                       specification_status,specification_source,NULL
                FROM sys_metric_candidate
                WHERE candidate_status<>'removed_from_source'
                ORDER BY subject_kind,subject_id
            """).fetchall()
        ],
        "specificationOverrides": [
            dict(row) for row in conn.execute("""
                SELECT subject_kind,subject_id,override_key,patch_json,reason,
                       source_ref,priority,status,changed_by
                FROM sys_metric_spec_override
                ORDER BY subject_kind,subject_id,priority,override_key
            """).fetchall()
        ],
        "specificationOverrideRevisions": [
            dict(row) for row in conn.execute("""
                SELECT revision_id,override_id,revision_no,action,status,
                       subject_kind,subject_id,override_key,patch_json,reason,
                       source_ref,priority,changed_by
                FROM sys_metric_spec_override_revision
                ORDER BY revision_id
            """).fetchall()
        ],
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    conn.execute("""
        INSERT INTO sys_metric_snapshot(
            snapshot_id,schema_version,source_digest,candidate_count,metric_count,
            manifest_json
        ) VALUES(?,?,?,?,?,?)
        ON CONFLICT(source_digest) DO UPDATE SET
            schema_version=excluded.schema_version,
            candidate_count=excluded.candidate_count,
            metric_count=excluded.metric_count,
            manifest_json=excluded.manifest_json
    """, (f"snapshot:{digest[:20]}", SCHEMA_VERSION, digest, candidate_count, metric_count, manifest_json))
    return {
        "legacyMetricDefinitions": legacy_count,
        "candidateMetrics": candidate_count,
        "formalMetrics": metric_count,
        "snapshots": _scalar(conn, "SELECT COUNT(*) FROM sys_metric_snapshot") or 0,
    }


def _usage_points(conn: sqlite3.Connection, metric_id: str) -> list[dict]:
    rows = _query(conn, """
        SELECT u.usage_id,u.usage_type,u.occurrence_key,u.display_name,
               fp.feature_point_id,fp.name feature_point,
               fp.description feature_description,m.module_id,m.name module_name,
               m.path module_path,m.module_level,
               p.module_id parent_module_id,p.name parent_module_name,
               gp.module_id grandparent_module_id,gp.name grandparent_module_name
        FROM sys_metric_usage u
        JOIN sys_metric_feature_point fp ON fp.feature_point_id=u.feature_point_id
        JOIN sys_metric_module m ON m.module_id=fp.module_id
        LEFT JOIN sys_metric_module p ON p.module_id=m.parent_id
        LEFT JOIN sys_metric_module gp ON gp.module_id=p.parent_id
        WHERE u.metric_id=?
        ORDER BY m.sort_order,fp.name,u.occurrence_key
    """, (metric_id,))
    for row in rows:
        level = row["module_level"]
        row["firstLevelModule"] = (
            row["grandparent_module_name"] if level >= 3
            else row["parent_module_name"] if level == 2 else row["module_name"]
        )
        row["secondLevelModule"] = (
            row["parent_module_name"] if level >= 3
            else row["module_name"] if level == 2 else None
        )
        row["thirdLevelModule"] = row["module_name"] if level >= 3 else None
        row["level1"] = row["firstLevelModule"]
        row["level2"] = row["secondLevelModule"]
        row["level3"] = row["thirdLevelModule"]
        row["first_level_module"] = row["firstLevelModule"]
        row["second_level_module"] = row["secondLevelModule"]
        row["third_level_module"] = row["thirdLevelModule"]
        row["featurePoint"] = row["feature_point"]
        row["featurePointDescription"] = row["feature_description"]
        row["functionPoint"] = row["feature_point"]
        row["function_point"] = row["feature_point"]
        row["description"] = row["feature_description"]
        row["function_description"] = row["feature_description"]
        row["path"] = row["module_path"]
        row["page_path"] = row["module_path"]
    return rows


def _tags(conn: sqlite3.Connection, metric_id: str) -> list[dict]:
    return _query(conn, """
        SELECT t.tag_id,t.name,t.tag_type,t.description
        FROM sys_metric_tag_link l JOIN sys_metric_tag t ON t.tag_id=l.tag_id
        WHERE l.metric_id=? ORDER BY t.tag_type,t.sort_order,t.name
    """, (metric_id,))


def _attach_specification(
    row: dict, specification_json: object, specification_status: str | None,
    specification_source: str | None,
) -> None:
    specification = parse_specification(specification_json, specification_status)
    row["specification"] = specification
    row["specification_status"] = specification_status or specification["quality"]["status"]
    row["specificationStatus"] = row["specification_status"]
    row["specification_source"] = specification_source or "deterministic_normalization"
    row["specificationSource"] = row["specification_source"]
    row["specificationQuality"] = specification["quality"]
    # Keep the legacy list/detail fields while serving the confirmed reference
    # layout: one readable indicator explanation and one Chinese calculation
    # rule.  The original formula remains available as calculationFormula.
    row["description"] = specification.get("indicatorDescription") or specification.get(
        "definitionDescription"
    ) or row.get("description", "")
    row["formula"] = specification.get("calculationRule") or row.get("formula", "")
    row["management_value"] = specification.get("managementUse") or row.get(
        "management_value", ""
    )
    # Convenience aliases keep internal governance consumers able to inspect
    # both the source formula and the user-facing Chinese calculation rule.
    for field in (
        "indicatorDescription", "calculationRule",
        "definitionDescription", "managementUse", "statisticalObject",
        "statisticalScope", "calculationType", "calculationFormula",
        "numerator", "denominator", "denominatorZeroRule",
        "deduplicationRule", "inclusionRule", "exclusionRule",
        "boundaryRule", "nullHandlingRule", "precisionRule",
        "dataSources", "dataAsOfRule",
    ):
        row[field] = specification.get(field)


def _metric_row(conn: sqlite3.Connection, metric_id: str) -> dict | None:
    row = _as_dict(conn.execute("""
        SELECT r.metric_id,r.metric_code,r.technical_kpi_id,r.lifecycle_status,
               r.source_kind,v.version_id,v.version_no,v.name,v.description,
               v.formula,v.boundary,v.management_value,v.domain,v.unit,
               v.value_type,v.grain,v.data_source,v.update_cycle,
               v.definition_status,v.implementation_status,v.source_ref,
               v.specification_json,v.specification_status,
               v.specification_source,
               (SELECT COUNT(DISTINCT d.target_metric_id)
                  FROM sys_metric_dependency d WHERE d.source_metric_id=r.metric_id)
                 reference_count,
               (SELECT COUNT(DISTINCT d.source_metric_id)
                  FROM sys_metric_dependency d WHERE d.target_metric_id=r.metric_id)
                 referenced_by_count,
               (SELECT COUNT(DISTINCT u.feature_point_id)
                  FROM sys_metric_usage u WHERE u.metric_id=r.metric_id)
                 usage_point_count,
               (SELECT COUNT(*) FROM sys_metric_issue i
                  WHERE i.metric_id=r.metric_id) issue_count,
               (SELECT COUNT(*) FROM sys_metric_issue i
                  WHERE i.metric_id=r.metric_id AND i.status='open')
                 open_issue_count,
               (SELECT COUNT(*) FROM sys_metric_issue i
                  WHERE i.metric_id=r.metric_id AND i.status='open'
                    AND i.severity='error') open_error_issue_count
        FROM sys_metric_registry r
        JOIN sys_metric_version v ON v.version_id=r.current_version_id
        WHERE r.metric_id=? OR r.metric_code=?
        LIMIT 1
    """, (metric_id, metric_id)).fetchone())
    if not row:
        return None
    row["tags"] = _tags(conn, row["metric_id"])
    row["usages"] = _usage_points(conn, row["metric_id"])
    row["usagePoints"] = row["usages"]
    row["aliases"] = _query(conn, """
        SELECT alias,alias_type FROM sys_metric_alias
        WHERE metric_id=? ORDER BY alias_type,alias
    """, (row["metric_id"],))
    row["referenceCount"] = row["reference_count"]
    row["referencedByCount"] = row["referenced_by_count"]
    row["referencedMetricCount"] = row["reference_count"]
    row["dependentMetricCount"] = row["referenced_by_count"]
    row["usagePointCount"] = row["usage_point_count"]
    row["page_count"] = row["usage_point_count"]
    row["metricId"] = row["metric_id"]
    row["metricCode"] = row["metric_code"]
    row["version"] = row["version_no"]
    row["page_refs"] = json.dumps(
        sorted({usage["module_path"] for usage in row["usages"]}),
        ensure_ascii=False,
    )
    definition_labels = {
        "pending_confirmation": "待学校确认", "published": "已发布",
        "context": "范围背景", "deprecated": "已停用",
    }
    implementation_labels = {
        "verified": "已实现并验证", "unverified": "待建立实现证据",
        "mismatch": "定义与实现不一致", "retired": "已退出页面",
    }
    row["definition_status_label"] = definition_labels.get(
        row["definition_status"], row["definition_status"]
    )
    row["implementation_status_label"] = implementation_labels.get(
        row["implementation_status"], row["implementation_status"]
    )
    _attach_specification(
        row, row.pop("specification_json", None),
        row.get("specification_status"), row.get("specification_source"),
    )
    return row


def _module_facets(conn: sqlite3.Connection) -> list[dict]:
    """Return a real module tree with de-duplicated descendant metric counts."""
    rows = _query(conn, """
        SELECT module_id,parent_id,name,path,module_level,sort_order
        FROM sys_metric_module WHERE status='active'
        ORDER BY sort_order,name
    """)
    for row in rows:
        row["count"] = _scalar(conn, """
            WITH RECURSIVE descendants(module_id) AS (
                SELECT module_id FROM sys_metric_module WHERE module_id=?
                UNION
                SELECT m.module_id FROM sys_metric_module m
                JOIN descendants d ON m.parent_id=d.module_id
            )
            SELECT COUNT(DISTINCT u.metric_id)
            FROM sys_metric_usage u
            JOIN sys_metric_feature_point fp
              ON fp.feature_point_id=u.feature_point_id
            WHERE fp.module_id IN descendants
        """, (row["module_id"],)) or 0
        row["children"] = []
    by_id = {row["module_id"]: row for row in rows}
    roots: list[dict] = []
    for row in rows:
        parent = by_id.get(row["parent_id"])
        if parent:
            parent["children"].append(row)
        else:
            roots.append(row)
    return roots


def list_metrics(
    conn: sqlite3.Connection, *, page: int = 1, page_size: int = 20,
    module_id: str | None = None, tag_ids: str | Iterable[str] | None = None,
    name: str | None = None, domain: str | None = None,
    keyword: str | None = None, definition_status: str | None = None,
    implementation_status: str | None = None,
) -> dict:
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 100)
    if isinstance(tag_ids, str):
        tags = sorted({item.strip() for item in tag_ids.split(",") if item.strip()})
    else:
        tags = sorted({str(item).strip() for item in (tag_ids or []) if str(item).strip()})
    # Ordinary query traffic sees the current catalog.  Governance callers can
    # still request an explicit deprecated/retired status for historical rows.
    clauses = ["1=1"]
    if definition_status not in {"deprecated"} and implementation_status not in {"retired"}:
        clauses.append("r.lifecycle_status='active'")
    params: list = []
    if module_id:
        clauses.append("""EXISTS (
            WITH RECURSIVE selected(module_id) AS (
                SELECT module_id FROM sys_metric_module WHERE module_id=? OR path=?
                UNION
                SELECT m.module_id FROM sys_metric_module m
                JOIN selected s ON m.parent_id=s.module_id
            )
            SELECT 1 FROM sys_metric_usage mu
            JOIN sys_metric_feature_point fp ON fp.feature_point_id=mu.feature_point_id
            WHERE mu.metric_id=r.metric_id AND fp.module_id IN selected
        )""")
        params.extend([module_id, module_id])
    for tag_id in tags:
        clauses.append("""EXISTS (
            SELECT 1 FROM sys_metric_tag_link tl
            WHERE tl.metric_id=r.metric_id AND tl.tag_id=?
        )""")
        params.append(tag_id)
    if name:
        pattern = f"%{name.strip()}%"
        clauses.append("""(
            v.name LIKE ? OR r.metric_code LIKE ? OR EXISTS (
                SELECT 1 FROM sys_metric_alias a
                WHERE a.metric_id=r.metric_id AND a.alias LIKE ?
            )
        )""")
        params.extend([pattern, pattern, pattern])
    if keyword:
        pattern = f"%{keyword.strip()}%"
        clauses.append("""(
            v.name LIKE ? OR r.metric_code LIKE ? OR v.formula LIKE ?
            OR v.description LIKE ? OR v.management_value LIKE ? OR EXISTS (
                SELECT 1 FROM sys_metric_alias a
                WHERE a.metric_id=r.metric_id AND a.alias LIKE ?
            )
        )""")
        params.extend([pattern] * 6)
    if domain:
        clauses.append("v.domain=?")
        params.append(domain)
    if definition_status:
        clauses.append("v.definition_status=?")
        params.append(definition_status)
    if implementation_status:
        clauses.append("v.implementation_status=?")
        params.append(implementation_status)
    where = " AND ".join(clauses)
    base = """
        FROM sys_metric_registry r
        JOIN sys_metric_version v ON v.version_id=r.current_version_id
    """
    total = _scalar(conn, f"SELECT COUNT(*) {base} WHERE {where}", params) or 0
    identifiers = _query(conn, f"""
        SELECT r.metric_id {base} WHERE {where}
        ORDER BY CASE v.definition_status WHEN 'published' THEN 0 ELSE 1 END,
                 v.domain,r.metric_code
        LIMIT ? OFFSET ?
    """, [*params, page_size, (page - 1) * page_size])
    items = [_metric_row(conn, item["metric_id"]) for item in identifiers]
    module_facets = _module_facets(conn)
    tag_facets = _query(conn, """
        SELECT t.tag_id,t.name,t.tag_type,COUNT(DISTINCT l.metric_id) count
        FROM sys_metric_tag t
        LEFT JOIN sys_metric_tag_link l ON l.tag_id=t.tag_id
        GROUP BY t.tag_id,t.name,t.tag_type,t.sort_order
        ORDER BY t.tag_type,t.sort_order,t.name
    """)
    return {
        "items": items, "total": total, "page": page, "pageSize": page_size,
        "facets": {"modules": module_facets, "tags": tag_facets},
        "filters": {"tagIdsFormat": "comma-separated"},
    }


def _candidate_metric_row(candidate: dict) -> dict:
    domain = candidate["domain"] or "其他"
    metric_id = candidate["metric_code"]
    row = {
        "metric_id": metric_id, "metricId": metric_id,
        "metric_code": metric_id, "metricCode": metric_id,
        "technical_kpi_id": None, "lifecycle_status": "candidate",
        "source_kind": "definition", "version_id": None,
        "version_no": "candidate", "version": "candidate",
        "name": candidate["name"],
        "description": candidate["description"] or "",
        "formula": candidate["formula"] or "",
        "boundary": candidate["boundary"] or "",
        "management_value": candidate["description"] or "",
        "domain": domain, "unit": None, "value_type": None,
        "grain": "", "data_source": "", "update_cycle": "",
        "definition_status": "pending_confirmation",
        "definition_status_label": "待学校确认",
        "implementation_status": "unverified",
        "implementation_status_label": "待建立实现证据",
        "source_ref": candidate["source_ref"],
        "tags": [{
            "tag_id": f"domain:{domain}", "name": domain,
            "tag_type": "业务域",
        }],
        "aliases": [], "usages": [], "usagePoints": [],
        "reference_count": 0, "referenced_by_count": 0,
        "referenceCount": 0, "referencedByCount": 0,
        "referencedMetricCount": 0, "dependentMetricCount": 0,
        "usage_point_count": 0, "usagePointCount": 0, "page_count": 0,
        "page_refs": "[]", "issue_count": 0,
        "open_issue_count": 0, "open_error_issue_count": 0,
        "candidate_status": candidate["candidate_status"],
    }
    _attach_specification(
        row, candidate.get("specification_json"),
        candidate.get("specification_status"),
        candidate.get("specification_source"),
    )
    return row


def list_governance_metrics(
    conn: sqlite3.Connection, *, page: int = 1, page_size: int = 20,
    module_id: str | None = None, tag_ids: str | Iterable[str] | None = None,
    name: str | None = None, domain: str | None = None,
    keyword: str | None = None, definition_status: str | None = None,
    implementation_status: str | None = None,
) -> dict:
    """Return the governance union of formal metrics and unmatched candidates.

    The read-only “指标查询” uses :func:`list_metrics` and never exposes
    documentation-only rows.  The existing governance page needs the wider
    union so its pending-confirmation card can still be reconciled.
    """
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 100)
    if isinstance(tag_ids, str):
        tags = {item.strip() for item in tag_ids.split(",") if item.strip()}
    else:
        tags = {str(item).strip() for item in (tag_ids or []) if str(item).strip()}

    formal_ids = _query(conn, """
        SELECT r.metric_id FROM sys_metric_registry r
        JOIN sys_metric_version v ON v.version_id=r.current_version_id
        ORDER BY r.metric_id
    """)
    rows = [_metric_row(conn, item["metric_id"]) for item in formal_ids]
    for row in rows:
        if row["open_error_issue_count"]:
            row["implementation_status"] = "mismatch"
            row["implementation_status_label"] = "定义与实现不一致"

    for candidate in _query(conn, """
        SELECT c.* FROM sys_metric_candidate c
        WHERE c.candidate_status<>'removed_from_source' AND NOT EXISTS (
            SELECT 1 FROM sys_metric_registry r
            WHERE r.metric_id=c.metric_code OR r.metric_code=c.metric_code
        )
        ORDER BY c.metric_code
    """):
        rows.append(_candidate_metric_row(candidate))

    selected_modules: set[str] | None = None
    if module_id:
        selected_modules = {
            item["module_id"] for item in _query(conn, """
                WITH RECURSIVE selected(module_id) AS (
                    SELECT module_id FROM sys_metric_module
                    WHERE module_id=? OR path=?
                    UNION
                    SELECT m.module_id FROM sys_metric_module m
                    JOIN selected s ON m.parent_id=s.module_id
                ) SELECT module_id FROM selected
            """, (module_id, module_id))
        }

    name_term = (name or "").strip().casefold()
    keyword_term = (keyword or "").strip().casefold()

    def matches(row: dict) -> bool:
        if domain and row["domain"] != domain:
            return False
        if definition_status and row["definition_status"] != definition_status:
            return False
        if implementation_status and row["implementation_status"] != implementation_status:
            return False
        if selected_modules is not None and not any(
            usage["module_id"] in selected_modules for usage in row["usages"]
        ):
            return False
        if tags and not tags.issubset({tag["tag_id"] for tag in row["tags"]}):
            return False
        aliases = " ".join(item.get("alias", "") for item in row["aliases"])
        if name_term and name_term not in " ".join((
            row["name"], row["metric_id"], aliases,
        )).casefold():
            return False
        if keyword_term and keyword_term not in " ".join((
            row["name"], row["metric_id"], row["formula"],
            row["description"], row["management_value"], aliases,
        )).casefold():
            return False
        return True

    rows = [row for row in rows if matches(row)]
    status_order = {
        "published": 0, "pending_confirmation": 1,
        "context": 2, "deprecated": 3,
    }
    rows.sort(key=lambda row: (
        status_order.get(row["definition_status"], 9),
        row["domain"], row["metric_id"],
    ))
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size], "total": total,
        "page": page, "pageSize": page_size,
        "facets": {"modules": _module_facets(conn), "tags": _query(conn, """
            SELECT t.tag_id,t.name,t.tag_type,COUNT(DISTINCT l.metric_id) count
            FROM sys_metric_tag t
            LEFT JOIN sys_metric_tag_link l ON l.tag_id=t.tag_id
            GROUP BY t.tag_id,t.name,t.tag_type,t.sort_order
            ORDER BY t.tag_type,t.sort_order,t.name
        """)},
        "filters": {"tagIdsFormat": "comma-separated", "scope": "governance"},
    }


def get_metric_detail(conn: sqlite3.Connection, metric_id: str) -> dict | None:
    metric = _metric_row(conn, metric_id)
    if not metric:
        candidate = _as_dict(conn.execute("""
            SELECT * FROM sys_metric_candidate
            WHERE metric_code=? OR source_key=? LIMIT 1
        """, (metric_id, metric_id)).fetchone())
        if not candidate:
            return None
        metric = _candidate_metric_row(candidate)
        return {
            "metric": metric, "definition": metric,
            "specification": metric["specification"],
            "dependencies": [], "references": [],
            "dependents": [], "referencedBy": [],
            "usages": [], "usagePoints": [], "bindings": [],
            "ruleBindings": [], "rules": [], "evidence": [], "issues": [],
            "governance": {
                "definitionEditable": False,
                "thresholdManagedBy": "分析方案管理",
                "changeRule": "该条目仅来自确认书候选，需完成代码实现和页面使用证据核验后才能进入正式目录。",
            },
        }
    dependencies = []
    for edge in _query(conn, """
        SELECT target_metric_id metric_id,relation_type,description,source_ref
        FROM sys_metric_dependency WHERE source_metric_id=?
        ORDER BY target_metric_id
    """, (metric["metric_id"],)):
        item = _metric_row(conn, edge["metric_id"])
        item["dependency"] = {key: edge[key] for key in ("relation_type", "description", "source_ref")}
        dependencies.append(item)
    dependents = []
    for edge in _query(conn, """
        SELECT source_metric_id metric_id,relation_type,description,source_ref
        FROM sys_metric_dependency WHERE target_metric_id=?
        ORDER BY source_metric_id
    """, (metric["metric_id"],)):
        item = _metric_row(conn, edge["metric_id"])
        item["dependency"] = {key: edge[key] for key in ("relation_type", "description", "source_ref")}
        dependents.append(item)
    rule_bindings = _query(conn, """
        SELECT binding_id,rule_type,rule_id,role,description,source_ref
        FROM sys_metric_rule_binding WHERE metric_id=?
        ORDER BY rule_type,rule_id,role
    """, (metric["metric_id"],))
    for binding in rule_bindings:
        binding["name"] = binding["rule_id"]
        binding["type"] = binding["rule_type"]
        binding["condition"] = binding["description"] or ""
        binding["warningLevel"] = ""
        binding["version"] = ""
        binding["status"] = "active"
    evidence = _query(conn, """
        SELECT evidence_id,evidence_type,source_ref,description,
               verification_status,verified_at
        FROM sys_metric_evidence WHERE metric_id=?
        ORDER BY evidence_type,source_ref
    """, (metric["metric_id"],))
    issues = _query(conn, """
        SELECT issue_id,issue_type,severity,status,description,source_ref
        FROM sys_metric_issue WHERE metric_id=?
        ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                 issue_type
    """, (metric["metric_id"],))
    return {
        "metric": metric,
        "definition": metric,
        "specification": metric["specification"],
        "dependencies": dependencies,
        "references": dependencies,
        "dependents": dependents,
        "referencedBy": dependents,
        "usages": metric["usages"],
        "usagePoints": metric["usages"],
        "bindings": metric["usages"],
        "ruleBindings": rule_bindings,
        "rules": rule_bindings,
        "evidence": evidence,
        "issues": issues,
        "governance": {
            "definitionEditable": False,
            "thresholdManagedBy": "分析方案管理",
            "changeRule": "正式口径通过代码核验种子和幂等迁移发布，运行时接口只读。",
        },
    }


def get_metric_impact(conn: sqlite3.Connection, metric_id: str) -> dict | None:
    metric = _metric_row(conn, metric_id)
    if not metric:
        return None
    edges = _query(conn, """
        SELECT source_metric_id,target_metric_id FROM sys_metric_dependency
        ORDER BY source_metric_id,target_metric_id
    """)
    reverse: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        reverse[edge["target_metric_id"]].add(edge["source_metric_id"])
    distance = {metric["metric_id"]: 0}
    queue = deque([metric["metric_id"]])
    while queue:
        current = queue.popleft()
        for dependent in sorted(reverse.get(current, ())):
            if dependent not in distance:
                distance[dependent] = distance[current] + 1
                queue.append(dependent)
    affected = []
    for affected_id, depth in sorted(distance.items(), key=lambda item: (item[1], item[0])):
        if affected_id == metric["metric_id"]:
            continue
        item = _metric_row(conn, affected_id)
        item["impactDepth"] = depth
        affected.append(item)
    affected_ids = [metric["metric_id"], *[item["metric_id"] for item in affected]]
    placeholders = ",".join("?" * len(affected_ids))
    usages = _query(conn, f"""
        SELECT DISTINCT u.metric_id,fp.feature_point_id,fp.name feature_point,
               fp.description feature_description,m.module_id,m.name module_name,
               m.path module_path
        FROM sys_metric_usage u
        JOIN sys_metric_feature_point fp ON fp.feature_point_id=u.feature_point_id
        JOIN sys_metric_module m ON m.module_id=fp.module_id
        WHERE u.metric_id IN ({placeholders})
        ORDER BY m.sort_order,fp.name,u.metric_id
    """, affected_ids)
    direct = [item for item in affected if item["impactDepth"] == 1]
    return {
        "metric": metric,
        "directDependents": direct,
        "affectedMetrics": affected,
        "affectedUsagePoints": usages,
        "summary": {
            "directDependentCount": len(direct),
            "affectedMetricCount": len(affected),
            "affectedUsagePointCount": len({item["feature_point_id"] for item in usages}),
        },
    }


def catalog_summary(conn: sqlite3.Connection) -> dict:
    definition = {
        row["key"]: row["count"] for row in _query(conn, """
            SELECT v.definition_status key,COUNT(*) count
            FROM sys_metric_registry r
            JOIN sys_metric_version v ON v.version_id=r.current_version_id
            GROUP BY v.definition_status
        """)
    }
    formal_total = _scalar(conn, "SELECT COUNT(*) FROM sys_metric_registry") or 0
    pending_total = _scalar(conn, """
        SELECT COUNT(*) FROM sys_metric_candidate c
        WHERE c.candidate_status<>'removed_from_source' AND NOT EXISTS (
            SELECT 1 FROM sys_metric_registry r
            WHERE r.metric_id=c.metric_code OR r.metric_code=c.metric_code
        )
    """) or 0
    inconsistent = _scalar(conn, """
        SELECT COUNT(DISTINCT metric_id) FROM sys_metric_issue
        WHERE status='open' AND severity='error'
    """) or 0
    return {
        "total": formal_total + pending_total,
        "formalTotal": formal_total,
        "currentFormalTotal": _scalar(conn, """
            SELECT COUNT(*) FROM sys_metric_registry WHERE lifecycle_status='active'
        """) or 0,
        "candidateTotal": _scalar(conn, """
            SELECT COUNT(*) FROM sys_metric_candidate
            WHERE candidate_status<>'removed_from_source'
        """) or 0,
        "linkedCandidateTotal": _scalar(conn, """
            SELECT COUNT(*) FROM sys_metric_candidate c
            WHERE c.candidate_status<>'removed_from_source' AND EXISTS (
                SELECT 1 FROM sys_metric_registry r
                WHERE r.metric_id=c.metric_code OR r.metric_code=c.metric_code
            )
        """) or 0,
        "published": definition.get("published", 0),
        "verified": _scalar(conn, """
            SELECT COUNT(*) FROM sys_metric_registry r
            JOIN sys_metric_version v ON v.version_id=r.current_version_id
            WHERE v.implementation_status='verified'
              AND NOT EXISTS (
                  SELECT 1 FROM sys_metric_issue i
                  WHERE i.metric_id=r.metric_id AND i.status='open'
                    AND i.severity='error'
              )
        """) or 0,
        "pendingConfirmation": pending_total,
        "inconsistent": inconsistent,
        "issueTotal": _scalar(conn, """
            SELECT COUNT(*) FROM sys_metric_issue WHERE status='open'
        """) or 0,
        "retired": definition.get("deprecated", 0),
        "boundPages": _scalar(conn, """
            SELECT COUNT(DISTINCT m.path) FROM sys_metric_usage u
            JOIN sys_metric_feature_point fp ON fp.feature_point_id=u.feature_point_id
            JOIN sys_metric_module m ON m.module_id=fp.module_id
        """) or 0,
        "domains": _query(conn, """
            SELECT domain label,COUNT(*) count FROM (
                SELECT r.metric_id,v.domain FROM sys_metric_registry r
                JOIN sys_metric_version v ON v.version_id=r.current_version_id
                UNION ALL
                SELECT c.metric_code,c.domain FROM sys_metric_candidate c
                WHERE c.candidate_status<>'removed_from_source' AND NOT EXISTS (
                    SELECT 1 FROM sys_metric_registry r
                    WHERE r.metric_id=c.metric_code OR r.metric_code=c.metric_code
                )
            ) GROUP BY domain ORDER BY domain
        """),
        "catalogVersion": SCHEMA_VERSION,
    }


def catalog_pages(conn: sqlite3.Connection) -> list[dict]:
    return _query(conn, """
        SELECT m.path page_path,COUNT(DISTINCT u.metric_id) metric_count,
               COUNT(DISTINCT CASE WHEN NOT EXISTS (
                   SELECT 1 FROM sys_metric_issue ix
                   WHERE ix.metric_id=u.metric_id AND ix.status='open'
                     AND ix.severity='error'
               ) THEN u.metric_id END) consistent_count,
               COUNT(DISTINCT CASE WHEN i.status='open' THEN i.metric_id END)
                 issue_count,
               MAX(v.updated_at) updated_at
        FROM sys_metric_usage u
        JOIN sys_metric_feature_point fp ON fp.feature_point_id=u.feature_point_id
        JOIN sys_metric_module m ON m.module_id=fp.module_id
        JOIN sys_metric_registry r ON r.metric_id=u.metric_id
        JOIN sys_metric_version v ON v.version_id=r.current_version_id
        LEFT JOIN sys_metric_issue i ON i.metric_id=u.metric_id
        GROUP BY m.path,m.sort_order ORDER BY m.sort_order,m.path
    """)
