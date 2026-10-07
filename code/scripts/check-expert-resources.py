"""Read-only test-database integration checks; never publishes or changes school data."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.metric_verification.config import load_environment
from backend.metric_verification.database import connection
from backend.expert_resources.runtime import execute_resource, analysis_options, rows, run_tool, fingerprint
from backend.api.envelope import ApiError


def main():
    load_environment()
    actor = {'username': 'implementation-readonly-check', 'identity_id': 'test-harness',
             'permission_context': {'authorized': True, 'activeIdentityId': 'test-harness',
                'scopeFingerprint': 'readonly-integration', 'actionPermissions': ['system.manage'], 'detailScope': {'type': 'all'}}}
    catalog = json.loads((Path(__file__).resolve().parents[1]/'expert-resources/catalog.json').read_text(encoding='utf-8'))
    options = analysis_options(actor)
    assert len(options['plans']) > 1 and options['semesters'], 'No usable real analysis objects'
    source_plan, target_plan = options['plans'][:2]
    with connection('analytics', consistent=True) as db:
        progress_plan = rows(db, '''SELECT p.plan_id,COUNT(*) n FROM act_student_plan_progress_summary p
            JOIN act_curriculum_plan c ON c.plan_id=p.plan_id GROUP BY p.plan_id ORDER BY n DESC LIMIT 1''')[0]['plan_id']
        first_set = {r['course_id'] for r in rows(db,'SELECT DISTINCT course_id FROM act_curriculum_plan_course WHERE plan_id=%s AND course_id IS NOT NULL',[source_plan['id']])}
        second_set = {r['course_id'] for r in rows(db,'SELECT DISTINCT course_id FROM act_curriculum_plan_course WHERE plan_id=%s AND course_id IS NOT NULL',[target_plan['id']])}
    inputs = {
        'program-structure': {'plan_id': source_plan['id'], 'limit': 20},
        'program-comparison': {'plan_id': source_plan['id'], 'target_plan_id': target_plan['id'], 'limit': 20},
        'course-performance': {'semester_id': options['semesters'][0]['id'], 'limit': 20},
        'transfer-plan-gap': {'plan_id': source_plan['id'], 'target_plan_id': target_plan['id'], 'limit': 20},
        'transfer-history': {'limit': 20}, 'graduation-progress': {'plan_id': progress_plan},
        'graduation-audit': {'limit': 20}, 'recommendation-policy': {}, 'capacity-evidence': {}}
    checks = []
    dependencies = {'mcps': [{**server, 'version': 'integration-contract', 'content': server} for server in catalog['mcps']],
                    'snapshot': [{'kind': 'mcps', 'id': server['id'], 'version': 'integration-contract', 'enabled': True} for server in catalog['mcps']]}
    for skill in catalog['skills']:
        if skill['id'] not in inputs:
            continue  # Expanded candidate definitions have their own readiness/tests.
        if skill['execution'].get('processorId') and not skill['execution']['processorId'].startswith('legacy:'):
            selected = inputs[skill['id']]
            selected['previewLimit'] = selected.pop('limit', 20)
            if skill['id'] == 'program-comparison':
                selected['comparisonMode'] = 'all_course_ids'
        result = execute_resource('skills',skill,inputs[skill['id']],actor,dependencies)
        expected = 'blocked' if skill['execution'].get('handler')=='unavailable' else 'passed'
        assert result['status']==expected, skill['id'] + ': '+result['summary']
        if skill['id'] in {'program-comparison','transfer-plan-gap'}:
            data=result['result']['data']
            assert data['共同课程种数']==len(first_set & second_set)
            assert data['合并去重课程种数']==len(first_set | second_set)
        if skill['id']=='graduation-progress':
            for r in result['result']['tables'][0]['rows']:
                if not r['valid_remaining_records']:
                    assert r['remaining_records'] is None and r['avg_remaining'] is None
        checks.append({'skillId': skill['id'],'input':inputs[skill['id']], 'status':result['status'],
                       'summary':result['summary'], 'missingEvidence':result['missingEvidence']})
    for college_id in ['35','34']:
        academy = {**actor, 'permission_context': {**actor['permission_context'], 'actionPermissions':['ai.analyze'],
                    'detailScope':{'type':'college','collegeIds':[college_id]}}}
        scoped = analysis_options(academy)
        assert all(p['college_id']==college_id for p in scoped['plans'])
        outside = next(p for p in options['plans'] if p['college_id']!=college_id)
        try:
            run_tool('read_program_structure',{'plan_id':outside['id']},academy)
        except ApiError as exc:
            assert exc.status_code==403
        else:
            raise AssertionError('Cross-college plan access was not denied')
    print(json.dumps({'status':'passed','kind':'read-only database integration; fixture identities, not remote-login validation',
        'runtimeFingerprint':fingerprint(),'planOptions':len(options['plans']),'checks':checks,
        'scopeChecks':'two separate academies and cross-academy rejection passed'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
