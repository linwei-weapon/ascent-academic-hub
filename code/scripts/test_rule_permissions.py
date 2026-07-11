"""在数据库副本验证规则治理职责分离。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.envelope import ApiError
from backend.api.routers.settings import _ensure_governance, _require_rule_permission
from backend.etl.config import DB_PATH


CASES = [
    ({"username": "admin", "role_id": "dean"}, "edit", True),
    ({"username": "admin", "role_id": "dean"}, "review", False),
    ({"username": "quality_office", "role_id": "quality_office"}, "review", True),
    ({"username": "quality_office", "role_id": "quality_office"}, "publish", False),
    ({"username": "school_leader", "role_id": "school_leader"}, "activate", True),
    ({"username": "counselor", "role_id": "counselor"}, "audit", False),
]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_rule_permissions.py <copied-db>")
    path = Path(sys.argv[1]).resolve()
    if path == Path(DB_PATH).resolve():
        raise SystemExit("拒绝在生产数据库执行权限专项测试")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_governance(conn)
    results = []
    for user, permission, expected in CASES:
        allowed = True
        try:
            _require_rule_permission(conn, user, permission)
        except ApiError as exc:
            allowed = False
            if exc.code != 403:
                raise
        results.append((user["role_id"], permission, allowed))
        if allowed != expected:
            raise SystemExit(f"权限结果不符：{user['role_id']} {permission}")
    conn.rollback()
    conn.close()
    print(results)


if __name__ == "__main__":
    main()
