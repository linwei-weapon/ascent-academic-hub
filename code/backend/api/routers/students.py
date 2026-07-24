"""学生学业分析组：GPA 分层画像 / 年级 GPA / 学分完成 / 挂科集中课程。
全部算自真实成绩 fact_grade + 预警 fact_alert + 合成毕业 fact_graduation。
支持维度过滤：semester(学期) / grade(年级) / college(学院码)，无值=全量。
"""
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..academic_metrics import (
    earned_credit_map,
    per_student_weighted_gpa,
    term_grade_and_failed_students,
    weighted_gpa_expression,
)
from ..deps import get_db, get_current_user, student_data_scope, _staff_student_ids
from ..envelope import ApiError, ok
from ..settings import CURRENT_SEMESTER
from ..student_growth import build_growth_snapshot, filter_growth_rows

router = APIRouter(prefix="/api/admin/students", tags=["students"])
_ANALYSIS_CACHE: dict[tuple, tuple[float, dict]] = {}
_ANALYSIS_CACHE_TTL = 900
_GROWTH_CACHE: dict[tuple, tuple[float, dict]] = {}
_GROWTH_CACHE_TTL = 900


def _growth_snapshot(
    conn: sqlite3.Connection,
    user: dict,
    from_semester: Optional[str],
    to_semester: Optional[str],
    college: Optional[str],
    major: Optional[str],
    grade: Optional[str],
    class_id: Optional[str],
) -> dict:
    scope_fingerprint = (
        (user.get("permission_context") or {}).get("scopeFingerprint")
        or f"legacy:{user.get('username')}:{user.get('role_id')}"
    )
    key = (
        scope_fingerprint, from_semester, to_semester,
        college, major, grade, class_id,
    )
    cached = _GROWTH_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _GROWTH_CACHE_TTL:
        return cached[1]
    snapshot = build_growth_snapshot(
        conn, user, from_semester=from_semester, to_semester=to_semester,
        college=college, major=major, grade=grade, class_id=class_id,
    )
    _GROWTH_CACHE[key] = (time.monotonic(), snapshot)
    return snapshot


@router.get("/growth/overview")
def growth_overview(
    from_semester: Optional[str] = None,
    to_semester: Optional[str] = None,
    college: Optional[str] = None,
    major: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """学生成长管理首屏：指标、关注分组和组织比较。"""
    snapshot = _growth_snapshot(
        conn, user, from_semester, to_semester,
        college, major, grade, class_id,
    )
    return ok({
        key: value for key, value in snapshot.items()
        if key not in ("rows", "organizations", "organizationLabel")
    })


@router.get("/growth/organizations")
def growth_organizations(
    from_semester: Optional[str] = None,
    to_semester: Optional[str] = None,
    college: Optional[str] = None,
    major: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """按当前授权范围返回下一级组织比较，不包含学生明细。"""
    snapshot = _growth_snapshot(
        conn, user, from_semester, to_semester,
        college, major, grade, class_id,
    )
    return ok({
        "period": snapshot["period"],
        "rule": snapshot["rule"],
        "organizationLabel": snapshot["organizationLabel"],
        "organizations": snapshot["organizations"],
        "evidence": snapshot["evidence"],
    })


@router.get("/growth/list")
def growth_priority_list(
    from_semester: Optional[str] = None,
    to_semester: Optional[str] = None,
    college: Optional[str] = None,
    major: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[str] = None,
    group: Optional[str] = None,
    organization_id: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """透明优先级学生名单；不返回或使用未披露的综合风险分。"""
    if page < 1 or page_size < 1 or page_size > 100:
        raise ApiError("分页参数超出允许范围", code=400, status_code=400)
    snapshot = _growth_snapshot(
        conn, user, from_semester, to_semester,
        college, major, grade, class_id,
    )
    rows = filter_growth_rows(
        snapshot, group=group, organization_id=organization_id,
    )
    if keyword:
        value = keyword.strip().lower()
        rows = [
            row for row in rows
            if value in row["sid"].lower() or value in row["name"].lower()
        ]
    total = len(rows)
    offset = (page - 1) * page_size
    return ok({
        "period": snapshot["period"],
        "rule": snapshot["rule"],
        "group": group or "all",
        "organizationId": organization_id,
        "total": total, "page": page, "pageSize": page_size,
        "students": rows[offset:offset + page_size],
        "sorting": [
            "同时命中连续受挫和重复未解决",
            "低年级首次受挫",
            "明确恶化且未通过课程增加",
            "仅GPA明显下降",
            "其他关注学生",
        ],
        "overlapNotice": snapshot["evidence"]["overlapNotice"],
    })


@router.get("/analysis")
def analysis(semester: Optional[str] = None, grade: Optional[str] = None,
             college: Optional[str] = None, major: Optional[str] = None,
             class_id: Optional[str] = None, retake: Optional[str] = None,
             required: Optional[str] = None, year: Optional[str] = None,
             user: dict = Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_db)):
    scope_fingerprint = (
        (user.get("permission_context") or {}).get("scopeFingerprint")
        or f"legacy:{user.get('username')}:{user.get('role_id')}"
    )
    cache_key = (scope_fingerprint, semester, grade, college,
                 major, class_id, retake, required, year)
    cached = _ANALYSIS_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _ANALYSIS_CACHE_TTL:
        return ok(cached[1])
    # 学生维度过滤（学院/年级/专业/班级）：限定参与统计的学生集合。无值=全量。
    scond, sparams = [], []
    if college:
        scond.append("college_id=?"); sparams.append(college)
    if grade:
        scond.append("grade=?"); sparams.append(grade)
    if major:
        scond.append("major_id=?"); sparams.append(major)
    if class_id:
        scond.append("class_id=?"); sparams.append(class_id)
    # 数据范围过滤：college/major/class 角色仅看自己范围内的学生
    scope_frag, scope_sp = student_data_scope(user, conn, "dim_student")
    if scope_frag:
        scond.append(scope_frag); sparams += scope_sp
    swhere = (" WHERE " + " AND ".join(scond)) if scond else ""
    # fact_grade 子句：限定到上述学生集合 + 可选学期
    stu_sub = ""
    if scond:
        stu_sub = (" AND student_id IN (SELECT student_id FROM dim_student WHERE "
                   + " AND ".join(scond) + ")")

    # 学期/学年：semester 优先；否则 year 展开为该学年全部 semester（S1 跨学期聚合）。无值=全量。
    sem_ids = None
    if semester:
        sem_ids = [semester]
    elif year:
        sem_ids = [r["semester_id"] for r in dbm.query(
            conn, "SELECT semester_id FROM dim_semester WHERE year=?", (year,))]

    def _sem(col):
        if not sem_ids:
            return "", []
        ph = ",".join("?" * len(sem_ids))
        return f" AND {col} IN ({ph})", list(sem_ids)

    def _grade_clauses(alias="g"):
        """返回 (extra_where, params)：成绩表按学期/学生集合/重修/课程性质过滤。"""
        frag, params = _sem(f"{alias}.semester_id")
        conds = [frag[5:]] if frag else []  # 去掉前导 ' AND '
        if scond:
            conds.append(f"{alias}.student_id IN (SELECT student_id FROM dim_student WHERE "
                         + " AND ".join(scond) + ")")
            params += sparams
        if retake in ("重修", "1"):
            conds.append(f"{alias}.is_retake=1")
        elif retake in ("非重修", "0"):
            conds.append(f"{alias}.is_retake=0")
        if required in ("必修", "1"):
            conds.append(f"{alias}.is_required=1")
        elif required in ("选修", "0"):
            conds.append(f"{alias}.is_required=0")
        return (" AND " + " AND ".join(conds)) if conds else "", params

    total_stu = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student{swhere}", tuple(sparams)) or 0

    # 每生学分加权 GPA；缺少有效学分的成绩不进入 GPA。
    gw, gp = ["gpa IS NOT NULL"], []
    gsem, gsemp = _sem("semester_id")
    if gsem:
        gw.append(gsem[5:]); gp += gsemp
    if retake in ("重修", "1"):
        gw.append("is_retake=1")
    elif retake in ("非重修", "0"):
        gw.append("is_retake=0")
    if required in ("必修", "1"):
        gw.append("is_required=1")
    elif required in ("选修", "0"):
        gw.append("is_required=0")
    gpa_sql = f"""SELECT student_id,{weighted_gpa_expression()} g
        FROM fact_grade WHERE {' AND '.join(gw)}{stu_sub} GROUP BY student_id"""
    stu_gpa = {r["student_id"]: r["g"] for r in dbm.query(conn, gpa_sql, tuple(gp + sparams))}
    gpa_vals = list(stu_gpa.values())
    gpa_avg = round(sum(gpa_vals) / len(gpa_vals), 2) if gpa_vals else 0

    # 未通过人次率（真实成绩记录口径）
    fw, fpms = _grade_clauses("g")
    rtot = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_grade g WHERE g.source='real' AND g.is_pass IS NOT NULL{fw}", tuple(fpms)) or 0
    rfail = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_grade g WHERE g.source='real' AND g.is_pass=0{fw}", tuple(fpms)) or 0
    fail_rate = round(rfail / rtot * 100, 1) if rtot else 0
    alert_stu = dbm.scalar(conn, f"SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a WHERE COALESCE(a.is_active,1)=1"
                           + (f" AND a.student_id IN (SELECT student_id FROM dim_student WHERE {' AND '.join(scond)})" if scond else ""),
                           tuple(sparams)) or 0
    alert_rate = round(alert_stu / total_stu * 100, 1) if total_stu else 0
    # 毕业/学位为合成事实；沿用完整学生集合过滤，避免班级与角色范围越界。
    gradcond, gradp = [], []
    if scond:
        gradcond.append("student_id IN (SELECT student_id FROM dim_student WHERE "
                        + " AND ".join(scond) + ")")
        gradp += sparams
    gradw = (" WHERE " + " AND ".join(gradcond)) if gradcond else ""
    grad_rate = dbm.scalar(conn, f"SELECT AVG(graduated) FROM fact_graduation{gradw}", tuple(gradp)) or 0
    degree_rate = dbm.scalar(conn, f"SELECT AVG(degree) FROM fact_graduation{gradw}", tuple(gradp)) or 0

    studentKpis = [
        {"label": "在籍学生", "value": f"{total_stu:,}", "color": "#1E3A5F",
         "formula": "在籍本科生总数 COUNT(学籍)"},
        {"label": "范围GPA均值", "value": str(gpa_avg), "color": "#2563EB",
         "formula": "AVG(每生学分加权GPA)·5分制"},
        {"label": "未通过人次率", "value": f"{fail_rate}%", "color": "#DC2626",
         "formula": "未通过课程记录数÷有效成绩记录数（真实）"},
        {"label": "预警率", "value": f"{alert_rate}%", "color": "#EA580C",
         "formula": "预警学生÷在籍学生"},
        {"label": "毕业率", "value": f"{round(grad_rate * 100, 1)}%", "color": "#16A34A",
         "formula": "按期毕业÷应届总人数"},
        {"label": "学位授予率", "value": f"{round(degree_rate * 100, 1)}%", "color": "#1E3A5F",
         "formula": "获学位÷应届总人数"},
    ]

    # GPA 分层画像（固定 5 档，并非机器学习聚类；保留 clusters 键兼容既有前端契约）
    buckets = [("优秀", 3.5, 99, "#16A34A", "≥3.5"), ("良好", 3.0, 3.5, "#2563EB", "3.0-3.5"),
               ("一般", 2.5, 3.0, "#EA580C", "2.5-3.0"), ("困难", 2.0, 2.5, "#DC2626", "2.0-2.5"),
               ("高危", -1, 2.0, "#991B1B", "<2.0")]
    n_gpa = len(gpa_vals) or 1
    clusters = []
    for label, lo, hi, color, rng in buckets:
        c = sum(1 for g in gpa_vals if lo <= g < hi)
        clusters.append({"label": label, "count": c, "pct": round(c / n_gpa * 100),
                         "color": color, "gpa": rng})

    # 各年级 GPA（含未通过人次率/预警学生率）。
    gradeGpa = []
    for r in dbm.query(conn, f"SELECT grade, COUNT(*) n FROM dim_student{swhere} GROUP BY grade ORDER BY grade DESC", tuple(sparams)):
        gr = r["grade"]
        # 该年级叠加全部显式筛选与角色数据范围，避免子指标越界。
        gsc = ["grade=?"] + list(scond)
        gsp = [gr] + list(sparams)
        sub = "(SELECT student_id FROM dim_student WHERE " + " AND ".join(gsc) + ")"
        gvals = [stu_gpa[s] for s in [x["student_id"] for x in dbm.query(
            conn, f"SELECT student_id FROM dim_student WHERE {' AND '.join(gsc)}", tuple(gsp))]
            if s in stu_gpa]
        g_avg = round(sum(gvals) / len(gvals), 2) if gvals else 0
        sem_extra, sem_p = _sem("semester_id")
        rr_extra = ""
        if retake in ("重修", "1"):
            rr_extra += " AND is_retake=1"
        elif retake in ("非重修", "0"):
            rr_extra += " AND is_retake=0"
        if required in ("必修", "1"):
            rr_extra += " AND is_required=1"
        elif required in ("选修", "0"):
            rr_extra += " AND is_required=0"
        ft = dbm.query_one(conn, f"""
            SELECT COUNT(*) t, SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) f
            FROM fact_grade WHERE source='real' AND is_pass IS NOT NULL{sem_extra}{rr_extra}
              AND student_id IN {sub}""", tuple(sem_p + gsp)) or {}
        fr = round((ft.get("f") or 0) / ft["t"] * 100, 1) if ft.get("t") else 0
        al = dbm.scalar(conn, f"""
            SELECT COUNT(DISTINCT student_id) FROM fact_alert
            WHERE student_id IN {sub} AND COALESCE(is_active,1)=1""", tuple(gsp)) or 0
        ar = round(al / r["n"] * 100, 1) if r["n"] else 0
        gradeGpa.append({"grade": gr, "students": r["n"], "gpa": g_avg,
                         "failRate": f"{fr}%", "alertRate": f"{ar}%"})

    # 学分完成分布（已修÷应修）：对全体在校生现算，覆盖所有年级。
    # 已修=该生按课程去重后的通过学分（不随学期过滤，取全部历史）；
    # 应修=该生 (专业,年级) 在 fact_major_req 的 total_req。req 缺失则跳过该生（不计分母）。
    # 受学院/年级/专业/班级过滤（scond）限定参与统计的学生集合。
    cbuckets = [(">90%", 0.9, 9, "#16A34A"), ("80-90%", 0.8, 0.9, "#2563EB"),
                ("60-80%", 0.6, 0.8, "#EA580C"), ("<60%", -1, 0.6, "#DC2626")]
    req_map = {(r["major_id"], r["grade"]): r["total_req"]
               for r in dbm.query(conn, "SELECT major_id, grade, total_req FROM fact_major_req WHERE total_req>0")}
    scope_students = dbm.query(
        conn, f"SELECT student_id,major_id,grade FROM dim_student{swhere}",
        tuple(sparams),
    )
    earned_map = earned_credit_map(
        conn, [student["student_id"] for student in scope_students]
    )
    ratios = []
    for s in scope_students:
        req = req_map.get((s["major_id"], s["grade"]))
        if not req:
            continue
        earned = earned_map.get(s["student_id"], 0.0) or 0.0
        ratios.append(min(earned / req, 1.0))
    n_ratio = len(ratios) or 1
    creditDist = []
    for label, lo, hi, color in cbuckets:
        c = sum(1 for x in ratios if lo <= x < hi)
        creditDist.append({"label": label, "count": c,
                           "pct": round(c / n_ratio * 100), "color": color})

    # 挂科集中课程 TOP10（真实，修读≥30）
    fcw, fcp = _grade_clauses("g")
    # 课程级首次/最终通过率（取自 agg_course_term，旧口径，保留一个版本周期）
    cr_map = {}
    for cr in dbm.query(conn,
        "SELECT course_id, first_pass_rate, final_pass_rate FROM agg_course_term "
        "WHERE first_pass_rate IS NOT NULL GROUP BY course_id"):
        cr_map[cr["course_id"]] = (cr["first_pass_rate"], cr["final_pass_rate"])
    # M1：三分层通过率与课程类别改读 V2 agg_course_pass_stat。
    # 与总览保持“明确学期 + 当前学生范围”口径；V2 未构建时字段为 None。
    from .dashboard import _rate as _v2_rate, _v2_pass_stats
    pass_semester = (
        semester
        or (sorted(sem_ids)[-1] if sem_ids else CURRENT_SEMESTER)
    )
    pass_student_ids = (
        [row["student_id"] for row in dbm.query(
            conn, f"SELECT student_id FROM dim_student{swhere}", tuple(sparams))]
        if scond else None
    )
    v2_courses = (
        _v2_pass_stats(pass_semester, pass_student_ids) or {}
    ).get("courses", {})
    failCourses = []
    for r in dbm.query(conn, f"""
        SELECT g.course_id, co.name cname, co.dept, COUNT(*) total,
               SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fc, AVG(g.score) av
        FROM fact_grade g LEFT JOIN dim_course co ON g.course_id=co.course_id
        WHERE g.source='real' AND g.is_pass IS NOT NULL{fcw}
        GROUP BY g.course_id HAVING total>=30 AND fc>0
        ORDER BY (fc*1.0/total) DESC LIMIT 10""", tuple(fcp)):
        fr = round(r["fc"] / r["total"] * 100, 1)
        fpr, lpr = cr_map.get(r["course_id"], (None, None))
        v2c = v2_courses.get(r["course_id"]) or {}
        failCourses.append({
            "id": r["course_id"], "name": r["cname"] or r["course_id"],
            "dept": r["dept"] or "—", "failRate": fr, "failCount": r["fc"],
            "totalCount": r["total"],
            "avgScore": round(r["av"], 1) if r["av"] is not None else "—",
            "firstPassRate": round((fpr or 0) * 100, 1),
            "finalPassRate": round((lpr or 0) * 100, 1),
            "makeupPassRate": _v2_rate(v2c.get("mp"), v2c.get("ma")),
            "retakePassRate": _v2_rate(v2c.get("rp"), v2c.get("ra")),
            "courseGroup": v2c.get("course_group"),
        })

    # 相邻学期画像迁移：优先使用所选学年中的后两个学期；单学期时向前补一学期；
    # 未指定时使用有成绩的最新两个学期。只比较两个学期均有 GPA 的学生。
    available_sems = [r["semester_id"] for r in dbm.query(conn,
        "SELECT semester_id FROM dim_semester ORDER BY semester_id")]
    if sem_ids and len(sem_ids) >= 2:
        pair = sorted(sem_ids)[-2:]
    elif sem_ids and len(sem_ids) == 1:
        target = sem_ids[0]
        previous = [s for s in available_sems if s < target]
        pair = ([previous[-1]] if previous else []) + [target]
    else:
        grade_sems = [r["semester_id"] for r in dbm.query(conn,
            "SELECT DISTINCT semester_id FROM fact_grade WHERE gpa IS NOT NULL ORDER BY semester_id")]
        pair = grade_sems[-2:]
    migration = {"fromSemester": pair[0] if len(pair) == 2 else None,
                 "toSemester": pair[1] if len(pair) == 2 else None,
                 "improved": 0, "stable": 0, "declined": 0, "mixed": 0,
                 "insufficient": total_stu, "compared": 0, "avgDelta": None,
                 "avgFailDelta": None, "threshold": 0.3, "failThreshold": 1,
                 "definition": "同时比较学期学分加权GPA和未通过课程门数；任一指标明显变化且另一指标未反向恶化，判为改善或恶化；两个指标方向冲突时列为变化分化。"}
    if len(pair) == 2:
        ph = ",".join("?" * 2)
        mig_student = (" AND g.student_id IN (SELECT student_id FROM dim_student WHERE "
                       + " AND ".join(scond) + ")") if scond else ""
        mig_rows = dbm.query(conn, f"""SELECT g.student_id,g.semester_id,
            {weighted_gpa_expression('g')} gpa,
            COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.course_id END) fail_count,
            COUNT(*) grade_count
            FROM fact_grade g WHERE g.semester_id IN ({ph}){mig_student}
            GROUP BY g.student_id,g.semester_id""", tuple(pair + sparams))
        by_student = {}
        for row in mig_rows:
            by_student.setdefault(row["student_id"], {})[row["semester_id"]] = row
        deltas = []
        fail_deltas = []
        for values in by_student.values():
            if pair[0] not in values or pair[1] not in values:
                continue
            old, new = values[pair[0]], values[pair[1]]
            gpa_delta = (new["gpa"] - old["gpa"]) if old["gpa"] is not None and new["gpa"] is not None else None
            fail_delta = (new["fail_count"] or 0) - (old["fail_count"] or 0)
            if gpa_delta is not None: deltas.append(gpa_delta)
            improve_signal = (gpa_delta is not None and gpa_delta >= 0.3) or fail_delta <= -1
            decline_signal = (gpa_delta is not None and gpa_delta <= -0.3) or fail_delta >= 1
            category = "mixed" if improve_signal and decline_signal else "improved" if improve_signal else "declined" if decline_signal else "stable"
            migration[category] += 1
            fail_deltas.append(fail_delta)
        migration["compared"] = len(fail_deltas)
        migration["insufficient"] = max(total_stu - len(fail_deltas), 0)
        migration["avgDelta"] = round(sum(deltas) / len(deltas), 2) if deltas else None
        migration["avgFailDelta"] = round(sum(fail_deltas) / len(fail_deltas), 2) if fail_deltas else None

    # 挂科模式：基于当前筛选范围内的真实不及格记录，可相互重叠。
    pattern_where, pattern_params = _grade_clauses("g")
    failed_rows = dbm.query(conn, f"""SELECT g.student_id,g.course_id,g.semester_id,
        g.is_required,g.is_retake FROM fact_grade g
        WHERE g.source='real' AND g.is_pass=0{pattern_where}""", tuple(pattern_params))
    by_stu_course, by_stu_sem, required_fail, retake_fail = {}, {}, {}, set()
    for row in failed_rows:
        sid = row["student_id"]
        by_stu_course[(sid, row["course_id"])] = by_stu_course.get((sid, row["course_id"]), 0) + 1
        by_stu_sem.setdefault(sid, set()).add(row["semester_id"])
        if row["is_required"] == 1:
            required_fail[sid] = required_fail.get(sid, 0) + 1
        if row["is_retake"] == 1:
            retake_fail.add(sid)
    repeated = {sid for (sid, _), count in by_stu_course.items() if count >= 2}
    multi_sem = {sid for sid, semesters_set in by_stu_sem.items() if len(semesters_set) >= 2}
    required_multi = {sid for sid, count in required_fail.items() if count >= 3}
    failPatterns = [
        {"key": "repeat_course", "label": "同课重复挂科", "count": len(repeated),
         "definition": "同一学生同一课程至少2条不及格记录"},
        {"key": "multi_semester", "label": "跨学期持续挂科", "count": len(multi_sem),
         "definition": "同一学生至少2个学期存在不及格记录"},
        {"key": "required_multi", "label": "必修挂科集中", "count": len(required_multi),
         "definition": "同一学生至少3条必修课程不及格记录"},
        {"key": "retake_failed", "label": "重修仍未通过", "count": len(retake_fail),
         "definition": "存在重修标记且结果仍不及格"},
    ]

    payload = {"studentKpis": studentKpis, "clusters": clusters,
               "gradeGpa": gradeGpa, "creditDist": creditDist,
               "failCourses": failCourses, "migration": migration,
               "failPatterns": failPatterns,
               "evidence": {
                   "real": ["学籍、成绩、GPA、挂科、当前有效预警、跨学期GPA与挂科联合迁移、历史挂科模式"],
                   "simulated": ["毕业结果、学位授予结果、非真实培养方案专业的学分要求"],
                   "limitation": "毕业率和学位授予率来自固定种子合成业务表；学分完成度仅在真实培养方案覆盖专业可精确解释。"
               }}
    _ANALYSIS_CACHE[cache_key] = (time.monotonic(), payload)
    return ok(payload)


@router.get("/list")
def student_list(semester: Optional[str] = None, grade: Optional[str] = None,
                  college: Optional[str] = None, major: Optional[str] = None,
                  class_id: Optional[str] = None, retake: Optional[str] = None,
                  required: Optional[str] = None, year: Optional[str] = None,
                  course: Optional[str] = None,
                  pattern: Optional[str] = None,
                  migration: Optional[str] = None,
                  from_semester: Optional[str] = None,
                  to_semester: Optional[str] = None,
                  keyword: Optional[str] = None,
                  sort: Optional[str] = None, order: Optional[str] = "asc",
                  page: int = 1, page_size: int = 20,
                  user: dict = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """学生明细列表：支持筛选 + 关键词搜索 + 分页 + 关键学业指标。每行可跳转学生详情。"""
    scond, sparams = [], []
    if college:
        scond.append("college_id=?"); sparams.append(college)
    if grade:
        scond.append("grade=?"); sparams.append(grade)
    if major:
        scond.append("major_id=?"); sparams.append(major)
    if class_id:
        scond.append("class_id=?"); sparams.append(class_id)
    # 数据范围过滤
    scope_frag2, scope_sp2 = student_data_scope(user, conn, "dim_student")
    if scope_frag2:
        scond.append(scope_frag2); sparams += scope_sp2
    if keyword:
        kw = f"%{keyword}%"
        scond.append("(student_id LIKE ? OR name LIKE ?)")
        sparams += [kw, kw]
    # 学期过滤
    sem_ids = None
    if semester:
        sem_ids = [semester]
    elif year:
        sem_ids = [r["semester_id"] for r in dbm.query(
            conn, "SELECT semester_id FROM dim_semester WHERE year=?", (year,))]

    # 课程下钻必须与所选学期/学年取交集；未选周期时才表示历史修读。
    if course:
        course_sql = """student_id IN (
            SELECT DISTINCT student_id FROM fact_grade
            WHERE source='real' AND course_id=?"""
        course_params = [course]
        if sem_ids:
            course_sql += " AND semester_id IN (" + ",".join("?" * len(sem_ids)) + ")"
            course_params.extend(sem_ids)
        course_sql += ")"
        scond.append(course_sql)
        sparams.extend(course_params)

    def _sem_cond(alias="g"):
        if not sem_ids:
            return "", []
        ph = ",".join("?" * len(sem_ids))
        field = f"{alias}.semester_id" if alias else "semester_id"
        return f" AND {field} IN ({ph})", list(sem_ids)

    # 群体画像下钻：挂科模式沿用当前学期/课程性质/重修口径；迁移使用指定相邻学期。
    # 最终仍与显式维度筛选和角色数据范围取交集。
    def _include_ids(ids):
        values = sorted(set(ids))
        if values:
            scond.append("student_id IN (" + ",".join("?" * len(values)) + ")")
            sparams.extend(values)
        else:
            scond.append("1=0")

    valid_patterns = {"repeat_course", "multi_semester", "required_multi", "retake_failed"}
    if pattern:
        if pattern not in valid_patterns:
            raise ApiError("无效的挂科模式", code=400, status_code=400)
        psem, pparams = _sem_cond("g")
        pextra = ""
        if retake in ("重修", "1"):
            pextra += " AND g.is_retake=1"
        elif retake in ("非重修", "0"):
            pextra += " AND g.is_retake=0"
        if required in ("必修", "1"):
            pextra += " AND g.is_required=1"
        elif required in ("选修", "0"):
            pextra += " AND g.is_required=0"
        prows = dbm.query(conn, f"""SELECT g.student_id,g.course_id,g.semester_id,
            g.is_required,g.is_retake FROM fact_grade g
            WHERE g.source='real' AND g.is_pass=0{psem}{pextra}""", tuple(pparams))
        p_course, p_semesters, p_required, p_retake = {}, {}, {}, set()
        for row in prows:
            sid = row["student_id"]
            p_course[(sid, row["course_id"])] = p_course.get((sid, row["course_id"]), 0) + 1
            p_semesters.setdefault(sid, set()).add(row["semester_id"])
            if row["is_required"] == 1:
                p_required[sid] = p_required.get(sid, 0) + 1
            if row["is_retake"] == 1:
                p_retake.add(sid)
        pattern_ids = {
            "repeat_course": {sid for (sid, _), count in p_course.items() if count >= 2},
            "multi_semester": {sid for sid, values in p_semesters.items() if len(values) >= 2},
            "required_multi": {sid for sid, count in p_required.items() if count >= 3},
            "retake_failed": p_retake,
        }
        _include_ids(pattern_ids[pattern])

    valid_migrations = {"improved", "stable", "declined", "mixed", "insufficient"}
    if migration:
        if migration not in valid_migrations:
            raise ApiError("无效的画像迁移分类", code=400, status_code=400)
        if not from_semester or not to_semester or from_semester >= to_semester:
            raise ApiError("画像迁移下钻需要有效的起止学期", code=400, status_code=400)
        mrows = dbm.query(conn, f"""SELECT student_id,semester_id,
            {weighted_gpa_expression()} gpa,
            COUNT(DISTINCT CASE WHEN is_pass=0 THEN course_id END) fail_count,
            COUNT(*) grade_count
            FROM fact_grade WHERE semester_id IN (?,?)
            GROUP BY student_id,semester_id""", (from_semester, to_semester))
        mvalues = {}
        for row in mrows:
            mvalues.setdefault(row["student_id"], {})[row["semester_id"]] = row
        categories = {"improved": set(), "stable": set(), "declined": set(), "mixed": set()}
        compared = set()
        for sid, values in mvalues.items():
            if from_semester not in values or to_semester not in values:
                continue
            compared.add(sid)
            old, new = values[from_semester], values[to_semester]
            gpa_delta = (new["gpa"] - old["gpa"]) if old["gpa"] is not None and new["gpa"] is not None else None
            fail_delta = (new["fail_count"] or 0) - (old["fail_count"] or 0)
            improve_signal = (gpa_delta is not None and gpa_delta >= 0.3) or fail_delta <= -1
            decline_signal = (gpa_delta is not None and gpa_delta <= -0.3) or fail_delta >= 1
            category = "mixed" if improve_signal and decline_signal else "improved" if improve_signal else "declined" if decline_signal else "stable"
            categories[category].add(sid)
        if migration == "insufficient":
            if compared:
                values = sorted(compared)
                scond.append("student_id NOT IN (" + ",".join("?" * len(values)) + ")")
                sparams.extend(values)
        else:
            _include_ids(categories[migration])

    swhere = (" WHERE " + " AND ".join(scond)) if scond else ""

    # 学生 GPA：画像迁移下钻时固定展示目标学期，避免名单使用全历史
    # GPA、抽屉使用最新学期 GPA 而与分组证据冲突。
    metric_sem_ids = (
        [to_semester] if migration and to_semester else (sem_ids or [])
    )
    gw = ["gpa IS NOT NULL"]
    if metric_sem_ids:
        gsem = " AND semester_id IN (" + ",".join("?" * len(metric_sem_ids)) + ")"
        gsemp = list(metric_sem_ids)
    else:
        gsem, gsemp = "", []
    if gsem:
        gw.append(gsem[5:])
    if retake in ("重修", "1"):
        gw.append("is_retake=1")
    elif retake in ("非重修", "0"):
        gw.append("is_retake=0")
    if required in ("必修", "1"):
        gw.append("is_required=1")
    elif required in ("选修", "0"):
        gw.append("is_required=0")
    stu_sub = ""
    if scond:
        stu_sub = (" AND student_id IN (SELECT student_id FROM dim_student WHERE "
                   + " AND ".join(scond) + ")")
    gw.append("1=1")  # ensures at least one condition before stu_sub
    gpa_sql = f"""SELECT student_id,{weighted_gpa_expression()} g
        FROM fact_grade WHERE {' AND '.join(gw)}{stu_sub} GROUP BY student_id"""
    stu_gpa = {r["student_id"]: r["g"] for r in dbm.query(conn, gpa_sql, tuple(gsemp + sparams))}

    # 挂科数
    fail_extra = ""
    if retake in ("重修", "1"):
        fail_extra += " AND is_retake=1"
    elif retake in ("非重修", "0"):
        fail_extra += " AND is_retake=0"
    if required in ("必修", "1"):
        fail_extra += " AND is_required=1"
    elif required in ("选修", "0"):
        fail_extra += " AND is_required=0"
    fail_sql = f"""SELECT student_id, COUNT(*) fc FROM fact_grade
        WHERE source='real' AND is_pass=0{gsem}{fail_extra}{stu_sub} GROUP BY student_id"""
    stu_fail = {r["student_id"]: r["fc"] for r in dbm.query(conn, fail_sql, tuple(gsemp + sparams))}

    # 预警状态
    alert_sql = f"""SELECT student_id, GROUP_CONCAT(DISTINCT level) levels
        FROM fact_alert WHERE status='未处理' AND COALESCE(is_active,1)=1{stu_sub.replace('student_id IN','a.student_id IN').replace('dim_student','dim_student')}
        GROUP BY student_id""" if scond else """SELECT student_id, GROUP_CONCAT(DISTINCT level) levels
        FROM fact_alert WHERE status='未处理' AND COALESCE(is_active,1)=1 GROUP BY student_id"""
    # Skip complex subquery rewrite — just query all alerts
    stu_alert_levels: dict = {}
    for r in dbm.query(conn, """SELECT student_id, level FROM fact_alert
                                  WHERE status='未处理' AND COALESCE(is_active,1)=1"""):
        prev = stu_alert_levels.get(r["student_id"], "")
        if r["level"] not in prev:
            stu_alert_levels[r["student_id"]] = (prev + " " + r["level"]).strip()

    # 名称映射
    cname = {r["college_id"]: r["name"] for r in dbm.query(conn, "SELECT college_id, name FROM dim_college")}
    mname = {r["major_id"]: r["name"] for r in dbm.query(conn, "SELECT major_id, name FROM dim_major")}
    clname = {r["class_id"]: r["name"] for r in dbm.query(conn, "SELECT class_id, name FROM dim_class")}

    # 分页：复用上方已按学期/重修/课程性质计算的 GPA 映射排序，
    # 避免为每名学生执行相关子查询，也保证列表顺序与展示 GPA 口径一致。
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student{swhere}", tuple(sparams)) or 0
    offset = (page - 1) * page_size
    students = []
    candidate_students = dbm.query(conn, f"""SELECT student_id,name,college_id,major_id,
        class_id,grade,status FROM dim_student{swhere}""", tuple(sparams))
    if sort == "gpa":
        reverse = (order or "asc") == "desc"
        candidate_students.sort(key=lambda x: (
            stu_gpa.get(x["student_id"]) is not None,
            stu_gpa.get(x["student_id"]) if stu_gpa.get(x["student_id"]) is not None else -1,
            x["student_id"]), reverse=reverse)
    else:
        candidate_students.sort(key=lambda x: x["student_id"], reverse=(order or "asc") == "desc")
    for s in candidate_students[offset:offset + page_size]:
        sid = s["student_id"]
        gpa = stu_gpa.get(sid)
        students.append({
            "sid": sid, "name": s["name"] or sid, "college": cname.get(s["college_id"], s["college_id"]),
            "major": s["major_id"], "majorName": mname.get(s["major_id"], ""),
            "class": s["class_id"] or "—", "className": clname.get(s["class_id"], ""),
            "grade": (s["grade"] or "") + ("级" if s["grade"] else ""),
            "gpa": round(gpa, 2) if gpa is not None else None,
            "failCount": stu_fail.get(sid, 0),
            "alertLevel": stu_alert_levels.get(sid, "—"),
        })

    pop_gpas = list(stu_gpa.values())
    return ok({"total": total, "page": page, "pageSize": page_size, "students": students,
               "appliedFilters": {
                   "semester": semester, "year": year, "college": college,
                   "major": major, "grade": grade, "classId": class_id,
                   "course": course, "retake": retake, "required": required,
                   "pattern": pattern, "migration": migration,
               },
               "summary": {"withGpa": len(pop_gpas),
                           "avgGpa": round(sum(pop_gpas) / len(pop_gpas), 2) if pop_gpas else None,
                           "metricSemester": metric_sem_ids[0] if len(metric_sem_ids) == 1 else None}})


# ── M3：我的班级/我的学生（辅导员/班主任/导师群体视图） ──
# 口径与 /api/admin/student/{sid}（alert.py）及本模块 analysis 保持一致：
# GPA=本学期每生学分加权 GPA 再平均；
# 本学期未通过学生率=本学期至少1门未通过学生÷本学期有有效成绩学生；
# 学分完成率=按课程去重的已通过学分 ÷ fact_major_req.total_req
# （req 缺失不计入中位数）；
# 未解除预警=alert_event.workflow_status 未进入 resolved/closed。

_MY_SCOPE_ROLES = ("counselor", "class_adviser", "mentor")

_MY_SCOPE_EVIDENCE = {
    "real": ["学籍、本学期成绩、学分加权GPA、本学期未通过记录", "未解除预警事件（alert_event 工作流状态）"],
    "simulated": ["非真实培养方案专业的学分要求（影响学分完成率）"],
    "limitation": "学分完成率按课程去重，但只有真实培养方案覆盖的专业可精确解释；要求学分缺失的学生不计入学分完成率中位数。",
}


def _in_ph(ids) -> str:
    return ",".join("?" * len(ids))


def _per_student_gpa(conn, ids, semester=None) -> dict:
    return per_student_weighted_gpa(
        conn, ids, [semester] if semester else None
    )


def _earned_credit_map(conn, ids) -> dict:
    return earned_credit_map(conn, ids)


def _term_fail_count_map(conn, ids, semester) -> dict:
    """本学期真实挂科门数（与学生详情页 semesterSummary 同学期口径）。"""
    if not ids:
        return {}
    return {r["student_id"]: r["fc"] for r in dbm.query(conn, f"""
        SELECT student_id, COUNT(DISTINCT course_id) fc FROM fact_grade
        WHERE source='real' AND is_pass=0 AND semester_id=?
          AND student_id IN ({_in_ph(ids)})
        GROUP BY student_id""", (semester, *ids))}


def _open_event_maps(conn, ids) -> tuple[dict, set]:
    """未解除预警：alert_event.workflow_status 未进入 resolved/closed。
    返回 (每生未解除事件数, 有未解除事件学生集合)。"""
    if not ids:
        return {}, set()
    per_sid, sids = {}, set()
    for r in dbm.query(conn, f"""
        SELECT student_id, COUNT(*) n FROM alert_event
        WHERE workflow_status NOT IN ('resolved','closed')
          AND student_id IN ({_in_ph(ids)})
        GROUP BY student_id""", tuple(ids)):
        per_sid[r["student_id"]] = r["n"]
        sids.add(r["student_id"])
    return per_sid, sids


def _credit_req_map(conn) -> dict:
    return {(r["major_id"], r["grade"]): r["total_req"] for r in dbm.query(
        conn, "SELECT major_id, grade, total_req FROM fact_major_req WHERE total_req>0")}


def _median(values) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if not n:
        return None
    mid = n // 2
    med = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2
    return round(med, 1)


def _scope_metrics(conn, students, semester) -> tuple[dict, list]:
    """对一组 dim_student 行计算群体汇总与每生明细行（数字全部后端算好）。"""
    ids = [s["student_id"] for s in students]
    gpa = _per_student_gpa(conn, ids, semester)
    earned = _earned_credit_map(conn, ids)
    graded, failed = term_grade_and_failed_students(conn, ids, semester)
    term_fail = _term_fail_count_map(conn, ids, semester)
    per_sid_alerts, alert_sids = _open_event_maps(conn, ids)
    reqs = _credit_req_map(conn)
    clname = {r["class_id"]: r["name"] for r in dbm.query(
        conn, "SELECT class_id, name FROM dim_class")}
    ratios, rows = [], []
    for s in students:
        sid = s["student_id"]
        req = reqs.get((s["major_id"], s["grade"]))
        ratio = None
        if req:
            ratio = round(min((earned.get(sid) or 0.0) / req, 1.0) * 100, 1)
            ratios.append(ratio)
        g = gpa.get(sid)
        rows.append({
            "sid": sid, "name": s["name"] or sid,
            "classId": s["class_id"] or "",
            "className": clname.get(s["class_id"], "") or (s["class_id"] or "—"),
            "gpa": round(g, 2) if g is not None else None,
            "failCount": term_fail.get(sid, 0),
            "creditRatio": ratio,
            "openAlerts": per_sid_alerts.get(sid, 0),
        })
    gpa_vals = [v for v in gpa.values() if v is not None]
    summary = {
        "studentCount": len(ids),
        "avgGpa": round(sum(gpa_vals) / len(gpa_vals), 2) if gpa_vals else None,
        "gradedStudentCount": len(graded),
        "gradeCoverageRate": round(len(graded) / len(ids) * 100, 1) if ids else None,
        "failedStudentCount": len(failed),
        "failRate": round(len(failed) / len(graded) * 100, 1) if graded else None,
        "creditMedian": _median(ratios),
        "withOpenAlerts": len(alert_sids),
        "openAlerts": sum(per_sid_alerts.values()),
    }
    return summary, rows


def _class_students(conn, class_id):
    return dbm.query(conn, """
        SELECT student_id, name, major_id, grade, class_id
        FROM dim_student WHERE class_id=? ORDER BY student_id""", (class_id,))


def _class_cards(conn, groups: list[tuple[str, list]], semester) -> list:
    names = {r["class_id"]: r["name"] for r in dbm.query(
        conn, "SELECT class_id, name FROM dim_class")}
    cards = []
    for class_id, students in groups:
        summary, rows = _scope_metrics(conn, students, semester)
        cards.append({
            "classId": class_id,
            "className": names.get(class_id, class_id or "未分班"),
            **summary,
            "students": rows,
        })
    return cards


@router.get("/my-scope")
def my_scope(user: dict = Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_db)):
    """M3 三视角群体视图：
    - counselor：按 sys_user_scope 班级集合逐班聚合（班级卡 + 班内学生行）；
    - class_adviser：按人员—行政班关系学生集合，再按行政班分组（同辅导员班级卡结构）；
    - mentor：按人员—学生关系返回学生明细行数组；
    - 其他角色：scopeKind='other' + 空载荷（前端引导去学生成长分析页），不报错。
    """
    role_id = user.get("role_id")
    semester = CURRENT_SEMESTER
    base = {"roleId": role_id, "semester": semester, "evidence": _MY_SCOPE_EVIDENCE}
    if role_id not in _MY_SCOPE_ROLES:
        return ok({**base, "scopeKind": "other", "view": "none",
                   "summary": None, "classes": [], "students": []})

    context = user.get("permission_context") or {}
    detail = context.get("detailScope") or {}
    if role_id == "counselor" and detail.get("type") == "class":
        class_ids = sorted(detail.get("classIds") or [])
        groups = [(cid, _class_students(conn, cid)) for cid in class_ids]
        classes = _class_cards(conn, groups, semester)
        all_students = [s for _, students in groups for s in students]
        summary, _ = _scope_metrics(conn, all_students, semester)
        return ok({**base, "scopeKind": "class", "view": "classes",
                   "summary": summary, "classes": classes, "students": []})

    # staff_relation：班主任/导师（或无班级范围的辅导员）按人员关系取学生集合
    ids = _staff_student_ids(user)
    students = dbm.query(conn, f"""
        SELECT student_id, name, major_id, grade, class_id
        FROM dim_student WHERE student_id IN ({_in_ph(ids)})
        ORDER BY student_id""", tuple(ids)) if ids else []
    if role_id == "mentor":
        summary, rows = _scope_metrics(conn, students, semester)
        return ok({**base, "scopeKind": "staff_relation", "view": "students",
                   "summary": summary, "classes": [], "students": rows})
    by_class: dict[str, list] = {}
    for s in students:
        by_class.setdefault(s["class_id"] or "", []).append(s)
    groups = sorted(by_class.items(), key=lambda kv: kv[0])
    classes = _class_cards(conn, groups, semester)
    summary, _ = _scope_metrics(conn, students, semester)
    return ok({**base, "scopeKind": "staff_relation", "view": "classes",
               "summary": summary, "classes": classes, "students": []})
