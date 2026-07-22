"""接入课程替代、2021级成绩尝试并生成版本化有效课程结果。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from .init_v2 import init_v2
from .run_log import run_logged, should_skip_logging
from .v2_master_loader import _code, _date, _hash, _number, _text
from .v2_student_plan_loader import _batch


GRADE_FILE = "2021级学生成绩.xlsx"
SUBSTITUTION_FILE = "课程替代.xlsx"
RULE_VERSION = "grade-effective-v1"

GRADE_COLUMNS = (
    "学期", "学号", "课程代码", "课程名称", "被替代课程代码", "被替代课程名称",
    "教学班代码", "学分", "是否必修", "是否重修", "是否及格重修", "得分", "等级",
    "绩点", "是否通过", "发布状态", "总评成绩", "补考成绩", "缓考成绩", "加分成绩",
    "补考标记", "备注",
)
SUBSTITUTION_COLUMNS = (
    "学号", "原课程", "替代课程", "申请时间", "审核结果", "流程状态", "完成时间",
)


def _locate(root: Path, filename: str, preferred: str) -> Path:
    matches = [p for p in root.rglob(filename) if preferred in str(p)]
    if len(matches) != 1:
        raise FileNotFoundError(f"文件不唯一或不存在: {filename}, {matches}")
    return matches[0]


def _read_selected(path: Path, columns: tuple[str, ...], header: int, sheet_name=0) -> pd.DataFrame:
    actual = pd.read_excel(path, sheet_name=sheet_name, header=header, nrows=0).columns
    missing = sorted(set(columns) - set(actual))
    if missing:
        raise ValueError(f"{path.name} 缺少白名单字段: {missing}")
    return pd.read_excel(path, sheet_name=sheet_name, header=header, usecols=list(columns)).dropna(how="all")


def parse_course_reference(value) -> tuple[str | None, str | None, float | None]:
    text = _text(value)
    if not text:
        return None, None, None
    matches = list(re.finditer(r"\(([^()]+)\)", text))
    code = matches[-1].group(1).strip() if matches else None
    name = text[:matches[-1].start()].strip() if matches else text
    tail = text[matches[-1].end():] if matches else ""
    credits = _number(tail)
    return code, name, credits


def attempt_id(batch_id: str, source_row_no: int) -> str:
    payload = f"{batch_id}|{source_row_no}"
    return "GRADE-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24].upper()


def _bool_pass(value, score) -> int | None:
    text = _text(value)
    if text in {"通过", "是", "及格"}:
        return 1
    if text in {"未通过", "否", "不及格"}:
        return 0
    number = _number(score)
    return None if number is None else int(number >= 60)


def _attempt_type(row: pd.Series) -> str:
    if _text(row.get("是否重修")) not in {None, "正常", "否"}:
        return "retake"
    if _number(row.get("补考成绩")) is not None or _text(row.get("补考标记")):
        return "makeup"
    if _number(row.get("缓考成绩")) is not None:
        return "deferred"
    return "regular"


def _load_grades(root: Path | None = None, db_path: Path | None = None) -> dict:
    root = Path(root or config.V2_SOURCE_ROOT)
    grade_path = _locate(root, GRADE_FILE, "新增数据")
    substitution_path = _locate(root, SUBSTITUTION_FILE, "20260712")
    grades = _read_selected(grade_path, GRADE_COLUMNS, header=0, sheet_name="Sheet1")
    substitutions = _read_selected(substitution_path, SUBSTITUTION_COLUMNS, header=1, sheet_name="Sheet1")
    grade_batch = f"grade-{_hash(grade_path)[:16]}"
    sub_batch = f"substitution-{_hash(substitution_path)[:16]}"

    conn = init_v2(db_path)
    try:
        # 课程替代只将审核通过且流程结束的记录作为生效事实，其余仍可在源批次追溯。
        sub_rows = []
        for idx, row in substitutions.iterrows():
            if _text(row.get("审核结果")) != "通过" or _text(row.get("流程状态")) != "流程已结束":
                continue
            sid = _code(row.get("学号"))
            original_id, original_name, original_credits = parse_course_reference(row.get("原课程"))
            substitute_id, substitute_name, substitute_credits = parse_course_reference(row.get("替代课程"))
            if not sid or not original_id or not substitute_id:
                continue
            source_row_no = int(idx) + 3
            sub_id = "SUB-" + hashlib.sha256(f"{sub_batch}|{source_row_no}".encode()).hexdigest()[:20].upper()
            sub_rows.append((sub_id, sid, original_id, original_name, substitute_id, substitute_name,
                             original_credits or substitute_credits, "通过", "流程已结束",
                             _date(row.get("完成时间")) or _date(row.get("申请时间")), "real"))
        conn.executemany(
            "INSERT INTO student_course_substitution(substitution_id,student_id,original_course_id,original_course_name,substitute_course_id,substitute_course_name,recognized_credits,approval_status,workflow_status,approved_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(substitution_id) DO UPDATE SET approval_status=excluded.approval_status,workflow_status=excluded.workflow_status,approved_at=excluded.approved_at,source='real'",
            sub_rows,
        )
        conn.execute(
            "INSERT INTO dim_student(student_id,entry_grade,source) "
            "SELECT DISTINCT x.student_id,CASE WHEN substr(x.student_id,1,4) GLOB '[0-9][0-9][0-9][0-9]' THEN CAST(substr(x.student_id,1,4) AS INTEGER) END,'real_partial' "
            "FROM student_course_substitution x WHERE NOT EXISTS(SELECT 1 FROM dim_student s WHERE s.student_id=x.student_id)"
        )

        attempt_rows = []
        for idx, row in grades.iterrows():
            sid = _code(row.get("学号"))
            cid = _code(row.get("课程代码"))
            if not sid or not cid:
                continue
            source_row_no = int(idx) + 2
            score = _number(row.get("得分"))
            if score is None:
                score = _number(row.get("总评成绩"))
            published_status = _text(row.get("发布状态"))
            attempt_rows.append((attempt_id(grade_batch, source_row_no), sid, cid,
                                 _text(row.get("课程名称")), _code(row.get("被替代课程代码")),
                                 _text(row.get("被替代课程名称")), _code(row.get("教学班代码")),
                                 _text(row.get("学期")), _attempt_type(row), _text(row.get("是否必修")),
                                 _number(row.get("学分")), score, _number(row.get("总评成绩")),
                                 _number(row.get("补考成绩")), _number(row.get("缓考成绩")),
                                 _number(row.get("加分成绩")), _text(row.get("等级")),
                                 _number(row.get("绩点")), _bool_pass(row.get("是否通过"), score),
                                 1 if published_status == "已发布" else 0, published_status, 0,
                                 None, grade_batch, source_row_no, "real"))
        conn.executemany(
            "INSERT INTO grade_attempt(attempt_id,student_id,course_id,course_name,replaced_course_id,replaced_course_name,lesson_id,semester_id,attempt_type,requirement_type,credits,score,total_score,makeup_score,deferred_score,bonus_score,grade_level,gpa,is_pass,is_published,publish_status,is_void,previous_attempt_id,batch_id,source_row_no,source) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET score=excluded.score,total_score=excluded.total_score,makeup_score=excluded.makeup_score,deferred_score=excluded.deferred_score,bonus_score=excluded.bonus_score,grade_level=excluded.grade_level,gpa=excluded.gpa,is_pass=excluded.is_pass,is_published=excluded.is_published,publish_status=excluded.publish_status,is_void=excluded.is_void,source='real'",
            attempt_rows,
        )

        # 成绩中存在少量未进入当前/往届学籍快照的学生。仅补建学号存根，避免虚构画像。
        conn.execute(
            "INSERT INTO dim_student(student_id,entry_grade,source) "
            "SELECT DISTINCT g.student_id,CASE WHEN substr(g.student_id,1,4) GLOB '[0-9][0-9][0-9][0-9]' THEN CAST(substr(g.student_id,1,4) AS INTEGER) END,'real_partial' "
            "FROM grade_attempt g WHERE g.batch_id=? AND NOT EXISTS(SELECT 1 FROM dim_student s WHERE s.student_id=g.student_id)",
            (grade_batch,),
        )

        # 规则V1：只看已发布且未作废；有通过记录时优先通过并取最高分，否则取最新学期记录。
        conn.execute("DELETE FROM student_course_result WHERE rule_version=?", (RULE_VERSION,))
        calculated_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO student_course_result(student_id,course_id,rule_version,effective_attempt_id,effective_score,is_pass,earned_credits,result_basis,calculated_at,source) "
            "SELECT student_id,course_id,?,attempt_id,score,is_pass,CASE WHEN is_pass=1 THEN credits ELSE 0 END,CASE WHEN is_pass=1 THEN 'published-pass-highest-score' ELSE 'published-latest-failure' END,?,'derived' "
            "FROM (SELECT g.*,ROW_NUMBER() OVER(PARTITION BY student_id,course_id ORDER BY CASE WHEN is_pass=1 THEN 1 ELSE 0 END DESC,CASE WHEN is_pass=1 THEN COALESCE(score,-999) END DESC,semester_id DESC,source_row_no DESC) rn FROM grade_attempt g WHERE is_published=1 AND is_void=0) ranked WHERE rn=1",
            (RULE_VERSION, calculated_at),
        )
        _batch(conn, "grade", grade_path, len(grades), len(attempt_rows))
        _batch(conn, "substitution", substitution_path, len(substitutions), len(sub_rows))
        conn.commit()

        report = {
            "grade_attempts": len(attempt_rows),
            "grade_students": int(grades["学号"].nunique()),
            "grade_courses": int(grades["课程代码"].nunique()),
            "published_attempts": conn.execute("SELECT COUNT(*) FROM grade_attempt WHERE batch_id=? AND is_published=1", (grade_batch,)).fetchone()[0],
            "retake_attempts": conn.execute("SELECT COUNT(*) FROM grade_attempt WHERE batch_id=? AND attempt_type='retake'", (grade_batch,)).fetchone()[0],
            "effective_results": conn.execute("SELECT COUNT(*) FROM student_course_result WHERE rule_version=?", (RULE_VERSION,)).fetchone()[0],
            "effective_failures": conn.execute("SELECT COUNT(*) FROM student_course_result WHERE rule_version=? AND is_pass=0", (RULE_VERSION,)).fetchone()[0],
            "effective_unknown_pass": conn.execute("SELECT COUNT(*) FROM student_course_result WHERE rule_version=? AND is_pass IS NULL", (RULE_VERSION,)).fetchone()[0],
            "grade_orphan_students": conn.execute("SELECT COUNT(DISTINCT g.student_id) FROM grade_attempt g LEFT JOIN dim_student s ON s.student_id=g.student_id WHERE g.batch_id=? AND s.student_id IS NULL", (grade_batch,)).fetchone()[0],
            "grade_only_student_stubs": conn.execute("SELECT COUNT(DISTINCT s.student_id) FROM dim_student s JOIN grade_attempt g ON g.student_id=s.student_id WHERE g.batch_id=? AND s.source='real_partial' AND NOT EXISTS(SELECT 1 FROM student_status_event e WHERE e.student_id=s.student_id)", (grade_batch,)).fetchone()[0],
            "grade_courses_missing_master": conn.execute("SELECT COUNT(DISTINCT g.course_id) FROM grade_attempt g LEFT JOIN dim_course c ON c.course_id=g.course_id WHERE g.batch_id=? AND c.course_id IS NULL", (grade_batch,)).fetchone()[0],
            "approved_substitutions": len(sub_rows),
            "substitution_orphan_students": conn.execute("SELECT COUNT(*) FROM student_course_substitution x LEFT JOIN dim_student s ON s.student_id=x.student_id WHERE s.student_id IS NULL").fetchone()[0],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def load_grades(root: Path | None = None, db_path: Path | None = None,
                triggered_by: str = "manual") -> dict:
    """公共入口：接入成绩尝试与课程替代并重建有效结果，运行结果落 etl_run。"""
    if should_skip_logging(db_path):
        return _load_grades(root, db_path)
    with run_logged("v2_grade_loader", db_path,
                    triggered_by=triggered_by, source="loader") as run:
        report = _load_grades(root, db_path)
        run["rows_written"] = sum(int(report.get(key) or 0) for key in (
            "grade_attempts", "approved_substitutions", "effective_results",
        ))
        run["checks"] = report
        return report


def main() -> None:
    print(json.dumps(load_grades(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
