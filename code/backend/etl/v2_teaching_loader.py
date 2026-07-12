"""接入教师、班主任、导师和2023-2024-1教学任务，并构建排课聚合。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from . import config
from .init_v2 import init_v2
from .v2_master_loader import _code, _date, _number, _text
from .v2_student_plan_loader import _batch

TASK_SEMESTER = "2023-2024-1"
WEEKDAYS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}


def _locate(root: Path, filename: str, preferred: str) -> Path:
    matches = [p for p in root.rglob(filename) if preferred in str(p)]
    if len(matches) != 1:
        raise FileNotFoundError(f"文件不唯一或不存在: {filename}, {matches}")
    return matches[0]


def _read(path: Path, columns: tuple[str, ...]) -> pd.DataFrame:
    actual = pd.read_excel(path, nrows=0).columns
    missing = sorted(set(columns) - set(actual))
    if missing:
        raise ValueError(f"{path.name} 缺少字段: {missing}")
    return pd.read_excel(path, usecols=list(columns)).dropna(how="all")


def placeholder_staff_id(name: str, role: str) -> str:
    return f"{role.upper()}-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:16].upper()


def parse_schedule(raw) -> list[dict]:
    text = _text(raw)
    if not text:
        return []
    results = []
    for part in re.split(r";\s*", text):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"^(.*?)周\s+星期([一二三四五六日])\s+(\d+)~(\d+)节\s+(\S+)\s+(\S+)\s+(.+)$", part)
        if match:
            results.append({"week_pattern": match.group(1).strip(), "weekday": WEEKDAYS[match.group(2)],
                            "period_start": int(match.group(3)), "period_end": int(match.group(4)),
                            "campus": match.group(5), "room": match.group(6),
                            "teacher": match.group(7).strip(), "raw": part})
    return results


def day_part(period_start: int) -> str:
    return "morning" if period_start <= 4 else ("afternoon" if period_start <= 8 else "evening")


def load_teaching(root: Path | None = None, db_path: Path | None = None) -> dict:
    root = Path(root or config.V2_SOURCE_ROOT)
    teacher_path = _locate(root, "正式教师.xlsx", "新增数据")
    adviser_path = _locate(root, "行政班班主任.xlsx", "20260712")
    mentor_path = _locate(root, "学生导师库.xls", "20260712")
    task_path = _locate(root, "教学任务-历史学期.xls", "新增数据")
    teachers = _read(teacher_path, ("工号", "中文名称", "所属部门", "教师职称", "教师类型", "是否授课", "是否在职"))
    advisers = _read(adviser_path, ("行政班代码", "行政班名称", "班主任", "所属院系", "职称"))
    mentors = _read(mentor_path, ("学号", "导师类型", "导师工号", "导师姓名", "导师所属部门", "教师职称", "指导开始日期", "指导结束日期", "发布状态", "是否有效"))
    tasks = _read(task_path, ("课程代码", "课程名称", "教学班代码", "开课部门", "总学时", "理论学时", "实验学时", "实践学时", "授课教师", "教师工号", "教师所属部门", "职称", "日期时间地点人员", "上课年级", "上课专业", "上课行政班", "选课人数上限", "已选学生数"))
    conn = init_v2(db_path)
    try:
        name_to_ids: dict[str, list[str]] = {}; teacher_rows = []
        for _, row in teachers.iterrows():
            staff_id = _code(row.get("工号")); name = _text(row.get("中文名称"))
            if not staff_id: continue
            org_name = _text(row.get("所属部门")); found = conn.execute("SELECT organization_id FROM dim_organization WHERE name=?", (org_name,)).fetchone()
            teacher_rows.append((staff_id, name, found[0] if found else org_name, _text(row.get("教师类型")), _text(row.get("教师职称")), _text(row.get("是否在职")), "real"))
            if name: name_to_ids.setdefault(name, []).append(staff_id)
        conn.executemany("INSERT INTO dim_staff(staff_id,display_name,organization_id,staff_type,title,status,source) VALUES(?,?,?,?,?,?,?) ON CONFLICT(staff_id) DO UPDATE SET display_name=excluded.display_name,organization_id=excluded.organization_id,staff_type=excluded.staff_type,title=excluded.title,status=excluded.status,source='real'", teacher_rows)

        mentor_scopes = []
        for _, row in mentors.iterrows():
            if _text(row.get("是否有效")) != "是" or _text(row.get("发布状态")) != "已发布": continue
            sid = _code(row.get("学号")); staff_id = _code(row.get("导师工号"))
            if not sid or not staff_id: continue
            conn.execute("INSERT INTO dim_staff(staff_id,display_name,organization_id,staff_type,title,status,source) VALUES(?,?,?,?,?,'active','real') ON CONFLICT(staff_id) DO UPDATE SET display_name=COALESCE(dim_staff.display_name,excluded.display_name),title=COALESCE(dim_staff.title,excluded.title)", (staff_id, _text(row.get("导师姓名")), _text(row.get("导师所属部门")), "mentor", _text(row.get("教师职称"))))
            mentor_scopes.append((staff_id, sid, _text(row.get("导师类型")) or "mentor", _date(row.get("指导开始日期")) or "2024-03-11", _date(row.get("指导结束日期")), "real"))
        conn.executemany("INSERT INTO staff_student_scope(staff_id,student_id,relation_type,valid_from,valid_to,source) VALUES(?,?,?,?,?,?) ON CONFLICT(staff_id,student_id,relation_type,valid_from) DO UPDATE SET valid_to=excluded.valid_to,source='real'", mentor_scopes)

        adviser_scopes = []; placeholder_classes = 0
        for _, row in advisers.iterrows():
            name = _text(row.get("班主任")); class_name = _text(row.get("行政班名称"))
            if not name or not class_name: continue
            ids = name_to_ids.get(name, [])
            staff_id = ids[0] if len(ids) == 1 else placeholder_staff_id(name, "adviser")
            if len(ids) != 1:
                placeholder_classes += 1
                conn.execute("INSERT INTO dim_staff(staff_id,display_name,organization_id,staff_type,title,status,source) VALUES(?,?,?,?,?,'active','real_partial') ON CONFLICT(staff_id) DO NOTHING", (staff_id, name, _text(row.get("所属院系")), "class_adviser", _text(row.get("职称"))))
            adviser_scopes.extend((staff_id, sid, "class_adviser", "2022-09-01", None, "real") for (sid,) in conn.execute("SELECT student_id FROM dim_student WHERE class_code=?", (class_name,)))
        conn.executemany("INSERT INTO staff_student_scope(staff_id,student_id,relation_type,valid_from,valid_to,source) VALUES(?,?,?,?,?,?) ON CONFLICT(staff_id,student_id,relation_type,valid_from) DO NOTHING", adviser_scopes)

        lessons = []; lesson_teachers = []; meetings = []; unparsed = 0
        for _, row in tasks.iterrows():
            lesson_code = _code(row.get("教学班代码")); course_id = _code(row.get("课程代码"))
            if not lesson_code: continue
            lesson_id = f"{TASK_SEMESTER}:{lesson_code}"; schedule = _text(row.get("日期时间地点人员"))
            lessons.append((lesson_id, lesson_code, TASK_SEMESTER, course_id, _text(row.get("课程名称")), _text(row.get("开课部门")), int(_number(row.get("选课人数上限")) or 0), int(_number(row.get("已选学生数")) or 0), _number(row.get("总学时")), _number(row.get("理论学时")), _number(row.get("实验学时")), _number(row.get("实践学时")), _text(row.get("上课年级")), _text(row.get("上课专业")), _text(row.get("上课行政班")), schedule, None, "active", "real"))
            ids = [x.strip() for x in re.split(r"[;,]", _text(row.get("教师工号")) or "") if x.strip()]
            names = [x.strip() for x in re.split(r"[;,]", _text(row.get("授课教师")) or "") if x.strip()]
            for pos, staff_id in enumerate(ids):
                if not conn.execute("SELECT 1 FROM dim_staff WHERE staff_id=?", (staff_id,)).fetchone():
                    conn.execute("INSERT INTO dim_staff(staff_id,display_name,organization_id,staff_type,title,status,source) VALUES(?,?,?,?,?,'active','real_partial')", (staff_id, names[pos] if pos < len(names) else None, _text(row.get("教师所属部门")), "lesson_teacher", _text(row.get("职称"))))
                lesson_teachers.append((lesson_id, staff_id, "teacher", None, "real"))
            parsed = parse_schedule(schedule)
            if schedule and not parsed: unparsed += 1
            for pos, item in enumerate(parsed):
                mid = "MEET-" + hashlib.sha256(f"{lesson_id}|{pos}|{item['raw']}".encode()).hexdigest()[:20].upper()
                room = conn.execute("SELECT room_id FROM dim_room WHERE name=?", (item["room"],)).fetchone()
                meetings.append((mid, lesson_id, None, item["week_pattern"], item["weekday"], None, item["period_start"], item["period_end"], room[0] if room else None, None, "scheduled", item["raw"], "real"))
        conn.executemany("INSERT INTO teaching_lesson(lesson_id,source_lesson_code,semester_id,course_id,course_name,organization_id,capacity,enrolled,total_hours,theory_hours,experiment_hours,practice_hours,student_grade,majors_text,classes_text,schedule_text,location_text,status,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(lesson_id) DO UPDATE SET course_id=excluded.course_id,course_name=excluded.course_name,capacity=excluded.capacity,enrolled=excluded.enrolled,total_hours=excluded.total_hours,schedule_text=excluded.schedule_text,source='real'", lessons)
        conn.executemany("INSERT INTO lesson_teacher(lesson_id,staff_id,role,workload_hours,source) VALUES(?,?,?,?,?) ON CONFLICT(lesson_id,staff_id,role) DO UPDATE SET source='real'", lesson_teachers)
        conn.executemany("INSERT INTO course_meeting(meeting_id,lesson_id,week_no,week_pattern,weekday,period_id,period_start,period_end,room_id,meeting_date,status,raw_schedule,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(meeting_id) DO UPDATE SET room_id=excluded.room_id,status=excluded.status,raw_schedule=excluded.raw_schedule,source='real'", meetings)

        conn.execute("DELETE FROM agg_course_offering WHERE semester_id=?", (TASK_SEMESTER,)); conn.execute("INSERT INTO agg_course_offering SELECT l.semester_id,l.course_id,COUNT(DISTINCT l.lesson_id),COUNT(DISTINCT lt.staff_id),SUM(COALESCE(l.enrolled,0)),SUM(COALESCE(l.total_hours,0)),'derived' FROM teaching_lesson l LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id WHERE l.semester_id=? GROUP BY l.semester_id,l.course_id", (TASK_SEMESTER,))
        conn.execute("DELETE FROM agg_course_team WHERE semester_id=?", (TASK_SEMESTER,)); conn.execute("INSERT INTO agg_course_team SELECT l.semester_id,l.course_id,COUNT(DISTINCT lt.staff_id),COUNT(DISTINCT CASE WHEN s.title='教授' THEN lt.staff_id END),COUNT(DISTINCT CASE WHEN s.title='副教授' THEN lt.staff_id END),COUNT(DISTINCT CASE WHEN s.title='讲师' THEN lt.staff_id END),COUNT(DISTINCT CASE WHEN s.title IS NULL OR s.title IN ('未知','无') THEN lt.staff_id END),'derived' FROM teaching_lesson l JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id WHERE l.semester_id=? GROUP BY l.semester_id,l.course_id", (TASK_SEMESTER,))
        conn.execute("DELETE FROM agg_teacher_schedule_preference WHERE semester_id=?", (TASK_SEMESTER,)); conn.execute("INSERT INTO agg_teacher_schedule_preference SELECT l.semester_id,lt.staff_id,m.weekday,CASE WHEN m.period_start<=4 THEN 'morning' WHEN m.period_start<=8 THEN 'afternoon' ELSE 'evening' END,COUNT(DISTINCT m.meeting_id),COUNT(DISTINCT l.course_id),'derived' FROM course_meeting m JOIN teaching_lesson l ON l.lesson_id=m.lesson_id JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id WHERE l.semester_id=? GROUP BY l.semester_id,lt.staff_id,m.weekday,CASE WHEN m.period_start<=4 THEN 'morning' WHEN m.period_start<=8 THEN 'afternoon' ELSE 'evening' END", (TASK_SEMESTER,))
        _batch(conn, "teacher", teacher_path, len(teachers), len(teacher_rows)); _batch(conn, "class_adviser", adviser_path, len(advisers), len(adviser_scopes)); _batch(conn, "student_adviser", mentor_path, len(mentors), len(mentor_scopes)); _batch(conn, "lesson", task_path, len(tasks), len(lessons)); conn.commit()
        report = {"teachers": len(teacher_rows), "mentor_scopes": len(mentor_scopes), "class_adviser_scopes": len(adviser_scopes), "placeholder_adviser_classes": placeholder_classes, "lessons": len(lessons), "lesson_teachers": len(lesson_teachers), "meetings": len(meetings), "unparsed_schedule_lessons": unparsed, "course_offerings": conn.execute("SELECT COUNT(*) FROM agg_course_offering WHERE semester_id=?", (TASK_SEMESTER,)).fetchone()[0], "course_teams": conn.execute("SELECT COUNT(*) FROM agg_course_team WHERE semester_id=?", (TASK_SEMESTER,)).fetchone()[0], "teacher_preference_cells": conn.execute("SELECT COUNT(*) FROM agg_teacher_schedule_preference WHERE semester_id=?", (TASK_SEMESTER,)).fetchone()[0]}
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    return report


def main() -> None:
    print(json.dumps(load_teaching(), ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
