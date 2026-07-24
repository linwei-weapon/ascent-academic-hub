"""构建方案课程状态、成长指标、困难标签和标准时间线。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .init_v2 import init_v2
from .v2_grade_loader import RULE_VERSION


GROWTH_VERSION = "growth-v1"


def current_study_term(entry_grade: int | str | None,
                       at: datetime | None = None) -> int | None:
    """按入学年和当前校历位置推导学习学期，当前学期本身不算逾期。"""
    try:
        grade = int(entry_grade)
    except (TypeError, ValueError):
        return None
    now = at or datetime.now()
    if now.month >= 9:
        academic_start, semester_in_year = now.year, 1
    elif now.month <= 2:
        academic_start, semester_in_year = now.year - 1, 1
    else:
        academic_start, semester_in_year = now.year - 1, 2
    value = (academic_start - grade) * 2 + semester_in_year
    return max(1, min(value, 20))


def term_number(value) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() and 1 <= int(text) <= 20 else None


def _status_id(student_id: str, plan_course_id: int) -> str:
    return "PCS-" + hashlib.sha256(f"{student_id}|{plan_course_id}|{GROWTH_VERSION}".encode()).hexdigest()[:24].upper()


def _module_key(value: object) -> str:
    return re.sub(r"[\s（）()、，,·—_\-]+", "", str(value or "")).lower()


_CN_NUMBER = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _choice_minimum(text: object) -> int | None:
    match = re.search(r"([一二三四五六七八九十\d]+)\s*选\s*([一二三四五六七八九十\d]+)", str(text or ""))
    if not match:
        return None
    raw = match.group(2)
    return int(raw) if raw.isdigit() else _CN_NUMBER.get(raw)


def _best_module_rule(module_name: str, rules: list[dict]) -> dict | None:
    key = _module_key(module_name)
    exact = [rule for rule in rules if _module_key(rule.get("module_name")) == key]
    if exact:
        return exact[-1]
    candidates = []
    for rule in rules:
        rule_key = _module_key(rule.get("module_name"))
        hierarchy_key = _module_key(rule.get("raw_hierarchy"))
        if rule_key and (rule_key in key or key in rule_key):
            candidates.append((len(rule_key), rule))
        elif hierarchy_key and key and key in hierarchy_key:
            candidates.append((len(rule_key), rule))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def build_growth(db_path: Path | None = None) -> dict:
    conn = init_v2(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("DELETE FROM student_plan_course_status WHERE rule_version=?", (GROWTH_VERSION,))
        source_rows = conn.execute(
            "SELECT a.student_id,a.plan_id,pc.plan_course_id,pc.course_id,pc.module,pc.requirement_type,pc.suggested_term,"
            "r.effective_attempt_id,r.effective_score,r.is_pass,r.earned_credits,pc.credits,"
            "s.entry_grade,p.grade,s.major_name,p.major_name,"
            "CASE WHEN sub.substitution_id IS NOT NULL THEN 1 ELSE 0 END recognized "
            "FROM student_plan_assignment a JOIN curriculum_plan_course pc ON pc.plan_id=a.plan_id "
            "JOIN dim_student s ON s.student_id=a.student_id "
            "JOIN curriculum_plan p ON p.plan_id=a.plan_id "
            "LEFT JOIN student_course_result r ON r.student_id=a.student_id AND r.course_id=pc.course_id AND r.rule_version=? "
            "LEFT JOIN student_course_substitution sub ON sub.student_id=a.student_id AND sub.original_course_id=pc.course_id AND sub.approval_status='通过' AND sub.workflow_status='流程已结束'",
            (RULE_VERSION,),
        ).fetchall()
        status_rows = []
        binding_mismatches: dict[tuple[str, str], tuple[int | None, int | None]] = {}
        for row in source_rows:
            (sid, pid, pcid, cid, module, required, suggested, attempt, score, passed,
             earned_credits, plan_credits, entry_grade, plan_grade, student_major,
             plan_major, recognized) = row
            if (entry_grade is None or plan_grade is None or int(entry_grade) != int(plan_grade)
                    or not student_major or not plan_major
                    or str(student_major).strip() != str(plan_major).strip()):
                binding_mismatches[(sid, pid)] = (entry_grade, plan_grade)
                continue
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
            study_term = current_study_term(entry_grade)
            # 到期只表示建议修读学期已过且尚无完成证据；与“明确可行动”分开。
            # failed 可直接形成重修核查，not_completed/unknown 只能进入选课/认定核验。
            overdue = int(status not in {"passed", "recognized"} and suggested_no is not None
                          and study_term is not None and suggested_no < study_term)
            effective_credits = earned_credits
            if status == "recognized" and effective_credits is None:
                effective_credits = plan_credits
            if status not in {"passed", "recognized"}:
                effective_credits = 0
            status_rows.append((_status_id(sid, pcid), sid, pid, pcid, cid, module, required,
                                suggested, status, actionable, overdue, attempt, score,
                                effective_credits,
                                GROWTH_VERSION, now, "derived"))
        conn.executemany(
            "INSERT INTO student_plan_course_status(status_id,student_id,plan_id,plan_course_id,course_id,module,requirement_type,suggested_term,completion_status,is_actionable,is_overdue,effective_attempt_id,effective_score,earned_credits,rule_version,calculated_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            status_rows,
        )

        # 统一模块评价：最低学分 → 最低门数/选择组 → 逐门必修 → 不可自动评价。
        conn.execute("DELETE FROM student_plan_module_status WHERE rule_version=?", (GROWTH_VERSION,))
        conn.execute("DELETE FROM student_plan_progress_summary WHERE rule_version=?", (GROWTH_VERSION,))
        plan_rules: dict[str, list[dict]] = {}
        for rule in conn.execute(
            "SELECT plan_id,parent_module,module_name,requirement_type,minimum_credits,"
            "minimum_courses,raw_hierarchy,source_file,source_table "
            "FROM curriculum_plan_module_requirement ORDER BY plan_id,source_table,module_requirement_id"
        ).fetchall():
            plan_rules.setdefault(rule["plan_id"], []).append(dict(rule))
        grouped: dict[tuple[str, str, str], list[dict]] = {}
        for item in conn.execute(
            "SELECT x.student_id,x.plan_id,COALESCE(NULLIF(x.module,''),'未标注模块') module,"
            "x.requirement_type,x.completion_status,x.is_overdue,x.earned_credits,pc.credits "
            "FROM student_plan_course_status x "
            "LEFT JOIN curriculum_plan_course pc ON pc.plan_course_id=x.plan_course_id "
            "WHERE x.rule_version=? ORDER BY x.student_id,x.plan_id,x.module",
            (GROWTH_VERSION,),
        ).fetchall():
            grouped.setdefault((item["student_id"], item["plan_id"], item["module"]), []).append(dict(item))
        module_rows = []
        student_modules: dict[tuple[str, str], list[dict]] = {}
        for (sid, pid, module_name), courses in grouped.items():
            rule = _best_module_rule(module_name, plan_rules.get(pid, []))
            earned = round(sum(float(c.get("earned_credits") or 0) for c in courses), 2)
            pool_credits = round(sum(float(c.get("credits") or 0) for c in courses), 2)
            completed = sum(c["completion_status"] in {"passed", "recognized"} for c in courses)
            required_courses = [c for c in courses if c.get("requirement_type") == "必修"]
            failed_required = sum(c["completion_status"] == "failed" for c in required_courses)
            due_candidates = sum(
                c["completion_status"] in {"not_completed", "unknown"} and c.get("is_overdue") == 1
                for c in required_courses
            )
            minimum_credits = float(rule.get("minimum_credits") or 0) if rule else 0
            minimum_courses = int(rule.get("minimum_courses") or 0) if rule else 0
            choice_minimum = _choice_minimum(
                " ".join([module_name] + [
                    str((rule or {}).get(key) or "") for key in ("module_name", "requirement_type")
                ])
            )
            # 合并单元格提取偶尔会把父级学分要求带到相邻子模块。
            # 若要求学分已经大于该模块全部课程记录学分之和，它不可能是这个
            # 叶子模块的有效规则；按“学分→门数→逐门必修”的约定回退。
            credible_credit_rule = minimum_credits > 0 and pool_credits > 0 and minimum_credits <= pool_credits + 0.01
            if credible_credit_rule:
                rule_type, target, achieved = "minimum_credits", minimum_credits, earned
                rule_label = f"至少{minimum_credits:g}学分"
            elif minimum_courses > 0 or choice_minimum:
                target = float(minimum_courses or choice_minimum or 0)
                achieved = float(completed)
                rule_type = "minimum_courses"
                rule_label = f"至少{int(target)}门"
            elif required_courses:
                target = float(len(required_courses))
                achieved = float(sum(c["completion_status"] in {"passed", "recognized"} for c in required_courses))
                rule_type = "required_courses"
                rule_label = f"逐门核查{int(target)}门必修课"
            else:
                target = achieved = None
                rule_type, rule_label = "not_assessable", "缺少学分、门数或逐门必修规则"
            assessable = int(target is not None)
            complete = int(assessable and achieved is not None and achieved >= target)
            if not assessable:
                evidence_status = "not_assessable"
            elif complete:
                evidence_status = "complete"
            elif failed_required:
                evidence_status = "explicit_gap"
            elif due_candidates:
                evidence_status = "candidate"
            else:
                evidence_status = "not_due"
            parent_module = (rule or {}).get("parent_module")
            source_reference = None
            if rule:
                source_reference = "|".join(str(x) for x in (
                    rule.get("source_file") or "结构化培养方案",
                    rule.get("source_table") or "—",
                ))
            row = {
                "student_id": sid, "plan_id": pid, "module_name": module_name,
                "parent_module": parent_module, "rule_type": rule_type, "rule_label": rule_label,
                "target_value": target, "achieved_value": achieved, "earned_credits": earned,
                "completed_courses": completed, "total_courses": len(courses),
                "failed_required_courses": failed_required if not complete else 0,
                "due_candidate_courses": due_candidates if not complete else 0,
                "is_assessable": assessable, "is_complete": complete,
                "evidence_status": evidence_status, "source_reference": source_reference,
            }
            student_modules.setdefault((sid, pid), []).append(row)
            module_rows.append((
                sid, pid, module_name, parent_module, rule_type, rule_label, target, achieved,
                earned, completed, len(courses), row["failed_required_courses"],
                row["due_candidate_courses"], assessable, complete, evidence_status,
                source_reference, GROWTH_VERSION, now, "derived",
            ))
        conn.executemany(
            "INSERT INTO student_plan_module_status(student_id,plan_id,module_name,parent_module,"
            "rule_type,rule_label,target_value,achieved_value,earned_credits,completed_courses,"
            "total_courses,failed_required_courses,due_candidate_courses,is_assessable,is_complete,"
            "evidence_status,source_reference,rule_version,calculated_at,source) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            module_rows,
        )
        student_meta = {
            (row["student_id"], row["plan_id"]): dict(row)
            for row in conn.execute(
                "SELECT a.student_id,a.plan_id,s.entry_grade,p.grade plan_grade "
                "FROM student_plan_assignment a JOIN dim_student s ON s.student_id=a.student_id "
                "JOIN curriculum_plan p ON p.plan_id=a.plan_id"
            ).fetchall()
        }
        summary_rows = []
        for key, modules in student_modules.items():
            meta = student_meta[key]
            assessable_modules = sum(x["is_assessable"] for x in modules)
            completed_modules = sum(x["is_complete"] for x in modules)
            explicit_modules = sum(x["evidence_status"] == "explicit_gap" for x in modules)
            candidate_modules = sum(x["evidence_status"] == "candidate" for x in modules)
            evidence_status = "explicit_gap" if explicit_modules else (
                "candidate" if candidate_modules else "no_due_issue"
            )
            rule_coverage = round(assessable_modules * 100 / len(modules), 1) if modules else 0
            summary_rows.append((
                key[0], key[1], meta["plan_grade"], current_study_term(meta["entry_grade"]),
                round(sum(x["earned_credits"] for x in modules), 2), len(modules),
                assessable_modules, completed_modules, rule_coverage,
                sum(x["failed_required_courses"] for x in modules),
                sum(x["due_candidate_courses"] for x in modules),
                explicit_modules, candidate_modules, evidence_status, "matched",
                GROWTH_VERSION, now, "derived",
            ))
        for (sid, pid), (entry_grade, plan_grade) in binding_mismatches.items():
            summary_rows.append((
                sid, pid, plan_grade, current_study_term(entry_grade), 0, 0, 0, 0, 0,
                0, 0, 0, 0, "binding_mismatch", "grade_mismatch",
                GROWTH_VERSION, now, "derived",
            ))
        conn.executemany(
            "INSERT INTO student_plan_progress_summary(student_id,plan_id,applicable_grade,"
            "current_study_term,earned_credits,module_count,assessable_modules,completed_modules,"
            "rule_coverage_rate,failed_required_courses,due_candidate_courses,explicit_gap_modules,"
            "candidate_modules,evidence_status,binding_status,rule_version,calculated_at,source) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            summary_rows,
        )

        conn.execute("DELETE FROM student_growth_indicator WHERE indicator_version=?", (GROWTH_VERSION,))
        students = [row[0] for row in conn.execute("SELECT student_id FROM dim_student")]
        course_stats = {
            row["student_id"]: dict(row) for row in conn.execute(
                "SELECT student_id,"
                "SUM(CASE WHEN is_pass=1 THEN 1 ELSE 0 END) passed_courses,"
                "SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) failed_courses,"
                "SUM(CASE WHEN is_pass=1 THEN COALESCE(earned_credits,0) ELSE 0 END) earned_credits "
                "FROM student_course_result WHERE rule_version=? GROUP BY student_id",
                (RULE_VERSION,),
            )
        }
        gpa_stats = {
            row["student_id"]: row["avg_gpa"] for row in conn.execute(
                "SELECT student_id,AVG(gpa) avg_gpa FROM grade_attempt "
                "WHERE is_published=1 AND is_void=0 AND gpa IS NOT NULL GROUP BY student_id"
            )
        }
        retake_stats = {
            row["student_id"]: row["retakes"] for row in conn.execute(
                "SELECT student_id,COUNT(*) retakes FROM grade_attempt "
                "WHERE attempt_type='retake' GROUP BY student_id"
            )
        }
        plan_stats = {
            row["student_id"]: dict(row) for row in conn.execute(
                "SELECT student_id,"
                "SUM(CASE WHEN requirement_type='必修' THEN 1 ELSE 0 END) required_courses,"
                "SUM(CASE WHEN requirement_type='必修' AND completion_status IN ('passed','recognized') THEN 1 ELSE 0 END) required_completed,"
                "SUM(CASE WHEN requirement_type='必修' AND completion_status NOT IN ('passed','recognized') THEN 1 ELSE 0 END) required_missing,"
                "SUM(CASE WHEN is_overdue=1 THEN 1 ELSE 0 END) overdue_required "
                "FROM student_plan_course_status WHERE rule_version=? GROUP BY student_id",
                (GROWTH_VERSION,),
            )
        }
        event_stats = {
            row["student_id"]: row["events"] for row in conn.execute(
                "SELECT student_id,COUNT(*) events FROM student_status_event GROUP BY student_id"
            )
        }
        growth_rows = []
        for sid in students:
            course = course_stats.get(sid, {})
            plan = plan_stats.get(sid, {})
            growth_rows.append((
                sid, GROWTH_VERSION,
                int(course.get("passed_courses") or 0),
                int(course.get("failed_courses") or 0),
                float(course.get("earned_credits") or 0),
                gpa_stats.get(sid),
                int(retake_stats.get(sid) or 0),
                int(plan.get("required_courses") or 0),
                int(plan.get("required_completed") or 0),
                int(plan.get("required_missing") or 0),
                int(plan.get("overdue_required") or 0),
                int(event_stats.get(sid) or 0),
                now, "derived",
            ))
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
            "module_status_rows": len(module_rows),
            "progress_summary_rows": len(summary_rows),
            "binding_mismatches": len(binding_mismatches),
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
