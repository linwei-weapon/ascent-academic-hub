"""Deterministic metric specification normalization and manual overrides.

The normalizer never changes a business formula.  Missing semantics are made
explicit and receive a quality issue instead of being guessed.  Human-reviewed
sources (for example, a faculty metric definition confirmed from a PDF) can be
stored as JSON patches in ``sys_metric_spec_override`` and are applied by the
next idempotent catalog migration.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Mapping


NORMALIZATION_VERSION = "metric-spec-1.0"
UNKNOWN = "以实现/确认口径为准"
NOT_APPLICABLE = "不适用（非比例指标）"

VALUE_TYPE_BY_CALCULATION = {
    "count": "integer_count",
    "ratio": "percentage",
    "average": "average",
    "median": "median",
    "rank": "rank",
    "distribution": "distribution",
    "status": "status",
    "formula": "formula",
    "paired_count": "paired_count",
    # Unknown means the normalizer cannot safely refine the calculation shape;
    # the stored source formula remains the authoritative expression.
    "unknown": "formula",
}

SPECIFICATION_COLUMNS = {
    "specification_json": "TEXT NOT NULL DEFAULT '{}'",
    "specification_status": "TEXT NOT NULL DEFAULT 'needs_review'",
    "specification_source": "TEXT NOT NULL DEFAULT 'deterministic_normalization'",
    "specification_updated_at": "TEXT",
}

SPECIFICATION_OVERRIDE_DDL = """
CREATE TABLE IF NOT EXISTS sys_metric_spec_override (
    override_id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    override_key TEXT NOT NULL DEFAULT 'manual',
    patch_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    changed_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(subject_kind,subject_id,override_key),
    CHECK(subject_kind IN ('formal','candidate')),
    CHECK(status IN ('active','inactive'))
);
CREATE INDEX IF NOT EXISTS idx_metric_spec_override_subject
ON sys_metric_spec_override(subject_kind,subject_id,status,priority);

CREATE TABLE IF NOT EXISTS sys_metric_spec_override_revision (
    revision_id TEXT PRIMARY KEY,
    override_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    override_key TEXT NOT NULL,
    patch_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    priority INTEGER NOT NULL,
    changed_by TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK(subject_kind IN ('formal','candidate')),
    CHECK(action IN ('created','updated','activated','deactivated')),
    CHECK(status IN ('active','inactive')),
    UNIQUE(override_id,revision_no),
    FOREIGN KEY(override_id) REFERENCES sys_metric_spec_override(override_id)
);
CREATE INDEX IF NOT EXISTS idx_metric_spec_override_revision_subject
ON sys_metric_spec_override_revision(subject_kind,subject_id,override_key,recorded_at);
CREATE TRIGGER IF NOT EXISTS trg_metric_spec_override_revision_no_update
BEFORE UPDATE ON sys_metric_spec_override_revision
BEGIN
    SELECT RAISE(ABORT,'metric specification override history is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_metric_spec_override_revision_no_delete
BEFORE DELETE ON sys_metric_spec_override_revision
BEGIN
    SELECT RAISE(ABORT,'metric specification override history is append-only');
END;
"""

PUBLIC_SPEC_FIELDS = {
    "definitionDescription",
    "managementUse",
    "statisticalObject",
    "statisticalScope",
    "calculationType",
    "numerator",
    "denominator",
    "denominatorZeroRule",
    "deduplicationRule",
    "inclusionRule",
    "exclusionRule",
    "boundaryRule",
    "nullHandlingRule",
    "precisionRule",
    "dataSources",
    "dataAsOfRule",
    "notes",
    "qualityDisclosures",
}

CALCULATION_TYPES = {
    "count", "ratio", "average", "median", "rank", "distribution",
    "status", "formula", "paired_count", "unknown",
}


# Code-aligned specification patches for the faculty examples that require
# semantics more precise than generic text normalization can safely infer.
# They describe current implementation evidence; DB overrides remain the
# supported seam for a later human-reviewed PDF or school confirmation.
CURATED_SPEC_PATCHES: dict[str, dict] = {
    "F-01": {
        "definitionDescription": "统计当前授权范围内实际参与有效教学任务的去重教师人数。",
        "indicatorDescription": "实际授课教师：当前授权范围和查询条件内，有效教学任务涉及的主讲教师与联合教师；按教师工号去重。已登记为待处理的高等级教师任务异常记录不纳入统计。",
        "calculationRule": "实际授课教师数 = 当前授权范围内有效教学任务涉及的主讲教师与联合教师按教师工号去重后的数量。",
        "statisticalObject": "实际参与授课的教师",
        "statisticalScope": "当前查询学期、当前身份授权课程范围内的有效教学任务",
        "calculationType": "count",
        "numerator": NOT_APPLICABLE,
        "denominator": NOT_APPLICABLE,
        "denominatorZeroRule": NOT_APPLICABLE,
        "deduplicationRule": "合并主讲及联合教师后按教师工号DISTINCT去重。",
        "inclusionRule": "纳入授权课程有效教学任务关联的主讲及联合教师。",
        "exclusionRule": "排除命中待处理高等级教师任务数据质量问题的记录。",
        "nullHandlingRule": "空教师工号不形成教师计数；被排除记录数应单独披露。",
        "precisionRule": "整数人数，不进行小数舍入。",
    },
    "F-09": {
        "definitionDescription": "计算高职称实际授课教师去重人数占全部实际授课教师去重人数的比例。",
        "indicatorDescription": "• 授课教师总数：当前授权范围和查询条件内教学任务涉及的授课教师去重数；\n• 教授或副教授实际授课教师数：上述授课教师中，职称为教授或副教授且具有真实职称证据的教师去重数。\n职称证据覆盖率低于90%时不输出正式比例；职称缺失教师仍计入分母。",
        "calculationRule": "高职称教师授课占比 = 教授或副教授实际授课教师去重人数 ÷ 当前授权范围实际授课教师去重总数 × 100%。\n分母为0或职称证据覆盖率低于90%时显示“—”。",
        "statisticalObject": "实际授课教师",
        "statisticalScope": "当前查询学期、当前身份授权课程范围",
        "calculationType": "ratio",
        "numerator": "具有真实职称证据且职称为教授或副教授的实际授课教师DISTINCT人数",
        "denominator": "同范围全部实际授课教师DISTINCT人数（包含职称缺失教师）",
        "denominatorZeroRule": "授课教师分母为0时显示“—”，不解释为0%。",
        "deduplicationRule": "分子、分母均按教师工号DISTINCT去重。",
        "inclusionRule": "职称按真实人员快照、正式在职人员主数据、明确标记为真实的教师维表顺序解析。",
        "exclusionRule": "模拟或来源不明的职称不进入分子；职称缺失教师仍保留在分母。",
        "nullHandlingRule": "职称覆盖率低于90%或无已知职称教师时不输出正式比例，显示“—”。",
        "precisionRule": "比例单位为%；具体小数位沿用当前后端输出，不在目录层二次舍入。",
    },
    "F-10": {
        "definitionDescription": "统计满足连续单点、55岁年龄同侧或初中级职称单一结构任一核查规则的去重课程数。",
        "indicatorDescription": "命中以下至少一项规则，则为教师结构异常课程：\n• 规则A（连续单点）：同一课程最近3次实际开课中，同一教师至少2次作为唯一授课教师；只有2次实际开课且均由同一教师唯一承担时也命中。\n• 规则B（年龄结构）：课程授课教师全部≥55岁，或者全部≤55岁；恰好55岁同时属于两侧。年龄数据不完整时不触发本规则。\n• 规则C（职称结构）：课程授课教师职称仅包含助教、讲师；职称数据不完整时不触发本规则。\n同一课程命中多条规则只计1门。",
        "calculationRule": "• 同一教师在同一课程最近3次实际开课中至少2次作为唯一授课教师；\n• 或授课教师年龄全部≥55岁，或者全部≤55岁；\n• 或授课教师职称仅包含助教或讲师。\n命中任一规则后按课程编号去重计数，同一课程最多计1次。",
        "statisticalObject": "命中师资结构核查规则的课程",
        "statisticalScope": "当前查询学期、当前身份授权课程及责任学院范围",
        "calculationType": "count",
        "numerator": NOT_APPLICABLE,
        "denominator": NOT_APPLICABLE,
        "denominatorZeroRule": NOT_APPLICABLE,
        "deduplicationRule": "任一或多项规则命中的课程按课程ID DISTINCT去重，每门课程最多计1次。",
        "inclusionRule": "纳入命中连续单点、年龄同处55岁阈值一侧或职称仅含助教/讲师任一规则的可评价课程。",
        "exclusionRule": "课程组织、有效任务或授课教师证据不足，以及命中高等级任务异常的课程不进入正式结构判定。",
        "boundaryRule": "年龄规则要求所有授课教师证据完整且全部位于≥55岁一侧或≤55岁一侧；恰好55岁同时属于两侧。年龄或职称证据不完整时不触发对应规则。",
        "nullHandlingRule": "年龄或职称证据缺失不按0或默认类别补齐，也不触发对应结构规则。",
        "precisionRule": "整数课程数，不进行小数舍入。",
        "qualityDisclosures": [{
            "field": "boundaryRule",
            "code": "threshold_requires_confirmation",
            "severity": "warning",
            "message": "55岁双侧边界是当前实现规则，正式政策阈值仍需学校确认。",
        }],
    },
    "F-17": {
        "definitionDescription": "并列统计授权课程范围内实际授课教师去重人数与同学期同范围正式在职教师去重人数。",
        "indicatorDescription": "• 授课教师总数：当前授权范围和查询条件内教学任务涉及的授课教师，按教师工号去重；\n• 教职工总数：当前查询学期、同一授权范围内的正式在职教师，按人员工号去重。\n历史学期没有对应人员快照时，教职工总数显示“—”，不使用当前人数回填。",
        "calculationRule": "授课教师总数 = 当前授权教学任务涉及的教师按教师工号去重后的数量；\n教职工总数 = 同学期、同范围正式在职教师按人员工号去重后的数量。",
        "statisticalObject": "实际授课教师与同范围正式在职教师",
        "statisticalScope": "当前查询学期及授权课程范围；人员总数使用同学期、同范围的正式人员数据",
        "calculationType": "paired_count",
        "numerator": NOT_APPLICABLE,
        "denominator": NOT_APPLICABLE,
        "denominatorZeroRule": NOT_APPLICABLE,
        "deduplicationRule": "授课教师和正式在职教师分别按教师/人员工号DISTINCT去重。",
        "inclusionRule": "左侧纳入授权教学任务涉及教师；右侧优先纳入真实人员学期快照，后备使用source=real的正式在职教师主数据。",
        "exclusionRule": "排除导师、班主任、教学关系补出的占位人员及real_partial记录；历史学期不得用当前人员数回填。",
        "nullHandlingRule": "同学期正式人员数据不可用时右侧显示“—”，不以0代替。",
        "precisionRule": "两侧均为整数人数；该卡片不直接计算比例。",
    },
    "F-18": {
        "definitionDescription": "统计同一课程最近最多3次实际开课中至少2次由同一教师单独授课的去重教师人数。",
        "indicatorDescription": "连续单点授课教师：同一教师在同一课程最近最多3次实际开课中，至少2次作为唯一授课教师。最近3次按实际开课记录计算，不按连续自然学期计算；历史观测不足或授课团队为空时不触发。",
        "calculationRule": "连续单点授课教师数 = 满足连续单点条件的教师按教师工号跨课程去重后的数量。",
        "statisticalObject": "命中连续单点课程口径的教师",
        "statisticalScope": "同一课程最近最多3次实际开课记录，不按连续自然学期",
        "calculationType": "count",
        "numerator": NOT_APPLICABLE,
        "denominator": NOT_APPLICABLE,
        "denominatorZeroRule": NOT_APPLICABLE,
        "deduplicationRule": "先按教师—课程识别连续单点，再按教师工号跨课程DISTINCT去重。",
        "inclusionRule": "同一教师在同一课程最近最多3次实际开课中至少2次作为唯一授课教师时纳入。",
        "exclusionRule": "无有效授课团队证据或命中待处理高等级任务异常的开课记录不用于正式判定。",
        "nullHandlingRule": "历史观测不足或授课团队为空时不触发连续单点，不以缺失记录补足次数。",
        "precisionRule": "整数教师数，不进行小数舍入。",
    },
    "F-19": {
        "definitionDescription": "计算具有真实年龄证据且年龄小于35岁的实际授课教师去重人数占全部实际授课教师去重人数的比例。",
        "indicatorDescription": "• 授课教师总数：当前授权范围和查询条件内教学任务涉及的授课教师去重数；\n• 35岁以下青年授课教师数：上述授课教师中，具有真实年龄证据且年龄小于35岁的教师去重数。\n年龄缺失教师仍计入分母；按照确认口径，年龄证据覆盖率低于90%时不输出正式比例。",
        "calculationRule": "青年教师授课占比 = 35岁以下青年授课教师去重人数 ÷ 当前授权范围实际授课教师去重总数 × 100%。\n分母为0或年龄证据覆盖率低于90%时显示“—”。",
        "statisticalObject": "当前授权教学范围内参与授课的教师",
        "statisticalScope": "当前查询学期、当前身份授权课程范围",
        "calculationType": "ratio",
        "numerator": "具有真实年龄证据且当前年龄小于35岁的实际授课教师DISTINCT人数",
        "denominator": "同范围全部实际授课教师DISTINCT人数（包含年龄缺失教师）",
        "denominatorZeroRule": "授课教师分母为0或不可得时显示“—”，不解释为0%。",
        "deduplicationRule": "分子、分母均按教师工号DISTINCT去重。",
        "inclusionRule": "青年标识只使用真实人员快照中的出生日期、受控年龄段或明确青年标识。",
        "exclusionRule": "模拟年龄画像不进入分子；年龄缺失教师仍保留在分母。",
        "boundaryRule": "确认书要求年龄证据覆盖率低于90%不输出正式比例；当前代码在至少存在1条年龄证据时仍计算比例并标记partial，两者尚未一致。",
        "nullHandlingRule": "无年龄证据时青年人数和比例显示“—”；部分覆盖时当前实现输出partial参考值，不得视为完全符合正式90%门槛。",
        "precisionRule": "当前卡片比例保留2位小数；目录不再二次舍入。",
        "qualityDisclosures": [{
            "field": "inclusionRule",
            "code": "implementation_definition_mismatch",
            "severity": "error",
            "message": "正式90%年龄覆盖门槛与当前partial计算行为不一致。",
        }],
    },
    "TA.FAC.EVALUABLE_COURSES": {
        "definitionDescription": "统计同时满足有效教学班、可识别授课教师、责任学院映射及任务质量门禁的去重课程数。",
        "indicatorDescription": "师资结构可评价课程：同时具有至少1个有效教学班、至少1名可识别授课教师、可映射责任学院，并且不存在被排除的高等级教学任务异常。关键证据缺失的课程只进入数据候选，不进入正式结构判定。",
        "calculationRule": "师资结构可评价课程数 = 同时满足有效教学班、授课教师、责任学院和任务质量门禁的课程按课程编号去重后的数量。",
        "statisticalObject": "满足师资结构评价最低数据门禁的课程",
        "statisticalScope": "当前查询学期、筛选条件及授权课程范围",
        "calculationType": "count",
        "numerator": NOT_APPLICABLE,
        "denominator": NOT_APPLICABLE,
        "denominatorZeroRule": NOT_APPLICABLE,
        "deduplicationRule": "按课程ID DISTINCT去重。",
        "inclusionRule": "课程至少有1个有效教学班、1名可识别授课教师、可映射责任学院，且没有被排除的高等级教学任务异常。",
        "exclusionRule": "责任学院缺失、授课教师为空、无有效教学任务或存在被排除任务记录的课程不进入可评价集合。",
        "nullHandlingRule": "关键证据缺失时进入数据候选，不触发需要完整证据的结构规则。",
        "precisionRule": "整数课程数，不进行小数舍入。",
    },
    "TA.FAC.IMPORTANT_COURSE_FLAG": {
        "definitionDescription": "按必修标志或课程名称、性质、类别中的重点关键词，为每门课程生成一个重点课程布尔标识。",
        "indicatorDescription": "重点课程：课程必修标志为“是”，或者课程名称、课程性质、课程类别任一字段命中必修、主干、核心、基础、思想、政治、体育、数学、英语等重点关键词。必修标志和文本证据均不足时不判定为重点课程。",
        "calculationRule": "课程必修标志为“是”，或课程名称、课程性质、课程类别任一字段命中重点关键词时，判定为重点课程；否则判定为非重点课程。",
        "statisticalObject": "授权范围内课程",
        "statisticalScope": "当前查询学期、筛选条件及授权课程范围",
        "calculationType": "status",
        "numerator": NOT_APPLICABLE,
        "denominator": NOT_APPLICABLE,
        "denominatorZeroRule": NOT_APPLICABLE,
        "deduplicationRule": "按课程ID形成一个布尔判定结果；同一课程多个命中条件不重复。",
        "inclusionRule": "课程必修标志=1，或课程名称、性质、类别任一字段命中当前重点关键词词表时为真。",
        "exclusionRule": "未命中必修标志和关键词的课程为假；缺失字段不得推断为命中。",
        "nullHandlingRule": "必修标志及文本证据均不足时不触发重点课程识别，且不得据此形成风险结论。",
        "precisionRule": "布尔值（是/否），不涉及数值舍入。",
        "qualityDisclosures": [{
            "field": "inclusionRule",
            "code": "keyword_policy_requires_confirmation",
            "severity": "warning",
            "message": "当前关键词词表是原型规则，正式生产词表仍需学校确认。",
        }],
    },
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_specification_schema(conn: sqlite3.Connection) -> None:
    """Idempotently upgrade a pre-specification V2 database in place."""
    conn.executescript(SPECIFICATION_OVERRIDE_DDL)
    for table in ("sys_metric_candidate", "sys_metric_version"):
        existing = _columns(conn, table)
        for column, ddl in SPECIFICATION_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _stable_override_id(subject_kind: str, subject_id: str, override_key: str) -> str:
    raw = f"{subject_kind}\x1f{subject_id}\x1f{override_key}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"spec-override:{digest}"


def _validate_override_patch(patch: Mapping[str, object]) -> None:
    unknown = set(patch) - PUBLIC_SPEC_FIELDS
    if unknown:
        raise ValueError(f"unsupported specification fields: {sorted(unknown)}")
    if not patch:
        raise ValueError("specification override patch cannot be empty")
    for field, value in patch.items():
        if field in {"dataSources", "qualityDisclosures"}:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        if not value.strip():
            raise ValueError(f"{field} cannot be blank")
    if "calculationType" in patch and patch["calculationType"] not in CALCULATION_TYPES:
        raise ValueError(f"unsupported calculationType: {patch['calculationType']}")
    if "dataSources" in patch and (
        not isinstance(patch["dataSources"], list)
        or not patch["dataSources"]
        or not all(isinstance(item, str) for item in patch["dataSources"])
        or not all(item.strip() for item in patch["dataSources"])
    ):
        raise ValueError("dataSources must be a non-empty list of non-blank strings")
    disclosures = patch.get("qualityDisclosures")
    if disclosures is not None:
        if not isinstance(disclosures, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("field"), str)
            and bool(item["field"].strip())
            and isinstance(item.get("code"), str)
            and bool(item["code"].strip())
            and item.get("severity", "warning") in {"info", "warning", "error"}
            for item in disclosures
        ):
            raise ValueError(
                "qualityDisclosures must contain field/code objects with a valid severity"
            )


def _normalize_subject_id(
    conn: sqlite3.Connection, subject_kind: str, subject_id: str,
) -> str:
    if subject_kind == "formal":
        row = conn.execute("""
            SELECT metric_id FROM sys_metric_registry
            WHERE metric_id=? OR metric_code=? LIMIT 1
        """, (subject_id, subject_id)).fetchone()
    else:
        row = conn.execute("""
            SELECT metric_code,source_key FROM sys_metric_candidate
            WHERE candidate_id=? OR metric_code=? OR source_key=?
            ORDER BY CASE WHEN metric_code=? OR source_key=? THEN 0 ELSE 1 END,
                     candidate_id
            LIMIT 1
        """, (
            subject_id, subject_id, subject_id, subject_id, subject_id,
        )).fetchone()
    if not row:
        raise ValueError(f"unknown {subject_kind} specification subject: {subject_id}")
    if subject_kind == "formal":
        return str(row[0])
    # Candidate overrides deliberately use the API-visible metric code (with
    # source_key as fallback), never the internal hash candidate_id.
    return str(row[0] or row[1])


def _append_override_revision(
    conn: sqlite3.Connection,
    *,
    override_id: str,
    action: str,
    status: str,
    subject_kind: str,
    subject_id: str,
    override_key: str,
    patch_json: str,
    reason: str,
    source_ref: str,
    priority: int,
    changed_by: str | None,
) -> None:
    revision_no = conn.execute("""
        SELECT COALESCE(MAX(revision_no),0)+1
        FROM sys_metric_spec_override_revision WHERE override_id=?
    """, (override_id,)).fetchone()[0]
    conn.execute("""
        INSERT INTO sys_metric_spec_override_revision(
            revision_id,override_id,revision_no,action,status,subject_kind,
            subject_id,override_key,patch_json,reason,source_ref,priority,
            changed_by
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        f"{override_id}:r{revision_no}", override_id, revision_no, action,
        status, subject_kind, subject_id, override_key, patch_json, reason,
        source_ref, priority, changed_by,
    ))


def upsert_specification_override(
    conn: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_id: str,
    patch: Mapping[str, object],
    reason: str,
    source_ref: str,
    override_key: str = "manual",
    priority: int = 100,
    changed_by: str | None = None,
) -> str:
    """Store a reviewed override without altering formulas or source seeds.

    The catalog migration materializes the effective specification.  Multiple
    active patches are merged in ascending priority order, so a larger priority
    wins for fields set by more than one source.
    """
    if subject_kind not in {"formal", "candidate"}:
        raise ValueError("subject_kind must be formal or candidate")
    if not isinstance(patch, Mapping):
        raise ValueError("specification override patch must be an object")
    _validate_override_patch(patch)
    if not isinstance(reason, str) or not isinstance(source_ref, str):
        raise ValueError("reason and source_ref must be strings")
    if not reason.strip() or not source_ref.strip():
        raise ValueError("reason and source_ref are required")
    subject_id = _normalize_subject_id(conn, subject_kind, subject_id)
    override_id = _stable_override_id(subject_kind, subject_id, override_key)
    patch_json = json.dumps(dict(patch), ensure_ascii=False, sort_keys=True)
    current = conn.execute("""
        SELECT patch_json,reason,source_ref,priority,status,changed_by
        FROM sys_metric_spec_override WHERE override_id=?
    """, (override_id,)).fetchone()
    effective = (
        patch_json, reason.strip(), source_ref.strip(), int(priority),
        "active", changed_by,
    )
    conn.execute("""
        INSERT INTO sys_metric_spec_override(
            override_id,subject_kind,subject_id,override_key,patch_json,reason,
            source_ref,priority,status,changed_by
        ) VALUES(?,?,?,?,?,?,?,?,'active',?)
        ON CONFLICT(subject_kind,subject_id,override_key) DO UPDATE SET
            patch_json=excluded.patch_json,reason=excluded.reason,
            source_ref=excluded.source_ref,priority=excluded.priority,
            status='active',changed_by=excluded.changed_by,
            updated_at=datetime('now','localtime')
    """, (
        override_id, subject_kind, subject_id, override_key,
        patch_json,
        reason.strip(), source_ref.strip(), int(priority), changed_by,
    ))
    if current is None or tuple(current) != effective:
        action = (
            "created" if current is None
            else "activated" if current[4] == "inactive" else "updated"
        )
        _append_override_revision(
            conn, override_id=override_id, action=action, status="active",
            subject_kind=subject_kind, subject_id=subject_id,
            override_key=override_key, patch_json=patch_json,
            reason=reason.strip(), source_ref=source_ref.strip(),
            priority=int(priority), changed_by=changed_by,
        )
    return override_id


def set_specification_override_status(
    conn: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_id: str,
    override_key: str = "manual",
    active: bool,
    changed_by: str | None = None,
) -> str:
    """Activate/deactivate an override while preserving an append-only event."""
    if subject_kind not in {"formal", "candidate"}:
        raise ValueError("subject_kind must be formal or candidate")
    subject_id = _normalize_subject_id(conn, subject_kind, subject_id)
    override_id = _stable_override_id(subject_kind, subject_id, override_key)
    row = conn.execute("""
        SELECT patch_json,reason,source_ref,priority,status
        FROM sys_metric_spec_override WHERE override_id=?
    """, (override_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown specification override: {override_id}")
    status = "active" if active else "inactive"
    if row[4] == status:
        return override_id
    conn.execute("""
        UPDATE sys_metric_spec_override
        SET status=?,changed_by=?,updated_at=datetime('now','localtime')
        WHERE override_id=?
    """, (status, changed_by, override_id))
    _append_override_revision(
        conn, override_id=override_id,
        action="activated" if active else "deactivated", status=status,
        subject_kind=subject_kind, subject_id=subject_id,
        override_key=override_key, patch_json=row[0], reason=row[1],
        source_ref=row[2], priority=int(row[3]), changed_by=changed_by,
    )
    return override_id


def _object_from_text(source: Mapping[str, object]) -> str:
    grain = str(source.get("grain") or "").strip()
    if grain:
        return grain.split("×", 1)[0].strip()
    text = " ".join(str(source.get(key) or "") for key in (
        "name", "formula", "domain", "boundary",
    ))
    objects = (
        ("学生", ("学生", "学业", "毕业")),
        ("教师", ("教师", "师资", "教职工")),
        ("课程", ("课程", "开课", "修读")),
        ("教学班", ("教学班",)),
        ("行政班", ("行政班", "班级")),
        ("教室", ("教室", "楼宇")),
        ("预警事件", ("预警事件", "规则命中")),
        ("调停课事件", ("调课", "停课", "调停课")),
    )
    for label, words in objects:
        if any(word in text for word in words):
            return label
    return UNKNOWN


def _calculation_type(source: Mapping[str, object]) -> str:
    name = str(source.get("name") or "")
    formula = str(source.get("formula") or "")
    unit = str(source.get("unit") or "")
    text = f"{name} {formula}"
    if unit == "%" or any(word in name for word in ("率", "占比", "比例", "覆盖度")):
        return "ratio"
    if any(word in text for word in ("平均", "均值", "AVG", "人均")):
        return "average"
    if any(word in text for word in ("中位", "P50")):
        return "median"
    if any(word in text for word in ("排名", "排行", "分位")):
        return "rank"
    if any(word in text for word in ("分布", "分档", "档位", "区间")):
        return "distribution"
    if any(word in text for word in ("数量", "人数", "人次", "门数", "次数", "总数", "计数", "COUNT")):
        return "count"
    if any(word in text for word in ("是否", "状态", "候选")):
        return "status"
    if formula:
        return "formula"
    return "unknown"


def _split_fraction(formula: str) -> tuple[str | None, str | None]:
    normalized = formula.strip()
    if "÷" in normalized:
        numerator, denominator = normalized.split("÷", 1)
    elif re.search(r"\s/\s", normalized):
        numerator, denominator = re.split(r"\s/\s", normalized, maxsplit=1)
    else:
        return None, None
    denominator = re.sub(r"(?:×|\*)\s*100%.*$", "", denominator).strip()
    return numerator.strip(" （("), denominator.strip(" ）);；")


def _dependency_parts(
    metric_id: str,
    dependencies: Iterable[Mapping[str, object]],
    metric_names: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    numerators: list[str] = []
    denominators: list[str] = []
    for edge in dependencies:
        if edge.get("source_metric_id") != metric_id:
            continue
        target = str(edge.get("target_metric_id") or "")
        label = metric_names.get(target, target)
        relation = str(edge.get("relation_type") or "")
        if relation == "numerator":
            numerators.append(label)
        elif relation == "denominator":
            denominators.append(label)
    return sorted(set(numerators)), sorted(set(denominators))


def _data_sources(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        result = [str(item).strip() for item in value if str(item).strip()]
    else:
        result = [item.strip() for item in re.split(
            r"\s*/\s*|\s*,\s*", str(value or "")
        ) if item.strip()]
    return result or [UNKNOWN]


def _description(source: Mapping[str, object], statistical_object: str) -> str:
    name = str(source.get("name") or "未命名指标").strip()
    description = str(source.get("description") or "").strip()
    management = str(source.get("management_value") or "").strip()
    if description and description != management:
        return description
    # Extension packs historically copied the only available prose into both
    # description and management_value.  Keep definition-like wording such as
    # “统计/汇总……” intact: replacing it with a generic sentence would discard
    # useful semantics.  Only prose that clearly describes a management use is
    # rewritten into a definition.
    management_opening = re.compile(
        r"^(?:主要)?(?:用于|支持|观察|比较|评价|判断|识别|定位|衡量)"
    )
    if description and not management_opening.search(description):
        return description
    object_text = statistical_object if statistical_object != UNKNOWN else "目标统计对象"
    formula = str(source.get("formula") or "").strip() or UNKNOWN
    grain = str(source.get("grain") or "").strip() or UNKNOWN
    return (
        f"{name}按“{formula}”计算指定范围内{object_text}的结果，"
        f"统计粒度为“{grain}”。"
    )


_FORMULA_TERMS = {
    "academic_year_offset": "入学学年偏移量", "action": "需行动", "action_required": "需要行动",
    "active": "有效", "activity_type": "活动类型", "affected_students": "受影响学生数",
    "agg_course_offering": "课程开课汇总记录", "agg_teacher_load": "教师工作量汇总记录",
    "alert_event": "预警事件", "applicable": "适用", "assessable": "可评价", "assigned": "归属",
    "associated": "关联", "attempt": "成绩尝试", "attention_score": "关注分",
    "available": "可用", "binding": "绑定", "binding_status": "绑定状态", "bottleneck": "瓶颈项",
    "bound": "已绑定", "built": "已生成", "calendar_month": "自然月", "candidate": "候选",
    "capacity": "容量", "category": "类别", "cell": "周次节次单元", "class_count": "教学班数",
    "class_size_band": "班额区间", "classification": "分类", "classroom": "教室",
    "classroom_id": "教室编号", "classroom_occupancy": "教室占用记录", "closed": "已关闭",
    "college": "学院", "completeness": "完整性", "conflict": "冲突", "course": "课程",
    "course_count": "课程数", "course_credit": "课程学分", "course_id": "课程编号",
    "course_name": "课程名称", "course_nature": "课程性质", "course_substitution": "课程替代关系",
    "created_at": "创建时间", "credit": "学分", "current_term": "当前培养学期",
    "data": "数据", "due_candidate_courses": "应修候选课程数", "effective": "有效",
    "enrolled": "修读人数", "enrolled_visits": "修读人次", "entry_grade": "入学年级",
    "event": "事件", "evidence": "证据", "evidence_status": "证据状态", "exists": "存在",
    "explicit_gap": "明确缺口", "fact_alert": "预警事实", "faculty": "师资",
    "fail_count": "未通过次数", "failed_required_courses": "必修未通过课程数", "false": "否",
    "first": "首考", "flag": "标识", "grade": "年级", "graduation": "毕业核查",
    "has": "具有", "history": "历史", "hours": "学时", "id": "编号", "inferred": "推断范围",
    "insufficient": "不足", "is_assessable": "是否可评价", "is_complete": "是否完成",
    "items": "项目", "judgement": "判定", "known": "已知", "latest_is_pass": "最新结果是否通过",
    "lesson": "教学班", "lesson_college": "开课学院", "lesson_count": "教学班数",
    "lesson_id": "教学班编号", "lesson_meeting": "排课记录", "lesson_teacher": "教学班教师关系",
    "lessons": "教学班", "lookback": "回溯期", "major": "专业", "major_id": "专业编号",
    "makeup": "补考", "mapping": "映射", "master": "主数据", "matched": "已匹配",
    "matches": "匹配", "matching": "匹配", "meeting": "排课记录",
    "meeting_period_length": "单次排课节数", "meeting_weeks": "排课周数", "met": "已满足",
    "minimum": "最低要求", "missing": "缺失", "module": "培养模块", "new": "待核查",
    "no": "无", "normalized": "标准化", "numeric": "数值型", "occupancy": "占用记录",
    "occupancy_id": "占用记录编号", "occupied_date": "占用日期", "offering": "开课安排",
    "outside": "外部", "overlap": "重叠", "passed": "通过", "passing": "通过",
    "percentage": "百分比", "period": "节次", "period_start": "起始节次", "plan": "培养方案",
    "plan_id": "培养方案编号", "plan_student_mapping": "学生培养方案映射记录",
    "points": "百分点", "primary_teacher_id": "主讲教师工号", "priority_review": "优先复核",
    "progress": "培养进度", "readiness": "毕业准备", "readiness_status": "毕业准备状态",
    "reason": "原因", "recommended_term": "建议修读学期", "required": "必修",
    "required_credits": "要求学分", "requirement": "要求", "requires": "需要",
    "resolved": "已解除", "result": "结果", "retake": "重修", "review": "核查",
    "rule": "规则", "schedule_change_event": "调停课事件", "scope": "范围", "score": "成绩",
    "semantic": "语义", "semester": "学期", "semesters": "学期", "source": "来源",
    "stage": "考试阶段", "status": "状态", "structure": "结构", "student": "学生",
    "student_count": "学生人次", "student_id": "学号", "substitute": "替代课程",
    "substitution": "替代关系", "target": "目标", "tasks": "教学任务", "teacher": "教师",
    "teacher_id": "教师工号", "teaching": "教学", "teaching_lesson": "教学班",
    "term_first_fail_rate": "学期首考未通过率", "term_index": "学期序号", "title": "职称",
    "total_hours": "总学时", "training_plan": "培养方案", "training_plan_module": "培养方案模块",
    "true": "是", "type": "类型", "unmet": "未满足", "valid": "有效",
    "verification": "需核验", "volatility": "波动值", "weekday": "星期",
    "workflow_status": "管理状态", "priority": "优先级", "rate": "比例",
    "staff": "人员", "current": "当前", "term": "学期", "value": "数值",
    "where": "，其中", "and": "且", "or": "或", "not": "不", "in": "属于",
    "among": "在下列项目中", "by": "按", "every": "全部", "for": "针对", "is": "为",
    "to": "到", "with": "关联", "of": "的", "from": "来自", "outside": "外部",
    "count": "计数", "distinct": "去重", "sum": "求和", "avg": "平均值", "median": "中位数",
    "max": "最大值", "min": "最小值", "group": "分组", "order": "排序", "within": "范围内",
    "nullif": "零值排除", "percentile_cont": "百分位数", "p": "百分位数",
}


def _translate_formula_terms(text: str) -> str:
    phrase_replacements = (
        (r"\bvalid\s+grade\s+attempt\b", "有效成绩尝试"),
        (r"\bgrade\s+attempt\b", "成绩尝试"),
        (r"\bactive\s+student\s+matching\s+plan\s+grade/major\s+scope\b", "符合培养方案年级与专业适用范围的有效学生"),
        (r"\bactive\s+student\b", "有效学生"),
        (r"\bmatching\s+plan\s+grade/major\s+scope\b", "匹配培养方案年级与专业范围"),
        (r"\bpercentage\s+points\b", "个百分点"),
        (r"\bNo\s+Data\b", "无数据"),
        (r"P90", "第90百分位数"),
        (r"CET-?4", "大学英语四级"),
    )
    for pattern, replacement in phrase_replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)

    def replace_token(match: re.Match) -> str:
        token = match.group(0)
        lower = token.casefold()
        if lower == "gpa":
            return "平均学分绩点"
        if lower == "cet":
            return "大学英语等级"
        translated = _FORMULA_TERMS.get(lower)
        if translated:
            return translated
        if "_" in lower:
            parts = [_FORMULA_TERMS.get(part, "业务字段") for part in lower.split("_")]
            return "".join(parts)
        return "业务字段"

    return re.sub(r"[A-Za-z_]+", replace_token, text)


def _chinese_calculation_rule(name: str, formula: str) -> str:
    """Convert implementation-like formula text into a Chinese business rule."""
    text = formula.strip() or UNKNOWN
    # Presentation and drill-down instructions belong to usage documentation,
    # not to the calculation rule shown beside the indicator definition.
    text = re.split(
        r"[。；](?=(?:下钻|页面|名单|图表|支持|默认|导出|卡片|副文案|标题|弹窗))",
        text,
        maxsplit=1,
    )[0].strip("；。 ")
    text = re.sub(r"R(\d+)W", r"规则\1警告级", text, flags=re.I)
    text = re.sub(r"R(\d+)", r"规则\1", text, flags=re.I)
    text = re.sub(r"\bP90\b", "第90百分位数", text, flags=re.I)
    text = re.sub(
        r"MIN\s*[（(]\s*MAX\s*[（(]\s*([^()（）]*?)\s*,\s*0\s*[）)]\s*,\s*3\s*[）)]",
        r"\1先与0比较取较大值，再与3比较取较小值",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"AVG\s*[（(]\s*NULLIF\s*[（(]\s*([^,()（）]+)\s*,\s*0\s*[）)]\s*[）)]",
        r"\1非0记录的平均值",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(COUNT|SUM|AVG|MEDIAN|MAX|MIN)\s*（", r"\1(", text, flags=re.I,
    )
    text = text.replace("）", ")")
    if text.count("(") > text.count(")"):
        text += ")" * (text.count("(") - text.count(")"))
    text = re.sub(
        r"PERCENTILE_CONT\s*\(\s*0\.9\s*\)\s*WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+([^()]*)\)",
        lambda match: f"{_translate_formula_terms(match.group(1))}的第90百分位数",
        text,
        flags=re.I,
    )
    group_match = re.search(r"\s+GROUP\s+BY\s+(.+)$", text, flags=re.I)
    group_text = ""
    if group_match:
        group_text = _translate_formula_terms(group_match.group(1).strip())
        text = text[:group_match.start()].strip()

    def distinct_count(value: str) -> str:
        if "，其中" in value:
            subject, condition = value.split("，其中", 1)
            return f"在{condition}的记录中，按{subject}去重计数"
        return f"按{value}去重计数"

    def ordinary_count(value: str) -> str:
        if "，其中" in value:
            subject, condition = value.split("，其中", 1)
            return f"统计满足{condition}的{subject}数量"
        return f"统计{value}的数量"

    function_patterns = (
        (r"COUNT\s*\(\s*DISTINCT\s+([^()]*)\)", distinct_count),
        (r"COUNT\s*\(\s*([^()]*)\)", ordinary_count),
        (r"SUM\s*\(\s*([^()]*)\)", lambda value: f"对{value}求和"),
        (r"AVG\s*\(\s*([^()]*)\)", lambda value: f"计算{value}的平均值"),
        (r"MEDIAN\s*\(\s*([^()]*)\)", lambda value: f"计算{value}的中位数"),
        (r"MAX\s*\(\s*([^()]*)\)", lambda value: f"取{value}的最大值"),
        (r"MIN\s*\(\s*([^()]*)\)", lambda value: f"取{value}的最小值"),
    )
    for pattern, renderer in function_patterns:
        text = re.sub(
            pattern,
            lambda match, fn=renderer: fn(_translate_formula_terms(match.group(1).strip())),
            text,
            flags=re.I,
        )
    text = re.sub(r"NULLIF\s*\(([^,]+),\s*0\)", r"\1（为0时不参与）", text, flags=re.I)
    text = re.sub(r"\bNOT\s+IN\b", "不属于", text, flags=re.I)
    text = re.sub(r"\bWHERE\b", "，其中", text, flags=re.I)
    text = re.sub(r"\bAND\b", "且", text, flags=re.I)
    text = re.sub(r"\bOR\b", "或", text, flags=re.I)
    text = re.sub(r"\bIN\b", "属于", text, flags=re.I)
    text = _translate_formula_terms(text)
    text = text.replace("'", "“").replace('"', "”")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*([，；。÷×=<>≥≤＋－/])\s*", r"\1", text)
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u3400-\u9fff])\.(?=[\u3400-\u9fff])", "的", text)
    text = text.replace(",", "、")
    text = text.replace("(", "（").replace(")", "）")
    if group_text:
        text = f"按{group_text}分组，{text}"
    display_name = _translate_formula_terms(name)
    if not text.startswith((name, display_name, "•")) and not any(
        marker in text for marker in ("判为", "命中", "分类为")
    ):
        text = f"{display_name} = {text}"
    if text and text[-1] not in "。；":
        text += "。"
    return text


def _indicator_description(name: str, spec: Mapping[str, object]) -> str:
    lines = [str(spec.get("definitionDescription") or f"{name}的统计定义待确认。").strip()]
    if spec.get("calculationType") == "ratio":
        numerator = str(spec.get("numerator") or "").strip()
        denominator = str(spec.get("denominator") or "").strip()
        if numerator and UNKNOWN not in numerator:
            lines.append(f"• 分子：{numerator}；")
        if denominator and UNKNOWN not in denominator:
            lines.append(f"• 分母：{denominator}。")
    for label, field in (
        ("去重规则", "deduplicationRule"),
        ("适用边界", "boundaryRule"),
    ):
        value = str(spec.get(field) or "").strip()
        if value and value != NOT_APPLICABLE and UNKNOWN not in value:
            lines.append(f"• {label}：{value}")
    return "\n".join(dict.fromkeys(lines))


def _quality(
    spec: dict, *, subject_kind: str, override_sources: list[dict],
    curated_applied: bool,
) -> dict:
    issues: list[dict] = []
    required = {
        "definitionDescription": "definition_description_unconfirmed",
        "managementUse": "management_use_unconfirmed",
        "statisticalObject": "statistical_object_unconfirmed",
        "statisticalScope": "statistical_scope_unconfirmed",
        "calculationFormula": "calculation_formula_unconfirmed",
        "deduplicationRule": "deduplication_unconfirmed",
        "inclusionRule": "inclusion_unconfirmed",
        "exclusionRule": "exclusion_unconfirmed",
        "boundaryRule": "boundary_unconfirmed",
        "nullHandlingRule": "null_handling_unconfirmed",
        "precisionRule": "precision_unconfirmed",
        "dataAsOfRule": "data_as_of_unconfirmed",
    }
    for field, code in required.items():
        if UNKNOWN in str(spec.get(field) or ""):
            issues.append({"field": field, "code": code})
    if spec.get("calculationType") == "unknown":
        issues.append({
            "field": "calculationType", "code": "calculation_type_unconfirmed",
        })
    if any(UNKNOWN in str(item) for item in spec.get("dataSources", [])):
        issues.append({"field": "dataSources", "code": "data_source_unconfirmed"})
    if spec.get("calculationType") == "ratio":
        for field, code in (
            ("numerator", "numerator_unconfirmed"),
            ("denominator", "denominator_unconfirmed"),
            ("denominatorZeroRule", "denominator_zero_unconfirmed"),
        ):
            if UNKNOWN in str(spec.get(field) or ""):
                issues.append({"field": field, "code": code})
    if subject_kind == "candidate":
        issues.append({"field": "catalogStatus", "code": "candidate_not_code_verified"})
    disclosures = spec.get("qualityDisclosures") or []
    for disclosure in disclosures:
        if isinstance(disclosure, dict) and disclosure.get("field") and disclosure.get("code"):
            issues.append(dict(disclosure))
    deduplicated = {(item["field"], item["code"]): item for item in issues}
    issues = [deduplicated[key] for key in sorted(deduplicated)]
    if subject_kind == "candidate":
        status = "candidate_needs_confirmation"
    elif any(item.get("severity") == "error" for item in issues):
        status = "mismatch"
    elif issues:
        status = "override_applied_needs_review" if override_sources else "needs_review"
    else:
        status = "override_applied" if override_sources else "complete"
    return {
        "status": status,
        "issues": issues,
        "normalizationVersion": NORMALIZATION_VERSION,
        "overrideApplied": bool(override_sources),
        "overrideSources": override_sources,
        "curatedSpecificationApplied": curated_applied,
    }


def build_specification(
    source: Mapping[str, object],
    *,
    subject_kind: str,
    dependencies: Iterable[Mapping[str, object]] = (),
    metric_names: Mapping[str, str] | None = None,
    override_rows: Iterable[Mapping[str, object]] = (),
) -> dict:
    """Build one deterministic specification without changing its formula."""
    metric_id = str(source.get("metric_id") or source.get("metric_code") or "")
    name = str(source.get("name") or metric_id)
    formula = str(source.get("formula") or "").strip() or UNKNOWN
    boundary = str(source.get("boundary") or "").strip() or UNKNOWN
    management_use = str(source.get("management_value") or "").strip() or UNKNOWN
    statistical_object = _object_from_text(source)
    grain = str(source.get("grain") or "").strip()
    domain = str(source.get("domain") or "其他").strip()
    statistical_scope = (
        f"业务域：{domain}；统计粒度：{grain}"
        if grain else f"业务域：{domain}；具体组织、对象及时间范围{UNKNOWN}"
    )
    calculation_type = _calculation_type(source)
    parsed_numerator, parsed_denominator = _split_fraction(formula)
    dep_numerators, dep_denominators = _dependency_parts(
        metric_id, dependencies, metric_names or {},
    )
    is_ratio = calculation_type == "ratio"
    numerator = "；".join(dep_numerators) or parsed_numerator or (
        UNKNOWN if is_ratio else NOT_APPLICABLE
    )
    denominator = "；".join(dep_denominators) or parsed_denominator or (
        UNKNOWN if is_ratio else NOT_APPLICABLE
    )
    combined = " ".join((formula, boundary))
    zero_rule = re.search(
        r"分母\s*(?:为|=)\s*0.*?(?:不输出|为空|NULL|显示\s*[“”\"']*[—-])",
        combined,
        re.I,
    )
    if is_ratio and zero_rule:
        denominator_zero = "分母为0时按现有口径显示“—”或不输出，不得将结果解释为0%。"
    elif is_ratio:
        denominator_zero = f"未在现有证据中确认；不得默认按0处理，需{UNKNOWN}"
    else:
        denominator_zero = NOT_APPLICABLE
    deduplication = (
        "公式或边界已明确去重；具体去重业务键以实现证据为准。"
        if "去重" in combined else f"去重层级和业务键{UNKNOWN}"
    )
    null_handling = (
        "按现有公式或边界中明确的缺失值规则处理；未明示字段不得擅自补零。"
        if any(word in combined for word in ("缺失", "为空", "NULL", "无有效"))
        else f"空值、缺失值及无有效记录的处理方式{UNKNOWN}"
    )
    precision = (
        f"单位为{source.get('unit')}；小数位和舍入方式{UNKNOWN}"
        if source.get("unit") else f"展示单位、小数位和舍入方式{UNKNOWN}"
    )
    spec = {
        "definitionDescription": _description(source, statistical_object),
        "managementUse": management_use,
        "statisticalObject": statistical_object,
        "statisticalScope": statistical_scope,
        "calculationType": calculation_type,
        "calculationFormula": formula,
        "numerator": numerator,
        "denominator": denominator,
        "denominatorZeroRule": denominator_zero,
        "deduplicationRule": deduplication,
        "inclusionRule": f"按现有公式、统计范围和边界中明确的条件纳入；未明示条件{UNKNOWN}",
        "exclusionRule": f"按现有边界中明确的条件排除；未明示排除项{UNKNOWN}",
        "boundaryRule": boundary,
        "nullHandlingRule": null_handling,
        "precisionRule": precision,
        "dataSources": _data_sources(source.get("data_source")),
        "dataAsOfRule": str(source.get("update_cycle") or "").strip() or UNKNOWN,
        "notes": "",
        "qualityDisclosures": [],
    }
    curated_patch = CURATED_SPEC_PATCHES.get(metric_id)
    if curated_patch:
        spec.update(curated_patch)
    override_sources: list[dict] = []
    ordered_overrides = sorted(
        (dict(row) for row in override_rows),
        key=lambda row: (int(row.get("priority") or 0), str(row.get("override_id") or "")),
    )
    for row in ordered_overrides:
        patch = json.loads(str(row["patch_json"]))
        if not isinstance(patch, dict):
            raise ValueError("persisted specification override patch must be an object")
        _validate_override_patch(patch)
        disclosures = list(spec.get("qualityDisclosures") or [])
        for key, value in patch.items():
            if key == "qualityDisclosures":
                disclosures.extend(value)
            else:
                spec[key] = value
        spec["qualityDisclosures"] = disclosures
        override_sources.append({
            "overrideId": row.get("override_id"),
            "overrideKey": row.get("override_key"),
            "reason": row.get("reason"),
            "sourceRef": row.get("source_ref"),
            "changedBy": row.get("changed_by"),
        })
    # This separation is a hard contract: management purpose is not a metric
    # definition.  If an override accidentally makes them equal, retain the
    # reviewed purpose and regenerate a neutral definition description.
    if str(spec["definitionDescription"]).strip() == str(spec["managementUse"]).strip():
        spec["definitionDescription"] = (
            f"{name}描述指定统计范围内{statistical_object}的口径结果；"
            "定义内容与管理用途分开维护。"
        )
    # The query page follows the confirmed reference layout: a readable
    # indicator explanation plus one Chinese calculation rule.  The detailed
    # specification remains stored for governance, but is not a separate UI
    # section.
    if not str(spec.get("indicatorDescription") or "").strip():
        spec["indicatorDescription"] = _indicator_description(name, spec)
    if not str(spec.get("calculationRule") or "").strip():
        spec["calculationRule"] = _chinese_calculation_rule(name, formula)
    spec["quality"] = _quality(
        spec, subject_kind=subject_kind, override_sources=override_sources,
        curated_applied=bool(curated_patch),
    )
    return spec


def _active_overrides(
    conn: sqlite3.Connection, subject_kind: str, subject_id: str,
) -> list[dict]:
    return [dict(row) for row in conn.execute("""
        SELECT override_id,override_key,patch_json,reason,source_ref,priority,
               changed_by
        FROM sys_metric_spec_override
        WHERE subject_kind=? AND subject_id=? AND status='active'
        ORDER BY priority,override_id
    """, (subject_kind, subject_id)).fetchall()]


def refresh_specifications(
    conn: sqlite3.Connection,
    *,
    formal_sources: Iterable[Mapping[str, object]],
    candidate_sources: Iterable[Mapping[str, object]],
    dependencies: Iterable[Mapping[str, object]],
) -> None:
    """Materialize effective specifications for all current catalog subjects."""
    formal = [dict(item) for item in formal_sources]
    candidates = [dict(item) for item in candidate_sources]
    dependency_rows = [dict(item) for item in dependencies]
    metric_names = {
        str(item["metric_id"]): str(item.get("name") or item["metric_id"])
        for item in formal
    }
    for source in formal:
        metric_id = str(source["metric_id"])
        spec = build_specification(
            source,
            subject_kind="formal",
            dependencies=dependency_rows,
            metric_names=metric_names,
            override_rows=_active_overrides(conn, "formal", metric_id),
        )
        conn.execute("""
            UPDATE sys_metric_version
            SET specification_json=?,specification_status=?,
                specification_source=?,
                specification_updated_at=datetime('now','localtime'),
                value_type=CASE
                    WHEN value_type IS NULL OR TRIM(value_type)=''
                    THEN ? ELSE value_type END
            WHERE metric_id=? AND effective_status='current'
        """, (
            json.dumps(spec, ensure_ascii=False, sort_keys=True),
            spec["quality"]["status"],
            "manual_override" if spec["quality"]["overrideApplied"]
            else (
                "curated_code_evidence"
                if spec["quality"]["curatedSpecificationApplied"]
                else "deterministic_normalization"
            ),
            VALUE_TYPE_BY_CALCULATION[spec["calculationType"]],
            metric_id,
        ))
    for source in candidates:
        metric_code = str(source["metric_id"])
        candidate_id_row = conn.execute("""
            SELECT candidate_id FROM sys_metric_candidate
            WHERE source_kind='markdown' AND source_key=?
        """, (metric_code,)).fetchone()
        if not candidate_id_row:
            continue
        candidate_id = candidate_id_row[0]
        candidate_source = {
            **source,
            "description": source.get("management_value", ""),
            "management_value": source.get("management_value", ""),
            "data_source": "",
            "grain": "",
            "update_cycle": "",
        }
        spec = build_specification(
            candidate_source,
            subject_kind="candidate",
            override_rows=_active_overrides(conn, "candidate", metric_code),
        )
        conn.execute("""
            UPDATE sys_metric_candidate
            SET specification_json=?,specification_status=?,
                specification_source=?,
                specification_updated_at=datetime('now','localtime')
            WHERE candidate_id=?
        """, (
            json.dumps(spec, ensure_ascii=False, sort_keys=True),
            spec["quality"]["status"],
            "manual_override" if spec["quality"]["overrideApplied"]
            else "deterministic_normalization",
            candidate_id,
        ))


def parse_specification(value: object, status: str | None = None) -> dict:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    if "quality" not in parsed:
        parsed["quality"] = {
            "status": status or "needs_review",
            "issues": [{"field": "specification", "code": "not_materialized"}],
            "normalizationVersion": NORMALIZATION_VERSION,
            "overrideApplied": False,
            "overrideSources": [],
        }
    return parsed
