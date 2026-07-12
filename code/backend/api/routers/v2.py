"""V2真实数据验证接口。全部只读，响应继续使用{code,msg,data}。"""
import sqlite3
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Query

from .. import db as dbm
from ..deps import get_current_user, get_v2_db
from ..envelope import ApiError, ok

router = APIRouter(prefix="/api/v2", tags=["v2"])

V2_ALL_SCOPE_ROLES = {"school_leader", "dean", "dept_operation", "dept_research", "dept_practice", "quality_office"}
V2_MAPPED_SCOPE_ROLES = {"college_dean", "college_secretary", "counselor", "dept_director"}


def require_v2_reader(user: dict = Depends(get_current_user)) -> dict:
    """允许全校角色及已建立显式V2范围映射的角色。"""
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES | V2_MAPPED_SCOPE_ROLES:
        raise ApiError("当前角色没有V2访问范围", code=403, status_code=403)
    return user


def require_v2_all_reader(user: dict = Depends(get_current_user)) -> dict:
    """课程、教师和空间全校聚合在范围过滤完成前仅开放全校角色。"""
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES:
        raise ApiError("当前接口仅对全校范围角色开放", code=403, status_code=403)
    return user


def _student_scope(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    role = user.get("role_id")
    if role in V2_ALL_SCOPE_ROLES:
        return "", []
    mappings = dbm.query(conn, "SELECT * FROM access_scope_mapping WHERE role_id=? AND mapping_status='mapped'", (role,))
    if not mappings:
        raise ApiError("V2数据范围未映射", code=403, status_code=403)
    scope_type = mappings[0]["scope_type"]
    if scope_type == "college":
        values = [x["organization_id"] for x in mappings if x.get("organization_id")]
        field = "organization_id"
    elif scope_type == "major":
        values = [x["major_code"] for x in mappings if x.get("major_code")]
        field = "major_code"
    elif scope_type == "class":
        values = [x["class_code"] for x in mappings if x.get("class_code")]
        field = "class_code"
    else:
        raise ApiError("不支持的数据范围类型", code=403, status_code=403)
    if not values:
        raise ApiError("V2数据范围为空", code=403, status_code=403)
    return f"{alias}.{field} IN ({','.join('?' for _ in values)})", values


def _assert_student_access(student_id: str, user: dict, conn: sqlite3.Connection) -> None:
    fragment, params = _student_scope(user, conn, "s")
    sql = "SELECT 1 FROM dim_student s WHERE s.student_id=?" + (f" AND {fragment}" if fragment else "")
    if not dbm.query_one(conn, sql, tuple([student_id] + params)):
        raise ApiError("学生不存在或无权访问", code=404, status_code=404)


@router.get("/health")
def health(conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    batches = dbm.scalar(conn, "SELECT COUNT(*) FROM data_batch") or 0
    return ok({"status": "up", "batches": batches, "mode": "read-only"})


@router.get("/meta/teaching-semesters")
def teaching_semesters(conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    rows = dbm.query(conn, """SELECT s.semester_id,s.name,s.academic_year,s.season,COUNT(DISTINCT l.lesson_id) lesson_count
        FROM dim_semester s JOIN teaching_lesson l ON l.semester_id=s.semester_id
        GROUP BY s.semester_id,s.name,s.academic_year,s.season ORDER BY s.semester_id DESC""")
    return ok({"items": rows, "current": rows[0]["semester_id"] if rows else None,
               "scope": "仅返回已接入真实教学任务的学期"})


@router.get("/students/difficult")
def difficult_students(flag: Optional[str] = None, severity: Optional[str] = None,
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    cond, params = ["1=1"], []
    scope, scope_params = _student_scope(user, conn, "s")
    if scope:
        cond.append(scope); params.extend(scope_params)
    if flag:
        cond.append("f.flag_code=?"); params.append(flag)
    if severity:
        cond.append("f.severity=?"); params.append(severity)
    where = " AND ".join(cond)
    total = dbm.scalar(conn, f"SELECT COUNT(DISTINCT f.student_id) FROM student_difficulty_flag f JOIN dim_student s ON s.student_id=f.student_id WHERE {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT f.student_id,s.display_name,s.entry_grade,s.organization_id,s.major_code,s.class_code,
        COUNT(*) flag_count,MAX(CASE f.severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) severity_rank,
        GROUP_CONCAT(f.flag_code) flags,g.failed_courses,g.required_missing,g.retake_attempts
        FROM student_difficulty_flag f JOIN dim_student s ON s.student_id=f.student_id
        LEFT JOIN student_growth_indicator g ON g.student_id=f.student_id AND g.indicator_version='growth-v1'
        WHERE {where} GROUP BY f.student_id ORDER BY severity_rank DESC,flag_count DESC,f.student_id LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset]))
    return ok({"items": rows, "total": total, "limit": limit, "offset": offset})


@router.get("/topics/early-setback")
def early_setback_topic(organization_id: Optional[str] = None, major_code: Optional[str] = None,
                        entry_grade: Optional[int] = None,
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    """大一首次挂科及后续恢复专题；只使用已发布、未作废且通过口径明确的成绩。"""
    cond, params = ["s.entry_grade BETWEEN 2000 AND 2100"], []
    scope, scope_params = _student_scope(user, conn, "s")
    if scope:
        cond.append(scope); params.extend(scope_params)
    if organization_id:
        cond.append("s.organization_id=?"); params.append(organization_id)
    if major_code:
        cond.append("s.major_code=?"); params.append(major_code)
    if entry_grade:
        cond.append("s.entry_grade=?"); params.append(entry_grade)
    where = " AND ".join(cond)
    cte = f"""
    WITH eligible AS (
      SELECT s.* FROM dim_student s WHERE {where}
    ), term_result AS (
      SELECT g.student_id,g.semester_id,
        CAST(substr(g.semester_id,1,4) AS INTEGER)-e.entry_grade+1 study_year,
        substr(g.semester_id,-1) term_no,
        COUNT(*) attempts,SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failures,
        AVG(g.gpa) avg_gpa
      FROM grade_attempt g JOIN eligible e ON e.student_id=g.student_id
      WHERE g.is_published=1 AND g.is_void=0 AND g.is_pass IS NOT NULL
      GROUP BY g.student_id,g.semester_id
    ), student_result AS (
      SELECT e.student_id,e.display_name,e.entry_grade,e.organization_id,e.major_code,e.major_name,e.class_code,
        SUM(CASE WHEN t.study_year=1 AND t.term_no IN ('1','2') THEN t.failures ELSE 0 END) first_year_failures,
        SUM(CASE WHEN t.study_year=1 AND t.term_no IN ('1','2') THEN t.attempts ELSE 0 END) first_year_attempts,
        SUM(CASE WHEN t.study_year>1 AND t.term_no IN ('1','2') THEN t.failures ELSE 0 END) later_failures,
        SUM(CASE WHEN t.study_year>1 AND t.term_no IN ('1','2') THEN t.attempts ELSE 0 END) later_attempts,
        MIN(CASE WHEN t.study_year=1 AND t.term_no IN ('1','2') AND t.failures>0 THEN t.semester_id END) first_setback_semester,
        MAX(CASE WHEN t.study_year>1 AND t.term_no IN ('1','2') THEN t.semester_id END) latest_later_semester,
        AVG(CASE WHEN t.study_year=1 AND t.term_no IN ('1','2') THEN t.avg_gpa END) first_year_gpa,
        AVG(CASE WHEN t.study_year>1 AND t.term_no IN ('1','2') THEN t.avg_gpa END) later_gpa
      FROM eligible e LEFT JOIN term_result t ON t.student_id=e.student_id GROUP BY e.student_id
    ), classified AS (
      SELECT *,CASE
        WHEN first_year_failures=0 THEN 'no_setback'
        WHEN later_attempts=0 THEN 'pending_observation'
        WHEN later_failures=0 THEN 'recovered'
        WHEN later_failures<=first_year_failures THEN 'recovering'
        ELSE 'persistent' END recovery_status
      FROM student_result WHERE first_year_attempts>0
    )
    """
    all_rows = dbm.query(conn, cte + "SELECT * FROM classified", tuple(params))
    setback_rows = [x for x in all_rows if x["first_year_failures"] > 0]
    rank = {"persistent": 0, "recovering": 1, "pending_observation": 2, "recovered": 3}
    setback_rows.sort(key=lambda x: (rank[x["recovery_status"]], -x["later_failures"],
                                     -x["first_year_failures"], x["student_id"]))
    total = len(setback_rows); students = setback_rows[offset:offset + limit]
    summary = {"eligible_students": len(all_rows), "setback_students": len(setback_rows),
      "recovered_students": sum(x["recovery_status"] == "recovered" for x in setback_rows),
      "recovering_students": sum(x["recovery_status"] == "recovering" for x in setback_rows),
      "persistent_students": sum(x["recovery_status"] == "persistent" for x in setback_rows),
      "pending_students": sum(x["recovery_status"] == "pending_observation" for x in setback_rows)}
    grade_groups = defaultdict(list); major_groups = defaultdict(list)
    for row in all_rows:
        grade_groups[row["entry_grade"]].append(row)
        major_groups[(row["organization_id"], row["major_code"], row["major_name"])].append(row)
    by_grade = [{"entry_grade": grade, "eligible_students": len(rows),
      "setback_students": sum(x["first_year_failures"] > 0 for x in rows),
      "persistent_students": sum(x["recovery_status"] == "persistent" for x in rows),
      "improved_students": sum(x["recovery_status"] == "recovered" for x in rows)}
      for grade, rows in sorted(grade_groups.items())]
    by_major = [{"organization_id": org, "major_code": code, "major_name": name,
      "eligible_students": len(rows), "setback_students": sum(x["first_year_failures"] > 0 for x in rows),
      "persistent_students": sum(x["recovery_status"] == "persistent" for x in rows),
      "improved_students": sum(x["recovery_status"] == "recovered" for x in rows)}
      for (org, code, name), rows in major_groups.items() if any(x["first_year_failures"] > 0 for x in rows)]
    by_major.sort(key=lambda x: (-x["persistent_students"], -x["setback_students"])); by_major = by_major[:12]
    courses = dbm.query(conn, f"""WITH eligible AS (SELECT s.* FROM dim_student s WHERE {where})
      SELECT g.course_id,COALESCE(MAX(g.course_name),MAX(c.name),g.course_id) course_name,
      COUNT(*) failed_attempts,COUNT(DISTINCT g.student_id) affected_students
      FROM grade_attempt g JOIN eligible e ON e.student_id=g.student_id LEFT JOIN dim_course c ON c.course_id=g.course_id
      WHERE g.is_published=1 AND g.is_void=0 AND g.is_pass=0
        AND CAST(substr(g.semester_id,1,4) AS INTEGER)=e.entry_grade AND substr(g.semester_id,-1) IN ('1','2')
      GROUP BY g.course_id ORDER BY affected_students DESC,failed_attempts DESC LIMIT 10""", tuple(params))
    eligible = summary.get("eligible_students") or 0; setback = summary.get("setback_students") or 0
    summary["setback_rate"] = round(setback * 100.0 / eligible, 2) if eligible else 0
    return ok({"summary": summary, "by_grade": by_grade, "by_major": by_major, "courses": courses,
               "students": students, "total": total, "limit": limit, "offset": offset,
               "definition": {"first_year": "观察范围：有有效入学年，且大一第一或第二学期至少有1条有效成绩的去重学生。",
                 "setback": "大一第一或第二学期至少出现1条明确未通过成绩的去重学生；比例分母为纳入观察的学生。",
                 "recovered": "后续常规学期已有成绩且未再出现未通过记录；仅表示近期结果改善，不表示原课程已经通过。",
                 "recovering": "后续仍有未通过记录，但累计门次未超过大一阶段，表示仍需观察。",
                 "persistent": "后续未通过门次超过大一阶段，表示未通过记录仍持续出现，不推断个人原因。", "pending_observation": "大一有未通过记录，但尚无后续常规学期成绩可用于判断。",
                 "management_value": "人数反映需要配置多少关注资源，比例用于发现群体集中度；课程集中提示基础课支持，专业持续人数提示学院优先核查。",
                 "number_unit": "学生指标均为去重人数；课程表“未通过记录数”允许同一学生多次出现。",
                 "boundary": "群体筛查不推断个人原因，不自动建立帮扶任务；无有效入学年或无大一常规学期成绩者不进入分母。"}})


@router.get("/topics/graduation-readiness")
def graduation_readiness_topic(organization_id: Optional[str] = None, major_code: Optional[str] = None,
                               plan_id: Optional[str] = None, readiness: Optional[str] = None,
                               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                               conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    """培养方案完成证据与毕业准备度专题；准备度不是毕业审核结论。"""
    cond, params = ["x.rule_version='growth-v1'"], []
    scope, scope_params = _student_scope(user, conn, "s")
    if scope:
        cond.append(scope); params.extend(scope_params)
    if organization_id:
        cond.append("s.organization_id=?"); params.append(organization_id)
    if major_code:
        cond.append("s.major_code=?"); params.append(major_code)
    if plan_id:
        cond.append("x.plan_id=?"); params.append(plan_id)
    where = " AND ".join(cond)
    cte = f"""WITH student_readiness AS (
      SELECT s.student_id,s.display_name,s.entry_grade,s.organization_id,s.major_code,s.major_name,s.class_code,
        x.plan_id,p.plan_name,p.version,
        COUNT(*) plan_courses,ROUND(SUM(COALESCE(pc.credits,0)),1) plan_credits,
        SUM(CASE WHEN x.completion_status IN ('passed','recognized') THEN 1 ELSE 0 END) completed_courses,
        ROUND(SUM(CASE WHEN x.completion_status IN ('passed','recognized') THEN COALESCE(pc.credits,x.earned_credits,0) ELSE 0 END),1) completed_credits,
        SUM(CASE WHEN x.requirement_type='必修' THEN 1 ELSE 0 END) required_courses,
        SUM(CASE WHEN x.requirement_type='必修' AND x.completion_status IN ('passed','recognized') THEN 1 ELSE 0 END) required_completed,
        SUM(CASE WHEN x.requirement_type='必修' AND x.completion_status='failed' THEN 1 ELSE 0 END) explicit_required_failures,
        SUM(CASE WHEN x.requirement_type='必修' AND x.completion_status IN ('not_completed','unknown')
          AND CAST(COALESCE(NULLIF(x.suggested_term,''),'99') AS INTEGER)<=8 THEN 1 ELSE 0 END) due_required_gaps,
        SUM(CASE WHEN x.completion_status='recognized' THEN 1 ELSE 0 END) recognized_courses
      FROM student_plan_course_status x JOIN dim_student s ON s.student_id=x.student_id
      LEFT JOIN curriculum_plan p ON p.plan_id=x.plan_id LEFT JOIN curriculum_plan_course pc ON pc.plan_course_id=x.plan_course_id
      WHERE {where} GROUP BY s.student_id,x.plan_id
    ), classified AS (SELECT *,ROUND(required_completed*100.0/NULLIF(required_courses,0),1) completion_rate,
      CASE WHEN explicit_required_failures>0 THEN 'action_required'
           WHEN due_required_gaps>0 THEN 'verification_required'
           ELSE 'evidence_complete' END readiness_status FROM student_readiness)
    """
    read_cond, read_params = "", []
    if readiness:
        if readiness not in {"action_required", "verification_required", "evidence_complete"}:
            raise ApiError("不支持的准备度状态", code=400, status_code=400)
        read_cond = " WHERE readiness_status=?"; read_params = [readiness]
    all_rows = dbm.query(conn, cte + "SELECT * FROM classified", tuple(params))
    filtered = [x for x in all_rows if not readiness or x["readiness_status"] == readiness]
    rank = {"action_required": 0, "verification_required": 1, "evidence_complete": 2}
    filtered.sort(key=lambda x: (rank[x["readiness_status"]], -x["explicit_required_failures"],
                                 -x["due_required_gaps"], x["completion_rate"] or 0, x["student_id"]))
    total = len(filtered); students = filtered[offset:offset + limit]
    summary = {"covered_students": len(all_rows), "plan_count": len({x["plan_id"] for x in all_rows}),
      "action_required_students": sum(x["readiness_status"] == "action_required" for x in all_rows),
      "verification_students": sum(x["readiness_status"] == "verification_required" for x in all_rows),
      "evidence_complete_students": sum(x["readiness_status"] == "evidence_complete" for x in all_rows),
      "avg_completion_rate": round(sum(x["completion_rate"] or 0 for x in all_rows) / len(all_rows), 1) if all_rows else 0,
      "explicit_required_failures": sum(x["explicit_required_failures"] for x in all_rows),
      "due_required_gaps": sum(x["due_required_gaps"] for x in all_rows)}
    major_groups = defaultdict(list)
    for row in all_rows: major_groups[(row["major_code"], row["major_name"])].append(row)
    majors = []
    for (code, name), rows in major_groups.items():
        majors.append({"major_code": code, "major_name": name, "students": len(rows),
          "avg_completion_rate": round(sum(x["completion_rate"] or 0 for x in rows) / len(rows), 1),
          "failed_students": sum(x["explicit_required_failures"] > 0 for x in rows),
          "verification_students": sum(x["due_required_gaps"] > 0 for x in rows)})
    majors.sort(key=lambda x: (-x["failed_students"], -x["verification_students"])); majors = majors[:15]
    courses = dbm.query(conn, f"""SELECT x.course_id,COALESCE(MAX(c.name),x.course_id) course_name,
      COUNT(DISTINCT CASE WHEN x.completion_status='failed' THEN x.student_id END) failed_students,
      COUNT(DISTINCT CASE WHEN x.completion_status IN ('not_completed','unknown')
        AND CAST(COALESCE(NULLIF(x.suggested_term,''),'99') AS INTEGER)<=8 THEN x.student_id END) verification_students,
      COUNT(DISTINCT s.major_code) major_count
      FROM student_plan_course_status x JOIN dim_student s ON s.student_id=x.student_id LEFT JOIN dim_course c ON c.course_id=x.course_id
      WHERE {where} AND x.requirement_type='必修' GROUP BY x.course_id
      HAVING failed_students>0 OR verification_students>0 ORDER BY failed_students DESC,verification_students DESC LIMIT 12""", tuple(params))
    return ok({"summary": summary, "majors": majors, "courses": courses,
               "students": students, "total": total, "limit": limit, "offset": offset,
               "definition": {"action_required": "至少有1门培养方案必修课存在明确未通过成绩的去重学生人数。",
                 "verification_required": "已到建议修读学期但尚无通过、认定或明确未通过记录的去重学生人数；需结合选课与认定数据核验，不称为漏选。",
                 "evidence_complete": "当前接入记录中未发现明确未通过或到期缺记录的必修课，不等同学校毕业审核通过。",
                 "completion_rate": "每名学生已有通过或认定记录的必修课占其方案必修课的比例，再按专业或全校求平均；单位为%。",
                 "number_unit": "专业表为去重学生人数；课程表为涉及该课程的去重学生人数，不是成绩条数或课程门次。",
                 "boundary": "本专题不输出能否毕业或获得学位的结论；正式结果以学校毕业审核和学位审核为准。"}})


@router.get("/topics/course-quality")
def course_quality_topic(course_id: Optional[str] = None, semester_from: Optional[str] = None,
                         semester_to: Optional[str] = None, min_sample: int = Query(30, ge=10, le=500),
                         limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    """跨学期课程结果与教学供给专题，不用于教师个人评价。"""
    cond, params = ["g.is_published=1", "g.is_void=0", "g.is_pass IS NOT NULL"], []
    if course_id: cond.append("g.course_id=?"); params.append(course_id)
    if semester_from: cond.append("g.semester_id>=?"); params.append(semester_from)
    if semester_to: cond.append("g.semester_id<=?"); params.append(semester_to)
    where = " AND ".join(cond)
    term_rows = dbm.query(conn, f"""SELECT g.course_id,COALESCE(MAX(g.course_name),MAX(c.name),g.course_id) course_name,g.semester_id,
        COUNT(*) attempts,COUNT(DISTINCT g.student_id) students,
        SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failures,
        ROUND(SUM(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) fail_rate,
        ROUND(AVG(g.score),1) avg_score,SUM(CASE WHEN g.attempt_type='retake' THEN 1 ELSE 0 END) retake_attempts
      FROM grade_attempt g LEFT JOIN dim_course c ON c.course_id=g.course_id WHERE {where}
      GROUP BY g.course_id,g.semester_id HAVING COUNT(*)>=?""", tuple(params + [min_sample]))
    groups = defaultdict(list)
    for row in term_rows: groups[row["course_id"]].append(row)
    all_courses = []
    for cid, rows in groups.items():
        attempts = sum(x["attempts"] for x in rows); failures = sum(x["failures"] for x in rows)
        rates = [x["fail_rate"] for x in rows]; retakes = sum(x["retake_attempts"] for x in rows)
        reasons = []
        if len(rows) >= 2 and all(x >= 15 for x in rates): reasons.append("persistent_high")
        if len(rows) >= 2 and max(rates) - min(rates) >= 15: reasons.append("volatile")
        if failures >= 50: reasons.append("wide_impact")
        if retakes >= 30: reasons.append("retake_pressure")
        all_courses.append({"course_id": cid, "course_name": rows[0]["course_name"], "observed_terms": len(rows),
          "attempts": attempts, "student_term_count": sum(x["students"] for x in rows), "failures": failures,
          "fail_rate": round(failures * 100.0 / attempts, 1), "min_fail_rate": min(rates), "max_fail_rate": max(rates),
          "volatility": round(max(rates) - min(rates), 1), "retake_attempts": retakes, "attention_reasons": reasons})
    attention = [x for x in all_courses if x["attention_reasons"]]
    attention.sort(key=lambda x: (-len(x["attention_reasons"]), -x["failures"], -x["fail_rate"]))
    total = len(attention); courses = attention[offset:offset + limit]
    attempts = sum(x["attempts"] for x in all_courses); failures = sum(x["failures"] for x in all_courses)
    summary = {"observed_courses": len(all_courses), "attempts": attempts, "failures": failures,
      "overall_fail_rate": round(failures * 100.0 / attempts, 1) if attempts else 0,
      "persistent_high_courses": sum("persistent_high" in x["attention_reasons"] for x in all_courses),
      "volatile_courses": sum("volatile" in x["attention_reasons"] for x in all_courses),
      "wide_impact_courses": sum("wide_impact" in x["attention_reasons"] for x in all_courses),
      "retake_attempts": sum(x["retake_attempts"] for x in all_courses)}
    semesters = dbm.query(conn, f"SELECT DISTINCT g.semester_id FROM grade_attempt g WHERE {where} ORDER BY g.semester_id", tuple(params))
    return ok({"summary": summary, "courses": courses,
               "semesters": [x["semester_id"] for x in semesters], "total": total, "limit": limit, "offset": offset,
               "definition": {"sample": f"至少有一个学期达到{min_sample}条有效成绩记录的去重课程数。",
                 "overall": "进入统计范围的未通过成绩记录数 / 有效成绩记录总数，不是有挂科经历的学生比例。",
                 "persistent_high": "至少2个可比学期且每学期未通过率均不低于15%。",
                 "volatile": "至少2个可比学期，最高与最低未通过率相差不低于15个百分点。",
                 "wide_impact": "观察期累计未通过达到50人次。", "retake_pressure": "观察期重修尝试达到30人次。",
                 "boundary": "课程结果用于发现需核查的课程与资源问题，不证明教学质量原因，不用于教师个人排名。"}})


@router.get("/topics/course-quality/{course_id}/detail")
def course_quality_detail(course_id: str, semester_from: Optional[str] = None, semester_to: Optional[str] = None,
                          conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    cond, params = ["g.course_id=?", "g.is_published=1", "g.is_void=0", "g.is_pass IS NOT NULL"], [course_id]
    if semester_from: cond.append("g.semester_id>=?"); params.append(semester_from)
    if semester_to: cond.append("g.semester_id<=?"); params.append(semester_to)
    trends = dbm.query(conn, f"""SELECT g.semester_id,COUNT(*) attempts,COUNT(DISTINCT g.student_id) students,
      SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failures,
      ROUND(SUM(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) fail_rate,
      ROUND(AVG(g.score),1) avg_score,SUM(CASE WHEN g.attempt_type='retake' THEN 1 ELSE 0 END) retake_attempts
      FROM grade_attempt g WHERE {' AND '.join(cond)} GROUP BY g.semester_id ORDER BY g.semester_id""", tuple(params))
    offerings = dbm.query(conn, """SELECT a.semester_id,a.lesson_count,a.teacher_count,a.enrolled,a.total_hours,
      ROUND(a.enrolled*1.0/NULLIF(a.lesson_count,0),1) avg_class_size FROM agg_course_offering a
      WHERE a.course_id=? ORDER BY a.semester_id DESC""", (course_id,))
    name = dbm.scalar(conn, "SELECT name FROM dim_course WHERE course_id=?", (course_id,)) or course_id
    return ok({"course_id": course_id, "course_name": name, "trends": trends, "offerings": offerings,
               "offering_boundary": "当前真实教学任务主要覆盖一个接入学期，只能展示已接入供给，不能据此判断未来是否开课或资源是否充足。"})


@router.get("/topics/faculty-resource-risk")
def faculty_resource_risk(semester: str = "2023-2024-1", limit: int = Query(100, ge=1, le=300),
                          conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    rows = dbm.query(conn, """SELECT t.*,COALESCE(c.name,t.course_id) course_name,c.organization_id,
      COALESCE(o.lesson_count,0) lesson_count,COALESCE(o.enrolled,0) enrolled
      FROM agg_course_team t LEFT JOIN dim_course c ON c.course_id=t.course_id
      LEFT JOIN agg_course_offering o ON o.semester_id=t.semester_id AND o.course_id=t.course_id
      WHERE t.semester_id=?""", (semester,))
    for x in rows:
        reasons=[]
        if x["teacher_count"] == 1: reasons.append("single_teacher")
        if x["unknown_title_count"] > 0: reasons.append("title_incomplete")
        known=x["teacher_count"]-x["unknown_title_count"]
        if known>0 and x["professor_count"]+x["associate_professor_count"]==0: reasons.append("no_senior_title")
        x["attention_reasons"]=reasons; x["known_title_count"]=known
    attention=[x for x in rows if x["attention_reasons"]]
    attention.sort(key=lambda x:("single_teacher" not in x["attention_reasons"],-x["enrolled"],x["course_id"]))
    return ok({"semester":semester,"summary":{"courses":len(rows),"single_teacher_courses":sum(x["teacher_count"]==1 for x in rows),
      "title_incomplete_courses":sum(x["unknown_title_count"]>0 for x in rows),
      "no_senior_title_courses":sum("no_senior_title" in x["attention_reasons"] for x in rows),
      "teachers":dbm.scalar(conn,"SELECT COUNT(DISTINCT staff_id) FROM lesson_teacher lt JOIN teaching_lesson l ON l.lesson_id=lt.lesson_id WHERE l.semester_id=?",(semester,)) or 0},
      "courses":attention[:limit],"definition":{"single_teacher":"该学期该课程只有1名实际授课教师，表示当期教学任务单点承担，不等于长期人才断层。",
      "title_incomplete":"团队至少1名教师缺少可用职称，不能据此形成完整职称梯队结论。","no_senior_title":"职称已知成员中未见教授或副教授，仅作为团队结构核查线索。",
      "boundary":"当前仅有一个真实教学任务学期；年龄没有真实数据，因此不判断年龄断层，不评价教师个人能力。"}})


@router.get("/students/{student_id}/growth")
def student_growth(student_id: str, timeline_limit: int = Query(100, ge=1, le=500),
                   conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    _assert_student_access(student_id, user, conn)
    student = dbm.query_one(conn, """SELECT s.*,p.plan_name FROM dim_student s
        LEFT JOIN curriculum_plan p ON p.plan_id=s.plan_id WHERE s.student_id=?""", (student_id,))
    if not student:
        raise ApiError("学生不存在", code=404, status_code=404)
    indicator = dbm.query_one(conn, "SELECT * FROM student_growth_indicator WHERE student_id=? AND indicator_version='growth-v1'", (student_id,))
    flags = dbm.query(conn, "SELECT flag_code,severity,evidence_count,evidence_json FROM student_difficulty_flag WHERE student_id=? AND flag_version='growth-v1' ORDER BY severity DESC,flag_code", (student_id,))
    timeline = dbm.query(conn, "SELECT event_type,event_date,semester_id,title,detail_json,source_ref,source FROM student_timeline_event WHERE student_id=? ORDER BY COALESCE(event_date,semester_id) DESC LIMIT ?", (student_id, timeline_limit))
    graduation = dbm.query(conn, "SELECT graduation_status,degree_status,graduation_date,education_level FROM graduation_outcome WHERE student_id=? ORDER BY graduation_date DESC", (student_id,))
    return ok({"student": student, "indicator": indicator, "flags": flags,
               "timeline": timeline, "graduation": graduation})


@router.get("/students/{student_id}/plan-courses")
def student_plan_courses(student_id: str, status: Optional[str] = None,
                         actionable: Optional[bool] = None,
                         limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                         conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_reader)):
    _assert_student_access(student_id, user, conn)
    cond, params = ["x.student_id=?", "x.rule_version='growth-v1'"], [student_id]
    if status:
        cond.append("x.completion_status=?"); params.append(status)
    if actionable is not None:
        cond.append("x.is_actionable=?"); params.append(int(actionable))
    where = " AND ".join(cond)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM student_plan_course_status x WHERE {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT x.course_id,COALESCE(c.name,pc.course_id) course_name,x.module,x.requirement_type,
        x.suggested_term,x.completion_status,x.is_actionable,x.is_overdue,x.effective_score,x.earned_credits
        FROM student_plan_course_status x LEFT JOIN dim_course c ON c.course_id=x.course_id
        LEFT JOIN curriculum_plan_course pc ON pc.plan_course_id=x.plan_course_id
        WHERE {where} ORDER BY x.is_actionable DESC,x.is_overdue DESC,x.suggested_term,x.course_id LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset]))
    return ok({"items": rows, "total": total, "limit": limit, "offset": offset,
               "wording": "not_completed表示截至当前成绩和认定记录尚无完成证据，不等同于漏选"})


@router.get("/students/{student_id}/advice")
def student_advice(student_id: str, conn: sqlite3.Connection = Depends(get_v2_db),
                   user: dict = Depends(require_v2_reader)):
    """确定性建议证据包；不调用大模型，不产生毕业结论或心理推断。"""
    _assert_student_access(student_id, user, conn)
    student = dbm.query_one(conn, "SELECT student_id,display_name,entry_grade,major_code,class_code,student_status FROM dim_student WHERE student_id=?", (student_id,)) or {}
    indicator = dbm.query_one(conn, "SELECT * FROM student_growth_indicator WHERE student_id=? AND indicator_version='growth-v1'", (student_id,)) or {}
    audiences = ["student", "counselor", "class_adviser", "college", "academic_affairs"]
    cards = []

    actionable = dbm.query(conn, """SELECT x.course_id,COALESCE(c.name,x.course_id) course_name,x.effective_score
        FROM student_plan_course_status x LEFT JOIN dim_course c ON c.course_id=x.course_id
        WHERE x.student_id=? AND x.is_actionable=1 ORDER BY x.is_overdue DESC,x.suggested_term LIMIT 5""", (student_id,))
    for row in actionable:
        course = row["course_name"]
        cards.append({"advice_id": f"ADV-PLAN-FAILED-REQUIRED:{row['course_id']}", "priority": "high", "topic": "培养方案",
            "title": f"优先核对《{course}》后续修读安排",
            "evidence": f"培养方案课程存在明确未通过记录，有效成绩为{row['effective_score'] if row['effective_score'] is not None else '未记录'}",
            "evidence_ids": [f"plan-course:{row['course_id']}"], "confidence": "high",
            "messages": {"student": "建议尽早核对下一次开课或重修安排，并确认该课程是否影响后续课程衔接。",
                "counselor": "建议确认学生是否了解该必修课程状态，并持续关注后续修读安排。",
                "class_adviser": "建议关注该课程对应的专业基础及后续课程衔接，必要时提供学习指导。",
                "college": "建议核查该课程重修或跟班修读资源，并关注同类学生规模。",
                "academic_affairs": "建议关注该课程跨学院开课与重修资源；正式安排以教务系统为准。"},
            "verification": "当前数据未包含完整重修班容量与报名条件"})

    semester_gpa = dbm.query(conn, """SELECT semester_id,AVG(gpa) gpa FROM grade_attempt
        WHERE student_id=? AND is_void=0 AND gpa IS NOT NULL GROUP BY semester_id ORDER BY semester_id DESC LIMIT 2""", (student_id,))
    if len(semester_gpa) == 2:
        delta = (semester_gpa[0]["gpa"] or 0) - (semester_gpa[1]["gpa"] or 0)
        if abs(delta) >= 0.3:
            improved = delta > 0
            cards.append({"advice_id": "ADV-GPA-RECOVERY" if improved else "ADV-GPA-DECLINE",
                "priority": "positive" if improved else "medium", "topic": "积极进展" if improved else "成绩趋势",
                "title": "近期 GPA 有明显改善" if improved else "近期 GPA 出现下降",
                "evidence": f"{semester_gpa[1]['semester_id']}至{semester_gpa[0]['semester_id']}平均绩点变化{delta:+.2f}",
                "evidence_ids": [f"semester:{semester_gpa[1]['semester_id']}", f"semester:{semester_gpa[0]['semester_id']}"], "confidence": "high",
                "messages": {a: ("近期学习结果出现改善，建议保持有效的学习节奏，并继续关注尚未解决的课程。" if improved else
                    {"student": "建议回顾近期低分课程和学习负荷，优先安排基础薄弱课程的学习时间。",
                     "counselor": "建议关注下降是否持续，并结合课程负荷和学籍背景与学生核实。",
                     "class_adviser": "建议分析下降是否集中在专业基础课程，提供课程衔接建议。",
                     "college": "建议结合该专业同年级情况判断是否存在共性困难课程。",
                     "academic_affairs": "建议仅在形成跨学院共性时进入校级课程资源分析。"}[a]) for a in audiences},
                "verification": "GPA变化为结果事实，不用于推断具体原因"})

    latest_semester = dbm.scalar(conn, "SELECT MAX(semester_id) FROM grade_attempt WHERE student_id=? AND is_void=0", (student_id,))
    if latest_semester:
        difficult = dbm.query(conn, """WITH history AS (
            SELECT course_id,COUNT(*) attempts,SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) failures
            FROM grade_attempt WHERE is_void=0 AND semester_id<? AND is_pass IS NOT NULL GROUP BY course_id
            HAVING COUNT(*)>=30 AND SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END)*1.0/COUNT(*)>=0.15)
            SELECT DISTINCT a.course_id,COALESCE(a.course_name,c.name,a.course_id) course_name,h.attempts,h.failures
            FROM grade_attempt a JOIN history h ON h.course_id=a.course_id LEFT JOIN dim_course c ON c.course_id=a.course_id
            WHERE a.student_id=? AND a.semester_id=? AND a.is_void=0 LIMIT 5""", (latest_semester, student_id, latest_semester))
        for row in difficult:
            rate = round(row["failures"] * 100.0 / row["attempts"], 1); course = row["course_name"]
            cards.append({"advice_id": f"ADV-HIGH-FAIL-COURSE:{row['course_id']}", "priority": "medium", "topic": "课程难度",
                "title": f"关注《{course}》的历史学习难度", "confidence": "medium",
                "evidence": f"最近修读记录为{latest_semester}；此前历史样本{row['attempts']}人次，未通过率{rate}%",
                "evidence_ids": [f"recent-course:{latest_semester}:{row['course_id']}", f"course-history:{row['course_id']}"],
                "messages": {"student": "该课程历史未通过率相对较高，建议尽早安排学习时间、复习先修知识并关注课程答疑资源。",
                    "counselor": "建议关注学生是否同时修读多门历史高难度课程，避免学习负荷过度集中。",
                    "class_adviser": "建议关注先修知识和专业课程衔接，为学生提供针对性的学习指导。",
                    "college": "建议核查该课程答疑、助教、课程团队和重修资源是否充足。",
                    "academic_affairs": "建议关注该课程是否形成跨专业、跨学院的共同学习压力。"},
                "verification": "历史群体结果不预测个人结果；原型缺当前选课状态，仅按最近学期修读记录提示"})

    order = {"high": 0, "medium": 1, "positive": 2}; cards.sort(key=lambda x: (order.get(x["priority"], 9), x["advice_id"]))
    return ok({"student": student, "indicator": indicator, "cards": cards[:12], "audiences": audiences,
        "generated_by": "deterministic-template-v1", "ai_enabled": False,
        "wording": "建议基于确定性证据生成；尚无完成证据不等同漏选，历史课程难度不预测个人结果"})


@router.get("/courses/offerings")
def course_offerings(semester: str = "2023-2024-1", category: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                     conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    cond, params = ["a.semester_id=?"], [semester]
    if category:
        cond.append("c.category=?"); params.append(category)
    where = " AND ".join(cond)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM agg_course_offering a LEFT JOIN dim_course c ON c.course_id=a.course_id WHERE {where}", tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT a.*,c.name course_name,c.category,c.nature,c.organization_id
        FROM agg_course_offering a LEFT JOIN dim_course c ON c.course_id=a.course_id WHERE {where}
        ORDER BY a.lesson_count DESC,a.enrolled DESC LIMIT ? OFFSET ?""", tuple(params + [limit, offset]))
    return ok({"items": rows, "total": total, "semester": semester})


@router.get("/courses/schedule-distribution")
def course_schedule_distribution(semester: str = "2023-2024-1", focus: str = Query("all", pattern="^(all|pe|politics)$"),
                                 conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    conditions = ["l.semester_id=?"]
    params: list = [semester]
    if focus == "pe":
        conditions.append("(COALESCE(c.category,'') LIKE '%体育%' OR COALESCE(c.nature,'') LIKE '%体育%' OR COALESCE(c.name,l.course_name,'') LIKE '%体育%')")
    elif focus == "politics":
        conditions.append("(COALESCE(c.category,'') LIKE '%思政%' OR COALESCE(c.nature,'') LIKE '%思政%' OR COALESCE(c.name,l.course_name,'') LIKE '%思想政治%' OR COALESCE(c.name,l.course_name,'') LIKE '%马克思%' OR COALESCE(c.name,l.course_name,'') LIKE '%毛泽东%')")
    where = " AND ".join(conditions)
    cells = dbm.query(conn, f"""SELECT m.weekday,
        CASE WHEN m.period_start<=4 THEN 'morning' WHEN m.period_start<=8 THEN 'afternoon' ELSE 'evening' END day_part,
        COUNT(DISTINCT m.meeting_id) meeting_count,COUNT(DISTINCT l.course_id) course_count,
        COUNT(DISTINCT l.lesson_id) lesson_count
        FROM course_meeting m JOIN teaching_lesson l ON l.lesson_id=m.lesson_id
        LEFT JOIN dim_course c ON c.course_id=l.course_id WHERE {where}
        GROUP BY m.weekday,CASE WHEN m.period_start<=4 THEN 'morning' WHEN m.period_start<=8 THEN 'afternoon' ELSE 'evening' END
        ORDER BY m.weekday,day_part""", tuple(params))
    return ok({"semester": semester, "focus": focus, "cells": cells,
               "classification": "体育/思政专项按课程类别、性质与课程名称关键词识别，生产系统应由课程标签主数据替代"})


@router.get("/courses/{course_id}/team")
def course_team(course_id: str, semester: str = "2023-2024-1",
                conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    summary = dbm.query_one(conn, "SELECT * FROM agg_course_team WHERE semester_id=? AND course_id=?", (semester, course_id))
    if not summary:
        raise ApiError("暂无课程团队数据", code=404, status_code=404)
    members = dbm.query(conn, """SELECT DISTINCT s.staff_id,s.display_name,s.title,s.organization_id,s.source
        FROM teaching_lesson l JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id WHERE l.semester_id=? AND l.course_id=? ORDER BY s.title,s.staff_id""", (semester, course_id))
    return ok({"summary": summary, "members": members})


@router.get("/teachers/{staff_id}/schedule-preference")
def teacher_preference(staff_id: str, semester: str = "2023-2024-1",
                       conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    teacher = dbm.query_one(conn, "SELECT staff_id,display_name,title,organization_id,source FROM dim_staff WHERE staff_id=?", (staff_id,))
    if not teacher:
        raise ApiError("教师不存在", code=404, status_code=404)
    cells = dbm.query(conn, "SELECT weekday,day_part,meeting_count,course_count FROM agg_teacher_schedule_preference WHERE semester_id=? AND staff_id=? ORDER BY weekday,day_part", (semester, staff_id))
    return ok({"teacher": teacher, "semester": semester, "cells": cells,
               "scope": "历史实际排课分布，不是教师主动填报偏好"})


@router.get("/rooms/summary")
def room_summary(conn: sqlite3.Connection = Depends(get_v2_db), user: dict = Depends(require_v2_all_reader)):
    totals = dbm.query_one(conn, """SELECT COUNT(*) total_rooms,SUM(is_available) marked_available,
        SUM(CASE WHEN is_available=1 AND is_virtual=0 AND seats>0 THEN 1 ELSE 0 END) usable_rooms,
        SUM(CASE WHEN is_available=1 AND is_virtual=0 AND seats>0 THEN seats ELSE 0 END) usable_seats FROM dim_room""")
    buildings = dbm.query(conn, """SELECT COALESCE(b.name,'待映射楼宇') building,COUNT(*) total_rooms,
        SUM(CASE WHEN r.is_available=1 AND r.is_virtual=0 AND r.seats>0 THEN 1 ELSE 0 END) usable_rooms,
        SUM(CASE WHEN r.is_available=1 AND r.is_virtual=0 AND r.seats>0 THEN r.seats ELSE 0 END) usable_seats
        FROM dim_room r LEFT JOIN dim_building b ON b.building_id=r.building_id GROUP BY COALESCE(b.name,'待映射楼宇') ORDER BY usable_rooms DESC""")
    return ok({"summary": totals, "buildings": buildings,
               "denominator": "可用、非虚拟、座位数大于0；可用数量由上游主数据提供，本系统只消费和分析"})
