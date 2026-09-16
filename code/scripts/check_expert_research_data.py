"""V3 D0 read-only data inventory; coverage and executable code are NOT approval.

Only aggregate diagnostics are emitted. No names, student identifiers, source
document contents, session text or credentials are included in the report.
"""
from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "code"
REPORT_VERSION = "expert-research-data/3.0"
SOURCE_KINDS = {"real", "real_legacy", "real_partial", "derived", "synthetic", "demo"}


def open_readonly(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Required database is not an existing file")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
               sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_RECURSIVE}

    def authorize(action, arg1, arg2, database, trigger):
        if action in allowed:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA and arg1 in {"table_info", "query_only", "data_version"} and (arg1 != "query_only" or arg2 is None):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    db.set_authorizer(authorize)
    db.execute("BEGIN")
    return db


class Inventory:
    def __init__(self, db):
        self.db = db
        self.schema = {r[0]: {c[1] for c in db.execute('PRAGMA table_info("' + r[0].replace('"', '""') + '")')}
                       for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    def has(self, required):
        return all(set(columns) <= self.schema.get(table, set()) for table, columns in required.items())

    def rows(self, sql, required, params=()):
        if not self.has(required):
            return None
        return [dict(row) for row in self.db.execute(sql, params)]

    def one(self, sql, required, params=()):
        values = self.rows(sql, required, params)
        return values[0] if values else None

    def count(self, table):
        if table not in self.schema:
            return None
        return self.db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]

    def sources(self, table):
        if not self.has({table: ["source"]}):
            return None
        totals = Counter()
        for value, count in self.db.execute('SELECT source,COUNT(*) FROM "' + table + '" GROUP BY source'):
            totals[value if value in SOURCE_KINDS else "unclassified"] += count
        return dict(totals)


def code_constant(relative, name):
    try:
        tree = ast.parse((CODE / relative).read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                value = ast.literal_eval(node.value)
                return value if isinstance(value, str) else None
    except (OSError, ValueError, SyntaxError):
        pass
    return None


def document_inventory(team):
    rows = team.rows("SELECT plan_id,status,file_hash,content,sections_json,issues_json FROM team_document",
                     {"team_document": ["plan_id", "status", "file_hash", "content", "sections_json", "issues_json"]})
    if rows is None:
        return {"rows": None, "malformed_json": None, "by_plan": {}}, {}
    status_counts, by_plan, raw = Counter(), {}, {}
    invalid = 0
    for row in rows:
        status = row["status"] if row["status"] in {"extracted", "conflict", "ready", "published", "draft", "rejected"} else "unclassified"
        status_counts[status] += 1
        try:
            sections, issues = json.loads(row["sections_json"]), json.loads(row["issues_json"])
            if not isinstance(sections, list) or not isinstance(issues, list):
                raise ValueError("Unexpected document JSON shape")
            titles = [str(s.get("title", "")) for s in sections if isinstance(s, dict) and str(s.get("text", "")).strip()]
            valid_json = True
        except (ValueError, TypeError):
            invalid += 1
            titles, issues, valid_json = [], [], False
        by_plan[row["plan_id"]] = {
            "source_status": status, "content_present": bool(row["content"]),
            "hash_present": bool(row["file_hash"]), "json_valid": valid_json,
            "goal_section": any("培养目标" in t for t in titles),
            "requirement_section": any("毕业" in t or "知识和能力" in t for t in titles),
            "issues_count": len(issues) if valid_json else None,
            "usable_extracted_text": bool(valid_json and row["content"] and row["file_hash"] and status in {"extracted", "ready", "published"} and not issues),
            "business_approved": False,
        }
        raw[row["plan_id"]] = row
    return {"rows": len(rows), "statuses": dict(status_counts), "malformed_json": invalid,
            "by_plan": by_plan, "business_approval": "unverified",
            "approval_note": "Extraction/ready/published labels alone do not establish authorized publication."}, raw


def probe_courses(v2, team, plan_ids):
    """Exercise existing read-only classification, not a replacement metric."""
    sys.path.insert(0, str(CODE)) if str(CODE) not in sys.path else None
    from backend.expert_team.analysis import courses, compare_sets
    output, cached = {}, {}
    unresolved_modules, unresolved_bases = Counter(), Counter()
    for plan_id in plan_ids:
        try:
            current = courses(v2, team, plan_id)
            cached[plan_id] = current
            for course in current.values():
                if course.get("layer") in {"unknown", "mixed"}:
                    unresolved_bases[(course["layer"], course.get("classification_basis", "unreported"))] += 1
                    for module in course.get("modules", []) or ["unreported"]:
                        unresolved_modules[(course["layer"], module)] += 1
            output[plan_id] = {
                "status": "executed", "course_count": len(current),
                "layer_counts": dict(Counter(c.get("layer", "unknown") for c in current.values())),
                "unresolved_layers": sum(c.get("layer") in {"unknown", "mixed"} for c in current.values()),
                "credit_conflicts": sum(bool(c.get("conflict")) for c in current.values()),
                "mandatory_count": sum(bool(c.get("mandatory")) for c in current.values()),
                "choice_count": sum(bool(c.get("choice")) for c in current.values()),
                "unresolved_terms": sum(len(c.get("terms", [])) != 1 or str(c["terms"][0]) not in set("12345678") for c in current.values()),
            }
        except Exception as exc:
            output[plan_id] = {"status": "failed", "error_type": type(exc).__name__}
    pair_checks = 0
    values = list(cached.values())
    for index in range(len(values) - 1):
        a, b = values[index:index + 2]
        result = compare_sets(a, b)
        reverse = compare_sets(b, a)
        if result["structural_similarity"] != reverse["structural_similarity"]:
            raise ValueError("Existing structural metric is not symmetric")
        pair_checks += 1
    return {"status": "executed", "plans": output, "symmetric_pair_checks": pair_checks,
            "unresolved_module_counts": [{"layer": layer, "source_module": module, "plan_course_module_count": count} for (layer, module), count in unresolved_modules.most_common(50)],
            "unresolved_basis_counts": [{"layer": layer, "classification_basis": basis, "plan_course_count": count} for (layer, basis), count in unresolved_bases.most_common()],
            "boundary": "Exercises existing curriculum classification only; not full-scene, permission or model acceptance."}


def comparison_gate(instance):
    """Maintenance eligibility for one object; never a current-role authorization."""
    rows = instance.get("course_coverage") or {}
    probe = instance.get("program_probe") or {}
    document = instance.get("document") or {}
    source_ok = bool(instance.get("source_kind") == "real" and instance.get("grade")
                     and instance.get("version") and rows.get("distinct_courses", 0) > 0
                     and rows.get("missing_course_id") == 0 and rows.get("missing_hash") == 0
                     and document.get("source_status") != "conflict")
    executed = probe.get("status") == "executed" and probe.get("course_count", 0) > 0
    layered = bool(source_ok and executed and probe.get("unresolved_layers") == 0
                   and probe.get("credit_conflicts") == 0)
    required = bool(source_ok and executed and probe.get("mandatory_count", 0) > 0
                    and probe.get("credit_conflicts") == 0)
    allowed = ["all"] if source_ok and executed else []
    if layered:
        allowed += [name for name, count in probe.get("layer_counts", {}).items()
                    if count and name not in {"unknown", "mixed"}]
    return {"all_code_preview": bool(source_ok and executed), "layered_preview": layered,
            "target_mandatory_preview": required, "allowed_focus": allowed,
            "all_only": bool(source_ok and executed and not layered),
            "all_only_excluded_fields": ["professional_shared", "professional_union", "structural_similarity", "rank"],
            "pair_gate": "same_grade_version_confirmed_training_type_different_family_and_current_permission_required",
            "production_allowed": False}


def inspect_data(v2, team, calculate=True):
    v, t = Inventory(v2), Inventory(team)
    grade_rule = code_constant("backend/etl/v2_grade_loader.py", "RULE_VERSION")
    growth_rule = code_constant("backend/etl/v2_growth_builder.py", "GROWTH_VERSION")
    plans = v.rows("SELECT plan_id,grade,version,source FROM curriculum_plan", {"curriculum_plan": ["plan_id", "grade", "version", "source"]}) or []
    labels = v.rows("SELECT plan_id,plan_name,major_name FROM curriculum_plan",
                    {"curriculum_plan": ["plan_id", "plan_name", "major_name"]}) or []
    labels = {row["plan_id"]: row for row in labels}
    documents, _ = document_inventory(t)
    plan_rows = t.rows("""SELECT plan_id,COUNT(*) AS rows,COUNT(DISTINCT course_id) AS distinct_courses,
        SUM(course_id IS NULL OR course_id='') AS missing_course_id,
        SUM(module IS NULL OR module='') AS missing_module,
        SUM(nature IS NULL OR nature='') AS missing_nature,
        SUM(credits IS NULL OR credits<0) AS invalid_credits,
        SUM(term IS NULL OR term='') AS missing_term,
        SUM(source_hash IS NULL OR source_hash='') AS missing_hash
        FROM team_plan_course GROUP BY plan_id""",
        {"team_plan_course": ["plan_id", "course_id", "module", "nature", "credits", "term", "source_hash"]})
    by_plan = {r["plan_id"]: r for r in plan_rows or []}
    plan_ids = [p["plan_id"] for p in plans]
    probe = {"status": "not_run", "plans": {}, "symmetric_pair_checks": 0}
    probe_schema = {"team_plan_course": ["plan_id", "source_row", "course_id", "course_name", "module", "nature", "credits", "hours", "assessment", "term", "source_file"],
                    "team_document": ["plan_id", "content"]}
    if calculate and plan_ids and t.has(probe_schema):
        try:
            probe = probe_courses(v2, team, plan_ids)
        except Exception as exc:
            probe = {"status": "failed", "error_type": type(exc).__name__, "plans": {}, "symmetric_pair_checks": 0}
    cohorts = Counter(str(p["grade"]) for p in plans)
    public_plans = []
    for plan in plans:
        pid = plan["plan_id"]
        course = by_plan.get(pid)
        doc = documents["by_plan"].get(pid)
        public_plans.append({"plan_id": pid, "grade": plan["grade"], "version": plan["version"],
                             "source_kind": plan["source"] if plan["source"] in SOURCE_KINDS else "unclassified",
                             "course_coverage": course, "document": doc,
                             "program_probe": probe["plans"].get(pid), "business_approval": "unverified"})
        name = labels.get(pid, {}).get("plan_name", "") or ""
        training_type = next((kind for kind in ("预科", "留学生", "全英文", "未来班", "创新班", "实验班") if kind in name), "未明确特殊类型")
        public_plans[-1]["plan_label"] = labels.get(pid)
        public_plans[-1]["training_type_hint"] = training_type
        public_plans[-1]["training_type_approved"] = False
        public_plans[-1]["comparison_gate"] = comparison_gate(public_plans[-1])
    d01 = {"plans": len(plans), "cohorts": dict(cohorts), "source_kinds": v.sources("curriculum_plan"),
           "source_course_rows": v.count("curriculum_plan_course"), "team_course_rows": t.count("team_plan_course"),
           "plans_with_source_courses": len(by_plan),
           "unknown_course_plan_links": sum(r["rows"] for pid, r in by_plan.items() if pid not in set(plan_ids)),
           "missing_fields": {key: sum((r.get(key) or 0) for r in by_plan.values()) if plan_rows is not None else None
                              for key in ("missing_course_id", "missing_module", "missing_nature", "invalid_credits", "missing_term", "missing_hash")},
           "program_probe": {key: value for key, value in probe.items() if key != "plans"},
           "fully_classified_plans": sum(r.get("status") == "executed" and r.get("course_count", 0) > 0 and r.get("unresolved_layers") == 0 for r in probe["plans"].values())}
    d02 = {"documents": {key: value for key, value in documents.items() if key != "by_plan"},
           "plans_without_document": sum(pid not in documents["by_plan"] for pid in plan_ids),
           "usable_extracted_documents": sum(d["usable_extracted_text"] for d in documents["by_plan"].values()),
           "goal_rows": v.count("curriculum_plan_goal"), "graduation_requirement_rows": v.count("curriculum_graduation_requirement"),
           "course_requirement_mappings": v.count("curriculum_course_requirement_mapping"),
           "requirement_indicators": v.count("curriculum_requirement_indicator"),
           "goal_sources": v.sources("curriculum_plan_goal"), "requirement_sources": v.sources("curriculum_graduation_requirement")}
    effective = v.one("""SELECT COUNT(*) AS rows,
        SUM(g.attempt_id IS NULL) AS missing_attempt,
        SUM(g.attempt_id IS NOT NULL AND (g.student_id<>r.student_id OR g.course_id<>r.course_id)) AS identity_mismatch,
        SUM(g.attempt_id IS NOT NULL AND (g.is_published IS NOT 1 OR g.is_void IS NOT 0)) AS unpublished_or_void,
        SUM(g.attempt_id IS NOT NULL AND r.is_pass IS NOT g.is_pass) AS pass_mismatch,
        SUM(r.rule_version IS NOT ?) AS different_rule,
        SUM(g.attempt_id IS NOT NULL AND g.student_id=r.student_id AND g.course_id=r.course_id
            AND r.rule_version=? AND g.is_published=1 AND g.is_void=0
            AND g.source IN ('real','real_legacy') AND r.is_pass IS g.is_pass) AS usable_linked_rows,
        SUM(r.is_pass IS NULL) AS unknown_pass,
        MIN(r.calculated_at) AS earliest_calculation,MAX(r.calculated_at) AS latest_calculation
        FROM student_course_result r LEFT JOIN grade_attempt g ON g.attempt_id=r.effective_attempt_id""",
        {"student_course_result": ["effective_attempt_id", "student_id", "course_id", "is_pass", "rule_version", "calculated_at"],
         "grade_attempt": ["attempt_id", "student_id", "course_id", "is_published", "is_void", "source", "is_pass"]}, (grade_rule, grade_rule))
    substitutions = v.one("""SELECT COUNT(*) AS rows,SUM(approval_status='通过' AND workflow_status='流程已结束'
        AND source IN ('real','real_legacy')) AS ended_approved_records FROM student_course_substitution""",
        {"student_course_substitution": ["approval_status", "workflow_status", "source"]})
    d03 = {"rule_version": grade_rule, "effective": effective, "source_kinds": v.sources("student_course_result"),
           "substitutions": substitutions, "target_plan_applicability_field": v.has({"student_course_substitution": ["target_plan_id"]}),
           "recognition_boundary": "Approved substitution records do not by themselves approve applicability to a target curriculum."}
    first = "g.source IN ('real','real_legacy') AND g.is_published=1 AND g.is_void=0 AND g.is_pass IN (0,1) AND (g.attempt_type IS NULL OR g.attempt_type NOT IN ('makeup','retake'))"
    grade_columns = ["source", "is_published", "is_void", "is_pass", "attempt_type", "student_id", "course_id", "semester_id"]
    performance = v.one("SELECT COUNT(*) AS records,COUNT(DISTINCT g.student_id) AS students,COUNT(DISTINCT g.course_id) AS courses,COUNT(DISTINCT g.semester_id) AS semesters FROM grade_attempt g WHERE " + first,
                        {"grade_attempt": grade_columns})
    history = v.rows("""SELECT s.plan_id,g.course_id,COUNT(DISTINCT g.semester_id) AS terms
        FROM grade_attempt g JOIN dim_student s ON s.student_id=g.student_id WHERE """ + first +
        " AND g.semester_id IS NOT NULL AND s.plan_id IS NOT NULL GROUP BY s.plan_id,g.course_id",
        {"grade_attempt": grade_columns, "dim_student": ["student_id", "plan_id"]})
    history_plans = Counter(r["plan_id"] for r in history or [])
    comparable_plans = Counter(r["plan_id"] for r in history or [] if r["terms"] >= 2)
    chronology = v.rows("""SELECT s.plan_id,COUNT(*) AS records,
        SUM(d.semester_id IS NULL OR date(d.start_date) IS NULL OR date(d.end_date) IS NULL
            OR date(d.end_date)<date(d.start_date)) AS unresolved_calendar_records,
        COUNT(DISTINCT CASE WHEN date(d.start_date) IS NOT NULL AND date(d.end_date)>=date(d.start_date)
            THEN d.start_date END) AS mapped_start_dates
        FROM grade_attempt g JOIN dim_student s ON s.student_id=g.student_id
        LEFT JOIN dim_semester d ON d.semester_id=g.semester_id WHERE """ + first +
        " AND s.plan_id IS NOT NULL GROUP BY s.plan_id",
        {"grade_attempt": grade_columns, "dim_student": ["student_id", "plan_id"],
         "dim_semester": ["semester_id", "start_date", "end_date"]})
    chronology_by_plan = {row["plan_id"]: row for row in chronology or []}
    d04 = {"grade_rows": v.count("grade_attempt"), "grade_sources": v.sources("grade_attempt"),
           "first_attempt": performance, "plans_with_current_membership_history": len(history_plans),
           "plans_with_two_recorded_terms": len(comparable_plans),
           "comparable_course_plan_pairs": sum(comparable_plans.values()),
           "recorded_label_pairs_are_not_proven_chronology": True,
           "calendar_checked": chronology is not None,
           "boundary": "Record denominator, not unique-student denominator; current plan membership and administrative classes are not historical enrollment or teaching classes."}
    progress = v.rows("""SELECT binding_status,evidence_status,rule_version,COUNT(*) AS rows
        FROM student_plan_progress_summary GROUP BY binding_status,evidence_status,rule_version""",
        {"student_plan_progress_summary": ["binding_status", "evidence_status", "rule_version"]})
    safe_progress = []
    for r in progress or []:
        safe_progress.append({"binding_status": r["binding_status"] if r["binding_status"] in {"matched", "grade_mismatch", "missing", "unbound"} else "other",
                              "evidence_status": r["evidence_status"] if r["evidence_status"] in {"candidate", "explicit_gap", "no_due_issue", "binding_mismatch"} else "other",
                              "current_rule": r["rule_version"] == growth_rule, "rows": r["rows"]})
    student_coverage = v.one("""SELECT COUNT(*) AS active_real_students,
        SUM(p.plan_id IS NULL) AS missing_plan,
        SUM(p.plan_id IS NOT NULL AND CAST(s.entry_grade AS TEXT)<>CAST(p.grade AS TEXT)) AS grade_mismatch,
        SUM(ps.student_id IS NULL) AS missing_progress,
        SUM(ps.student_id IS NOT NULL AND (ps.rule_version IS NOT ? OR ps.source IS NOT 'derived')) AS outdated_or_unexpected_progress
        FROM dim_student s LEFT JOIN curriculum_plan p ON p.plan_id=s.plan_id
        LEFT JOIN student_plan_progress_summary ps ON ps.student_id=s.student_id AND ps.plan_id=s.plan_id
        WHERE s.source IN ('real','real_legacy') AND s.student_status='在校'""",
        {"dim_student": ["student_id", "plan_id", "entry_grade", "source", "student_status"],
         "curriculum_plan": ["plan_id", "grade"], "student_plan_progress_summary": ["student_id", "plan_id", "rule_version", "source"]}, (growth_rule,))
    object_students = v.rows("""SELECT s.plan_id,COUNT(*) AS active_real_students,
        SUM(CAST(s.entry_grade AS TEXT)=CAST(p.grade AS TEXT)) AS grade_aligned_students,
        SUM(ps.student_id IS NOT NULL AND ps.rule_version=? AND ps.source='derived') AS current_progress_students
        FROM dim_student s JOIN curriculum_plan p ON p.plan_id=s.plan_id
        LEFT JOIN student_plan_progress_summary ps ON ps.student_id=s.student_id AND ps.plan_id=s.plan_id
        WHERE s.source IN ('real','real_legacy') AND s.student_status='在校' GROUP BY s.plan_id""",
        {"dim_student": ["student_id", "plan_id", "entry_grade", "source", "student_status"],
         "curriculum_plan": ["plan_id", "grade"], "student_plan_progress_summary": ["student_id", "plan_id", "rule_version", "source"]}, (growth_rule,))
    students_by_plan = {row["plan_id"]: row for row in object_students or []}
    module_counts = v.rows("SELECT plan_id,COUNT(*) AS rows FROM student_plan_module_status GROUP BY plan_id",
                           {"student_plan_module_status": ["plan_id"]})
    course_counts = v.rows("SELECT plan_id,COUNT(*) AS rows FROM student_plan_course_status GROUP BY plan_id",
                           {"student_plan_course_status": ["plan_id"]})
    module_counts = {row["plan_id"]: row["rows"] for row in module_counts or []}
    course_counts = {row["plan_id"]: row["rows"] for row in course_counts or []}
    transfer_students = v.rows("""SELECT s.plan_id,COUNT(DISTINCT s.student_id) AS students
        FROM dim_student s JOIN curriculum_plan p ON p.plan_id=s.plan_id
        JOIN student_course_result r ON r.student_id=s.student_id
        JOIN grade_attempt g ON g.attempt_id=r.effective_attempt_id
        WHERE s.source IN ('real','real_legacy') AND s.student_status='在校'
        AND CAST(s.entry_grade AS TEXT)=CAST(p.grade AS TEXT) AND s.major_name=p.major_name
        AND r.rule_version=? AND r.is_pass IN (0,1) AND r.is_pass=g.is_pass
        AND g.student_id=r.student_id AND g.course_id=r.course_id
        AND g.is_published=1 AND g.is_void=0 AND g.source IN ('real','real_legacy') GROUP BY s.plan_id""",
        {"dim_student": ["plan_id", "student_id", "entry_grade", "major_name", "source", "student_status"],
         "curriculum_plan": ["plan_id", "grade", "major_name"],
         "student_course_result": ["student_id", "course_id", "effective_attempt_id", "is_pass", "rule_version"],
         "grade_attempt": ["attempt_id", "student_id", "course_id", "is_pass", "is_published", "is_void", "source"]}, (grade_rule,))
    transfer_counts = {row["plan_id"]: row["students"] for row in transfer_students or []}
    for instance in public_plans:
        pid = instance["plan_id"]
        instance["student_coverage"] = students_by_plan.get(pid)
        instance["course_history"] = chronology_by_plan.get(pid)
        instance["two_recorded_course_terms"] = bool(comparable_plans.get(pid))
        instance["module_condition_rows"] = module_counts.get(pid, 0)
        instance["course_condition_rows"] = course_counts.get(pid, 0)
        instance["aligned_students_with_effective_results"] = transfer_counts.get(pid, 0)
    d05 = {"student_rows": v.count("dim_student"), "student_sources": v.sources("dim_student"),
           "progress_rows": v.count("student_plan_progress_summary"), "module_status_rows": v.count("student_plan_module_status"),
           "course_status_rows": v.count("student_plan_course_status"), "rule_version": growth_rule,
           "progress_states": safe_progress if progress is not None else None, "active_student_coverage": student_coverage,
           "boundary": "Computed curriculum progress is neither full graduation approval nor business data cutoff."}
    snapshot_rows = t.rows("SELECT username,identity_id,scope_key,plan_id,snapshot_json FROM team_graduation_snapshot",
                          {"team_graduation_snapshot": ["username", "identity_id", "scope_key", "plan_id", "snapshot_json"]})
    groups, malformed, versions, snapshots = defaultdict(set), 0, Counter(), 0
    for r in snapshot_rows or []:
        try:
            value = json.loads(r["snapshot_json"])
            required = ("population_hash", "snapshot_version", "rule_version", "plan_grade", "source_hash", "counts", "source_times")
            if not isinstance(value, dict) or value.get("plan_id") != r["plan_id"] or any(not value.get(k) for k in required):
                raise ValueError("Incomplete snapshot")
            key = tuple(r[k] for k in ("username", "identity_id", "scope_key", "plan_id")) + tuple(value[k] for k in required[:4])
            groups[key].add(str(value["source_hash"]))
            versions["current" if value["snapshot_version"] == "graduation-preparation/2" else "other"] += 1
            snapshots += 1
        except (ValueError, TypeError):
            malformed += 1
    d06 = {"snapshots": len(snapshot_rows) if snapshot_rows is not None else None,
           "valid_aggregate_snapshots": snapshots, "invalid_snapshots": malformed,
           "compatible_history_groups": sum(len(hashes) >= 2 for hashes in groups.values()),
           "plans_with_compatible_history": sorted({key[3] for key, hashes in groups.items() if len(hashes) >= 2}),
           "repeated_content_does_not_create_stage": True, "versions": dict(versions),
           "granularity": "aggregate_only; no individual historical reconstruction"}
    d07 = source_contract(v, "course_syllabus", ["course_id", "version", "course_objectives", "teaching_tasks", "assessment_tasks", "scoring_rules", "source_location"])
    lesson = v.one("""SELECT COUNT(*) AS rows,SUM(capacity IS NULL) AS missing_capacity,
        SUM(semester_id IS NULL OR semester_id='') AS missing_semester,
        SUM(course_id IS NULL OR course_id='') AS missing_course,
        SUM(schedule_text IS NULL OR schedule_text='') AS missing_schedule
        FROM teaching_lesson""", {"teaching_lesson": ["capacity", "semester_id", "course_id", "schedule_text"]})
    d08 = {"teaching_lesson": lesson, "course_meetings": v.count("course_meeting"),
           "course_offering_aggregates": v.count("agg_course_offering"), "teaching_sources": v.sources("teaching_lesson"),
           "prerequisites": source_contract(v, "course_prerequisite", ["course_id", "prerequisite_course_id", "rule_version", "source_location"]),
           "construction_projects": source_contract(v, "course_construction_project", ["course_id", "project_id", "start_date", "resource_scope", "source_location"]),
           "shared_teaching": source_contract(v, "shared_course_arrangement", ["course_id", "plan_id", "lesson_id", "applicable_version", "source_location"]),
           "boundary": "Existing historical lessons/capacity do not establish future availability, prerequisites, shared resources or project duplication."}
    d09 = source_contract(v, "annual_academic_policy", ["policy_year", "organization_id", "eligible_population", "conditions_json", "course_scope", "tie_rule", "quota_rule", "approved_version", "source_location"])
    d09["boundary"] = "No connected annual-policy contract found is not a claim that the school lacks policies; generic metric definitions do not substitute for them."
    batch = v.one("""SELECT COUNT(*) AS rows,SUM(collected_at IS NULL OR collected_at='') AS missing_collected_at,
        SUM(file_hash IS NULL OR file_hash='') AS missing_hash,MIN(collected_at) AS earliest_collection,
        MAX(collected_at) AS latest_collection,MIN(ingested_at) AS earliest_ingestion,
        MAX(ingested_at) AS latest_ingestion FROM data_batch""", {"data_batch": ["collected_at", "ingested_at", "file_hash"]})
    semesters = v.one("SELECT COUNT(*) AS rows,MIN(start_date) AS first_start,MAX(end_date) AS last_end FROM dim_semester",
                      {"dim_semester": ["start_date", "end_date"]})
    unknown_semesters = v.one("""SELECT COUNT(*) AS rows FROM grade_attempt g LEFT JOIN dim_semester s
        ON s.semester_id=g.semester_id WHERE g.semester_id IS NOT NULL AND s.semester_id IS NULL""",
        {"grade_attempt": ["semester_id"], "dim_semester": ["semester_id"]})
    d10 = {"data_batches": batch, "semester_calendar": semesters, "unmapped_grade_semesters": unknown_semesters,
           "historical_graduation_outcomes": v.count("graduation_outcome"),
           "transfer_application_batch": source_contract(v, "transfer_application", ["application_batch", "student_id", "target_plan_id", "business_cutoff", "status"]),
           "business_cutoff": None, "business_cutoff_verified": False,
           "boundary": "Collection, ingestion, calculation, calendar and business cutoff are different dates; a current application population cannot be reconstructed from status-event history."}
    data = {"D01": d01, "D02": d02, "D03": d03, "D04": d04, "D05": d05,
            "D06": d06, "D07": d07, "D08": d08, "D09": d09, "D10": d10}
    return data, public_plans


def source_contract(inventory, table, fields):
    present = inventory.schema.get(table, set())
    return {"contract_table": table, "rows": inventory.count(table),
            "missing_fields": sorted(set(fields) - present),
            "status": "fields_present_unverified" if set(fields) <= present else "not_connected",
            "business_approval": "unverified"}


SCENES = {
    "P1": ("candidate", ["D01"], "Comparable curriculum sets, explicit denominators and at most 2-3 candidates", "Teaching-content equivalence or unauthorized school-wide ranking"),
    "P2": ("limited", ["D01", "D02"], "Common/different course structure with unresolved classification isolated", "Duplicate content, duplicate investment or unsupported joint construction"),
    "P3": ("limited", ["D02"], "Nonconflicting extracted objectives and requirements, with original sections", "Sufficient curriculum support or achievement scores"),
    "P4": ("limited", ["D01"], "Recorded semester/practice arrangements; unknown arrangements separate", "Invented prerequisites or load thresholds"),
    "P5": ("limited", ["D01"], "Explicit hypothetical course/credit changes against current structure", "Resource savings or full reform feasibility"),
    "C1": ("limited", ["D04"], "Courses worth further investigation from current-record impact", "Annual quality or investment ranking"),
    "C2": ("limited", ["D04"], "Course/group distributions and limits of possible explanations", "Teacher blame or causal diagnosis from outcomes alone"),
    "C3": ("deferred", ["D07"], "No core execution before approved syllabus/assessment admission", "Invented objectives, assessment tasks or achievement"),
    "C4": ("limited", ["D04", "D01"], "Conditioned approaches to an observed course issue", "Optimal resource investment or measured effects without projects"),
    "C5": ("limited", ["D04"], "Recorded performance across comparable terms with cohort caveat", "Attributing change to undocumented construction measures"),
    "T1": ("limited", ["D01"], "Directional target individually-required coverage at curriculum level", "Assumed completed source curriculum or admission recommendation"),
    "T2": ("limited", ["D01", "D03"], "Authorized effective-record versus target requirement comparison", "Automatic recognition in an unconfirmed target curriculum"),
    "T3": ("limited", ["D01", "D03"], "Determinate mandatory gaps and separately identified choice requirements", "Complete remedial-credit totals with unresolved allocation rules"),
    "T4": ("deferred", ["D08", "D10"], "No core scheduling feasibility; recorded curriculum terms may be read in T3", "Guaranteed seats, conflict-free schedule or completion date"),
    "T5": ("limited", ["D01"], "Explicit hypothetical curriculum-transition effects and unknown conditions", "Actual current application batch, quota or eligibility calculation"),
    "R1": ("deferred", ["D09"], "No current-year policy execution before admission", "Generic/old rules substituted for this year's approved rules"),
    "R2": ("deferred", ["D09", "D03", "D10"], "No complete group readiness before all relevant conditions are available", "Partial data converted into eligibility list or complete readiness rate"),
    "R3": ("deferred", ["D09", "D03"], "No formal academic-rule calculation before policy admission", "Invented course scope, tie-break or ranking"),
    "R4": ("deferred", ["D09"], "No complete annual preparation checklist before policy admission", "Generic missing items presented as the complete current-year list"),
    "R5": ("deferred", ["D09", "D10"], "No annual policy/quota impact calculation before admission", "Invented population, rank or quota changes"),
    "G1": ("limited", ["D05"], "Readiness with missing records and binding problems separated", "Formal graduation or degree pass rate"),
    "G2": ("limited", ["D05"], "Known conditions met/unmet/unknown/not-applicable individually", "Partial course facts upgraded into full eligibility"),
    "G3": ("limited", ["D05"], "Determinate course/requirement gaps and deduplicated group impacts", "Unknown as zero or summed overlapping course populations"),
    "G4": ("limited", ["D05"], "Record issues versus shared curriculum issues and unknown teaching conditions", "Missing record treated as noncompletion or automatic teaching action"),
    "G5": ("limited", ["D06"], "Compatible aggregate stages only, where actually present", "Reconstructed individual history or cross-cohort improvement"),
}


def scene_object_admission(scene_id, instance, data):
    """Object-bound coverage hints, not a user-facing access decision."""
    gate = instance.get("comparison_gate") or {}
    students = instance.get("student_coverage") or {}
    history = instance.get("course_history") or {}
    basic = bool(instance.get("source_kind") == "real" and instance.get("grade") and instance.get("version"))
    if scene_id in {"P1", "P2", "P4", "P5", "T1", "T5"}:
        return basic and gate.get("all_code_preview", False)
    if scene_id == "P3":
        return basic and bool((instance.get("document") or {}).get("usable_extracted_text"))
    if scene_id in {"C1", "C2", "C4"}:
        return basic and history.get("records", 0) > 0
    if scene_id == "C5":
        return bool(basic and instance.get("two_recorded_course_terms")
                    and history.get("mapped_start_dates", 0) >= 2
                    and history.get("unresolved_calendar_records") == 0)
    if scene_id in {"T2", "T3"}:
        return basic and instance.get("aligned_students_with_effective_results", 0) > 0
    if scene_id in {"G1", "G2", "G3", "G4"}:
        valid = basic and students.get("active_real_students", 0) > 0 and students.get("current_progress_students", 0) > 0
        if scene_id in {"G2", "G3"}:
            valid = valid and instance.get("module_condition_rows", 0) > 0
        if scene_id == "G3":
            valid = valid and instance.get("course_condition_rows", 0) > 0
        return bool(valid)
    if scene_id == "G5":
        return basic and instance["plan_id"] in data["D06"].get("plans_with_compatible_history", [])
    return False


def scene_gates(data, plans):
    available = {
        "D01": data["D01"]["plans_with_source_courses"] > 0,
        "D02": data["D02"]["usable_extracted_documents"] > 0,
        "D03": bool((data["D03"]["effective"] or {}).get("usable_linked_rows")),
        "D04": bool((data["D04"]["first_attempt"] or {}).get("records")),
        "D05": bool(data["D05"]["progress_rows"]),
        "D06": data["D06"]["compatible_history_groups"] > 0,
        "D07": False, "D08": False, "D09": False, "D10": False,
    }
    output = []
    for scene_id, (release, dependencies, allowed_fields, forbidden) in SCENES.items():
        object_ids = [p["plan_id"] for p in plans if scene_object_admission(scene_id, p, data)]
        missing = [key for key in dependencies if not available[key]]
        blockers = ["business_publication_not_verified", "object_year_and_current_permission_admission_required"]
        if missing:
            blockers.extend("insufficient_" + key for key in missing)
        if release == "deferred":
            blockers.append("V3_core_capability_deferred")
        if scene_id == "C5" and not data["D04"]["plans_with_two_recorded_terms"]:
            blockers.append("no_comparable_recorded_terms")
        if scene_id in {"T2", "T3"} and not data["D03"]["target_plan_applicability_field"]:
            blockers.append("recognition_target_applicability_unconfirmed")
        if scene_id == "P1" and not data["D01"]["fully_classified_plans"]:
            blockers.append("no_fully_classified_curriculum_instance")
        ready_fields = not missing and release != "deferred"
        if scene_id in {"G2", "G3"} and not data["D05"]["module_status_rows"]:
            blockers.append("module_condition_records_missing")
            ready_fields = False
        if scene_id == "G3" and not data["D05"]["course_status_rows"]:
            blockers.append("course_condition_records_missing")
            ready_fields = False
        if scene_id == "C5" and not data["D04"]["plans_with_two_recorded_terms"]:
            ready_fields = False
        if not object_ids:
            blockers.append("no_object_passed_maintenance_coverage_gate")
            ready_fields = False
        if scene_id == "C5" and not object_ids:
            blockers.append("no_object_with_verified_calendar_comparison")
        target_ids = [p["plan_id"] for p in plans if (p.get("comparison_gate") or {}).get("target_mandatory_preview")]
        if scene_id in {"T1", "T2", "T3", "T5"} and not target_ids:
            blockers.append("no_target_with_determinate_mandatory_requirements")
            ready_fields = False
        component = any((p.get("program_probe") or {}).get("status") == "executed" for p in plans) if scene_id in {"P1", "P2", "P4", "P5", "T1", "T2", "T3", "T5"} else not missing
        output.append({"scene_id": scene_id, "declared_release": release, "required_groups": dependencies,
                       "program_capability": {"status": "verified_component" if component else "unverified", "full_scene_verified": False},
                       "data_coverage": "partial_fields_present" if ready_fields else "insufficient",
                       "business_approval": "unverified", "production_allowed": False,
                       "preview_candidate": ready_fields,
                       "candidate_plan_ids": object_ids,
                       "candidate_target_plan_ids": target_ids if scene_id.startswith("T") else [],
                       "object_gate_boundary": "Maintenance only; paired objects, authorized group, official type, current permission and business publication still required",
                       "permitted_preview_fields": allowed_fields if ready_fields else None,
                       "blocked_core": not ready_fields, "forbidden_results": forbidden, "blockers": blockers})
    return output


def build_report(v2_path, team_path, calculate=True):
    v2, team = None, None
    try:
        v2 = open_readonly(v2_path)
        team = open_readonly(team_path)
        data, plans = inspect_data(v2, team, calculate=calculate)
        scenes = scene_gates(data, plans)
        return {"report_version": REPORT_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "purpose": "maintenance_aggregate_inventory_not_user_authorization",
                "runtime": {"python": sys.executable, "python_version": sys.version.split()[0]},
                "databases": {"v2": str(Path(v2_path).resolve()), "team": str(Path(team_path).resolve())},
                "read_only": True, "cross_database_consistency": "independent_read_transactions; not an atomic cross-database publication",
                "data_groups": data, "plan_instances": plans, "scenes": scenes,
                "summary": {"scene_count": len(scenes), "preview_candidates": sum(s["preview_candidate"] for s in scenes),
                            "deferred_by_v3": sum(s["declared_release"] == "deferred" for s in scenes),
                            "production_approved": 0, "approval_status": "unverified"},
                "limitations": ["No student names/identifiers or source document text are emitted.",
                                "source=real and extraction/ready statuses do not establish business approval.",
                                "Plan-level diagnostics are maintenance data and must be permission-filtered before any UI use.",
                                "Missing contract tables describe this connected baseline, not the school's entire information estate.",
                                "Component probes do not replace full scenario, permissions, fixed-model or business-owner acceptance."]}
    finally:
        for db in (v2, team):
            if db is not None:
                db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-db", type=Path)
    parser.add_argument("--team-db", type=Path)
    parser.add_argument("--output", type=Path, help="Aggregate JSON under work/expert-team/v3-data only")
    parser.add_argument("--skip-calculation-probe", action="store_true")
    parser.add_argument("--require-production-approved", action="store_true", help="Exit 3 unless every scene has verified production approval (never inferred here)")
    args = parser.parse_args(argv)
    if args.output:
        destination = args.output.resolve()
        allowed_root = (ROOT / "work/expert-team/v3-data").resolve()
        if not destination.is_relative_to(allowed_root) or destination.suffix.lower() != ".json":
            parser.error("Output must be a .json artifact under work/expert-team/v3-data")
    try:
        if args.v2_db is None or args.team_db is None:
            sys.path.insert(0, str(CODE)) if str(CODE) not in sys.path else None
            from backend.etl import config
            args.v2_db = args.v2_db or config.V2_DB_PATH
            args.team_db = args.team_db or config.DB_PATH.with_name("expert_team.sqlite")
        report = build_report(args.v2_db, args.team_db, not args.skip_calculation_probe)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered + "\n", encoding="utf-8")
            print(json.dumps({"output": str(destination), "summary": report["summary"]}, ensure_ascii=False))
        else:
            print(rendered)
        return 3 if args.require_production_approved and not all(s["production_allowed"] for s in report["scenes"]) else 0
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"status": "inspection_failed", "error_type": type(exc).__name__, "production_allowed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
