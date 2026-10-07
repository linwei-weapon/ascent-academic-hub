"""Build resource drafts using the backend virtual environment and task schemas.

This is a content build, not publication or business-data execution. After changing
resource definitions, regenerate and validate before importing them as drafts.
"""
from copy import deepcopy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SPEC = "文档/4-需求文档/4.7-AI管理决策/expert-design-v3-20260916/02-专家职责与场景发布清单.md"
VERSION = "2.0.0"
sys.path.insert(0, str(REPO / 'code'))
from backend.expert_resources.tasks import task_definitions

TASK_DEFINITIONS = task_definitions()

PARAMETERS = {
    "plan_id": {"type": "string", "minLength": 1, "maxLength": 128, "description": "从当前身份可用选项选择的培养方案ID；不是专业名称。"},
    "target_plan_id": {"type": "string", "minLength": 1, "maxLength": 128, "description": "明确选定的另一份培养方案ID；转专业场景中为目标方案。"},
    "semester_id": {"type": "string", "minLength": 1, "maxLength": 64, "description": "从当前数据选项选择的学期ID；未指定时由返回结果明确实际范围。"},
    "college_id": {"type": "string", "minLength": 1, "maxLength": 128, "description": "当前身份授权范围内的学院ID；不传不代表获得全校权限。"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50, "description": "最多展示的课程或汇总记录条数；不改变分母，截断必须披露。"},
}


def inputs(names, required=()):
    properties = {key: deepcopy(PARAMETERS[key]) for key in names}
    if 'semester_id' in required:
        properties['semester_id']['description'] = '从当前数据选项选择学期ID；本工具必须指定学期，不自动继承旧筛选。'
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


def output(description, fields=None):
    return {
        "type": "object",
        "description": description,
        "required": ["status", "summary", "scope", "data", "sources", "limitations", "missingEvidence"],
        "properties": {
            "status": {"type": "string", "enum": ["completed", "limited", "blocked"], "description": "计算完成、限定结果或缺证据无法执行；不代表人工业务验收通过。"},
            "summary": {"type": "string", "description": "基于本轮实际返回事实的简短判断，不编造未返回的指标。"},
            "scope": {"type": "object", "description": "服务端实际授权与过滤后的学院、方案、学期、观察时间等范围；保留空值和未指定情况。", "additionalProperties": True},
            "data": {"type": "object", "description": description, "properties": fields or {}, "additionalProperties": True},
            "tables": {"type": "array", "description": "实际返回的结构化证据表，汇总值与展示行截断分别说明。", "items": {"type": "object", "required": ["title", "columns", "rows", "note"], "properties": {"title": {"type": "string"}, "columns": {"type": "array", "items": {"type": "object", "required": ["key", "label"], "properties": {"key": {"type": "string"}, "label": {"type": "string"}}, "additionalProperties": False}}, "rows": {"type": "array", "items": {"type": "object", "additionalProperties": True}}, "note": {"type": "string"}}, "additionalProperties": False}},
            "sources": {"type": "array", "description": "本轮真实使用的库表、查询名称、数据时点与记录范围；不得填写假来源。", "items": {"type": "object", "additionalProperties": True}},
            "limitations": {"type": "array", "items": {"type": "string"}, "description": "实际受限项，包括范围、缺字段、映射、截断和时间不可比。"},
            "missingEvidence": {"type": "array", "items": {"type": "string"}, "description": "需要补充或确认的具体资料；空记录不等于缺证据已补齐。"},
        },
        "additionalProperties": False,
    }


def task_output(description):
    schema = output(description)
    schema['required'] += ['schemaVersion', 'taskId', 'resultKind', 'facts', 'coverage', 'evidence', 'conditions', 'issues']
    schema['properties'].update({
        'schemaVersion': {'const': '2.0'}, 'taskId': {'type': 'string'},
        'resultKind': {'enum': ['facts', 'rule_check', 'scenario']},
        'facts': {'type': 'array', 'items': {'type': 'object', 'required': ['factId', 'name', 'value', 'sourceRefs'],
                  'properties': {'factId': {'type': 'string'}, 'name': {'type': 'string'}, 'value': {},
                                 'sourceRefs': {'type': 'array', 'items': {'type': 'string'}}}, 'additionalProperties': True}},
        'coverage': {'type': 'object', 'required': ['definedPopulation', 'observedPopulation', 'evaluablePopulation',
                                                 'unknownCount', 'exclusions', 'inputCompleteness'], 'additionalProperties': True},
        'evidence': {'type': 'array', 'items': {'type': 'object', 'required': ['evidenceId', 'sourceRef', 'grain',
            'sourceRowCount', 'retainedRowCount', 'fields', 'retentionComplete', 'records'],
            'properties': {'evidenceId': {'type': 'string'}, 'records': {'type': 'array', 'items': {'type': 'object'}},
                           'retentionComplete': {'type': 'boolean'}}, 'additionalProperties': True}},
        'conditions': {'type': 'array', 'items': {'type': 'object'}},
        'issues': {'type': 'array', 'items': {'type': 'object'}},
        'comparisonCapability': {'type': 'object', 'additionalProperties': True},
    })
    schema['properties']['tables']['items']['properties'].update({
        'totalRows': {'type': ['integer', 'null']}, 'returnedRows': {'type': 'integer'},
        'truncated': {'type': ['boolean', 'null']}, 'evidenceId': {'type': 'string'}})
    return schema


def course_task_output(description):
    """C-BRIEF-01 extensions are optional; old saved results keep their contract."""
    schema = task_output(description)
    count = {'type': 'integer', 'minimum': 0}
    row = {'type': 'object', 'required': ['course_id', 'semester_id', 'first_attempts', 'first_pass',
        'first_unpassed', 'first_pass_pct'], 'properties': {'course_id': {'type': 'string'},
        'semester_id': {'type': 'string'}, 'first_attempts': deepcopy(count), 'first_pass': deepcopy(count),
        'first_unpassed': deepcopy(count), 'first_pass_pct': {'type': 'number'}}, 'additionalProperties': True}
    schema['properties'].update({
        'publishMode': {'enum': ['observation', 'facts_only', 'blocked'],
                        'description': '当次真实语义、指标登记和独立复算决定的发布模式。'},
        'publicationGate': {'type': 'object', 'required': ['publishMode', 'reasons'],
            'properties': {'publishMode': {'enum': ['observation', 'facts_only', 'blocked']},
                           'reasons': {'type': 'array', 'items': {'type': 'string'}}}, 'additionalProperties': True},
        'validationBasis': {'type': 'object', 'required': ['schemaVersion', 'environment',
            'firstAttemptSemantics', 'ruleCompatibility', 'methodRef', 'metricRefs', 'mappingRef',
            'frozenInput', 'independentRecompute', 'threeLayerCheck'],
            'properties': {'schemaVersion': {'const': '1.0'}, 'environment': {'type': 'string'},
                'metricRefs': {'type': 'array', 'items': {'type': 'object'}},
                'mappingRef': {'type': ['object', 'null']},
                'frozenInput': {'type': 'object', 'required': ['sha256', 'rowCount'],
                    'properties': {'sha256': {'type': 'string'}, 'rowCount': deepcopy(count)}, 'additionalProperties': True},
                'independentRecompute': {'type': 'object', 'required': ['state', 'checks', 'inputSha256'],
                    'properties': {'state': {'enum': ['passed', 'failed']}, 'checks': {'type': 'object'},
                                   'inputSha256': {'type': 'string'}}, 'additionalProperties': True},
                'threeLayerCheck': {'type': 'object', 'required': ['state'],
                    'properties': {'state': {'enum': ['equal_current', 'pending']}}, 'additionalProperties': True}},
            'additionalProperties': True},
        'observationState': {'enum': ['no_data', 'no_valid_courses', 'one_course', 'observations', 'no_observations']},
        'observationExclusions': {'type': 'array', 'items': {'type': 'object'}},
        'observationExclusionCounts': {'type': 'object', 'additionalProperties': deepcopy(count)},
        'observations': {'type': 'array', 'items': row}, 'observationCount': deepcopy(count),
        'observationBaseline': {'type': 'object', 'required': ['firstAttempts', 'firstPass', 'ratePct', 'courseCount', 'population'],
            'properties': {'firstAttempts': deepcopy(count), 'firstPass': deepcopy(count),
                'courseCount': deepcopy(count), 'ratePct': {'type': ['number', 'null']}, 'population': {'type': 'string'}},
            'additionalProperties': False},
    })
    return schema


COMMON_RULES = [
    "每次调用使用服务端当前工作身份校验范围；参数不能扩大学院范围，不返回个人身份信息。",
    "先读取可选对象，再使用真实ID查询；输入不完整时只追问影响本轮计算的关键项。",
    "只消费学校数据，既不回写学校主数据，也不执行开班、录取、课程认定或资格审批。",
    "正式事实、管理者补充和讨论假设分开表达；口头补充不能覆盖已保存的来源事实。",
    "未知、未映射、零记录和数值0分别表达；缺失对象不得被静默排除以制造完整结果。",
    "输出实际范围、来源和观察时间；只有同对象、同规则且可复核的数据才能比较。历史批次不稳定时不补造趋势。",
    "工具运行完成仅说明执行状态；需经人工检查数字、范围、边界后才可确认业务结果。",
]

COMMON_STEPS = [
    "确认本轮要回答的问题与当前身份范围；需要对象时调用 list_analysis_options。",
    "校验所需对象和证据，范围冲突或关键资料缺失时停止相应计算并列出具体缺项。",
]

RULE_MISSING = [
    "当年度已批准的学校推免办法、学院实施细则及其生效版本",
    "适用群体、名额分配及毕业/学位/纪律等相关条件来源",
    "课程范围、有效成绩、权重、排名全集、并列及例外处理规则",
    "年度材料清单、认定状态及有效期；接收院校要求需单独核对",
]
CAPACITY_MISSING = [
    "当年度转专业申请与接收规则、批准版本和适用对象",
    "明确的申请/接收群体、预计规模和剩余培养时间",
    "实际开课、班额、可用容量和占用情况",
    "正式先修规则、排课冲突及课程认定关系",
]


def skill(identifier, name, summary, category, params, required, handler, steps, rules, boundaries,
          evidence, data_description, scenarios, missing=(), example_params=None):
    if identifier in {"program-structure", "program-comparison", "transfer-plan-gap"}:
        rules = rules + [
            "展示字段 credits 取自 act_course.credits，标签为课程目录学分；act_curriculum_plan_course.credits 保留为 recorded_plan_credits，标签为方案字段原值（待核对），不直接作为正式学分。",
            "credit_check 区分目录学分缺失、方案字段缺失、字段值不一致和字段值相同；值相同只说明数值一致，不代表已通过学校业务认定。",
            "模块的课程目录学分合计按实际课程安排行的已知目录学分求和，跨模块/学期重复安排仍分别计入；缺值单列，全部缺值时合计未知。",
            "课程目录学分及其模块合计仅供结构对照，不代表该培养方案正式应修学分、毕业最低要求、个人已获学分或可抵扣学分。",
            "方案结构重合与目标覆盖继续按 course_id 去重计数，不采用学分加权；学分字段差异不改变交并集，但必须保留供核对。",
            "读取课程目录学分不表示方案字段或ETL已修复；不回写原数据，不把所有差异自动认定为学时错放。",
        ]
        boundaries = boundaries + ["现有方案课程学分字段与课程目录存在差异；未获学校确认前不能据此计算正式方案学分要求或课程认定。"]
        data_description += " 课程明细区分课程目录学分 credits、方案字段原值 recorded_plan_credits 和 credit_check；不得将结构展示值解释成正式方案学分。"
    binding = [] if handler == "unavailable" else [{"serverId": "education-data", "toolName": "list_analysis_options"}, {"serverId": "education-data", "toolName": handler}]
    sample = example_params or {}
    expected = {
        "status": "blocked" if handler == "unavailable" else "completed_or_limited",
        "assertions": (["明确列出未具备的年度资料", "不生成资格、名额、排名或容量数值"] if handler == "unavailable" else ["范围与所选真实对象一致，包含来源及观察时间", "结果由注册只读工具返回，可回到记录或聚合范围复核", "已知缺项与截断明确列出，不用示例值补齐"]),
    }
    examples = [{"name": "缺证据保护" if handler == "unavailable" else "授权对象的正常查询", "input": sample,
                 "binding": "selection" if any(isinstance(v, str) and v.startswith("${") for v in sample.values()) else "literal", "expected": expected},
                {"name": "缺项或越权时的处理", "input": {}, "expected": {"assertions": ["缺少必填参数时返回参数提示；越权时拒绝且不返回业务数据", "数据不具备时显示具体缺项，不将无结果解释为业务合格或风险为零"]}}]
    if identifier in {"program-structure", "program-comparison", "transfer-plan-gap"}:
        examples[0]["expected"]["assertions"].append("课程目录学分、方案字段原值和核对状态分列；差异不隐藏、不自动修复；交并集仍按课程编号计数")
    special = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(steps))
    return {
        "id": identifier, "name": name, "summary": summary, "category": category, "version": VERSION,
        "instructions": f"任务：{summary}\n先核对当前身份、对象与可用证据。\n{special}\n回答顺序：当前可确认的事实 → 对管理问题的含义 → 不能确认的内容 → 最小下一步。只引用本轮工具返回的证据，不补写学校政策或业务数据。",
        "inputSchema": inputs(params, required),
        "outputSchema": output(data_description),
        "steps": COMMON_STEPS + steps + ["按输出契约保存结果、来源、限制及待明确事项；发布版本与运行时实际版本分别记录。"],
        "rules": COMMON_RULES + rules,
        "boundaries": boundaries,
        "requiredEvidence": evidence,
        "missingEvidence": list(missing),
        "toolBindings": binding,
        "execution": {"handler": handler},
        "examples": examples,
        "references": [SPEC, "code/backend/expert_research/catalog.py", f"code/expert-resources/skills/{identifier}/references/contract.md", f"code/expert-resources/skills/{identifier}/examples/cases.json"],
        "sceneIds": scenarios,
    }


SKILLS = [
    skill("program-structure", "培养方案结构核对", "读取一份培养方案的课程、类别、学分与学期安排，识别结构资料中的待确认项。", "专业建设", ["plan_id", "limit"], ["plan_id"], "read_program_structure",
          ["读取当前方案及课程记录，核对方案名称、适用年级和来源。", "按真实字段展示课程类别、性质、学分和安排；原值未知时单列。", "检查课程明细与汇总范围，标明课程池及未映射类别。", "将原文目标、先修条款和可修改参数的缺项作为下一步资料要求。"],
          ["选修课程池记录数不等于每名学生应修门数；课程池总学分不当作毕业学分要求。", "课程名称近似不能认定为同一课程；只有正式代码或已确认映射可合并。", "学期安排仅表达方案规定，不代表实际开课、无冲突或负荷合理。"],
          ["P3 的目标/毕业要求原文对照尚需经核验的原文版本和定位。", "没有正式先修规则时不判断倒置；没有批准阈值时不判定负荷超限。", "不产生专业特色评分、培养达成率或自动修改方案。"],
          ["当前身份可读的培养方案及其适用关系", "方案课程代码、类别/性质、学分、建议学期及来源记录"],
          "方案身份、实际课程总量、返回明细及结构统计；标明课程池、未知类别、截断和未接原文。", ["P3", "P4"], example_params={"plan_id": "${selected_plan_id}", "limit": 20}),
    skill("program-comparison", "培养方案课程比较", "比较两份已选方案的共同与不同课程，说明可比范围和结构差异。", "专业建设", ["plan_id", "target_plan_id", "limit"], ["plan_id", "target_plan_id"], "compare_programs",
          ["确认两份方案的适用年级和记录范围；不同年级只作为版本结构对照并明确提示。", "使用已注册的课程身份关系分别去重，计算共同和目标独有课程。", "保留双方规模及共同部分，解释交集/并集和交集/目标规模的不同含义。", "围绕结构共同部分列出需核对的培养任务或实际开课资料。"],
          ["当前口径包含全部模块，按 course_id 去重；不自动排除公共课，不强行套用旧场景的非公共必修口径。", "对称结构重合口径为共同去重课程数/双方去重课程并集数；分母为0时返回未知，不填0%。", "目标课程覆盖率为共同课程数/目标全部去重课程数，不等于目标必修要求覆盖率。", "当前仅比较用户明确选择的方案；未遍历并核验候选全集时不称全校最相近或自动排名。", "只在工具确实返回指标及其分母时解释该比例，不由语言模型补算未注册指标。"],
          ["不同适用年级允许做版本结构对照，不作为同年级横向排名；不能把版本差异归因为培养改进效果。", "课程代码共同不等于教学内容重复，也不代表重复投入。", "不从结构差异推导专业优劣、合并建议或课程认定。", "P5 的任意增删课程模拟、师资/成本收益测算尚未接入。"],
          ["两份在当前身份范围内的方案与其现有课程集合", "同一课程身份规则、明确版本与适用年级，缺失记录另行披露"],
          "双方方案、全部模块按course_id去重的规模、共同/目标独有数量、交集/并集、交集/目标规模与目标侧课程对照；仅解释工具实际返回的字段。", ["P1", "P2", "P5"], example_params={"plan_id": "${selected_plan_id}", "target_plan_id": "${selected_target_plan_id}", "limit": 20}),
    skill("course-performance", "课程表现与问题定位", "读取选定范围的课程表现，定位需进一步了解的课程和证据缺项。", "课程质量", ["semester_id", "college_id", "limit"], ["semester_id"], "read_course_performance",
          ["明确学期和学院范围，读取现有课程聚合结果及实际采用的口径。", "查看有效记录、未通过等实际返回的指标及分母，识别值得关注的表现。", "将成绩表现与成因解释分开；跨课程比较时披露群体差异。", "列出分析教学原因、改进做法或前后变化所需的额外证据。"],
          ["当前学院过滤按课程的开课院系，不是学生归属学院；结果必须明示这一范围。", "成绩表现按注册聚合口径读取，不临时改变有效成绩、首修/重修或未通过定义。", "first_attempts 的源注释为首次修读人次；first_pass 为首次通过人次，两者比值为本工具展示的首次通过率，零分母返回空值。", "failures 的源注释为 is_pass=0 的失败次数，不能称未通过人数；课程人数、修读人次和失败次数不能混用。", "列表按现有聚合库的未通过次数降序，仅用于浏览；不作为年度质量排名或教师评价。", "样本不足时披露样本和范围，不自动借用其他学期或演示数据。"],
          ["C3 目标—教学—考核对应暂缓：缺已核对的大纲、教学任务和评分关系。", "不能仅凭未通过率确定教师、教学方式或学生能力的因果。", "C4 只支持提出需核查的问题；没有建设项目与资源证据，不提供最优投入方案。", "C5 当前查询不构成历史批次回放；没有同对象同规则可比记录，不输出变化或建设效果。"],
          ["已授权的课程表现聚合与明确数据时间", "指标含义、有效成绩范围和分母口径"],
          "课程统计记录数、本次展示条数、首次修读人次、首次通过人次、未通过次数等现有聚合字段、首次通过率及聚合版本。", ["C1", "C2", "C3", "C4", "C5"], example_params={"semester_id": "${selected_semester_id}", "limit": 20}),
    skill("transfer-plan-gap", "转专业方案衔接对照", "按来源方案到目标方案的方向查看课程差异，形成需要确认的衔接问题。", "转专业", ["plan_id", "target_plan_id", "limit"], ["plan_id", "target_plan_id"], "compare_programs",
          ["确认来源方案、目标方案及转入方向，不把两份方案当作学生已修记录。", "读取双方共同与各有课程，优先区分目标逐门必修与组合/选修要求。", "仅对字段与规则明确的目标要求解释结构覆盖；条件不足时只显示课程集合差异。", "列出形成个人认定或补修清单还需要的有效成绩、等同关系和目标规则。"],
          ["当前工具包含全部模块，按 course_id 去重；目标课程覆盖率=共同课程数/目标全部去重课程数，只反映课程集合结构。", "目标要求覆盖有方向；不得将 program-comparison 的对称结构重合比例用作转专业覆盖率。", "本版本不计算目标逐门必修覆盖，不将目标独有课程全部称为必须补修。", "相同代码仅说明方案中有共同课程，不代表该学生已修、已通过或可以认定。", "所有成果认定与选修分配需学校正式规则，同一成果不得重复抵扣。"],
          ["当前输入无学生范围和实际已修成绩，因此 T2 实际修读认定与 T3 个人/群体补修量不在本执行能力内。", "不输出申请资格、录取推荐、完整学分认定、保证名额或按期完成承诺。", "T5 仅保留结构衔接讨论；年度接收与承载能力另需 capacity-evidence。"],
          ["来源与目标的可比培养方案和课程记录", "目标课程性质及要求完整性；未知部分须可辨识"],
          "来源和目标方向、共同及不同课程、目标要求中尚待确认的部分；不生成个人资格或完整补修清单。", ["T1", "T2", "T3", "T5"], example_params={"plan_id": "${selected_plan_id}", "target_plan_id": "${selected_target_plan_id}", "limit": 20}),
    skill("transfer-history", "转专业异动记录查询", "从贴源异动记录解析专业与学院路径，按原状态汇总并说明生效时间和覆盖。", "转专业", ["college_id", "semester_id", "limit"], [], "read_transfer_history",
          ["确定当前身份与可选学院；学院范围需映射到唯一名称，无法确认时拒绝查询。", "从 edu_source.std_alteration 读取类型名称为转专业的记录，解析 FIELDS_TEXT 的学院与专业 oldValue/newValue。", "按转出/转入学院、专业和 STATUS 原状态分组，分别展示异动条数及分组内去重学生数。", "选学期时以 act_semester 的起止日期过滤 EFFECTIVE_DATE_TIME；保留来源、生效时间及状态边界。"],
          ["记录类型由 std_alteration.STD_ALTER_TYPE_ID 关联 b_std_alter_type.ID，并限定 NAME_ZH='转专业'；不从缺失路径的ACT投影推造字段。", "FIELDS_TEXT 中 student.departmentAssoc 和 student.majorAssoc 分别给出学院与专业的 oldValue/newValue；按合法JSON解析，不从名称相似推断。", "学院身份以授权 act_organization 的唯一名称精确匹配转出和转入两端，两端均需在范围；无唯一映射时拒绝。", "保留 STATUS 原值并分别分组；INITIAL、UNDONE 等状态不能当作已完成转入，全部异动记录数不是已完成转专业人数。", "学期按已核对起止日期及 EFFECTIVE_DATE_TIME 归属，起日包含、止日次日之前；缺少学期起止日期时拒绝时间归属。", "此方法只使用 std_alteration 集合，不与 student_changes 等其他异动清单混拼。", "历史记录不表示当前年度申请量、成功率或潜在接收需求；同一人多次异动不能把记录条数称为人数，分组人数不能直接相加。"],
          ["属于辅助资料查询，不替代年度转专业管理主线。", "不暴露学生姓名、证件、联系方式或学号明细。", "不能据历史流向推断个人偏好、专业优劣或当年名额。"],
          ["edu_source.std_alteration、b_std_alter_type 中类型、合法 FIELDS_TEXT、STATUS 与 EFFECTIVE_DATE_TIME", "学院查询需授权组织唯一名称；学期查询需 act_semester 有效起止日期"],
          "本次展示路径与状态分组数；转出/转入学院与专业、源记录状态、异动记录数、分组内去重学生数和最近生效日期。来源明确为edu_source，不含个人标识。", ["aux-history"], example_params={"limit": 20}),
    skill("graduation-progress", "毕业准备进度分析", "读取培养进度和模块学分差额汇总，区分已知问题与待确认记录。", "毕业准备", ["plan_id"], ["plan_id"], "read_graduation_progress",
          ["确定对象集合、适用方案/年级及已有进度数据时间。", "读取已计算的进度和缺口汇总，保留未绑定、缺记录等未知状态。", "区分课程要求、课程池与学分差额，不从一个进度指标推断完整资格。", "列出需关注的共性问题以及继续核对所需的条件与资料。"],
          ["已完成学分只采用原系统正式口径；不把来源课程池学分相加后重建毕业要求。", "remaining_credits 为空表示未知，不能由 CASE 的 ELSE 0 变成没有差额；全部缺失时差额数量与平均值必须保持未知并报告缺项。", "模块剩余学分平均值只针对非空记录，必须同时披露有效记录数及缺值数；总学分也要把完整和缺值记录分开。", "缺口课程影响人数不可直接求和当作去重群体总数。", "方案归属与学生当前学院权限分别校验；不能因为方案属于本院就读取当前已属其他学院学生的进度。", "方案适用关系缺失时标记待确认，不直接判定学生未完成。", "规则和数据时点不一致时不能比较准备率或把群体变化解释为改善。"],
          ["不输出正式毕业通过率、学位通过率或资格名单。", "原进度表若只包含汇总或有限条件，不扩展成完整逐条审核。", "G5 历史批次不稳定时只保存本轮观察，不能承诺重建过去的逐人状态。"],
          ["适用对象与方案关系", "当前培养进度聚合、数据时间和计算口径"],
          "方案进度的学生数、记录数、学分值完整记录数、仍有学分差额记录数及模块汇总；无学生个人标识。", ["G1", "G3", "G5"], example_params={"plan_id": "${selected_plan_id}"}),
    skill("graduation-audit", "毕业审核记录核对", "查看既有毕业和学位审核状态，明确需要人工复核的记录范围。", "毕业准备", ["college_id", "semester_id", "limit"], [], "read_graduation_audit",
          ["核对现有审核记录实际标注的批次、群体及生成时间；未返回的规则版本保持未知。", "分别查看已返回的毕业状态、学位状态和源系统公布标记，保留原值。", "原始字典未确认时不解释状态是否通过；没有逐条件记录时不编条件清单。", "列出需要业务部门核对的资料，不把记录缺失当作课程未完成。"],
          ["既有审核记录是本轮读取的证据，不等于本 Skill 重新完成全套资格审核。", "审核状态原值需用确认后的字典解释；不得把未知状态映射成通过。", "毕业与学位条件分开，局部条件满足不能升级为总体资格通过。", "记录缺失不是学生未达到要求；规则不足时保留待确认。"],
          ["不代替学校正式毕业/学位决定，不自动修改审核状态。", "没有条件级来源时仅展示记录层汇总，不编造逐项条件。", "G4 不涉及开班、补考或安排教学；G5 无稳定历史时不补造变化。"],
          ["已授权的审核记录、原状态及实际标注的批次和时间", "解释状态含义另需已确认字典；逐条件审核另需正式规则与条件级记录"],
          "既有审核记录状态分布、条件或记录问题及可查来源；保留未知状态，不含个人明细。", ["G2", "G4", "G5"], example_params={"limit": 20}),
    skill("recommendation-policy", "推免年度规则核对", "整理推免条件、排名、材料与规则影响所需的年度证据；条件未具备时阻止资格计算。", "推免规则", ["college_id"], [], "unavailable",
          ["确认拟讨论年度、学校规则与学院细则的适用关系。", "逐项登记已批准规则、版本、范围、条款及认定责任来源。", "核对课程、成绩、权重、排名全集、并列、名额和例外处理是否齐备。", "当前缺少年度资料时输出具体缺项及补充顺序；资料补齐后需新增适配器、样例测试和业务确认才能开放。"],
          ["通用经验、往年办法和管理者口头假设不能替代当年度正式政策。", "排名必须使用同一规则下完整且授权的群体，不在局部名单上补算正式名次。", "校内推免资格与目标院校接收要求分别核对，不能合并为保研成功判断。", "规则讨论与现行规则分开，讨论参数不能写回或替代已批准版本。"],
          ["R1—R5 均未达到年度业务执行条件；仅交付规则检查契约和缺项清单。", "不生成资格名单、完整准备率、分数排名、名额变化或录取概率。", "接收要求辅助能力尚需目标院校/专业的有效规则。"],
          RULE_MISSING,
          "status=blocked；data 只允许表示资料准备和检查项，返回 missingEvidence，不生成资格、排名、名额等业务结果。", ["R1", "R2", "R3", "R4", "R5", "aux-targets"], missing=RULE_MISSING),
    skill("capacity-evidence", "转专业接收条件核对", "核对年度接收、开课容量与培养时间等证据，防止把课程相近当作接收可行。", "转专业", ["plan_id", "target_plan_id", "college_id"], ["plan_id", "target_plan_id"], "unavailable",
          ["明确来源与目标、年度及实际或假设群体，并标明群体性质。", "核对申请/接收规则与批准版本，区分资格和教学承接条件。", "检查开课容量、正式先修、剩余培养时间及冲突资料。", "当前资料不具备时列出缺项和可先做的方案层对照；补齐后需实现规则适配并重新验收。"],
          ["方案建议学期不等于实际开课，不等于有剩余名额或课表无冲突。", "历史异动规模不能当作本批申请/接收群体。", "条件性分析需列清假设，不能对外称已经形成实际接收决定。"],
          ["T4 开课可行性和 T5 完整承接影响当前阻止执行。", "不输出最大接收人数、保证名额、无冲突课表或按期毕业承诺。", "课程结构差异可由 transfer-plan-gap 独立提供，但不解除本 Skill 的缺项。"],
          CAPACITY_MISSING,
          "status=blocked；列明接收规则、实际群体、课程容量与冲突资料缺项，不生成容量数字和接收结论。", ["T4", "T5"], missing=CAPACITY_MISSING,
          example_params={"plan_id": "${selected_plan_id}", "target_plan_id": "${selected_target_plan_id}"}),
]


def expert(identifier, name, summary, category, responsibilities, boundaries, skill_ids, questions, missing=(), planned=()):
    instructions = (
        f"你承担{name}的业务说明职责。{summary}\n"
        "工作步骤：①确认领导当前要作出的判断、对象和身份范围；②选择已有且可用的 Skill 读取事实；"
        "③先说明能确认的判断，再列出关键证据、管理含义和具体限制；④对影响结论的缺项提出一个最小追问；"
        "⑤保留来源、版本、数据时点及待明确事项。\n"
        "输出结构：问题与范围；当前判断；事实依据；可考虑的下一步；缺项与适用边界。"
        "不展示模型内部推理，只展示真实调用步骤、工具输出依据和规则解释。"
        "已完成工具执行不等于业务确认，已发布资源不等于当前对象资料齐全。"
    )
    return {"id": identifier, "name": name, "summary": summary, "category": category, "version": VERSION,
            "instructions": instructions, "responsibilities": responsibilities, "boundaries": boundaries,
            "skillIds": skill_ids, "plannedSkillIds": list(planned), "starterQuestions": questions, "missingEvidence": list(missing)}


EXPERTS = [
    expert("program", "专业建设专家", "比较培养安排与共同课程，明确需要论证的专业差异。", "建设与改进",
           ["说明培养方案课程结构及资料完整性。", "比较指定方案的共同与不同课程，解释口径和分母。", "提出需要结合培养任务、原文或实际开课继续论证的问题。"],
           ["结构共同不等于教学内容重复或专业同质化。", "当前不支持全校候选自动排名、目标达成评价或任意方案修改模拟。", "没有原文或正式先修规则时不能编造培养目标和衔接问题。"],
           ["program-structure", "program-comparison"], ["这份培养方案的课程和学期安排有哪些待确认项？", "比较这两份方案，哪些课程共同，哪些各有侧重？"]),
    expert("course", "课程质量建设专家", "了解当前课程表现，区分问题事实、成因假设与建设资料缺项。", "建设与改进",
           ["读取学期与学院范围内的课程表现及口径。", "指出值得进一步了解的课程表现和群体范围。", "说明验证教学原因、建设做法及效果还需哪些证据。"],
           ["不把成绩表现直接变成教师评价或因果判断。", "目标—教学—考核对应缺少核验资料，当前暂缓。", "历史批次不可稳定复核时不输出建设前后效果。"],
           ["course-performance"], ["本学期本院哪些课程表现值得进一步了解？", "要判断这类成绩问题的教学原因，还缺哪些资料？"]),
    expert("transfer", "转专业专家", "比较来源与目标培养方案，明确课程衔接、年度规则和承接条件的不同证据要求。", "培养与资格",
           ["按转入方向对照两份方案的共同和不同课程。", "查询贴源转专业异动的授权路径与原状态汇总作为背景。", "列出形成个人认定、补修或接收判断所需的规则与资料。"],
           ["方案对照不是个人已修成果认定，不能直接形成补修承诺。", "没有年度规则与真实容量资料时不判断资格、名额或接收可行。", "历史异动需区分原状态，不都视为已完成，也不代替本批申请数据。"],
           ["transfer-plan-gap", "transfer-history"], ["从这份方案转到目标方案，哪些课程要求需要进一步确认？", "在我的权限范围内，转专业异动记录有哪些路径和状态？"], planned=["capacity-evidence"]),
    expert("recommendation", "保研专家", "围绕当年度已确认规则核对推免条件与工作准备，规则未齐时明确停止资格计算。", "培养与资格",
           ["明确年度规则、学院细则和适用群体。", "核对排名、名额、材料与认定要求是否具备。", "说明资料补齐及业务确认后才能开放的能力。"],
           ["当前年度规则和必要群体记录尚未具备，仅提供准备契约。", "不输出资格名单、正式排名、名额测算或录取概率。", "校内推免与院校接收要求分别核对。"],
           ["recommendation-policy"], ["开始本年度推免条件分析前，需要确认哪些规则与资料？"], missing=RULE_MISSING),
    expert("graduation", "毕业资格审核专家", "读取毕业准备与既有审核资料，区分课程缺口、条件状态和记录问题。", "培养与资格",
           ["说明适用方案下的当前培养进度与已知缺口。", "核对已有审核记录、条件状态和资料异常。", "列出需人工确认的共同保障事项，保留毕业与学位条件边界。"],
           ["不把资料缺失判为学生未完成。", "局部课程进度或既有记录不能替代学校完整资格审核。", "历史批次不稳定时不能补造逐人历史或将群体变化称作改善。"],
           ["graduation-progress", "graduation-audit"], ["本院毕业准备中，哪些是已知课程问题，哪些是资料待确认？", "已有审核记录中的状态和缺项分别代表什么？"]),
]

# This builds candidates only. Existing releases and SQLite history are never rewritten.
for item in SKILLS:
    item['fingerprintScheme'] = 'task-v2'
    task = next((task for task in TASK_DEFINITIONS if task['skillId'] == item['id']), None)
    if task:
        item['taskIds'] = [task['taskId']]
        item['taskDefinitions'] = [task]
        item['realAdapterAvailable'] = task['realAdapterAvailable']
        item['algorithmImplemented'] = task['algorithmImplemented']
        if not task['available']:
            item['plannedProcessorId'] = task['processorId']
    if item['id'] in {'program-comparison', 'course-performance'}:
        item['execution'] = {'processorId': task['processorId']}
        item['inputSchema'] = deepcopy(task['inputSchema'])
        item['outputSchema'] = task_output(item['outputSchema']['description'])
        sample = item['examples'][0]['input']
        if 'limit' in sample:
            sample['previewLimit'] = sample.pop('limit')
        if item['id'] == 'program-comparison':
            sample['comparisonMode'] = 'all_course_ids'
            item['rules'] += ['双方完整课程安排分别保存为证据；previewLimit只改变表格预览，不改变集合或比例分母。',
                              '未知编号记录单列并保留，比例仅称已识别子集；模块未知不能支持排除公共课或专业课分类。']
        else:
            item['outputSchema'] = course_task_output(item['outputSchema']['description'])
            item['rules'] += ['course_id为本轮可选单课筛选；开课院系与学生归属学院不能混用。',
                              '完整聚合行保存为证据；重复课程×学期粒度未经确认不合并，冲突行比率未知。',
                              'students只保留各聚合行原值；跨行重叠未确认时不汇总为唯一人数。',
                              'C-BRIEF-01仅在当次首修集合、源键及字段、开课组织、指标登记和独立复算通过后输出观察；否则保留原字段并说明缺项。',
                              '首修显式is_retake=0、is_published=1、is_void=0、is_pass为0/1；延考未知结果排除并留存，不算作未通过。',
                              'U=first_attempts-first_pass；同范围参照为全部有效唯一课程的sum(P)/sum(N)，不能用前5或算术平均率。',
                              '观察条件U>0且P*scopeN<scopeP*N，顺序U降序、精确P/N升序、course_id升序；预览前5而证据保留全部。',
                              '保存validationBasis、完整原字段和独立复算结果；当次三层一致不证明聚合历史批次可重建。']
    item['execution']['schemaVersion'] = '2.0' if item['id'] in {'program-comparison', 'course-performance'} else '1.0'

existing_ids = {item['id'] for item in SKILLS}
TASK_SCENES = {'P-SUPPORT': ['P3'], 'P-PATH': ['P4'], 'P-CHANGE': ['P5'], 'P-DOCUMENT': ['P3', 'P4'],
    'C-SUPPORT': ['C3', 'C4'], 'C-CHANGE': ['C5'], 'T-RECOGNITION': ['T2', 'T3'],
    'T-POLICY': ['T5'], 'T-POLICY-SCENARIO': ['T5'], 'R-RANK': ['R3'], 'R-CHECK': ['R2'],
    'R-SCENARIO': ['R5'], 'G-CHECK': ['G1', 'G2', 'G3', 'G4'], 'G-CHANGE': ['G5']}
for task in TASK_DEFINITIONS:
    if task['skillId'] in existing_ids:
        continue
    grouped = [value for value in TASK_DEFINITIONS if value['skillId'] == task['skillId']]
    missing = list(dict.fromkeys(reason for value in grouped for reason in value.get('requiredDependencies', [value['reason']])))
    candidate = skill(task['skillId'], task['title'], '；'.join(value['title'] for value in grouped),
        {'program': '专业建设', 'course': '课程质量', 'transfer': '转专业',
         'recommendation': '推免', 'graduation': '毕业核验'}[task['expertId']], [], [], 'unavailable',
        ['校验任务、对象引用与固定适用版本；不从客户端接收成绩或学习成果作为事实。',
         '从授权真实来源和已确认规则读取必要事实；依赖未接入时停止正式计算。',
         '复用已登记共享算法，独立标明来源覆盖、未知、假设和正式结果。'],
        ['候选算法验证不能代替学校业务确认或正式发布。',
         '正式输入仅为对象、已保存结果、文档和规则引用；数据与确认记录由服务端可信适配器读取。',
         'scenario只改变明示获准参数，不改正式基线、规则和学校主数据。'],
        ['真实来源适配器与必要依据尚未就绪，当前不可执行或发布。',
         '不虚构MCP工具、完整资格、因果、全体排名或未来容量。'], missing,
        '任务结果规划；正式执行仍受真实适配器、规则和证据准入约束。',
        list(dict.fromkeys(scene for value in grouped for scene in TASK_SCENES.get(value['taskId'], []))), missing=missing)
    candidate.update({'fingerprintScheme': 'task-v2', 'taskIds': [value['taskId'] for value in grouped],
                      'taskDefinitions': grouped, 'realAdapterAvailable': False,
                      'plannedProcessorId': task['processorId'], 'algorithmImplemented': task['algorithmImplemented']})
    candidate['inputSchema'] = deepcopy(task['inputSchema'])
    if len(grouped) > 1:
        branches = []
        props = {'taskId': {'type': 'string', 'enum': [value['taskId'] for value in grouped]}}
        for value in grouped:
            branch = deepcopy(value['inputSchema'])
            branch['properties']['taskId'] = {'const': value['taskId']}
            branch['required'].append('taskId')
            branches.append(branch)
            props.update(deepcopy(value['inputSchema']['properties']))
        candidate['inputSchema'] = {'type': 'object', 'properties': props, 'required': ['taskId'],
                                    'additionalProperties': False, 'oneOf': branches}
    candidate['outputSchema'] = task_output(candidate['outputSchema']['description'])
    candidate['execution'] = {'handler': 'unavailable', 'schemaVersion': '2.0'}
    candidate['toolBindings'] = []
    if task['realAdapterAvailable']:
        candidate['execution'] = {'processorId': task['processorId'], 'schemaVersion': '2.0'}
        candidate['toolBindings'] = [{'serverId': 'education-data', 'toolName': 'read_learning_results'}]
        candidate['realAdapterAvailable'] = True
    candidate['examples'] = [{'name': '当前正式执行阻塞', 'input': {}, 'expected': {
        'status': 'blocked', 'assertions': ['明确列出真实适配器与必要依据缺口', '不接受客户端成绩、通过状态或成果作为正式事实']}}]
    SKILLS.append(candidate)
    existing_ids.add(task['skillId'])

for item in EXPERTS:
    item['fingerprintScheme'] = 'task-v2'
    item['plannedSkillIds'] = list(dict.fromkeys([*item.get('plannedSkillIds', []),
        *(task['skillId'] for task in TASK_DEFINITIONS if task['expertId'] == item['id'] and not task['formalAvailable']
          and task['skillId'] not in item['skillIds'])]))

TOOL_DEFS = [
    ("list_analysis_options", "可用分析对象", "读取当前身份允许的方案、学院、学期选项；不包含用户或学生个人信息。", inputs([]), "当前授权范围的选项及记录覆盖；用于选择真实ID，不能据选项存在推定详情可执行。"),
    ("read_program_structure", "读取培养方案结构", "读取一份已授权方案的课程结构、记录数，分列课程目录学分与方案字段原值及差异。", inputs(["plan_id", "limit"], ["plan_id"]), "方案身份、课程结构、课程目录学分合计、明细与字段核对；目录学分不代表正式方案学分要求。"),
    ("compare_programs", "比较两份培养方案", "按全部模块的course_id去重比较两份获准方案；不自动排除公共课，不输出必修覆盖；学分差异另列。", inputs(["plan_id", "target_plan_id", "limit"], ["plan_id", "target_plan_id"]), "课程集合交并集、目标覆盖和目标侧明细；目录学分/方案字段原值及差异分列，比例不采用学分加权。"),
    ("read_course_performance", "读取课程表现", "读取当前可用的课程聚合指标及记录数，不输出个人成绩。", inputs(["semester_id", "college_id", "limit"], ["semester_id"]), "授权开课院系/学期的课程聚合行、实际采用口径和来源。"),
    ("read_transfer_history", "读取转专业异动路径与状态", "从edu_source.std_alteration解析学院/专业路径，保留STATUS，以生效日期归属学期；仅授权汇总，无个人标识。", inputs(["college_id", "semester_id", "limit"]), "贴源异动路径与原状态分组、记录数、组内去重人数、最近生效日期及实际来源；不把所有状态当完成。"),
    ("read_graduation_progress", "读取毕业准备进度", "读取指定方案的培养进度聚合，保留已知、未知和缺记录状态。", inputs(["plan_id"], ["plan_id"]), "进度与缺口汇总、对象范围、规则/数据时间和限制。"),
    ("read_graduation_audit", "读取既有毕业审核记录", "读取已有审核记录的状态汇总及问题，既不重新审批也不修改结果。", inputs(["college_id", "semester_id", "limit"]), "已有审核状态和资料问题汇总，保留状态原义与记录范围。"),
]
learning_fields = next(item for item in TASK_DEFINITIONS if item['taskId'] == 'G-CHECK')['inputSchema']['properties']
learning_input = {'type': 'object', 'properties': {key: deepcopy(learning_fields[key])
    for key in ('plan_id', 'populationRef', 'college_id')}, 'required': ['plan_id', 'populationRef'], 'additionalProperties': False}
learning_output = {'type': 'object', 'required': ['status', 'summary', 'objects', 'coverage', 'scope', 'sources', 'limitations'],
    'properties': {'status': {'enum': ['limited']}, 'summary': {'type': 'string'},
        'objects': {'type': 'array', 'items': {'type': 'object', 'required': ['objectRef', 'achievements', 'coverage'],
            'properties': {'objectRef': {'type': 'string'}, 'achievements': {'type': 'array', 'items': {'type': 'object'}},
                           'coverage': {'type': 'object'}}, 'additionalProperties': False}},
        'coverage': {'type': 'object'}, 'scope': {'type': 'object'},
        'sources': {'type': 'array', 'items': {'type': 'object'}},
        'limitations': {'type': 'array', 'items': {'type': 'string'}}}, 'additionalProperties': False,
    'description': '固定授权学籍群体、真实有效结果及实际尝试关联；无姓名学号，业务来源完整性与学校成果/学分确认分别标明。'}
TOOL_DEFS.append(('read_learning_results', '读取真实学习成果关联证据',
    '校验正式主方案分配与学籍专业归属后读取真实有效成果及尝试关联；不以推导进度替代正式分配，全部成果覆盖仍未知。',
    learning_input, learning_output['description']))

MCPS = [{
    "id": "education-data", "name": "教学数据只读服务", "version": VERSION, "transport": "internal", "enabled": True,
    "fingerprintScheme": "task-v2",
    "summary": "按当前工作身份读取培养方案、课程表现、转专业与毕业准备数据，保留来源、记录数和缺项。", "category": "教学数据",
    "endpoint": "/api/admin/expert-resources/mcp",
    "description": "由专家资源服务承载的内部 MCP，只开放登记的只读教学数据工具。沿用当前登录和工作身份，在服务端执行授权与参数校验；不接受任意 SQL，不保存明文数据库凭据。连接检测只能证明当时的协议/数据库可达，不能替代每个 Skill 的业务样例检查。",
    "tools": [{"name": name, "title": title, "description": desc, "inputSchema": schema,
               "outputSchema": deepcopy(learning_output) if name == 'read_learning_results' else output(result_desc), "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}}
              for name, title, desc, schema, result_desc in TOOL_DEFS],
}]


def main():
    catalog = {"experts": EXPERTS, "skills": SKILLS, "mcps": MCPS}
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in SKILLS:
        folder = ROOT / "skills" / item["id"]
        (folder / "references").mkdir(parents=True, exist_ok=True)
        (folder / "examples").mkdir(parents=True, exist_ok=True)
        for key, name in (("inputSchema", "input.schema.json"), ("outputSchema", "output.schema.json")):
            (folder / name).write_text(json.dumps(item[key], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "examples" / "cases.json").write_text(json.dumps(item["examples"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sections = [f"---\nname: {item['id']}\ndescription: {item['summary']}\n---\n", f"# {item['name']}\n", f"应用资源版本：{VERSION}。来源为资源目录种子；实际发布状态、固定依赖和运行记录由系统管理。\n",
                    "## 适用任务\n\n" + item["summary"] + "\n", "## 执行说明\n\n" + item["instructions"] + "\n",
                    "## 输入\n\n输入契约见 [input.schema.json](input.schema.json)。对象ID从当前身份的选项取得，不能用专业名称或示例标记直接调用。\n"]
        props = item["inputSchema"]["properties"]
        sections.append("| 字段 | 必填 | 含义 |\n| --- | --- | --- |\n" + "\n".join(f"| `{k}` | {'是' if k in item['inputSchema']['required'] else '否'} | {v.get('description', k)} |" for k, v in props.items()) + "\n")
        sections += ["## 工作步骤\n\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(item["steps"])) + "\n",
                     "## 计算与解释规则\n\n" + "\n".join("- " + x for x in item["rules"]) + "\n",
                     "## 输出\n\n输出契约见 [output.schema.json](output.schema.json)。" + item["outputSchema"]["description"] + "\n\n用户阅读顺序：范围与本轮判断 → 实际数据与证据表 → 限制与待补资料 → 可以继续的问题。运行成功与人工确认分开。\n",
                     "## 已知边界\n\n" + "\n".join("- " + x for x in item["boundaries"]) + "\n",
                     "## 所需证据\n\n" + "\n".join("- " + x for x in item["requiredEvidence"]) + "\n",
                     "## 当前固定缺项\n\n" + ("\n".join("- " + x for x in item["missingEvidence"]) if item["missingEvidence"] else "没有统一阻止此方法的固定缺项；每次仍需检查所选对象的真实记录。") + "\n",
                     "## 工具依赖\n\n" + ("\n".join(f"- `{b['serverId']}/{b['toolName']}`" for b in item["toolBindings"]) if item["toolBindings"] else "当前处理器为 `unavailable`。没有可执行业务工具，不允许修改状态绕过证据要求。") + "\n",
                     "## 案例与发布检查\n\n案例见 [examples/cases.json](examples/cases.json)。`${selected_*}` 为需由真实选项替换的输入标记，预期值是核验条件，不是虚构的学校结果。使用同一版本真实运行，核对参数、数据范围、来源、限制及输出结构后才可提交人工确认；确认后按系统规则发布。\n",
                     "## 依据\n\n详见 [执行契约与业务依据](references/contract.md)。本文件由目录构建脚本生成；编辑目录内容后统一重建，避免界面与文件不同步。\n"]
        (folder / "SKILL.md").write_text("\n".join(sections), encoding="utf-8")
        (folder / "references" / "contract.md").write_text(
            f"# {item['name']}：执行契约与业务依据\n\n"
            f"对应业务编号：{'、'.join(item['sceneIds'])}。这些是覆盖定位，不代表每个编号的完整目标均已实现。实际范围见 [覆盖清单](../../../coverage.md)。\n\n"
            f"需求依据：仓库根目录下 `{SPEC}`。历史能力边界：`code/backend/expert_research/catalog.py`。\n\n"
            "## 调用前\n\n"
            "- 当前身份由服务端确认，缺失或过期时重新登录，不用管理员默认范围兜底。\n"
            "- 输入只包含 input.schema.json 登记的字段；数据库连接与凭据从服务端配置取得，不从输入传入。\n"
            "- 选择型示例必须用当前选项的真实ID绑定；没有合适对象时保留阻止状态，不换成演示数据。\n\n"
            "## 调用后\n\n"
            "| 字段 | 解释 |\n| --- | --- |\n"
            "| status | completed / limited / blocked 是业务执行范围，不等于人工确认结果 |\n"
            "| summary | 只解释本轮已返回的事实 |\n"
            "| scope | 实际身份范围、对象、过滤条件与环境 |\n"
            "| data | 该方法返回的聚合值；数据类型保留，不把空值变成0 |\n"
            "| tables | 可选证据表；列名与原始键对应，note 解释口径与截断 |\n"
            "| sources | 实际库表、规则及查询/更新时间；查询时间不等于源数据更新时间 |\n"
            "| limitations | 已返回结果的限制，保留在页面和后续引用中 |\n"
            "| missingEvidence | 当前缺失的具体资料，需说明补齐后能解决什么判断 |\n\n"
            "资源运行服务在此结果外保存执行状态、真实工具步骤和版本依赖。执行前即被固定缺项阻止时，外层 status=blocked、result=null，并返回 missingEvidence；不会伪造一个正常业务结果。\n\n"
            "## 与产品经理或业务负责人的交互\n\n"
            "只有会改变本轮数据或解释的问题才追问。按‘冲突或缺项—影响的判断—需要确认的资料—可以先完成的部分’组织；不要泛问用户是否继续。新规则需要出处、适用范围、生效版本与确认记录，不能把一次口头选择升级为全校政策。\n\n"
            "## 验收\n\n"
            "正常样例必须带真实来源和实际范围；缺项样例不输出肯定资格结论；跨学院参数不得扩大权限；更改内容或依赖后重新测试；保留旧运行所用版本。不要用旧测试记录证明新版本已通过。\n",
            encoding="utf-8")
        if item["id"] in {"program-structure", "program-comparison", "transfer-plan-gap"}:
            with (folder / "references" / "contract.md").open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n## 课程学分字段的核对口径\n\n"
                    "当前方案课程表的学分字段与课程目录存在实值差异，部分方案字段经贴源抽查对应的是学时。当前方法采用以下受限展示，不据此宣布全部差异原因已查明。\n\n"
                    "| 返回字段或名称 | 来源与解释 |\n| --- | --- |\n"
                    "| `credits`／课程目录学分 | `act_course.credits`，按课程编号关联，供结构对照 |\n"
                    "| `recorded_plan_credits`／方案字段原值（待核对） | `act_curriculum_plan_course.credits` 原值保留，不自动纠正或隐藏 |\n"
                    "| `credit_check`／字段核对 | 目录学分缺失、方案字段缺失、字段值不一致、字段值相同；相同不等于业务确认 |\n"
                    "| 课程目录学分合计 | 按课程安排行的已知目录学分求和，跨模块/学期保留；缺失条数单列，全部缺失则为空 |\n"
                    "| 学分字段待核对条数／方案字段差异条数 | 非‘字段值相同’的安排条数，包含缺值和数值差异 |\n"
                    "| 结构重合率／目标课程覆盖率 | 仍按 `course_id` 去重计数；不使用目录或方案学分加权 |\n\n"
                    "目录学分不是已经确认的方案应修学分；模块合计不是毕业最低学分要求；目标课程中的目录学分不是个人补修或成果认定学分。选修池也不能全部累加成每名学生应修负担。该处理只保留可核对证据，没有回写方案表或修复ETL。\n")
        if item["id"] == "transfer-history":
            with (folder / "references" / "contract.md").open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n## 当前贴源查询的对应关系\n\n"
                    "| 内容 | 实际读取与处理 |\n| --- | --- |\n"
                    "| 来源库与记录 | `edu_source.std_alteration`，不是修复后的ACT结果 |\n"
                    "| 异动类型 | `STD_ALTER_TYPE_ID → b_std_alter_type.ID`，`NAME_ZH='转专业'` |\n"
                    "| 学院路径 | 合法 `FIELDS_TEXT` 数组中 `field='student.departmentAssoc'` 的 `oldValue/newValue` |\n"
                    "| 专业路径 | 数组中 `field='student.majorAssoc'` 的 `oldValue/newValue`；缺专业值不进入路径分组 |\n"
                    "| 权限 | 授权 `act_organization` 的名称须唯一；转出、转入学院名称都精确命中授权范围；不做模糊匹配 |\n"
                    "| 状态 | 按 `STATUS` 原值分别分组，不把全部记录解释为已完成 |\n"
                    "| 学期 | `act_semester.start_date/end_date`；`EFFECTIVE_DATE_TIME >= start_date` 且 `< end_date+1天` |\n"
                    "| 数量 | 每组 `COUNT(DISTINCT ID)` 为记录数，`COUNT(DISTINCT STUDENT_ID)` 为组内去重人数 |\n"
                    "| 时间 | 最近生效日期是本组 `MAX(EFFECTIVE_DATE_TIME)`，源更新时间与查询时间另列 |\n"
                    "| 展示 | 依请求上限返回1—200个路径与状态分组，不能将展示行数视为全校路径总数 |\n\n"
                    "贴源表补充的是本轮读取证据，没有修复或回写事实层。`student_changes` 是另一份数据集合，不拼入本方法。记录状态、路径分组和时间范围都必须随结果保留，后续解释不能只引用汇总数。\n")
    expert_dir = ROOT / "experts"
    expert_dir.mkdir(exist_ok=True)
    for item in EXPERTS:
        text = f"# {item['name']}\n\n版本 {VERSION}；应用资源草稿种子。\n\n{item['summary']}\n\n## 工作说明\n\n{item['instructions']}\n\n"
        for title, field in (("职责", "responsibilities"), ("边界", "boundaries"), ("建议问题", "starterQuestions"), ("固定缺项", "missingEvidence")):
            text += f"## {title}\n\n" + ("\n".join("- " + s for s in item[field]) or "没有专家级统一固定缺项；单个 Skill 与所选对象的可用性另行检查。") + "\n\n"
        text += "## 能力依赖\n\n" + "\n".join(f"- [{next(s['name'] for s in SKILLS if s['id'] == k)}](../skills/{k}/SKILL.md)" for k in item["skillIds"]) + "\n\nMCP 依赖从所选 Skill 推导；不再维护另一套专家直绑工具清单。发布时只固定已满足发布条件的 Skill 版本，仍缺证据的候选能力保持待补齐。\n"
        if item["plannedSkillIds"]:
            text += "\n## 待具备条件后接入\n\n" + "\n".join(f"- [{next(s['name'] for s in SKILLS if s['id'] == k)}](../skills/{k}/SKILL.md)" for k in item["plannedSkillIds"]) + "\n\n候选能力不属于当前可执行依赖，补齐证据和处理方法后再经测试与业务确认绑定新专家版本。\n"
        (expert_dir / f"{item['id']}.md").write_text(text, encoding="utf-8")
    mcp_dir = ROOT / "mcps" / "education-data"
    mcp_dir.mkdir(parents=True, exist_ok=True)
    (mcp_dir / "tools.json").write_text(json.dumps(MCPS[0]["tools"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (mcp_dir / "README.md").write_text(
        "# 教学数据只读服务\n\n"
        f"资源ID：`education-data`；版本：`{VERSION}`；传输类型：`internal`；入口：`/api/admin/expert-resources/mcp`。\n\n"
        + MCPS[0]["description"] + "\n\n"
        "## 工具清单\n\n| 工具 | 用途 |\n| --- | --- |\n" + "\n".join(f"| `{t['name']}` | {t['description']} |" for t in MCPS[0]["tools"]) + "\n\n"
        "每个工具的完整输入、输出 schema 及只读声明见 [tools.json](tools.json)。只开放登记的方法，客户端不传连接字符串、SQL或身份授权声明。\n\n"
        "## 认证与配置\n\n"
        "由服务端复核现有登录和当前工作身份，服务端保管数据库配置。数据库账号密码不能写入资源内容、示例、运行结果或导出文件。学院范围与全校范围使用同一权限入口，缺失范围拒绝。\n\n"
        "## 能力使用\n\n"
        "Skill 在 toolBindings 中声明精确工具名；专家只选择 Skill。运行时需要核对已发布依赖版本、开关、当前权限、参数契约与实际数据条件。enabled=true 只是配置启用，不代表连通、发布或业务测试已通过。\n\n"
        "## 连接与业务检查\n\n"
        "协议/连接检查核验工具发现和当前身份的只读对象查询。每个工具仍需各自的真实样例，尤其核对学院字段含义、空记录、截断、零分母与缺项。连接状态不替代这些检查。\n\n"
        "## 当前边界\n\n"
        "此包只登记内部服务。外部HTTP服务、SSE服务器、通用适配器、任意SQL工具与学校数据写入均无对应运行实现，不能只添加一个URL或启用状态宣称已接入。历史结果记录当时实际返回内容，不保证重建学校历史批次。\n",
        encoding="utf-8")
    print(f"Generated {len(EXPERTS)} experts, {len(SKILLS)} Skills, {sum(len(s['tools']) for s in MCPS)} MCP tools.")


if __name__ == "__main__":
    main()
