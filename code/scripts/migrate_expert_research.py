"""Create the separate research store and immutable legacy archives.

Default is read-only dry-run. --apply initializes only the separate store.
--import-legacy additionally archives old records after a confirmed write freeze.
SQLite backups precede changes; no old table is edited.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.expert_research import store
from backend.expert_team import storage as legacy
from backend.api import settings


def readonly(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def backup(source, directory):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    destination = directory / f'{source.name}.{stamp}.{uuid.uuid4().hex[:8]}.backup'
    with closing(readonly(source)) as src, closing(sqlite3.connect(destination)) as dest:
        src.backup(dest)
    return str(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=store.path())
    parser.add_argument('--legacy', type=Path, default=legacy.path())
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--import-legacy', action='store_true')
    parser.add_argument('--confirm-legacy-read-only', action='store_true')
    args = parser.parse_args(argv)
    target, source = args.target.resolve(), args.legacy.resolve()
    protected = {source, Path(settings.DB_PATH).resolve(), Path(settings.V2_DB_PATH).resolve()}
    if target in protected:
        parser.error('target must be a separate research database, not a business or legacy source')
    if target.exists():
        with closing(readonly(target)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'er_research' not in tables:
                parser.error('existing target is not a recognized research database')
    records = 0
    if source.is_file():
        with closing(readonly(source)) as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_session'").fetchone()
            if exists:
                records = conn.execute('SELECT COUNT(*) FROM team_session').fetchone()[0]
    report = dict(mode='apply' if args.apply else 'dry_run', target=str(target), legacy=str(source),
                  legacy_records=records, target_exists=target.exists(), source_changes=False, backups=[])
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.import_legacy and records and not args.confirm_legacy_read_only:
        parser.error('freeze old expert-team writes first, then pass --confirm-legacy-read-only')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        report['backups'].append(backup(target, target.parent))
    if args.import_legacy and source.is_file():
        report['backups'].append(backup(source, target.parent))
    with closing(sqlite3.connect(target)) as conn:
        store.migrate(conn)
        if args.import_legacy and records:
            with closing(readonly(source)) as src:
                report['archive'] = store.import_legacy(conn, src, source.as_uri())
        else:
            report['archive'] = dict(imported=0, unchanged=0, conflicts=[])
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        report['integrity_check'] = integrity
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report['archive']['conflicts'] or integrity != 'ok' else 0


if __name__ == '__main__':
    raise SystemExit(main())
