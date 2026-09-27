"""Apply the unified metric catalog V2 migration.

The migration is idempotent.  Markdown rows are staged as candidates; only
the code-verified seed registry is published to the formal catalog.

Run from the repository root:
    python -X utf8 code/scripts/migrate_metric_catalog_v2.py [database]
    python -X utf8 code/scripts/migrate_metric_catalog_v2.py [database] \
        --override-file reviewed-specifications.json

The optional JSON file is either a list or ``{"overrides": [...]}``.  Each
entry contains subjectKind (formal/candidate), subjectId, patch, reason and
sourceRef; overrideKey, priority and changedBy are optional audit metadata.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config
from backend.metric_catalog_v2 import migrate_metric_catalog_v2
from backend.metric_catalog_specification import upsert_specification_override


def apply_override_file(conn: sqlite3.Connection, override_path: Path) -> int:
    """Validate and store reviewed specification patches from one JSON file."""
    payload = json.loads(override_path.read_text(encoding="utf-8-sig"))
    rows = payload.get("overrides") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("override file must be a list or contain an overrides list")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"override entry {index} must be an object")
        try:
            upsert_specification_override(
                conn,
                subject_kind=row["subjectKind"],
                subject_id=row["subjectId"],
                patch=row["patch"],
                reason=row["reason"],
                source_ref=row["sourceRef"],
                override_key=row.get("overrideKey", "manual"),
                priority=row.get("priority", 100),
                changed_by=row.get("changedBy"),
            )
        except KeyError as exc:
            raise ValueError(
                f"override entry {index} is missing {exc.args[0]}"
            ) from exc
    return len(rows)


def migrate(
    conn: sqlite3.Connection,
    document_path: Path | None = None,
    override_path: Path | None = None,
) -> dict:
    result = migrate_metric_catalog_v2(conn, document_path)
    if override_path is not None:
        result["specificationOverridesApplied"] = apply_override_file(
            conn, override_path,
        )
        # Re-run the idempotent materializer so overrides and the effective
        # specification are committed atomically by this wrapper.
        materialized = migrate_metric_catalog_v2(conn, document_path)
        result.update(materialized)
    conn.commit()
    return result


def main(
    db_path: Path | None = None, override_path: Path | None = None,
) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        result = migrate(conn, override_path=override_path)
    finally:
        conn.close()
    print(f"== 指标目录V2迁移: {path} ==")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", type=Path)
    parser.add_argument("--override-file", type=Path)
    arguments = parser.parse_args()
    main(arguments.database, arguments.override_file)
