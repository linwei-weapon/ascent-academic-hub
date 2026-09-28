"""D0 read-only inspection contracts; all writable databases are temporary fixtures."""
import contextlib
import hashlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_expert_research_data.py"
spec = importlib.util.spec_from_file_location("expert_research_data_check", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@contextlib.contextmanager
def fixture_db(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


class ExpertResearchDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.v2 = Path(self.temp.name) / "source.sqlite"
        self.team = Path(self.temp.name) / "team.sqlite"
        with fixture_db(self.v2) as db:
            db.executescript("""
                CREATE TABLE curriculum_plan(plan_id,grade,version,source);
                INSERT INTO curriculum_plan VALUES('PLAN',2022,'2022','real');
                CREATE TABLE curriculum_plan_course(plan_id,course_id);
                INSERT INTO curriculum_plan_course VALUES('PLAN','COURSE');
                CREATE TABLE curriculum_plan_goal(plan_id,source);
                INSERT INTO curriculum_plan_goal VALUES('PLAN','real');
                CREATE TABLE curriculum_graduation_requirement(plan_id,source);
                INSERT INTO curriculum_graduation_requirement VALUES('PLAN','real');
                CREATE TABLE curriculum_course_requirement_mapping(plan_id);
                CREATE TABLE curriculum_requirement_indicator(plan_id);
                CREATE TABLE dim_student(student_id,display_name,plan_id,entry_grade,source,student_status);
                INSERT INTO dim_student VALUES('PRIVATE_STUDENT_001','PRIVATE_NAME','PLAN',2022,'real','在校');
                INSERT INTO dim_student VALUES('PRIVATE_STUDENT_002','PRIVATE_NAME_2','PLAN',2021,'real','在校');
                CREATE TABLE grade_attempt(attempt_id,student_id,course_id,is_published,is_void,source,is_pass,attempt_type,semester_id);
                INSERT INTO grade_attempt VALUES('A1','PRIVATE_STUDENT_001','COURSE',1,0,'real',1,'first','S1');
                INSERT INTO grade_attempt VALUES('A2','PRIVATE_STUDENT_002','COURSE',0,0,'real',0,'first','S1');
                CREATE TABLE student_course_result(student_id,course_id,rule_version,effective_attempt_id,is_pass,calculated_at,source);
                INSERT INTO student_course_result VALUES('PRIVATE_STUDENT_001','COURSE','grade-effective-v1','A1',1,'2026-01-01','derived');
                INSERT INTO student_course_result VALUES('PRIVATE_STUDENT_002','COURSE','grade-effective-v1','A2',0,'2026-01-01','derived');
                CREATE TABLE student_course_substitution(approval_status,workflow_status,source);
                INSERT INTO student_course_substitution VALUES('通过','流程已结束','real');
                CREATE TABLE student_plan_progress_summary(student_id,plan_id,binding_status,evidence_status,rule_version,source);
                INSERT INTO student_plan_progress_summary VALUES('PRIVATE_STUDENT_001','PLAN','matched','candidate','growth-v1','derived');
                CREATE TABLE student_plan_module_status(student_id);
                CREATE TABLE student_plan_course_status(student_id);
                CREATE TABLE data_batch(collected_at,ingested_at,file_hash);
                INSERT INTO data_batch VALUES(NULL,'2026-07-01','file-hash');
                CREATE TABLE dim_semester(semester_id,start_date,end_date);
                INSERT INTO dim_semester VALUES('S1','2022-09-01','2023-01-01');
            """)
        with fixture_db(self.team) as db:
            db.executescript("""
                CREATE TABLE team_plan_course(plan_id,course_id,module,nature,credits,term,source_hash);
                INSERT INTO team_plan_course VALUES('PLAN','COURSE','专业基础','必修',2,'1','hash');
                CREATE TABLE team_document(plan_id,status,file_hash,content,sections_json,issues_json);
                CREATE TABLE team_graduation_snapshot(username,identity_id,scope_key,plan_id,snapshot_json);
            """)
            db.execute("INSERT INTO team_document VALUES(?,?,?,?,?,?)", ("PLAN", "ready", "hash", "PRIVATE_DOCUMENT_TEXT",
                       json.dumps([{"title": "培养目标", "text": "PRIVATE_DOCUMENT_TEXT"}], ensure_ascii=False), "[]"))

    def report(self):
        return checker.build_report(self.v2, self.team, calculate=False)

    def scene(self, scene_id):
        return next(s for s in self.report()["scenes"] if s["scene_id"] == scene_id)

    def test_missing_file_does_not_create_database(self):
        missing = Path(self.temp.name) / "missing.sqlite"
        with self.assertRaises(FileNotFoundError):
            checker.open_readonly(missing)
        self.assertFalse(missing.exists())

    def test_readonly_connection_denies_mutation_attach_and_query_only_disable(self):
        before = hashlib.sha256(self.v2.read_bytes()).hexdigest()
        db = checker.open_readonly(self.v2)
        try:
            for statement in ("DELETE FROM curriculum_plan", "CREATE TABLE forbidden(x)",
                              "PRAGMA query_only=OFF", "ATTACH DATABASE ':memory:' AS bypass"):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.DatabaseError):
                    db.execute(statement)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM curriculum_plan").fetchone()[0], 1)
        finally:
            db.close()
        self.assertEqual(before, hashlib.sha256(self.v2.read_bytes()).hexdigest())

    def test_complete_catalog_and_three_independent_axes(self):
        report = self.report()
        self.assertEqual({s["scene_id"] for s in report["scenes"]}, {f"{g}{i}" for g in "PCTRG" for i in range(1, 6)})
        self.assertEqual(report["summary"]["scene_count"], 25)
        self.assertEqual(report["summary"]["deferred_by_v3"], 7)
        for scene in report["scenes"]:
            self.assertIn("program_capability", scene)
            self.assertIn("data_coverage", scene)
            self.assertEqual(scene["business_approval"], "unverified")
            self.assertFalse(scene["production_allowed"])

    def test_real_and_ready_do_not_become_business_approval(self):
        report = self.report()
        self.assertEqual(report["data_groups"]["D02"]["usable_extracted_documents"], 1)
        self.assertEqual(report["plan_instances"][0]["document"]["source_status"], "ready")
        self.assertFalse(report["plan_instances"][0]["document"]["business_approved"])
        self.assertEqual(report["summary"]["production_approved"], 0)

    def test_report_does_not_emit_student_names_ids_or_document_text(self):
        rendered = json.dumps(self.report(), ensure_ascii=False)
        self.assertNotIn("PRIVATE_STUDENT", rendered)
        self.assertNotIn("PRIVATE_NAME", rendered)
        self.assertNotIn("PRIVATE_DOCUMENT_TEXT", rendered)

    def test_conflicting_document_is_not_usable(self):
        with fixture_db(self.team) as db:
            db.execute("UPDATE team_document SET status='conflict',issues_json='[\"conflict\"]'")
        report = self.report()
        self.assertEqual(report["data_groups"]["D02"]["usable_extracted_documents"], 0)
        self.assertTrue(self.scene("P3")["blocked_core"])

    def test_invalid_document_json_degrades_without_leaking_content(self):
        with fixture_db(self.team) as db:
            db.execute("UPDATE team_document SET sections_json='PRIVATE_INVALID_CONTENT'")
        report = self.report()
        self.assertEqual(report["data_groups"]["D02"]["documents"]["malformed_json"], 1)
        self.assertNotIn("PRIVATE_INVALID_CONTENT", json.dumps(report))

    def test_effective_results_must_link_to_published_nonvoid_grade(self):
        effective = self.report()["data_groups"]["D03"]["effective"]
        self.assertEqual(effective["rows"], 2)
        self.assertEqual(effective["usable_linked_rows"], 1)
        self.assertEqual(effective["unpublished_or_void"], 1)

    def test_approved_substitution_is_not_target_applicability(self):
        data = self.report()["data_groups"]["D03"]
        self.assertEqual(data["substitutions"]["ended_approved_records"], 1)
        self.assertFalse(data["target_plan_applicability_field"])
        self.assertIn("recognition_target_applicability_unconfirmed", self.scene("T2")["blockers"])

    def test_missing_source_contract_is_unknown_not_zero(self):
        contract = self.report()["data_groups"]["D07"]
        self.assertIsNone(contract["rows"])
        self.assertEqual(contract["status"], "not_connected")
        self.assertTrue(contract["missing_fields"])
        self.assertTrue(self.scene("C3")["blocked_core"])

    def test_ingestion_time_not_business_cutoff(self):
        data = self.report()["data_groups"]["D10"]
        self.assertEqual(data["data_batches"]["missing_collected_at"], 1)
        self.assertIsNone(data["business_cutoff"])
        self.assertFalse(data["business_cutoff_verified"])

    def test_one_term_and_missing_conditions_do_not_enable_trend_or_conditions(self):
        self.assertTrue(self.scene("C5")["blocked_core"])
        self.assertTrue(self.scene("G2")["blocked_core"])
        self.assertTrue(self.scene("G3")["blocked_core"])

    def test_no_snapshot_pair_does_not_enable_g5(self):
        self.assertTrue(self.scene("G5")["blocked_core"])
        snapshot = {"plan_id": "PLAN", "population_hash": "pop", "snapshot_version": "graduation-preparation/2",
                    "rule_version": "growth-v1 / grade-effective-v1", "plan_grade": "2022",
                    "source_hash": "hash", "counts": {"candidate": 1}, "source_times": ["2026-01-01"]}
        with fixture_db(self.team) as db:
            db.execute("INSERT INTO team_graduation_snapshot VALUES(?,?,?,?,?)", ("PRIVATE_OWNER", "identity", "scope", "PLAN", json.dumps(snapshot)))
        self.assertTrue(self.scene("G5")["blocked_core"])
        with fixture_db(self.team) as db:
            snapshot["source_hash"] = "new-hash"
            db.execute("INSERT INTO team_graduation_snapshot VALUES(?,?,?,?,?)", ("PRIVATE_OWNER", "identity", "scope", "PLAN", json.dumps(snapshot)))
        report = self.report()
        self.assertEqual(report["data_groups"]["D06"]["compatible_history_groups"], 1)
        self.assertNotIn("PRIVATE_OWNER", json.dumps(report))
        self.assertFalse(self.scene("G5")["production_allowed"])

    def test_snapshot_with_wrong_plan_is_rejected(self):
        snapshot = {"plan_id": "OTHER", "population_hash": "pop", "snapshot_version": "graduation-preparation/2",
                    "rule_version": "growth-v1", "plan_grade": "2022", "source_hash": "hash",
                    "counts": {"candidate": 1}, "source_times": ["2026-01-01"]}
        with fixture_db(self.team) as db:
            db.execute("INSERT INTO team_graduation_snapshot VALUES(?,?,?,?,?)", ("owner", "identity", "scope", "PLAN", json.dumps(snapshot)))
        self.assertEqual(self.report()["data_groups"]["D06"]["invalid_snapshots"], 1)

    def test_output_cannot_overwrite_business_database_or_outside_work_area(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            checker.main(["--output", str(self.v2)])
        self.assertEqual(failure.exception.code, 2)

    def test_production_gate_has_distinct_failing_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = checker.main(["--v2-db", str(self.v2), "--team-db", str(self.team),
                                 "--skip-calculation-probe", "--require-production-approved"])
        self.assertEqual(code, 3)

    def test_report_leaves_both_database_bytes_unchanged(self):
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.v2, self.team)]
        self.report()
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.v2, self.team)])

    def test_duplicate_snapshot_content_does_not_create_second_stage(self):
        snapshot = {"plan_id": "PLAN", "population_hash": "pop", "snapshot_version": "graduation-preparation/2",
                    "rule_version": "growth-v1", "plan_grade": "2022", "source_hash": "same",
                    "counts": {"candidate": 1}, "source_times": ["2026-01-01"]}
        with fixture_db(self.team) as db:
            for _ in range(2):
                db.execute("INSERT INTO team_graduation_snapshot VALUES(?,?,?,?,?)", ("owner", "identity", "scope", "PLAN", json.dumps(snapshot)))
        self.assertEqual(self.report()["data_groups"]["D06"]["compatible_history_groups"], 0)
        self.assertTrue(self.scene("G5")["blocked_core"])

    def test_snapshot_pair_must_not_cross_scope(self):
        with fixture_db(self.team) as db:
            for scope in ("A", "B"):
                snapshot = {"plan_id": "PLAN", "population_hash": "pop", "snapshot_version": "graduation-preparation/2",
                            "rule_version": "growth-v1", "plan_grade": "2022", "source_hash": scope,
                            "counts": {"candidate": 1}, "source_times": ["2026-01-01"]}
                db.execute("INSERT INTO team_graduation_snapshot VALUES(?,?,?,?,?)", ("owner", "identity", scope, "PLAN", json.dumps(snapshot)))
        self.assertEqual(self.report()["data_groups"]["D06"]["compatible_history_groups"], 0)

    def test_unknown_layer_only_all_code_comparison(self):
        instance = {"source_kind": "real", "grade": 2022, "version": "2022",
                    "course_coverage": {"distinct_courses": 3, "missing_course_id": 0, "missing_hash": 0},
                    "program_probe": {"status": "executed", "course_count": 3, "unresolved_layers": 1,
                                      "credit_conflicts": 0, "mandatory_count": 1}}
        gate = checker.comparison_gate(instance)
        self.assertTrue(gate["all_only"])
        self.assertEqual(gate["allowed_focus"], ["all"])
        self.assertFalse(gate["layered_preview"])
        self.assertTrue(gate["target_mandatory_preview"])
        instance["document"] = {"source_status": "conflict"}
        self.assertFalse(checker.comparison_gate(instance)["all_code_preview"])

    def test_unexecuted_probe_does_not_admit_comparison(self):
        self.assertFalse(self.report()["plan_instances"][0]["comparison_gate"]["all_code_preview"])
        self.assertTrue(self.scene("P1")["blocked_core"])

    def test_document_coverage_does_not_leak_to_other_object(self):
        with fixture_db(self.v2) as db:
            db.execute("INSERT INTO curriculum_plan VALUES('OTHER',2022,'2022','real')")
        self.assertEqual(self.scene("P3")["candidate_plan_ids"], ["PLAN"])

    def test_c5_unmapped_term_blocks_object_even_with_two_labels(self):
        instance = {"source_kind": "real", "grade": 2022, "version": "2022", "two_recorded_course_terms": True,
                    "course_history": {"mapped_start_dates": 2, "unresolved_calendar_records": 1}}
        self.assertFalse(checker.scene_object_admission("C5", instance, {}))
        instance["course_history"]["unresolved_calendar_records"] = 0
        self.assertTrue(checker.scene_object_admission("C5", instance, {}))


if __name__ == "__main__":
    unittest.main()
