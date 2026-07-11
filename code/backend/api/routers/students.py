"""学生学业分析组：GPA 群体聚类 / 年级 GPA / 学分完成 / 挂科集中课程。
全部算自真实成绩 fact_grade + 预警 fact_alert + 合成毕业 fact_graduation。
支持维度过滤：semester(学期) / grade(年级) / college(学院码)，无值=全量。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope
from ..envelope import ok

router = APIRouter(prefix="/api/admin/students", tags=["students"])


@router.get("/analysis")
def analysis(semester: Optional[str] = None, grade: Optional[str] = None,
             college: Optional[str] = None, major: Optional[str] = None,
             class_id: Optional[str] = None, retake: Optional[str] = None,
             required: Optional[str] = None, year: Optional[str] = None,
             user: dict = Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_db)):
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
    scope_frag, scope_sp = student_data_scope(user, conn)
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

    # 每生平均绩点
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
    gpa_sql = f"SELECT student_id, AVG(gpa) g FROM fact_grade WHERE {' AND '.join(gw)}{stu_sub} GROUP BY student_id"
    stu_gpa = {r["student_id"]: r["g"] for r in dbm.query(conn, gpa_sql, tuple(gp + sparams))}
    gpa_vals = list(stu_gpa.values())
    gpa_avg = round(sum(gpa_vals) / len(gpa_vals), 2) if gpa_vals else 0

    # 挂科率（真实）
    fw, fpms = _grade_clauses("g")
    rtot = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_grade g WHERE g.source='real' AND g.is_pass IS NOT NULL{fw}", tuple(fpms)) or 0
    rfail = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_grade g WHERE g.source='real' AND g.is_pass=0{fw}", tuple(fpms)) or 0
    fail_rate = round(rfail / rtot * 100, 1) if rtot else 0
    alert_stu = dbm.scalar(conn, f"SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a WHERE COALESCE(a.is_active,1)=1"
                           + (f" AND a.student_id IN (SELECT student_id FROM dim_student WHERE {' AND '.join(scond)})" if scond else ""),
                           tuple(sparams)) or 0
    alert_rate = round(alert_stu / total_stu * 100, 1) if total_stu else 0
    # 毕业/学位（fact_graduation 自带 college_id/grade）
    gradcond, gradp = [], []
    if college:
        gradcond.append("college_id=?"); gradp.append(college)
    if grade:
        gradcond.append("grade=?"); gradp.append(grade)
    if major:
        gradcond.append("major_id=?"); gradp.append(major)
    gradw = (" WHERE " + " AND ".join(gradcond)) if gradcond else ""
    grad_rate = dbm.scalar(conn, f"SELECT AVG(graduated) FROM fact_graduation{gradw}", tuple(gradp)) or 0
    degree_rate = dbm.scalar(conn, f"SELECT AVG(degree) FROM fact_graduation{gradw}", tuple(gradp)) or 0

    studentKpis = [
        {"label": "在籍学生", "value": f"{total_stu:,}", "color": "#1E3A5F",
         "formula": "在籍本科生总数 COUNT(学籍)"},
        {"label": "全校GPA均值", "value": str(gpa_avg), "color": "#2563EB",
         "formula": "AVG(每生平均绩点)·5分制"},
        {"label": "挂科率", "value": f"{fail_rate}%", "color": "#DC2626",
         "formula": "不及格人次÷总修读人次（真实）"},
        {"label": "预警率", "value": f"{alert_rate}%", "color": "#EA580C",
         "formula": "预警学生÷在籍学生"},
        {"label": "毕业率", "value": f"{round(grad_rate * 100, 1)}%", "color": "#16A34A",
         "formula": "按期毕业÷应届总人数"},
        {"label": "学位授予率", "value": f"{round(degree_rate * 100, 1)}%", "color": "#1E3A5F",
         "formula": "获学位÷应届总人数"},
    ]

    # 群体聚类（GPA 5 档）
    buckets = [("优秀", 3.5, 99, "#16A34A", "≥3.5"), ("良好", 3.0, 3.5, "#2563EB", "3.0-3.5"),
               ("一般", 2.5, 3.0, "#EA580C", "2.5-3.0"), ("困难", 2.0, 2.5, "#DC2626", "2.0-2.5"),
               ("高危", -1, 2.0, "#991B1B", "<2.0")]
    n_gpa = len(gpa_vals) or 1
    clusters = []
    for label, lo, hi, color, rng in buckets:
        c = sum(1 for g in gpa_vals if lo <= g < hi)
        clusters.append({"label": label, "count": c, "pct": round(c / n_gpa * 100),
                         "color": color, "gpa": rng})

    # 各年级 GPA（含挂科率/预警率）。年级过滤时仅该年级一行；学院过滤收口到本院学生。
    gradeGpa = []
    for r in dbm.query(conn, f"SELECT grade, COUNT(*) n FROM dim_student{swhere} GROUP BY grade ORDER BY grade DESC", tuple(sparams)):
        gr = r["grade"]
        # 该年级（叠加学院过滤）的学生集合子查询
        gsc = ["grade=?"]
        gsp = [gr]
        if college:
            gsc.append("college_id=?"); gsp.append(college)
        if major:
            gsc.append("major_id=?"); gsp.append(major)
        if class_id:
            gsc.append("class_id=?"); gsp.append(class_id)
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
    # 已修=该生通过课程累计学分（fact_grade.is_pass=1，不随学期过滤，取全部历史）；
    # 应修=该生 (专业,年级) 在 fact_major_req 的 total_req。req 缺失则跳过该生（不计分母）。
    # 受学院/年级/专业/班级过滤（scond）限定参与统计的学生集合。
    cbuckets = [(">90%", 0.9, 9, "#16A34A"), ("80-90%", 0.8, 0.9, "#2563EB"),
                ("60-80%", 0.6, 0.8, "#EA580C"), ("<60%", -1, 0.6, "#DC2626")]
    req_map = {(r["major_id"], r["grade"]): r["total_req"]
               for r in dbm.query(conn, "SELECT major_id, grade, total_req FROM fact_major_req WHERE total_req>0")}
    earned_map = {r["student_id"]: r["e"] for r in dbm.query(conn, """
        SELECT student_id, SUM(credits) e FROM fact_grade
        WHERE is_pass=1 GROUP BY student_id""")}
    ratios = []
    for s in dbm.query(conn, f"SELECT student_id, major_id, grade FROM dim_student{swhere}", tuple(sparams)):
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
    # 课程级首次/最终通过率（取自 agg_course_term）
    cr_map = {}
    for cr in dbm.query(conn,
        "SELECT course_id, first_pass_rate, final_pass_rate FROM agg_course_term "
        "WHERE first_pass_rate IS NOT NULL GROUP BY course_id"):
        cr_map[cr["course_id"]] = (cr["first_pass_rate"], cr["final_pass_rate"])
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
        failCourses.append({
            "id": r["course_id"], "name": r["cname"] or r["course_id"],
            "dept": r["dept"] or "—", "failRate": fr, "failCount": r["fc"],
            "totalCount": r["total"],
            "avgScore": round(r["av"], 1) if r["av"] is not None else "—",
            "firstPassRate": round((fpr or 0) * 100, 1),
            "finalPassRate": round((lpr or 0) * 100, 1),
        })

    return ok({"studentKpis": studentKpis, "clusters": clusters,
               "gradeGpa": gradeGpa, "creditDist": creditDist,
               "failCourses": failCourses})


@router.get("/list")
def student_list(semester: Optional[str] = None, grade: Optional[str] = None,
                  college: Optional[str] = None, major: Optional[str] = None,
                  class_id: Optional[str] = None, retake: Optional[str] = None,
                  required: Optional[str] = None, year: Optional[str] = None,
                  course: Optional[str] = None,
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
    scope_frag2, scope_sp2 = student_data_scope(user, conn)
    if scope_frag2:
        scond.append(scope_frag2); sparams += scope_sp2
    if keyword:
        kw = f"%{keyword}%"
        scond.append("(student_id LIKE ? OR name LIKE ?)")
        sparams += [kw, kw]
    if course:
        scond.append("student_id IN (SELECT DISTINCT student_id FROM fact_grade WHERE course_id=?)")
        sparams.append(course)
    swhere = (" WHERE " + " AND ".join(scond)) if scond else ""

    # 学期过滤
    sem_ids = None
    if semester:
        sem_ids = [semester]
    elif year:
        sem_ids = [r["semester_id"] for r in dbm.query(
            conn, "SELECT semester_id FROM dim_semester WHERE year=?", (year,))]

    def _sem_cond(alias="g"):
        if not sem_ids:
            return "", []
        ph = ",".join("?" * len(sem_ids))
        return f" AND {alias}.semester_id IN ({ph})", list(sem_ids)

    # 学生 GPA
    gw = ["gpa IS NOT NULL"]
    gsem, gsemp = _sem_cond()
    if gsem:
        gw.append(gsem[5:])
    stu_sub = ""
    if scond:
        stu_sub = (" AND student_id IN (SELECT student_id FROM dim_student WHERE "
                   + " AND ".join(scond) + ")")
    gw.append("1=1")  # ensures at least one condition before stu_sub
    gpa_sql = f"SELECT student_id, AVG(gpa) g FROM fact_grade WHERE {' AND '.join(gw)}{stu_sub} GROUP BY student_id"
    stu_gpa = {r["student_id"]: r["g"] for r in dbm.query(conn, gpa_sql, tuple(gsemp + sparams))}

    # 挂科数
    fail_sql = f"""SELECT student_id, COUNT(*) fc FROM fact_grade
        WHERE source='real' AND is_pass=0{gsem}{stu_sub} GROUP BY student_id"""
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

    # 分页
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM dim_student{swhere}", tuple(sparams)) or 0
    offset = (page - 1) * page_size
    students = []
    # 动态排序
    order_col = "student_id"
    order_dir = "ASC" if (order or "asc") == "asc" else "DESC"
    if sort == "gpa":
        # 按 GPA 排序：将 GPA 映射值作为排序依据（NULL 排最后）
        gpa_order_case = "CASE WHEN student_id IN ({}) THEN 1 ELSE 0 END".format(
            ",".join(f"'{sid}'" for sid in stu_gpa.keys()) if stu_gpa else "''")
        order_col = f"COALESCE((SELECT AVG(gpa) FROM fact_grade fg WHERE fg.student_id=dim_student.student_id AND fg.gpa IS NOT NULL), -1)"
    for s in dbm.query(conn, f"""
        SELECT s.*, m.name AS major_name, c.name AS class_name
        FROM (SELECT student_id, name, college_id, major_id, class_id, grade, status
              FROM dim_student{swhere}
              ORDER BY {order_col} {order_dir}
              LIMIT ? OFFSET ?) s
        LEFT JOIN dim_major m ON s.major_id = m.major_id
        LEFT JOIN dim_class c ON s.class_id = c.class_id""", tuple(sparams + [page_size, offset])):
        sid = s["student_id"]
        gpa = stu_gpa.get(sid)
        students.append({
            "sid": sid, "name": s["name"] or sid, "college": cname.get(s["college_id"], s["college_id"]),
            "major": s["major_id"], "majorName": s["major_name"] or "",
            "class": s["class_id"] or "—", "className": s["class_name"] or "",
            "grade": (s["grade"] or "") + ("级" if s["grade"] else ""),
            "gpa": round(gpa, 2) if gpa else None,
            "failCount": stu_fail.get(sid, 0),
            "alertLevel": stu_alert_levels.get(sid, "—"),
        })

    return ok({"total": total, "page": page, "pageSize": page_size, "students": students})
