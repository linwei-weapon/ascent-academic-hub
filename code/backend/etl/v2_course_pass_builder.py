"""M1 课程通过率三分层聚合：grade_attempt → agg_course_pass_stat（幂等可重跑）。

口径（与 docs/91-管理分析增强实施计划.md M1 一致）：
- 有效记录：grade_attempt 中 is_published=1 AND is_void=0 AND is_pass IS NOT NULL。
- 三分层（attempt_type）：
    first  = 首次修读链路，attempt_type='regular'；缓考 deferred、空值等其他取值
             一并归入首次修读链路（它们都不是补考/重修）。
    makeup = 补考，attempt_type='makeup'。
    retake = 重修，attempt_type='retake'。
- 通过率存放 0-1 小数（4 位精度），分母为 0 时存 NULL 不存 0，由接口层换算为百分数。
- source 恒为 'derived'（由真实成绩记录推导的聚合，不回写业务事实表）。

课程类别 course_group 推导优先级（用户已确认的合并口径）：
  ① 培养方案 curriculum_plan_course 模块名 + requirement_type（逐行判定后按
     公共必修 > 实践 > 专业必修 > 选修 的优先级取最高）：
       模块名含"通识"或"公共"且必修 → 公共必修
       模块名含"实践"               → 实践
       必修                         → 专业必修
       选修                         → 选修
  ② V1 dim_course.category 映射：
       通识必修课/体育课 → 公共必修；专业必修课 → 专业必修；
       专业选修课 → 选修；实践课 → 实践
  ③ 以上均无 → 其他
group_basis 记录命中来源：plan_module / v1_category / default。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .init_v2 import init_v2


PASS_STAT_VERSION = "pass-stat-v1"

COURSE_GROUPS = ("公共必修", "专业必修", "选修", "实践", "其他")

# 同一课程在不同专业方案中可能落入不同模块，按此优先级取最高类别。
_GROUP_PRIORITY = ("公共必修", "实践", "专业必修", "选修")

V1_CATEGORY_MAP = {
    "通识必修课": "公共必修",
    "体育课": "公共必修",
    "专业必修课": "专业必修",
    "专业选修课": "选修",
    "实践课": "实践",
}


def classify_plan_row(module, requirement_type) -> str | None:
    """按培养方案单行（模块名+修读要求）判定课程类别；无法判定返回 None。

    规则顺序即优先级（与 M1 数据契约一致）：
    含"通识/公共"且必修 → 公共必修；含"实践" → 实践；必修 → 专业必修；选修 → 选修。
    """
    text = module or ""
    req = (requirement_type or "").strip()
    if req == "必修" and ("通识" in text or "公共" in text):
        return "公共必修"
    if "实践" in text:
        return "实践"
    if req == "必修":
        return "专业必修"
    if req == "选修":
        return "选修"
    return None


def derive_course_group(plan_groups: list[str], v1_category) -> tuple[str, str]:
    """合并推导课程类别，返回 (course_group, group_basis)。"""
    for wanted in _GROUP_PRIORITY:
        if wanted in plan_groups:
            return wanted, "plan_module"
    mapped = V1_CATEGORY_MAP.get((v1_category or "").strip())
    if mapped:
        return mapped, "v1_category"
    return "其他", "default"


def _load_v1_categories(v1_db_path: Path | None) -> dict[str, str]:
    """读取 V1 dim_course.category；库或表缺失时返回空映射（落“其他”）。"""
    path = Path(v1_db_path or config.DB_PATH)
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dim_course'"
        ).fetchone()
        if not exists:
            return {}
        return {
            row[0]: row[1]
            for row in conn.execute("SELECT course_id, category FROM dim_course")
        }
    finally:
        conn.close()


def build_course_pass_stat(db_path: Path | None = None,
                           v1_db_path: Path | None = None) -> dict:
    """全量重建 agg_course_pass_stat。先删后插，可安全重复执行。"""
    conn = init_v2(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        v1_categories = _load_v1_categories(v1_db_path)

        plan_groups: dict[str, list[str]] = {}
        for course_id, module, req in conn.execute(
                "SELECT course_id, module, requirement_type FROM curriculum_plan_course"):
            group = classify_plan_row(module, req)
            if group:
                plan_groups.setdefault(course_id, [])
                if group not in plan_groups[course_id]:
                    plan_groups[course_id].append(group)

        # 首次修读链路 = regular 与任何非 makeup/retake 取值（含 deferred/空值）。
        first_case = "(g.attempt_type IS NULL OR g.attempt_type NOT IN ('makeup','retake'))"
        rows = conn.execute(f"""
            SELECT g.course_id, g.semester_id,
                   COALESCE(MAX(g.course_name), MAX(c.name), g.course_id) course_name,
                   SUM(CASE WHEN {first_case} THEN 1 ELSE 0 END) first_attempts,
                   SUM(CASE WHEN {first_case} AND g.is_pass=1 THEN 1 ELSE 0 END) first_pass,
                   SUM(CASE WHEN g.attempt_type='makeup' THEN 1 ELSE 0 END) makeup_attempts,
                   SUM(CASE WHEN g.attempt_type='makeup' AND g.is_pass=1 THEN 1 ELSE 0 END) makeup_pass,
                   SUM(CASE WHEN g.attempt_type='retake' THEN 1 ELSE 0 END) retake_attempts,
                   SUM(CASE WHEN g.attempt_type='retake' AND g.is_pass=1 THEN 1 ELSE 0 END) retake_pass
            FROM grade_attempt g LEFT JOIN dim_course c ON c.course_id=g.course_id
            WHERE g.is_published=1 AND g.is_void=0 AND g.is_pass IS NOT NULL
            GROUP BY g.course_id, g.semester_id
        """).fetchall()

        def _rate(passed: int, attempts: int):
            return round(passed / attempts, 4) if attempts else None

        conn.execute("DELETE FROM agg_course_pass_stat")
        group_counts = {group: 0 for group in COURSE_GROUPS}
        basis_counts = {"plan_module": 0, "v1_category": 0, "default": 0}
        seen_courses: set[str] = set()
        payload = []
        for (course_id, semester_id, course_name,
             fa, fp, ma, mp, ra, rp) in rows:
            group, basis = derive_course_group(
                plan_groups.get(course_id, []), v1_categories.get(course_id))
            payload.append((
                course_id, semester_id, course_name, group, basis,
                fa, fp, ma, mp, ra, rp,
                _rate(fp, fa), _rate(mp, ma), _rate(rp, ra),
                PASS_STAT_VERSION, now, "derived",
            ))
            if course_id not in seen_courses:
                seen_courses.add(course_id)
                group_counts[group] += 1
                basis_counts[basis] += 1
        conn.executemany(
            "INSERT INTO agg_course_pass_stat(course_id,semester_id,course_name,"
            "course_group,group_basis,first_attempts,first_pass,makeup_attempts,"
            "makeup_pass,retake_attempts,retake_pass,first_pass_rate,"
            "makeup_pass_rate,retake_pass_rate,rule_version,calculated_at,source)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
        conn.commit()
        report = {
            "rule_version": PASS_STAT_VERSION,
            "rows": len(payload),
            "courses": len(seen_courses),
            "semesters": len({row[1] for row in rows}),
            "group_counts": group_counts,
            "group_basis_counts": basis_counts,
            "plan_group_courses": len(plan_groups),
            "v1_category_courses": len(v1_categories),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def main() -> None:
    print(json.dumps(build_course_pass_stat(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
