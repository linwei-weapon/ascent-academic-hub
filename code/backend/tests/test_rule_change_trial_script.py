"""规则变更单试算脚本维护：仅草稿可维护，并使旧试算失效。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.api.envelope import ApiError
from backend.api.routers.settings import (
    RuleChangeTrialScriptIn,
    _ensure_governance,
    evaluate_rule_change,
    get_rule_change_trial_script,
    save_rule_change_trial_script,
)
from scripts.migrate_rule_change_trial_script import COLUMNS, migrate


class RuleChangeTrialScriptTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""CREATE TABLE alert_event(
            event_id INTEGER PRIMARY KEY,
            cycle_no INTEGER NOT NULL DEFAULT 1,
            recurrence_of_event_id INTEGER,
            cycle_reason TEXT)""")
        _ensure_governance(self.conn)
        self.conn.execute("""INSERT INTO alert_rule_change(
            rule_id,base_params,proposed_params,base_enabled,proposed_enabled,
            status,reason,impact_json,created_by,created_at)
            VALUES ('R1','{}','{}',1,1,'draft','调整阈值用于测试',?, 'dean_user','2026-08-22T10:00:00+08:00')""",
            (json.dumps({"candidateStatus": "evaluated", "candidateStudents": 8}),))
        self.change_id = self.conn.execute(
            "SELECT change_id FROM alert_rule_change"
        ).fetchone()[0]
        self.conn.execute("""INSERT INTO alert_rule_change_candidate(
            change_id,student_id,action,created_at)
            VALUES (?,?,?,?)""", (self.change_id, "S1", "new", "2026-08-22"))
        self.user = {"role_id": "dean", "username": "dean_user"}

    def tearDown(self):
        self.conn.close()

    def test_save_and_read_sql_script(self):
        result = save_rule_change_trial_script(
            self.change_id,
            RuleChangeTrialScriptIn(
                script_type="sql",
                script_content="  SELECT student_id FROM fact_grade;  ",
            ),
            user=self.user,
            conn=self.conn,
        )
        self.assertEqual("sql", result["data"]["scriptType"])
        self.assertEqual(
            "SELECT student_id FROM fact_grade;",
            result["data"]["scriptContent"],
        )
        loaded = get_rule_change_trial_script(
            self.change_id, user=self.user, conn=self.conn
        )
        self.assertEqual(result["data"], loaded["data"])

    def test_saving_script_invalidates_previous_evaluation(self):
        save_rule_change_trial_script(
            self.change_id,
            RuleChangeTrialScriptIn(
                script_type="stored_procedure",
                script_content="CREATE PROCEDURE calc_alert AS SELECT 1;",
            ),
            user=self.user,
            conn=self.conn,
        )
        row = self.conn.execute(
            "SELECT impact_json FROM alert_rule_change WHERE change_id=?",
            (self.change_id,),
        ).fetchone()
        impact = json.loads(row["impact_json"])
        self.assertEqual("pending", impact["candidateStatus"])
        self.assertEqual(
            0,
            self.conn.execute(
                "SELECT COUNT(*) FROM alert_rule_change_candidate WHERE change_id=?",
                (self.change_id,),
            ).fetchone()[0],
        )

    def test_only_draft_can_be_maintained(self):
        self.conn.execute(
            "UPDATE alert_rule_change SET status='submitted' WHERE change_id=?",
            (self.change_id,),
        )
        with self.assertRaises(ApiError) as ctx:
            save_rule_change_trial_script(
                self.change_id,
                RuleChangeTrialScriptIn(
                    script_type="sql", script_content="SELECT 1"
                ),
                user=self.user,
                conn=self.conn,
            )
        self.assertEqual(400, ctx.exception.status_code)

    def test_script_type_and_content_are_required(self):
        for script_type, script_content in (
            ("python", "print(1)"),
            ("sql", "   "),
        ):
            with self.subTest(script_type=script_type, content=script_content):
                with self.assertRaises((ApiError, ValueError)):
                    save_rule_change_trial_script(
                        self.change_id,
                        RuleChangeTrialScriptIn(
                            script_type=script_type,
                            script_content=script_content,
                        ),
                        user=self.user,
                        conn=self.conn,
                    )

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "analytics.sqlite"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE alert_rule_change(change_id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()
            first = migrate(db_path)
            second = migrate(db_path)
            self.assertTrue(first["ready"])
            self.assertEqual(set(COLUMNS), set(first["added"]))
            self.assertEqual([], second["added"])

    def test_evaluation_requires_a_maintained_script(self):
        with self.assertRaises(ApiError) as ctx:
            evaluate_rule_change(
                self.change_id, user=self.user, conn=self.conn
            )
        self.assertIn("先维护", ctx.exception.msg)

    def test_role_without_edit_permission_cannot_save(self):
        with self.assertRaises(ApiError) as ctx:
            save_rule_change_trial_script(
                self.change_id,
                RuleChangeTrialScriptIn(
                    script_type="sql", script_content="SELECT 1"
                ),
                user={"role_id": "quality_office", "username": "reviewer"},
                conn=self.conn,
            )
        self.assertEqual(403, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
