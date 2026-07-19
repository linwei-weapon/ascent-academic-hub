"""管理专家注册表。

专家只负责组织管理问题、规则、证据和可调参数。正式指标仍由业务接口计算，
LLM 不得绕过本协议直接生成指标或扩大数据范围。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


EXPERT_PROTOCOL_VERSION = "management-expert/1.0"
MANAGEMENT_ROLES = [
    "school_leader", "dean", "dept_research", "dept_practice",
    "quality_office", "college_dean", "college_secretary",
]


def _source(name: str, database: str, purpose: str,
            condition: str, required: bool = True) -> dict:
    return {
        "source": name,
        "database": database,
        "required": required,
        "purpose": purpose,
        "completenessCondition": condition,
    }


EXPERTS: dict[str, dict] = {
    "graduation-readiness": {
        "expertId": "graduation-readiness",
        "name": "毕业准备核查专家",
        "version": "1.0.0",
        "status": "active",
        "managementQuestion": "哪些学生需要优先核验，哪些课程保障问题必须在下一轮选课或开课前处理？",
        "description": "区分明确未通过、到期缺证据和课程供给问题，形成学生核验与课程保障优先序。",
        "applicableRoles": MANAGEMENT_ROLES,
        "owners": ["教务处", "二级学院"],
        "dataRequirements": [
            _source("student_plan_course_status", "v2", "识别学生必修课程完成证据",
                    "学生已绑定培养方案，必修课状态可计算"),
            _source("curriculum_plan_course", "v2", "确认课程模块、必选属性和建议学期",
                    "培养方案课程结构已解析"),
            _source("teaching_lesson", "v2", "核查当前和历史开课供给",
                    "课程代码能够与培养方案课程映射"),
            _source("student_course_substitution", "v2", "排除替代或认定未回写造成的误判",
                    "替代关系按学校现行规则接入", False),
        ],
        "metrics": [
            {
                "metricId": "confirmed_failed_students",
                "name": "明确需处理学生",
                "source": "student_plan_course_status",
                "formula": "按学生去重，至少一门必修课 completion_status='failed'",
                "unit": "人",
                "managementValue": "用于形成重修、补修或个案核查名单，不混入仅缺数据证据的学生。",
            },
            {
                "metricId": "verification_due_students",
                "name": "到期待核验学生",
                "source": "student_plan_course_status",
                "formula": "按学生去重，必修课状态为 not_completed/unknown 且 is_overdue=1",
                "unit": "人",
                "managementValue": "优先核验选课、替代、认定和数据回写，避免把数据缺口误判为学业失败。",
            },
            {
                "metricId": "priority_courses",
                "name": "优先保障课程",
                "source": "课程缺口与 teaching_lesson",
                "formula": "明确未通过人次 + 到期缺证据人次 + 涉及专业数，并结合开课供给排序",
                "unit": "门",
                "managementValue": "把学生问题聚合为少量课程级协调事项，支持下一轮教学任务和重修资源安排。",
            },
        ],
        "rules": [
            {"ruleId": "GR-01", "condition": "必修课存在明确未通过证据",
             "meaning": "进入直接处理名单", "priority": "high"},
            {"ruleId": "GR-02", "condition": "建议学期已到但无通过或失败证据",
             "meaning": "进入证据核验名单，不直接判定课程缺失", "priority": "medium"},
            {"ruleId": "GR-03", "condition": "同一课程影响学生或专业较多且供给不足",
             "meaning": "由个案上升为课程保障事项", "priority": "high"},
        ],
        "eventPolicy": {
            "triggerWhen": ["明确需处理学生新增或扩大", "重点课程从有供给变为无供给", "临近毕业学生问题升级"],
            "suppressWhen": ["只有方案结构展示而没有学生执行证据", "问题规模与上次快照相同且无状态变化", "仅存在未核实的数据缺口"],
        },
        "outputs": [
            {"type": "eventCard", "title": "毕业准备变化事件",
             "evidenceRoute": "/admin/curriculum?tab=graduation-readiness"},
            {"type": "evidenceCard", "title": "学生—课程核验依据",
             "evidenceRoute": "/admin/curriculum?tab=graduation-readiness"},
            {"type": "candidateDecision", "title": "课程保障候选决策单",
             "evidenceRoute": "/admin/curriculum?tab=graduation-readiness"},
        ],
        "followUpIntents": [
            {"intentId": "narrow_college", "example": "只看本学院",
             "parameterBindings": ["college"], "scopeExpansionAllowed": False},
            {"intentId": "focus_failed", "example": "只看明确未通过学生",
             "parameterBindings": ["priorityFocus"], "scopeExpansionAllowed": False},
            {"intentId": "simulate_classes", "example": "如果新增3个班能覆盖多少人",
             "parameterBindings": ["addedClasses", "classCapacity", "availableTeachers"],
             "scopeExpansionAllowed": False},
        ],
        "parameters": {
            "addedClasses": {"type": "integer", "default": 3, "min": 0, "max": 20,
                             "unit": "个", "meaning": "本次可讨论的新增班级上限"},
            "classCapacity": {"type": "integer", "default": 30, "min": 15, "max": 120,
                              "unit": "人", "meaning": "单班计划容量"},
            "availableTeachers": {"type": "integer", "default": 3, "min": 0, "max": 20,
                                  "unit": "人", "meaning": "已确认可协调教师上限"},
            "priorityFocus": {"type": "enum", "default": "balanced",
                              "options": ["balanced", "failed", "verification"],
                              "meaning": "本次排序侧重点"},
        },
        "thresholds": {
            "courseHighImpactStudents": 20,
            "graduatingGradeWeight": 1.5,
        },
        "recommendedActions": [
            {"role": "二级学院", "action": "核验学生课程证据并确认处理路径", "timing": "5个工作日内"},
            {"role": "教务处", "action": "汇总跨专业高影响课程并协调开课资源", "timing": "下一轮教学任务前"},
        ],
        "simulator": {
            "enabled": True,
            "scenario": "graduation",
            "endpoint": "/api/admin/ai/simulation/graduation-course-support",
            "doesNotWriteBusinessData": True,
        },
        "uncertainty": ["替代、认定和选课过程数据不完整会扩大待核验范围", "教师与教室实际可用性需要人工确认"],
        "boundaries": ["不输出正式毕业资格结论", "不把待核验证据直接判定为学生未完成", "不承诺未来开课"],
        "testCases": [
            {"caseId": "GR-T01", "given": "必修明确未通过且临近毕业", "expect": "进入高优先级直接处理"},
            {"caseId": "GR-T02", "given": "只有到期缺证据", "expect": "进入核验，不输出明确失败结论"},
        ],
        "recommendedQuestions": ["本次新增的毕业准备问题是什么？", "哪些课程应在下一轮开课前优先保障？", "如果新增3个班，预计能覆盖多少明确未通过人次？"],
        "configurable": {
            "thresholds": ["courseHighImpactStudents", "graduatingGradeWeight"],
            "parameterDefaults": ["addedClasses", "classCapacity", "availableTeachers", "priorityFocus"],
            "recommendedQuestions": True,
        },
    },
    "high-impact-course-support": {
        "expertId": "high-impact-course-support",
        "name": "高影响课程保障专家",
        "version": "1.0.0",
        "status": "active",
        "managementQuestion": "有限的重修、答疑和教学支持资源，应优先投入哪些课程？",
        "description": "综合课程未通过影响面、持续性、供给与学生结构，形成可核查的课程支持优先序。",
        "applicableRoles": MANAGEMENT_ROLES,
        "owners": ["教务处", "开课学院"],
        "dataRequirements": [
            _source("fact_grade", "legacy", "计算课程未通过人数、率和学期变化",
                    "成绩记录包含课程、学生、学期与通过标记"),
            _source("dim_course", "legacy", "提供课程名称和类别",
                    "课程代码与成绩记录可关联"),
            _source("teaching_lesson", "v2", "核查开课班数、容量和学生覆盖",
                    "教学任务课程代码可映射"),
            _source("student_plan_course_status", "v2", "识别必修缺口和受影响学生",
                    "学生培养方案绑定达到可分析范围", False),
        ],
        "metrics": [
            {
                "metricId": "comparable_course_count", "name": "可比课程",
                "source": "fact_grade", "formula": "至少两个学期具有有效成绩记录的去重课程数",
                "unit": "门", "managementValue": "限定可做趋势判断的课程范围，避免用单学期偶然结果判断持续问题。",
            },
            {
                "metricId": "persistent_high_course_count", "name": "持续偏高课程",
                "source": "fact_grade", "formula": "连续可比学期未通过率超过学校阈值的课程数",
                "unit": "门", "managementValue": "优先安排课程复盘、答疑和学习支持资源，而不是只追逐单学期波动。",
            },
            {
                "metricId": "affected_students", "name": "影响学生",
                "source": "fact_grade.student_id", "formula": "重点课程未通过学生去重数",
                "unit": "人", "managementValue": "估算课程支持动作可触达的真实学生规模。",
            },
        ],
        "rules": [
            {"ruleId": "CQ-01", "condition": "至少两个学期可比且未通过率持续超过阈值",
             "meaning": "进入持续性课程支持核查", "priority": "high"},
            {"ruleId": "CQ-02", "condition": "本学期较历史基线变化超过百分点阈值",
             "meaning": "进入波动原因核查，不直接归因教学质量", "priority": "medium"},
            {"ruleId": "CQ-03", "condition": "高影响课程同时存在供给或必修缺口",
             "meaning": "提升资源保障优先级", "priority": "high"},
        ],
        "eventPolicy": {
            "triggerWhen": ["持续偏高课程新增", "影响学生规模明显扩大", "供给约束与高未通过叠加"],
            "suppressWhen": ["仅有一个学期数据", "样本量低于阈值", "变化未超过学校设定百分点"],
        },
        "outputs": [
            {"type": "eventCard", "title": "课程支持变化事件",
             "evidenceRoute": "/admin/operation/course-quality"},
            {"type": "comparisonCard", "title": "课程学期趋势与同类比较",
             "evidenceRoute": "/admin/operation/course-quality"},
            {"type": "candidateDecision", "title": "课程支持资源候选单",
             "evidenceRoute": "/admin/operation/course-quality"},
        ],
        "followUpIntents": [
            {"intentId": "focus_required", "example": "只看必修课",
             "parameterBindings": ["courseType"], "scopeExpansionAllowed": False},
            {"intentId": "change_threshold", "example": "把显著波动改为10个百分点",
             "parameterBindings": ["significantChangePp"], "scopeExpansionAllowed": False},
            {"intentId": "simulate_support", "example": "如果优先支持5门课，覆盖哪些学生",
             "parameterBindings": ["supportCourseLimit"], "scopeExpansionAllowed": False},
        ],
        "parameters": {
            "supportCourseLimit": {"type": "integer", "default": 5, "min": 1, "max": 20,
                                   "unit": "门", "meaning": "本次可优先投入资源的课程数"},
            "significantChangePp": {"type": "number", "default": 8.0, "min": 3.0, "max": 30.0,
                                    "unit": "个百分点", "meaning": "识别显著波动的临时阈值"},
            "courseType": {"type": "enum", "default": "all",
                           "options": ["all", "required", "general", "major"],
                           "meaning": "课程范围"},
        },
        "thresholds": {"persistentFailRate": 20.0, "minimumSampleSize": 30},
        "recommendedActions": [
            {"role": "开课学院", "action": "复核重点课程教学支持和考核结构", "timing": "教学任务制定前"},
            {"role": "教务处", "action": "协调跨学院重修、助教和答疑资源", "timing": "下一轮选课前"},
        ],
        "simulator": {
            "enabled": True, "scenario": "course_support",
            "endpoint": "/api/admin/ai/simulation/graduation-course-support",
            "doesNotWriteBusinessData": True,
        },
        "uncertainty": ["未接入完整考核构成时不能解释具体教学原因", "课程代码变更会影响跨学期可比性"],
        "boundaries": ["不评价单个教师", "波动百分点只描述率的差值", "小样本课程不输出持续偏高结论"],
        "testCases": [
            {"caseId": "CQ-T01", "given": "连续三学期高于阈值且样本充分", "expect": "进入持续偏高"},
            {"caseId": "CQ-T02", "given": "单学期高未通过", "expect": "仅提示观察，不输出持续性判断"},
        ],
        "recommendedQuestions": ["本次新增的高影响课程有哪些？", "哪些课程是持续偏高而不是单学期波动？", "如果只能支持5门课程，优先序是什么？"],
        "configurable": {
            "thresholds": ["persistentFailRate", "minimumSampleSize"],
            "parameterDefaults": ["supportCourseLimit", "significantChangePp", "courseType"],
            "recommendedQuestions": True,
        },
    },
    "course-team-continuity": {
        "expertId": "course-team-continuity",
        "name": "课程团队连续性专家",
        "version": "1.0.0",
        "status": "active",
        "managementQuestion": "哪些高影响课程存在真实的团队连续性风险，需要在教学任务锁定前安排保障？",
        "description": "只核查高覆盖、多班或结构证据不足的课程，排除正常的一班一教师授课。",
        "applicableRoles": MANAGEMENT_ROLES,
        "owners": ["教务处", "开课学院"],
        "dataRequirements": [
            _source("agg_course_team", "v2", "汇总课程教师数量、年龄与职称结构",
                    "课程团队汇总已按课程和学期生成"),
            _source("teaching_lesson", "v2", "计算教学班和学生覆盖",
                    "教学任务、容量与选课人数可用"),
            _source("lesson_teacher", "v2", "核对课程任课教师",
                    "教学班教师关系可用"),
            _source("dim_staff", "v2", "提供年龄和职称结构证据",
                    "教师主数据职称与出生信息达到学校确认范围", False),
        ],
        "metrics": [
            {
                "metricId": "high_impact_single_point", "name": "高影响单点课程",
                "source": "agg_course_team + teaching_lesson",
                "formula": "教师数=1 且（选课≥阈值，或教学班≥阈值且选课≥较低阈值）",
                "unit": "门", "managementValue": "只识别一旦教师不可用就会影响较多学生或多个教学班的课程。",
            },
            {
                "metricId": "title_structure_gap", "name": "职称梯队待核查课程",
                "source": "dim_staff.title", "formula": "团队职称缺失或高职称覆盖未达到学校阈值",
                "unit": "门", "managementValue": "支持课程团队建设核验，不作为教师个人评价。",
            },
            {
                "metricId": "age_structure_gap", "name": "年龄梯队待核查课程",
                "source": "dim_staff.birth_date", "formula": "团队成员年龄集中且缺少相邻梯队，前提是出生信息完整",
                "unit": "门", "managementValue": "提前识别课程传承和师资储备需求。",
            },
        ],
        "rules": [
            {"ruleId": "FT-01", "condition": "单教师且选课人数达到高影响阈值",
             "meaning": "核查备份教师与课程资料", "priority": "high"},
            {"ruleId": "FT-02", "condition": "单教师但仅一个小班",
             "meaning": "正常授课形态，不进入重点核查", "priority": "suppressed"},
            {"ruleId": "FT-03", "condition": "年龄或职称主数据不完整",
             "meaning": "标记证据不足，不输出人才危机结论", "priority": "medium"},
        ],
        "eventPolicy": {
            "triggerWhen": ["高影响单点新增", "覆盖学生或教学班明显扩大", "已关注课程失去备份教师"],
            "suppressWhen": ["正常一班一教师且影响规模低", "教师主数据不足以判断年龄或职称结构", "快照无变化"],
        },
        "outputs": [
            {"type": "eventCard", "title": "团队连续性变化事件", "evidenceRoute": "/admin/faculty"},
            {"type": "evidenceCard", "title": "课程团队结构证据", "evidenceRoute": "/admin/faculty"},
            {"type": "candidateDecision", "title": "备份与梯队建设候选单", "evidenceRoute": "/admin/faculty"},
        ],
        "followUpIntents": [
            {"intentId": "raise_impact", "example": "只看覆盖300人以上的课程",
             "parameterBindings": ["minimumStudents"], "scopeExpansionAllowed": False},
            {"intentId": "simulate_backup", "example": "如果可协调3名教师，优先保障哪些课程",
             "parameterBindings": ["availableTeachers"], "scopeExpansionAllowed": False},
        ],
        "parameters": {
            "availableTeachers": {"type": "integer", "default": 3, "min": 0, "max": 20,
                                  "unit": "人", "meaning": "已确认可协调的备份教师上限"},
            "minimumStudents": {"type": "integer", "default": 300, "min": 50, "max": 1000,
                                "unit": "人次", "meaning": "高影响单点课程学生阈值"},
        },
        "thresholds": {
            "singleTeacherHighStudents": 300,
            "multiClassMinimumLessons": 3,
            "multiClassMinimumStudents": 100,
        },
        "recommendedActions": [
            {"role": "开课学院", "action": "确认备份教师、课程资料和替代开课安排", "timing": "教学任务锁定前"},
            {"role": "教务处", "action": "协调跨学院高影响课程师资保障", "timing": "排课前"},
        ],
        "simulator": {
            "enabled": True, "scenario": "faculty_assurance",
            "endpoint": "/api/admin/ai/simulation/graduation-course-support",
            "doesNotWriteBusinessData": True,
        },
        "uncertainty": ["教师实际可用时间和跨院协调意愿尚需人工确认", "年龄职称主数据缺失时仅能提示核验"],
        "boundaries": ["不把所有单教师课程判定为风险", "不形成教师个人评价", "不输出岗位或晋升建议"],
        "testCases": [
            {"caseId": "FT-T01", "given": "单教师覆盖633人次", "expect": "进入高影响单点核查"},
            {"caseId": "FT-T02", "given": "单教师单小班", "expect": "抑制，不进入重点核查"},
        ],
        "recommendedQuestions": ["本次新增的高影响单点课程是什么？", "哪些课程只是正常一班一教师？", "如果可协调3名教师，应优先保障哪些课程？"],
        "configurable": {
            "thresholds": ["singleTeacherHighStudents", "multiClassMinimumLessons", "multiClassMinimumStudents"],
            "parameterDefaults": ["availableTeachers", "minimumStudents"],
            "recommendedQuestions": True,
        },
    },
}


REQUIRED_FIELDS = {
    "expertId", "name", "version", "managementQuestion", "applicableRoles",
    "dataRequirements", "metrics", "rules", "eventPolicy", "outputs",
    "followUpIntents", "parameters", "recommendedActions", "simulator",
    "uncertainty", "boundaries", "testCases", "configurable",
}


def validate_expert_definition(expert: dict) -> list[str]:
    errors = [f"缺少字段：{name}" for name in sorted(REQUIRED_FIELDS - set(expert))]
    if expert.get("expertId") and not str(expert["expertId"]).replace("-", "").isalnum():
        errors.append("expertId 只能包含字母、数字和连字符")
    if not expert.get("applicableRoles"):
        errors.append("applicableRoles 不能为空")
    if not expert.get("metrics"):
        errors.append("metrics 不能为空")
    for output in expert.get("outputs") or []:
        route = str(output.get("evidenceRoute") or "")
        if not route.startswith("/admin/"):
            errors.append(f"输出 {output.get('title') or '-'} 缺少受控证据路由")
    return errors


def list_experts(role_id: str | None = None) -> list[dict]:
    rows = []
    for expert in EXPERTS.values():
        if role_id and role_id not in expert["applicableRoles"]:
            continue
        rows.append(deepcopy(expert))
    return rows


def get_expert(expert_id: str) -> dict | None:
    expert = EXPERTS.get(expert_id)
    return deepcopy(expert) if expert else None


def _validate_parameter_default(expert: dict, key: str, value: Any) -> str | None:
    spec = (expert.get("parameters") or {}).get(key)
    if not spec:
        return f"参数 {key} 未注册"
    value_type = spec.get("type")
    if value_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return f"参数 {key} 必须为整数"
    if value_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return f"参数 {key} 必须为数值"
    if value_type == "enum" and value not in spec.get("options", []):
        return f"参数 {key} 不在允许选项中"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if spec.get("min") is not None and value < spec["min"]:
            return f"参数 {key} 低于下限 {spec['min']}"
        if spec.get("max") is not None and value > spec["max"]:
            return f"参数 {key} 高于上限 {spec['max']}"
    return None


def validate_school_override(expert: dict, override: dict) -> list[str]:
    errors = []
    allowed_top = {"thresholds", "parameterDefaults", "recommendedQuestions"}
    for key in override:
        if key not in allowed_top:
            errors.append(f"不允许覆盖：{key}")
    configurable = expert.get("configurable") or {}
    allowed_thresholds = set(configurable.get("thresholds") or [])
    for key, value in (override.get("thresholds") or {}).items():
        if key not in allowed_thresholds:
            errors.append(f"阈值 {key} 不允许由学校覆盖")
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"阈值 {key} 必须为数值")
    allowed_params = set(configurable.get("parameterDefaults") or [])
    for key, value in (override.get("parameterDefaults") or {}).items():
        if key not in allowed_params:
            errors.append(f"参数默认值 {key} 不允许由学校覆盖")
            continue
        error = _validate_parameter_default(expert, key, value)
        if error:
            errors.append(error)
    questions = override.get("recommendedQuestions")
    if questions is not None:
        if not configurable.get("recommendedQuestions"):
            errors.append("推荐问题不允许由学校覆盖")
        elif not isinstance(questions, list) or not questions or any(
                not isinstance(item, str) or not item.strip() for item in questions):
            errors.append("推荐问题必须是非空字符串数组")
        elif len(questions) > 8:
            errors.append("推荐问题最多8条")
    return errors


def apply_school_override(expert: dict, override: dict | None) -> dict:
    merged = deepcopy(expert)
    if not override:
        merged["configurationSource"] = "product_default"
        return merged
    errors = validate_school_override(merged, override)
    if errors:
        raise ValueError("；".join(errors))
    merged["thresholds"].update(override.get("thresholds") or {})
    for key, value in (override.get("parameterDefaults") or {}).items():
        merged["parameters"][key]["default"] = value
    if override.get("recommendedQuestions") is not None:
        merged["recommendedQuestions"] = list(override["recommendedQuestions"])
    merged["configurationSource"] = "school_override"
    return merged
