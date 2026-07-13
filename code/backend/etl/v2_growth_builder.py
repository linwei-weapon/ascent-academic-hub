"""构建方案课程状态、成长指标、困难标签和标准时间线。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .init_v2 import init_v2
from .v2_grade_loader import RULE_VERSION


GROWTH_VERSION = "growth-v1"
CURRENT_STUDY_TERM = 8


def term_number(value) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() and 1 <= int(text) <= 20 else None


def _status_id(student_id: str, plan_course_id: int) -> str:
    return "PCS-" + hashlib.sha256(f"{student_id}|{plan_course_id}|{GROWTH_VERSION}".encode()).hexdigest()[:24].upper()


def build_growth(db_path: Path | None = None) -> dict:
    conn = init_v2(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("DELETE FROM student_plan_course_status WHERE rule_version=?", (GROWTH_VERSION,))
        source_rows = conn.execute(
            "SELECT a.student_id,a.plan_id,pc.plan_course_id,pc.course_id,pc.module,pc.requirement_type,pc.suggested_term,"
            "r.effective_attempt_id,r.effective_score,r.is_pass,r.earned_credits,"
            "CASE WHEN sub.substitution_id IS NOT NULL THEN 1 ELSE 0 END recognized "
            "FROM student_plan_assignment a JOIN curriculum_plan_course pc ON pc.plan_id=a.plan_id "
            "LEFT JOIN student_course_result r ON r.student_id=a.student_id AND r.course_id=pc.course_id AND r.rule_version=? "
            "LEFT JOIN student_course_substitution sub ON sub.student_id=a.student_id AND sub.original_course_id=pc.course_id AND sub.approval_status='通过' AND sub.workflow_status='流程已结束'",
            (RULE_VERSION,),
        ).fetchall()
        status_rows = []
        for row in source_rows:
            (sid, pid, pcid, cid, module, required, suggested, attempt, score, passed, credits, recognized) = row
            if recognized:
                status = "recognized"
            elif passed == 1:
                status = "passed"
            elif passed == 0:
                status = "failed"
            elif passed is None and attempt:
                status = "unknown"
            else:
                status = "not_completed"
            # “成绩中未出现”只能作为候选缺口；缺少选课/认定全量时不能直接触发困难标签。
            # 只有存在明确未通过成绩的必修课程才是可行动缺口。
            actionable = int(required == "必修" and status == "failed")
            suggested_no = term_number(suggested)
            # 到期只表示建议修读学期已过且尚无完成证据；与“明确可行动”分开。
            # failed 可直接形成重修核查，not_completed/unknown 只能进入选课/认定核验。
            overdue = int(status not in {"passed", "recognized"} and suggested_no is not None
                          and suggested_no < CURRENT_STUDY_TERM)
            status_rows.append((_status_id(sid, pcid), sid, pid, pcid, cid, module, required,
                                suggested, status, actionable, overdue, attempt, score,
                                credits or (0 if status not in {"passed", "recognized"} else None),
                                GROWTH_VERSION, now, "derived"))
        conn.executemany(
            "INSERT INTO student_plan_course_status(status_id,student_id,plan_id,plan_course_id,course_id,module,requirement_type,suggested_term,completion_status,is_actionable,is_overdue,effective_attempt_id,effective_score,earned_credits,rule_version,calculated_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            status_rows,
        )

        conn.execute("DELETE FROM student_growth_indicator WHERE indicator_version=?", (GROWTH_VERSION,))
        students = [row[0] for row in conn.execute("SELECT student_id FROM dim_student")]
        growth_rows = []
        for sid in students:
            course = conn.execute(
                "SELECT SUM(CASE WHEN is_pass=1 THEN 1 ELSE 0 END),SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END),SUM(CASE WHEN is_pass=1 THEN COALESCE(earned_credits,0) ELSE 0 END) FROM student_course_result WHERE student_id=? AND rule_version=?",
                (sid, RULE_VERSION),
            ).fetchone()
            avg_gpa = conn.execute("SELECT AVG(gpa) FROM grade_attempt WHERE student_id=? AND is_published=1 AND is_void=0 AND gpa IS NOT NULL", (sid,)).fetchone()[0]
            retakes = conn.execute("SELECT COUNT(*) FROM grade_attempt WHERE student_id=? AND attempt_type='retake'", (sid,)).fetchone()[0]
            plan = conn.execute(
                "SELECT SUM(CASE WHEN requirement_type='必修' THEN 1 ELSE 0 END),SUM(CASE WHEN requirement_type='必修' AND completion_status IN ('passed','recognized') THEN 1 ELSE 0 END),SUM(CASE WHEN requirement_type='必修' AND completion_status NOT IN ('passed','recognized') THEN 1 ELSE 0 END),SUM(CASE WHEN is_overdue=1 THEN 1 ELSE 0 END) FROM student_plan_course_status WHERE student_id=? AND rule_version=?",
                (sid, GROWTH_VERSION),
            ).fetchone()
            events = conn.execute("SELECT COUNT(*) FROM student_status_event WHERE student_id=?", (sid,)).fetchone()[0]
            growth_rows.append((sid, GROWTH_VERSION, *(int(v or 0) for v in course[:2]), float(course[2] or 0), avg_gpa,
                                retakes, *(int(v or 0) for v in plan), events, now, "derived"))
        conn.executemany(
            "INSERT INTO student_growth_indicator(student_id,indicator_version,passed_courses,failed_courses,earned_credits,avg_gpa,retake_attempts,required_courses,required_completed,required_missing,overdue_required,status_events,calculated_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            growth_rows,
        )

        conn.execute("DELETE FROM student_difficulty_flag WHERE flag_version=?", (GROWTH_VERSION,))
        # 当前多门未通过。
        conn.execute(
            "INSERT INTO student_difficulty_flag(student_id,flag_code,flag_version,severity,evidence_count,evidence_json,calculated_at,source) "
            "SELECT student_id,'multiple_current_failures',?,CASE WHEN COUNT(*)>=3 THEN 'high' ELSE 'medium' END,COUNT(*),json_object('failed_courses',COUNT(*)),?,'derived' FROM student_course_result WHERE rule_version=? AND is_pass=0 GROUP BY student_id HAVING COUNT(*)>=2",
            (GROWTH_VERSION, now, RULE_VERSION),
        )
        # 同一课程存在两次及以上未通过尝试。
        conn.execute(
            "INSERT INTO student_difficulty_flag(student_id,flag_code,flag_version,severity,evidence_count,evidence_json,calculated_at,source) "
            "SELECT student_id,'repeated_course_failure',?,'high',SUM(fail_count),json_object('courses',COUNT(*),'failed_attempts',SUM(fail_count)),?,'derived' FROM (SELECT student_id,course_id,COUNT(*) fail_count FROM grade_attempt WHERE is_published=1 AND is_pass=0 GROUP BY student_id,course_id HAVING COUNT(*)>=2) x GROUP BY student_id",
            (GROWTH_VERSION, now),
        )
        # 必修课程缺口。
        conn.execute(
            "INSERT INTO student_difficulty_flag(student_id,flag_code,flag_version,severity,evidence_count,evidence_json,calculated_at,source) "
            "SELECT student_id,'required_course_gap',?,CASE WHEN COUNT(*)>=5 THEN 'high' ELSE 'medium' END,COUNT(*),json_object('required_missing',COUNT(*),'overdue',SUM(is_overdue)),?,'derived' FROM student_plan_course_status WHERE rule_version=? AND is_actionable=1 GROUP BY student_id HAVING COUNT(*)>0",
            (GROWTH_VERSION, now, GROWTH_VERSION),
        )

        # 标准时间线：异动、学期成绩摘要、毕业学位。
        conn.execute("DELETE FROM student_timeline_event")
        conn.execute(
            "INSERT INTO student_timeline_event(event_id,student_id,event_type,event_date,title,detail_json,source_ref,source) "
            "SELECT 'TL-STATUS-'||event_id,student_id,'status_change',effective_at,event_type,json_object('before_status',before_status,'after_status',after_status,'before_major',before_major_name,'after_major',after_major_name,'reason',event_reason),event_id,'real' FROM student_status_event"
        )
        conn.execute(
            "INSERT INTO student_timeline_event(event_id,student_id,event_type,semester_id,title,detail_json,source_ref,source) "
            "SELECT 'TL-TERM-'||student_id||'-'||semester_id,student_id,'semester_result',semester_id,'学期学习结果',json_object('courses',COUNT(DISTINCT course_id),'failed',SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END),'passed',SUM(CASE WHEN is_pass=1 THEN 1 ELSE 0 END),'avg_score',ROUND(AVG(score),2)),NULL,'derived' FROM grade_attempt WHERE is_published=1 GROUP BY student_id,semester_id"
        )
        conn.execute(
            "INSERT INTO student_timeline_event(event_id,student_id,event_type,event_date,title,detail_json,source_ref,source) "
            "SELECT 'TL-GRAD-'||student_id||'-'||audit_batch,student_id,'graduation',graduation_date,'毕业与学位结果',json_object('graduation_status',graduation_status,'degree_status',degree_status),audit_batch,'real' FROM graduation_outcome"
        )
        conn.commit()
        report = {
            "plan_course_status_rows": len(status_rows),
            "plan_students": conn.execute("SELECT COUNT(DISTINCT student_id) FROM student_plan_course_status").fetchone()[0],
            "passed": conn.execute("SELECT COUNT(*) FROM student_plan_course_status WHERE rule_version=? AND completion_status='passed'", (GROWTH_VERSION,)).fetchone()[0],
            "recognized": conn.execute("SELECT COUNT(*) FROM student_plan_course_status WHERE rule_version=? AND completion_status='recognized'", (GROWTH_VERSION,)).fetchone()[0],
            "failed": conn.execute("SELECT COUNT(*) FROM student_plan_course_status WHERE rule_version=? AND completion_status='failed'", (GROWTH_VERSION,)).fetchone()[0],
            "required_missing": conn.execute("SELECT COUNT(*) FROM student_plan_course_status WHERE rule_version=? AND is_actionable=1", (GROWTH_VERSION,)).fetchone()[0],
            "required_gap_candidates": conn.execute("SELECT COUNT(*) FROM student_plan_course_status WHERE rule_version=? AND requirement_type='必修' AND completion_status NOT IN ('passed','recognized')", (GROWTH_VERSION,)).fetchone()[0],
            "growth_students": len(growth_rows),
            "difficulty_flags": conn.execute("SELECT COUNT(*) FROM student_difficulty_flag WHERE flag_version=?", (GROWTH_VERSION,)).fetchone()[0],
            "flagged_students": conn.execute("SELECT COUNT(DISTINCT student_id) FROM student_difficulty_flag WHERE flag_version=?", (GROWTH_VERSION,)).fetchone()[0],
            "timeline_events": conn.execute("SELECT COUNT(*) FROM student_timeline_event").fetchone()[0],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def main() -> None:
    print(json.dumps(build_growth(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
