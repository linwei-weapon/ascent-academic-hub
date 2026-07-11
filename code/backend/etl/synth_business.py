"""合成业务数据（R3）：真实学业源缺失的业务域，按真实学业数据派生。

照 simulate.py 范式：固定种子可复现、source='sim'、不加演示标识。
派生原则 —— 每条都挂靠真实学生/课程/学院，分布由真实学业指标驱动，
使"毕业率/学位率/异动/出勤"等指标与已有成绩、预警、学分自洽（非凭空写死）。

产出 6 张表：
  fact_major_req   各专业毕业学分要求（M017/M031 用真实方案=real，其余按真实均值合成=sim）
  fact_graduation  毕业届学生(2022级)毕业/学位/就业去向（按已修学分+绩点+预警判定）
  fact_attrition   学籍异动（约 1%，偏向低绩点/预警学生）
  fact_discipline  考纪记录（违纪/作弊，少量，按学院规模分布）
  fact_exam_cert   校外考试通过（CET4/6、计算机二/三级，按学院英语/计算机倾向）
  fact_attend      课程出勤（当前学期，出勤率与挂科率负相关）
"""
import numpy as np
import pandas as pd

from . import config


def _earned_by_student(grade: pd.DataFrame) -> pd.DataFrame:
    """每生：已修学分(通过)、平均绩点、修读门数。"""
    g = grade.copy()
    passed = g[g["is_pass"] == 1]
    earned = passed.groupby("student_id")["credits"].sum()
    gpa = g.dropna(subset=["gpa"]).groupby("student_id")["gpa"].mean()
    return pd.DataFrame({"earned": earned, "gpa": gpa}).fillna(0.0)


def build_major_req(dim_student, dim_major, plan_meta) -> pd.DataFrame:
    """各专业毕业学分要求。真实方案(M017/M031)直接用，其余按真实方案均值合成。"""
    real = {}
    for _, r in plan_meta.iterrows():
        real[r["major_id"]] = {
            "total_req": r["total_credits"], "general_req": None,
            "major_req": r["required_credits"], "practice_req": r["practice_credits"],
        }
    # 合成基准 = 真实方案均值（缺则取通用工科默认）
    if real:
        base_total = float(np.mean([v["total_req"] for v in real.values()]))
        base_major = float(np.mean([v["major_req"] for v in real.values()]))
        base_prac = float(np.mean([v["practice_req"] for v in real.values()]))
    else:
        base_total, base_major, base_prac = 165.0, 110.0, 28.0

    rng = np.random.default_rng(config.SEED + 21)
    grade_of = dim_student.groupby("major_id")["grade"].agg(
        lambda s: s.dropna().mode().iloc[0] if s.dropna().size else "2022").to_dict()
    rows = []
    for _, m in dim_major.iterrows():
        mid = m["major_id"]
        gr = grade_of.get(mid, "2022")
        if mid in real:
            tot = real[mid]["total_req"]
            mreq = real[mid]["major_req"]
            prac = real[mid]["practice_req"]
            gen = round(tot - mreq - prac, 1)
            src = "real"
        else:
            tot = round(base_total + rng.integers(-6, 7), 1)        # 159~171
            mreq = round(base_major + rng.integers(-8, 9), 1)
            prac = round(base_prac + rng.integers(-4, 5), 1)
            gen = round(tot - mreq - prac, 1)
            src = "sim"
        rows.append({"major_id": mid, "grade": gr, "total_req": tot,
                     "general_req": max(gen, 0), "major_req": mreq,
                     "practice_req": prac, "source": src})
    return pd.DataFrame(rows)


def build_graduation(dim_student, grade, alert, major_req, graduating_ids=None) -> pd.DataFrame:
    """毕业届(当前在校 graduating_ids = 2022级)毕业/学位/就业去向。
    判定：已修学分(对数据残缺尾部按专业中位数补全)达应修线→按期毕业；
    学位再要求 GPA≥2.0 且无在途严重预警；去向按 GPA 高低给概率(高→升学多)。

    说明：真实成绩库未覆盖完整四年培养方案，部分学生学分明显偏低实为数据
    不全(非真不及格)。故对学分以"专业中位数"做缺失补全，使毕业率落在
    真实高校合理区间(~95%)，避免把数据缺口误判为大面积不毕业。

    graduating_ids：当前学期在校且年级=毕业届(2022)的学生 id 集合，只对该群体
    产毕业记录（往届已从在校快照消失、低年级未到毕业期）。"""
    rng = np.random.default_rng(config.SEED + 22)
    es = _earned_by_student(grade)
    req = major_req.set_index("major_id")["total_req"].to_dict()
    sev_stu = (set(alert.loc[alert["level"] == "严重", "student_id"].astype(str))
               if len(alert) else set())

    grad_ds = dim_student
    if graduating_ids is not None:
        gset = set(str(x) for x in graduating_ids)
        grad_ds = dim_student[dim_student["student_id"].astype(str).isin(gset)]

    # 成绩库未覆盖完整四年，"已修学分"系统性偏低且分布残缺，绝对学分线不可靠。
    # 改用专业内学分位次判定：位次太靠后(后5%)才视为学业未达标。
    es_join = es.join(dim_student.set_index("student_id")["major_id"])
    es_join["pct"] = es_join.groupby("major_id")["earned"].rank(pct=True)

    rows = []
    for _, s in grad_ds.iterrows():
        sid = s["student_id"]
        earned_raw = float(es["earned"].get(sid, 0.0))
        gpa = float(es["gpa"].get(sid, 0.0))
        pct = float(es_join["pct"].get(sid, 0.5))
        is_sev = sid in sev_stu
        # 学业达标：专业内学分位次≥5% 且 GPA≥1.5(及格档边界)
        ok = pct >= 0.05 and gpa >= 1.5
        # 严重预警：不硬否决(真实多数处理后毕业)，但降低毕业概率
        if ok and is_sev:
            ok = rng.random() < 0.85
        if not ok:
            graduated = 0
            status = "延期毕业" if (gpa >= 1.0 and pct >= 0.02) else "结业"
        else:
            graduated = 0 if rng.random() < 0.02 else 1
            status = "按期毕业" if graduated else "延期毕业"
        # 学位：毕业 + GPA≥2.0(及格档以上) + 无在途严重预警
        degree = 1 if (graduated and gpa >= 2.0 and sid not in sev_stu) else 0
        if graduated and gpa >= 2.0 and sid in sev_stu and rng.random() < 0.4:
            degree = 1  # 预警已处理者部分仍授予
        # 就业去向：GPA 越高升学概率越高
        if graduated:
            p_grad = min(0.10 + gpa * 0.06, 0.42)      # 升学读研
            r = rng.random()
            if r < p_grad:
                goal = "升学读研"
            elif r < p_grad + 0.62:
                goal = "签约就业"
            elif r < p_grad + 0.62 + 0.13:
                goal = "灵活就业"
            else:
                goal = "待业"
        else:
            goal = "待业"
        rows.append({
            "student_id": sid, "grade": s["grade"], "major_id": s["major_id"],
            "college_id": s["college_id"], "earned_credits": round(earned_raw, 1),
            "req_credits": float(req.get(s["major_id"], 165.0)),
            "graduated": graduated, "degree": degree,
            "grad_status": status, "goal": goal,
            "semester_id": config.SIM_SEMESTER, "source": "sim",
        })
    return pd.DataFrame(rows)


def build_attrition(dim_student, grade, alert) -> pd.DataFrame:
    """学籍异动：约 1% 学生，偏向低绩点/预警学生。"""
    rng = np.random.default_rng(config.SEED + 23)
    es = _earned_by_student(grade)
    alert_stu = set(alert["student_id"].astype(str)) if len(alert) else set()
    students = dim_student["student_id"].tolist()
    # 权重：预警生×3，低绩点(<2.0)×2
    weights = []
    for sid in students:
        w = 1.0
        if sid in alert_stu:
            w *= 3
        if float(es["gpa"].get(sid, 3.0)) < 2.0:
            w *= 2
        weights.append(w)
    weights = np.array(weights) / np.sum(weights)
    n = max(4, int(len(students) * 0.011))
    picked = rng.choice(students, size=min(n, len(students)), replace=False, p=weights)
    sinfo = dim_student.set_index("student_id")
    kinds = ["休学", "复学", "退学", "转专业"]
    kweights = [0.40, 0.22, 0.13, 0.25]
    reasons = {"休学": "因病休学", "复学": "休学期满复学",
               "退学": "学业困难退学", "转专业": "转专业调整"}
    rows = []
    for sid in picked:
        s = sinfo.loc[sid]
        k = rng.choice(kinds, p=kweights)
        rows.append({
            "student_id": sid, "grade": s["grade"], "major_id": s["major_id"],
            "college_id": s["college_id"], "kind": k, "reason": reasons[k],
            "semester_id": config.SIM_SEMESTER, "source": "sim",
        })
    return pd.DataFrame(rows)


def build_discipline(dim_student, dim_college, current_ids=None) -> pd.DataFrame:
    """考纪记录：少量，按学院学生规模分布；含违纪与作弊。
    current_ids：仅对当前学期在校学生产记录（往届不计当前考纪）。"""
    rng = np.random.default_rng(config.SEED + 24)
    ds = dim_student
    if current_ids is not None:
        cset = set(str(x) for x in current_ids)
        ds = dim_student[dim_student["student_id"].astype(str).isin(cset)]
    size = ds.groupby("college_id").size().to_dict()
    punishes = {"违纪": ["警告", "严重警告", "记过"],
                "作弊": ["记过", "留校察看"]}
    details = {"违纪": "考场违纪", "作弊": "考试作弊"}
    pool = ds.groupby("college_id")["student_id"].apply(list).to_dict()
    rows = []
    for _, c in dim_college.iterrows():
        cid = c["college_id"]
        sts = pool.get(cid, [])
        if not sts:
            continue
        # 千分之 ~2 量级，至少 0
        n = int(round(len(sts) * rng.uniform(0.001, 0.004)))
        for _ in range(n):
            kind = "作弊" if rng.random() < 0.38 else "违纪"
            sid = rng.choice(sts)
            rows.append({
                "student_id": sid, "college_id": cid, "kind": kind,
                "detail": details[kind],
                "punish": rng.choice(punishes[kind]),
                "semester_id": config.SIM_SEMESTER, "source": "sim",
            })
    return pd.DataFrame(rows)


def build_exam_cert(dim_student, grade) -> pd.DataFrame:
    """校外考试通过：CET4/6、计算机二/三级。
    通过概率与该生平均绩点正相关；外语类学院 CET 偏高、信息/理工 NCRE 偏高。"""
    rng = np.random.default_rng(config.SEED + 25)
    es = _earned_by_student(grade)
    rows = []
    for _, s in dim_student.iterrows():
        sid = s["student_id"]
        gpa = float(es["gpa"].get(sid, 2.5))
        base = np.clip((gpa - 1.0) / 4.0, 0.05, 0.95)   # 绩点驱动基线
        cet4 = int(rng.random() < min(base + 0.25, 0.98))
        cet6 = int(cet4 and rng.random() < base * 0.7)
        ncre2 = int(rng.random() < min(base + 0.15, 0.95))
        ncre3 = int(ncre2 and rng.random() < base * 0.45)
        rows.append({
            "student_id": sid, "college_id": s["college_id"],
            "cet4": cet4, "cet6": cet6, "ncre2": ncre2, "ncre3": ncre3,
            "source": "sim",
        })
    return pd.DataFrame(rows)


def build_attend(grade, dim_course, dim_student) -> pd.DataFrame:
    """课程出勤(当前学期)：出勤率与课程挂科率负相关；旷课>3 人数据修读规模派生。"""
    rng = np.random.default_rng(config.SEED + 26)
    cur = grade[grade["semester_id"] == config.SIM_SEMESTER]
    if cur.empty:
        cur = grade[grade["semester_id"] == config.LATEST_REAL_SEMESTER]
    cdept = dim_course.set_index("course_id")["dept"].to_dict()
    cname_ok = set(dim_course["course_id"])
    # 课程→学院(用修读学生多数票)
    smap = dim_student.set_index("student_id")["college_id"].to_dict()
    rows = []
    for cid, grp in cur.groupby("course_id"):
        total = len(grp)
        if total < 20 or cid not in cname_ok:
            continue
        fail_rate = float((grp["is_pass"] == 0).mean())
        # 出勤率：基线 0.97，随挂科率下降，加少量噪声
        attend = float(np.clip(0.97 - fail_rate * 1.2 + rng.normal(0, 0.015), 0.80, 0.995))
        absent_gt3 = int(round(total * (1 - attend) * rng.uniform(0.8, 1.4)))
        pct = round(absent_gt3 / total * 100, 1) if total else 0.0
        trend = "down" if attend < 0.90 else ("up" if attend > 0.96 else "stable")
        # 课程所属学院：取修读学生学院众数
        cids = grp["student_id"].map(smap).dropna()
        college_id = cids.mode().iloc[0] if not cids.empty else None
        rows.append({
            "course_id": cid, "college_id": college_id,
            "semester_id": config.SIM_SEMESTER, "attend_rate": round(attend, 4),
            "absent_gt3": absent_gt3, "absent_gt3_pct": pct, "trend": trend,
            "source": "sim",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------- 职称规范化
# 真实 title 为脏串（如"教授;副教授;工程师"/"未知"/"研究员（自然科学）"），
# 取其中最高职称归一到 5 档，供师资画像与负荷分桶用。
_TITLE_RANK = {"教授": 4, "副教授": 3, "讲师": 2, "助教": 1, "其他": 0}


def norm_title(raw) -> str:
    """脏职称串 → 5 档（教授/副教授/讲师/助教/其他），取最高。"""
    s = str(raw or "")
    best = 0
    for tok in s.replace("；", ";").split(";"):
        if "副教授" in tok or "副研究员" in tok:
            r = 3
        elif "教授" in tok or ("研究员" in tok and "助理" not in tok):
            r = 4
        elif "讲师" in tok or "工程师" in tok or "实验师" in tok or "助理研究员" in tok:
            r = 2
        elif "助教" in tok:
            r = 1
        else:
            r = 0
        best = max(best, r)
    for name, rk in _TITLE_RANK.items():
        if rk == best:
            return name
    return "其他"


def build_teacher_profile(dim_teacher) -> pd.DataFrame:
    """师资画像：学历/学位/年龄/学缘/教龄/毕业院校（真实库缺该域，按职称派生）。
    高职称→学历更高、年龄更长、教龄更久；学缘按典型高校结构分布。"""
    rng = np.random.default_rng(config.SEED + 27)
    # 学历分布（博士/硕士/本科）按职称
    edu_p = {
        "教授": [0.93, 0.06, 0.01], "副教授": [0.86, 0.12, 0.02],
        "讲师": [0.66, 0.30, 0.04], "助教": [0.40, 0.50, 0.10],
        "其他": [0.45, 0.45, 0.10],
    }
    edu_lvl = ["博士研究生", "硕士研究生", "大学本科"]
    degree_of = {"博士研究生": "博士", "硕士研究生": "硕士", "大学本科": "学士"}
    # 年龄段分布（<35/36-45/46-55/56+）按职称
    age_p = {
        "教授": [0.03, 0.22, 0.45, 0.30], "副教授": [0.15, 0.45, 0.30, 0.10],
        "讲师": [0.45, 0.40, 0.13, 0.02], "助教": [0.70, 0.25, 0.04, 0.01],
        "其他": [0.55, 0.30, 0.12, 0.03],
    }
    age_band = ["35岁以下", "36-45岁", "46-55岁", "56岁以上"]
    age_rng = {"35岁以下": (28, 35), "36-45岁": (36, 45),
               "46-55岁": (46, 55), "56岁以上": (56, 62)}
    origins = ["本校毕业", "外校(境内)", "境外高校"]
    origin_p = [0.34, 0.48, 0.18]
    schools_cn = ["中国石油大学", "清华大学", "北京大学", "浙江大学", "西安交通大学",
                  "中国科学技术大学", "天津大学", "大连理工大学", "哈尔滨工业大学",
                  "中国地质大学", "华东理工大学", "四川大学"]
    schools_ow = ["新加坡国立大学", "帝国理工学院", "代尔夫特理工大学",
                  "得克萨斯大学", "阿尔伯塔大学", "悉尼大学"]
    rows = []
    for _, t in dim_teacher.iterrows():
        title = norm_title(t["title"])
        edu = rng.choice(edu_lvl, p=edu_p[title])
        band = rng.choice(age_band, p=age_p[title])
        lo, hi = age_rng[band]
        age = int(rng.integers(lo, hi + 1))
        origin = rng.choice(origins, p=origin_p)
        if origin == "本校毕业":
            school = "中国石油大学"
        elif origin == "境外高校":
            school = rng.choice(schools_ow)
        else:
            school = rng.choice([s for s in schools_cn if s != "中国石油大学"])
        teach_years = int(np.clip(age - 27 - (0 if edu != "博士研究生" else 3),
                                  1, 38))
        rows.append({
            "teacher_id": t["teacher_id"], "norm_title": title,
            "education": edu, "degree": degree_of[edu], "age": age,
            "age_band": band, "origin": origin, "school": school,
            "teach_years": teach_years, "source": "sim",
        })
    return pd.DataFrame(rows)


def build_schedule_change(dim_teacher, lesson, dim_college) -> pd.DataFrame:
    """调停课记录（真实库缺该域）：约总教学班 5%~6% 的调课，按教师派生。
    锚定真实排课教师与学院；停课少量；原因/月份/学时按典型分布；
    >4 学时需教务审核（审核更久），≤4 学时院系自动通过。"""
    rng = np.random.default_rng(config.SEED + 28)
    # 教师→学院：dim_teacher.dept 脏串(可含重复/None)取首段，按名匹配 college
    name2cid = dict(zip(dim_college["name"], dim_college["college_id"]))

    def dept2cid(dept):
        s = str(dept or "").replace("；", ";").split(";")[0].strip()
        return name2cid.get(s)

    tinfo = {}
    for _, t in dim_teacher.iterrows():
        tinfo[t["teacher_id"]] = dept2cid(t["dept"])
    # 真实学期排课：教师授课班数、平均选课人数
    real = lesson[lesson["semester_id"] == config.LATEST_REAL_SEMESTER]
    if real.empty:
        real = lesson
    tload = real.groupby("teacher_id").agg(
        classes=("lesson_id", "count"),
        enrolled=("enrolled", "mean")).to_dict("index")
    # 候选教师 = 有学院归属且有排课
    cand = [tid for tid in tload if tinfo.get(tid)]
    if not cand:
        return pd.DataFrame()
    weights = np.array([tload[tid]["classes"] for tid in cand], dtype=float)
    weights /= weights.sum()
    n_changes = max(20, int(round(len(real) * 0.055)))
    reasons = ["病假", "事假", "公差", "教学调整", "其他"]
    reason_p = [0.30, 0.20, 0.18, 0.23, 0.09]
    months = [3, 4, 5, 6]
    month_p = [0.30, 0.30, 0.28, 0.12]
    hours_opt = [2, 4, 6]
    hours_p = [0.55, 0.30, 0.15]
    rows = []
    picks = rng.choice(len(cand), size=n_changes, replace=True, p=weights)
    for idx in picks:
        tid = cand[idx]
        cid = tinfo[tid]
        kind = "停课" if rng.random() < 0.22 else "调课"
        reason = rng.choice(reasons, p=reason_p)
        month = int(rng.choice(months, p=month_p))
        hours = int(rng.choice(hours_opt, p=hours_p))
        enrolled = tload[tid]["enrolled"]
        affected = int(max(1, round((enrolled if not np.isnan(enrolled) else 40)
                                    * rng.uniform(0.85, 1.0))))
        auto = 1 if hours <= 4 else 0
        review_days = round(float(rng.uniform(0.3, 1.2) if auto
                                  else rng.uniform(1.5, 3.5)), 1)
        rows.append({
            "teacher_id": tid, "college_id": cid, "kind": kind, "reason": reason,
            "month": month, "hours": hours, "affected": affected,
            "auto_approved": auto, "review_days": review_days,
            "semester_id": config.SIM_SEMESTER, "source": "sim",
        })
    return pd.DataFrame(rows)


def build_all(allg, lesson, dims, alert, plan_meta, extras=None) -> dict:
    """统一入口：返回 {table_name: DataFrame}。allg=全学期真实成绩。
    extras：extract_ts.read_all 的第三返回值，提供 current_ids / graduating_ids。
    fact_attrition / fact_exam_cert / fact_schedule_change 已改由
    extract_ts.build_real_business 用真实源(student_changes/external_exams/
    course_changes)构造，此处不再合成。"""
    ds = dims["dim_student"]
    dc = dims["dim_college"]
    dm = dims["dim_major"]
    dt = dims["dim_teacher"]
    dcourse = dims["dim_course"]
    current_ids = (extras or {}).get("current_ids")
    graduating_ids = (extras or {}).get("graduating_ids")
    major_req = build_major_req(ds, dm, plan_meta)
    return {
        "fact_major_req": major_req,
        "fact_graduation": build_graduation(ds, allg, alert, major_req, graduating_ids),
        "fact_discipline": build_discipline(ds, dc, current_ids),
        "fact_attend": build_attend(allg, dcourse, ds),
        "fact_teacher_profile": build_teacher_profile(dt),
    }


if __name__ == "__main__":
    import pandas as pd
    from . import extract, transform, simulate, parse_plan, seed, alert_engine
    g = extract.read_grades(); t = extract.read_tasks()
    dims, maps = transform.build_dims(g, t)
    fg = transform.build_fact_grade(g); fl = transform.build_fact_lesson(t)
    sg, sl, _ = simulate.simulate(fg, dims["dim_student"], fl)
    allg = pd.concat([fg, sg], ignore_index=True)
    mdf, cdf = parse_plan.parse_all()
    mdf["major_id"] = mdf["major_name"].map(maps["major"])
    rules = seed.build_rules_df()
    alerts = alert_engine.run_engine(allg, dims["dim_student"], dims["dim_course"], mdf, rules)
    alll = pd.concat([fl, sl], ignore_index=True)
    out = build_all(allg, alll, dims, alerts, mdf)
    for k, v in out.items():
        print(f"{k}: {len(v)} 行")
    tp = out["fact_teacher_profile"]
    print("学历分布:", tp["education"].value_counts().to_dict())
    print("年龄段:", tp["age_band"].value_counts().to_dict())
    sc = out["fact_schedule_change"]
    print("调停课:", len(sc), "停课:", int((sc["kind"] == "停课").sum()),
          "原因:", sc["reason"].value_counts().to_dict())
    grad = out["fact_graduation"]
    print("毕业率:", round(grad['graduated'].mean() * 100, 1), "%")
    print("学位率:", round(grad['degree'].mean() * 100, 1), "%")
    print("去向分布:", grad['goal'].value_counts().to_dict())
    print("异动:", out['fact_attrition']['kind'].value_counts().to_dict())
    print("考纪:", len(out['fact_discipline']), "条")
    print("CET4 通过率:", round(out['fact_exam_cert']['cet4'].mean() * 100, 1), "%")
    print("出勤课程数:", len(out['fact_attend']),
          "均出勤:", round(out['fact_attend']['attend_rate'].mean() * 100, 1), "%")
