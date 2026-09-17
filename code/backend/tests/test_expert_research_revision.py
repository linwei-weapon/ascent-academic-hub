"""Regression of the actual director task, including adverse language and data."""
import copy
import unittest
from io import BytesIO
from zipfile import ZipFile
from backend.expert_research import service, program_review, memo, materials

FOLLOWUP='先不判断专业特色。请把公共课程排除，只列双方已经明确属于专业基础和专业主干的共同课程；分类不清楚的单列。告诉我这次可以请学院核对的具体课程和培养目标材料是什么。'

def course(cid,layer):
    labels={'foundation':'专业基础','main':'专业主干','common':'公共课程','unknown':'层级待明确','mixed':'跨层级记录'}
    return {'id':cid,'name':'课程'+cid,'layer':layer,'layer_label':labels[layer], 'modules':[labels[layer]],
        'common':layer=='common','mandatory':True,'individual_required':True,'source':'课程源表', 'credits':[2], 'required':True}

def result(conflict=False):
    doc=lambda name: {'plan':name,'file':name+'.doc','sections':[],'issues':[],'status':'extracted'}
    docs=[doc('甲方案'),doc('乙方案')]
    if conflict:docs[0].update(status='conflict',issues=['培养目标为其他专业表述，原文归属需确认'])
    return {'expert_id':'program','scenario':'overlap','title':'比较','headline':'旧标题','body':'',
        'documents':docs,'tables':[{'id':'positioning','rows':[{'plan':'甲方案','text':'错误培养目标'},{'plan':'乙方案','text':'可用内容'}],'note':'','title':'原文','columns':[]}],
        'comparison':{'source':{'plan_id':'a'},'target':{'plan_id':'b'}},'missing':[],'methods':[],'limitations':[], 'sources':[], 'candidates':[{'plan_id':'c'}]}

class RevisionTests(unittest.TestCase):
    def test_original_followup_changes_scope_and_avoids_negated_feature(self):
        changes,msg=service.resolve(FOLLOWUP,{'plan_id':'a','target_plan_id':'b','focus':'all'})
        self.assertFalse(msg);self.assertEqual(changes,[('program','overlap',{'focus':'foundation_main'})])

    def test_scope_paraphrases(self):
        for text,focus in [('请去掉公共课程再比较','non_common'),('只看专业基础，不看公共课','foundation'),
            ('仅列专业主干共同课程','main'),('排除公共课，只保留专业基础和主干课程','foundation_main'),
            ('查看全部课程','all'),('研究相近专业的全部课程结构','all'),('只看逐门必修','required'),('只看专业实践','practice')]:
            with self.subTest(text=text):
                intents,error=service.resolve(text,{'plan_id':'a'})
                self.assertFalse(error);self.assertEqual(intents[0][2]['focus'],focus)

    def test_unsupported_conditions_do_not_silently_keep_old_scope(self):
        for text in ['只看三学分的专业基础','只看专业基础且学分大于3','排除公共课和英语课',
                     '不要排除公共课程','查看全部课程，同时只看专业基础','只比较专业实践与专业基础',
                     '只看专业基础前十门','排除英语课程','只看大一课程']:
            with self.subTest(text=text):
                intents,error=service.resolve(text,{'plan_id':'a','focus':'all'})
                self.assertFalse(intents);self.assertTrue(error)

    def test_explicit_expert_mismatch_does_not_execute_another(self):
        self.assertFalse(service.resolve('只看专业主干',{'plan_id':'a'},explicit='course')[0])

    def test_partial_intersection_excludes_public_unknown_and_one_sided(self):
        a={i:course(i,l) for i,l in [('1','foundation'),('2','common'),('3','main'),('4','unknown'),('5','foundation')]}
        b={i:course(i,l) for i,l in [('1','main'),('2','common'),('3','unknown'),('4','main')]}
        r=program_review.apply(result(),{'focus':'foundation_main'},a,b,'director')
        t={x['id']:x for x in r['tables']}
        self.assertEqual([x['id'] for x in t['selected_shared']['rows']],['1'])
        self.assertEqual([x['id'] for x in t['classification_pending']['rows']],['3','4'])
        self.assertEqual(r['comparison']['focus_union'],4)
        self.assertIsNone(r['comparison']['focus_similarity']);self.assertEqual(r['candidates'],[])
        self.assertIn('已明确',r['request_receipt'])

    def test_conflicting_original_is_quarantined_not_source_rewritten(self):
        original=result(True);r=copy.deepcopy(original)
        a={'1':course('1','foundation')};b={'1':course('1','foundation')}
        program_review.apply(r,{'focus':'foundation_main'},a,b,'dean')
        self.assertEqual(r['documents'],original['documents']);self.assertTrue(r['critical_issues'])
        self.assertIn('原文确认',r['headline']);self.assertIn('1门',r['body'])
        positioning=next(t for t in r['tables'] if t['id']=='positioning')
        self.assertEqual([x['plan'] for x in positioning['rows']],['乙方案'])
        self.assertIn('本院',r['management_note'])

    def test_disputed_document_cannot_supply_missing_classification(self):
        a={'1':course('1','main')};a['1']['modules']=['不明确模块']
        safe=program_review.safe_courses(a,result(True)['documents'][0])
        self.assertEqual(safe['1']['layer'],'unknown');self.assertEqual(a['1']['layer'],'main')

    def test_all_pool_is_not_rank_and_does_not_ask_review_hundreds(self):
        a={str(i):course(str(i),'common') for i in range(250)}
        r=program_review.apply(result(),{'focus':'all'},a,a,'director')
        self.assertEqual(r['candidates'],[]);self.assertNotIn('250',r['decision_summary'])
        self.assertIn('250门',r['body']);self.assertNotIn('%',r['headline'])

    def test_memo_order_freeze_and_conflict_quarantine(self):
        r=result(True);r['tables'][0]['columns']=[{'key':'text','label':'原文'}]
        snap={'title':'测试研究','result':r,'opinion':{'text':'先确认原文再讨论','revision':2},'questions':[]}
        frozen=memo.build(snap);snap['discussion_memo']=frozen
        titles=[s['title'] for s in frozen['sections']]
        self.assertLess(titles.index('个人意见（经本人确认选入）'),titles.index('尚需补充的情况'))
        self.assertNotIn('错误培养目标',str(frozen))
        r['headline']='事后变化';self.assertNotIn('事后变化',str(frozen))
        artifact={'id':'m','research_id':'r','title':'测试','created_at':'2026-09-16T00:00:00+00:00','snapshot':snap}
        payload=materials.render_docx(artifact)
        xml=ZipFile(BytesIO(payload)).read('word/document.xml').decode()
        self.assertLess(xml.index('先确认原文再讨论'),xml.index('附录：课程与计算资料'))
        self.assertNotIn('错误培养目标',xml);self.assertIn('08:00',xml)

    def test_no_fabricated_personal_opinion(self):
        value=memo.build({'result':result(),'opinion':None})
        self.assertFalse(any('个人意见' in s['title'] for s in value['sections']))

    def test_zero_subset_never_means_different_training_and_memo_has_concrete_summary(self):
        r=program_review.apply(result(True),{'focus':'foundation_main'},{'1':course('1','foundation')},{'2':course('2','main')},'dean')
        self.assertIn('不能据此判断',r['headline'])
        r['tables'].append({'id':'course_options','title':'建设做法','columns':[{'key':'action','label':'做法'}], 'rows':[{'action':'复盘具体考核安排'}],'note':'需先了解情况'})
        summary=memo.build({'result':r})
        self.assertTrue(any('复盘具体考核安排' in ' '.join(s['paragraphs']) for s in summary['sections']))

if __name__=='__main__':unittest.main()
