"""加工 transform：清洗 + 维表生成 + 事实表构建。
输入：成绩 DataFrame、教学任务 DataFrame。
输出：dict[str, DataFrame]，列名已对齐 schema.sql。
口径依据 逐页规格书 §0.3 / 数据字典.md。
"""
import re
import pandas as pd

from . import config

# 教师串解析："李**(2061)" 多个用 , ; ； 、 分隔
_TEACHER_RE = re.compile(r"([^,;；、()]+?)\(([^)]+)\)")
# 教室利用率："四教206(67%)" → (四教206, 0.67)
_UTIL_RE = re.compile(r"([^();；\s]+)\((\d+)%\)")


def _to_num(s):
    return pd.to_numeric(s, errors="coerce")


def parse_semester(sem: str):
    """'2025-2026-1' → ('2025-2026', 1)"""
    if not isinstance(sem, str):
        return (None, None)
    parts = sem.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return (parts[0], int(parts[1]))
    return (sem, None)


def _id_map(values, prefix, width):
    """对去重后的有序值生成稳定编码 {value: 'C01'}。"""
    uniq = sorted(v for v in values if pd.notna(v) and str(v).strip())
    return {v: f"{prefix}{i+1:0{width}d}" for i, v in enumerate(uniq)}


# ---------------------------------------------------------------------
# 维表
# ---------------------------------------------------------------------
def build_dims(g: pd.DataFrame, t: pd.DataFrame):
    dims = {}

    # --- dim_college ---
    college_map = _id_map(g["管理部门"].dropna().unique(), "C", 2)
    dims["dim_college"] = pd.DataFrame(
        [{"college_id": cid, "name": name, "source_name": name, "source": "real"}
         for name, cid in college_map.items()]
    )

    # --- dim_major（管理部门→专业）---
    mj = g[["管理部门", "专业"]].dropna().drop_duplicates()
    major_map = _id_map(mj["专业"].unique(), "M", 3)
    dims["dim_major"] = pd.DataFrame(
        [{"major_id": major_map[r["专业"]],
          "college_id": college_map.get(r["管理部门"]),
          "name": r["专业"], "source": "real"}
         for _, r in mj.iterrows()]
    ).drop_duplicates("major_id")

    # --- dim_class（专业+年级+行政班）---
    cl = g[["专业", "年级", "行政班"]].dropna(subset=["行政班"]).drop_duplicates()
    class_map = _id_map(cl["行政班"].unique(), "B", 4)
    dims["dim_class"] = pd.DataFrame(
        [{"class_id": class_map[r["行政班"]],
          "major_id": major_map.get(r["专业"]),
          "grade": str(r["年级"]) if pd.notna(r["年级"]) else None,
          "name": r["行政班"], "source": "real"}
         for _, r in cl.iterrows()]
    ).drop_duplicates("class_id")

    # --- dim_semester ---
    sems = sorted(g["学期"].dropna().unique())
    dims["dim_semester"] = pd.DataFrame(
        [{"semester_id": s, "year": parse_semester(s)[0], "term": parse_semester(s)[1],
          "is_current": 1 if s == config.CURRENT_SEMESTER else 0, "source": "real"}
         for s in sems]
    )

    # --- dim_student（取每个学号最新学期记录）---
    gs = g.dropna(subset=["学号"]).copy()
    gs["学号"] = gs["学号"].astype(str)
    gs = gs.sort_values("学期")
    latest = gs.groupby("学号", as_index=False).last()
    dims["dim_student"] = pd.DataFrame(
        [{"student_id": r["学号"], "name": r["姓名"],
          "college_id": college_map.get(r["管理部门"]),
          "major_id": major_map.get(r["专业"]),
          "class_id": class_map.get(r["行政班"]),
          "grade": str(r["年级"]) if pd.notna(r["年级"]) else None,
          "enroll_on": None, "status": "在籍", "source": "real"}
         for _, r in latest.iterrows()]
    )

    # --- dim_teacher（教学任务为主，成绩教师串补充）---
    teachers = {}
    for _, r in t.iterrows():
        ids = [x.strip() for x in re.split(r"[;,；、]", str(r.get("教师工号", ""))) if x.strip()]
        names = [x.strip() for x in re.split(r"[;,；、]", str(r.get("授课教师", ""))) if x.strip()]
        dept = r.get("教师所属部门") or None
        title = r.get("职称") or None
        for i, tid in enumerate(ids):
            nm = names[i] if i < len(names) else (names[0] if names else None)
            teachers.setdefault(tid, {"teacher_id": tid, "name": nm,
                                      "dept": dept, "title": title, "source": "real"})
    # 成绩教师串补漏（无职称）
    for cell in g["教师"].dropna().unique():
        for nm, tid in _TEACHER_RE.findall(str(cell)):
            teachers.setdefault(tid.strip(), {"teacher_id": tid.strip(), "name": nm.strip(),
                                              "dept": None, "title": None, "source": "real"})
    dims["dim_teacher"] = pd.DataFrame(list(teachers.values()))

    # --- dim_course（成绩 ∪ 教学任务，教学任务补元数据）---
    course = {}
    # 成绩侧：名称 + 必修多数票
    gc = g[["课程代码", "课程名称", "是否必修"]].dropna(subset=["课程代码"])
    for code, grp in gc.groupby("课程代码"):
        name = grp["课程名称"].dropna().iloc[0] if grp["课程名称"].notna().any() else None
        req = 1 if (grp["是否必修"] == "必修").mean() >= 0.5 else 0
        course[code] = {"course_id": code, "name": name, "credits": None,
                        "category": None, "course_nature": None, "is_required": req,
                        "dept": None, "source": "real"}
    # 教学任务侧补：学分/类别/性质/开课部门
    for _, r in t.iterrows():
        code = r.get("课程代码")
        if not code or pd.isna(code):
            continue
        c = course.setdefault(code, {"course_id": code, "name": r.get("课程名称"),
                                     "credits": None, "category": None, "course_nature": None,
                                     "is_required": None, "dept": None, "source": "real"})
        if c.get("name") is None:
            c["name"] = r.get("课程名称")
        c["credits"] = c["credits"] or _to_num(pd.Series([r.get("学分")]))[0]
        c["category"] = c["category"] or (r.get("课程类别") or None)
        c["course_nature"] = c["course_nature"] or (r.get("课程性质") or None)
        c["dept"] = c["dept"] or (r.get("开课部门") or None)
    dims["dim_course"] = pd.DataFrame(list(course.values()))

    maps = {"college": college_map, "major": major_map, "class": class_map}
    return dims, maps


# ---------------------------------------------------------------------
# 事实表
# ---------------------------------------------------------------------
def build_fact_grade(g: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame()
    df["student_id"] = g["学号"].astype(str)
    df["course_id"] = g["课程代码"]
    df["lesson_id"] = g["教学班代码"]
    df["semester_id"] = g["学期"]
    df["score"] = _to_num(g["得分"])
    df["level"] = g["等级"]
    df["gpa"] = _to_num(g["绩点"])
    tp = g["是否通过"]
    df["is_pass"] = tp.map(lambda v: 1 if v == "通过" else (None if pd.isna(v) or str(v).strip() == "" else 0))
    df["is_required"] = (g["是否必修"] == "必修").astype("Int64")
    df["is_retake"] = (g["是否重修"] == "重修").astype("Int64")
    df["credits"] = _to_num(g["学分"])
    # 考试情况：补考标记(补考/缓考)，无标记=正常考试
    df["exam_status"] = g["补考标记"].map(lambda v: v if isinstance(v, str) and v.strip() else "正常")
    df["source"] = "real"
    return df


def _parse_util(text):
    """'四教206(67%); 三教502机房(67%)' → 平均利用率(0-1) + 主教室。"""
    if not isinstance(text, str):
        return (None, None)
    found = _UTIL_RE.findall(text)
    if not found:
        return (None, None)
    pcts = [int(p) for _, p in found]
    return (sum(pcts) / len(pcts) / 100.0, found[0][0])


def build_fact_lesson(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in t.iterrows():
        lid = r.get("教学班代码")
        if not lid or pd.isna(lid):
            continue
        sem = r.get("学期")  # 时间序列：每行教学任务自带学期
        util, room = _parse_util(r.get("教室利用率"))
        tids = [x.strip() for x in re.split(r"[;,；、]", str(r.get("教师工号", ""))) if x.strip()]
        rows.append({
            "lesson_id": lid, "semester_id": sem, "course_id": r.get("课程代码"),
            "teacher_id": tids[0] if tids else None,
            "teacher_ids": ";".join(tids) if tids else None,
            "capacity": _to_num(pd.Series([r.get("选课人数上限")]))[0],
            "enrolled": _to_num(pd.Series([r.get("已选学生数")]))[0],
            "retake_count": _to_num(pd.Series([r.get("重修人数")]))[0],
            "total_hours": _to_num(pd.Series([r.get("总学时")]))[0],
            "theory_hours": _to_num(pd.Series([r.get("理论学时")]))[0],
            "exp_hours": _to_num(pd.Series([r.get("实验学时")]))[0],
            "practice_hours": _to_num(pd.Series([r.get("实践学时")]))[0],
            "lab_hours": _to_num(pd.Series([r.get("上机学时")]))[0],
            "classroom": room, "utilization": util,
            "campus": r.get("授课校区") or None,
            "class_names": r.get("上课行政班") or None,
            "source": "real",
        })
    df = pd.DataFrame(rows)
    # 同一(教学班,学期)去重，保留首行
    return df.drop_duplicates(subset=["lesson_id", "semester_id"], keep="first")
