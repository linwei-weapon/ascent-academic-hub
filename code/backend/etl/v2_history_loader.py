"""接入历史学籍、毕业学位结果和学籍异动。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from . import config
from .init_v2 import init_v2
from .v2_master_loader import _code, _date, _hash, _number, _text
from .v2_student_plan_loader import _batch, major_code


HISTORY_FILE = "学籍信息-2021级往届学生.xlsx"
CHANGE_FILE = "异动维护.xlsx"

HISTORY_COLUMNS = (
    "学号", "姓名", "性别", "年级", "学历层次", "专业院系代码", "专业代码", "专业", "行政班",
    "学籍状态", "培养方案", "入学年级", "入学日期", "实际毕业日期", "毕业结论",
    "获得学位类别", "获得学位日期",
)
CHANGE_COLUMNS = (
    "流水号", "学号", "异动类型", "异动原因", "异动说明", "创建时间", "生效时间",
    "异动前学籍状态", "异动后学籍状态", "异动前年级", "异动后年级",
    "异动前管理部门", "异动后管理部门", "异动前专业院系", "异动后专业院系",
    "异动前专业代码", "异动后专业代码", "异动前专业", "异动后专业",
    "异动前行政班", "异动后行政班",
)


def _locate(root: Path, filename: str) -> Path:
    matches = [p for p in root.rglob(filename) if "新增数据" in str(p)]
    if len(matches) != 1:
        raise FileNotFoundError(f"文件不唯一或不存在: {filename}, {matches}")
    return matches[0]


def _read_selected(path: Path, columns: tuple[str, ...], header: int) -> pd.DataFrame:
    actual = pd.read_excel(path, header=header, nrows=0).columns
    missing = sorted(set(columns) - set(actual))
    if missing:
        raise ValueError(f"{path.name} 缺少白名单字段: {missing}")
    return pd.read_excel(path, header=header, usecols=list(columns)).dropna(how="all")


def event_id(flow_id, batch_id: str, source_row_no: int, values: list) -> str:
    flow = _text(flow_id)
    if flow:
        return "STATUS-" + flow
    payload = "|".join([batch_id, str(source_row_no), *[_text(v) or "" for v in values]])
    return "STATUS-H-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()


def load_history(root: Path | None = None, db_path: Path | None = None) -> dict:
    root = Path(root or config.V2_SOURCE_ROOT)
    history_path = _locate(root, HISTORY_FILE)
    change_path = _locate(root, CHANGE_FILE)
    history = _read_selected(history_path, HISTORY_COLUMNS, header=1)
    changes = _read_selected(change_path, CHANGE_COLUMNS, header=0)
    history_hash = _hash(history_path)
    change_hash = _hash(change_path)
    history_batch = f"student_history-{history_hash[:16]}"
    change_batch = f"student_change-{change_hash[:16]}"

    conn = init_v2(db_path)
    try:
        students = []
        outcomes = []
        for _, row in history.iterrows():
            sid = _code(row.get("学号"))
            if not sid:
                continue
            level = _text(row.get("学历层次"))
            org = _code(row.get("专业院系代码"))
            major = major_code(row.get("专业代码"))
            students.append((sid, _text(row.get("姓名")), _text(row.get("性别")),
                             int(_number(row.get("入学年级")) or _number(row.get("年级")) or 0),
                             level, org, major, _text(row.get("专业")), _text(row.get("行政班")), None,
                             _text(row.get("学籍状态")), _date(row.get("入学日期")), None, "real"))
            grad_status = _text(row.get("毕业结论")) or _text(row.get("学籍状态"))
            degree_type = _text(row.get("获得学位类别"))
            degree_status = f"已获{degree_type}学位" if degree_type else (
                "已授学位" if _text(row.get("学籍状态")) == "毕业并授学位" else "未记录授予学位"
            )
            grad_date = _date(row.get("实际毕业日期")) or _date(row.get("获得学位日期"))
            outcomes.append((sid, history_batch, grad_status, degree_status, level, org, major, grad_date, "real"))

        # 当前2022级学籍优先；历史文件只补充尚不存在的学生。
        conn.executemany(
            "INSERT INTO dim_student(student_id,display_name,gender,entry_grade,education_level,organization_id,major_code,major_name,class_code,plan_id,student_status,valid_from,valid_to,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(student_id) DO UPDATE SET major_name=COALESCE(dim_student.major_name,excluded.major_name)",
            students,
        )
        conn.executemany(
            "INSERT INTO graduation_outcome(student_id,audit_batch,graduation_status,degree_status,education_level,organization_id,major_code,graduation_date,source) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(student_id,audit_batch) DO UPDATE SET graduation_status=excluded.graduation_status,degree_status=excluded.degree_status,education_level=excluded.education_level,organization_id=excluded.organization_id,major_code=excluded.major_code,graduation_date=excluded.graduation_date,source='real'",
            outcomes,
        )

        events = []
        for idx, row in changes.iterrows():
            sid = _code(row.get("学号"))
            if not sid:
                continue
            source_row_no = int(idx) + 2
            values = [sid, row.get("异动类型"), row.get("生效时间"), row.get("异动前专业代码"), row.get("异动后专业代码")]
            eid = event_id(row.get("流水号"), change_batch, source_row_no, values)
            events.append((eid, sid, _text(row.get("异动类型")), _text(row.get("异动前学籍状态")),
                           _text(row.get("异动后学籍状态")), _text(row.get("异动前年级")),
                           _text(row.get("异动后年级")), _text(row.get("异动前管理部门")) or _text(row.get("异动前专业院系")),
                           _text(row.get("异动后管理部门")) or _text(row.get("异动后专业院系")),
                           major_code(row.get("异动前专业代码")), major_code(row.get("异动后专业代码")),
                           _text(row.get("异动前专业")), _text(row.get("异动后专业")),
                           _text(row.get("异动前行政班")), _text(row.get("异动后行政班")),
                           _text(row.get("异动原因")), _text(row.get("异动说明")),
                           _date(row.get("生效时间")) or _date(row.get("创建时间")),
                           change_batch, source_row_no, "real"))
        conn.executemany(
            "INSERT INTO student_status_event(event_id,student_id,event_type,before_status,after_status,before_grade,after_grade,before_organization,after_organization,before_major_code,after_major_code,before_major_name,after_major_name,before_class_code,after_class_code,event_reason,event_note,effective_at,batch_id,source_row_no,source) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET student_id=excluded.student_id,event_type=excluded.event_type,before_status=excluded.before_status,after_status=excluded.after_status,before_grade=excluded.before_grade,after_grade=excluded.after_grade,before_organization=excluded.before_organization,after_organization=excluded.after_organization,before_major_code=excluded.before_major_code,after_major_code=excluded.after_major_code,before_major_name=excluded.before_major_name,after_major_name=excluded.after_major_name,before_class_code=excluded.before_class_code,after_class_code=excluded.after_class_code,event_reason=excluded.event_reason,event_note=excluded.event_note,effective_at=excluded.effective_at,source='real'",
            events,
        )
        # 异动覆盖了当前/往届学籍快照之外的学生（主要为2020级）。为保证成长事件可关联，
        # 仅以真实异动记录补建最小学生存根，不虚构姓名、专业或组织。
        event_only_students = conn.execute(
            "SELECT COUNT(DISTINCT e.student_id) FROM student_status_event e "
            "LEFT JOIN dim_student s ON s.student_id=e.student_id WHERE e.batch_id=? AND s.student_id IS NULL",
            (change_batch,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO dim_student(student_id,entry_grade,student_status,source) "
            "SELECT student_id,CASE WHEN substr(student_id,1,4) GLOB '[0-9][0-9][0-9][0-9]' THEN CAST(substr(student_id,1,4) AS INTEGER) END,COALESCE(after_status,before_status),'real_partial' "
            "FROM (SELECT e.*,ROW_NUMBER() OVER(PARTITION BY e.student_id ORDER BY COALESCE(e.effective_at,'') DESC,e.source_row_no DESC) rn FROM student_status_event e WHERE e.batch_id=?) x "
            "WHERE rn=1 AND NOT EXISTS(SELECT 1 FROM dim_student s WHERE s.student_id=x.student_id)",
            (change_batch,),
        )
        _batch(conn, "student_history", history_path, len(history), len(students))
        _batch(conn, "student_change", change_path, len(changes), len(events))
        conn.commit()

        report = {
            "history_students": len(students),
            "graduation_outcomes": len(outcomes),
            "status_events": len(events),
            "status_event_students": conn.execute("SELECT COUNT(DISTINCT student_id) FROM student_status_event WHERE batch_id=?", (change_batch,)).fetchone()[0],
            "events_without_source_flow_id": int(changes["流水号"].isna().sum()),
            "events_without_before_after_status": int(((changes["异动前学籍状态"].isna()) & (changes["异动后学籍状态"].isna())).sum()),
            "event_orphan_students": conn.execute("SELECT COUNT(*) FROM student_status_event e LEFT JOIN dim_student s ON s.student_id=e.student_id WHERE e.batch_id=? AND s.student_id IS NULL", (change_batch,)).fetchone()[0],
            "event_only_student_stubs": conn.execute("SELECT COUNT(DISTINCT s.student_id) FROM dim_student s JOIN student_status_event e ON e.student_id=s.student_id WHERE e.batch_id=? AND s.source='real_partial'", (change_batch,)).fetchone()[0],
            "undergraduate_history": int((history["学历层次"] == "本科").sum()),
            "degree_recorded": int(history["获得学位类别"].notna().sum()),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def main() -> None:
    print(json.dumps(load_history(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
