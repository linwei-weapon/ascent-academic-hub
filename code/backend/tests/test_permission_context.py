import sqlite3
import unittest

from backend.api.deps import student_data_scope
from backend.api.envelope import ApiError
from backend.api.permission_context import (
    build_permission_context, list_identities, v2_lesson_scope, v2_student_scope,
)
from backend.api.routers.admin_rbac import (
    IdentityScopesIn, ScopeItemIn, data_permission_options,
    list_data_permissions, set_identity_scopes,
)
from scripts.migrate_permission_context import migrate


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sys_user(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            role_id TEXT,
            status TEXT
        );
        CREATE TABLE sys_role(
            role_id TEXT PRIMARY KEY,
            name TEXT,
            data_scope_type TEXT
        );
        CREATE TABLE sys_role_scope(role_id TEXT,scope_id TEXT);
        CREATE TABLE sys_menu(
            menu_id TEXT PRIMARY KEY,parent_id TEXT,title TEXT,path TEXT,icon TEXT,sort_order INTEGER
        );
        CREATE TABLE sys_role_menu(role_id TEXT,menu_id TEXT);
        CREATE TABLE dim_college(college_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE dim_major(major_id TEXT PRIMARY KEY,name TEXT,college_id TEXT);
        CREATE TABLE dim_student(
          student_id TEXT PRIMARY KEY,name TEXT,college_id TEXT,major_id TEXT,
          class_id TEXT,grade TEXT
        );
        CREATE TABLE dim_teacher(
          teacher_id TEXT PRIMARY KEY,name TEXT,dept TEXT
        );
        INSERT INTO sys_role VALUES
          ('dean','系统管理员','all'),
          ('college_dean','学院院长','college'),
          ('counselor','辅导员','class');
        INSERT INTO sys_user VALUES
          (1,'admin','管理员','dean','active'),
          (2,'college_a','甲学院用户','college_dean','active'),
          (3,'college_b','乙学院用户','college_dean','active'),
          (4,'missing_scope','缺范围用户','counselor','active');
        INSERT INTO sys_role_scope VALUES('college_dean','C01');
        INSERT INTO sys_menu VALUES('/admin/dashboard','/admin/analysis','总览','/admin/dashboard','',1);
        INSERT INTO sys_role_menu VALUES('college_dean','/admin/dashboard');
        INSERT INTO dim_college VALUES('C01','甲学院'),('C02','乙学院');
        INSERT INTO dim_major VALUES('M01','甲专业','C01'),('M02','乙专业','C02');
        INSERT INTO dim_student VALUES
          ('S01','甲同学','C01','M01','B01','2022'),
          ('S02','乙同学','C02','M02','B02','2022');
        INSERT INTO dim_teacher VALUES('T01','甲教师','C01');
    """)
    return conn


class PermissionContextTest(unittest.TestCase):
    def test_migration_is_idempotent(self):
        conn = make_conn()
        first = migrate(conn)
        second = migrate(conn)
        self.assertEqual(first, second)
        self.assertEqual(4, second["identities"])
        self.assertEqual(2, second["scopes"])
        self.assertGreater(second["actions"], 0)
        conn.close()

    def test_same_role_can_have_different_user_scopes(self):
        conn = make_conn()
        migrate(conn)
        conn.execute("""
            UPDATE sys_user_scope SET scope_id='C02',
              user_scope_id='US:UR:college_b:college_dean:college:C02',
              source='manual'
            WHERE user_role_id='UR:college_b:college_dean'
        """)
        a = build_permission_context(
            conn, {"user_id": 2, "username": "college_a", "role_id": "college_dean"}
        )
        b = build_permission_context(
            conn, {"user_id": 3, "username": "college_b", "role_id": "college_dean"}
        )
        self.assertEqual(["C01"], a["detailScope"]["collegeIds"])
        self.assertEqual(["C02"], b["detailScope"]["collegeIds"])
        self.assertNotEqual(a["scopeFingerprint"], b["scopeFingerprint"])
        conn.close()

    def test_restricted_identity_without_scope_is_fail_closed(self):
        conn = make_conn()
        migrate(conn)
        context = build_permission_context(
            conn, {"user_id": 4, "username": "missing_scope", "role_id": "counselor"}
        )
        self.assertFalse(context["authorized"])
        fragment, params = student_data_scope(
            {"role_id": "counselor", "permission_context": context}, conn, "s"
        )
        self.assertEqual("1=0", fragment)
        self.assertEqual([], params)
        conn.close()

    def test_all_scope_is_explicit_and_authorized(self):
        conn = make_conn()
        migrate(conn)
        context = build_permission_context(
            conn, {"user_id": 1, "username": "admin", "role_id": "dean"}
        )
        self.assertTrue(context["authorized"])
        self.assertEqual("all", context["detailScope"]["type"])
        self.assertIn("system.manage", context["actionPermissions"])
        conn.close()

    def test_identity_must_belong_to_current_user(self):
        conn = make_conn()
        migrate(conn)
        with self.assertRaises(ApiError):
            build_permission_context(
                conn,
                {"user_id": 2, "username": "college_a", "role_id": "college_dean"},
                "UR:college_b:college_dean",
            )
        identities = list_identities(conn, "college_a")
        self.assertEqual(["UR:college_a:college_dean"],
                         [item["identityId"] for item in identities])
        conn.close()

    def test_v2_scope_uses_context_source_ids_and_fails_if_incomplete(self):
        conn = make_conn()
        migrate(conn)
        conn.execute("""
            CREATE TABLE access_scope_mapping(
              role_id TEXT,scope_type TEXT,source_scope_id TEXT,
              organization_id TEXT,major_code TEXT,class_code TEXT,mapping_status TEXT
            )
        """)
        conn.execute("""
            INSERT INTO access_scope_mapping VALUES(
              'college_dean','college','C01','233',NULL,NULL,'mapped'
            )
        """)
        context = build_permission_context(
            conn, {"user_id": 2, "username": "college_a", "role_id": "college_dean"}
        )
        fragment, params = v2_student_scope(context, conn, "s")
        self.assertEqual("s.organization_id IN (?)", fragment)
        self.assertEqual(["233"], params)
        lesson_fragment, lesson_params = v2_lesson_scope(context, conn, "tl")
        self.assertEqual("tl.organization_id IN (?)", lesson_fragment)
        self.assertEqual(["233"], lesson_params)
        conn.execute("""
            UPDATE sys_user_scope SET scope_id='C02',
              user_scope_id='US:UR:college_a:college_dean:college:C02'
            WHERE user_role_id='UR:college_a:college_dean'
        """)
        incomplete = build_permission_context(
            conn, {"user_id": 2, "username": "college_a", "role_id": "college_dean"}
        )
        with self.assertRaises(ApiError):
            v2_student_scope(incomplete, conn, "s")
        conn.close()

    def test_permission_admin_lists_options_and_replaces_identity_scope(self):
        conn = make_conn()
        migrate(conn)
        users = list_data_permissions(None, {"username": "admin"}, conn)["data"]
        self.assertEqual(4, len(users))
        options = data_permission_options({"username": "admin"}, conn)["data"]
        self.assertEqual(2, len(options["colleges"]))
        self.assertEqual("B01", options["classes"][0]["value"])

        body = IdentityScopesIn(scopes=[
            ScopeItemIn(scope_type="college", scope_id="C02"),
        ])
        result = set_identity_scopes(
            "college_a", "UR:college_a:college_dean", body,
            {"username": "admin"}, conn,
        )["data"]
        self.assertEqual(
            ["C02"],
            [item["scope_id"] for item in result["identities"][0]["scopes"]],
        )
        context = build_permission_context(
            conn, {"user_id": 2, "username": "college_a", "role_id": "college_dean"}
        )
        self.assertEqual(["C02"], context["detailScope"]["collegeIds"])
        conn.close()

    def test_staff_relationship_scope_isolated_and_expired_rows_excluded(self):
        conn = make_conn()
        conn.executescript("""
            INSERT INTO sys_user VALUES
              (5,'adviser_a','甲班主任','class_adviser','active'),
              (6,'adviser_b','乙班主任','class_adviser','active'),
              (7,'mentor_a','甲导师','mentor','active'),
              (8,'mentor_b','乙导师','mentor','active');
        """)
        migrate(conn)
        conn.executescript("""
            INSERT INTO sys_user_staff(username,staff_id,valid_from,status,source)
            VALUES
              ('adviser_a','TA','2020-01-01','active','test'),
              ('adviser_b','TB','2020-01-01','active','test'),
              ('mentor_a','MA','2020-01-01','active','test'),
              ('mentor_b','MB','2020-01-01','active','test');
            CREATE TABLE staff_student_scope(
              staff_id TEXT,student_id TEXT,relation_type TEXT,valid_from TEXT,
              valid_to TEXT,status TEXT
            );
            INSERT INTO staff_student_scope VALUES
              ('TA','S01','class_adviser','2020-01-01',NULL,'active'),
              ('TA','S02','class_adviser','2020-01-01','2020-12-31','active'),
              ('TB','S02','class_adviser','2020-01-01',NULL,'active'),
              ('MA','S01','学业导师','2020-01-01',NULL,'active'),
              ('MB','S02','导师','2020-01-01',NULL,'active');
        """)
        expected = {
            "adviser_a": ["S01"],
            "adviser_b": ["S02"],
            "mentor_a": ["S01"],
            "mentor_b": ["S02"],
        }
        for username, student_ids in expected.items():
            user = db_user = conn.execute(
                "SELECT user_id,username,role_id,status FROM sys_user WHERE username=?",
                (username,),
            ).fetchone()
            context = build_permission_context(conn, dict(db_user))
            fragment, params = v2_student_scope(context, conn, "s")
            rows = conn.execute(
                f"SELECT student_id FROM dim_student s WHERE {fragment} ORDER BY student_id",
                params,
            ).fetchall()
            self.assertEqual(student_ids, [row[0] for row in rows])
        conn.close()


if __name__ == "__main__":
    unittest.main()
