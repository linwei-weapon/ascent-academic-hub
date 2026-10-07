"""Fixed business tasks and processors, separate from the read-only tool registry.

Dependencies are server-frozen resource versions, never client-supplied packages.
Registering a processor does not publish a Skill or grant a data permission.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
from time import monotonic

from jsonschema import Draft202012Validator
from backend.api.envelope import ApiError
from . import runtime
from .auth import require_use

LOADED_FINGERPRINT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_POLICY_HASHES = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                  for name in ('policy_tasks.py', 'matching.py', 'rules.py', 'policy_adapter.py')}

_ID = {'type': 'string', 'minLength': 1, 'maxLength': 128}
_PREVIEW = {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50}
_STRINGS = {'type': 'array', 'items': deepcopy(_ID), 'uniqueItems': True}
_RULE_REF = {'type': 'object', 'properties': {'ruleId': _ID, 'version': _ID},
             'required': ['ruleId', 'version'], 'additionalProperties': False}
_RESULT_REF = {'type': 'object', 'properties': {'resultId': _ID, 'objectRefs': _STRINGS,
               'conditionIds': _STRINGS, 'evidenceIds': _STRINGS}, 'required': ['resultId'], 'additionalProperties': False}
_DOCUMENT_REF = {'type': 'object', 'properties': {'documentId': _ID, 'version': _ID},
                 'required': ['documentId', 'version'], 'additionalProperties': False}
_FIELD_LABELS = {
    'plan_id': ('基线培养方案', '从当前授权选项选择本轮基线培养方案。'),
    'target_plan_id': ('对照培养方案', '选择与基线不同的授权对照方案；转入任务表示目标方案。'),
    'semester_id': ('分析学期', '选择本轮实际观察的学期，不继承隐藏的旧学期筛选。'),
    'college_id': ('学院范围', '只允许当前身份授权的学院，按本任务的实际组织口径筛选。'),
    'course_id': ('指定课程编号（可选）', '只查看指定课程的聚合表现；留空时使用当前完整筛选范围。'),
    'previewLimit': ('预览记录数', '只改变表格展示条数，完整证据和统计分母保持一致。'),
    'comparisonMode': ('比较口径', '当前按全部模块的已识别课程编号比较；未确认分类不能排除公共课。'),
    'ruleRef': ('已发布规则版本', '引用唯一适用且已确认发布的规则，不由客户端提供规则事实。'),
    'populationRef': ('授权对象群体', '引用服务端可验证的对象集合；不能上传成绩或通过状态充当事实。'),
    'year': ('适用年度', '明确本轮规则年度；不根据当前日期或年级猜测。'),
    'conditionIds': ('核验条件', '选择固定规则中的条件子范围；其他条件保持未核或未知。'),
    'documentRef': ('固定文档版本', '引用已确认文档的固定版本与来源定位。'),
    'documentRefs': ('固定文档版本', '引用所需已确认文档的固定版本。'),
    'resultRef': ('已保存分析结果', '引用已保存且可鉴权的实际分析结果。'),
    'baselineRef': ('已保存基线结果', '引用可鉴权、范围和口径可核对的基线结果。'),
    'currentRef': ('已保存对照结果', '引用另一份实际保存结果，不补造未保存的历史。'),
    'recognitionRef': ('已保存认定结果', '引用适用对象的已核认定与未知结果。'),
    'rankingRef': ('已保存排名结果', '引用同年度、完整群体且合法的精确排名结果。'),
    'remainingTerms': ('剩余培养学期数', '使用对象实际剩余培养时间，不保证未来开课或容量。'),
    'offeringSemesterIds': ('实际开课学期范围', '指定已接入真实开课记录的学期。'),
    'changes': ('明示调整参数', '只提供拟讨论的变更；不覆盖正式规则或来源事实。'),
    'thresholds': ('明示条件阈值', '只允许正式规则明确可讨论的条件参数。'),
    'problem': ('需了解的问题', '明确课程问题背景，与来源事实和教学成因分别表达。'),
}


def _schema(fields, required=()):
    props = {key: deepcopy(value) for key, value in fields.items()}
    for key, value in props.items():
        label, description = _FIELD_LABELS.get(key, ('对象引用', '使用服务端已验证的对象或版本引用。'))
        value.update(title=label, description=description)
        if key == 'comparisonMode':
            value['default'] = 'all_course_ids'
        if key == 'college_id' and 'semester_id' in fields and 'course_id' in fields:
            value.update(title='开课院系筛选', description='课程表现按授权开课院系筛选，不等同学生归属学院。')
    return {'type': 'object', 'properties': props, 'required': list(required), 'additionalProperties': False}


_DEFINITIONS = [
    {'taskId': 'P-COMPARE', 'expertId': 'program', 'skillId': 'program-comparison',
     'title': '两方案共同与独有课程比较', 'processorId': 'program-comparison-v2', 'handler': 'compare_programs',
     'inputSchema': _schema({'plan_id': _ID, 'target_plan_id': _ID,
         'comparisonMode': {'type': 'string', 'enum': ['all_course_ids']}, 'previewLimit': _PREVIEW},
         ['plan_id', 'target_plan_id', 'comparisonMode'])},
    {'taskId': 'C-PERFORMANCE', 'expertId': 'course', 'skillId': 'course-performance',
     'title': '课程首修表现与问题分布', 'processorId': 'course-performance-v2', 'handler': 'read_course_performance',
     'observationMethod': {'presetId': 'C-BRIEF-01', 'metricModuleId': 'ai-briefing',
        'cohort': 'is_retake=0 AND is_published=1 AND is_void=0 AND is_pass IN(0,1)',
        'referencePopulation': '当前范围全部有效唯一课程聚合行', 'previewLimit': 5,
        'selection': 'U=N-P>0 AND P*scopeN<scopeP*N',
        'ordering': ['U descending', 'exact P/N ascending', 'course_id ascending']},
     'inputSchema': _schema({'semester_id': _ID, 'college_id': _ID, 'course_id': _ID,
                             'previewLimit': _PREVIEW}, ['semester_id'])},
    {'taskId': 'P-STRUCTURE', 'expertId': 'program', 'skillId': 'program-structure',
     'title': '方案课程结构浏览', 'handler': 'read_program_structure',
     'inputSchema': _schema({'plan_id': _ID, 'previewLimit': _PREVIEW}, ['plan_id'])},
    {'taskId': 'T-REQUIREMENTS', 'expertId': 'transfer', 'skillId': 'transfer-plan-gap',
     'title': '来源与目标方案课程编号衔接', 'handler': 'compare_programs',
     'inputSchema': _schema({'plan_id': _ID, 'target_plan_id': _ID, 'previewLimit': _PREVIEW}, ['plan_id', 'target_plan_id'])},
    {'taskId': 'T-HISTORY', 'expertId': 'transfer', 'skillId': 'transfer-history',
     'title': '历史异动路径浏览', 'handler': 'read_transfer_history',
     'inputSchema': _schema({'college_id': _ID, 'semester_id': _ID, 'previewLimit': _PREVIEW})},
    {'taskId': 'G-PROGRESS', 'expertId': 'graduation', 'skillId': 'graduation-progress',
     'title': '已有毕业准备进度', 'handler': 'read_graduation_progress',
     'inputSchema': _schema({'plan_id': _ID}, ['plan_id'])},
    {'taskId': 'G-AUDIT', 'expertId': 'graduation', 'skillId': 'graduation-audit',
     'title': '已有审核原状态', 'handler': 'read_graduation_audit',
     'inputSchema': _schema({'college_id': _ID, 'semester_id': _ID, 'previewLimit': _PREVIEW})},
    {'taskId': 'R-PREPARE', 'expertId': 'recommendation', 'skillId': 'recommendation-policy',
     'title': '当年推免规则准备', 'handler': 'unavailable', 'processorId': 'recommendation-policy-v2',
     'inputSchema': _schema({'year': _ID, 'college_id': _ID, 'ruleRef': _RULE_REF}, ['year']),
     'requiredDependencies': ['当年已发布适用学校规则与学院细则', '可信材料来源及有效期读取适配器'],
     'reason': '尚缺已确认的当年适用规则与可信材料读取适配器'},
    {'taskId': 'T-SCHEDULE', 'expertId': 'transfer', 'skillId': 'capacity-evidence',
     'title': '实际开课与承接条件', 'handler': 'unavailable', 'processorId': 'capacity-evidence-v2',
     'inputSchema': _schema({'recognitionRef': _RESULT_REF, 'remainingTerms': {'type': 'integer', 'minimum': 1},
                             'offeringSemesterIds': _STRINGS}, ['recognitionRef', 'remainingTerms']),
     'requiredDependencies': ['合法认定上游结果与正式先修规则', '实际开课、剩余时间和容量的可信读取适配器'],
     'reason': '尚缺实际开课、正式先修和容量依据'},
]
_PLANNED = [
    ('P-SUPPORT', 'program', 'program-support', '培养目标原文与显式课程支撑', 'program-support-v2', 'facts',
     {'plan_id': _ID, 'target_plan_id': _ID, 'documentRefs': {'type': 'array', 'items': _DOCUMENT_REF}},
     ['plan_id', 'documentRefs'], ['固定版本的已确认培养目标原文及定位', '已确认目标—课程关联与可信文档读取适配器']),
    ('C-SUPPORT', 'course', 'course-support', '课程目标教学考核对应与建议', 'course-support-v2', 'facts',
     {'course_id': _ID, 'documentRefs': {'type': 'array', 'items': _DOCUMENT_REF}, 'resultRef': _RESULT_REF, 'problem': _ID},
     ['course_id', 'documentRefs'], ['课程大纲、目标、教学任务与考核的已确认原文', '显式对应及可信文档读取适配器']),
    ('C-CHANGE', 'course', 'saved-result-comparison', '实际保存课程表现变化', 'saved-result-comparison-v2', 'facts',
     {'baselineRef': _RESULT_REF, 'currentRef': _RESULT_REF}, ['baselineRef', 'currentRef'],
     ['两个可鉴权的实际保存课程结果', '规则、范围、粒度和时间可比性检查适配器']),
    ('T-RECOGNITION', 'transfer', 'transfer-recognition', '实际已修认定与确定补修', 'transfer-recognition-v2', 'rule_check',
     {'populationRef': _ID, 'target_plan_id': _ID, 'ruleRef': _RULE_REF}, ['populationRef', 'target_plan_id', 'ruleRef'],
     ['唯一适用的已确认已发布认定规则与正式目标要求', '授权有效成果、学分与来源覆盖的真实库适配器']),
    ('T-POLICY', 'transfer', 'transfer-policy-impact', '真实群体的转入规则影响', 'transfer-policy-impact-v2', 'rule_check',
     {'populationRef': _ID, 'year': _ID, 'ruleRef': _RULE_REF}, ['populationRef', 'year', 'ruleRef'],
     ['已确认年度政策与真实申请或明确已选群体来源', '共享认定组件的真实群体读取适配器']),
    ('T-POLICY-SCENARIO', 'transfer', 'transfer-policy-impact', '显式假设的转入规则影响', 'transfer-policy-impact-v2', 'scenario',
     {'baselineRef': _RESULT_REF, 'ruleRef': _RULE_REF, 'changes': {'type': 'array', 'items': {
         'type': 'object', 'properties': {'conditionId': _ID, 'proposedValue': {'type': ['number', 'string']}},
         'required': ['conditionId', 'proposedValue'], 'additionalProperties': False}}}, ['baselineRef', 'ruleRef', 'changes'],
     ['已保存且可复用的正式基线与获准讨论的参数', '假设参数适用检查及真实成果读取适配器']),
    ('R-RANK', 'recommendation', 'recommendation-ranking', '精确成绩与已确认并列排序', 'recommendation-ranking-v2', 'rule_check',
     {'populationRef': _ID, 'year': _ID, 'ruleRef': _RULE_REF}, ['populationRef', 'year', 'ruleRef'],
     ['当年适用课程、权重、并列和有效成绩规则', '完整授权排名群体及精确成绩的真实库适配器']),
    ('R-CHECK', 'recommendation', 'recommendation-condition-check', '成绩及非成绩条件核验', 'recommendation-condition-check-v2', 'rule_check',
     {'rankingRef': _RESULT_REF, 'year': _ID, 'ruleRef': _RULE_REF}, ['rankingRef', 'year', 'ruleRef'],
     ['合法完整排名结果与当年适用条件规则', '纪律等非成绩条件和来源覆盖的可信适配器']),
    ('R-SCENARIO', 'recommendation', 'recommendation-condition-check', '获准条件参数的假设影响', 'recommendation-condition-check-v2', 'scenario',
     {'baselineRef': _RESULT_REF, 'ruleRef': _RULE_REF, 'thresholds': {'type': 'object', 'additionalProperties': {'type': ['number', 'string']}}},
     ['baselineRef', 'ruleRef', 'thresholds'], ['合法正式基线与已确认可调整条件清单', '规则与非成绩条件的可信适配器']),
    ('G-CHECK', 'graduation', 'graduation-condition-check', '毕业与学位的限定条件核验', 'graduation-condition-check-v2', 'rule_check',
     {'populationRef': _ID, 'plan_id': _ID, 'ruleRef': _RULE_REF, 'conditionIds': _STRINGS}, ['populationRef', 'plan_id', 'ruleRef'],
     ['唯一适用已发布毕业或学位条件规则、正式要求', '有效成果、学分来源与业务覆盖的真实库适配器']),
    ('G-CHANGE', 'graduation', 'saved-result-comparison', '实际保存条件与进度变化', 'saved-result-comparison-v2', 'facts',
     {'baselineRef': _RESULT_REF, 'currentRef': _RESULT_REF}, ['baselineRef', 'currentRef'],
     ['两个实际保存的同对象条件结果', '条件、规则及未知状态可比性检查适配器']),
    ('P-PATH', 'program', 'program-path-and-change', '方案学期路径与明确先修检查', 'program-path-and-change-v2', 'rule_check',
     {'plan_id': _ID, 'ruleRef': _RULE_REF}, ['plan_id', 'ruleRef'],
     ['已确认的正式先修条款及适用关系', '课程路径和正式约束的可信读取适配器']),
    ('P-CHANGE', 'program', 'program-path-and-change', '指定课程结构变更的条件影响', 'program-path-and-change-v2', 'scenario',
     {'plan_id': _ID, 'ruleRef': _RULE_REF, 'changes': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'action': {'enum': ['add', 'remove', 'update']}, 'courseId': _ID,
        'values': {'type': 'object', 'properties': {'semester': {'type': ['number', 'string']},
        'credits': {'type': ['number', 'string']}, 'category': _ID}, 'additionalProperties': False}},
        'required': ['action', 'courseId'], 'additionalProperties': False}}}, ['plan_id', 'ruleRef', 'changes'],
     ['正式基线、可确定的方案学分及变更约束', '来源和约束确认适配器；无依据不计算成本或师资收益']),
    ('P-DOCUMENT', 'program', 'program-document-reader', '固定版本培养方案原文读取', 'program-document-reader-v2', 'facts',
     {'plan_id': _ID, 'documentRef': _DOCUMENT_REF}, ['plan_id', 'documentRef'],
     ['学校真实培养方案文档、版本哈希、页段定位与授权', '已确认文档仓库及可信读取适配器']),
]
for _task_id, _expert, _skill, _title, _processor, _kind, _fields, _required, _dependencies in _PLANNED:
    _DEFINITIONS.append({'taskId': _task_id, 'expertId': _expert, 'skillId': _skill, 'title': _title,
        'processorId': _processor, 'handler': 'unavailable', 'resultKind': _kind,
        'inputSchema': _schema(_fields, _required), 'requiredDependencies': _dependencies,
        'reason': '；'.join(_dependencies)})
_g_check = next(item for item in _DEFINITIONS if item['taskId'] == 'G-CHECK')
_g_check.update(handler='read_learning_results', available=True, realAdapterAvailable=True, formalAvailable=False,
    inputSchema=_schema({'populationRef': _ID, 'plan_id': _ID, 'ruleRef': _RULE_REF, 'year': _ID,
                         'college_id': _ID, 'conditionIds': _STRINGS}, ['populationRef', 'plan_id', 'ruleRef', 'year']),
    requiredDependencies=['唯一已确认已发布适用规则及learningBasis对成果/学分来源的确认',
                          '实际成绩与认定来源覆盖依据；缺记录保持未知'],
    reason='')
for _item in _DEFINITIONS:
    _item.setdefault('processorId', 'legacy:' + _item['handler'])
    _item.setdefault('resultKind', 'facts')
    _item.setdefault('available', _item['handler'] in runtime.HANDLERS)
    _item.setdefault('reason', '' if _item['available'] else '处理器尚未实现')
    _item.setdefault('realAdapterAvailable', _item['available'])
    _item['technicalAvailable'] = _item['realAdapterAvailable']
    _item.setdefault('formalAvailable', _item['available'])
    if not _item['available']:
        _item['plannedProcessorId'] = _item['processorId']

PROCESSORS = frozenset(item['processorId'] for item in _DEFINITIONS if item['realAdapterAvailable'])
PLANNED_PROCESSORS = frozenset(item['processorId'] for item in _DEFINITIONS if not item['available'])


def task_definitions():
    """Implementation availability; live publication is checked by resolve_task."""
    fields = ('taskId', 'expertId', 'skillId', 'title', 'inputSchema', 'resultKind', 'available', 'reason',
              'processorId', 'plannedProcessorId', 'realAdapterAvailable', 'technicalAvailable', 'formalAvailable',
              'requiredDependencies')
    from .policy_tasks import TASKS as implemented_algorithms
    values = [{key: deepcopy(item[key]) for key in fields if key in item} for item in _DEFINITIONS]
    for value in values:
        value['algorithmImplemented'] = value['available'] or value['taskId'] in implemented_algorithms
        if not value['algorithmImplemented']:
            value['reason'] += '；对应确定性业务算法尚未实现'
    return values


def definition(task_id):
    item = next((item for item in _DEFINITIONS if item['taskId'] == task_id), None)
    if item is None:
        raise ApiError('未登记的业务任务', status_code=422)
    return deepcopy(item)


def _validate(schema, value, message, code=422):
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        field = '.'.join(str(p) for p in errors[0].absolute_path)
        raise ApiError(message + ('：' + field if field else '，请核对必填项和不支持的条件'), status_code=code)


def _dependency(dependencies, kind, resource_id):
    found = [item for item in dependencies.get(kind, []) if item.get('id') == resource_id]
    if len(found) != 1 or not found[0].get('version') or not isinstance(found[0].get('content'), dict):
        raise ApiError('任务缺少唯一固定的已发布依赖：' + resource_id, status_code=409)
    item = found[0]
    if item.get('enabled') is False:
        raise ApiError('任务依赖已停用：' + resource_id, status_code=409)
    if not dependencies.get('_candidate'):
        pinned = [row for row in dependencies.get('snapshot', [])
                  if row.get('kind') == kind and row.get('id') == resource_id and row.get('version') == item['version']]
        if len(pinned) != 1 or pinned[0].get('enabled') is not True:
            raise ApiError('任务依赖尚未冻结为可用发布版本：' + resource_id, status_code=409)
    return item


def _skill_for_task(item, dependencies):
    if not item['available']:
        raise ApiError(item['reason'], status_code=409)
    selected = _dependency(dependencies, 'skills', item['skillId'])
    content = selected['content']
    execution = content.get('execution') or {}
    processor = execution.get('processorId')
    handler = execution.get('handler')
    if processor:
        if processor != item['processorId'] or processor not in PROCESSORS or handler:
            raise ApiError('Skill处理器未登记或存在两条执行路径', status_code=409)
    elif handler != item['handler']:
        raise ApiError('Skill与任务的已登记处理器不一致', status_code=409)
    if content.get('missingEvidence'):
        raise ApiError('该方法尚缺业务依据：' + '；'.join(content['missingEvidence']), status_code=409)
    bindings = [binding for binding in content.get('toolBindings', []) if binding.get('toolName') == item['handler']]
    if not bindings:
        raise ApiError('Skill未声明任务所需只读工具', status_code=409)
    # Every declared tool must exist in its fixed internal service, not only the selected tool.
    for binding in content.get('toolBindings', []):
        server = _dependency(dependencies, 'mcps', binding.get('serverId'))
        tools = server['content'].get('tools', [])
        if binding.get('toolName') not in runtime.HANDLERS or not any(
                isinstance(tool, dict) and tool.get('name') == binding['toolName'] for tool in tools):
            raise ApiError('Skill工具与固定服务的登记不一致', status_code=409)
    return selected


def resolve_task(task_id, expert_content, dependencies):
    item = definition(task_id)
    if item['skillId'] not in (expert_content.get('skillIds') or []):
        raise ApiError('该任务未绑定到当前专家已发布的方法', status_code=409)
    selected = _skill_for_task(item, dependencies)
    return {**item, 'skillVersion': selected['version']}


def _task_inputs(item, inputs):
    inputs = deepcopy(inputs or {})
    if not isinstance(inputs, dict):
        raise ApiError('本轮任务输入必须为对象', status_code=422)
    if 'taskId' in inputs:
        if inputs.pop('taskId') != item['taskId']:
            raise ApiError('本轮输入任务与冻结任务不一致', status_code=422)
    if 'limit' in inputs:
        if 'previewLimit' in inputs:
            raise ApiError('limit与previewLimit不能同时提供', status_code=422)
        inputs['previewLimit'] = inputs.pop('limit')
    for key, field in item['inputSchema']['properties'].items():
        if 'default' in field and key not in inputs:
            inputs[key] = deepcopy(field['default'])
    _validate(item['inputSchema'], inputs, '输入不符合业务任务契约')
    return inputs


def _skill_inputs(content, inputs):
    processor = (content.get('execution') or {}).get('processorId')
    if processor and not processor.startswith('legacy:'):
        return inputs
    adapted = deepcopy(inputs)
    adapted.pop('comparisonMode', None)
    if 'previewLimit' in adapted:
        adapted['limit'] = adapted.pop('previewLimit')
    return adapted


def _adapt_result(item, result):
    result = deepcopy(result)
    result.update({'schemaVersion': '2.0', 'taskId': item['taskId'], 'resultKind': item['resultKind']})
    result.setdefault('facts', [])
    result.setdefault('conditions', [])
    result.setdefault('issues', [])
    if 'evidence' not in result:
        # Other legacy tools retained only their returned tables; do not invent full input evidence.
        result['evidence'] = []
        for index, displayed in enumerate(result.get('tables', [])):
            retained = displayed.get('rows', [])
            src = (result.get('sources') or [{'name': '旧方法保存内容', 'queriedAt': None, 'dataUpdatedAt': None}])[0]
            evidence = runtime._evidence(f'legacy-table-{index+1}', src, retained,
                                         '旧方法返回表格，源查询总量未知', None, recomputable=False)
            evidence.update({'retentionComplete': False, 'sourceRowCount': None})
            result['evidence'].append(evidence)
            displayed.update({'evidenceId': evidence['evidenceId'], 'totalRows': None,
                              'returnedRows': len(retained), 'truncated': None})
    result.setdefault('coverage', {'definedPopulation': None, 'observedPopulation': None,
        'evaluablePopulation': None, 'unknownCount': None, 'exclusions': [], 'grain': '旧方法原口径',
        'inputCompleteness': [{'dimension': 'retainedInput', 'state': 'unknown',
                              'basis': '旧方法未登记全量证据策略，不能由展示行数推断完整性'}]})
    complete = bool(result['evidence']) and all(e.get('retentionComplete') for e in result['evidence'])
    result['comparisonCapability'] = {'viewSavedResult': True, 'compareSavedResults': False,
        'compareSavedResultsReason': '尚未实现保存结果可比性校验', 'replayFromRetainedInput': complete,
        'replayFromRetainedInputReason': '仅可复核本次确定性事实；不能重建源库历史批次' if complete else '输入证据未完整留存'}
    if item['taskId'] == 'C-PERFORMANCE' and result.get('validationBasis'):
        result['comparisonCapability']['independentCurrentInputCheck'] = (
            result['validationBasis'].get('independentRecompute') or {}).get('state', 'not_run')
        result['comparisonCapability']['threeLayerCheck'] = (
            result['validationBasis'].get('threeLayerCheck') or {}).get('state', 'pending')
        result['comparisonCapability']['observationMode'] = result.get('publishMode', 'facts_only')
    return result


def _execute(item, inputs, actor, content):
    require_use(actor)
    _validate(content.get('inputSchema') or {}, _skill_inputs(content, inputs), '输入不符合已发布Skill契约')
    start = monotonic()
    result = runtime.run_tool(item['handler'], inputs, actor, schema_version='2.0')
    processor = (content.get('execution') or {}).get('processorId')
    if processor and not processor.startswith('legacy:'):
        projected = _adapt_result(item, result)
    else:
        projected = runtime._legacy_projection(result)
    _validate(content.get('outputSchema') or {}, projected, '实际输出不符合Skill契约', 409)
    result = _adapt_result(item, result)
    status = 'blocked' if result['status'] == 'blocked' else 'passed'
    return {'status': status, 'summary': result['summary'], 'result': result,
        'trace': [{'step': '复核固定任务与Skill工具依赖', 'status': 'passed', 'taskId': item['taskId'], 'processorId': item['processorId']},
                  {'step': '调用唯一只读计算工具', 'tool': item['handler'], 'status': status,
                   'elapsedMs': round((monotonic()-start)*1000)}, {'step': '校验输出契约', 'status': 'passed'}],
        'missingEvidence': result.get('missingEvidence', [])}


def run_task(task_id, inputs, actor, dependencies):
    require_use(actor)
    item = definition(task_id)
    inputs = _task_inputs(item, inputs)
    selected = _skill_for_task(item, dependencies)
    if dependencies.get('expertContent') is not None:
        resolve_task(task_id, dependencies['expertContent'], dependencies)
    if item['taskId'] == 'G-CHECK':
        return execute_processor(item['processorId'], selected['content'], inputs, actor, dependencies)
    return _execute(item, inputs, actor, selected['content'])


def execute_processor(processor_id, content, inputs, actor, dependencies):
    """Controlled candidate/legacy resource testing; no dynamic Python imports."""
    if processor_id not in PROCESSORS:
        raise ApiError('未登记的Skill处理器', status_code=422)
    item = next(item for item in _DEFINITIONS if item['processorId'] == processor_id)
    # Test content can be a fixed candidate; tool dependencies must still be real fixed versions.
    for binding in content.get('toolBindings', []):
        server = _dependency(dependencies, 'mcps', binding.get('serverId'))
        if binding.get('toolName') not in runtime.HANDLERS or not any(
                tool.get('name') == binding.get('toolName') for tool in server['content'].get('tools', [])):
            raise ApiError('候选处理器依赖的工具尚未登记', status_code=409)
    if not any(binding.get('toolName') == item['handler'] for binding in content.get('toolBindings', [])):
        raise ApiError('候选处理器未声明所需工具', status_code=409)
    if (content.get('execution') or {}).get('handler'):
        raise ApiError('处理器与handler不能同时形成执行路径', status_code=409)
    validated = _task_inputs(item, inputs)
    if item['taskId'] == 'G-CHECK':
        from .policy_adapter import execute
        _validate(content.get('inputSchema') or {}, validated, '输入不符合核验Skill契约')
        fresh = actor['_authorize']() if actor.get('_authorize') is not None else actor
        require_use(fresh)
        outcome = execute('G-CHECK', validated, fresh, dependencies)
        if outcome.get('status') == 'blocked' or not isinstance(outcome.get('result'), dict):
            return outcome
        calculated = outcome['result']
        learning = calculated.get('learningEvidence') or {}
        objects = learning.get('objects', [])
        src = {'name': 'act_student_course_result + act_grade_attempt', 'queriedAt': runtime.now(), 'dataUpdatedAt': None}
        evidence = runtime._evidence('learning-results', src, objects, '授权学籍对象及实际有效结果与尝试关联',
                                      learning.get('scope'), recomputable=True)
        conditions = [dict(condition, objectRef=obj['objectRef'], ruleRef=validated['ruleRef'])
                      for obj in calculated.get('objects', []) for condition in obj.get('conditions', [])]
        counts = calculated.get('objectCounts') or {}
        state_names = {'satisfied': '已满足所核条件', 'unsatisfied': '未满足所核条件',
                       'unknown': '条件未知', 'not_applicable': '不适用'}
        facts = [runtime._fact('objects-' + state, state_names.get(state, '核验对象状态'), value, '人', refs=['learning-results'])
                 for state, value in counts.items()]
        result = {'status': 'limited', 'summary': outcome.get('summary', '限定条件核验'), 'scope': learning.get('scope', {}),
            'data': {'对象数': len(objects), '完整毕业或学位资格': None}, 'tables': [],
            'sources': learning.get('sources', []), 'limitations': outcome.get('limitations', []) +
                ['限定条件核验不代表完整毕业或学位资格；来源覆盖不明的缺项保持未知。'],
            'missingEvidence': outcome.get('missingEvidence', []), 'facts': facts, 'conditions': conditions,
            'issues': [], 'evidence': [evidence],
            'coverage': {'definedPopulation': len(objects), 'observedPopulation': len(objects),
                'evaluablePopulation': None, 'unknownCount': counts.get('unknown'), 'exclusions': [],
                'grain': '对象×规则条件，毕业与学位类别分别保留',
                'inputCompleteness': [{'dimension': 'learningSourceCoverage', 'state': 'unknown',
                    'basis': '可信适配器已保留全部返回成果；尚无源教务记录接入完整性证明'}]}}
        result = _adapt_result(item, result)
        _validate(content.get('outputSchema') or {}, result, '实际核验输出不符合Skill契约', 409)
        return {'status': 'passed', 'summary': result['summary'], 'result': result,
                'trace': outcome.get('trace', []), 'missingEvidence': result['missingEvidence']}
    return _execute(item, validated, actor, content)


def legacy_result(outcome, turn_id=None):
    """Read-only saved-result adapter: never queries or fabricates missing rows."""
    result = deepcopy(outcome)
    if isinstance(result.get('result'), dict):
        result['result'].setdefault('schemaVersion', 'legacy')
        result['result']['legacy'] = True
        result['result'].setdefault('coverage', {'inputCompleteness': [{'dimension': 'retainedInput',
            'state': 'unknown', 'basis': '原保存结果没有完整证据与来源覆盖声明'}]})
        result['result']['comparisonCapability'] = {'viewSavedResult': True, 'compareSavedResults': False,
            'replayFromRetainedInput': False, 'reason': '原结果只保留已有内容，不补造证据或历史覆盖'}
    if turn_id is not None:
        result['legacyResultId'] = 'legacy:' + str(turn_id)
    return result
