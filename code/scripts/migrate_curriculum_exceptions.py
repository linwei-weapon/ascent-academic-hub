"""建立培养方案例外认定结构；不生成没有业务来源的认定记录。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.settings import DB_PATH

DDL = """
CREATE TABLE IF NOT EXISTS fact_course_equivalence (
 equivalence_id INTEGER PRIMARY KEY AUTOINCREMENT, major_id TEXT NOT NULL, grade TEXT NOT NULL,
 target_course_id TEXT NOT NULL, substitute_course_id TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
 status TEXT NOT NULL DEFAULT 'active', approval_ref TEXT, source TEXT NOT NULL DEFAULT 'manual',
 UNIQUE(major_id,grade,target_course_id,substitute_course_id));
CREATE TABLE IF NOT EXISTS fact_student_credit_recognition (
 recognition_id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL,
 recognition_type TEXT NOT NULL, target_course_id TEXT, module TEXT, credits REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', approval_ref TEXT, approved_at TEXT,
 source TEXT NOT NULL DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS fact_plan_course_group (
 group_id TEXT, major_id TEXT, grade TEXT, group_name TEXT, module TEXT,
 min_courses INTEGER NOT NULL DEFAULT 0, min_credits REAL NOT NULL DEFAULT 0,
 course_ids_json TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'manual',
 PRIMARY KEY(group_id,major_id,grade));
CREATE TABLE IF NOT EXISTS curriculum_rule_change (
 change_id INTEGER PRIMARY KEY AUTOINCREMENT, rule_type TEXT NOT NULL, payload_json TEXT NOT NULL,
 reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 reviewed_by TEXT, reviewed_at TEXT, review_comment TEXT, activated_by TEXT, activated_at TEXT);
CREATE TABLE IF NOT EXISTS curriculum_rule_audit (
 audit_id INTEGER PRIMARY KEY AUTOINCREMENT, change_id INTEGER NOT NULL, action TEXT NOT NULL,
 operator TEXT NOT NULL, operated_at TEXT NOT NULL, detail TEXT);
"""

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    conn.commit()
    for table in ("fact_course_equivalence", "fact_student_credit_recognition", "fact_plan_course_group"):
        print(table, conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    conn.close()
