# -*- coding: utf-8 -*-
"""M4 数据采集监控测试：etl_run 迁移幂等、run_log 落库、接口契约与鉴权。

运行：cd code && python -X utf8 -m unittest backend.tests.test_data_collection -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.envelope import ApiError
from backend.api.routers.data_collection import (
    TRIGGER_TASKS, TriggerIn, list_data_batches, list_etl_runs,
    trigger_collection_task,
)
from backend.etl.init_v2 import init_v2
from backend.etl.run_log import (
    RunConflictError, finish_run, latest_run, run_logged, start_run,
)
from backend.etl.v2_course_pass_builder import build_course_pass_stat
from backend.permission_catalog import ACTION_CATALOG, ROLE_ACTIONS
from scripts.migrate_data_collection_menu import migrate as migrate_dc_menu
from scripts.migrate_etl_run import migrate as migrate_etl_run


def _user(actions: set[str]) -> dict:
    return {
        "username": "tester",
        "permission_context": {"actionPermissions": sorted(actions)},
    }


def _menu_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sys_menu (
            menu_id TEXT PRIMARY KEY, parent_id TEXT, title TEXT NOT NULL,
            path TEXT, icon TEXT, sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE sys_role_menu (
            role_id TEXT, menu_id TEXT, PRIMARY KEY(role_id,menu_id)
        );
    """)
    return conn


class MigrationTest(unittest.TestCase):
    def test_etl_run_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            v2_path = Path(tmp) / "v2.sqlite"
            v1_path = Path(tmp) / "v1.sqlite"
            v1 = sqlite3.connect(v1_path)
            v1.execute("""CREATE TABLE sys_role_action(
                role_id TEXT, action_id TEXT, PRIMARY KEY(role_id,action_id))""")
            v1.commit()
            v1.close()

            first = migrate_etl_run(v2_path, v1_path)
            second = migrate_etl_run(v2_path, v1_path)
            self.assertEqual(first, second)
            self.assertTrue(second["etl_run_ready"])
            self.assertIn("uq_etl_run_running_task", second["etl_run_indexes"])
            self.assertEqual(1, second["trigger_action_grants"])
            self.assertIsNotNone(second["refresh_cron"])

    def test_menu_migration_is_idempotent_and_admin_only(self):
        conn = _menu_conn()
        conn.execute("INSERT INTO sys_role_menu VALUES('college_dean',?)",
                     ("/admin/system/data-collection",))
        first = migrate_dc_menu(conn)
        second = migrate_dc_menu(conn)
        self.assertEqual(first, second)
        self.assertEqual(["dean"], second["grantedRoles"])
        self.assertEqual("/admin/system", second["menu"]["parent_id"])
        conn.close()

    def test_trigger_action_registered_in_catalog(self):
        self.assertIn("etl.trigger", ACTION_CATALOG)
        self.assertIn("etl.trigger", ROLE_ACTIONS["dean"])
        for role, actions in ROLE_ACTIONS.items():
            if role == "dean":
                continue
            self.assertNotIn("etl.trigger", actions, role)


class RunLogTest(unittest.TestCase):
    def test_success_and_failed_runs_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.sqlite"
            with run_logged("demo_task", path) as run:
                run["rows_written"] = 7
                run["checks"] = {"ok": True}
            with self.assertRaises(ValueError):
                with run_logged("demo_task", path):
                    raise ValueError("boom")

            conn = init_v2(path)
            rows = conn.execute(
                "SELECT status,rows_written,checks_json,error,duration_ms"
                " FROM etl_run WHERE task='demo_task' ORDER BY run_id"
            ).fetchall()
            conn.close()
            self.assertEqual("success", rows[0][0])
            self.assertEqual(7, rows[0][1])
            self.assertEqual({"ok": True}, json.loads(rows[0][2]))
            self.assertIsNotNone(rows[0][4])
            self.assertEqual("failed", rows[1][0])
            self.assertIn("boom", rows[1][3])

    def test_running_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.sqlite"
            conn = init_v2(path)
            start_run(conn, "demo_task")
            conn.commit()
            with self.assertRaises(RunConflictError):
                start_run(conn, "demo_task")
            # 完成后可再次启动。
            finish_run(conn, 1, "success")
            conn.commit()
            start_run(conn, "demo_task")
            conn.close()

    def test_builder_writes_run_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            v2_path = Path(tmp) / "v2.sqlite"
            v1_path = Path(tmp) / "missing-v1.sqlite"
            report = build_course_pass_stat(v2_path, v1_path)
            conn = init_v2(v2_path)
            row = latest_run(conn, "v2_course_pass_builder")
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual("success", row["status"])
            self.assertEqual(report["rows"], row["rows_written"])
            self.assertEqual(report["rule_version"],
                             json.loads(row["checks_json"])["rule_version"])
            self.assertIsNotNone(row["duration_ms"])
            self.assertEqual("manual", row["triggered_by"])


class ApiContractTest(unittest.TestCase):
    def _seed_v2(self, path: Path) -> None:
        conn = init_v2(path)
        conn.execute("""
            INSERT INTO data_batch(batch_id,source_code,source_file,file_hash,
                collected_at,ingested_at,row_count,accepted_count,rejected_count,
                quality_status)
            VALUES('grade-abc','grade','成绩.xlsx','hash1','2026-07-01 10:00:00',
                '2026-07-01 10:05:00',100,98,2,'passed')
        """)
        start_run(conn, "v2_grade_loader", batch_id="grade-abc",
                  triggered_by="tester")
        finish_run(conn, 1, "success", rows_written=98,
                   checks={"grade_attempts": 98}, started_monotonic=None)
        start_run(conn, "v2_course_pass_builder", triggered_by="tester")
        finish_run(conn, 2, "failed", error="disk full")
        conn.commit()
        conn.close()

    def test_batches_contract_joins_last_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.sqlite"
            self._seed_v2(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            payload = list_data_batches({}, conn)["data"]
            conn.close()
            self.assertEqual(1, payload["summary"]["total"])
            batch = payload["batches"][0]
            self.assertEqual("grade-abc", batch["batch_id"])
            self.assertEqual("success", batch["last_run_status"])
            self.assertEqual(98, batch["accepted_count"])

    def test_runs_contract_pagination_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.sqlite"
            self._seed_v2(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            all_runs = list_etl_runs(None, None, 1, 20, {}, conn)["data"]
            self.assertEqual(2, all_runs["total"])
            required = {"run_id", "task", "status", "started_at", "finished_at",
                        "duration_ms", "rows_read", "rows_written",
                        "checks_json", "error", "triggered_by", "source"}
            self.assertTrue(required <= set(all_runs["runs"][0].keys()))

            failed = list_etl_runs(None, "failed", 1, 20, {}, conn)["data"]
            self.assertEqual(1, failed["total"])
            self.assertEqual("disk full", failed["runs"][0]["error"])

            by_task = list_etl_runs("v2_grade_loader", None, 1, 20, {}, conn)["data"]
            self.assertEqual(1, by_task["total"])

            paged = list_etl_runs(None, None, 2, 1, {}, conn)["data"]
            self.assertEqual(1, len(paged["runs"]))
            self.assertEqual(2, paged["total"])
            conn.close()

    def test_runs_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.sqlite"
            self._seed_v2(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            with self.assertRaises(ApiError) as ctx:
                list_etl_runs(None, "bogus", 1, 20, {}, conn)
            self.assertEqual(400, ctx.exception.status_code)
            conn.close()

    def test_trigger_requires_action_permission(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with self.assertRaises(ApiError) as ctx:
            trigger_collection_task(
                TriggerIn(task="v2_course_pass_builder"),
                _user(set()), conn)
        self.assertEqual(403, ctx.exception.status_code)
        conn.close()

    def test_trigger_rejects_task_outside_whitelist(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with self.assertRaises(ApiError) as ctx:
            trigger_collection_task(
                TriggerIn(task="arbitrary_shell_command"),
                _user({"etl.trigger"}), conn)
        self.assertEqual(400, ctx.exception.status_code)
        conn.close()

    def test_trigger_whitelist_only_maps_to_known_callables(self):
        self.assertEqual(
            {"v2_course_pass_builder", "v2_teaching_loader", "v2_grade_loader"},
            set(TRIGGER_TASKS),
        )
        for spec in TRIGGER_TASKS.values():
            module, func = spec["callable"].split(":")
            self.assertTrue(module.startswith("backend.etl."), module)
            self.assertTrue(func, spec)


if __name__ == "__main__":
    unittest.main()
