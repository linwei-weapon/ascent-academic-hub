"""预警规则引擎：按 sys_alert_rule 从真实+模拟成绩算出预警。
- 内置规则(R1~R6)：硬编码逻辑，保持原有精确性
- 自发现规则(trigger_type='discovered')：通用评估器，解析 conditions JSON 动态计算
- 以"近2学期(最新真实+模拟)"为当前风险窗口
"""
import json
import math
import numpy as np
import pandas as pd

from . import config
from .extract_ts import SEMESTERS as _SEMS

RECENT = _SEMS[-2:]  # 当前风险窗口（最近两学期：2025-2026-1, 2025-2026-2）
_BASE_DATE = np.datetime64("2026-03-01")


# ── 通用规则评估器（处理 trigger_type='discovered' 的规则）──

def _compute_features(grade: pd.DataFrame, dim_student: pd.DataFrame,
                      plan_course: pd.DataFrame | None) -> pd.DataFrame:
    """计算每个学生的特征值，返回 DataFrame，index=student_id。"""
    g = grade.copy()

    # 总挂科
    total_fail = g[g["is_pass"] == 0].groupby("student_id").size()

    # 核心课挂科（需培养方案标记 is_core）
    core_fail = pd.Series(dtype=int)
    if plan_course is not None and len(plan_course):
        core_courses = plan_course[plan_course["is_core"] == 1]["course_id"].unique()
        core_g = g[g["course_id"].isin(core_courses)]
        core_fail = core_g[core_g["is_pass"] == 0].groupby("student_id").size()

    # GPA 逐学期轨迹
    gpa_g = g.dropna(subset=["gpa"])
    gpa_term = gpa_g.groupby(["student_id", "semester_id"])["gpa"].mean().reset_index()
    gpa_term = gpa_term.sort_values(["student_id", "semester_id"])

    # GPA 总趋势（最新 - 最早）
    gpa_first = gpa_term.groupby("student_id").first()["gpa"]
    gpa_last = gpa_term.groupby("student_id").last()["gpa"]
    gpa_trend = gpa_last - gpa_first

    # GPA 下滑次数
    def _drop_count(seq):
        if len(seq) < 2:
            return 0
        return sum(1 for i in range(1, len(seq)) if seq[i] < seq[i-1] - 0.2)
    gpa_drop = gpa_term.groupby("student_id")["gpa"].apply(list).apply(_drop_count)

    # 学分完成率
    earned = g[g["is_pass"] == 1].groupby("student_id")["credits"].sum()
    stu_major = dim_student.set_index("student_id")[["major_id", "grade"]]

    features = pd.DataFrame(index=dim_student["student_id"].unique())
    features["total_fail"] = total_fail.reindex(features.index).fillna(0).astype(int)
    features["core_fail"] = core_fail.reindex(features.index).fillna(0).astype(int)
    features["gpa_trend"] = gpa_trend.reindex(features.index).fillna(0).round(2)
    features["gpa_drop_count"] = gpa_drop.reindex(features.index).fillna(0).astype(int)
    features["credit_ratio"] = 0.0  # 默认值，后续按专业填充
    features["earned_credits"] = earned.reindex(features.index).fillna(0.0)

    return features


def _evaluate_generic_rules(rules: dict, features: pd.DataFrame,
                             dim_student: pd.DataFrame,
                             plan_meta: pd.DataFrame | None,
                             grade: pd.DataFrame,
                             cname: dict) -> list[dict]:
    """评估所有 trigger_type='discovered' 的自发现规则，返回 alert 列表。"""
    alerts = []
    # 补充学分完成率（需要培养方案元数据）
    if plan_meta is not None and len(plan_meta):
        stu_major = dim_student.set_index("student_id")["major_id"].to_dict()
        major_total = plan_meta.set_index("major_id")["total_credits"].to_dict()
        for sid in features.index:
            mid = stu_major.get(sid)
            tot = major_total.get(mid)
            if tot and tot > 0:
                features.at[sid, "credit_ratio"] = round(
                    min(features.at[sid, "earned_credits"] / tot, 1.0), 2)

    for rule_id, r in rules.items():
        if r.get("trigger_type") != "discovered" or not r.get("enabled"):
            continue
        try:
            conds = json.loads(r["params"]) if isinstance(r["params"], str) else (r["params"] or {})
        except Exception:
            continue
        # params 是 {key: value, "text": "..."} 格式；排除 text
        if not conds or not any(k != "text" for k in conds):
            continue

        # 对每个学生判断是否命中
        matched = pd.Series(True, index=features.index)
        detail_parts = []

        # 处理单特征条件
        for key, threshold in conds.items():
            if key == "text" or key not in features.columns:
                continue
            if threshold is None:
                continue
            try:
                th = float(threshold)
            except (TypeError, ValueError):
                continue

            col = features[key]
            # 判断操作符（从 value 的正负和 key 语义推断）
            if key in ("gpa_trend", "credit_ratio"):
                op = "<"
                cond_match = col < th
                label_map = {"gpa_trend": "GPA总降幅", "credit_ratio": "学分完成率"}
                unit = "" if key == "gpa_trend" else "%"
                display_val = abs(th) if key == "gpa_trend" else th * 100
                detail_parts.append(f"{label_map.get(key, key)}{op}{display_val}{unit}")
            elif key in ("total_fail", "core_fail", "gpa_drop_count"):
                op = "≥"
                th_int = math.ceil(th)
                cond_match = col >= th_int
                label_map = {"total_fail": "挂科门次", "core_fail": "核心课挂科",
                             "gpa_drop_count": "GPA下滑次数"}
                unit_map = {"total_fail": "门", "core_fail": "门", "gpa_drop_count": "次"}
                detail_parts.append(f"{label_map.get(key, key)}{op}{th_int}{unit_map.get(key, '')}")
            else:
                continue

            if len(features.loc[matched]) > 0:
                matched = matched & cond_match

        # 复合条件（全部满足才算命中）
        hit_sids = features.index[matched]
        for sid in hit_sids:
            detail = r.get("name", "自发现规则") + "：" + "，".join(detail_parts)
            row = features.loc[sid]
            vals = []
            for key in conds:
                if key == "text" or key not in features.columns:
                    continue
                v = row[key]
                vals.append(f"{key}={v}")
            detail += "（" + "，".join(vals) + "）"
            alerts.append({
                "student_id": sid, "rule_id": rule_id,
                "type": r.get("name", "自发现规则"),
                "level": r.get("level", "警告"),
                "trigger_detail": detail,
                "semester_id": config.SIM_SEMESTER, "source": "real",
            })

    return alerts


def _rules_index(rules_df):
    idx = {}
    for _, r in rules_df.iterrows():
        params = json.loads(r["params"]) if isinstance(r["params"], str) else (r["params"] or {})
        idx[r["rule_id"]] = {"name": r["name"], "level": r["level"],
                             "enabled": int(r["enabled"]), "params": params,
                             "trigger_type": r.get("trigger_type", "threshold")}
    return idx


def _term_gpa(grade: pd.DataFrame) -> pd.DataFrame:
    """每学生每学期平均绩点（按学期排序）。"""
    tg = (grade.dropna(subset=["gpa"])
          .groupby(["student_id", "semester_id"])["gpa"].mean().reset_index())
    return tg.sort_values(["student_id", "semester_id"])


def run_engine(grade: pd.DataFrame, dim_student: pd.DataFrame,
               dim_course: pd.DataFrame, plan_meta: pd.DataFrame,
               rules_df: pd.DataFrame,
               plan_course: pd.DataFrame | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(config.SEED + 7)
    rules = _rules_index(rules_df)
    cname = dim_course.set_index("course_id")["name"].to_dict()

    g = grade.copy()
    recent = g[g["semester_id"].isin(RECENT)]
    fails_recent = recent[recent["is_pass"] == 0]
    # 学生×课程只要历史上出现过通过，即视为已解决；近期风险只保留尚未通过课程。
    passed_pairs = set(map(tuple, g[g["is_pass"] == 1][["student_id", "course_id"]]
                           .dropna().drop_duplicates().to_numpy()))
    unresolved_recent = fails_recent[["student_id", "course_id", "is_required"]].dropna(
        subset=["student_id", "course_id"]).drop_duplicates(["student_id", "course_id"])
    if passed_pairs:
        unresolved_recent = unresolved_recent[
            ~unresolved_recent.apply(
                lambda r: (r["student_id"], r["course_id"]) in passed_pairs, axis=1)]

    alerts = []

    def emit(sid, rule_id, detail):
        r = rules[rule_id]
        alerts.append({"student_id": sid, "rule_id": rule_id, "type": r["name"],
                       "level": r["level"], "trigger_detail": detail,
                       "semester_id": config.SIM_SEMESTER, "source": "real"})

    # --- R2：近窗口不同且尚未解决的课程数≥N ---
    if rules["R2"]["enabled"]:
        n = rules["R2"]["params"].get("fail_courses", 3)
        cnt = unresolved_recent.groupby("student_id")["course_id"].nunique()
        for sid, c in cnt[cnt >= n].items():
            emit(sid, "R2", f"近2学期尚未通过课程 {int(c)} 门（按不同课程去重）")

    # --- R2W：恰好2门为警告；与R2(≥3门严重)互斥，避免重复预警 ---
    if rules.get("R2W", {}).get("enabled"):
        lower = int(rules["R2W"]["params"].get("fail_courses", 2))
        upper = int(rules["R2W"]["params"].get("upper_exclusive", 3))
        cnt = unresolved_recent.groupby("student_id")["course_id"].nunique()
        for sid, c in cnt[(cnt >= lower) & (cnt < upper)].items():
            emit(sid, "R2W", f"近2学期尚未通过课程 {int(c)} 门（关注级）")

    # --- R4：有真实培养方案按核心课；无方案时明确降级为必修课风险 ---
    if rules["R4"]["enabled"]:
        core_n = int(rules["R4"]["params"].get("core_fail", 2))
        student_plan = dim_student.set_index("student_id")[["major_id", "grade"]].to_dict("index")
        plan_core = {}
        if plan_course is not None and len(plan_course):
            for (mid, grade), grp in plan_course.groupby(["major_id", "grade"]):
                plan_core[(mid, str(grade))] = set(
                    grp[grp["is_core"] == 1]["course_id"].dropna().astype(str))
        for sid, grp in unresolved_recent.groupby("student_id"):
            stu = student_plan.get(sid, {})
            key = (stu.get("major_id"), str(stu.get("grade")))
            if key in plan_core:
                cids = [c for c in grp["course_id"].astype(str).unique()
                        if c in plan_core[key]]
                risk_name = "培养方案核心课"
            else:
                cids = grp[grp["is_required"] == 1]["course_id"].dropna().astype(str).unique()
                risk_name = "必修课（无真实培养方案，降级判定）"
            if len(cids) < core_n:
                continue
            names = [cname.get(c, c) for c in cids[:2]]
            emit(sid, "R4", risk_name + "尚未通过：" + "、".join(map(str, names)))

    # --- R1 GPA持续下降：最近2学期连降且降幅>阈值 ---
    if rules["R1"]["enabled"]:
        drop = rules["R1"]["params"].get("gpa_drop", 0.3)
        tg = _term_gpa(g)
        for sid, grp in tg.groupby("student_id"):
            # 仅当下降发生在当前风险窗口（最新学期∈RECENT）才算实时预警
            if grp["semester_id"].iloc[-1] not in RECENT:
                continue
            seq = grp["gpa"].tolist()
            if len(seq) >= 3:
                a, b, c = seq[-3], seq[-2], seq[-1]
                if c < b < a and (a - c) > drop:
                    emit(sid, "R1", f"近3学期GPA {a:.2f}→{b:.2f}→{c:.2f}（降{a-c:.2f}）")
            elif len(seq) == 2 and (seq[0] - seq[1]) > drop:
                emit(sid, "R1", f"近2学期GPA {seq[0]:.2f}→{seq[1]:.2f}（降{seq[0]-seq[1]:.2f}）")

    # --- R6 退学风险：当前学期GPA<阈值 且 近窗口挂科≥N ---
    if rules["R6"]["enabled"]:
        gpa_below = rules["R6"]["params"].get("gpa_below", 1.8)
        fc_n = int(rules["R6"]["params"].get("fail_courses", 2))
        cur = g[g["semester_id"] == config.SIM_SEMESTER]
        cur_gpa = cur.dropna(subset=["gpa"]).groupby("student_id")["gpa"].mean()
        fcnt = unresolved_recent.groupby("student_id")["course_id"].nunique()
        for sid, gp in cur_gpa[cur_gpa < gpa_below].items():
            if fcnt.get(sid, 0) >= fc_n:
                emit(sid, "R6", f"本学期GPA {gp:.2f}（<{gpa_below}）+近2学期挂科{int(fcnt.get(sid,0))}门")

    # --- R3 学分缺口：仅 2 专业，按期望进度(0.8*总学分)比对 ---
    if rules["R3"]["enabled"] and plan_meta is not None and len(plan_meta):
        gap_th = rules["R3"]["params"].get("credit_gap", 10)
        prog = 0.8  # 2022级当前学期期望完成比例
        stu_major = dim_student.set_index("student_id")["major_id"].to_dict()
        major_total = plan_meta.set_index("major_id")["total_credits"].to_dict()
        earned = g[g["is_pass"] == 1].groupby("student_id")["credits"].sum()
        for sid in dim_student["student_id"]:
            mid = stu_major.get(sid)
            tot = major_total.get(mid)
            if not tot:
                continue
            exp = tot * prog
            got = earned.get(sid, 0.0)
            if exp - got > gap_th:
                emit(sid, "R3", f"学分缺口 {exp-got:.1f}（期望{exp:.0f}/已修{got:.0f}）")

    # --- 通用评估器：处理自发现规则 ---
    discovered_alerts = _evaluate_generic_rules(
        rules, _compute_features(g, dim_student, plan_course),
        dim_student, plan_meta, g, cname)
    alerts.extend(discovered_alerts)

    df = pd.DataFrame(alerts)
    if df.empty:
        return df

    # --- 处理状态（模拟流转）+ 生成时间（散布近3个月，供月度趋势）---
    statuses = rng.choice(["待处理", "已约谈", "已解决"], size=len(df), p=[0.45, 0.21, 0.34])
    df["status"] = statuses
    offsets = rng.integers(0, 90, size=len(df))
    df["created_at"] = [str(_BASE_DATE + np.timedelta64(int(o), "D")) for o in offsets]
    return df


if __name__ == "__main__":
    from . import extract, transform, simulate, parse_plan, seed
    g = extract.read_grades(); t = extract.read_tasks()
    dims, maps = transform.build_dims(g, t)
    fg = transform.build_fact_grade(g); fl = transform.build_fact_lesson(t)
    sg, sl, _ = simulate.simulate(fg, dims["dim_student"], fl)
    allg = pd.concat([fg, sg], ignore_index=True)
    mdf, cdf = parse_plan.parse_all()
    mdf["major_id"] = mdf["major_name"].map(maps["major"])
    rules = seed.build_rules_df()
    alerts = run_engine(allg, dims["dim_student"], dims["dim_course"], mdf, rules)
    print(f"预警总数 {len(alerts)} / 涉及学生 {alerts['student_id'].nunique()}")
    print("按规则:", alerts["type"].value_counts().to_dict())
    print("按等级:", alerts["level"].value_counts().to_dict())
    print("按状态:", alerts["status"].value_counts().to_dict())
    print("解决率:", round((alerts["status"] == "已解决").mean() * 100, 1), "%")
    print("示例:", alerts[["type", "level", "trigger_detail"]].head(4).to_dict("records"))
