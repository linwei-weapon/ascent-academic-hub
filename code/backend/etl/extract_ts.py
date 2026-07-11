"""时间序列抽取 extract_ts：从 构造数据/ 的 9 个按学期 SQLite 库读原始业务数据，
映射为下游 transform 期望的中文列 schema（与原单 Excel 口径对齐），贯通 9 学期。

产出：
  read_all() → (g, t, extras)
    g  : 成绩事实源（9 学期并表），列对齐 transform.build_dims/build_fact_grade。
    t  : 教学任务源（9 学期并表，含「学期」列），列对齐 transform.build_fact_lesson。
    extras: dict
      current_ids        : 当前学期(CURRENT_SEMESTER) 在校学生 id 集合（在校快照）
      graduating_ids     : 当前在校且年级=毕业届(2022) 的学生 id 集合
      student_changes    : 异动日志（9 学期并表，原始列）
      external_exams     : 校外考试（9 学期并表，原始列）
      course_changes     : 调停课（9 学期并表，原始列）+ 关联 task 的 teacher/课程

  build_real_business(extras, maps, dims) → dict
    用真实源构造 fact_attrition / fact_exam_cert / fact_schedule_change，
    替换 synth_business 的合成版本（plan §1.6：能用真表的改读真表）。
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

# 构造数据目录（9 个学期库）。交接包版统一走 config.TS_DIR（指向 datasource/构造数据，
# 可用环境变量 TS_DIR 覆盖），不再用旧的 PROJECT_DIR 同级硬路径。
TS_DIR = config.TS_DIR

SEMESTERS = [
    "2021-2022-2", "2022-2023-1", "2022-2023-2",
    "2023-2024-1", "2023-2024-2", "2024-2025-1",
    "2024-2025-2", "2025-2026-1", "2025-2026-2",
]


def _read_table(conn, name, cols=None):
    sel = "*" if cols is None else ",".join(cols)
    try:
        return pd.read_sql(f"SELECT {sel} FROM {name}", conn)
    except Exception:
        return pd.DataFrame()


def read_all(ts_dir=None):
    """读 9 学期库 → (g, t, extras)。"""
    ts_dir = Path(ts_dir or TS_DIR)
    g_parts, t_parts = [], []
    sc_parts, ee_parts, cc_parts = [], [], []
    current_ids, graduating_ids = set(), set()

    for sem in SEMESTERS:
        db = ts_dir / f"{sem}.db"
        if not db.exists():
            continue
        conn = sqlite3.connect(str(db))
        try:
            scores = _read_table(conn, "scores")
            students = _read_table(conn, "students")
            tasks = _read_table(conn, "teaching_tasks")
            teachers = _read_table(conn, "teachers")
            rooms = _read_table(conn, "rooms")
            courses = _read_table(conn, "courses")
            schanges = _read_table(conn, "student_changes")
            exams = _read_table(conn, "external_exams")
            cchanges = _read_table(conn, "course_changes")
        finally:
            conn.close()

        # 当前学期在校快照
        if sem == config.CURRENT_SEMESTER and not students.empty:
            cur = students[["student_id", "grade_year"]].copy()
            current_ids = set(cur["student_id"].astype(str))
            grad_year = str(config.GRADUATING_GRADE)
            graduating_ids = set(
                cur[cur["grade_year"].astype(str) == grad_year]["student_id"].astype(str))

        # ---- 成绩源 g：scores ⋈ students ⋈ teaching_tasks ----
        if not scores.empty:
            sinfo = students[["student_id", "name", "major", "class_name",
                              "grade_year", "college"]].copy()
            sinfo["student_id"] = sinfo["student_id"].astype(str)
            tinfo = tasks[["task_id", "course_nature", "teacher_id", "teacher_name"]].copy()
            gp = scores.copy()
            gp["student_id"] = gp["student_id"].astype(str)
            gp = gp.merge(sinfo, on="student_id", how="left")
            gp = gp.merge(tinfo, on="task_id", how="left")
            gframe = pd.DataFrame({
                "学号": gp["student_id"],
                "姓名": gp["name"],
                "管理部门": gp["college"],
                "专业": gp["major"],
                "年级": gp["grade_year"],
                "行政班": gp["class_name"],
                "学期": gp["semester"],
                "课程代码": gp["course_code"],
                "课程名称": gp["course_name"],
                "教学班代码": gp["task_id"],
                "得分": gp["total_score"],
                "等级": None,
                "绩点": gp["gpa"],
                "是否通过": np.where(pd.to_numeric(gp["total_score"], errors="coerce") >= 60,
                                 "通过", "不通过"),
                "是否必修": np.where(gp["course_nature"] == "必修", "必修", "选修"),
                "是否重修": np.where(gp["is_retake"] == 1, "重修", ""),
                "学分": gp["credits"],
                "补考标记": np.where(gp["is_retake"] == 1, "补考", ""),
                "教师": gp["teacher_name"].fillna("").astype(str) + "(" +
                       gp["teacher_id"].fillna("").astype(str) + ")",
            })
            g_parts.append(gframe)

        # ---- 教学任务源 t：teaching_tasks ⋈ teachers ⋈ rooms ⋈ courses ----
        if not tasks.empty:
            tk = tasks.copy()
            teach = teachers[["teacher_id", "department", "title"]].copy()
            tk = tk.merge(teach, on="teacher_id", how="left")
            rm = rooms[["room_id", "name", "campus", "capacity"]].rename(
                columns={"name": "room_name"})
            tk = tk.merge(rm, on="room_id", how="left")
            co = courses[["course_code", "college"]].rename(columns={"college": "course_college"})
            co = co.dropna(subset=["course_code"]).drop_duplicates(subset=["course_code"])
            tk = tk.merge(co, on="course_code", how="left")
            cap = pd.to_numeric(tk["capacity"], errors="coerce")
            scnt = pd.to_numeric(tk["student_count"], errors="coerce")
            pct = np.where((cap > 0), (scnt / cap * 100).round().fillna(0), 0).astype(int)
            util_str = tk["room_name"].fillna("").astype(str) + "(" + pd.Series(pct).astype(str) + "%)"
            tframe = pd.DataFrame({
                "教师工号": tk["teacher_id"],
                "授课教师": tk["teacher_name"],
                "教师所属部门": tk["department"],
                "职称": tk["title"],
                "课程代码": tk["course_code"],
                "课程名称": tk["course_name"],
                "学分": tk["credits"],
                "课程类别": tk["course_type"],
                "课程性质": tk["course_nature"],
                "开课部门": tk["course_college"],
                "教学班代码": tk["task_id"],
                "教室利用率": util_str,
                "选课人数上限": tk["capacity"],
                "已选学生数": tk["student_count"],
                "重修人数": np.where(tk["is_retake_task"] == 1, tk["student_count"], 0),
                "总学时": tk["hours"],
                "理论学时": tk["theory_hours"],
                "实验学时": tk["lab_hours"],
                "实践学时": tk["practice_hours"],
                "上机学时": tk["computer_hours"],
                "授课校区": tk["campus"],
                "上课行政班": tk["class_name"],
                "学期": tk["semester"],
            })
            t_parts.append(tframe)

        if not schanges.empty:
            sc_parts.append(schanges)
        if not exams.empty:
            ee_parts.append(exams)
        if not cchanges.empty:
            # 关联 task 拿 teacher/课程/学院/规模
            ccx = cchanges.merge(
                tasks[["task_id", "teacher_id", "course_code", "student_count", "hours"]],
                on="task_id", how="left")
            ccx = ccx.merge(
                courses[["course_code", "college"]].dropna(subset=["course_code"])
                .drop_duplicates(subset=["course_code"]),
                on="course_code", how="left")
            cc_parts.append(ccx)

    g = pd.concat(g_parts, ignore_index=True) if g_parts else pd.DataFrame()
    t = pd.concat(t_parts, ignore_index=True) if t_parts else pd.DataFrame()
    extras = {
        "current_ids": current_ids,
        "graduating_ids": graduating_ids,
        "student_changes": pd.concat(sc_parts, ignore_index=True) if sc_parts else pd.DataFrame(),
        "external_exams": pd.concat(ee_parts, ignore_index=True) if ee_parts else pd.DataFrame(),
        "course_changes": pd.concat(cc_parts, ignore_index=True) if cc_parts else pd.DataFrame(),
    }
    return g, t, extras


# ---------------------------------------------------------------------
# 真实业务表（替换 synth 合成版）
# ---------------------------------------------------------------------
def build_real_business(extras, maps, dims) -> dict:
    """用真实源构造 fact_attrition / fact_exam_cert / fact_schedule_change。"""
    out = {}
    college_map = maps["college"]
    major_map = maps["major"]
    ds = dims["dim_student"].set_index("student_id")

    # ---- fact_attrition ← student_changes ----
    sc = extras["student_changes"]
    rows = []
    if not sc.empty:
        for _, r in sc.iterrows():
            sid = str(r["student_id"])
            kind = r.get("change_type") or None
            college = r.get("new_college") or r.get("old_college")
            major = r.get("new_major") or r.get("old_major")
            grade = r.get("new_grade") or r.get("old_grade")
            cid = college_map.get(college)
            mid = major_map.get(major)
            if cid is None and sid in ds.index:
                cid = ds.loc[sid, "college_id"]
            if mid is None and sid in ds.index:
                mid = ds.loc[sid, "major_id"]
            rows.append({
                "student_id": sid, "grade": str(grade) if pd.notna(grade) else None,
                "major_id": mid, "college_id": cid, "kind": kind,
                "reason": r.get("change_type") or "学籍异动",
                "semester_id": r.get("semester"), "source": "real",
            })
    out["fact_attrition"] = pd.DataFrame(rows, columns=[
        "student_id", "grade", "major_id", "college_id", "kind",
        "reason", "semester_id", "source"])

    # ---- fact_exam_cert ← external_exams（当前在校学生，跨学期取曾通过）----
    ee = extras["external_exams"]
    current_ids = extras["current_ids"]
    rows = []
    if not ee.empty:
        ee = ee.copy()
        ee["student_id"] = ee["student_id"].astype(str)
        ee["passed"] = pd.to_numeric(ee["is_passed"], errors="coerce").fillna(0).astype(int)

        def _passed(grp, key):
            sub = grp[grp["exam_type"].astype(str).str.contains(key, na=False)]
            return int((sub["passed"] == 1).any())

        keep = ee[ee["student_id"].isin(current_ids)] if current_ids else ee
        for sid, grp in keep.groupby("student_id"):
            cid = ds.loc[sid, "college_id"] if sid in ds.index else None
            rows.append({
                "student_id": sid, "college_id": cid,
                "cet4": _passed(grp, "四级"),
                "cet6": _passed(grp, "六级"),
                "ncre2": _passed(grp, "计算机二级"),
                "ncre3": _passed(grp, "计算机三级"),
                "source": "real",
            })
    out["fact_exam_cert"] = pd.DataFrame(rows, columns=[
        "student_id", "college_id", "cet4", "cet6", "ncre2", "ncre3", "source"])

    # ---- fact_schedule_change ← course_changes ----
    cc = extras["course_changes"]
    rows = []
    if not cc.empty:
        for _, r in cc.iterrows():
            cid = college_map.get(r.get("college"))
            ctype = str(r.get("change_type") or "")
            kind = "停课" if "停课" in ctype else "调课"
            # 月份：apply_time / change 日期 'YYYY-MM-DD ...'
            month = None
            for col in ("apply_time",):
                v = r.get(col)
                if isinstance(v, str) and len(v) >= 7 and v[5:7].isdigit():
                    month = int(v[5:7])
                    break
            hours = pd.to_numeric(r.get("hours"), errors="coerce")
            hours = int(hours) if pd.notna(hours) else 0
            hours = hours if hours in (2, 4, 6, 8) else (2 if hours <= 2 else (4 if hours <= 4 else 6))
            affected = pd.to_numeric(r.get("student_count"), errors="coerce")
            affected = int(affected) if pd.notna(affected) else 0
            auto = 1 if hours <= 4 else 0
            status = str(r.get("status") or "")
            rows.append({
                "teacher_id": r.get("teacher_id"), "college_id": cid,
                "kind": kind, "reason": r.get("reason") or "教学调整",
                "month": month, "hours": hours, "affected": max(affected, 1),
                "auto_approved": auto,
                "review_days": round(0.6 if auto else 2.2, 1),
                "semester_id": r.get("semester"), "source": "real",
            })
    out["fact_schedule_change"] = pd.DataFrame(rows, columns=[
        "teacher_id", "college_id", "kind", "reason", "month", "hours",
        "affected", "auto_approved", "review_days", "semester_id", "source"])

    return out


if __name__ == "__main__":
    g, t, ex = read_all()
    print("g 行", len(g), "| t 行", len(t))
    print("学期枚举 g:", sorted(g["学期"].dropna().unique().tolist()))
    print("当前在校", len(ex["current_ids"]), "| 毕业届", len(ex["graduating_ids"]))
    print("异动", len(ex["student_changes"]), "| 校外考试", len(ex["external_exams"]),
          "| 调停课", len(ex["course_changes"]))
