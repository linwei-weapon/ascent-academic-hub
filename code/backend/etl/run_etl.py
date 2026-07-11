"""run_etl 编排：extract_ts(9学期库)→transform→parse_plan→alert→aggregate→
synth_business→real_business→seed→load，最后跑数据校验报告
（行数对账 / 挂科率合理 / 无孤儿外键 / GPA分布合理）。
用法：PYTHONIOENCODING=utf-8 python -X utf8 -m backend.etl.run_etl
"""
import pandas as pd

from . import (config, db, extract_ts, transform, parse_plan,
               alert_engine, aggregate, seed, synth_business)


def build_all_tables():
    """跑完整 ETL，返回 {table_name: DataFrame}（未入库）。"""
    print("① 采集 extract_ts（9 学期时间序列库）…")
    g, t, extras = extract_ts.read_all()
    print(f"   成绩 {len(g)} 行 / 教学任务 {len(t)} 行 / "
          f"当前在校 {len(extras['current_ids'])} / 毕业届 {len(extras['graduating_ids'])}")

    print("② 加工 transform（维表+事实，贯通 9 学期）…")
    dims, maps = transform.build_dims(g, t)
    fg = transform.build_fact_grade(g)
    fl = transform.build_fact_lesson(t)
    allg, alll = fg, fl   # 9 学期全为真实，无模拟增量

    print("③ 解析培养方案 docx（2 专业）…")
    mdf, cdf = parse_plan.parse_all()
    mdf["major_id"] = mdf["major_name"].map(maps["major"])
    cdf["major_id"] = cdf["major_name"].map(maps["major"])
    miss = int(mdf["major_id"].isna().sum())
    if miss:
        print(f"   ⚠ {miss} 个专业名未匹配 dim_major（按名对齐）")
    cdf = cdf[cdf["major_id"].notna()]

    print("④ 预警规则引擎（G1，仅当前在校学生）…")
    rules = seed.build_rules_df()
    # 合并自发现规则（已审核通过但不在 seed 中的）
    discovered_rules = seed.load_discovered_rules()
    if len(discovered_rules):
        rules = pd.concat([rules, discovered_rules], ignore_index=True)
        print(f"   加载 {len(discovered_rules)} 条自发现规则")
    alerts = alert_engine.run_engine(allg, dims["dim_student"], dims["dim_course"], mdf, rules)
    # 只保留当前学期在校学生的预警（往届/已毕业天然排除）
    cur = extras["current_ids"]
    if len(alerts) and cur:
        alerts = alerts[alerts["student_id"].astype(str).isin(cur)].reset_index(drop=True)
    print(f"   预警 {len(alerts)} 条 / 涉及学生 {alerts['student_id'].nunique() if len(alerts) else 0}")

    print("⑤ 预聚合 agg_* （按 9 学期）…")
    aggs = aggregate.build_all(allg, alll, alerts, dims)

    print("⑥ 合成业务表（毕业/考纪/出勤/学分要求/师资画像）…")
    biz = synth_business.build_all(allg, alll, dims, alerts, mdf, extras)
    print(f"   毕业 {len(biz['fact_graduation'])} / 考纪 {len(biz['fact_discipline'])} / "
          f"出勤 {len(biz['fact_attend'])} / 师资画像 {len(biz['fact_teacher_profile'])}")

    print("⑦ 真实业务表（异动/校外考试/调停课，读真源覆盖合成版）…")
    real_biz = extract_ts.build_real_business(extras, maps, dims)
    biz.update(real_biz)
    print(f"   异动 {len(real_biz['fact_attrition'])} / 校外考试 {len(real_biz['fact_exam_cert'])} / "
          f"调停课 {len(real_biz['fact_schedule_change'])}")

    print("⑧ RBAC/规则元数据 seed …")
    sys_tables = seed.build_sys_tables(dims)
    # 合并已审核通过的自发现规则到 sys_alert_rule（避免被 seed 覆盖）
    discovered = seed.load_discovered_rules()
    if len(discovered):
        sys_tables["sys_alert_rule"] = pd.concat(
            [sys_tables["sys_alert_rule"], discovered], ignore_index=True)
        print(f"   保留 {len(discovered)} 条自发现规则")

    tables = {}
    tables.update(dims)                       # 7 dim_
    tables["fact_grade"] = allg               # 9 学期真实
    tables["fact_lesson"] = alll
    tables["fact_plan_course"] = cdf
    tables["fact_plan_meta"] = mdf
    tables["fact_alert"] = alerts
    tables.update(aggs)                        # 6 agg_
    tables.update(biz)                         # 8 业务 fact_
    tables.update(sys_tables)                  # 6 sys_
    return tables


def validate(conn) -> dict:
    """入库后校验：行数 / 挂科率 / 孤儿外键 / GPA分布。返回报告 dict。"""
    rep = {}

    def q1(sql):
        return conn.execute(sql).fetchone()[0]

    # 行数对账
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    rep["counts"] = {n: db.table_count(conn, n) for (n,) in rows}

    # 挂科率（仅真实）
    total = q1("SELECT COUNT(*) FROM fact_grade WHERE source='real' AND is_pass IS NOT NULL")
    failn = q1("SELECT COUNT(*) FROM fact_grade WHERE source='real' AND is_pass=0")
    rep["fail_rate_real"] = round(failn / total * 100, 2) if total else None

    # 模拟挂科率（穿帮自检）
    stot = q1("SELECT COUNT(*) FROM fact_grade WHERE source='sim' AND is_pass IS NOT NULL")
    sfail = q1("SELECT COUNT(*) FROM fact_grade WHERE source='sim' AND is_pass=0")
    rep["fail_rate_sim"] = round(sfail / stot * 100, 2) if stot else None

    # 孤儿外键
    rep["orphans"] = {
        "grade_student": q1("SELECT COUNT(*) FROM fact_grade f "
                            "LEFT JOIN dim_student d ON f.student_id=d.student_id "
                            "WHERE d.student_id IS NULL"),
        "grade_course": q1("SELECT COUNT(*) FROM fact_grade f "
                           "LEFT JOIN dim_course d ON f.course_id=d.course_id "
                           "WHERE f.course_id IS NOT NULL AND d.course_id IS NULL"),
        "alert_student": q1("SELECT COUNT(*) FROM fact_alert f "
                            "LEFT JOIN dim_student d ON f.student_id=d.student_id "
                            "WHERE d.student_id IS NULL"),
        "student_major": q1("SELECT COUNT(*) FROM dim_student s "
                            "LEFT JOIN dim_major m ON s.major_id=m.major_id "
                            "WHERE s.major_id IS NOT NULL AND m.major_id IS NULL"),
    }

    # GPA 范围
    lo = q1("SELECT MIN(gpa) FROM fact_grade WHERE gpa IS NOT NULL")
    hi = q1("SELECT MAX(gpa) FROM fact_grade WHERE gpa IS NOT NULL")
    avg = q1("SELECT AVG(gpa) FROM fact_grade WHERE gpa IS NOT NULL")
    rep["gpa_range"] = (round(lo, 2), round(hi, 2), round(avg, 2))

    # 预警分布
    rep["alert_by_level"] = dict(conn.execute(
        "SELECT level, COUNT(*) FROM fact_alert GROUP BY level").fetchall())
    rep["alert_by_status"] = dict(conn.execute(
        "SELECT status, COUNT(*) FROM fact_alert GROUP BY status").fetchall())

    return rep


def print_report(rep: dict):
    print("\n" + "=" * 56)
    print("数据校验报告")
    print("=" * 56)
    print("\n[行数对账]")
    for n, c in rep["counts"].items():
        print(f"  {n:<22} {c:>8}")
    print(f"\n[挂科率] 真实 {rep['fail_rate_real']}%（合理区间 3-8%） / 模拟 {rep['fail_rate_sim']}%")
    print("[孤儿外键]（应全 0）")
    for k, v in rep["orphans"].items():
        flag = "✓" if v == 0 else "✗"
        print(f"  {flag} {k:<16} {v}")
    print(f"[GPA] min={rep['gpa_range'][0]} max={rep['gpa_range'][1]} avg={rep['gpa_range'][2]}")
    print(f"[预警] 等级 {rep['alert_by_level']}")
    print(f"       状态 {rep['alert_by_status']}")
    ok = (all(v == 0 for v in rep["orphans"].values())
          and rep["fail_rate_real"] and 3.0 <= rep["fail_rate_real"] <= 8.0)
    print("\n结论：", "✓ 通过" if ok else "✗ 存在异常，请核查")
    print("=" * 56)


def main():
    tables = build_all_tables()
    print("\n⑨ 入库 load …")
    conn = db.get_conn()
    db.init_schema(conn)
    from .load import load_all
    counts = load_all(conn, tables)
    print(f"   写入 {sum(counts.values())} 行 / {len(counts)} 表")
    rep = validate(conn)
    print_report(rep)
    conn.close()
    print(f"\n分析库就绪：{config.DB_PATH}")


if __name__ == "__main__":
    main()
