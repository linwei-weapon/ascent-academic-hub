"""规则自发现执行确认、脱敏清单与后台任务契约。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks

from backend.api.envelope import ApiError
from backend.api.routers.settings import (
    DISCOVERY_RUN_DDL,
    DiscoveryRunRequest,
    _execute_discovery_run,
    discovery_preview,
    discovery_run_status,
    trigger_discovery,
)
from backend.api.settings import CURRENT_SEMESTER


def manager() -> dict:
    return {
        "username": "dean",
        "role_id": "dean",
        "permission_context": {
            "actionPermissions": ["rule.discovery.manage"],
        },
    }


class RuleDiscoveryExecutionTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE dim_student(student_id TEXT, college_id TEXT,
                major_id TEXT, grade TEXT);
            CREATE TABLE fact_grade(student_id TEXT, semester_id TEXT,
                source TEXT, gpa REAL);
            CREATE TABLE fact_plan_course(course_id TEXT);
            CREATE TABLE fact_alert(student_id TEXT, level TEXT,
                is_active INTEGER);
            CREATE TABLE fact_attrition(student_id TEXT, source TEXT,
                kind TEXT);
            CREATE TABLE fact_major_req(major_id TEXT, total_req REAL);
            CREATE TABLE sys_discovered_rule(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                semester_id TEXT NOT NULL, name TEXT NOT NULL,
                conditions TEXT NOT NULL, level TEXT, confidence REAL,
                risk_ratio REAL, sample_size INTEGER, detail_json TEXT,
                status TEXT DEFAULT 'pending', source TEXT,
                created_at TEXT, approved_at TEXT
            );

            INSERT INTO dim_student VALUES ('S1','C1','M1','2024');
            INSERT INTO dim_student VALUES ('S2','C1','M1','2024');
            INSERT INTO fact_grade VALUES ('S1','2024-1','real',3.1);
            INSERT INTO fact_grade VALUES ('S1','2024-2','real',2.8);
            INSERT INTO fact_grade VALUES ('S2','2024-1','sim',3.0);
            INSERT INTO fact_plan_course VALUES ('K1');
            INSERT INTO fact_alert VALUES ('S1','严重',1);
            INSERT INTO fact_alert VALUES ('S2','提醒',1);
            INSERT INTO fact_attrition VALUES ('S1','real','退学');
            INSERT INTO fact_attrition VALUES ('S2','sim','退学');
            INSERT INTO fact_major_req VALUES ('M1',160);
        """)

    def tearDown(self):
        self.conn.close()

    def test_preview_returns_real_table_counts_and_anonymization_contract(self):
        data = discovery_preview(user=manager(), conn=self.conn)["data"]
        self.assertEqual(6, data["summary"]["tableCount"])
        self.assertEqual(8, data["summary"]["totalRows"])
        self.assertEqual(1, data["summary"]["analyzableStudents"])
        self.assertEqual(
            [
                "dim_student", "fact_grade", "fact_plan_course",
                "fact_alert", "fact_attrition", "fact_major_req",
            ],
            [item["tableName"] for item in data["tables"]],
        )
        self.assertEqual(2, data["tables"][1]["rowCount"])
        self.assertTrue(data["anonymization"]["rules"])
        self.assertTrue(data["agreement"]["required"])
        self.assertEqual(64, len(data["manifestFingerprint"]))

    def test_execution_requires_consent_and_current_manifest(self):
        preview = discovery_preview(user=manager(), conn=self.conn)["data"]
        tasks = BackgroundTasks()
        with self.assertRaises(ApiError) as consent_error:
            trigger_discovery(
                body=DiscoveryRunRequest(
                    consent=False,
                    manifestFingerprint=preview["manifestFingerprint"],
                ),
                background_tasks=tasks,
                user=manager(), conn=self.conn,
            )
        self.assertEqual(400, consent_error.exception.status_code)

        with self.assertRaises(ApiError) as stale_error:
            trigger_discovery(
                body=DiscoveryRunRequest(
                    consent=True, manifestFingerprint="0" * 64,
                ),
                background_tasks=tasks,
                user=manager(), conn=self.conn,
            )
        self.assertEqual(409, stale_error.exception.status_code)
        self.assertEqual(0, len(tasks.tasks))

    def test_general_llm_config_cannot_bypass_discovery_specific_switch(self):
        self.conn.executescript("""
            CREATE TABLE sys_ai_decision_llm_config(
                config_key TEXT PRIMARY KEY, config_value TEXT
            );
            CREATE TABLE sys_config(
                config_key TEXT PRIMARY KEY, config_value TEXT
            );
            INSERT INTO sys_ai_decision_llm_config VALUES(
                'decision.llm',
                '{"enabled":true,"base_url":"https://model.invalid/v1","api_key":"secret","model":"approved-model"}'
            );
            INSERT INTO sys_config VALUES(
                'discovery.llm', '{"mode":"off"}'
            );
        """)
        preview = discovery_preview(user=manager(), conn=self.conn)["data"]
        self.assertFalse(preview["model"]["ready"])
        self.assertEqual("local_controlled", preview["model"]["mode"])

        self.conn.execute("""
            UPDATE sys_config SET config_value='{"mode":"approved_cloud"}'
            WHERE config_key='discovery.llm'
        """)
        preview = discovery_preview(user=manager(), conn=self.conn)["data"]
        self.assertTrue(preview["model"]["ready"])
        self.assertEqual("approved_model", preview["model"]["mode"])

    def test_execution_queues_job_and_supersedes_current_pending_rules(self):
        self.conn.execute("""
            INSERT INTO sys_discovered_rule(
                semester_id,name,conditions,status
            ) VALUES(?,?,?,'pending')
        """, (CURRENT_SEMESTER, "旧建议", "[]"))
        self.conn.commit()
        preview = discovery_preview(user=manager(), conn=self.conn)["data"]
        tasks = BackgroundTasks()

        data = trigger_discovery(
            body=DiscoveryRunRequest(
                consent=True,
                manifestFingerprint=preview["manifestFingerprint"],
            ),
            background_tasks=tasks,
            user=manager(), conn=self.conn,
        )["data"]

        self.assertEqual("queued", data["status"])
        self.assertEqual(1, data["supersededCount"])
        self.assertEqual(1, len(tasks.tasks))
        status = discovery_run_status(user=manager(), conn=self.conn)["data"]
        self.assertEqual(data["runId"], status["runId"])
        self.assertEqual("queued", status["status"])
        self.assertEqual(
            "superseded",
            self.conn.execute(
                "SELECT status FROM sys_discovered_rule WHERE name='旧建议'"
            ).fetchone()[0],
        )

    def test_existing_candidate_gates_and_levels_remain_unchanged(self):
        source = (
            Path(__file__).resolve().parents[1] / "etl" / "rule_discovery.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "if len(features) < 100:",
            "sample < 30 or pos_count < 5",
            "if ratio < 2.0",
            '"严重" if ratio >= 5 else ("警告" if ratio >= 3 else "提醒")',
            'return rules[:10]',
        ):
            self.assertIn(marker, source)

    def test_background_worker_persists_completion_for_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "analytics.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(DISCOVERY_RUN_DDL)
            conn.execute("""
                INSERT INTO sys_discovery_run(
                    run_id,semester_id,status,manifest_fingerprint,
                    table_count,total_rows,analyzable_students,consent_by,
                    consent_at,created_at,superseded_count,engine_mode,
                    model_status
                ) VALUES('run-1',?,'queued',?,6,8,1,'dean',?,?,1,
                    'local_controlled','not_configured')
            """, (CURRENT_SEMESTER, "a" * 64,
                  "2026-08-22T10:00:00+08:00", "2026-08-22T10:00:00+08:00"))
            conn.commit()
            conn.close()

            with patch(
                "backend.etl.rule_discovery.run_and_save", return_value=3,
            ) as run_and_save:
                _execute_discovery_run(str(db_path), "run-1", CURRENT_SEMESTER)

            conn = sqlite3.connect(db_path)
            row = conn.execute("""
                SELECT status,candidate_count,model_status,finished_at
                FROM sys_discovery_run WHERE run_id='run-1'
            """).fetchone()
            conn.close()
            self.assertEqual("completed", row[0])
            self.assertEqual(3, row[1])
            self.assertEqual("not_configured", row[2])
            self.assertTrue(row[3])
            run_and_save.assert_called_once_with(
                CURRENT_SEMESTER, db_path=db_path,
            )


if __name__ == "__main__":
    unittest.main()
