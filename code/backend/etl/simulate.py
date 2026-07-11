"""模拟新学期增量（R2）：在真实历史之上生成 2025-2026-2 学期。
原则：走真实分布、固定种子可复现、source='sim'、不加演示标识。
- 活跃学生 = 在最新真实学期(2025-2026-1)有成绩的学生。
- 课表 = 各专业历史"春季学期(term=2)"高频课程作为典型课程包。
- 成绩 = 按课程历史分数分布采样；得分→绩点用真实映射表。
- 异常注入 = 约 3-4% 学生命中预警阈值（挂科累积/GPA下降/核心课/退学风险）。
"""
import numpy as np
import pandas as pd

from . import config


def build_gpa_map(real_grade: pd.DataFrame) -> dict:
    """从真实数据建 得分(整) → 绩点 中位数映射。"""
    df = real_grade.dropna(subset=["score", "gpa"]).copy()
    df["sc"] = df["score"].round().astype(int)
    m = df.groupby("sc")["gpa"].median().to_dict()
    return m


def _gpa_of(score, gpa_map):
    if score is None or np.isnan(score):
        return None
    s = int(round(score))
    if s in gpa_map:
        return float(gpa_map[s])
    # 就近取
    keys = sorted(gpa_map)
    if not keys:
        return None
    nearest = min(keys, key=lambda k: abs(k - s))
    return float(gpa_map[nearest])


def simulate(real_grade: pd.DataFrame, dim_student: pd.DataFrame,
             real_lesson: pd.DataFrame, anomaly_rate: float = 0.035):
    """返回 (sim_grade_df, sim_lesson_df)。"""
    rng = np.random.default_rng(config.SEED)
    sim_sem = config.SIM_SEMESTER
    gpa_map = build_gpa_map(real_grade)

    # 课程历史分数分布
    cstat = real_grade.dropna(subset=["score"]).groupby("course_id")["score"].agg(["mean", "std"])
    cstat["std"] = cstat["std"].fillna(8.0).clip(lower=4.0)
    # 课程学分（取众数）
    ccred = real_grade.dropna(subset=["credits"]).groupby("course_id")["credits"].median()
    creq = real_grade.groupby("course_id")["is_required"].mean()

    # 学生→专业
    stu_major = dim_student.set_index("student_id")["major_id"].to_dict()
    g = real_grade.copy()
    g["term"] = g["semester_id"].str[-1]
    g["major_id"] = g["student_id"].map(stu_major)

    # 活跃学生
    active = sorted(set(g.loc[g["semester_id"] == config.LATEST_REAL_SEMESTER, "student_id"].dropna()))
    if not active:  # 兜底：取最近一学年
        active = sorted(set(g.loc[g["semester_id"].str.startswith("2024-2025"), "student_id"].dropna()))

    # 各专业春季(term=2)典型课程包（高频 top8）+ 历史参与率
    # 参与率 = 该课历史去重选课人数 / 该专业历史春季去重学生数，
    # 用于离散化每生选课，避免"整包全选"导致多门课人数完全相同的穿帮。
    spring = g[g["term"] == "2"]
    major_menu = {}
    major_course_p: dict = {}
    for mid, grp in spring.groupby("major_id"):
        denom = grp["student_id"].nunique() or 1
        vc = grp.groupby("course_id")["student_id"].nunique().sort_values(ascending=False)
        top = vc.head(8).index.tolist()
        major_menu[mid] = top
        for cid in top:
            major_course_p[(mid, cid)] = float(min(1.0, vc[cid] / denom))

    # 学生已通过课程（避免重复开同一已过课）
    passed = g[g["is_pass"] == 1].groupby("student_id")["course_id"].apply(set).to_dict()

    # 异常学生分配
    n_anom = max(1, int(len(active) * anomaly_rate))
    anom_students = set(rng.choice(active, size=min(n_anom, len(active)), replace=False))
    # 异常类型轮转
    anom_types = {s: ["fail3", "gpa_drop", "core_fail", "dropout"][i % 4]
                  for i, s in enumerate(sorted(anom_students))}

    rows = []
    for sid in active:
        mid = stu_major.get(sid)
        cand = [c for c in major_menu.get(mid, []) if c not in passed.get(sid, set())]
        if not cand:  # 该专业无历史春季课→退而取全校高频
            cand = list(cstat.index[:5])
        # 按历史参与率离散选课（保留频次顺序），不足3门则用高频课兜底
        sel = {c for c in cand if rng.random() < major_course_p.get((mid, c), 0.6)}
        menu = [c for c in cand if c in sel]
        if len(menu) < 3:
            menu = cand[:max(3, len(menu))]
        atype = anom_types.get(sid)
        for ci, cid in enumerate(menu):
            mean = cstat["mean"].get(cid, 78.0)
            std = cstat["std"].get(cid, 8.0)
            score = float(np.clip(rng.normal(mean, std), 0, 100))
            # 异常注入：覆盖得分
            if atype == "fail3" and ci < 3:
                score = float(rng.uniform(40, 58))            # 前3门挂
            elif atype == "core_fail" and creq.get(cid, 0) >= 0.5 and ci == 0:
                score = float(rng.uniform(45, 58))            # 核心(必修)挂1门
            elif atype == "dropout":
                score = float(rng.uniform(30, 55))            # 普遍低分
            elif atype == "gpa_drop":
                score = float(np.clip(score - 25, 0, 100))    # 整体下滑
            score = round(score)
            gp = _gpa_of(score, gpa_map)
            is_pass = 1 if score >= 60 else 0
            rows.append({
                "student_id": sid, "course_id": cid, "lesson_id": f"{cid}.S2",
                "semester_id": sim_sem, "score": float(score), "level": None,
                "gpa": gp, "is_pass": is_pass,
                "is_required": int(creq.get(cid, 0) >= 0.5),
                "is_retake": 0, "credits": float(ccred.get(cid, 2.0)),
                "exam_status": "正常", "source": "sim",
            })
    sim_grade = pd.DataFrame(rows)

    # 模拟教学班：复用真实排课快照，挂到 sim 学期
    sim_lesson = real_lesson.copy()
    sim_lesson["semester_id"] = sim_sem
    sim_lesson["source"] = "sim"

    return sim_grade, sim_lesson, anom_types


if __name__ == "__main__":
    from . import extract, transform
    g = extract.read_grades()
    t = extract.read_tasks()
    dims, _ = transform.build_dims(g, t)
    fg = transform.build_fact_grade(g)
    fl = transform.build_fact_lesson(t)
    sg, sl, anom = simulate(fg, dims["dim_student"], fl)
    print(f"模拟 {config.SIM_SEMESTER}: 成绩 {len(sg)} 行 / 学生 {sg['student_id'].nunique()} / 异常 {len(anom)}")
    print("挂科率(sim):", round((sg['is_pass'] == 0).mean() * 100, 2), "%")
    print("avg score(sim):", round(sg['score'].mean(), 1), "avg gpa:", round(sg['gpa'].dropna().mean(), 2))
