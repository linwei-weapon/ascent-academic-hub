"""预聚合 agg_*：从 真实+模拟 的 grade/lesson/alert 事实算看板用聚合表。
原则：可算的全真算；缺调度维度的(教室热力)按楼宇均值做最小化确定性铺底。
- 学期级 source：semester==SIM → 'sim'，否则 'real'。
- credit_done = 通过学分 / 修读学分（比例代理，规避培养方案依赖）。
"""
import numpy as np
import pandas as pd

from . import config

# GPA 4分制分桶（0.5步长，与dashboard.py _GPA_BANDS对齐）
_BUCKETS = [("3.5-4.0", 3.5), ("3.0-3.5", 3.0), ("2.5-3.0", 2.5),
            ("2.0-2.5", 2.0), ("<2.0", 0.0)]
_PERIODS = ["p12", "p34", "p56", "p78"]


def _src(sem: str) -> str:
    # 时间序列改造后 9 学期全为真实数据
    return "real"


def _bucket(gpa: float) -> str:
    for name, lo in _BUCKETS:
        if gpa >= lo:
            return name
    return "<2.0"


def agg_college_term(grade, dim_student, alert):
    smajor = dim_student.set_index("student_id")[["college_id"]]
    g = grade.merge(smajor, on="student_id", how="left")
    rows = []
    # 预警学生集合（按 college, semester）
    al = alert.merge(smajor, on="student_id", how="left") if len(alert) else None
    for (cid, sem), grp in g.groupby(["college_id", "semester_id"]):
        if pd.isna(cid):
            continue
        students = grp["student_id"].nunique()
        cr_tot = grp["credits"].sum()
        cr_done = grp.loc[grp["is_pass"] == 1, "credits"].sum()
        a_stu = 0
        if al is not None and len(al):
            a_stu = al[(al["college_id"] == cid) & (al["semester_id"] == sem)]["student_id"].nunique()
        rows.append({
            "college_id": cid, "semester_id": sem, "students": int(students),
            "avg_score": round(grp["score"].mean(), 2),
            "fail_rate": round((grp["is_pass"] == 0).mean(), 4),
            "gpa_avg": round(grp["gpa"].dropna().mean(), 3) if grp["gpa"].notna().any() else None,
            "alert_rate": round(a_stu / students, 4) if students else 0.0,
            "credit_done": round(cr_done / cr_tot, 4) if cr_tot else None,
            "source": _src(sem),
        })
    return pd.DataFrame(rows)


def agg_major_term(grade, dim_student, alert):
    sinfo = dim_student.set_index("student_id")[["major_id", "grade"]]
    g = grade.merge(sinfo, on="student_id", how="left")
    al = alert.merge(sinfo, on="student_id", how="left") if len(alert) else None
    rows = []
    for (mid, sem, grade_yr), grp in g.groupby(["major_id", "semester_id", "grade"]):
        if pd.isna(mid):
            continue
        cr_tot = grp["credits"].sum()
        cr_done = grp.loc[grp["is_pass"] == 1, "credits"].sum()
        acnt = 0
        if al is not None and len(al):
            acnt = len(al[(al["major_id"] == mid) & (al["semester_id"] == sem) & (al["grade"] == grade_yr)])
        rows.append({
            "major_id": mid, "semester_id": sem, "grade": grade_yr,
            "students": int(grp["student_id"].nunique()),
            "avg_score": round(grp["score"].mean(), 2),
            "fail_rate": round((grp["is_pass"] == 0).mean(), 4),
            "gpa_avg": round(grp["gpa"].dropna().mean(), 3) if grp["gpa"].notna().any() else None,
            "alert_count": int(acnt),
            "credit_done": round(cr_done / cr_tot, 4) if cr_tot else None,
            "source": _src(sem),
        })
    return pd.DataFrame(rows)


def agg_course_term(grade):
    # ---------- 课程级首次/最终通过率（跨学期，每 (学生,课程) 分组） ----------
    sg = grade.dropna(subset=["is_pass", "semester_id"]).copy()
    course_rates: dict[str, tuple[float | None, float | None]] = {}
    if len(sg):
        # 每 (student, course) 首次尝试
        first_idx = sg.groupby(["student_id", "course_id"])["semester_id"].idxmin()
        first = sg.loc[first_idx]
        fp_agg = first.groupby("course_id").agg(
            first_pass_cnt=("is_pass", lambda x: (x == 1).sum()),
            first_total=("student_id", "count"),
        )
        # 每 (student, course) 末次尝试
        last_idx = sg.groupby(["student_id", "course_id"])["semester_id"].idxmax()
        last = sg.loc[last_idx]
        lp_agg = last.groupby("course_id").agg(
            final_pass_cnt=("is_pass", lambda x: (x == 1).sum()),
            final_total=("student_id", "count"),
        )
        all_cids = set(fp_agg.index) | set(lp_agg.index)
        for cid in all_cids:
            fp = fp_agg.loc[cid] if cid in fp_agg.index else None
            lp = lp_agg.loc[cid] if cid in lp_agg.index else None
            fpr = round(float(fp["first_pass_cnt"]) / float(fp["first_total"]), 4) if fp is not None and fp["first_total"] > 0 else None
            lpr = round(float(lp["final_pass_cnt"]) / float(lp["final_total"]), 4) if lp is not None and lp["final_total"] > 0 else None
            course_rates[cid] = (fpr, lpr)

    # ---------- 按学期构建 agg_course_term，注入课程级通过率 ----------
    rows = []
    for (cid, sem), grp in grade.groupby(["course_id", "semester_id"]):
        if pd.isna(cid):
            continue
        fpr, lpr = course_rates.get(cid, (None, None))
        rows.append({
            "course_id": cid, "semester_id": sem,
            "avg_score": round(grp["score"].mean(), 2),
            "fail_rate": round((grp["is_pass"] == 0).mean(), 4),
            "total": int(len(grp)),
            "excellent_rate": round((grp["score"] >= 90).mean(), 4),
            "retake_rate": round((grp["is_retake"] == 1).mean(), 4),
            "first_pass_rate": fpr,
            "final_pass_rate": lpr,
            "source": _src(sem),
        })
    return pd.DataFrame(rows)


def agg_gpa_dist(grade, dim_student):
    """按学生-学期均绩点分桶；scope=all(ALL) 与 scope=college。"""
    smajor = dim_student.set_index("student_id")[["college_id"]]
    g = grade.dropna(subset=["gpa"]).merge(smajor, on="student_id", how="left")
    stu_term = (g.groupby(["student_id", "semester_id", "college_id"])["gpa"]
                .mean().reset_index())
    stu_term["bucket"] = stu_term["gpa"].map(_bucket)
    rows = []

    def emit(scope_type, scope_id, sub):
        sem = sub["semester_id"].iloc[0]
        tot = len(sub)
        vc = sub["bucket"].value_counts().to_dict()
        for name, _ in _BUCKETS:
            c = int(vc.get(name, 0))
            rows.append({
                "scope_type": scope_type, "scope_id": scope_id, "semester_id": sem,
                "bucket": name, "count": c,
                "percent": round(c / tot, 4) if tot else 0.0, "source": _src(sem),
            })

    for sem, sub in stu_term.groupby("semester_id"):
        emit("all", "ALL", sub)
    for (cid, sem), sub in stu_term.groupby(["college_id", "semester_id"]):
        if pd.isna(cid):
            continue
        emit("college", cid, sub)
    return pd.DataFrame(rows)


def agg_teacher_load(lesson, dim_teacher):
    title = dim_teacher.set_index("teacher_id")["title"].to_dict()
    rows = []
    for (tid, sem), grp in lesson.groupby(["teacher_id", "semester_id"]):
        if pd.isna(tid):
            continue
        rows.append({
            "teacher_id": tid, "semester_id": sem, "title": title.get(tid),
            "hours": round(grp["total_hours"].fillna(0).sum(), 1),
            "courses": int(grp["course_id"].nunique()),
            "classes": int(len(grp)),
            "source": _src(sem),
        })
    return pd.DataFrame(rows)


# 楼宇规范化：真实 classroom 串含"三教咨询任课教师"等脏尾，归并到干净楼栋名
_BUILDINGS = ["三教", "四教", "五教", "东教", "主楼B座", "主楼", "理学楼A座", "理学楼",
              "中油大厦", "润杰公寓", "体育教学场地", "红旗操场",
              "北校园", "南校园", "东校园"]


def _building(classroom):
    """从教室名规范化楼栋（'三教502机房'→'三教'、'三教咨询任课教师'→'三教'）。"""
    s = str(classroom or "").strip()
    if not s or s.lower() == "nan":
        return None
    for b in _BUILDINGS:
        if s.startswith(b):
            return b
    import re
    m = re.match(r"^([\u4e00-\u9fa5A-Za-z]{1,4}[教楼])", s)
    return m.group(1) if m else (s[:3] or None)


def _room_type(classroom):
    """按教室名关键词判定类型：多媒体/机房·实验室·体育场地·普通教室。"""
    s = str(classroom or "")
    if any(k in s for k in ("机房", "网络", "线上", "教学平台")):
        return "多媒体/机房"
    if "实验" in s:
        return "实验室"
    if any(k in s for k in ("体育", "操场", "体育馆", "游泳", "网球",
                            "健美", "形体", "健身", "活动中心")):
        return "体育场地"
    return "普通教室"


def agg_classroom_util(lesson):
    """教室利用率热力图：利用率真实(排课快照 utilization)，按 干净楼栋×类型 求均，
    确定性铺到 周1-5 × 4时段(缺真实调度维度→固定种子合成 day/period 波动)。"""
    df = lesson.dropna(subset=["utilization"]).copy()
    if df.empty:
        return pd.DataFrame()
    df["building"] = df["classroom"].map(_building)
    df["room_type"] = df["classroom"].map(_room_type)
    df = df.dropna(subset=["building"])
    bmean = df.groupby(["building", "room_type", "semester_id"])["utilization"].mean()
    rng = np.random.default_rng(config.SEED + 11)
    rows = []
    for (building, rtype, sem), base in bmean.items():
        for day in range(1, 6):
            for period in _PERIODS:
                # 围绕真实均值的确定性波动；午后/晚段略低，周五整体偏低
                factor = 1.0 if period in ("p12", "p34") else 0.85
                if day == 5:
                    factor *= 0.9
                u = float(np.clip(base * factor + rng.normal(0, 0.05), 0, 1))
                rows.append({
                    "building": building, "room_type": rtype,
                    "semester_id": sem, "day": day, "period": period,
                    # 楼栋利用率基线来自真实排课，但星期/节次由固定种子铺设，整体证据等级必须标 sim。
                    "utilization": round(u, 4), "source": "sim",
                })
    return pd.DataFrame(rows)


def agg_course_category_term(lesson, dim_course):
    """按 (课程类别, 学期) 聚合排课指标，用于课程排课分析页。"""
    lc = lesson.merge(dim_course[["course_id", "category"]], on="course_id", how="left")
    lc["category"] = lc["category"].fillna("未知")
    rows = []
    for (cat, sem), grp in lc.groupby(["category", "semester_id"]):
        enrolled = grp["enrolled"].dropna()
        th = grp["total_hours"].fillna(0).sum()
        rows.append({
            "category": cat, "semester_id": sem,
            "course_count": int(grp["course_id"].nunique()),
            "lesson_count": int(len(grp)),
            "total_hours": round(th, 1),
            "theory_hours": round(grp["theory_hours"].fillna(0).sum(), 1),
            "exp_hours": round(grp["exp_hours"].fillna(0).sum(), 1),
            "practice_hours": round(grp["practice_hours"].fillna(0).sum(), 1),
            "lab_hours": round(grp["lab_hours"].fillna(0).sum(), 1),
            "avg_enrolled": round(enrolled.mean(), 1) if len(enrolled) else None,
            "small_count": int((enrolled < 30).sum()),
            "medium_count": int(((enrolled >= 30) & (enrolled < 60)).sum()),
            "large_count": int(((enrolled >= 60) & (enrolled < 120)).sum()),
            "xlarge_count": int((enrolled >= 120).sum()),
            "source": "real",
        })
    return pd.DataFrame(rows)


def build_all(grade, lesson, alert, dims) -> dict:
    ds, dt = dims["dim_student"], dims["dim_teacher"]
    return {
        "agg_college_term": agg_college_term(grade, ds, alert),
        "agg_major_term": agg_major_term(grade, ds, alert),
        "agg_course_term": agg_course_term(grade),
        "agg_gpa_dist": agg_gpa_dist(grade, ds),
        "agg_teacher_load": agg_teacher_load(lesson, dt),
        "agg_classroom_util": agg_classroom_util(lesson),
        "agg_course_category_term": agg_course_category_term(lesson, dims["dim_course"]),
    }


if __name__ == "__main__":
    from . import extract, transform, simulate, parse_plan, seed, alert_engine
    g = extract.read_grades(); t = extract.read_tasks()
    dims, maps = transform.build_dims(g, t)
    fg = transform.build_fact_grade(g); fl = transform.build_fact_lesson(t)
    sg, sl, _ = simulate.simulate(fg, dims["dim_student"], fl)
    allg = pd.concat([fg, sg], ignore_index=True)
    alll = pd.concat([fl, sl], ignore_index=True)
    mdf, cdf = parse_plan.parse_all()
    mdf["major_id"] = mdf["major_name"].map(maps["major"])
    rules = seed.build_rules_df()
    alerts = alert_engine.run_engine(allg, dims["dim_student"], dims["dim_course"], mdf, rules)
    aggs = build_all(allg, alll, alerts, dims)
    for k, v in aggs.items():
        print(f"{k}: {len(v)} 行")
    print("\ncollege_term 示例:", aggs["agg_college_term"].head(2).to_dict("records"))
    print("gpa_dist(all) 示例:",
          aggs["agg_gpa_dist"][aggs["agg_gpa_dist"]["scope_type"] == "all"].head(5).to_dict("records"))
