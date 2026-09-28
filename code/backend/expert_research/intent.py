"""Bounded scope requests, not an open-domain natural-language interpreter."""
import re

LABELS = {'all': '全部课程代码', 'non_common': '已明确的非公共课程',
          'foundation': '已明确的专业基础', 'main': '已明确的专业主干',
          'foundation_main': '已明确的专业基础与专业主干',
          'practice': '已明确的专业实践', 'required': '逐门必修'}


def scope_request(text):
    """Return (change, clarification, positive text). Fail closed on ambiguity."""
    text = re.sub(r'(?<!专业)基础课', '专业基础课', text)
    text = re.sub(r'(?<!专业)主干课', '专业主干课', text)
    clauses = re.split(r'[。；;！？!?\n]', text)
    # A negated topic must not become a positive keyword route.
    positive = '。'.join(c for c in clauses if not re.match(
        r'\s*(?:请)?(?:先|暂时|暂)?(?:不|不要|不用)(?:再)?(?:判断|研究|分析|讨论|评价)', c))
    wants = bool(re.search(r'只(?:看|列|比较|分析|保留)|仅(?:看|列|比较|分析|保留)|排除|剔除|去除|去掉|不含|不包括|不计入|单列|全部课程', positive))
    if not wants:
        return {}, '', positive
    if re.search(r'^(?:请)?(?:排除|剔除|去除|不含|不包括|不计入)(?:[，,\s]|$)', positive):
        return {}, '尚未明确要排除哪些课程，本轮未改变分析范围。请说明课程类别。', positive
    if re.search(r'(?:不要|不用|不必|不再)(?:排除|剔除|去除)|不能不|不要不', positive):
        return {}, '这里存在否定范围的表达，本轮未改变分析范围。请直接选择“全部课程”或明确要保留的课程类别。', positive
    excludes_public = bool(re.search(r'(?:排除|剔除|去除|去掉|不含|不包括|不计入)(?:双方|所有|全部|的|\s)*公共(?:课|课程)|公共(?:课程|课)(?:全部|先|都)?(?:排除|剔除|去掉|不计入)', positive))
    layers = [key for key, word in [('foundation','专业基础'),('main','专业主干'),('practice','专业实践')] if word in positive]
    focused = bool(layers and re.search(r'只|仅|比较|查看|列出|看看', positive))
    all_courses = bool(re.search(r'(?:全部|所有)课程', positive))
    if all_courses and (excludes_public or focused):
        return {}, '同时提出了全部课程和限定课程范围，本轮未改变分析范围。请明确本轮要采用哪一项。', positive
    if re.search(r'(?:排除|剔除|去除|去掉|不含|不包括)(?!公共|双方公共|全部公共|所有公共)', positive) and not excludes_public:
        return {}, '当前不能可靠执行这项排除条件，本轮未改变分析范围。可以选择公共课程以外、专业基础、专业主干或专业实践；具体课程排除尚未接入。', positive
    if re.search(r'高学分|低学分|两学分|三学分|[0-9]+学分|学分.*(?:以上|以下|大于|小于)|大一|大二|大三|大四|前[一二三四五十0-9]+|英语|数学|[<>≥≤]', positive):
        return {}, '这项附加筛选条件尚未接入，本轮未按旧范围重新计算。请先选择已支持的课程类别，不能把当前结果视为已执行该条件。', positive
    if focused:
        if len(layers) > 1 and set(layers) != {'foundation','main'}:
            return {}, '当前支持基础与主干合并查看，其他层级组合请分别选择；本轮未改变范围。', positive
        focus = 'foundation_main' if len(layers) == 2 else layers[0]
    elif excludes_public: focus = 'non_common'
    elif all_courses or positive.strip() == '查看全部课程': focus = 'all'
    elif '逐门必修' in positive: focus = 'required'
    elif re.search(r'分类.*(?:不清|不明|待明确).*单列', positive):
        return {}, '请同时明确要研究的课程范围；分类不明的记录会另列，不会自动归入专业课程。', positive
    else:
        return {}, '当前不能可靠执行这项范围限定，本轮未改变分析范围。请使用课程范围选择项，或分别说明要保留的课程类别。', positive
    return {'focus': focus}, '', positive
