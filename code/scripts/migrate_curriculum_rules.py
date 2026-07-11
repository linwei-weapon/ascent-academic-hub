"""为现有培养方案建立模块性质和毕业要求支撑矩阵的单一数据源。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.settings import DB_PATH
from backend.api.routers.curriculum import _GRAD_REQS_12, _MODULE_ORDER, _MODULE_TO_GRAD_REQ


DDL = """
CREATE TABLE IF NOT EXISTS fact_plan_module_rule (
 major_id TEXT, grade TEXT, module TEXT,
 course_nature TEXT NOT NULL CHECK(course_nature IN ('required','elective')),
 min_credits REAL NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0,
 source TEXT NOT NULL DEFAULT 'derived', PRIMARY KEY (major_id,grade,module));
CREATE TABLE IF NOT EXISTS fact_grad_req_support (
 major_id TEXT, grade TEXT, module TEXT, requirement_no INTEGER,
 requirement_name TEXT, weight INTEGER NOT NULL DEFAULT 0 CHECK(weight BETWEEN 0 AND 3),
 source TEXT NOT NULL DEFAULT 'prototype',
 PRIMARY KEY (major_id,grade,module,requirement_no));
"""


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    plans = conn.execute("SELECT major_id,grade,elective_credits FROM fact_plan_meta").fetchall()
    for major_id, grade, elective_min in plans:
        modules = conn.execute("""SELECT module,SUM(COALESCE(credits,0)) FROM fact_plan_course
            WHERE major_id=? AND CAST(grade AS TEXT)=CAST(? AS TEXT) GROUP BY module""",
            (major_id, grade)).fetchall()
        elective_modules = [m for m, _ in modules if "选修" in (m or "")]
        elective_total = sum(c or 0 for m, c in modules if m in elective_modules) or 1
        for module, credits in modules:
            nature = "elective" if module in elective_modules else "required"
            minimum = round((elective_min or 0) * (credits or 0) / elective_total, 1) if nature == "elective" else credits or 0
            order = _MODULE_ORDER.index(module) if module in _MODULE_ORDER else 99
            conn.execute("""INSERT OR REPLACE INTO fact_plan_module_rule
                VALUES (?,?,?,?,?,?,?)""", (major_id, str(grade), module, nature, minimum, order, "derived-from-plan"))
            weights = _MODULE_TO_GRAD_REQ.get(module, [0] * 12)
            for idx, name in enumerate(_GRAD_REQS_12, 1):
                conn.execute("""INSERT OR REPLACE INTO fact_grad_req_support
                    VALUES (?,?,?,?,?,?,?)""", (major_id, str(grade), module, idx, name, weights[idx - 1], "prototype-migrated"))
    conn.commit()
    print("module rules:", conn.execute("SELECT COUNT(*) FROM fact_plan_module_rule").fetchone()[0])
    print("support rows:", conn.execute("SELECT COUNT(*) FROM fact_grad_req_support").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
