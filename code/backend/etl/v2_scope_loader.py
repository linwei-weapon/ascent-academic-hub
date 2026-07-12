"""把现有RBAC范围代码显式映射到V2真实组织、专业和行政班。"""
import json
from pathlib import Path

from . import config
from .init_v2 import init_v2


def load_scope_mappings(db_path: Path | None = None, legacy_path: Path | None = None) -> dict:
    conn = init_v2(db_path)
    legacy_path = Path(legacy_path or config.DB_PATH)
    try:
        conn.execute("ATTACH DATABASE ? AS legacy", (str(legacy_path),))
        conn.execute("DELETE FROM access_scope_mapping")
        rows = conn.execute("""SELECT s.role_id,s.scope_id,r.data_scope_type,
            CASE r.data_scope_type WHEN 'college' THEN c.name WHEN 'major' THEN m.name WHEN 'class' THEN b.name END scope_name
            FROM legacy.sys_role_scope s JOIN legacy.sys_role r ON r.role_id=s.role_id
            LEFT JOIN legacy.dim_college c ON r.data_scope_type='college' AND c.college_id=s.scope_id
            LEFT JOIN legacy.dim_major m ON r.data_scope_type='major' AND m.major_id=s.scope_id
            LEFT JOIN legacy.dim_class b ON r.data_scope_type='class' AND b.class_id=s.scope_id""").fetchall()
        mapped = 0
        for role_id, scope_id, scope_type, name in rows:
            org = major = class_code = None
            if scope_type == "college":
                found = conn.execute("SELECT organization_id FROM dim_organization WHERE name=?", (name,)).fetchone()
                org = found[0] if found else None
            elif scope_type == "major":
                found = conn.execute("SELECT major_code FROM dim_student WHERE major_name=? AND major_code IS NOT NULL LIMIT 1", (name,)).fetchone()
                major = found[0] if found else None
            elif scope_type == "class":
                found = conn.execute("SELECT class_code FROM dim_student WHERE class_code=? LIMIT 1", (name,)).fetchone()
                class_code = found[0] if found else None
            status = "mapped" if any((org, major, class_code)) else "unmapped"
            mapped += status == "mapped"
            conn.execute("INSERT INTO access_scope_mapping(role_id,scope_type,source_scope_id,organization_id,major_code,class_code,mapping_status,note) VALUES(?,?,?,?,?,?,?,?)",
                         (role_id, scope_type, scope_id, org, major, class_code, status, None if status == "mapped" else f"未匹配名称: {name}"))
        conn.commit()
        cursor = conn.execute("SELECT * FROM access_scope_mapping ORDER BY role_id,source_scope_id")
        columns = [item[0] for item in cursor.description]
        report = {"total": len(rows), "mapped": mapped, "unmapped": len(rows)-mapped,
                  "rows": [dict(zip(columns, x)) for x in cursor.fetchall()]}
        conn.execute("DETACH DATABASE legacy")
    finally:
        conn.close()
    return report


def main():
    print(json.dumps(load_scope_mappings(), ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
