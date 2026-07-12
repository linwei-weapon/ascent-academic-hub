import unittest
import sqlite3
from backend.api.main import app
from backend.api.envelope import ApiError
from backend.api.routers.v2 import _student_scope, require_v2_all_reader, require_v2_reader

class V2ApiTest(unittest.TestCase):
    def test_v2_routes_registered(self):
        paths = {route.path for route in app.routes}
        expected = {"/api/v2/health", "/api/v2/meta/teaching-semesters", "/api/v2/students/difficult",
                    "/api/v2/students/{student_id}/growth",
                    "/api/v2/students/{student_id}/plan-courses",
                    "/api/v2/students/{student_id}/advice",
                    "/api/v2/topics/early-setback",
                    "/api/v2/topics/graduation-readiness",
                    "/api/v2/topics/course-quality",
                    "/api/v2/topics/course-quality/{course_id}/detail",
                    "/api/v2/topics/faculty-resource-risk",
                    "/api/v2/topics/schedule-strategy",
                    "/api/v2/courses/offerings", "/api/v2/courses/schedule-distribution",
                    "/api/v2/courses/{course_id}/team",
                    "/api/v2/teachers/{staff_id}/schedule-preference", "/api/v2/rooms/summary"}
        self.assertTrue(expected.issubset(paths))

    def test_unknown_role_is_denied(self):
        with self.assertRaises(ApiError):
            require_v2_reader({"role_id": "unknown"})
        self.assertEqual("dean", require_v2_reader({"role_id": "dean"})["role_id"])

    def test_scoped_role_is_denied_from_all_scope_endpoint(self):
        with self.assertRaises(ApiError):
            require_v2_all_reader({"role_id": "counselor"})

    def test_student_scope_uses_explicit_class_mapping(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE access_scope_mapping(role_id TEXT,scope_type TEXT,source_scope_id TEXT,organization_id TEXT,major_code TEXT,class_code TEXT,mapping_status TEXT)")
        conn.execute("INSERT INTO access_scope_mapping VALUES('counselor','class','B1',NULL,NULL,'计算机21-1班','mapped')")
        fragment, params = _student_scope({"role_id": "counselor"}, conn, "s")
        conn.close()
        self.assertEqual("s.class_code IN (?)", fragment)
        self.assertEqual(["计算机21-1班"], params)

if __name__ == "__main__": unittest.main()
