"""Install the validated prototype baseline in the LOCAL resource store only.

Run check-expert-resources.py first. This is an implementation review, not school
acceptance. Existing versions are retained; explicit runtime refresh creates new versions.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.metric_verification.config import load_environment
from backend.expert_resources import store, runtime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation',required=True,help='JSON report produced by check-expert-resources.py')
    parser.add_argument('--apply',action='store_true',help='Publish verified initial definitions in the local prototype store')
    parser.add_argument('--refresh-runtime',action='store_true',help='Retest unchanged seeded definitions and publish new versions after runtime changes')
    parser.add_argument('--upgrade-definitions',action='store_true',help='Use reviewed generated definitions for an unchanged published baseline; preserve custom persona/name and pending edits')
    args=parser.parse_args()
    report=json.loads(Path(args.validation).read_text(encoding='utf-8-sig'))
    if report.get('status')!='passed' or report.get('runtimeFingerprint')!=runtime.fingerprint():
        raise SystemExit('Run the read-only integration checks for the currently loaded runtime first.')
    load_environment()
    store.initialize()
    actor={'username':'prototype-implementation-review','name':'原型开发验证（Codex）','identity_id':'local-implementation',
        'permission_context':{'authorized':True,'activeIdentityId':'local-implementation','scopeFingerprint':'implementation-school-readonly',
            'actionPermissions':['system.manage'],'detailScope':{'type':'all'}}}
    checks={r['skillId']:r for r in report['checks']}
    registered=json.loads((store.CODE/'expert-resources/catalog.json').read_text(encoding='utf-8'))
    definitions = {(kind, value['id']): value.get('content', value) for kind in store.KINDS for value in registered[kind]}
    tool_contracts={t['name']:t for server in registered['mcps'] for t in server['tools']}
    note=('开发验证：已在114只读数据中核对输入、输出字段、记录数量、确定性公式、空值与来源。'
          '学分仅展示课程目录值，方案字段差异原值保留；毕业模块缺值不计0；异动按原状态分组。'
          '此发布用于本地原型体验，不代表产品经理或学校已完成业务验收。')
    outcomes=[]
    def install(kind,item,inputs):
        if item.get('published'):
            if not args.refresh_runtime:
                outcomes.append({'kind':kind,'id':item['id'],'status':'existing version retained'})
                return
            if item['draft']['content'] != item['published']['content']:
                outcomes.append({'kind':kind,'id':item['id'],'status':'pending user edits retained; upgrade in UI'})
                return
            if args.apply and item['draft']['version']==item['published']['version']:
                content=json.loads(json.dumps(item['draft']['content']))
                if args.upgrade_definitions:
                    generated = definitions.get((kind, item['id']))
                    if not generated:
                        raise SystemExit('No reviewed definition: ' + item['id'])
                    preserved = {key: content[key] for key in ('name','icon','personaPrompt','welcomeMessage','modelId','executionMode','expertType','maxIters') if key in content}
                    content=json.loads(json.dumps(generated))
                    content.update(preserved)
                if kind=='mcps':
                    for tool in content.get('tools',[]):
                        for schema in ('inputSchema','outputSchema'):
                            tool[schema]=tool_contracts[tool['name']][schema]
                item=store.save_resource(kind,item['id'],item['draft']['revision'],content,actor)
        if not args.apply:
            outcomes.append({'kind':kind,'id':item['id'],'status':'would test and publish'})
            return
        tested=store.test_resource(kind,item['id'],item['draft']['revision'],inputs,actor)
        test=tested['draft']['test']
        if test['status']!='passed':
            outcomes.append({'kind':kind,'id':item['id'],'status':test['status'],'summary':test['summary']})
            return
        if kind!='mcps':
            store.review_resource(kind,item['id'],tested['draft']['revision'],test['runId'],True,note,actor)
        published=store.publish_resource(kind,item['id'],tested['draft']['revision'],actor)
        outcomes.append({'kind':kind,'id':item['id'],'status':'published','version':published['published']['version']})
    for item in store.catalog(actor)['mcps']:
        if item['id']!='education-data':
            continue
        install('mcps',item,{})
    for item in store.catalog(actor)['skills']:
        if item['id'] not in checks:
            continue
        check=checks[item['id']]
        if check['status']=='passed':
            install('skills',item,check['input'])
        else:
            if args.apply:
                store.test_resource('skills',item['id'],item['draft']['revision'],check['input'],actor)
            outcomes.append({'kind':'skills','id':item['id'],'status':'blocked; missing evidence retained'})
    for item in store.catalog(actor)['experts']:
        if item['id'] not in {'program','course','transfer','recommendation','graduation'}:
            continue
        skill_ids=item['draft']['content']['skillIds']
        if any(sid not in checks or checks[sid]['status']!='passed' for sid in skill_ids):
            outcomes.append({'kind':'experts','id':item['id'],'status':'draft; missing business evidence'})
            continue
        sid=skill_ids[0]
        install('experts',item,{'skill_id':sid,**checks[sid]['input']})
    print(json.dumps({'applied':args.apply,'store':'local prototype only','reviewer':actor['name'],'resources':outcomes},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
