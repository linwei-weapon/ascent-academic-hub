"""Read-only real-data smoke check. Writes no business data or discussion sessions."""
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.etl import config
from backend.expert_team import analysis, storage
from backend.expert_team.catalog import catalog


def main():
    v2=sqlite3.connect(config.V2_DB_PATH.resolve().as_uri()+'?mode=ro',uri=True)
    team=sqlite3.connect(storage.path().resolve().as_uri()+'?mode=ro',uri=True)
    for db in (v2,team):db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
    user={'username':'readonly-test','permission_context':{'authorized':True,'activeRole':'dean','activeIdentityId':'test',
          'scopeFingerprint':'test','detailScope':{'type':'all'}}}
    p=v2.execute("SELECT plan_id FROM curriculum_plan WHERE major_name='计算机科学与技术' AND plan_name NOT LIKE '%实验%' LIMIT 1").fetchone()[0]
    for ex in catalog():
        for s in ex['scenarios']:
            start=time.perf_counter()
            result=analysis.analyze(v2,team,user,{'expert_id':ex['id'],'scenario':s['id'],'plan_id':p})
            print(json.dumps({'expert':ex['id'],'scenario':s['id'],'status':result['status'],'headline':result['headline'],
                              'tables':[(t['id'],len(t['rows'])) for t in result['tables']],
                              'seconds':round(time.perf_counter()-start,3)},ensure_ascii=False),flush=True)
    print('COURSE_ROWS',team.execute('SELECT COUNT(*) FROM team_plan_course').fetchone()[0])
    print('DOCUMENT_STATUS', [tuple(r) for r in team.execute('SELECT status,COUNT(*) FROM team_document GROUP BY status')])
    print('PROGRESS_STATUS',[tuple(r) for r in v2.execute('SELECT binding_status,evidence_status,COUNT(*) FROM student_plan_progress_summary GROUP BY 1,2')])
    print('CONFLICTS',[dict(r) for r in team.execute("SELECT file_name,issues_json FROM team_document WHERE status='conflict'")])
    print('READ_ONLY_SMOKE_PASS')
    v2.close();team.close()


if __name__=='__main__':main()
