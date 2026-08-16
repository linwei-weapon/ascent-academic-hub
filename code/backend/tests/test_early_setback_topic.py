import sqlite3
import unittest

from backend.api.routers import v2
from backend.api.routers.v2 import early_setback_options, early_setback_topic


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_student(
          student_id TEXT PRIMARY KEY,display_name TEXT,entry_grade INTEGER,
          organization_id TEXT,major_code TEXT,major_name TEXT,class_code TEXT
        );
        CREATE TABLE dim_organization(organization_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE dim_course(course_id TEXT PRIMARY KEY,name TEXT);
        CREATE TABLE grade_attempt(
          student_id TEXT,semester_id TEXT,course_id TEXT,course_name TEXT,
          is_pass INTEGER,gpa REAL,is_published INTEGER,is_void INTEGER
        );
        CREATE TABLE access_scope_mapping(
          role_id TEXT,scope_type TEXT,source_scope_id TEXT,organization_id TEXT,
          major_code TEXT,class_code TEXT,mapping_status TEXT
        );
        INSERT INTO access_scope_mapping VALUES
          ('counselor','class','班级一',NULL,NULL,'班级一','mapped');
        INSERT INTO dim_organization VALUES('O1','一院'),('O2','二院');
        INSERT INTO dim_course VALUES('K1','课程一'),('K2','课程二');
        INSERT INTO dim_student VALUES
          ('S1','甲',2022,'O1','M1','专业一','班级一'),
          ('S2','乙',2022,'O1','M1','专业一','班级一'),
          ('S3','丙',2022,'O1','M1','专业一','班级二'),
          ('S4','丁',2022,'O1','M2','专业二','班级三'),
          ('S5','戊',2022,'O1','M2','专业二','班级三'),
          ('S6','己',2022,'O2','M3','专业三','班级四');
        INSERT INTO grade_attempt VALUES
          ('S1','2022-2023-1','K1','课程一',1,3.0,1,0),
          ('S1','2023-2024-1','K1','课程一',1,3.2,1,0),
          ('S2','2022-2023-1','K1','课程一',0,1.0,1,0),
          ('S2','2023-2024-1','K1','课程一',1,2.5,1,0),
          ('S3','2022-2023-1','K1','课程一',0,1.0,1,0),
          ('S3','2023-2024-1','K1','课程一',0,1.0,1,0),
          ('S3','2023-2024-1','K2','课程二',0,1.0,1,0),
          ('S4','2022-2023-1','K1','课程一',0,1.0,1,0),
          ('S5','2022-2023-1','K1','课程一',0,1.0,1,0),
          ('S5','2022-2023-2','K2','课程二',0,1.0,1,0),
          ('S5','2023-2024-1','K1','课程一',0,1.0,1,0),
          ('S6','2022-2023-1','K1','课程一',0,1.0,1,0),
          ('S6','2023-2024-1','K1','课程一',1,2.5,1,0);
    """)
    return conn


class EarlySetbackTopicTest(unittest.TestCase):
    def setUp(self):
        v2._QUERY_CACHE.clear()
        self.conn = make_conn()
        self.user = {"role_id": "dean", "username": "dean"}

    def tearDown(self):
        v2._QUERY_CACHE.clear()
        self.conn.close()

    def test_options_are_authorized_linked_and_ignore_self_dimension(self):
        base = early_setback_options(user=self.user, conn=self.conn)["data"]
        self.assertEqual(["O1", "O2"], [x["value"] for x in base["college"]])
        self.assertEqual(3, len(base["major"]))
        self.assertEqual([2022], [x["value"] for x in base["grade"]])
        self.assertEqual(4, len(base["class"]))

        college = early_setback_options(
            organization_id="O1", user=self.user, conn=self.conn,
        )["data"]
        self.assertEqual(2, len(college["college"]))
        self.assertEqual(["M1", "M2"], [x["value"] for x in college["major"]])
        self.assertEqual(3, len(college["class"]))

        major = early_setback_options(
            organization_id="O1", major_code="M1",
            user=self.user, conn=self.conn,
        )["data"]
        self.assertEqual(["M1", "M2"], [x["value"] for x in major["major"]])
        self.assertEqual(["班级一", "班级二"], [x["value"] for x in major["class"]])

    def test_focus_dimension_and_rate_sort_follow_filters(self):
        all_scope = early_setback_topic(
            limit=50, offset=0, user=self.user, conn=self.conn,
        )["data"]
        self.assertEqual("college", all_scope["focus_dimension"])
        self.assertEqual(["二院", "一院"], [x["group_name"] for x in all_scope["focus_groups"]])
        self.assertEqual([100.0, 80.0], [x["setback_rate"] for x in all_scope["focus_groups"]])
        self.assertEqual(
            {"专业一", "专业二", "专业三"},
            {x["major_name"] for x in all_scope["by_major"]},
        )

        college = early_setback_topic(
            organization_id="O1", limit=50, offset=0,
            user=self.user, conn=self.conn,
        )["data"]
        self.assertEqual("major", college["focus_dimension"])
        self.assertEqual(["专业二", "专业一"], [x["group_name"] for x in college["focus_groups"]])

        major = early_setback_topic(
            organization_id="O1", major_code="M1",
            limit=50, offset=0,
            user=self.user, conn=self.conn,
        )["data"]
        self.assertEqual("class", major["focus_dimension"])
        self.assertEqual(["班级二", "班级一"], [x["group_name"] for x in major["focus_groups"]])

        class_scope = early_setback_topic(
            organization_id="O1", major_code="M1", class_code="班级一",
            limit=50, offset=0,
            user=self.user, conn=self.conn,
        )["data"]
        self.assertEqual("class", class_scope["focus_dimension"])
        self.assertEqual(1, len(class_scope["focus_groups"]))
        self.assertEqual("班级一", class_scope["focus_groups"][0]["group_name"])

    def test_five_card_presets_reconcile_with_student_list(self):
        base = early_setback_topic(
            limit=50, offset=0, user=self.user, conn=self.conn,
        )["data"]
        expected = {
            "eligible": base["summary"]["eligible_students"],
            "setback": base["summary"]["setback_students"],
            "recovered": base["summary"]["recovered_students"],
            "persistent": base["summary"]["persistent_students"],
            "pending_observation": base["summary"]["pending_students"],
        }
        for preset, total in expected.items():
            with self.subTest(preset=preset):
                result = early_setback_topic(
                    observation_status=preset, limit=200, offset=0,
                    user=self.user, conn=self.conn,
                )["data"]
                self.assertEqual(total, result["total"])
                self.assertEqual(total, len(result["students"]))

    def test_options_and_results_do_not_escape_current_identity_scope(self):
        counselor = {"role_id": "counselor", "username": "counselor"}
        options = early_setback_options(user=counselor, conn=self.conn)["data"]
        self.assertEqual(["O1"], [x["value"] for x in options["college"]])
        self.assertEqual(["M1"], [x["value"] for x in options["major"]])
        self.assertEqual(["班级一"], [x["value"] for x in options["class"]])

        result = early_setback_topic(
            observation_status="eligible", limit=50, offset=0,
            user=counselor, conn=self.conn,
        )["data"]
        self.assertEqual(2, result["total"])
        self.assertEqual({"S1", "S2"}, {x["student_id"] for x in result["students"]})


if __name__ == "__main__":
    unittest.main()
