"""Course-management scenes built from the existing first-attempt definition."""
from collections import defaultdict
from datetime import date

from ..api.envelope import ApiError
from . import curriculum


# Same published/non-void, non-makeup/retake population as v2_course_pass_builder.
# Deferred and unknown attempt types remain in the first-attempt population.
VALID_FIRST = """g.source IN ('real','real_legacy') AND g.is_published=1 AND g.is_void=0
    AND g.is_pass IN (0,1) AND (g.attempt_type IS NULL OR g.attempt_type NOT IN ('makeup','retake'))"""


def calendar_order(v2):
    """An ID is a label, not a date. Duplicate/invalid periods stay unclassified."""
    periods = {}
    duplicates = set()
    for row in v2.execute('SELECT semester_id,start_date,end_date FROM dim_semester'):
        try:
            start, end = date.fromisoformat(row[1]), date.fromisoformat(row[2])
        except (ValueError, TypeError):
            continue
        if start > end:
            continue
        if start.isoformat() in periods.values():
            duplicates.add(start.isoformat())
        periods[row[0]] = start.isoformat()
    return {key:value for key,value in periods.items() if value not in duplicates}


def percentage_point_change(current, previous):
    """Round the difference once, not the two displayed rates separately."""
    if not previous or not current['attempts'] or not previous['attempts']: return None
    return round(100 * (current['fails'] / current['attempts'] - previous['fails'] / previous['attempts']), 1)


def history(v2, user, plan_id):
    from .analysis import assert_plan, scoped_students, rows
    assert_plan(v2, user, plan_id)
    scope, params = scoped_students(v2, user)
    return rows(v2, f"""SELECT g.course_id,MAX(g.course_name) name,g.semester_id semester,
        COUNT(*) attempts,SUM(g.is_pass=0) fails,COUNT(DISTINCT g.student_id) students,
        COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) failed_students,
        ROUND(100.0*SUM(g.is_pass=0)/COUNT(*),1) fail_rate
        FROM grade_attempt g JOIN dim_student s ON s.student_id=g.student_id
        WHERE s.plan_id=? AND {scope} AND {VALID_FIRST} AND g.semester_id IS NOT NULL
        GROUP BY g.course_id,g.semester_id ORDER BY g.semester_id,g.course_id""", (plan_id, *params))


def class_distribution(v2, user, plan_id, semester, course_id):
    from .analysis import scoped_students, rows
    scope, params = scoped_students(v2, user)
    return rows(v2, f"""SELECT COALESCE(NULLIF(s.class_code,''),'班级待明确') class_name,
        COUNT(*) attempts,SUM(g.is_pass=0) fails,COUNT(DISTINCT g.student_id) students,
        COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) failed_students,
        ROUND(100.0*SUM(g.is_pass=0)/COUNT(*),1) fail_rate
        FROM grade_attempt g JOIN dim_student s ON s.student_id=g.student_id
        WHERE s.plan_id=? AND {scope} AND {VALID_FIRST} AND g.semester_id=? AND g.course_id=?
        GROUP BY COALESCE(NULLIF(s.class_code,''),'班级待明确')
        ORDER BY fails DESC,class_name""", (plan_id, *params, semester, course_id))


def analyze(v2, team, user, req, result):
    from .analysis import assert_plan, courses, document, table
    plan = assert_plan(v2, user, req['plan_id'])
    data = history(v2, user, req['plan_id'])
    order = req.get('_semester_order')
    if order is not None:
        data.sort(key=lambda r:(order.get(r['semester'], '9999'), r['semester'], r['course_id']))
    source = courses(v2, team, req['plan_id'])
    for row in data:
        row['name'] = (row['name'] or '').strip() or source.get(row['course_id'], {}).get('name') or row['course_id']
    semester = req.get('semester') or max((r['semester'] for r in data), default='')
    result.update(title=plan['major_name']+' · 课程质量建设', semester=semester)
    result['methods'].append('首次修读未通过率＝已发布、未作废、通过状态明确且非补考/重修的未通过记录数÷同条件全部记录数；沿用现有首次修读口径。变化使用百分点，不用百分比增幅。')
    result['limitations'] += ['按当前授权及方案归属回看历史，不代表各历史学期原在籍群体；行政班不是教学班。',
        '课程表现和班级差异不能直接解释为教学原因或教师评价；未记录建设措施和实施时间时，不做效果归因。']
    if not data:
        result.update(status='blocked', headline='当前范围没有符合首次修读口径的成绩记录，暂不能开展课程表现分析。')
        return
    grouped = defaultdict(list)
    for row in data: grouped[row['course_id']].append(row)
    result['course_options'] = [{'id':cid, 'name':rs[-1]['name'] or cid} for cid,rs in grouped.items()]
    current = sorted((dict(r) for r in data if r['semester']==semester), key=lambda r:(-r['fails'],-r['attempts'],r['course_id']))
    for row in current:
        course_rows = grouped[row['course_id']]
        if order is None:
            previous = [r for r in course_rows if r['semester']<semester]
        else:
            comparable = semester in order and all(r['semester'] in order for r in course_rows)
            previous = [r for r in course_rows if order[r['semester']]<order[semester]] if comparable else []
        prior = previous[-1] if previous else None
        row.update(previous_term=prior['semester'] if prior else None,
                   previous_rate=prior['fail_rate'] if prior else None,
                   change=percentage_point_change(row, prior))
    if req.get('course_id') and req['course_id'] not in grouped:
        raise ApiError('课程不存在或当前方案授权范围没有相应记录', code=404, status_code=404)
    cid = req.get('course_id') or (current[0]['course_id'] if current else '')
    if not cid:
        result.update(status='blocked', headline='所选学期没有符合口径的课程记录，请更换学期；这不代表没有课程问题。')
        return
    result['course'] = {'id':cid, 'name':grouped[cid][-1]['name'] or cid}
    selected = next((r for r in current if r['course_id']==cid), None)
    selected_name = result['course']['name']
    scene = req['scenario']
    if order is not None:
        unknown_terms = sorted({r['semester'] for r in data if r['semester'] not in order})
        result['methods'].append('前后顺序仅按校历有效开始日期确定，不按学期编号字符串推断；某课程含未对应校历的记录时，不计算该课程变化。')
        if unknown_terms:
            result['limitations'].append('部分历史学期尚未对应有效校历：'+ '、'.join(unknown_terms)+'。原标签保留，相关变化不计算。')
    cols = [('name','课程'),('course_id','代码'),('attempts','首次修读记录'),('fails','未通过记录'),
            ('students','涉及学生'),('fail_rate','未通过率（%）'),('previous_term','上一有记录学期'),('change','变化（百分点）')]
    if scene=='priority':
        result['headline'] = f'本学期有{len(current)}门课程可比较，其中{sum(r["fails"]>0 for r in current)}门有首次修读未通过记录；先结合影响人数和持续情况选择研究对象。'
        result['tables'] = [table('performance','课程表现与前期对照',cols,current,
            '按未通过记录数排列，不是课程建设优先级评分。上一有记录学期可能不连续；无可比记录时不填写变化值。')]
        return
    result['title'] = selected_name+' · '+{'diagnosis':'问题分析','alignment':'目标与考核对照','options':'建设做法比较','outcomes':'学期变化'}[scene]
    if selected:
        result['tables'].append(table('course_current','本学期课程情况',cols,[selected],
            '记录人次与去重学生分别展示；未通过率不是最终未通过学生率。'))
    else:
        result['missing'].append('所选课程在当前学期没有符合口径的记录，不能把缺失结果记作0。')
    if scene in {'diagnosis','options'}:
        history_count = sum((r['semester']<=semester if order is None else
                            r['semester'] in order and semester in order and order[r['semester']]<=order[semester])
                            for r in grouped[cid])
        classes = class_distribution(v2,user,req['plan_id'],semester,cid)
        result['tables'].append(table('class_distribution','同一课程的行政班表现',
            [('class_name','当前行政班'),('students','涉及学生'),('failed_students','未通过学生'),
             ('attempts','首次修读记录'),('fails','未通过记录'),('fail_rate','未通过率（%）')],classes,
            '以学生当前行政班分组，仅用于确定进一步了解的范围；不能解释为教学班、教师表现或因果差异。'))
        if scene=='diagnosis':
            result['headline'] = f'{selected_name}可从不同班级的涉及人数与未通过情况展开复盘；仅凭这些差异还不能确认原因。'
            result['tables'].append(table('diagnosis_questions','下一步具体了解什么',
                [('question','管理问题'),('available','本次能看到'),('needed','仍需了解')],[
                    {'question':'问题是否集中在部分群体','available':f'{len(classes)}个行政班有本学期符合口径的记录','needed':'学生基础、实际教学班与学习支持情况'},
                    {'question':'课程目标与考核是否一致','available':'可继续查看培养方案安排及考核形式','needed':'课程大纲、考核内容及评分要求'},
                    {'question':'是否持续出现相似情况','available':f'截至所选学期有{history_count}个有记录学期','needed':'核对各期群体、教学安排及制度变化'}],
                '这是具体的复盘问题，不是已经成立的原因判断。'))
        else:
            affected = str(selected['failed_students'])+'名本学期首次修读未通过学生' if selected else '当前学期人数待明确'
            result['headline'] = f'围绕{selected_name}，可比较学习支持、教学考核复盘和培养衔接检查三种做法；投入与成效尚未测算。'
            result['tables'].insert(0,table('course_options','三种建设做法如何取舍',
                [('option','做法'),('basis','本次依据'),('first','先做什么'),('needs','实施条件'),('observe','后续观察')],[
                    {'option':'开展有针对性的学习支持','basis':affected,'first':'确认学生实际学习困难，讨论答疑与补充学习内容','needs':'课程团队可用时间、学生参与意愿','observe':'支持覆盖情况与后续同口径课程表现'},
                    {'option':'复盘教学与考核安排','basis':f'{len(classes)}个行政班有可观察记录','first':'对照课程目标、授课内容、试卷与评分要求','needs':'大纲、试卷和实际教学安排','observe':'目标覆盖与后续可比学期表现'},
                    {'option':'检查培养内容与课程衔接','basis':'培养方案原文及课程安排可供对照','first':'讨论本课与前后课程的内容边界，不把学期先后当作先修关系','needs':'相关课程负责人确认内容及适用要求','observe':'课程之间的内容衔接与学习反馈'}],
                '三种做法不是必须同时实施；费用、工时、预计改善幅度均未计算，不代替学校管理决定。'))
    elif scene=='alignment':
        doc = document(team,v2,plan)
        result['documents'] = [doc]
        own = source.get(cid)
        result['tables'].insert(0,table('course_arrangement','培养方案对本课的安排',
            [('item','项目'),('value','已有内容'),('boundary','如何理解')],[
                {'item':'课程模块','value':' / '.join(own['modules']) if own else '未在方案课程表对应','boundary':'模块归属不是能力达成结论'},
                {'item':'学分','value':curriculum.credit_text([own]) if own else '待明确','boundary':'方案记录学分，不是认定学分'},
                {'item':'建议学期','value':' / '.join(own['terms']) if own else '待明确','boundary':'不能据此补造先修要求'},
                {'item':'学时','value':' / '.join(map(str,own['hours'])) if own and own['hours'] else '未提供','boundary':'学时总量不说明具体教学内容'},
                {'item':'考核形式','value':' / '.join(own['assessments']) if own and own['assessments'] else '未提供','boundary':'考试或考查不等于已取得试卷及评价标准'}]))
        named = [r for r in curriculum.named_courses(doc,source,{}) if r['id']==cid]
        result['tables'].append(table('course_original','原文主要课程中的对应',
            [('name','原文名称'),('id','对应代码'),('source','来源')],named,
            '只做完整名称的唯一对应；没有对应结果不表示该课没有培养价值。'))
        result['headline'] = f'{selected_name}的方案安排可以核对；课程目标、教学内容和考核题目尚未完整接入，不能判断三者是否一致。'
        result['missing'] += ['课程层面的目标与大纲','考核内容、评分要求及目标对应关系']
    elif scene=='outcomes':
        if order is not None and (semester not in order or any(r['semester'] not in order for r in grouped[cid])):
            result.update(status='blocked',headline='这门课程的历史学期尚未全部对应有效校历，暂不能判断前后变化。')
            result['missing'].append('相关学期的有效校历对应；当前保留所选学期记录，不绘制改善趋势。')
            return
        trend = [dict(r) for r in grouped[cid] if
                 (r['semester']<=semester if order is None else order[r['semester']]<=order[semester])]
        for index,row in enumerate(trend):
            row['change'] = percentage_point_change(row, trend[index-1]) if index else None
        result['tables'].insert(0,table('trend','截至所选学期的课程记录',
            [('semester','学期'),('attempts','首次修读记录'),('students','涉及学生'),('fails','未通过记录'),
             ('fail_rate','未通过率（%）'),('change','较上一有记录学期（百分点）')],trend,
            '不补齐没有记录的学期，不把缺失记为0；学生仍按当前方案归属回看，人数和群体变化须一同阅读。'))
        result['headline'] = (f'{selected_name}有{len(trend)}个学期的记录可观察；成绩变化不能直接归因于建设措施。'
                              if len(trend)>1 else '目前不足两个有记录学期，尚不能比较课程表现变化。')
        result['missing'] += ['建设措施、实施时间与可比条件；未接入前只做表现观察']
