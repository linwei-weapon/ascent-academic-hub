"""培养方案规则治理状态机专项测试；只走驳回分支并清理临时记录。"""
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.settings import DB_PATH

BASE = "http://127.0.0.1:8000"
PASSWORD = "Demo@2026"


def request(path, token=None, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def login(username):
    status, result = request("/api/auth/login", method="POST", body={"username": username, "password": PASSWORD})
    assert status == 200, (username, result)
    return result["data"]["token"]


def main():
    conn = sqlite3.connect(DB_PATH)
    users = {role: role for role in ("dean", "quality_office", "school_leader")}
    dean, quality, leader = (login(users[r]) for r in ("dean", "quality_office", "school_leader"))
    status, created = request("/api/admin/curriculum/rule-changes", dean, "POST", {
        "ruleType": "course_equivalence", "reason": "AUTOTEST temporary rejected change",
        "payload": {"majorId": "M014", "grade": "2022", "targetCourseId": "TEST-TARGET",
                    "substituteCourseId": "TEST-SUB", "approvalRef": "AUTOTEST"}})
    assert status == 200, created
    change_id = created["data"]["changeId"]
    try:
        preview_response = request(f"/api/admin/curriculum/rule-changes/{change_id}/preview", dean)
        assert preview_response[0] == 200, preview_response
        preview = preview_response[1]["data"]
        assert preview["isEstimate"] is True and preview["conflict"] is None
        duplicate_status = request("/api/admin/curriculum/rule-changes", dean, "POST", {
            "ruleType": "course_equivalence", "reason": "AUTOTEST duplicate",
            "payload": {"majorId": "M014", "grade": "2022", "targetCourseId": "TEST-TARGET",
                        "substituteCourseId": "TEST-SUB", "approvalRef": "AUTOTEST"}})[0]
        assert duplicate_status == 409
        assert request(f"/api/admin/curriculum/rule-changes/{change_id}/activate", dean, "POST", {})[0] == 403
        assert request(f"/api/admin/curriculum/rule-changes/{change_id}/submit", dean, "POST", {})[1]["data"]["status"] == "submitted"
        assert request(f"/api/admin/curriculum/rule-changes/{change_id}/review", leader, "POST", {"approved": True})[0] == 403
        reviewed = request(f"/api/admin/curriculum/rule-changes/{change_id}/review", quality, "POST",
                           {"approved": False, "comment": "AUTOTEST reject"})
        assert reviewed[1]["data"]["status"] == "rejected"
        detail = request(f"/api/admin/curriculum/rule-changes/{change_id}", dean)[1]["data"]
        assert [x["action"] for x in detail["auditTrail"]] == ["created", "submitted", "rejected"]
        print("PASS preview, duplicate conflict, roles, state transitions, audit trail")
    finally:
        conn.execute("DELETE FROM curriculum_rule_audit WHERE change_id=?", (change_id,))
        conn.execute("DELETE FROM curriculum_rule_change WHERE change_id=?", (change_id,))
        conn.commit()
    # 激活分支：短暂写入专用 TEST 课程替代，断言后立即清理。
    created2 = request("/api/admin/curriculum/rule-changes", dean, "POST", {
        "ruleType": "course_equivalence", "reason": "AUTOTEST activation cleanup",
        "payload": {"majorId": "M014", "grade": "2022", "targetCourseId": "TEST-ACTIVE-TARGET",
                    "substituteCourseId": "TEST-ACTIVE-SUB", "approvalRef": "AUTOTEST-ACTIVE"}})[1]
    change2 = created2["data"]["changeId"]
    try:
        request(f"/api/admin/curriculum/rule-changes/{change2}/submit", dean, "POST", {})
        request(f"/api/admin/curriculum/rule-changes/{change2}/review", quality, "POST", {"approved": True, "comment": "AUTOTEST"})
        active = request(f"/api/admin/curriculum/rule-changes/{change2}/activate", leader, "POST", {})
        assert active[1]["data"]["status"] == "activated"
        assert conn.execute("SELECT COUNT(*) FROM fact_course_equivalence WHERE approval_ref='AUTOTEST-ACTIVE'").fetchone()[0] == 1
        print("PASS approved activation writes effective rule")
    finally:
        conn.execute("DELETE FROM fact_course_equivalence WHERE approval_ref='AUTOTEST-ACTIVE'")
        conn.execute("DELETE FROM curriculum_rule_audit WHERE change_id=?", (change2,))
        conn.execute("DELETE FROM curriculum_rule_change WHERE change_id=?", (change2,))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    main()
