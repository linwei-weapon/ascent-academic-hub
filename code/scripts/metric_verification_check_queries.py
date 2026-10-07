"""Validate registry integrity and query arithmetic using isolated SQLite only.

No MySQL/Oracle connection is made. Oracle's final FETCH clause is translated
to LIMIT for this parser check; passing is not evidence of environment/schema
verification. Blocked candidate calculations are only run on synthetic fixtures
inside :memory:, never promoted to executionApproval=documented.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path

from metric_verification_build_queries import CORE, EXTRA, AUDIT_EXTRA, ROOT, OUT, build

NUMERIC = {"score", "gpa", "gp", "is_pass", "passed", "is_published", "published", "is_retake", "retake", "credits", "calculate_gp", "is_active", "is_resolved", "enabled", "in_school", "has_xue_ji", "zai_ji", "first_attempts", "first_pass", "makeup_attempts", "makeup_pass", "retake_attempts", "retake_pass", "student_count", "total_required_credits", "earned_credits", "missing_credits", "progress_percent", "is_actionable", "is_overdue", "effective_score", "final_score", "is_makeup_pass", "metric_value", "threshold_value"}


def all_queries(manifest):
    return [q for m in manifest["metrics"] for l in m["layers"] for q in l["queries"]]


def sqlite_sql(sql: str) -> str:
    return re.sub(r"FETCH FIRST 100 ROWS ONLY\s*$", "LIMIT 100", sql, flags=re.I)


def params(q):
    values = {p["name"]: None if not p["required"] else "fixture" for p in q["parameters"]}
    values.update({k: v for k, v in {"organization_id": "A", "semester_id": "T2", "previous_semester_id": "T1", "student_batch_id": "SB", "grade_batch_id": "GB", "course_batch_id": "CB", "alert_batch_id": "AB", "lesson_batch_id": "LB", "teacher_batch_id": "TB", "event_batch_id": "EB", "result_batch_id": "RB", "has_xue_ji_flag": 1, "in_school_flag": 1, "base_metric_id": "O-10", "rule_version": "1"}.items() if k in values})
    return values


def make_db(queries):
    NUMERIC.add('is_void')
    tables = {}
    for q in queries:
        for table, columns in q["requiredColumns"].items():
            tables.setdefault(table, set()).update(columns)
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for table, columns in tables.items():
        defs = [f'"{c}" ' + ("REAL" if c.lower() in NUMERIC or c.lower().endswith("_rate") else "TEXT") for c in sorted(columns)]
        db.execute(f'CREATE TABLE "{table}" (' + ", ".join(defs) + ")")
    return db


def insert(db, table, values):
    if table == 'ACT_GRADE_ATTEMPT':
        values.setdefault('is_void', 0)
        values.setdefault('credits', {'C1': 2, 'C2': 4, 'C3': 1}.get(values.get('course_id'), 1))
    known = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
    selected = {k: v for k, v in values.items() if k in known}
    db.execute(f'INSERT INTO "{table}" (' + ",".join('"' + k + '"' for k in selected) + ") VALUES (" + ",".join("?" for _ in selected) + ")", tuple(selected.values()))


def seed(db):
    for oid in ['A', 'B']:
        insert(db, 'ACT_ORGANIZATION', dict(organization_id=oid, is_college=1, source='real'))
    for sid, org, active in [("S1", "A", 1), ("S2", "A", 1), ("S3", "A", 1), ("S4", "B", 1)]:
        insert(db, "STUDENT", dict(ID=sid, DEPARTMENT_ID=org, MAJOR_ID="M", GRADE="2023", HAS_XUE_JI=1, IN_SCHOOL=active, ZAI_JI=1, STD_STATUS_ID="active"))
        insert(db, "ACT_STUDENT", dict(student_id=sid, organization_id=org, major_id="M", entry_grade="2023", has_xue_ji=1, in_school=active, std_status="active", batch_id="SB", source="real"))
    for cid, credits in [("C1", 2), ("C2", 4), ("C3", 1)]:
        insert(db, "COURSE", dict(ID=cid, CREDITS=credits, CALCULATE_GP=1))
        insert(db, "ACT_COURSE", dict(course_id=cid, credits=credits, calculate_gp=1, batch_id="CB", source="real"))
    grades = [
        ("1", "S1", "C1", "T2", 30, 0, 0, 1, "2026-02-01"),
        ("2", "S1", "C1", "T2", 40, 0, 0, 1, "2026-02-02"),
        ("3", "S1", "C2", "T2", 80, 3, 1, 1, "2026-02-03"),
        ("4", "S2", "C1", "T2", 90, 4, 1, 1, "2026-02-04"),
        ("5", "S2", "C3", "T2", 70, 2, 1, 1, "2026-02-05"),
        ("6", "S4", "C1", "T2", 30, 0, 0, 1, "2026-02-06"),
        ("7", "S1", "C3", "T2", 0, 0, 0, 0, "2026-02-07"),
        ("8", "S1", "C3", "T2", None, None, None, 1, "2026-02-08"),
        ("9", "S1", "C1", "T1", 80, 3, 1, 1, "2025-10-01"),
        ("10", "S2", "C1", "T1", 90, 4, 1, 1, "2025-10-02"),
    ]
    for aid, sid, cid, term, score, gp, passed, pub, date in grades:
        insert(db, "GRADE", dict(ID=aid, STUDENT_ID=sid, COURSE_ID=cid, SEMESTER_ID=term, SCORE=score, GP=gp, PASSED=passed, PUBLISHED=pub, GRADE_STATUS="valid", RETAKE=0, PUBLISHED_DATE_TIME=date, INPUT_DATE_TIME=date))
        insert(db, "ACT_GRADE_ATTEMPT", dict(attempt_id=aid, student_id=sid, course_id=cid, semester_id=term, score=score, gpa=gp, is_pass=passed, is_published=pub, grade_status="valid", is_retake=0, published_date_time=date, input_date_time=date, source_row_no=aid, batch_id="GB", source="real"))
    # A current hit remains current even after manual resolution.
    insert(db, "ACT_ALERT", dict(alert_id="A1", student_id="S1", rule_id="R", rule_code="RULE", semester_id="T2", is_active=1, is_resolved=1, source="real", batch_id="AB"))
    insert(db, "ACT_ALERT", dict(alert_id="A2", student_id="S1", rule_id="R2", rule_code="RULE2", semester_id="T2", is_active=1, is_resolved=0, source="real", batch_id="AB"))
    insert(db, "SYS_ALERT_RULE", dict(id="R", rule_code="RULE", enabled=1, version=1))
    insert(db, "SYS_ALERT_RULE", dict(id="R2", rule_code="RULE2", enabled=0, version=1))


def run_checks():
    data = json.loads(OUT.read_text(encoding="utf-8"))
    assert data == build(), "Registry is stale: run the generator."
    expected = set(CORE + ["MV106-" + key for key in EXTRA + AUDIT_EXTRA])
    assert {m["metricId"] for m in data["metrics"]} == expected
    catalog_file = ROOT / "catalog" / "teaching-overview.json"
    if catalog_file.exists():
        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
        assert {m["id"] for m in catalog["metrics"]} == expected, "Requirement and query metric IDs differ"
    queries = all_queries(data)
    # When the optional read-only runtime schema snapshots are available, check
    # them too; they are never required to generate the portable registry.
    runtime = ROOT.parents[1] / "work" / "runtime" / "highedu-start"
    schema_files = {"source": runtime / "metric-verification-schema-source.json", "application": runtime / "metric-verification-schema-application.json"}
    schema_check_count = 0
    if all(path.is_file() for path in schema_files.values()):
        schemas = {key: json.loads(path.read_text(encoding="utf-8-sig"))["tables"] for key, path in schema_files.items()}
        for q in queries:
            if q["dialect"] != "mysql":
                continue
            key = "source" if "-source-" in q["id"] else "application"
            tables = schemas[key]
            for table, fields in q["requiredColumns"].items():
                matches = [name for name in tables if name.lower() == table.lower()]
                assert len(matches) == 1, (q["id"], table)
                observed = {name.lower() for name in tables[matches[0]]}
                assert set(field.lower() for field in fields) <= observed, (q["id"], table, set(fields) - observed)
            schema_check_count += 1
    assert len({q["id"] for q in queries}) == len(queries)
    assert not any(q["executionApproval"] == "verified" for q in queries)
    for metric in data["metrics"]:
        assert {l["id"] for l in metric["layers"]} == {"source", "fact", "application"}
        for l in metric["layers"]:
            if not l["queries"]:
                assert l["issues"] and l["status"] == "blocked", metric["metricId"]
    for q in queries:
        sql = q["sql"]
        assert (ROOT / q["sqlFile"]).read_text(encoding="utf-8") == sql, q["id"]
        assert re.match(r"^(SELECT|WITH)\b", sql, re.I), q["id"]
        assert not re.search(r";|--|/\*|\b(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|SET|GRANT|CALL|EXECUTE|SLEEP|BENCHMARK|OUTFILE|LOAD_FILE)\b", sql, re.I), q["id"]
        assert set(q["requiredTables"]) == set(q["requiredColumns"]), q["id"]
        names = set(re.findall(r"(?<!:):([A-Za-z_]\w*)", sql))
        assert names == {p["name"] for p in q["parameters"]}, q["id"]
        assert q["requiresServerScope"] is True
        if q["kind"] == "detail":
            assert re.search(r"ORDER BY", sql, re.I) and re.search(r"(?:LIMIT 100|FETCH FIRST 100 ROWS ONLY)\s*$", sql), q["id"]
        if q["kind"] == "count":
            assert "matched_records" in sql and not re.search(r"\bLIMIT\b|FETCH FIRST", sql, re.I), q["id"]
        if q["executionApproval"] == "blocked":
            assert q["blockedReason"], q["id"]
        if q["kind"] == "calculate" and q['executionApproval'] == 'documented':
            assert q.get('approvalBasis'), 'Approved calculation requires explicit requirement/data basis'
    db = make_db(queries)
    for q in queries:
        try:
            db.execute("EXPLAIN " + sqlite_sql(q["sql"]), params(q)).fetchall()
        except sqlite3.Error as exc:
            raise AssertionError(f"{q['id']}: {exc}") from exc
    seed(db)
    index = {q["id"]: q for q in queries}

    def result(mid, kind="calculate", layer="fact", **overrides):
        candidates = [q for q in queries if q["id"].startswith(mid + "-" + layer + "-" + kind + "-mysql")]
        assert len(candidates) == 1, (mid, candidates)
        q = candidates[0]
        p = params(q)
        p.update(overrides)
        return [dict(row) for row in db.execute(sqlite_sql(q["sql"]), p)]

    for lid in ["source", "fact"]:
        assert result("O-10", layer=lid)[0]["candidate_metric_value"] == 50
        assert result("O-11", layer=lid)[0]["candidate_metric_value"] == 40
        assert result("O-20", layer=lid, course_id="C1")[0]["candidate_metric_value"] == 1
        assert result("O-09", layer=lid, course_id="C1")[0]["candidate_metric_value"] == 2
        assert math.isclose(result("O-05", layer=lid)[0]["candidate_metric_value"], (1.5 + 10 / 3) / 2)
        assert result("O-06", layer=lid, student_id="S1")[0]["candidate_metric_value"] == 2
        assert result("O-22", layer=lid, course_id="C1")[0]["candidate_metric_value"] == 50
        assert result("O-23", layer=lid, course_id="C1")[0]["candidate_metric_value"] == 2
        assert math.isclose(result("O-19", layer=lid)[0]["candidate_metric_value"], 200 / 3)
        assert result("O-18", layer=lid)[0]["candidate_delta_pp"] == 50
        assert result("O-18", layer=lid, previous_semester_id="missing")[0]["candidate_delta_pp"] is None
        ranks = result("MV106-GPA-RANK", layer=lid, organization_id=None)
        assert [r["organization_id"] for r in ranks] == ["A", "B"]
        assert ranks[0]["candidate_rank"] == 1 and ranks[0]["comparable_colleges"] == 2
        assert result("O-10", layer=lid, organization_id="empty")[0]["candidate_metric_value"] is None
        zero = result("O-10", layer=lid, student_id="S2")[0]
        assert zero["candidate_metric_value"] == 0 and zero["denominator"] == 1
        count = result("O-10", kind="count", layer=lid)[0]
        assert count["matched_records"] == 7 and count["candidate_valid_attempts"] == 5
        rows = result("O-10", kind="detail", layer=lid)
        assert len(rows) == 7 and {row["student_id"] for row in rows} == {"S1", "S2"}
    assert result("O-13")[0]["candidate_metric_value"] == 1, "Resolved workflow must not remove a current hit"
    assert math.isclose(result("O-14")[0]["candidate_metric_value"], 100 / 3)
    # A historical pass and a latest failure are different populations. R2 uses
    # never-passed courses, whereas current growth metrics use latest results.
    for lid in ["source", "fact"]:
        assert result("MV106-R2-UNRESOLVED-COURSES", layer=lid, student_id="S1")[0]["candidate_metric_value"] == 0
        assert result("MV106-CURRENT-FAILED-COURSE-COUNT", layer=lid, student_id="S1")[0]["candidate_metric_value"] == 1
        assert result("MV106-CURRENT-PASSED-COURSE-COUNT", layer=lid, student_id="S1")[0]["candidate_metric_value"] == 1
        assert result("MV106-PASSED-COURSE-COUNT", layer=lid, student_id="S1")[0]["profile_ever_passed_value"] == 2
        # Shared §10.10 evidence keeps every attempt, including unpublished,
        # missing GP and prior terms. It is not the calculation population.
        assert result("O-06", kind="count", layer=lid, student_id="S1")[0]["matched_records"] == 6
        attempts = result("O-06", kind="detail", layer=lid, student_id="S1")
        assert len(attempts) == 6
        assert sum(row["course_id"] == "C1" for row in attempts) == 3
    # Exact total must not collapse to the 100-row preview.
    for n in range(101):
        insert(db, "ACT_GRADE_ATTEMPT", dict(attempt_id=f"X{n:03}", student_id="S1", course_id="C3", semester_id="T2", score=80, gpa=3, is_pass=1, is_published=1, source="real", batch_id="GB"))
    assert result("O-10", kind="count")[0]["matched_records"] == 108
    assert len(result("O-10", kind="detail")) == 100
    # Source labels and batch guards are effective independently.
    insert(db, "ACT_GRADE_ATTEMPT", dict(attempt_id="SIM", student_id="S1", course_id="C3", semester_id="T2", is_pass=0, is_published=1, source="sim", batch_id="GB"))
    assert result("O-10", kind="count")[0]["matched_records"] == 108
    assert result("O-10", kind="count", grade_batch_id="OTHER")[0]["matched_records"] == 0
    # A grade belonging to a student outside the candidate active population
    # must not enter the coverage numerator.
    insert(db, "STUDENT", dict(ID="INACTIVE", DEPARTMENT_ID="A", IN_SCHOOL=0, HAS_XUE_JI=1))
    insert(db, "ACT_STUDENT", dict(student_id="INACTIVE", organization_id="A", in_school=0, has_xue_ji=1, source="real", batch_id="SB"))
    insert(db, "GRADE", dict(ID="INACTIVE-G", STUDENT_ID="INACTIVE", COURSE_ID="C1", SEMESTER_ID="T2", PUBLISHED=1, PASSED=1))
    insert(db, "ACT_GRADE_ATTEMPT", dict(attempt_id="INACTIVE-G", student_id="INACTIVE", course_id="C1", semester_id="T2", is_published=1, is_pass=1, source="real", batch_id="GB"))
    for lid in ["source", "fact"]:
        assert math.isclose(result("O-19", layer=lid)[0]["candidate_metric_value"], 200 / 3)
    before_void = result('O-10')[0]['candidate_metric_value']
    insert(db, 'ACT_GRADE_ATTEMPT', dict(attempt_id='VOID', student_id='S3', course_id='C1', semester_id='T2', is_published=1, is_pass=0, is_void=1, source='real', batch_id='GB'))
    assert result('O-10')[0]['candidate_metric_value'] == before_void, 'Voided grade must not change the fact numerator or denominator'
    insert(db, 'ACT_GRADE_ATTEMPT', dict(attempt_id='LATEST-NO-GP', student_id='S2', course_id='C1', semester_id='T2', is_published=1, is_pass=1, gpa=None, published_date_time='2099-01-01', input_date_time='2099-01-01', source='real', batch_id='GB'))
    assert result('O-23', course_id='C1')[0]['candidate_metric_value'] == 0, 'Blocked candidate selects latest before excluding missing GP; not an approved O-23 rule'
    for q in queries:
        if q['id'].startswith(('O-23-', 'O-03-')) and q['kind']=='calculate':
            assert q['executionApproval']=='blocked', 'Unresolved result selection cannot be silently approved'
    impacts = result('O-17', course_id=None)
    assert impacts[0]['organization_id'] == 'B' and impacts[0]['estimated_excess_students'] > 0
    assert impacts[0]['impact_rank'] == 1 and any(r['estimated_excess_students'] == 0 for r in impacts), 'Impact ranks raw positive deviation and floors negative deviation at zero'
    db.close()
    return {"metrics": len(data["metrics"]), "queriesChecked": len(queries), "mysqlQueriesMatchedToSavedSchema": schema_check_count, "isolatedCases": ["student_vs_attempt_count", "course_scope", "student_weighted_gpa_before_organization_mean", "college_gpa_rank", "latest_course_candidate", "coverage_same_population", "previous_term_delta_and_missing_baseline", "zero_vs_null", "published_filter", "resolved_workflow_vs_current_alert", "unpaginated_count_and_100_row_preview", "real_source_and_independent_batch_filters"],
            "additionalCases": ['void_exclusion', 'latest_then_exclude_missing_gp', 'positive_impact_raw_ranking', 'historical_pass_vs_current_failure_and_r2', 'all_personal_attempts_preserved'],
            "environment": "SQLite :memory: synthetic only", "mysqlOracleRuntimeVerified": False, "realDatabaseConnections": 0}


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False))
