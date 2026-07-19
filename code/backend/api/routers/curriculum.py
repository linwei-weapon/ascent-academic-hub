"""培养方案组：
GET /api/admin/curriculum/plan/{major}          培养方案详情
GET /api/admin/curriculum/objectives/{major}    课程目标达成度
GET /api/admin/curriculum/graduate-requirements/{major}  毕业要求达成度

真实数据来自 fact_plan_meta + fact_plan_course + fact_grade（脱敏教务培养方案，仅 2 个专业有真实方案）。
形状对齐前端预期。
"""
import json
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db as dbm
from ..deps import get_db, get_db_rw, get_current_user, student_data_scope
from ..envelope import ok, ApiError
from ..permission_context import has_action

router = APIRouter(prefix="/api/admin", tags=["curriculum"])


def _assert_major_access(conn: sqlite3.Connection, major_id: str,
                         user: dict) -> None:
    scope, params = student_data_scope(user, conn, "s")
    if not scope:
        return
    if not dbm.query_one(conn, f"""
        SELECT 1 FROM dim_student s
        WHERE s.major_id=? AND {scope} LIMIT 1
    """, tuple([major_id] + params)):
        raise ApiError("培养方案不存在或无权访问", code=404, status_code=404)

def _require_governance(user: dict, action: str):
    if not has_action(user, f"curriculum.governance.{action}"):
        raise ApiError("无权限执行培养方案规则治理操作", code=403, status_code=403)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CurriculumRuleChangeIn(BaseModel):
    ruleType: str
    payload: dict[str, Any]
    reason: str


class CurriculumRuleReviewIn(BaseModel):
    approved: bool
    comment: str = ""


def _change_conflict(conn, rule_type: str, payload: dict, exclude_change_id: int | None = None) -> str | None:
    if rule_type == "course_equivalence":
        exists = dbm.query_one(conn, """SELECT 1 FROM fact_course_equivalence WHERE major_id=? AND grade=?
            AND target_course_id=? AND substitute_course_id=? AND status='active'""",
            (payload.get("majorId"), str(payload.get("grade")), payload.get("targetCourseId"), payload.get("substituteCourseId")))
        if exists: return "相同课程替代关系已生效"
    elif rule_type == "credit_recognition":
        exists = dbm.query_one(conn, """SELECT 1 FROM fact_student_credit_recognition WHERE student_id=?
            AND COALESCE(target_course_id,'')=COALESCE(?,'') AND status='approved'""",
            (payload.get("studentId"), payload.get("targetCourseId")))
        if exists: return "该学生相同目标课程已有批准认定"
    else:
        exists = dbm.query_one(conn, "SELECT 1 FROM fact_plan_course_group WHERE group_id=? AND major_id=? AND grade=?",
                               (payload.get("groupId"), payload.get("majorId"), str(payload.get("grade"))))
        if exists: return "相同课程组编号已存在"
    for row in dbm.query(conn, """SELECT payload_json FROM curriculum_rule_change
            WHERE rule_type=? AND status IN ('draft','submitted','approved') AND change_id<>?""",
            (rule_type, exclude_change_id or -1)):
        if json.loads(row["payload_json"]) == payload:
            return "相同规则已有未完成变更单"
    return None

# 前端占位专业 id → 真实专业名（仅这两个专业有真实培养方案）。
_ALIAS = {"me_safety": "安全工程", "pe_ocean": "海洋油气工程"}
# 模块展示顺序 + 是否必修
_MODULE_ORDER = ["通识教育课", "专业大类平台课", "专业必修课", "专业选修课",
                 "实践教学环节（必修）", "通识选修", "第二课堂"]

# 12 条工程教育认证毕业要求
_GRAD_REQS_12 = [
    "工程知识",
    "问题分析",
    "设计/开发解决方案",
    "研究",
    "使用现代工具",
    "工程与社会",
    "环境和可持续发展",
    "职业规范",
    "个人和团队",
    "沟通",
    "项目管理",
    "终身学习",
]

# 培养方案模块 → 毕业要求支撑映射（模块对每条毕业要求的支撑权重 0-3）
_MODULE_TO_GRAD_REQ: dict[str, list[int]] = {
    "通识教育课":      [2, 1, 0, 0, 0, 2, 1, 2, 1, 3, 0, 2],
    "专业大类平台课":   [3, 3, 2, 1, 1, 0, 0, 1, 0, 0, 0, 0],
    "专业必修课":      [3, 3, 3, 3, 2, 0, 0, 0, 0, 0, 1, 0],
    "专业选修课":      [1, 2, 2, 2, 0, 1, 1, 0, 0, 0, 0, 1],
    "实践教学环节（必修）": [1, 2, 3, 2, 2, 0, 0, 0, 2, 1, 1, 0],
    "通识选修":        [1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1],
    "第二课堂":        [0, 0, 0, 0, 0, 1, 0, 1, 3, 2, 2, 1],
}


def _resolve_major(conn, major: str) -> str | None:
    if dbm.query_one(conn, "SELECT 1 FROM fact_plan_meta WHERE major_id=?", (major,)):
        return major
    if major in _ALIAS:
        row = dbm.query_one(conn, """
            SELECT m.major_id FROM fact_plan_meta p
            JOIN dim_major m ON p.major_id=m.major_id WHERE m.name=?""", (_ALIAS[major],))
        if row:
            return row["major_id"]
    return None


def _plan_meta(conn, major_id: str, grade: str | None = None) -> dict | None:
    if grade is not None:
        return dbm.query_one(conn, """SELECT * FROM fact_plan_meta
            WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)
            ORDER BY grade DESC LIMIT 1""", (major_id, grade))
    return dbm.query_one(conn, """SELECT * FROM fact_plan_meta
        WHERE major_id=? ORDER BY grade DESC LIMIT 1""", (major_id,))


def _grad_reqs(raw: str) -> list[str]:
    try:
        return [item.get("desc") or item.get("name", "") for item in json.loads(raw)]
    except (ValueError, TypeError):
        return []


def _module_rules(conn, major_id: str, grade: str) -> dict[str, dict]:
    rows = dbm.query(conn, """SELECT module,course_nature,min_credits,sort_order,source
        FROM fact_plan_module_rule WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)""",
        (major_id, grade))
    return {r["module"]: r for r in rows}


def _support_matrix(conn, major_id: str, grade: str) -> tuple[list[str], dict[str, list[int]]]:
    rows = dbm.query(conn, """SELECT module,requirement_no,requirement_name,weight
        FROM fact_grad_req_support WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)
        ORDER BY module,requirement_no""", (major_id, grade))
    names = [""] * 12
    matrix: dict[str, list[int]] = {}
    for row in rows:
        idx = int(row["requirement_no"]) - 1
        if 0 <= idx < 12:
            names[idx] = row["requirement_name"]
            matrix.setdefault(row["module"], [0] * 12)[idx] = int(row["weight"] or 0)
    return ([name or _GRAD_REQS_12[i] for i, name in enumerate(names)], matrix)


@router.get("/curriculum/plan/{major}")
def curriculum_plan(major: str, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(get_current_user)):
    mid = _resolve_major(conn, major)
    if not mid:
        raise ApiError("暂无培养方案数据", code=404, status_code=404)
    _assert_major_access(conn, mid, user)
    meta = _plan_meta(conn, mid)
    college = dbm.query_one(conn, """
        SELECT c.name FROM dim_major m LEFT JOIN dim_college c ON m.college_id=c.college_id
        WHERE m.major_id=?""", (mid,))

    # 按模块归组课程
    by_mod: dict[str, list] = {}
    for r in dbm.query(conn, """
        SELECT course_id, course_name, module, credits, term, is_core
        FROM fact_plan_course WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)
        ORDER BY term, course_id""", (mid, meta["grade"])):
        by_mod.setdefault(r["module"], []).append(r)

    ordered = [m for m in _MODULE_ORDER if m in by_mod] + \
              [m for m in by_mod if m not in _MODULE_ORDER]
    rules = _module_rules(conn, mid, meta["grade"])
    modules = []
    for mod in ordered:
        rows = by_mod[mod]
        required = rules.get(mod, {}).get("course_nature") == "required"
        credits = round(sum(r["credits"] or 0 for r in rows), 1)
        courses = [{
            "code": r["course_id"],
            "name": (r["course_name"] or r["course_id"]) + (" ★" if r["is_core"] else ""),
            "credits": r["credits"], "hours": round((r["credits"] or 0) * 16),
            "term": r["term"] or "", "dept": college["name"] if college else "—",
        } for r in rows]
        m = {"name": mod, "credits": credits, "required": required,
             "subModules": [{"name": mod, "courses": courses}]}
        if not required:
            m["electiveRequired"] = rules.get(mod, {}).get("min_credits", 0)
        modules.append(m)

    return ok({
        "name": meta["major_name"], "grade": f"{meta['grade']}级",
        "college": college["name"] if college else "—", "level": "本科",
        "totalCredits": meta["total_credits"], "requiredCredits": meta["required_credits"],
        "electiveMinCredits": meta["elective_credits"], "practiceCredits": meta["practice_credits"],
        "modules": modules,
        "graduationRequirements": _grad_reqs(meta["grad_reqs_json"]),
        "degreeRequirement": (meta["degree_req"] or "").replace("学位要求\t", "").strip(),
        "planVersion": f"{mid}-{meta['grade']}",
        "applicableGrade": str(meta["grade"]),
        "dataSource": "真实培养方案",
        "coverageNote": "仅适用于该专业与年级完全匹配的学生",
    })


@router.get("/curriculum/objectives/{major}")
def course_objectives(major: str, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(get_current_user)):
    """课程目标达成度：以培养方案模块作为课程目标维度，计算该模块下所有课程的平均分和通过率。
    达成标准：平均达成度 ≥ 65% 为达标。"""
    mid = _resolve_major(conn, major)
    if not mid:
        raise ApiError("暂无培养方案数据", code=404, status_code=404)
    _assert_major_access(conn, mid, user)
    student_scope, student_scope_params = student_data_scope(user, conn, "s")

    # 获取该专业培养方案中所有课程及其所属模块
    meta = _plan_meta(conn, mid)
    plan_courses = dbm.query(conn, """
        SELECT course_id, module, credits FROM fact_plan_course
        WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)""", (mid, meta["grade"]))
    if not plan_courses:
        return ok({"objectives": [], "overallRate": 0})

    # 按模块归组课程ID
    mod_courses: dict[str, list[str]] = {}
    mod_credits: dict[str, float] = {}
    for r in plan_courses:
        mod_courses.setdefault(r["module"], []).append(r["course_id"])
        mod_credits[r["module"]] = mod_credits.get(r["module"], 0) + (r["credits"] or 0)

    # 计算每个模块（课程目标）的达成度
    objectives = []
    total_weight = 0
    total_weighted_rate = 0
    ordered = [m for m in _MODULE_ORDER if m in mod_courses] + \
              [m for m in mod_courses if m not in _MODULE_ORDER]

    for mod in ordered:
        course_ids = mod_courses[mod]
        placeholders = ",".join(["?"] * len(course_ids))
        # 该模块所有课程的修读学生成绩
        scope_and = f" AND {student_scope}" if student_scope else ""
        stats = dbm.query_one(conn, f"""
            SELECT AVG(g.score) as avg_score,
                   COUNT(*) as total,
                   SUM(CASE WHEN g.is_pass=1 THEN 1 ELSE 0 END) as pass_count
            FROM fact_grade g JOIN dim_student s ON s.student_id=g.student_id
            WHERE g.course_id IN ({placeholders}) AND s.major_id=?
              AND g.score IS NOT NULL{scope_and}""",
            tuple(course_ids + [mid] + student_scope_params))

        avg_score = round(stats["avg_score"] or 0, 1)
        total = stats["total"] or 0
        pass_rate = round(stats["pass_count"] / total * 100, 1) if total > 0 else 0
        # 达成度 = 平均分 / 100 * 100%（即以百分制平均分作为达成度）
        achievement = round(avg_score, 1)

        weight = mod_credits.get(mod, 0)
        total_weight += weight
        total_weighted_rate += achievement * weight

        objectives.append({
            "objective": mod,
            "courseCount": len(course_ids),
            "credits": round(mod_credits.get(mod, 0), 1),
            "avgScore": avg_score,
            "passRate": pass_rate,
            "achievement": achievement,
            "standard": 65,
            "status": "达标" if achievement >= 65 else "未达标",
        })

    overall = round(total_weighted_rate / total_weight, 1) if total_weight > 0 else 0
    return ok({
        "major": major,
        "objectives": objectives,
        "overallAchievement": overall,
        "overallStatus": "达标" if overall >= 65 else "未达标",
    })


@router.get("/curriculum/graduate-requirements/{major}")
def graduate_requirements(major: str, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(get_current_user)):
    """毕业要求达成度：12 条通用毕业要求 × 课程模块支撑矩阵 + 课程目标达成度加权。"""
    mid = _resolve_major(conn, major)
    if not mid:
        raise ApiError("暂无培养方案数据", code=404, status_code=404)
    _assert_major_access(conn, mid, user)
    student_scope, student_scope_params = student_data_scope(user, conn, "s")

    # 先获取课程目标达成度（复用上面的计算逻辑）
    meta = _plan_meta(conn, mid)
    plan_courses = dbm.query(conn, """
        SELECT course_id, module, credits FROM fact_plan_course
        WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)""", (mid, meta["grade"]))
    if not plan_courses:
        return ok({"requirements": [], "overallRate": 0})

    mod_courses: dict[str, list[str]] = {}
    mod_credits: dict[str, float] = {}
    mod_achievement: dict[str, float] = {}
    for r in plan_courses:
        mod_courses.setdefault(r["module"], []).append(r["course_id"])
        mod_credits[r["module"]] = mod_credits.get(r["module"], 0) + (r["credits"] or 0)

    for mod, course_ids in mod_courses.items():
        placeholders = ",".join(["?"] * len(course_ids))
        scope_and = f" AND {student_scope}" if student_scope else ""
        stats = dbm.query_one(conn, f"""
            SELECT AVG(g.score) as avg_score
            FROM fact_grade g JOIN dim_student s ON s.student_id=g.student_id
            WHERE g.course_id IN ({placeholders}) AND s.major_id=?
              AND g.score IS NOT NULL{scope_and}""",
            tuple(course_ids + [mid] + student_scope_params))
        mod_achievement[mod] = round(stats["avg_score"] or 0, 1)

    req_names, support_matrix = _support_matrix(conn, mid, meta["grade"])
    # 计算每条毕业要求的加权达成度
    requirements = []
    total_weighted = 0
    total_weight = 0
    for idx, req_name in enumerate(req_names):
        weighted_sum = 0.0
        weight_sum = 0.0
        supporting_modules: list[str] = []
        for mod in mod_achievement:
            w = support_matrix.get(mod, [0] * 12)[idx]
            if w > 0:
                weighted_sum += mod_achievement[mod] * w * mod_credits.get(mod, 0)
                weight_sum += w * mod_credits.get(mod, 0)
                supporting_modules.append(mod)

        achievement = round(weighted_sum / weight_sum, 1) if weight_sum > 0 else 0
        total_weighted += achievement * weight_sum
        total_weight += weight_sum

        requirements.append({
            "index": idx + 1,
            "name": req_name,
            "achievement": achievement,
            "standard": 65,
            "status": "达标" if achievement >= 65 else "未达标",
            "supportModules": supporting_modules,
        })

    overall = round(total_weighted / total_weight, 1) if total_weight > 0 else 0
    return ok({
        "major": major,
        "planVersion": f"{mid}-{meta['grade']}",
        "requirementNames": req_names,
        "supportMatrix": support_matrix,
        "planModules": sorted(support_matrix, key=lambda m: _MODULE_ORDER.index(m) if m in _MODULE_ORDER else 99),
        "matrixSource": "培养方案支撑矩阵数据表",
        "requirements": requirements,
        "overallAchievement": overall,
        "overallStatus": "达标" if overall >= 65 else "未达标",
    })

# -- V1.1：学业进度监控 --
@router.get("/curriculum/progress/{major}")
def curriculum_progress(major: str, student_id: str = None, compliance_status: str = None,
                        risk_level: str = None, keyword: str = None,
                        conn: sqlite3.Connection = Depends(get_db),
                        user: dict = Depends(get_current_user)):
    """对照培养方案检查每生选课合规和学分缺口。"""
    mid = _resolve_major(conn, major)
    if not mid:
        return ok({"planCourses": [], "progress": [], "message": "暂无培养方案数据"})
    _assert_major_access(conn, mid, user)
    meta = _plan_meta(conn, mid)
    plan_courses = dbm.query(conn, """
        SELECT course_id, course_name, module, credits, term, is_core
        FROM fact_plan_course WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)
        ORDER BY term, course_id
    """, (mid, meta["grade"]))
    stu_cond = " AND s.student_id = ?" if student_id else ""
    student_scope, student_scope_params = student_data_scope(user, conn, "s")
    scope_and = f" AND {student_scope}" if student_scope else ""
    students = dbm.query(conn, f"""
        SELECT s.student_id,s.name,s.grade FROM dim_student s
        WHERE s.major_id=? AND CAST(s.grade AS TEXT)=CAST(? AS TEXT)
          {stu_cond}{scope_and}
        ORDER BY s.grade DESC,s.student_id
    """, tuple([mid, meta["grade"]] + ([student_id] if student_id else [])
               + student_scope_params))
    progress = []
    rules = _module_rules(conn, mid, meta["grade"])
    required_plan = [pc for pc in plan_courses if rules.get(pc["module"], {}).get("course_nature") == "required"]
    elective_plan = [pc for pc in plan_courses if rules.get(pc["module"], {}).get("course_nature") == "elective"]
    elective_min = round(sum(float(r.get("min_credits") or 0) for r in rules.values()
                             if r.get("course_nature") == "elective"), 1)
    equivalences = dbm.query(conn, """SELECT target_course_id,substitute_course_id,approval_ref
        FROM fact_course_equivalence WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)
        AND status='active'""", (mid, meta["grade"]))
    substitutes: dict[str, list[dict]] = {}
    for eq in equivalences:
        substitutes.setdefault(eq["target_course_id"], []).append(eq)
    course_groups = dbm.query(conn, """SELECT group_id,group_name,module,min_courses,min_credits,course_ids_json
        FROM fact_plan_course_group WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT)""",
        (mid, meta["grade"]))
    for s in students:
        sid = s["student_id"]
        taken = {r["course_id"]: r for r in dbm.query(conn, """
            SELECT course_id, MAX(is_pass) is_pass, COUNT(*) attempts, MAX(credits) credits
            FROM fact_grade
            WHERE student_id=? GROUP BY course_id
        """, (sid,))}
        recognitions = dbm.query(conn, """SELECT recognition_type,target_course_id,module,credits,approval_ref
            FROM fact_student_credit_recognition WHERE student_id=? AND status='approved'""", (sid,))
        recognized_targets = {r["target_course_id"] for r in recognitions if r["target_course_id"]}
        applied_exceptions = []
        gap_courses, required_gap, core_gap = [], 0.0, 0.0
        for pc in required_plan:
            t = taken.get(pc["course_id"])
            substitute = next((eq for eq in substitutes.get(pc["course_id"], [])
                               if taken.get(eq["substitute_course_id"], {}).get("is_pass") == 1), None)
            if t and t["is_pass"] == 1: continue
            if substitute:
                applied_exceptions.append({"type": "course_equivalence", "targetCourseId": pc["course_id"],
                    "substituteCourseId": substitute["substitute_course_id"], "credits": pc["credits"] or 0,
                    "approvalRef": substitute["approval_ref"]})
                continue
            if pc["course_id"] in recognized_targets:
                rec = next(r for r in recognitions if r["target_course_id"] == pc["course_id"])
                applied_exceptions.append({"type": rec["recognition_type"], "targetCourseId": pc["course_id"],
                    "credits": rec["credits"], "approvalRef": rec["approval_ref"]})
                continue
            g = pc["credits"] or 0; required_gap += g
            if pc["is_core"]: core_gap += g
            gap_courses.append({"courseId": pc["course_id"],
                "courseName": pc["course_name"] or pc["course_id"],
                "module": pc["module"], "credits": g, "term": pc["term"],
                "isCore": bool(pc["is_core"]),
                "status": "未选" if not t else "未通过"})
        plan_ids = {pc["course_id"] for pc in plan_courses}
        passed_rows = dbm.query(conn, """SELECT course_id,MAX(credits) credits
            FROM fact_grade WHERE student_id=? AND is_pass=1 GROUP BY course_id""", (sid,))
        plan_earned = round(sum((r["credits"] or 0) for r in passed_rows
                                if r["course_id"] in plan_ids), 1)
        recognized_course_credits = sum(float(r["credits"] or 0) for r in recognitions
                                        if r["target_course_id"] and not
                                        (taken.get(r["target_course_id"], {}).get("is_pass") == 1))
        recognized_module_credits = sum(float(r["credits"] or 0) for r in recognitions if not r["target_course_id"])
        substitution_credits = sum(float(r["credits"] or 0) for r in applied_exceptions
                                   if r["type"] == "course_equivalence")
        plan_earned = round(plan_earned + substitution_credits + recognized_course_credits + recognized_module_credits, 1)
        outside_earned = round(sum((r["credits"] or 0) for r in passed_rows
                                   if r["course_id"] not in plan_ids), 1)
        total_req = meta["total_credits"] or 0
        elective_ids = {pc["course_id"] for pc in elective_plan}
        elective_earned = round(sum((r["credits"] or 0) for r in passed_rows
                                     if r["course_id"] in elective_ids) + sum(float(r["credits"] or 0)
                                     for r in recognitions if r["module"] and
                                     rules.get(r["module"], {}).get("course_nature") == "elective"), 1)
        elective_gap = round(max(0, elective_min - elective_earned), 1)
        group_checks = []
        for group in course_groups:
            try:
                group_ids = set(json.loads(group["course_ids_json"] or "[]"))
            except (TypeError, ValueError):
                group_ids = set()
            passed_group = [r for r in passed_rows if r["course_id"] in group_ids]
            group_count = len(passed_group)
            group_credits = round(sum(float(r["credits"] or 0) for r in passed_group), 1)
            group_ok = group_count >= int(group["min_courses"] or 0) and group_credits >= float(group["min_credits"] or 0)
            group_checks.append({"groupId": group["group_id"], "groupName": group["group_name"],
                "module": group["module"], "passedCourses": group_count, "earnedCredits": group_credits,
                "minCourses": int(group["min_courses"] or 0), "minCredits": float(group["min_credits"] or 0),
                "status": "满足" if group_ok else "未满足"})
        total_gap = round(required_gap + elective_gap, 1)
        repeated = [{"courseId": cid, "attempts": int(t["attempts"])}
                    for cid, t in taken.items() if int(t["attempts"] or 0) > 1]
        outside_courses = [{"courseId": r["course_id"], "credits": r["credits"] or 0}
                           for r in passed_rows if r["course_id"] not in plan_ids]
        issues = []
        if required_gap:
            issues.append({"type": "required_missing", "level": "high",
                           "message": f"必修课程缺口 {required_gap:.1f} 学分"})
        if core_gap:
            issues.append({"type": "core_missing", "level": "high",
                           "message": f"核心课程缺口 {core_gap:.1f} 学分"})
        if elective_gap:
            issues.append({"type": "elective_shortage", "level": "medium",
                           "message": f"选修最低学分尚缺 {elective_gap:.1f} 学分"})
        if repeated:
            issues.append({"type": "repeated_attempt", "level": "medium",
                           "message": f"存在 {len(repeated)} 门重复修读课程"})
        if outside_courses:
            issues.append({"type": "outside_plan", "level": "info",
                           "message": f"方案外已通过课程 {len(outside_courses)} 门，共 {outside_earned:.1f} 学分"})
        if applied_exceptions or recognitions:
            issues.append({"type": "approved_exception", "level": "info",
                           "message": f"已应用 {len(applied_exceptions) + len([r for r in recognitions if not r['target_course_id']])} 条批准的例外认定"})
        unsatisfied_groups = [g for g in group_checks if g["status"] == "未满足"]
        if unsatisfied_groups:
            issues.append({"type": "course_group_shortage", "level": "medium",
                           "message": f"有 {len(unsatisfied_groups)} 个课程组未达到最低修读要求"})
        compliance_status_value = "不合规" if required_gap or core_gap or elective_gap or unsatisfied_groups else "合规"
        risk_level_value = "高" if (total_req and plan_earned/total_req < 0.6) else (
            "中" if (total_req and plan_earned/total_req < 0.8) else "低")
        progress.append({"studentId": sid, "name": s["name"],
            "grade": s["grade"], "earnedCredits": plan_earned,
            "planEarnedCredits": plan_earned, "outsidePlanCredits": outside_earned,
            "requiredCredits": total_req, "gapCredits": total_gap,
            "requiredGapCredits": round(required_gap, 1),
            "coreGapCredits": round(core_gap, 1),
            "electiveEarnedCredits": elective_earned,
            "electiveRequiredCredits": elective_min,
            "electiveGapCredits": elective_gap,
            "completionRate": round(plan_earned/total_req*100, 1) if total_req else 0,
            "gapCourses": gap_courses, "repeatedCourses": repeated,
            "outsidePlanCourses": outside_courses, "complianceIssues": issues,
            "appliedExceptions": applied_exceptions,
            "courseGroupChecks": group_checks,
            "recognizedCredits": round(recognized_course_credits + recognized_module_credits, 1),
            "complianceStatus": compliance_status_value,
            "requirementBasis": "必修/选修及最低学分来自方案模块规则表；核心课来自方案 is_core 字段",
            "riskLevel": risk_level_value})
    if compliance_status:
        progress = [row for row in progress if row["complianceStatus"] == compliance_status]
    if risk_level:
        progress = [row for row in progress if row["riskLevel"] == risk_level]
    if keyword:
        needle = keyword.strip().lower()
        progress = [row for row in progress if needle in row["studentId"].lower() or needle in (row["name"] or "").lower()]
    return ok({"planName": meta["major_name"], "planVersion": f"{mid}-{meta['grade']}",
        "exceptionRuleSummary": {"courseEquivalences": len(equivalences),
            "courseGroups": len(course_groups), "studentRecognitionsAreApprovalOnly": True},
        "applicableGrade": str(meta["grade"]), "planCourses": [
        {"courseId": pc["course_id"], "courseName": pc["course_name"] or pc["course_id"],
         "module": pc["module"], "credits": pc["credits"], "term": pc["term"]}
        for pc in plan_courses], "progress": progress})


# -- 培养方案例外规则治理：草稿 -> 提交 -> 审核 -> 激活 --
@router.get("/curriculum/rule-options")
def curriculum_rule_options(user: dict = Depends(get_current_user),
                            conn: sqlite3.Connection = Depends(get_db)):
    _require_governance(user, "audit")
    plans = dbm.query(conn, """SELECT p.major_id majorId,p.grade,m.name majorName
        FROM fact_plan_meta p LEFT JOIN dim_major m ON p.major_id=m.major_id ORDER BY m.name,p.grade DESC""")
    courses = dbm.query(conn, """SELECT major_id majorId,grade,course_id courseId,
        COALESCE(course_name,course_id) courseName,module FROM fact_plan_course ORDER BY course_name""")
    students = dbm.query(conn, """SELECT s.student_id studentId,s.name,s.major_id majorId,s.grade
        FROM dim_student s WHERE EXISTS (SELECT 1 FROM fact_plan_meta p WHERE p.major_id=s.major_id
        AND CAST(p.grade AS TEXT)=CAST(s.grade AS TEXT)) ORDER BY s.student_id LIMIT 1000""")
    modules = dbm.query(conn, """SELECT major_id majorId,grade,module FROM fact_plan_module_rule
        ORDER BY sort_order,module""")
    return ok({"plans": plans, "courses": courses, "students": students, "modules": modules})


@router.get("/curriculum/rule-changes")
def curriculum_rule_changes(status: str = None, user: dict = Depends(get_current_user),
                            conn: sqlite3.Connection = Depends(get_db)):
    _require_governance(user, "audit")
    where, params = (" WHERE status=?", [status]) if status else ("", [])
    rows = dbm.query(conn, "SELECT * FROM curriculum_rule_change" + where + " ORDER BY change_id DESC", params)
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return ok({
        "list": rows,
        "permissions": {
            action: has_action(user, f"curriculum.governance.{action}")
            for action in ("edit", "review", "activate", "audit")
        },
    })


@router.get("/curriculum/rule-changes/{change_id}")
def curriculum_rule_change_detail(change_id: int, user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_db)):
    _require_governance(user, "audit")
    row = dbm.query_one(conn, "SELECT * FROM curriculum_rule_change WHERE change_id=?", (change_id,))
    if not row:
        raise ApiError("规则变更单不存在", code=404, status_code=404)
    row["payload"] = json.loads(row.pop("payload_json"))
    row["auditTrail"] = dbm.query(conn, "SELECT action,operator,operated_at,detail FROM curriculum_rule_audit WHERE change_id=? ORDER BY audit_id", (change_id,))
    return ok(row)


@router.post("/curriculum/rule-changes")
def create_curriculum_rule_change(body: CurriculumRuleChangeIn, user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_governance(user, "edit")
    if body.ruleType not in {"course_equivalence", "credit_recognition", "course_group"}:
        raise ApiError("不支持的规则类型", code=400, status_code=400)
    if not body.reason.strip():
        raise ApiError("请填写变更原因", code=400, status_code=400)
    required = {
        "course_equivalence": {"majorId", "grade", "targetCourseId", "substituteCourseId", "approvalRef"},
        "credit_recognition": {"studentId", "recognitionType", "credits", "approvalRef"},
        "course_group": {"groupId", "majorId", "grade", "groupName", "module", "minCourses", "minCredits", "courseIds"},
    }[body.ruleType]
    missing = sorted(k for k in required if body.payload.get(k) in (None, "", []))
    if missing:
        raise ApiError("缺少必填字段：" + ",".join(missing), code=400, status_code=400)
    conflict = _change_conflict(conn, body.ruleType, body.payload)
    if conflict:
        raise ApiError(conflict, code=409, status_code=409)
    cur = dbm.execute(conn, """INSERT INTO curriculum_rule_change
        (rule_type,payload_json,reason,status,created_by,created_at) VALUES (?,?,?,'draft',?,?)""",
        (body.ruleType, json.dumps(body.payload, ensure_ascii=False), body.reason.strip(), user["username"], _now()))
    change_id = cur.lastrowid
    dbm.execute(conn, "INSERT INTO curriculum_rule_audit(change_id,action,operator,operated_at,detail) VALUES (?,?,?,?,?)",
                (change_id, "created", user["username"], _now(), body.reason.strip()))
    return ok({"changeId": change_id, "status": "draft"}, msg="规则变更草稿已创建")


@router.get("/curriculum/rule-changes/{change_id}/preview")
def preview_curriculum_rule_change(change_id: int, user: dict = Depends(get_current_user),
                                   conn: sqlite3.Connection = Depends(get_db)):
    _require_governance(user, "audit")
    row = dbm.query_one(conn, "SELECT * FROM curriculum_rule_change WHERE change_id=?", (change_id,))
    if not row:
        raise ApiError("规则变更单不存在", code=404, status_code=404)
    p = json.loads(row["payload_json"])
    impacted, credit_delta, detail = 0, 0.0, ""
    if row["rule_type"] == "course_equivalence":
        impacted = dbm.scalar(conn, """SELECT COUNT(DISTINCT s.student_id) FROM dim_student s
            WHERE s.major_id=? AND CAST(s.grade AS TEXT)=CAST(? AS TEXT)
            AND EXISTS (SELECT 1 FROM fact_grade g WHERE g.student_id=s.student_id AND g.course_id=? AND g.is_pass=1)
            AND NOT EXISTS (SELECT 1 FROM fact_grade g WHERE g.student_id=s.student_id AND g.course_id=? AND g.is_pass=1)""",
            (p["majorId"], p["grade"], p["substituteCourseId"], p["targetCourseId"])) or 0
        target = dbm.query_one(conn, """SELECT credits FROM fact_plan_course WHERE major_id=? AND grade=?
            AND course_id=? LIMIT 1""", (p["majorId"], str(p["grade"]), p["targetCourseId"]))
        credit_delta = round(impacted * float((target or {}).get("credits") or 0), 1)
        detail = "已通过替代课但尚未通过目标课的方案适用学生"
    elif row["rule_type"] == "credit_recognition":
        student = dbm.query_one(conn, "SELECT 1 FROM dim_student WHERE student_id=?", (p["studentId"],))
        impacted = 1 if student else 0
        credit_delta = float(p["credits"]) if impacted else 0
        detail = "指定学生的预计新增认定学分"
    else:
        impacted = dbm.scalar(conn, """SELECT COUNT(*) FROM dim_student WHERE major_id=?
            AND CAST(grade AS TEXT)=CAST(? AS TEXT)""", (p["majorId"], p["grade"])) or 0
        detail = "该培养方案版本全部适用学生将新增课程组合规检查"
    return ok({"changeId": change_id, "ruleType": row["rule_type"], "status": row["status"],
               "impactedStudents": impacted, "aggregateCreditDelta": credit_delta,
               "detail": detail, "isEstimate": True,
               "conflict": _change_conflict(conn, row["rule_type"], p, change_id)})


@router.post("/curriculum/rule-changes/{change_id}/submit")
def submit_curriculum_rule_change(change_id: int, user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_governance(user, "edit")
    row = dbm.query_one(conn, "SELECT * FROM curriculum_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "draft" or row["created_by"] != user["username"]:
        raise ApiError("仅创建人可提交草稿", code=400, status_code=400)
    dbm.execute(conn, "UPDATE curriculum_rule_change SET status='submitted' WHERE change_id=?", (change_id,))
    dbm.execute(conn, "INSERT INTO curriculum_rule_audit(change_id,action,operator,operated_at) VALUES (?,?,?,?)",
                (change_id, "submitted", user["username"], _now()))
    return ok({"changeId": change_id, "status": "submitted"}, msg="已提交质量审核")


@router.post("/curriculum/rule-changes/{change_id}/review")
def review_curriculum_rule_change(change_id: int, body: CurriculumRuleReviewIn,
                                  user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_governance(user, "review")
    row = dbm.query_one(conn, "SELECT * FROM curriculum_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "submitted":
        raise ApiError("仅已提交变更单可以审核", code=400, status_code=400)
    status = "approved" if body.approved else "rejected"
    dbm.execute(conn, "UPDATE curriculum_rule_change SET status=?,reviewed_by=?,reviewed_at=?,review_comment=? WHERE change_id=?",
                (status, user["username"], _now(), body.comment, change_id))
    dbm.execute(conn, "INSERT INTO curriculum_rule_audit(change_id,action,operator,operated_at,detail) VALUES (?,?,?,?,?)",
                (change_id, status, user["username"], _now(), body.comment))
    return ok({"changeId": change_id, "status": status}, msg="审核结果已记录")


@router.post("/curriculum/rule-changes/{change_id}/activate")
def activate_curriculum_rule_change(change_id: int, user: dict = Depends(get_current_user),
                                    conn: sqlite3.Connection = Depends(get_db_rw)):
    _require_governance(user, "activate")
    row = dbm.query_one(conn, "SELECT * FROM curriculum_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "approved":
        raise ApiError("仅审核通过的变更单可以激活", code=400, status_code=400)
    p = json.loads(row["payload_json"])
    if row["rule_type"] == "course_equivalence":
        dbm.execute(conn, """INSERT INTO fact_course_equivalence
            (major_id,grade,target_course_id,substitute_course_id,status,approval_ref,source)
            VALUES (?,?,?,?,'active',?,'governed')""",
            (p["majorId"], p["grade"], p["targetCourseId"], p["substituteCourseId"], p["approvalRef"]))
    elif row["rule_type"] == "credit_recognition":
        dbm.execute(conn, """INSERT INTO fact_student_credit_recognition
            (student_id,recognition_type,target_course_id,module,credits,status,approval_ref,approved_at,source)
            VALUES (?,?,?,?,?,'approved',?,?, 'governed')""",
            (p["studentId"], p["recognitionType"], p.get("targetCourseId"), p.get("module"),
             float(p["credits"]), p["approvalRef"], _now()))
    else:
        dbm.execute(conn, """INSERT OR REPLACE INTO fact_plan_course_group
            (group_id,major_id,grade,group_name,module,min_courses,min_credits,course_ids_json,source)
            VALUES (?,?,?,?,?,?,?,?, 'governed')""",
            (p["groupId"], p["majorId"], p["grade"], p["groupName"], p["module"],
             int(p["minCourses"]), float(p["minCredits"]), json.dumps(p["courseIds"], ensure_ascii=False)))
    now = _now()
    dbm.execute(conn, "UPDATE curriculum_rule_change SET status='activated',activated_by=?,activated_at=? WHERE change_id=?",
                (user["username"], now, change_id))
    dbm.execute(conn, "INSERT INTO curriculum_rule_audit(change_id,action,operator,operated_at) VALUES (?,?,?,?)",
                (change_id, "activated", user["username"], now))
    return ok({"changeId": change_id, "status": "activated"}, msg="规则已激活并开始参与合规计算")
