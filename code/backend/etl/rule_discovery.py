"""规则自发现引擎：基于历史学生学业轨迹，自动识别高风险特征组合。

输入：fact_grade / fact_plan_course / dim_student / fact_alert / fact_graduation
输出：sys_discovered_rule（status=pending 的建议规则）

方法：决策树特征重要性 + 简单关联规则挖掘
运行方式：离线批处理，嵌入 ETL 管道末尾或页面手动触发。
"""
import json
import sqlite3
import math
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "db" / "analytics.sqlite"

# 结果标签定义
POSITIVE_LABELS = {"退学", "留级", "肄业"}          # 正样本 = 严重学业问题
NEGATIVE_LABELS = {"毕业", "结业"}                  # 负样本 = 正常完成
ALERT_THRESHOLD = 3                                  # 3次及以上严重预警也算正样本


def _build_features(conn: sqlite3.Connection) -> list[dict]:
    """构建学生特征矩阵。每行一个学生，包含学业轨迹特征 + 结果标签。"""
    # 所有学生
    students = {r["student_id"]: dict(r) for r in conn.execute(
        "SELECT student_id, college_id, major_id, grade FROM dim_student").fetchall()}

    # 每学期 GPA
    gpa_rows = conn.execute("""
        SELECT student_id, semester_id, AVG(gpa) g
        FROM fact_grade WHERE gpa IS NOT NULL
        GROUP BY student_id, semester_id ORDER BY semester_id
    """).fetchall()
    stu_gpas: dict[str, list[float]] = defaultdict(list)
    for r in gpa_rows:
        stu_gpas[r["student_id"]].append(r["g"])

    # 挂科数（总）
    fail_rows = conn.execute("""
        SELECT student_id, COUNT(*) fc FROM fact_grade
        WHERE is_pass=0 GROUP BY student_id
    """).fetchall()
    stu_fail = {r["student_id"]: r["fc"] for r in fail_rows}

    # 核心课挂科数
    core_fail = conn.execute("""
        SELECT g.student_id, COUNT(*) fc
        FROM fact_grade g
        JOIN fact_plan_course pc ON g.course_id=pc.course_id AND pc.is_core=1
        WHERE g.is_pass=0 GROUP BY g.student_id
    """).fetchall()
    stu_core_fail = {r["student_id"]: r["fc"] for r in core_fail}

    # 培养方案模块级挂科（仅两个有方案的专业）
    plan_mods = conn.execute("""
        SELECT DISTINCT module FROM fact_plan_course ORDER BY module
    """).fetchall()
    module_names = [r["module"] for r in plan_mods]
    stu_mod_fail: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if module_names:
        mod_rows = conn.execute("""
            SELECT g.student_id, pc.module, COUNT(*) fc
            FROM fact_grade g
            JOIN fact_plan_course pc ON g.course_id=pc.course_id
            WHERE g.is_pass=0 GROUP BY g.student_id, pc.module
        """).fetchall()
        for r in mod_rows:
            stu_mod_fail[r["student_id"]][r["module"]] = r["fc"]

    # 学分完成率
    req_rows = conn.execute("""
        SELECT student_id, SUM(credits) e FROM fact_grade
        WHERE is_pass=1 GROUP BY student_id
    """).fetchall()
    earned = {r["student_id"]: r["e"] for r in req_rows}
    req_map = {(r["major_id"], r["grade"]): r["total_req"]
               for r in conn.execute("SELECT major_id, grade, total_req FROM fact_major_req WHERE total_req>0").fetchall()}

    # 预警次数
    alert_rows = conn.execute("""
        SELECT student_id, COUNT(*) ac FROM fact_alert
        WHERE level='严重' AND COALESCE(is_active,1)=1 GROUP BY student_id
    """).fetchall()
    stu_alert = {r["student_id"]: r["ac"] for r in alert_rows}

    # 结果标签
    grad_rows = conn.execute("""
        SELECT student_id, graduated, degree, grad_status
        FROM fact_graduation
    """).fetchall()
    stu_grad = {r["student_id"]: r for r in grad_rows}

    features = []
    for sid, s in students.items():
        gpas = stu_gpas.get(sid, [])
        if len(gpas) < 2:
            continue  # 需要至少两个学期数据

        # 特征
        gpa_trend = gpas[-1] - gpas[0]  # 最后一学期 vs 第一学期
        gpa_drop_count = sum(1 for i in range(1, len(gpas)) if gpas[i] < gpas[i-1] - 0.2)
        latest_gpa = gpas[-1]
        total_fail = stu_fail.get(sid, 0)
        core_fail_count = stu_core_fail.get(sid, 0)
        severe_alert_count = stu_alert.get(sid, 0)

        # 学分完成率
        e = earned.get(sid, 0) or 0
        rq = req_map.get((s["major_id"], s["grade"]))
        credit_ratio = min(e / rq, 1.0) if rq and rq > 0 else 1.0

        # V1.1 时序特征
        # 大一挂科标记（前2学期内挂科次数）
        freshman_fail = sum(1 for i, g in enumerate(gpas[:2])
                          if g < 2.0) if len(gpas) >= 2 else 0
        # 高学分课程挂科（学分>=4的课程挂科次数）
        high_credit_fail = sum(1 for cid, fc in [
            (k, v) for k, v in stu_mod_fail.get(sid, {}).items()
        ] if fc > 0) if stu_mod_fail.get(sid) else 0
        # 同课反复挂科（同一门课挂科次数的最大值）
        from collections import Counter
        fail_courses = Counter()
        for r_data in conn.execute(
            "SELECT course_id FROM fact_grade WHERE student_id=? AND is_pass=0",
            (sid,)).fetchall():
            fail_courses[r_data["course_id"]] += 1
        repeat_fail = max(fail_courses.values()) if fail_courses else 0
        # GPA连续下降最长序列
        consecutive_drop = 0
        cur_drop = 0
        for i in range(1, len(gpas)):
            if gpas[i] < gpas[i-1]:
                cur_drop += 1
                consecutive_drop = max(consecutive_drop, cur_drop)
            else:
                cur_drop = 0
        # 学分完成率骤降（逐个学期计算完成率，检测环比骤降>0.15）
        credit_sudden_drop = 0
        term_credits = []
        for sem in sorted(set(r["semester_id"] for r in
            conn.execute("SELECT DISTINCT semester_id FROM fact_grade WHERE student_id=?",
                         (sid,)).fetchall())):
            e_sem = conn.execute(
                "SELECT SUM(credits) FROM fact_grade WHERE student_id=? AND is_pass=1 AND semester_id<=?",
                (sid, sem)).fetchone()[0] or 0
            term_credits.append(e_sem / rq if rq else 0)
        for i in range(1, len(term_credits)):
            if term_credits[i-1] - term_credits[i] > 0.15:
                credit_sudden_drop = 1
                break

        # 标签（V1.1扩展：含延期毕业和肄业）
        grad = stu_grad.get(sid)
        gs = grad["grad_status"] if grad else ""
        is_positive = (gs in POSITIVE_LABELS or
                       gs in ("结业", "延期毕业", "肄业") or
                       severe_alert_count >= ALERT_THRESHOLD)

        feat = {
            "student_id": sid,
            "gpa_trend": round(gpa_trend, 2),
            "gpa_drop_count": gpa_drop_count,
            "latest_gpa": round(latest_gpa, 2),
            "total_fail": total_fail,
            "core_fail": core_fail_count,
            "credit_ratio": round(credit_ratio, 2),
            "severe_alerts": severe_alert_count,
            "semesters": len(gpas),
            # V1.1 时序特征
            "freshman_fail": freshman_fail,
            "high_credit_fail": high_credit_fail,
            "repeat_fail": repeat_fail,
            "consecutive_drop": consecutive_drop,
            "credit_sudden_drop": credit_sudden_drop,
            "label": 1 if is_positive else 0,
        }
        # 培养方案模块级挂科
        mf = stu_mod_fail.get(sid, {})
        for mod in module_names:
            feat[f"mod_fail_{mod}"] = mf.get(mod, 0)
        features.append(feat)

    return features


def _entropy(vals: list[int]) -> float:
    if not vals:
        return 0
    p = sum(vals) / len(vals)
    if p == 0 or p == 1:
        return 0
    return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def _info_gain(data: list[dict], feature: str, threshold: float) -> float:
    """计算按 feature <= threshold 切分的信息增益。"""
    if not data:
        return 0
    labels = [d["label"] for d in data]
    base_e = _entropy(labels)
    left = [d for d in data if d[feature] <= threshold]
    right = [d for d in data if d[feature] > threshold]
    if not left or not right:
        return 0
    wl = len(left) / len(data)
    wr = len(right) / len(data)
    return base_e - wl * _entropy([d["label"] for d in left]) - wr * _entropy([d["label"] for d in right])


def _risk_ratio(data: list[dict], feature: str, threshold: float) -> tuple[float, int, int]:
    """计算满足条件的样本的风险倍数。"""
    matched = [d for d in data if d[feature] > threshold]
    if not matched:
        return 1.0, 0, 0
    match_pos = sum(1 for d in matched if d["label"] == 1)
    match_rate = match_pos / len(matched) if matched else 0
    overall_pos = sum(1 for d in data if d["label"] == 1)
    overall_rate = overall_pos / len(data) if data else 0
    return round(match_rate / overall_rate, 1) if overall_rate > 0 else 1.0, len(matched), match_pos


def discover() -> list[dict]:
    """运行规则自发现，返回候选规则列表。"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    features = _build_features(conn)
    conn.close()

    if len(features) < 100:
        return []  # 样本量不足

    overall_pos = sum(1 for d in features if d["label"] == 1)
    overall_rate = overall_pos / len(features)

    # 单特征候选（排除循环特征 severe_alerts）
    # (feature, threshold, label, name, is_integer)
    candidates = [
        ("gpa_trend", -0.3, "GPA总降幅", "GPA持续下降（降幅>0.3）", False),
        ("gpa_trend", -0.5, "GPA总降幅", "GPA大幅下降（降幅>0.5）", False),
        ("gpa_drop_count", 1.5, "GPA下滑次数", "GPA多次下滑（≥2次）", True),
        ("total_fail", 3.5, "挂科门次", "挂科累积（≥4门）", True),
        ("total_fail", 5.5, "挂科门次", "挂科严重累积（≥6门）", True),
        ("core_fail", 0.5, "核心课挂科", "核心课挂科（≥1门）", True),
        ("credit_ratio", 0.75, "学分完成率", "学分缺口过大（完成率<75%）", False),
        # V1.1 时序特征候选
        ("freshman_fail", 0.5, "大一挂科", "大一挂科（≥1门）", True),
        ("repeat_fail", 1.5, "同课反复挂科", "同一门课反复挂科（≥2次）", True),
        ("consecutive_drop", 2.5, "GPA连续下降", "GPA连续下降（≥3学期）", True),
        ("credit_sudden_drop", 0.5, "学分骤降", "学分完成率骤降", True),
    ]

    rules = []
    seen_names = set()

    for feat, threshold, label, name, is_int in candidates:
        ratio, sample, pos_count = _risk_ratio(features, feat, threshold)
        if ratio < 2.0 or sample < 30 or pos_count < 5:
            continue

        match_rate = round(pos_count / sample * 100, 1) if sample else 0
        confidence = round(match_rate / 100, 2)
        level = "严重" if ratio >= 5 else ("警告" if ratio >= 3 else "提醒")

        # 整数字段向上取整呈现，避免"≥3.5门"
        display_value = math.ceil(abs(threshold)) if is_int else (abs(threshold) if threshold < 0 else threshold)
        display_op = "≥" if (is_int and threshold > 0) else (">" if threshold > 0 else "<")
        unit = "门" if "fail" in feat or "core_fail" in feat else ("次" if "drop_count" in feat else ("%" if "ratio" in feat else ""))

        if name not in seen_names:
            seen_names.add(name)
            rules.append({
                "name": name,
                "conditions": [
                    {"key": feat, "label": label, "op": display_op,
                     "value": display_value, "unit": unit}
                ],
                "level": level,
                "confidence": confidence,
                "risk_ratio": ratio,
                "sample_size": sample,
                "detail_json": json.dumps({
                    "match_positive": pos_count,
                    "match_total": sample,
                    "match_rate": match_rate,
                    "total_samples": len(features),
                    "overall_rate": round(overall_rate * 100, 1),
                    "overall_positive": overall_pos,
                }, ensure_ascii=False),
            })

    # 复合规则
    combos = [
        (lambda d: d["gpa_trend"] < -0.3 and d["core_fail"] >= 1,
         "GPA持续下降 + 核心课挂科",
         [{"key": "gpa_trend", "label": "GPA总降幅", "op": "<", "value": 0.3, "unit": ""},
          {"key": "core_fail", "label": "核心课挂科", "op": "≥", "value": 1, "unit": "门"}]),
        (lambda d: d["total_fail"] >= 4 and d["credit_ratio"] < 0.75,
         "挂科累积 + 学分缺口",
         [{"key": "total_fail", "label": "累计挂科", "op": "≥", "value": 4, "unit": "门"},
          {"key": "credit_ratio", "label": "学分完成率", "op": "<", "value": 75, "unit": "%"}]),
        (lambda d: d["gpa_drop_count"] >= 2 and d["total_fail"] >= 3,
         "GPA多次下滑 + 挂科累积",
         [{"key": "gpa_drop_count", "label": "GPA下滑次数", "op": "≥", "value": 2, "unit": "次"},
          {"key": "total_fail", "label": "累计挂科", "op": "≥", "value": 3, "unit": "门"}]),
    ]

    for matcher, name, conds in combos:
        matched = [d for d in features if matcher(d)]
        pos = sum(1 for d in matched if d["label"] == 1)
        if len(matched) < 30 or pos < 5:
            continue
        r = round((pos / len(matched)) / overall_rate, 1) if overall_rate > 0 else 1.0
        if r < 2.0:
            continue
        match_rate = round(pos / len(matched) * 100, 1)
        rules.append({
            "name": name,
            "conditions": conds,
            "level": "严重" if r >= 5 else ("警告" if r >= 3 else "提醒"),
            "confidence": round(match_rate / 100, 2),
            "risk_ratio": r,
            "sample_size": len(matched),
            "detail_json": json.dumps({
                "match_positive": pos,
                "match_total": len(matched),
                "match_rate": match_rate,
                "total_samples": len(features),
                "overall_rate": round(overall_rate * 100, 1),
                "overall_positive": overall_pos,
            }, ensure_ascii=False),
        })

    # 培养方案模块级规则（从特征中提取模块挂科列）
    mod_cols = [(k, k.replace("mod_fail_", "")) for k in (features[0] or {}).keys()
                if k.startswith("mod_fail_")]
    for mod_key, mod_name in mod_cols:
        for th in (0.5, 1.5):
            ratio, sample, pos_count = _risk_ratio(features, mod_key, th)
            if ratio < 2.0 or sample < 15 or pos_count < 3:
                continue
            th_int = math.ceil(th)
            name = f"{mod_name}挂科（≥{th_int}门）"
            if name not in seen_names:
                seen_names.add(name)
                match_rate = round(pos_count / sample * 100, 1) if sample else 0
                rules.append({
                    "name": name,
                    "conditions": [
                        {"key": mod_key, "label": f"{mod_name}挂科", "op": "≥",
                         "value": th_int, "unit": "门"}
                    ],
                    "level": "严重" if ratio >= 5 else ("警告" if ratio >= 3 else "提醒"),
                    "confidence": round(match_rate / 100, 2),
                    "risk_ratio": ratio,
                    "sample_size": sample,
                    "detail_json": json.dumps({
                        "match_positive": pos_count, "match_total": sample,
                        "match_rate": match_rate,
                        "total_samples": len(features),
                        "overall_rate": round(overall_rate * 100, 1),
                        "overall_positive": overall_pos,
                    }, ensure_ascii=False),
                })

    rules.sort(key=lambda r: -r["risk_ratio"])
    return rules[:10]


def run_and_save(semester_id: str = "2025-2026-2"):
    """执行发现并写入数据库（去重：相同条件组合不重复写入）。"""
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    # 清理当前学期的旧 pending 记录（重新发现时替换）
    conn.execute("DELETE FROM sys_discovered_rule WHERE semester_id=? AND status='pending'",
                 (semester_id,))

    rules = discover()
    for r in rules:
        cond_str = json.dumps(r["conditions"], ensure_ascii=False)
        # 检查是否已有相同条件的 approved 规则
        existing = conn.execute(
            "SELECT id FROM sys_discovered_rule WHERE conditions=? AND status='approved'",
            (cond_str,)).fetchone()
        if existing:
            continue
        # 检查是否已有相同条件的 pending 规则
        existing = conn.execute(
            "SELECT id FROM sys_discovered_rule WHERE conditions=? AND status='pending'",
            (cond_str,)).fetchone()
        if existing:
            continue  # 本周期已存在，跳过

        conn.execute("""
            INSERT INTO sys_discovered_rule
                (semester_id, name, conditions, level, confidence, risk_ratio,
                 sample_size, detail_json, status, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'ml')
        """, (semester_id, r["name"], cond_str, r["level"],
              r["confidence"], r["risk_ratio"], r["sample_size"],
              r["detail_json"]))

    conn.commit()
    pending = conn.execute(
        "SELECT COUNT(*) c FROM sys_discovered_rule WHERE status='pending'").fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) c FROM sys_discovered_rule WHERE status='approved'").fetchone()[0]
    print(f"规则自发现完成：{len(rules)} 条候选 → {pending} 条待审核，已启用 {approved} 条")
    conn.close()
    return len(rules)


if __name__ == "__main__":
    run_and_save()
