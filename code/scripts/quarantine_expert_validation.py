"""Reversible isolation of reviewed validation records; never renames business data.

Default: read-only inventory. --apply writes er_meta markers after a full backup.
--restore removes only this script's markers. All research contents remain intact.
"""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.expert_research import store

# Exact IDs reviewed in the 2026-09-16 leadership audit, not a text-regex purge.
REVIEWED = set('''513d689e-08b3-4e0c-99be-3c60eb1654ea cd333198-c078-4806-b811-3c290b538ca8 aa777592-5e76-4c23-b6cd-addee80715e9 ccea3682-3067-4f6c-9749-d4803b706953 5b009744-9742-4750-83f0-12901b950465 e52e60c2-7f49-4759-aedf-e708c2983f3d 4937e76a-353b-4a64-a003-f82f35e8150c e7961ddd-26d8-4394-a60e-459978e19846 2db3de5d-a0f4-4562-965e-bf977a9b891a 9d5b3288-2474-4680-9c1e-f8b5207c3270 0794df72-e0e5-42b8-88f5-c01068458efb 1862d5cf-9e20-4210-9a38-01c5c0ca85da d475a7b7-ce00-4faa-b68b-698d567aebe2 d151bbfb-e263-4fda-9047-4d5c23f57a3d 9d7f3b2b-d781-4877-900c-61df22fd11f5 31819c10-0a5e-4593-8b1e-840cd7c9d14b 876c3e9e-d0c0-415e-bca1-45bf92db6cbf c0e95b2d-f6bd-40ed-8b02-683eb17baf40 e630c0a9-af12-48cf-b7ff-ab575f39a327 0cac809a-5864-4858-80b1-5194d51df67a f1f3c642-6804-4955-9edf-1cf24fdf09a2 170111ad-f214-41f5-97ad-2e8317e7107e 1af5445c-4eee-4113-9862-cef6a4784bb9 d2277a3b-63b9-4ad7-88f2-a61d399cd98d df3d3336-8857-427d-8bcd-6250d31593ab f42785b8-99c8-41b5-9b19-8fc5848d1721 c7272082-1449-48e9-beb6-939bf0307da2 20b9c86e-845c-48b4-a1af-d0d919592fa6 ecfcb8c0-3c16-4bf0-bd65-13204e7b11e7 7dd30ace-95b4-45bd-8ef8-3a9deb3386d7'''.split())
TAG='leadership-cleanup-20260916'

def selected(conn):
    rows=[dict(r) for r in conn.execute('SELECT id,username,title,status FROM er_research') if r['id'] in REVIEWED]
    for row in rows:
        if row['username'] not in {'dean','college_dean'} or row['status']!='archived' or not row['title'].startswith(('[自动验证]','【体验走查】','【R2全过程体验】')):
            raise ValueError('Reviewed record has changed; stop for manual review: '+row['id'])
        if conn.execute("SELECT 1 FROM er_run WHERE research_id=? AND status IN ('queued','running','cancel_requested')",(row['id'],)).fetchone():
            raise ValueError('Cannot isolate an active run')
    return rows

def mark(conn, rows, restore=False):
    with store.transaction(conn):
        for row in rows:
            key='qa:research:'+row['id']
            if restore:
                old=conn.execute('SELECT value FROM er_meta WHERE key=?',(key,)).fetchone()
                if old and json.loads(old[0]).get('operation')==TAG:conn.execute('DELETE FROM er_meta WHERE key=?',(key,))
            else:
                conn.execute('INSERT OR IGNORE INTO er_meta VALUES(?,?)',(key,store.encode({'operation':TAG,'marked_at':store.now(),'original_title':row['title']})))

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--apply',action='store_true');g.add_argument('--restore',action='store_true');args=p.parse_args()
    target=store.path().resolve();root=Path(__file__).resolve().parents[2]
    if target!=root/'code/backend/db/expert_research.sqlite':raise ValueError('Only the named leadership research database may be isolated')
    conn=sqlite3.connect(target.as_uri()+('?mode=rw' if args.apply or args.restore else '?mode=ro'),uri=True);conn.row_factory=sqlite3.Row
    try:
        rows=selected(conn);backup=None
        if args.apply or args.restore:
            out=root/'work/expert-team/leadership-20260916/recovery';out.mkdir(parents=True,exist_ok=True)
            backup=out/('research-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.sqlite')
            with closing(sqlite3.connect(backup)) as saved:conn.backup(saved)
            mark(conn,rows,args.restore)
        print(json.dumps({'mode':'restore' if args.restore else 'apply' if args.apply else 'inventory','reviewed':len(rows),'backup':str(backup) if backup else None,'records':rows,'content_deletions':0},ensure_ascii=False))
    finally:conn.close()

if __name__=='__main__':main()
