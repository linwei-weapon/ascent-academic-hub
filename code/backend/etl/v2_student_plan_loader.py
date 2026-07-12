"""接入 2022 级学籍、培养方案和方案课程。仅选择业务白名单字段。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from .init_v2 import init_v2
from .v2_master_loader import _code, _hash, _number, _text


STUDENT_FILE = "学籍信息.xlsx"
PLAN_FILE = "专业方案全部计划课程 (1).xlsx"

STUDENT_COLUMNS = (
    "学号", "姓名", "性别", "年级", "学历层次", "专业院系代码", "专业院系",
    "专业代码", "专业", "行政班", "学籍状态", "培养方案", "入学年级", "入学日期",
)
PLAN_COLUMNS = (
    "培养方案名称", "年级", "学历层次", "学生类别", "专业院系", "专业", "专业方向",
    "课程模块", "课程代码", "课程名称", "课程类别", "课程性质", "开课学期", "学分",
    "总学时", "考核方式", "计划课程标识", "是否必修", "开课部门", "备注",
)


def _locate(root: Path, filename: str) -> Path:
    matches = [p for p in root.rglob(filename) if "新增数据" in str(p)]
    if len(matches) != 1:
        raise FileNotFoundError(f"文件不唯一或不存在: {filename}, {matches}")
    return matches[0]


def _read_selected(path: Path, allowed: tuple[str, ...]) -> pd.DataFrame:
    # 两个文件均为两级表头，第二行是业务字段。usecols 确保敏感字段不进入 DataFrame。
    header = pd.read_excel(path, header=1, nrows=0).columns
    available = [name for name in allowed if name in header]
    missing = sorted(set(allowed) - set(available))
    if missing:
        raise ValueError(f"{path.name} 缺少白名单字段: {missing}")
    return pd.read_excel(path, header=1, usecols=available).dropna(how="all")


def plan_id(plan_name: str) -> str:
    return "PLAN-" + hashlib.sha1(plan_name.encode("utf-8")).hexdigest()[:12].upper()


def major_code(value) -> str | None:
    value = _code(value)
    if value and value.isdigit() and len(value) < 5:
        return value.zfill(5)
    return value


def _batch(conn: sqlite3.Connection, code: str, path: Path, row_count: int, accepted: int) -> str:
    file_hash = _hash(path)
    batch_id = f"{code}-{file_hash[:16]}"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO data_batch(batch_id,source_code,source_file,file_hash,ingested_at,row_count,accepted_count,quality_status) "
        "VALUES(?,?,?,?,?,?,?,'accepted') ON CONFLICT(batch_id) DO UPDATE SET ingested_at=excluded.ingested_at,row_count=excluded.row_count,accepted_count=excluded.accepted_count,quality_status='accepted'",
        (batch_id, code, str(path), file_hash, now, row_count, accepted),
    )
    return batch_id


def load_student_plans(root: Path | None = None, db_path: Path | None = None) -> dict:
    root = Path(root or config.V2_SOURCE_ROOT)
    student_path = _locate(root, STUDENT_FILE)
    plan_path = _locate(root, PLAN_FILE)
    students = _read_selected(student_path, STUDENT_COLUMNS)
    plans = _read_selected(plan_path, PLAN_COLUMNS)

    plan_names = sorted({_text(v) for v in plans["培养方案名称"] if _text(v)})
    plan_ids = {name: plan_id(name) for name in plan_names}
    student_plan_names = {_text(v) for v in students["培养方案"] if _text(v)}
    unmatched_plan_names = sorted(student_plan_names - set(plan_names))

    conn = init_v2(db_path)
    try:
        # 方案元数据：当前结构化数据只有 2022 级课程明细，总学分暂不从选修课程简单求和。
        plan_meta = []
        for name in plan_names:
            sample = plans[plans["培养方案名称"].astype(str).str.strip() == name].iloc[0]
            plan_meta.append((plan_ids[name], name, int(_number(sample.get("年级")) or 0),
                              None, _text(sample.get("专业")), None, "2022", "active", "real"))
        conn.executemany(
            "INSERT INTO curriculum_plan(plan_id,plan_name,grade,major_code,major_name,total_credits,version,status,source) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(plan_id) DO UPDATE SET plan_name=excluded.plan_name,grade=excluded.grade,major_code=excluded.major_code,major_name=excluded.major_name,version=excluded.version,status=excluded.status,source='real'",
            plan_meta,
        )

        # 方案课程按本批方案全量替换，保证源文件更正后可重复重建。
        if plan_ids:
            placeholders = ",".join("?" for _ in plan_ids)
            conn.execute(f"DELETE FROM curriculum_plan_course WHERE plan_id IN ({placeholders})", tuple(plan_ids.values()))
        course_rows = []
        for _, row in plans.iterrows():
            pname = _text(row.get("培养方案名称"))
            cid = _code(row.get("课程代码"))
            if not pname or not cid:
                continue
            course_rows.append((plan_ids[pname], cid, _text(row.get("课程模块")),
                                _text(row.get("是否必修")) or _text(row.get("课程性质")),
                                _number(row.get("学分")), _text(row.get("开课学期")),
                                _text(row.get("开课学期")), "real"))
        conn.executemany(
            "INSERT INTO curriculum_plan_course(plan_id,course_id,module,requirement_type,credits,suggested_term,offered_season,source) VALUES(?,?,?,?,?,?,?,?)",
            course_rows,
        )

        student_rows = []
        assignment_rows = []
        for _, row in students.iterrows():
            sid = _code(row.get("学号"))
            if not sid:
                continue
            pname = _text(row.get("培养方案"))
            pid = plan_ids.get(pname)
            student_rows.append((sid, _text(row.get("姓名")), _text(row.get("性别")),
                                 int(_number(row.get("入学年级")) or _number(row.get("年级")) or 0),
                                 _text(row.get("学历层次")), _code(row.get("专业院系代码")),
                                 major_code(row.get("专业代码")), _text(row.get("专业")), _text(row.get("行政班")), pid,
                                 _text(row.get("学籍状态")), _text(row.get("入学日期")), None, "real"))
            if pid:
                assignment_rows.append((sid, pid, _text(row.get("入学日期")) or "2022-01-01", None, "学籍培养方案", "real"))
        conn.executemany(
            "INSERT INTO dim_student(student_id,display_name,gender,entry_grade,education_level,organization_id,major_code,major_name,class_code,plan_id,student_status,valid_from,valid_to,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(student_id) DO UPDATE SET display_name=excluded.display_name,gender=excluded.gender,entry_grade=excluded.entry_grade,education_level=excluded.education_level,organization_id=excluded.organization_id,major_code=excluded.major_code,major_name=excluded.major_name,class_code=excluded.class_code,plan_id=excluded.plan_id,student_status=excluded.student_status,valid_from=excluded.valid_from,source='real'",
            student_rows,
        )
        conn.executemany(
            "INSERT INTO student_plan_assignment(student_id,plan_id,valid_from,valid_to,assignment_reason,source) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(student_id,plan_id,valid_from) DO UPDATE SET valid_to=excluded.valid_to,assignment_reason=excluded.assignment_reason,source='real'",
            assignment_rows,
        )

        conn.execute("DELETE FROM code_mapping WHERE source_system='v2_student_plan_loader' AND domain='student_plan'")
        conn.executemany(
            "INSERT INTO code_mapping(domain,source_system,source_code,mapping_status,note) VALUES('student_plan','v2_student_plan_loader',?,'pending','学生方案未出现在2022级方案课程表')",
            [(name,) for name in unmatched_plan_names],
        )
        _batch(conn, "student_current", student_path, len(students), len(student_rows))
        _batch(conn, "plan_course", plan_path, len(plans), len(course_rows))
        conn.commit()

        report = {
            "students": len(student_rows),
            "plans": len(plan_meta),
            "plan_courses": len(course_rows),
            "student_assignments": len(assignment_rows),
            "student_plan_names": len(student_plan_names),
            "matched_plan_names": len(student_plan_names) - len(unmatched_plan_names),
            "unmatched_plan_names": unmatched_plan_names,
            "students_without_plan": len(student_rows) - len(assignment_rows),
            "plan_courses_missing_course_master": conn.execute("SELECT COUNT(DISTINCT pc.course_id) FROM curriculum_plan_course pc LEFT JOIN dim_course c ON c.course_id=pc.course_id WHERE c.course_id IS NULL").fetchone()[0],
            "students_missing_organization": conn.execute("SELECT COUNT(*) FROM dim_student s LEFT JOIN dim_organization o ON o.organization_id=s.organization_id WHERE s.organization_id IS NOT NULL AND o.organization_id IS NULL").fetchone()[0],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def main() -> None:
    print(json.dumps(load_student_plans(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
