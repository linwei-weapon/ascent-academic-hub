"""AI insight endpoints.

The prototype uses a hybrid strategy:
- a small set of representative records is returned as AI-enhanced samples;
- all other records are handled by deterministic, evidence-based rules.

This keeps demos stable while making the AI value visible on real school data.
"""
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import college_data_scope, get_current_user, get_db, get_v2_db, student_data_scope
from ..envelope import ApiError, ok
from ..util import clean_dept, normalize_title

router = APIRouter(prefix="/api/admin/ai", tags=["ai"])

LEVEL_ORDER = {"严重": 0, "警告": 1, "提醒": 2}
RISK_LABEL = {"critical": "高风险", "warning": "中风险", "info": "关注", "low": "低风险"}
TONE = {"critical": "danger", "warning": "warning", "info": "info", "low": "success"}
AI_SAMPLE_LIMIT = 5
MANAGEMENT_BRIEFING_CACHE_TTL = 1800
_MANAGEMENT_BRIEFING_CACHE: dict[tuple, tuple[float, dict]] = {}
_MANAGEMENT_BRIEFING_HISTORY: dict[tuple, dict] = {}
DECISION_SIMULATION_CACHE_TTL = 300
_DECISION_SIMULATION_CACHE: dict[tuple, tuple[float, dict]] = {}
_DECISION_SIMULATION_BASE_CACHE: dict[tuple, tuple[float, dict]] = {}
CURATED_SAMPLE_PATH = Path(__file__).resolve().parents[2] / "ai_samples" / "curated_insights.v1.json"


def _load_curated_samples() -> list[dict]:
    try:
        data = json.loads(CURATED_SAMPLE_PATH.read_text(encoding="utf-8"))
        return [item for item in data.get("samples", []) if item.get("reviewStatus") == "prototype_curated"]
    except (OSError, ValueError, TypeError):
        return []


CURATED_AI_SAMPLES = _load_curated_samples()
WORKFLOW_BY_LABEL = {
    "待处理": "new",
    "已分派": "assigned",
    "已通知": "notified",
    "已联系": "contacted",
    "帮扶中": "supporting",
    "待复核": "review_pending",
    "已解决": "resolved",
    "已关闭": "closed",
}
V2_ALL_SCOPE_ROLES = {"school_leader", "dean", "dept_operation", "dept_research", "dept_practice", "quality_office"}
V2_MAPPED_SCOPE_ROLES = {"college_dean", "college_secretary", "counselor", "dept_director"}

DEFAULT_TRACEABILITY = {
    "dataSources": ["当前页面已接入的业务数据表"],
    "calculationLogic": "按当前对象的关键证据、命中规则、影响范围和管理优先级生成AI辅助研判。",
    "rules": ["优先使用结构化事实数据；无完整证据时仅提示核查，不直接给出正式业务结论"],
    "formula": "管理优先级 = 风险强度 + 影响范围 + 可行动性 + 数据证据充分度",
    "boundary": "仅用于管理核查和决策辅助，不替代正式审批、毕业审核、教师评价或业务结论。",
    "explanationSources": [
        {"name": "AI结论", "source": "当前对象的证据项、命中规则和管理建议", "usage": "用于解释为什么需要关注，以及下一步应由谁核查。"}
    ],
}

TRACEABILITY_BY_SCENARIO = {
    "student": {
        "dataSources": ["fact_alert", "alert_event", "fact_grade", "dim_course", "dim_student"],
        "calculationLogic": "汇总学生有效预警、成绩通过情况、GPA变化、未通过课程及课程历史未通过率，形成学生个体学业风险研判。",
        "rules": [
            "有效预警来自 fact_alert.is_active=1",
            "未通过课程来自 fact_grade.is_pass=0",
            "GPA变化按相邻学期平均GPA比较",
            "高难度课程按同课程历史未通过率识别",
        ],
        "formula": "高风险：存在严重有效预警，或必修未通过≥2门，或累计未通过≥3门；中风险：存在警告有效预警，或至少1门未通过，或相邻学期GPA下降>0.30；其余按有效预警情况标记关注/低风险。",
        "boundary": "用于辅导员、班主任、学院和教务处核查学生状态，不替代正式成绩认定、处分、毕业资格审核或心理评估。",
        "explanationSources": [
            {"name": "预警解释", "source": "fact_alert.level/type/trigger_detail、alert_event.workflow_status", "usage": "确认最近一次预警来源和是否需要延续干预。"},
            {"name": "课程与GPA解释", "source": "fact_grade.is_pass/gpa/credits、dim_course.name", "usage": "判断学生是否存在课程缺口、GPA下滑或高难度课程暴露。"},
        ],
    },
    "alert_monitor": {
        "dataSources": ["fact_alert", "alert_event", "fact_grade", "dim_student", "dim_college"],
        "calculationLogic": "按预警等级、类型和学生成绩记录汇总当前预警池，识别需要优先分派或复核的学生群体。",
        "rules": ["预警学生按 fact_alert.student_id 去重", "严重/警告优先级高于提醒", "叠加未通过课程数判断处置优先级"],
        "formula": "汇总指标按完整筛选范围统计；重点对象按预警等级（严重>警告>提醒）、未通过课程数降序、触发时间降序排列，仅展示前3名。",
        "boundary": "用于预警监控和名单分派，不代表已完成干预闭环或学生最终风险结论。",
    },
    "graduation_readiness": {
        "dataSources": ["student_plan_course_status", "curriculum_plan_course", "dim_student", "dim_course"],
        "calculationLogic": "按学生绑定培养方案，核查必修课程完成状态、明确未通过、到期缺证据和模块要求，生成毕业准备核查建议。",
        "rules": ["明确未通过来自 completion_status='failed'", "到期缺证据来自 completion_status in ('not_completed','unknown') 且 is_overdue=1", "必修优先级高于选修缺口"],
        "formula": "毕业准备风险 = 必修明确未通过 + 到期缺证据 + 模块完成缺口 + 临近毕业权重",
        "boundary": "用于毕业准备提前核查，不替代学校正式毕业资格审核。",
    },
    "graduation_course_supply": {
        "dataSources": ["student_plan_course_status", "curriculum_plan_course", "teaching_lesson", "lesson_teacher", "student_course_substitution"],
        "calculationLogic": "以课程为单位汇总必修未通过、到期缺证据、涉及专业、开课供给、教师覆盖和替代关系，判断课程保障优先级。",
        "rules": ["学生缺口按课程聚合", "无教学班证据提示供给核查", "替代关系用于降低误判为未完成的风险"],
        "formula": "课程保障优先级 = 明确未通过人数 + 到期缺证据人数 + 涉及专业数 + 供给/替代证据缺口",
        "boundary": "用于课程保障和重修资源核查，不代表未来开课承诺。",
    },
    "operation_course_offering": {
        "dataSources": ["teaching_lesson", "lesson_teacher", "fact_grade", "dim_course"],
        "calculationLogic": "汇总单门课程开课班数、容量、选课人数、教师覆盖和历史未通过情况，判断课程供给与质量核查价值。",
        "rules": ["供给来自 teaching_lesson.capacity/enrolled", "教师覆盖来自 lesson_teacher.staff_id", "课程质量线索来自 fact_grade.is_pass"],
        "formula": "课程运行关注度 = 开课供给压力 + 教师覆盖不足 + 历史未通过率 + 影响学生规模",
        "boundary": "用于教学运行核查，不直接评价课程质量或教师表现。",
    },
    "operation_classroom_occupancy": {
        "dataSources": ["fact_room_occupancy", "dim_building", "dim_room"],
        "calculationLogic": "按楼宇、教室、日期、星期和节次汇总实际占用，识别高负荷时段、晚间占用、重叠记录和楼宇映射问题。",
        "rules": ["占用强度按实际占用记录与观察教室/时段计算", "晚间记录单独标识", "重叠与待映射记录作为数据质量核查线索"],
        "formula": "教室资源关注度 = 峰值占用强度 + 高负荷楼宇 + 晚间占用占比 + 重叠/待映射记录",
        "boundary": "当前是实际占用观察，不等同学校正式可用教室总量或最终排课容量。",
    },
    "operation_schedule_changes": {
        "dataSources": ["fact_schedule_change", "teaching_lesson", "lesson_teacher", "dim_staff"],
        "calculationLogic": "对调停课记录按原因文本、月份、教师和课程进行归类统计，识别集中原因与运行波动。",
        "rules": ["原因文本先做语义归类", "教师TOP只作为核查线索", "月份集中需结合校历和考试周解释"],
        "formula": "调课关注度 = 调课记录数 + 集中原因占比 + 教师/月份集中度",
        "boundary": "调课频次不直接等同教学质量问题，应结合审批依据和补课安排判断。",
    },
    "operation_schedule_teacher": {
        "dataSources": ["fact_schedule_change", "lesson_teacher", "dim_staff", "teaching_lesson"],
        "calculationLogic": "按教师维度汇总调停课次数、原因归类和月份分布，提示是否需要核查审批、补课或排课冲突。",
        "rules": ["同一教师记录数越集中越需要核查", "原因归类用于解释管理动作，不直接归因个人责任"],
        "formula": "教师调课关注度 = 调课次数 + 原因集中度 + 月份集中度",
        "boundary": "用于运行核查，不作为教师教学评价或绩效结论。",
    },
    "operation_teacher_load": {
        "dataSources": ["teaching_lesson", "lesson_teacher", "dim_staff", "dim_course"],
        "calculationLogic": "按教师、学院、职称汇总教学学时、课程数、教学班数和学生覆盖，识别负荷集中与结构性压力。",
        "rules": ["学时和教学班来自教学任务", "职称与组织来自教师主数据", "异常高负荷先进入数据质量核查"],
        "formula": "教师负荷关注度 = 学时 + 课程数 + 教学班数 + 学生覆盖 + 学院/职称结构集中度",
        "boundary": "用于管理核查排序，不替代学校正式工作量核算、超工作量认定或绩效结论。",
    },
    "operation_teacher_load_teacher": {
        "dataSources": ["teaching_lesson", "lesson_teacher", "dim_staff", "dim_course"],
        "calculationLogic": "按单个教师汇总教学任务、学时、课程、教学班和学生覆盖，识别是否需要核查任务映射或负荷分担。",
        "rules": ["超过合理上限时优先提示数据质量核查", "个人负荷只用于排课和资源协调线索"],
        "formula": "教师个人负荷风险 = 学时 + 课程数 + 教学班数 + 学生覆盖 + 数据异常标记",
        "boundary": "不直接评价教师个人教学质量或绩效。",
    },
    "faculty_resource_risk": {
        "dataSources": ["agg_course_team", "teaching_lesson", "lesson_teacher", "dim_staff", "dim_course"],
        "calculationLogic": "按课程团队聚合教师数量、职称结构、年龄线索和学生覆盖，识别单教师、高职称缺口或主数据缺失。",
        "rules": ["单教师课程提示连续性风险", "职称缺失优先作为主数据治理问题", "无高职称线索提示课程团队梯队核查"],
        "formula": "课程团队风险 = 单教师权重 + 职称缺口 + 无高职称线索 + 学生覆盖规模",
        "boundary": "用于课程团队保障核查，不替代教师评价、人事评价或课程质量结论。",
    },
    "faculty_resource_course": {
        "dataSources": ["agg_course_team", "teaching_lesson", "lesson_teacher", "dim_staff", "dim_course"],
        "calculationLogic": "针对单门课程检查教师人数、职称结构、学生覆盖和开课证据，判断团队保障风险。",
        "rules": ["单教师且覆盖学生多优先级最高", "职称缺失需先做教师主数据治理", "团队结构风险需结合学院实际师资确认"],
        "formula": "单课团队保障优先级 = 单教师标记 + 覆盖学生数 + 职称结构风险 + 开课连续性",
        "boundary": "用于课程团队保障核查，不等同课程质量评价。",
    },
    "management_briefing": {
        "dataSources": ["fact_alert", "fact_grade", "student_plan_course_status", "teaching_lesson", "fact_room_occupancy", "agg_course_team"],
        "calculationLogic": "按当前接入数据汇总有效预警、培养方案必修课完成证据、课程未通过记录、教学任务、教室占用和课程团队风险，再按管理影响面生成优先级。",
        "rules": ["有效预警学生按 fact_alert.is_active 去重", "毕业准备按必修课明确未通过和到期缺证据识别", "课程质量按成绩记录未通过率和累计未通过人次识别", "课程团队只把单教师且覆盖不少于300人次，或覆盖不少于3个教学班且不少于100人次的课程列为高影响单点"],
        "formula": "管理优先级 = 高风险学生影响 + 毕业准备可行动问题 + 高影响课程 + 课程团队保障风险 + 运行资源证据",
        "boundary": "管理要情用于管理优先级提示，不替代毕业审核、教师评价或正式审批。",
    },
    "graduation_course_support": {
        "dataSources": ["student_plan_course_status", "curriculum_plan_course", "teaching_lesson", "lesson_teacher", "agg_course_team", "student_course_substitution"],
        "calculationLogic": "先筛选必修课中存在明确未通过或到期缺证据的课程，再叠加开课容量、教师覆盖、课程团队和替代关系，比较不同管理动作的可核查覆盖规模和实施难度。",
        "rules": ["明确未通过来自 completion_status='failed'", "到期缺证据来自 completion_status in ('not_completed','unknown') 且 is_overdue=1", "重修/补修测算参考课程缺口人数和当前开课余量", "认定核查测算参考到期缺证据人数和替代关系线索", "课程团队保障测算参考单教师或职称信息缺口"],
        "formula": "方案得分 = 预计覆盖人次 × 方案收益系数 × 用户侧重点系数；再按得分排序为推荐、备选和观察。重修覆盖同时受可新增班级、单班容量和可协调教师数约束。",
        "boundary": "模拟结果是管理测算，不是学生最终通过预测、毕业结论或开课承诺。",
    },
}

METRIC_MANAGEMENT_META = {
    "有效预警学生": {"source": "fact_alert.student_id / fact_alert.is_active", "managementValue": "判断当前仍需跟踪的预警学生池规模，用于安排学院分派、辅导员沟通和复核优先级。"},
    "毕业需处理学生": {"source": "student_plan_course_status.completion_status / requirement_type", "managementValue": "识别毕业准备中有明确必修课未通过证据的学生，便于提前组织课程补修、重修或个案核查。"},
    "高影响挂科课程": {"source": "fact_grade.course_id / fact_grade.is_pass", "managementValue": "定位累计未通过较多、影响学生面较大的课程，用于课程质量复盘和学习支持资源配置。"},
    "高影响团队课程": {"source": "agg_course_team.teacher_count / teaching_lesson.enrolled", "managementValue": "从宽口径候选池中筛出当期单教师且累计选课不少于100人次的课程，用于优先安排备份教师和开课保障。"},
    "教室占用记录": {"source": "fact_room_occupancy.room_id / weekday / period_index", "managementValue": "判断教室资源分析的数据覆盖度和可用性；记录越完整，楼宇负荷、晚间占用和排课优化判断越可靠。"},
    "模拟课程": {"source": "student_plan_course_status.course_id / curriculum_plan_course.requirement_type", "managementValue": "限定本次模拟纳入的必修问题课程范围，便于教务处聚焦少量高影响课程先处理。"},
    "涉及学生": {"source": "student_plan_course_status.student_id 去重", "managementValue": "判断真实影响学生规模，避免只看课程人次而高估或低估管理工作量。"},
    "明确未通过": {"source": "student_plan_course_status.completion_status='failed'", "managementValue": "估算重修、补修班和学习支持资源的直接需求量。"},
    "到期缺证据": {"source": "student_plan_course_status.completion_status in ('not_completed','unknown') and is_overdue=1", "managementValue": "识别需要先做认定、替代课程或数据回写核验的问题，避免误判为学生未完成。"},
    "覆盖专业": {"source": "dim_student.major_code 按课程聚合", "managementValue": "判断该问题是否跨多个专业，决定由教务处牵头还是学院内部处理。"},
}

EVIDENCE_MANAGEMENT_VALUE = {
    "当前有效预警": "确认学生当前是否仍处于需要跟踪的预警周期，并判断是否需要延续核查。",
    "未通过课程": "判断课程缺口规模及必修课影响，决定是否优先核查重修、补修和选课路径。",
    "累计成绩GPA": "观察全部已接入成绩记录的累计GPA均值，并结合相邻学期变化识别持续下降而非单次波动。",
    "已获学分": "判断学生已完成学习量及未通过学分压力，为毕业准备核查提供基础。",
    "未通过重点课程": "提示当前最需要核对的未通过课程；只有历史未通过率达到阈值时才作为高难度课程提醒。",
    "明确未通过": "识别已有正式成绩证据的必修缺口，优先核查重修、补考或替代路径。",
    "缺结果候选": "识别到建议学期仍缺完成证据的课程，先核验选课、认定和数据回写，避免误判。",
    "无开课证据": "判断课程缺口是否同时存在供给风险，为补修班、替代资源和开课协调提供线索。",
    "培养方案": "确认学生核查所依据的方案版本，避免跨年级、跨专业套用错误要求。",
    "明确未通过学生": "估算课程层面的直接重修或补修需求，优先处理影响学生较多的必修课。",
    "历史教学班": "判断课程是否具有既有开课、师资和容量基础，支持课程保障核查。",
    "替代关系": "判断是否可以先通过课程替代或认定核验减少误判和不必要开班。",
    "教学班": "反映课程实际供给规模，用于判断是否需要查看全部教学班或补充开课资源。",
    "平均班额": "识别大班教学和容量压力，为拆班、增班或学习支持资源配置提供依据。",
    "教师覆盖": "判断课程是否存在教师单点及备份不足，支持下学期开课连续性核查。",
    "容量使用": "判断现有教学班是否还有接纳空间，为重修学生并班或新增班级测算提供依据。",
    "高频时段": "识别课程排课集中时段及晚间压力，为错峰排课和学生课表均衡提供依据。",
    "实际占用记录": "确认教室资源分析的数据覆盖基础，决定楼宇与时段结论的可信程度。",
    "已观察教室": "说明当前分析实际覆盖的教室范围，避免误认为学校正式可用教室总数。",
    "最高楼宇负荷": "定位最需要核查的楼宇与时段，但缺少正式分母时不作为学校利用率结论。",
    "晚间占用": "判断晚间教学活动规模和楼宇集中度，为是否纳入晚间排课优化提供依据。",
    "待核查记录": "识别重叠、楼宇待映射等证据问题，避免数据异常直接进入资源决策。",
    "调停课记录": "判断教学运行调整规模，识别需要结合审批原因和补课安排核查的事项。",
    "影响学生": "反映调停课波及学生规模，帮助优先处理影响面较大的运行问题。",
    "主要原因": "将文本原因归类为可治理问题，支持区分校历因素、临时冲突和可提前优化事项。",
    "高峰月份": "定位调停课集中时段，便于结合校历、考试周和实践周解释异常。",
    "集中月份": "判断单个教师调停课是否集中在特定月份，支持排课冲突核查。",
    "自动审核": "观察调课审批方式结构，为后续检查审批规则与人工复核范围提供依据。",
    "授课教师": "说明当前负荷分析覆盖教师规模，作为学院和职称结构比较的分母。",
    "人均学时": "反映总体任务强度，用于比较学院、职称和教师个体是否存在结构性集中。",
    "高负荷对象": "形成需要先核查任务映射和任务分担的候选教师清单。",
    "最高负荷教师": "定位最需要先核实教学任务、合班与跨学院承担情况的个体，不等同绩效评价。",
    "已排除异常": "说明异常数据未进入真实负荷排序，避免错误任务映射影响管理结论。",
    "最高职称层": "观察不同职称层的平均负荷差异，为师资结构与任务分担分析提供线索。",
    "总学时": "反映教师任务总量，为核查超高负荷、任务拆分和备份教师安排提供依据。",
    "课程/教学班": "同时观察备课种类和授课班级数，避免只用总学时判断实际压力。",
    "学生覆盖": "反映教师或课程团队影响学生规模，用于识别高影响单点。",
    "学院内排名": "用于学院内部确定核查先后，不作为教师绩效排名。",
    "真实团队课程": "说明课程团队分析的有效课程分母，用于计算候选风险比例。",
    "候选核查课程": "形成课程团队候选池；候选比例过高时应先收紧规则和补齐主数据。",
    "高影响单点": "识别单教师承担且学生覆盖较大的课程，优先确认备份教师和开课连续性。",
    "单一教师承担": "识别课程连续性单点，优先为覆盖学生多的课程确认备份教师。",
    "职称信息不完整": "定位教师主数据缺口，避免将资料缺失误判为团队梯队风险。",
    "重点覆盖人次": "衡量重点候选课程影响面，支持跨学院课程团队保障排序。",
    "实际授课教师": "确认单门课程真实师资规模，判断是否存在教学连续性单点。",
    "教学班/选课": "同时反映课程供给和学生影响面，为师资保障优先级提供依据。",
    "职称已知": "说明课程团队职称结构分析的证据完整度，缺失时先做主数据核验。",
    "教授/副教授": "观察高级职称梯队线索，用于课程团队传承和备份能力核查。",
    "命中原因": "汇总课程进入候选池的具体原因，帮助学院区分师资风险和数据问题。",
}

BUSINESS_SOURCE_LABELS = {
    "fact_alert": "学业预警记录",
    "alert_event": "预警处理状态",
    "fact_grade": "学生成绩明细",
    "dim_course": "课程主数据",
    "dim_student": "学生学籍信息",
    "dim_college": "学院组织信息",
    "student_plan_course_status": "学生培养方案课程完成证据",
    "curriculum_plan_course": "培养方案课程要求",
    "teaching_lesson": "教学任务与教学班",
    "lesson_teacher": "教学班授课教师",
    "student_course_substitution": "课程替代与认定关系",
    "fact_room_occupancy": "实际教室占用记录",
    "dim_building": "楼宇主数据",
    "dim_room": "教室主数据",
    "fact_schedule_change": "调停课记录",
    "dim_staff": "教师主数据",
    "agg_course_team": "课程团队结构汇总",
}

THRESHOLDS_BY_SCENARIO = {
    "student": [
        "存在严重有效预警，或必修未通过课程不少于2门，或累计未通过课程不少于3门：高风险",
        "存在警告有效预警，或至少1门课程未通过，或相邻学期GPA下降超过0.30：中风险",
        "课程历史未通过率达到20%才显示高难度课程提醒",
    ],
    "alert_monitor": ["完整筛选范围聚合，不受重点对象展示数量限制", "严重优先于警告，警告优先于提醒", "重点对象按等级、未通过课程数和触发时间排序"],
    "graduation_readiness": ["必修课明确未通过优先进入处理清单", "到建议学期仍缺通过、失败或认定证据时进入待核验清单"],
    "graduation_course_supply": ["明确未通过或到期缺证据不少于1人时进入候选池", "无教学班、教师不超过1人或无替代关系时增加保障核查原因"],
    "operation_course_offering": ["班均规模、容量使用、教师覆盖和历史未通过率共同构成核查线索", "课程差异只触发核查，不直接评价课程或教师"],
    "operation_classroom_occupancy": ["晚间记录按数据中的晚间标记统计", "待映射或重叠记录进入待核查清单", "缺少正式可用教室分母时不输出学校正式利用率"],
    "operation_schedule_changes": ["原因文本按语义词典归类", "教师和月份集中只作为运行核查线索，不归因个人责任"],
    "operation_schedule_teacher": ["教师调停课次数、原因集中度和月份集中度共同用于排序", "不作为教师评价或绩效结论"],
    "operation_teacher_load": ["高负荷阈值沿用当前教师负荷专题口径", "先排除异常任务映射，再判断任务集中"],
    "operation_teacher_load_teacher": ["个人负荷超过专题阈值时先核查任务映射与合班关系", "高负荷不等同教学质量问题"],
    "faculty_resource_risk": ["单教师承担、职称信息不完整或无高职称线索时进入候选池", "高影响单点=当期仅1名实际授课教师且累计选课人次不少于100；100人为原型核查阈值"],
    "faculty_resource_course": ["单教师且覆盖学生较多优先", "职称缺失先按主数据问题处理"],
    "management_briefing": ["管理要情优先展示本次新增、升级、变化或退出重点的管理事项", "专题排序依据影响范围、紧迫性和可行动性，不代表正式审批顺序"],
    "graduation_course_support": ["明确未通过与到期缺证据分别测算", "方案优先级同时考虑覆盖人次、资源成本、实施难度和数据核验价值"],
}

MANAGEMENT_CONSEQUENCE_BY_SCENARIO = {
    "student": "若不及时核查，课程缺口可能继续叠加，并在后续选课或毕业准备阶段集中暴露。",
    "alert_monitor": "若不先收敛重点对象，学院容易把精力平均分配到全部预警记录，真正需要介入的学生可能被淹没。",
    "graduation_readiness": "若不在关键培养节点前核查，明确课程问题可能延后到毕业审核阶段集中处理。",
    "graduation_course_supply": "若不先区分真实未通过与证据缺口，可能造成重修资源误配或遗漏课程供给瓶颈。",
    "operation_course_offering": "若不核查供给与质量线索的叠加影响，可能在下轮开课时继续形成容量或学习支持压力。",
    "operation_classroom_occupancy": "若不核查高峰时段与特殊空间瓶颈，排课优化可能只在局部时段反复挤压。",
    "operation_schedule_changes": "若不识别集中原因，调课问题可能被当作零散事务处理，难以形成运行改进措施。",
    "operation_schedule_teacher": "若不核查集中时段和原因，可能遗漏排课冲突或补课安排中的结构性问题。",
    "operation_teacher_load": "若不先核查异常映射和负荷集中，可能影响下轮任务分配与课程保障判断。",
    "operation_teacher_load_teacher": "若不核查任务映射和分担条件，可能延续个体负荷集中或形成课程连续性风险。",
    "faculty_resource_risk": "若不优先确认高影响课程的备份能力，可能在教师不可用或任务调整时影响稳定开课。",
    "faculty_resource_course": "若不确认备份教师和团队结构，课程在任务调整时可能缺少可替代的授课安排。",
}


def _management_intervention(payload: dict) -> dict:
    """Build a compact, management-oriented contract for every insight.

    Existing scenario payloads remain available during migration.  The new fields
    deliberately separate intervention status, decision wording, comparison facts
    and suggested actions so the UI no longer has to flatten all AI text equally.
    """
    risk = str(payload.get("riskLevel") or "").lower()
    tone = str(payload.get("riskTone") or "").lower()
    label = str(payload.get("riskLabel") or "")
    scenario = _trace_key(payload)
    confidence = str(payload.get("confidence") or "中")
    evidence = [item for item in (payload.get("evidence") or []) if isinstance(item, dict)]
    reasons = [str(item) for item in (payload.get("reasons") or []) if item]
    suggestions = [item for item in (payload.get("suggestions") or []) if isinstance(item, dict)]
    next_actions = [str(item) for item in (payload.get("nextActions") or []) if item]

    verification_words = ("待核验", "需核验", "缺证据", "证据不足", "待映射", "信息不完整")
    needs_verification = confidence == "低" or any(
        word in " ".join([
            label,
            str(payload.get("summary") or ""),
            *reasons,
            *[str(item.get("label") or "") + str(item.get("detail") or "") for item in evidence],
        ])
        for word in verification_words
    )
    high = risk in {"critical", "high"} or tone == "danger" or label in {"高风险", "严重", "高优先级"}
    medium = risk in {"warning", "medium"} or tone == "warning" or label in {"中风险", "警告", "中优先级"}
    low = risk in {"low"} or tone == "success" or label in {"低风险", "正常", "无需关注"}

    if high and not needs_verification:
        status, status_label, priority = "action_required", "需优先核查", "high"
    elif needs_verification and (high or medium or evidence):
        status, status_label, priority = "verification_required", "优先核验", "high" if high else "medium"
    elif medium:
        status, status_label, priority = "watch", "持续观察", "medium"
    elif low or not evidence:
        status, status_label, priority = "no_intervention", "当前无需AI介入", "low"
    else:
        status, status_label, priority = "watch", "持续观察", "low"

    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    comparison_available = bool(comparison.get("available") or comparison.get("changes"))
    comparison.setdefault("available", comparison_available)
    comparison.setdefault("baseline", "当前仅有单期或当前快照证据，不能判断是否恶化或改善。")
    comparison.setdefault("changes", [])

    primary = suggestions[0] if suggestions else {}
    primary_action = payload.get("primaryAction") if isinstance(payload.get("primaryAction"), dict) else {}
    primary_action.setdefault("role", primary.get("role") or "当前授权管理角色")
    primary_action.setdefault("action", primary.get("action") or (next_actions[0] if next_actions else "查看业务证据并确认是否需要纳入本轮核查"))
    primary_action.setdefault("detail", primary.get("detail") or "先核对对象、数据时点和关键证据，再形成正式业务判断。")
    primary_action.setdefault("timing", payload.get("recommendedTiming") or "下一业务节点前")
    primary_action.setdefault("expectedResult", payload.get("expectedResult") or "形成已核实的问题清单、责任范围和后续处理依据")

    alternative_actions = payload.get("alternativeActions")
    if not isinstance(alternative_actions, list):
        alternative_actions = [
            {
                "role": item.get("role"),
                "action": item.get("action"),
                "detail": item.get("detail"),
            }
            for item in suggestions[1:3]
        ]
        if len(alternative_actions) < 2:
            for action in next_actions[1:3]:
                alternative_actions.append({"role": "相关业务人员", "action": action, "detail": "作为首要核查后的备选动作。"})

    impact_parts = []
    for item in evidence[:3]:
        if item.get("label") and item.get("value"):
            impact_parts.append(f"{item['label']} {item['value']}")
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    decision.setdefault("headline", payload.get("summary") or "当前对象需要结合业务证据进一步核查。")
    decision.setdefault("whyNow", reasons[:3] or ["当前对象命中本场景管理介入规则，需要先核对关键证据和影响范围。"])
    decision.setdefault("impactScope", "；".join(impact_parts) or payload.get("targetName") or "当前对象")
    decision.setdefault("consequence", MANAGEMENT_CONSEQUENCE_BY_SCENARIO.get(scenario, "若不先核查关键证据，可能造成管理注意力分散或业务判断依据不足。"))

    return {
        "intervention": {
            "status": status,
            "label": status_label,
            "priority": priority,
            "priorityReasons": reasons[:3],
        },
        "decision": decision,
        "comparison": comparison,
        "primaryAction": primary_action,
        "alternativeActions": alternative_actions[:2],
    }


def _trace_key(payload: dict) -> str:
    scenario = payload.get("scenario") or ""
    target_type = payload.get("targetType") or ""
    if scenario in TRACEABILITY_BY_SCENARIO:
        return scenario
    if target_type == "student":
        return "student"
    if scenario.startswith("graduation"):
        return "graduation_readiness"
    if scenario.startswith("operation_teacher_load_teacher"):
        return "operation_teacher_load_teacher"
    if scenario.startswith("operation_teacher_load"):
        return "operation_teacher_load"
    if scenario.startswith("operation_schedule_teacher"):
        return "operation_schedule_teacher"
    if scenario.startswith("operation_schedule"):
        return "operation_schedule_changes"
    if scenario.startswith("faculty_resource_course"):
        return "faculty_resource_course"
    if scenario.startswith("faculty_resource"):
        return "faculty_resource_risk"
    return target_type or scenario or "default"


def _traceability_for(payload: dict) -> dict:
    base = dict(DEFAULT_TRACEABILITY)
    specific = TRACEABILITY_BY_SCENARIO.get(_trace_key(payload), {})
    base.update(specific)
    existing = payload.get("traceability") or {}
    base.update({k: v for k, v in existing.items() if v})
    return base


def _join_source(traceability: dict) -> str:
    sources = traceability.get("dataSources") or []
    if isinstance(sources, list):
        return "、".join(sources)
    return str(sources)


def _business_source_text(source) -> str:
    raw = "、".join(source) if isinstance(source, list) else str(source or "")
    labels = [label for table, label in BUSINESS_SOURCE_LABELS.items() if table in raw]
    return "、".join(dict.fromkeys(labels)) or "当前页面业务数据"


def _curated_evidence_map(payload: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("evidence", "metrics"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and item.get("label"):
                result[str(item["label"])] = str(item.get("value", ""))
    return result


def _apply_curated_sample(payload: dict) -> dict:
    """Apply a reviewed, offline LLM output only when its evidence fingerprint matches.

    A model-authored sample is never selected by risk level alone.  Target fields and
    the saved evidence snapshot must still match, otherwise the deterministic rule
    result remains visible and is labelled honestly as such.
    """
    evidence = _curated_evidence_map(payload)
    for sample in CURATED_AI_SAMPLES:
        match = sample.get("match") or {}
        if any(str(payload.get(key, "")) != str(value) for key, value in match.items()):
            continue
        fingerprint = sample.get("evidenceFingerprint") or {}
        if any(evidence.get(str(label)) != str(value) for label, value in fingerprint.items()):
            continue
        output = sample.get("output") or {}
        for key, value in output.items():
            payload[key] = value
        payload.update({
            "source": "curated_llm_sample",
            "sourceLabel": "离线大模型研判样本",
            "generatedBy": "curated_offline_llm_output",
            "curatedSampleId": sample.get("id"),
            "modelTrace": {
                **(sample.get("model") or {}),
                "promptVersion": sample.get("promptVersion"),
                "generatedAt": sample.get("generatedAt"),
                "reviewStatus": sample.get("reviewStatus"),
                "reviewedBy": sample.get("reviewedBy"),
                "evidenceSnapshot": sample.get("evidenceSnapshot") or fingerprint,
            },
        })
        return payload
    return payload


def _normalize_provenance(payload: dict) -> dict:
    generated_by = str(payload.get("generatedBy") or "")
    if payload.get("source") == "ai_sample" or generated_by.startswith("offline_llm"):
        payload["source"] = "rule"
        payload["sourceLabel"] = "规则研判"
        payload["generatedBy"] = "deterministic_rule_engine"
    return payload


def _with_ai_trace(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    traceability = _traceability_for(payload)
    trace_key = _trace_key(payload)
    traceability.setdefault("businessDataSources", _business_source_text(traceability.get("dataSources")))
    traceability.setdefault("ruleVersion", "AI-RULE-2026.07-v1")
    traceability.setdefault("asOfTime", payload.get("generatedAt") or _now())
    traceability.setdefault("scope", payload.get("scopeLabel") or payload.get("targetName") or "当前页面筛选范围")
    traceability.setdefault("thresholds", THRESHOLDS_BY_SCENARIO.get(trace_key, ["按当前场景结构化证据触发核查提示；证据不足时不输出正式业务结论"]))
    confidence = payload.get("confidence") or "中"
    traceability.setdefault("confidenceBasis", f"当前证据充分度为“{confidence}”，表示已接入结构化证据对本次解释的支持程度；它是原型阶段的定性标识，不是风险发生概率。")
    if payload.get("modelTrace"):
        model = payload["modelTrace"]
        traceability["generationMethod"] = (
            f"离线大模型样本 · {model.get('modelName','模型未标注')} · "
            f"提示词 {model.get('promptVersion','未标注')} · {model.get('reviewStatus','未审核')}"
        )
    else:
        traceability.setdefault("generationMethod", "确定性规则引擎实时计算")
    payload["traceability"] = traceability
    default_source = _join_source(traceability)

    for item in payload.get("evidence") or []:
        if isinstance(item, dict):
            item.setdefault("source", default_source)
            item.setdefault("businessSource", _business_source_text(item.get("source")))
            item.setdefault("managementValue", EVIDENCE_MANAGEMENT_VALUE.get(item.get("label"), "用于支撑本次AI研判的风险等级、原因解释和后续核查动作。"))

    for item in payload.get("metrics") or []:
        if isinstance(item, dict):
            meta = METRIC_MANAGEMENT_META.get(item.get("label"), {})
            item.setdefault("source", meta.get("source", default_source))
            item.setdefault("businessSource", _business_source_text(item.get("source")))
            item.setdefault("managementValue", meta.get("managementValue", item.get("hint") or "用于判断管理优先级和后续核查范围。"))

    for item in payload.get("priorities") or []:
        if isinstance(item, dict):
            item.setdefault("source", default_source)
            item.setdefault("businessSource", _business_source_text(item.get("source")))
            item.setdefault("managementValue", item.get("why") or "用于把AI摘要转化为管理优先级和专题核查入口。")

    for section in payload.get("sections") or []:
        if isinstance(section, dict):
            section.setdefault("source", default_source)
            section.setdefault("businessSource", _business_source_text(section.get("source")))
            for item in section.get("evidence") or []:
                if isinstance(item, dict):
                    item.setdefault("source", default_source)
                    item.setdefault("businessSource", _business_source_text(item.get("source")))
                    item.setdefault("managementValue", section.get("managementValue") or "用于支撑该专题的管理判断。")

    for item in payload.get("scenarios") or []:
        if isinstance(item, dict):
            item.setdefault("source", default_source)
            item.setdefault("businessSource", _business_source_text(item.get("source")))
            item.setdefault("managementValue", item.get("bestFor") or "用于比较不同管理动作的收益、成本和实施难度。")
            item.setdefault("evidenceBasis", [
                {"source": default_source, "usage": item.get("logic") or "用于支撑该方案的覆盖规模和优先级判断。"}
            ])

    if "explanationSources" not in payload:
        payload["explanationSources"] = traceability.get("explanationSources") or [
            {"name": "AI解释", "source": default_source, "usage": "用于说明研判原因、管理价值和建议动作的依据。"}
        ]
    management = _management_intervention(payload)
    for key, value in management.items():
        payload.setdefault(key, value)
    return payload


def ai_ok(payload: dict):
    payload = _normalize_provenance(payload)
    payload = _apply_curated_sample(payload)
    return ok(_with_ai_trace(payload))


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _student_scope_sql(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    frag, params = student_data_scope(user, conn, alias)
    return (f" AND {frag}" if frag else "", params)


def _v2_student_scope(user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    role = user.get("role_id")
    if role in V2_ALL_SCOPE_ROLES:
        return "", []
    if role not in V2_MAPPED_SCOPE_ROLES:
        raise ApiError("当前角色没有V2访问范围", code=403, status_code=403)
    mappings = dbm.query(conn, "SELECT * FROM access_scope_mapping WHERE role_id=? AND mapping_status='mapped'", (role,))
    if not mappings:
        raise ApiError("V2数据范围未映射", code=403, status_code=403)
    scope_type = mappings[0]["scope_type"]
    if scope_type == "college":
        values = [x["organization_id"] for x in mappings if x.get("organization_id")]
        field = "organization_id"
    elif scope_type == "major":
        values = [x["major_code"] for x in mappings if x.get("major_code")]
        field = "major_code"
    elif scope_type == "class":
        values = [x["class_code"] for x in mappings if x.get("class_code")]
        field = "class_code"
    else:
        raise ApiError("不支持的V2数据范围类型", code=403, status_code=403)
    if not values:
        raise ApiError("V2数据范围为空", code=403, status_code=403)
    return f"{alias}.{field} IN ({','.join('?' for _ in values)})", values


def _v2_student_access(conn: sqlite3.Connection, student_id: str, user: dict) -> dict:
    scope, params = _v2_student_scope(user, conn, "s")
    row = dbm.query_one(conn, f"""
        SELECT s.student_id,s.display_name,s.entry_grade,s.organization_id,s.major_code,
               s.major_name,s.class_code,p.plan_name,p.version
        FROM dim_student s
        LEFT JOIN curriculum_plan p ON p.plan_id=s.plan_id
        WHERE s.student_id=?{(' AND ' + scope) if scope else ''}
    """, tuple([student_id] + params))
    if not row:
        raise ApiError("学生不存在或无权访问", code=404, status_code=404)
    return row


def _gpa_history(conn: sqlite3.Connection, student_id: str) -> list[dict]:
    return dbm.query(conn, """
        SELECT semester_id, ROUND(AVG(gpa), 2) AS gpa
        FROM fact_grade
        WHERE student_id=? AND gpa IS NOT NULL
        GROUP BY semester_id
        ORDER BY semester_id
    """, (student_id,))


def _student_base(conn: sqlite3.Connection, student_id: str, user: dict) -> dict:
    scope_sql, scope_params = _student_scope_sql(user, conn, "s")
    row = dbm.query_one(conn, f"""
        SELECT s.student_id, s.name, s.grade, s.status,
               c.name AS college_name, m.name AS major_name, cl.name AS class_name
        FROM dim_student s
        LEFT JOIN dim_college c ON c.college_id=s.college_id
        LEFT JOIN dim_major m ON m.major_id=s.major_id
        LEFT JOIN dim_class cl ON cl.class_id=s.class_id
        WHERE s.student_id=?{scope_sql}
    """, [student_id] + scope_params)
    if not row:
        raise ApiError("学生不存在或无权访问", code=404, status_code=404)
    return row


def _student_alerts(conn: sqlite3.Connection, student_id: str) -> list[dict]:
    return dbm.query(conn, """
        SELECT a.alert_id, a.level, a.type, a.trigger_detail, a.status,
               a.created_at, a.semester_id, a.is_active,
               e.event_id, e.workflow_status
        FROM fact_alert a
        LEFT JOIN alert_event e ON e.alert_id=a.alert_id
        WHERE a.student_id=?
        ORDER BY COALESCE(a.created_at, '') DESC, a.alert_id DESC
    """, (student_id,))


def _student_grade_stats(conn: sqlite3.Connection, student_id: str) -> dict:
    stats = dbm.query_one(conn, """
        SELECT COUNT(*) AS grade_rows,
               COUNT(DISTINCT CASE WHEN is_pass=0 THEN course_id END) AS failed_courses,
               COUNT(DISTINCT CASE WHEN is_pass=0 AND COALESCE(is_required,0)=1 THEN course_id END) AS failed_required_courses,
               ROUND(AVG(CASE WHEN gpa IS NOT NULL THEN gpa END), 2) AS avg_gpa,
               ROUND(SUM(CASE WHEN is_pass=1 THEN COALESCE(credits,0) ELSE 0 END), 1) AS earned_credits,
               ROUND(SUM(CASE WHEN is_pass=0 THEN COALESCE(credits,0) ELSE 0 END), 1) AS failed_credits,
               SUM(CASE WHEN is_retake=1 THEN 1 ELSE 0 END) AS retake_attempts
        FROM fact_grade
        WHERE student_id=?
    """, (student_id,)) or {}
    history = _gpa_history(conn, student_id)
    stats["gpa_history"] = history
    if len(history) >= 2:
        stats["gpa_delta"] = round((history[-1]["gpa"] or 0) - (history[-2]["gpa"] or 0), 2)
    else:
        stats["gpa_delta"] = None
    return stats


def _failed_courses(conn: sqlite3.Connection, student_id: str, limit: int = 5) -> list[dict]:
    rows = dbm.query(conn, """
        SELECT g.course_id, COALESCE(c.name, g.course_id) AS course_name,
               COUNT(*) AS fail_count,
               MAX(g.semester_id) AS last_semester,
               ROUND(MIN(g.score), 1) AS min_score,
               MAX(COALESCE(g.is_required, c.is_required, 0)) AS is_required
        FROM fact_grade g
        LEFT JOIN dim_course c ON c.course_id=g.course_id
        WHERE g.student_id=? AND g.is_pass=0
        GROUP BY g.course_id, COALESCE(c.name, g.course_id)
        ORDER BY fail_count DESC, last_semester DESC
        LIMIT ?
    """, (student_id, limit))
    for row in rows:
        total = dbm.scalar(conn, "SELECT COUNT(*) FROM fact_grade WHERE course_id=? AND is_pass IS NOT NULL", (row["course_id"],)) or 0
        failed = dbm.scalar(conn, "SELECT COUNT(*) FROM fact_grade WHERE course_id=? AND is_pass=0", (row["course_id"],)) or 0
        row["historical_fail_rate"] = round(failed / total * 100, 1) if total else None
    return rows


def _sample_student_ids(conn: sqlite3.Connection, user: dict) -> set[str]:
    scope_sql, scope_params = _student_scope_sql(user, conn, "s")
    rows = dbm.query(conn, f"""
        SELECT a.student_id,
               MAX(CASE a.level WHEN '严重' THEN 3 WHEN '警告' THEN 2 ELSE 1 END) AS max_level,
               COUNT(DISTINCT a.alert_id) AS alert_count,
               COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.course_id END) AS fail_courses,
               ROUND(AVG(g.gpa), 2) AS avg_gpa
        FROM fact_alert a
        JOIN dim_student s ON s.student_id=a.student_id
        LEFT JOIN fact_grade g ON g.student_id=a.student_id
        WHERE COALESCE(a.is_active,1)=1{scope_sql}
        GROUP BY a.student_id
        ORDER BY max_level DESC, fail_courses DESC, alert_count DESC, avg_gpa ASC
        LIMIT ?
    """, scope_params + [AI_SAMPLE_LIMIT])
    return {r["student_id"] for r in rows}


def _risk_level(alerts: list[dict], stats: dict) -> str:
    active = [a for a in alerts if a.get("is_active") == 1]
    if any(a.get("level") == "严重" for a in active):
        return "critical"
    if (stats.get("failed_required_courses") or 0) >= 2 or (stats.get("failed_courses") or 0) >= 3:
        return "critical"
    if any(a.get("level") == "警告" for a in active):
        return "warning"
    if (stats.get("failed_courses") or 0) > 0 or (stats.get("gpa_delta") or 0) < -0.3:
        return "warning"
    return "info" if active else "low"


def _evidence(base: dict, alerts: list[dict], stats: dict, failed: list[dict]) -> list[dict]:
    active = [a for a in alerts if a.get("is_active") == 1]
    latest = alerts[0] if alerts else {}
    evidence = [
        {"label": "当前有效预警", "value": f"{len(active)} 条", "detail": latest.get("trigger_detail") or "来自已启用预警规则", "tone": "danger" if active else "success"},
        {"label": "未通过课程", "value": f"{stats.get('failed_courses') or 0} 门", "detail": f"其中必修 {stats.get('failed_required_courses') or 0} 门", "tone": "danger" if (stats.get("failed_courses") or 0) else "success"},
        {"label": "累计成绩GPA", "value": stats.get("avg_gpa") if stats.get("avg_gpa") is not None else "暂无", "detail": _gpa_detail(stats), "tone": "warning" if (stats.get("avg_gpa") or 9) < 2.3 else "info"},
        {"label": "已获学分", "value": f"{stats.get('earned_credits') or 0}", "detail": f"未通过学分 {stats.get('failed_credits') or 0}", "tone": "info"},
    ]
    if failed:
        top = failed[0]
        rate = top.get("historical_fail_rate")
        evidence.append({
            "label": "未通过重点课程",
            "value": top["course_name"],
            "detail": f"历史未通过率 {rate}%" if rate is not None else "存在未通过记录",
            "tone": "danger" if rate and rate >= 20 else "warning",
        })
    return evidence


def _gpa_detail(stats: dict) -> str:
    delta = stats.get("gpa_delta")
    if delta is None:
        return "暂未形成连续学期趋势"
    if delta < -0.3:
        return f"较上一学期下降 {abs(delta)}"
    if delta > 0.2:
        return f"较上一学期提升 {delta}"
    return "较上一学期基本稳定"


def _reasons(base: dict, alerts: list[dict], stats: dict, failed: list[dict], enhanced: bool) -> list[str]:
    reasons: list[str] = []
    if alerts:
        a = alerts[0]
        reasons.append(f"最近一次预警为“{a.get('level')} / {a.get('type')}”，触发依据是：{a.get('trigger_detail') or '规则命中'}。")
    if (stats.get("failed_required_courses") or 0) > 0:
        reasons.append(f"该生仍有 {stats.get('failed_required_courses')} 门必修课程未通过，毕业准备和后续选课需要优先核查。")
    elif (stats.get("failed_courses") or 0) > 0:
        reasons.append(f"该生存在 {stats.get('failed_courses')} 门课程未通过，建议区分必修、选修和重修资源后处理。")
    if stats.get("gpa_delta") is not None and stats["gpa_delta"] < -0.3:
        reasons.append(f"GPA 相邻学期下降 {abs(stats['gpa_delta'])}，需要确认是否由单门关键课程、学习状态或课程负荷变化造成。")
    high_rate = [c for c in failed if c.get("historical_fail_rate") and c["historical_fail_rate"] >= 20]
    if high_rate:
        names = "、".join(c["course_name"] for c in high_rate[:2])
        reasons.append(f"未通过课程中包含历史未通过率较高课程：{names}，学生需要提前获得课程难度提醒和学习资源建议。")
    if enhanced:
        reasons.append("该对象具备较完整的证据链，研判文本在规则证据基础上进行了管理视角增强。")
    return reasons or ["当前证据未显示明显恶化，但仍建议结合最近成绩、选课和学生访谈进行常规观察。"]


def _suggestions(base: dict, alerts: list[dict], stats: dict, failed: list[dict], enhanced: bool) -> list[dict]:
    failed_names = "、".join(c["course_name"] for c in failed[:3]) or "未通过课程"
    items = [
        {
            "role": "辅导员",
            "priority": "high" if alerts or (stats.get("failed_courses") or 0) >= 2 else "medium",
            "action": "优先完成一次学业状态沟通",
            "detail": f"围绕 {failed_names}、近期学习投入和心理受挫情况进行访谈，确认是否需要持续跟踪。",
        },
        {
            "role": "班主任/导师",
            "priority": "high" if (stats.get("failed_required_courses") or 0) else "medium",
            "action": "核查课程学习路径",
            "detail": "判断未通过课程是否属于基础先修链条，必要时建议学生调整后续选课顺序。",
        },
        {
            "role": "学院",
            "priority": "high" if (stats.get("failed_required_courses") or 0) >= 2 else "medium",
            "action": "核查重修与补修资源",
            "detail": "确认相关课程近期是否有教学班、重修班或替代认定路径，避免风险延后到毕业审核阶段暴露。",
        },
    ]
    if enhanced:
        items.append({
            "role": "学生本人",
            "priority": "medium",
            "action": "制定下一学期课程优先级",
            "detail": "优先处理必修缺口和历史难度较高课程，避免同时叠加多门高风险课程。",
        })
    return items


def _next_actions(base: dict, alerts: list[dict], stats: dict, failed: list[dict]) -> list[str]:
    actions = ["查看学生完整档案中的成长轨迹、历史预警和人工干预记录。"]
    if failed:
        actions.append("核查未通过课程是否已有下学期开课、重修班或课程替代资源。")
    if alerts:
        actions.append("在预警闭环中补充本次沟通记录，并约定下一次复核时间。")
    if (stats.get("failed_required_courses") or 0) > 0:
        actions.append("将必修未通过课程纳入学院毕业准备风险清单。")
    return actions


def _student_insight(conn: sqlite3.Connection, student_id: str, user: dict, scenario: str) -> dict:
    base = _student_base(conn, student_id, user)
    alerts = _student_alerts(conn, student_id)
    stats = _student_grade_stats(conn, student_id)
    failed = _failed_courses(conn, student_id)
    enhanced = student_id in _sample_student_ids(conn, user)
    risk = _risk_level(alerts, stats)
    source = "ai_sample" if enhanced else "rule"
    latest = alerts[0] if alerts else {}
    fail_courses = stats.get("failed_courses") or 0
    required_fail = stats.get("failed_required_courses") or 0
    gpa_history = stats.get("gpa_history") or []
    comparison_changes = []
    comparison_baseline = "当前仅有单期成绩证据，不能判断GPA是否恶化或改善。"
    if len(gpa_history) >= 2 and stats.get("gpa_delta") is not None:
        previous, current = gpa_history[-2], gpa_history[-1]
        delta = float(stats["gpa_delta"])
        direction = "上升" if delta > 0 else "下降" if delta < 0 else "持平"
        comparison_changes.append(
            f"相邻学期GPA由 {previous.get('gpa')} 变为 {current.get('gpa')}，{direction} {abs(delta):.2f}。"
        )
        comparison_baseline = f"比较 {previous.get('semester_id')} 与 {current.get('semester_id')} 两个相邻学期的平均GPA。"

    if enhanced:
        summary = (
            f"{base['name']}属于需要优先跟进的复合型学业风险学生：当前预警等级为"
            f"{latest.get('level') or '关注'}，未通过课程 {fail_courses} 门，其中必修 {required_fail} 门。"
            "建议把该生放入本轮学院帮扶核查名单，先确认课程缺口和重修资源，再安排辅导员沟通。"
        )
        confidence = "高"
    else:
        summary = (
            f"{base['name']}当前研判为{RISK_LABEL[risk]}，主要依据为有效预警、未通过课程、GPA 趋势和历史课程难度。"
        )
        confidence = "中"

    return {
        "targetType": "student",
        "targetId": student_id,
        "targetName": base["name"],
        "scenario": scenario,
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": source,
        "sourceLabel": "AI辅助研判" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": confidence,
        "profile": {
            "college": base.get("college_name"),
            "major": base.get("major_name"),
            "className": base.get("class_name"),
            "grade": base.get("grade"),
        },
        "evidence": _evidence(base, alerts, stats, failed),
        "reasons": _reasons(base, alerts, stats, failed, enhanced),
        "comparison": {
            "available": bool(comparison_changes),
            "baseline": comparison_baseline,
            "changes": comparison_changes,
        },
        "suggestions": _suggestions(base, alerts, stats, failed, enhanced),
        "nextActions": _next_actions(base, alerts, stats, failed),
        "limitations": [
            "本结果用于管理研判和核查提示，不替代学校正式毕业审核、成绩认定或处分结论。",
            "原型阶段优先使用结构化数据摘要；生产环境可经学校允许后接入云端或私有化大模型。",
        ],
    }


@router.get("/insight/student/{student_id}")
def student_insight(student_id: str, scenario: str = "alert",
                    user: dict = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    return ai_ok(_student_insight(conn, student_id, user, scenario))


@router.get("/insight/alert-summary")
def alert_summary(level: Optional[str] = None, type: Optional[str] = None,
                  status: Optional[str] = None, college: Optional[str] = None,
                  user: dict = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    conds = ["COALESCE(a.is_active,1)=1"]
    params: list = []
    if level:
        conds.append("a.level=?"); params.append(level)
    if type:
        conds.append("a.type=?"); params.append(type)
    if status:
        mapped_status = WORKFLOW_BY_LABEL.get(status, status)
        conds.append("(e.workflow_status=? OR a.status=?)"); params += [mapped_status, status]
    if college:
        conds.append("c.name=?"); params.append(college)
    scope_sql, scope_params = _student_scope_sql(user, conn, "s")
    if scope_sql:
        conds.append(scope_sql.replace(" AND ", "", 1)); params += scope_params
    where = " WHERE " + " AND ".join(conds)
    aggregate = dbm.query_one(conn, f"""
        SELECT COUNT(*) AS alert_records,
               COUNT(DISTINCT a.student_id) AS student_count,
               SUM(CASE WHEN a.level='严重' THEN 1 ELSE 0 END) AS critical_records,
               SUM(CASE WHEN a.level='警告' THEN 1 ELSE 0 END) AS warning_records,
               SUM(CASE WHEN a.level='提醒' THEN 1 ELSE 0 END) AS info_records
        FROM fact_alert a
        JOIN dim_student s ON s.student_id=a.student_id
        LEFT JOIN dim_college c ON c.college_id=s.college_id
        LEFT JOIN alert_event e ON e.alert_id=a.alert_id
        {where}
    """, params) or {}
    top = dbm.query(conn, f"""
        WITH ranked AS (
            SELECT a.student_id, s.name, c.name AS college, a.level, a.type,
                   a.trigger_detail, e.workflow_status,
                   COALESCE(g.failed_courses,0) AS failed_courses,
                   g.avg_gpa,COALESCE(a.created_at,'') AS created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.student_id
                       ORDER BY CASE a.level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END,
                                COALESCE(g.failed_courses,0) DESC,COALESCE(a.created_at,'') DESC
                   ) AS student_rank
            FROM fact_alert a
            JOIN dim_student s ON s.student_id=a.student_id
            LEFT JOIN dim_college c ON c.college_id=s.college_id
            LEFT JOIN alert_event e ON e.alert_id=a.alert_id
            LEFT JOIN (
                SELECT student_id,
                       COUNT(DISTINCT CASE WHEN is_pass=0 THEN course_id END) AS failed_courses,
                       ROUND(AVG(CASE WHEN gpa IS NOT NULL THEN gpa END),2) AS avg_gpa
                FROM fact_grade GROUP BY student_id
            ) g ON g.student_id=a.student_id
            {where}
        )
        SELECT student_id,name,college,level,type,trigger_detail,workflow_status,failed_courses,avg_gpa
        FROM ranked
        WHERE student_rank=1
        ORDER BY CASE level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END,
                 failed_courses DESC,created_at DESC
        LIMIT 10
    """, params)
    total = int(aggregate.get("alert_records") or 0)
    student_count = int(aggregate.get("student_count") or 0)
    critical = int(aggregate.get("critical_records") or 0)
    warning = int(aggregate.get("warning_records") or 0)
    summary = (
        f"当前筛选范围共有 {total} 条有效预警记录，涉及 {student_count} 名学生；"
        f"其中严重 {critical} 条、警告 {warning} 条。"
        f"下方重点对象仅展示排序前 {len(top)} 名，汇总指标按完整筛选范围计算。"
    )
    return ai_ok({
        "targetType": "alertGroup",
        "targetId": "current-alert-filter",
        "targetName": "当前预警筛选范围",
        "scenario": "alert_monitor",
        "riskLevel": "critical" if critical else "warning" if warning else "info",
        "riskLabel": "高风险" if critical else "中风险" if warning else "关注",
        "riskTone": "danger" if critical else "warning" if warning else "info",
        "source": "rule",
        "sourceLabel": "规则研判兜底",
        "generatedBy": "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中",
        "evidence": [
            {"label": "预警学生", "value": f"{student_count} 人", "detail": "按完整筛选范围对学生去重", "tone": "info", "source": "fact_alert.student_id（去重，is_active=1）", "managementValue": "判断本轮需要学院和辅导员覆盖的实际学生规模，避免用预警记录人次代替学生人数。"},
            {"label": "有效预警记录", "value": f"{total} 条", "detail": "同一学生可命中多条规则", "tone": "info", "source": "fact_alert.alert_id（is_active=1）", "managementValue": "判断预警规则触发总量和复合风险规模，用于估算本轮核查工作量。"},
            {"label": "严重预警", "value": f"{critical} 条", "detail": "应优先进入人工核查", "tone": "danger" if critical else "success", "source": "fact_alert.level='严重'", "managementValue": "定位最高等级风险记录，优先安排学院确认学生是否已被关注。"},
            {"label": "警告预警", "value": f"{warning} 条", "detail": "建议按课程缺口和 GPA 变化分层处理", "tone": "warning" if warning else "success", "source": "fact_alert.level='警告'", "managementValue": "识别可能继续恶化的学生群体，安排在严重预警之后分层复核。"},
        ],
        "reasons": [
            "预警切片用于帮助管理者判断本轮应先处理哪些学生，而不是仅按列表顺序逐条查看。",
            "严重等级、未通过课程数量和 GPA 偏低是本次排序的核心依据。",
        ],
        "suggestions": [
            {"role": "教务处", "priority": "high", "action": "按学院分派核查任务", "detail": "先推动严重预警学生所在学院确认课程缺口和重修资源。"},
            {"role": "二级学院", "priority": "high", "action": "建立本周重点学生清单", "detail": "优先处理严重预警、持续预警和必修未通过课程较多的学生。"},
            {"role": "辅导员", "priority": "medium", "action": "完成学生访谈并保留跟进证据", "detail": "在学校授权的预警业务流程中记录访谈结论，并同步呈现在学生档案中，便于比较历史预警变化。"},
        ],
        "nextActions": [
            "打开前 3 名重点学生的 AI 研判，确认是否进入本轮帮扶名单。",
            "对同一课程集中触发的学生，进一步查看课程质量与重修资源。",
        ],
        "focusItems": top,
        "limitations": ["当前统计基于已接入预警和成绩数据，未包含心理、出勤等暂未接入数据。"],
    })


@router.get("/insight/graduation-readiness/student/{student_id}")
def graduation_readiness_student_insight(student_id: str,
                                         user: dict = Depends(get_current_user),
                                         conn: sqlite3.Connection = Depends(get_v2_db)):
    student = _v2_student_access(conn, student_id, user)
    rows = dbm.query(conn, """
        SELECT x.course_id,COALESCE(c.name,x.course_id) course_name,x.suggested_term,
               x.completion_status,x.effective_score,pc.credits required_credits,
               (SELECT COUNT(DISTINCT l.lesson_id) FROM teaching_lesson l WHERE l.course_id=x.course_id) lesson_count,
               (SELECT COUNT(DISTINCT lt.staff_id) FROM teaching_lesson l
                  LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id WHERE l.course_id=x.course_id) teacher_count,
               (SELECT COUNT(DISTINCT scs.substitution_id) FROM student_course_substitution scs
                  WHERE scs.student_id=x.student_id AND scs.original_course_id=x.course_id) substitution_count
        FROM student_plan_course_status x
        LEFT JOIN dim_course c ON c.course_id=x.course_id
        LEFT JOIN curriculum_plan_course pc ON pc.plan_course_id=x.plan_course_id
        WHERE x.student_id=? AND x.rule_version='growth-v1' AND x.requirement_type='必修'
          AND (x.completion_status='failed' OR (x.completion_status IN ('not_completed','unknown') AND x.is_overdue=1))
        ORDER BY CASE WHEN x.completion_status='failed' THEN 0 ELSE 1 END,x.suggested_term,x.course_id
    """, (student_id,))
    failed = [r for r in rows if r["completion_status"] == "failed"]
    candidates = [r for r in rows if r["completion_status"] != "failed"]
    no_offering = [r for r in rows if not r["lesson_count"]]
    risk = "critical" if failed else "warning" if candidates else "low"
    enhanced = len(failed) >= 2 or (failed and no_offering)
    top_names = "、".join(r["course_name"] for r in rows[:3]) or "暂无明确课程缺口"
    summary = (
        f"{student['display_name']}当前毕业准备核查重点为：{top_names}。"
        f"其中明确未通过 {len(failed)} 门，到期缺结果候选 {len(candidates)} 门。"
        "建议先核查必修未通过课程的重修、补考、替代认定和近期教学班供给。"
    )
    if failed:
        intervention = {
            "status": "action_required", "label": "明确需处理", "priority": "high",
            "priorityReasons": [f"已有 {len(failed)} 门必修课未通过成绩，可直接进入课程补修与资源保障核查。"],
        }
        primary_action = {
            "role": "二级学院", "action": "确认必修未通过课程处理路径",
            "detail": "逐门确认补考、重修、课程替代及下一教学周期的开课资源，并形成学生可执行的课程处理清单。",
            "timing": "下一轮选课或开课计划确定前", "expectedResult": "形成已确认的课程处理路径、时间节点和责任人员",
        }
        consequence = "若未在下一轮选课或开课计划确定前完成核查，学生可能错过补修窗口，课程资源问题也可能延后到毕业审核阶段才暴露。"
    elif candidates:
        intervention = {
            "status": "verification_required", "label": "优先核验", "priority": "medium",
            "priorityReasons": [f"有 {len(candidates)} 门到期缺结果课程，但尚不能区分未选课、免修认定、课程替代或数据缺失。"],
        }
        primary_action = {
            "role": "二级学院", "action": "先核验课程完成证据",
            "detail": "核对选课、成绩、免修认定、课程替代和个人方案适用范围，证据确认前不把候选课程认定为学生缺修。",
            "timing": "本轮毕业准备名单形成前", "expectedResult": "把数据候选拆分为真实课程缺口与待补数据记录",
        }
        consequence = "若直接把缺结果候选当作学生缺修，可能造成误提醒和无效管理；若不核验，也可能遗漏真实课程缺口。"
    else:
        intervention = {
            "status": "no_intervention", "label": "当前无需AI介入", "priority": "low",
            "priorityReasons": ["当前未发现必修课明确未通过或到期缺结果候选。"],
        }
        primary_action = {
            "role": "二级学院", "action": "维持常规毕业准备观察",
            "detail": "在后续成绩发布、课程认定或培养方案调整后重新计算即可。",
            "timing": "下一数据更新周期", "expectedResult": "避免对无明确问题学生增加不必要核查",
        }
        consequence = "当前无需新增管理动作。"
    return ai_ok({
        "targetType": "graduationStudent",
        "targetId": student_id,
        "targetName": student["display_name"],
        "scenario": "graduation_readiness",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if enhanced else "rule",
        "sourceLabel": "AI辅助研判" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "intervention": intervention,
        "decision": {
            "headline": summary,
            "whyNow": intervention["priorityReasons"],
            "impactScope": f"明确未通过 {len(failed)} 门；到期缺结果候选 {len(candidates)} 门；无开课证据 {len(no_offering)} 门",
            "consequence": consequence,
        },
        "comparison": {
            "available": False,
            "baseline": "本场景依据当前培养方案绑定、课程完成状态与历史开课证据核查，不把单次快照解释为趋势。",
            "changes": [],
        },
        "primaryAction": primary_action,
        "confidence": "高" if rows else "中",
        "profile": {"college": student.get("organization_id"), "major": student.get("major_name"),
                    "className": student.get("class_code"), "grade": student.get("entry_grade")},
        "evidence": [
            {"label": "明确未通过", "value": f"{len(failed)} 门", "detail": "已发布成绩中存在必修课未通过记录", "tone": "danger" if failed else "success"},
            {"label": "缺结果候选", "value": f"{len(candidates)} 门", "detail": "到建议学期仍缺完成证据，需先核验选课与认定", "tone": "warning" if candidates else "success"},
            {"label": "无开课证据", "value": f"{len(no_offering)} 门", "detail": "历史教学任务中暂未发现该课程教学班", "tone": "danger" if no_offering else "info"},
            {"label": "培养方案", "value": student.get("plan_name") or "未绑定", "detail": student.get("version") or "当前学生绑定方案", "tone": "info"},
        ],
        "reasons": [
            "毕业准备核查关注的是学生是否存在必修课程完成证据缺口，不直接等同毕业审核结论。",
            "明确未通过课程可优先进入重修、补考、替代认定和课程保障核查。",
            "缺结果候选必须先核验选课、免修认定、课程替代和个人方案适用范围，不能直接认定学生缺修。",
        ],
        "suggestions": [
            {"role": "学院", "priority": "high" if failed else "medium", "action": "确认学生课程缺口清单", "detail": "逐门核查必修未通过课程是否有近期补修、重修或替代认定路径。"},
            {"role": "教务处", "priority": "high" if no_offering else "medium", "action": "核查课程供给和保障资源", "detail": "对无开课证据或影响学生较多的课程，确认下学期开课计划、教师容量和教学班资源。"},
            {"role": "辅导员/班主任", "priority": "medium", "action": "提醒学生制定毕业准备计划", "detail": "让学生明确优先处理哪些必修课程，避免毕业审核前集中暴露问题。"},
        ],
        "nextActions": [
            "查看核查证据弹窗中的明确未通过课程和缺结果候选课程。",
            "对无开课证据课程进入课程保障证据核查。",
            "必要时把学生加入学院毕业准备重点跟踪名单。",
        ],
        "limitations": ["本研判仅用于毕业准备管理核查，不替代学校正式毕业资格审核。"],
    })


@router.get("/insight/graduation-readiness/course/{course_id}")
def graduation_readiness_course_insight(course_id: str,
                                        user: dict = Depends(get_current_user),
                                        conn: sqlite3.Connection = Depends(get_v2_db)):
    scope, scope_params = _v2_student_scope(user, conn, "s")
    scope_sql = f" AND {scope}" if scope else ""
    course = dbm.query_one(conn, "SELECT course_id,name,category,nature,organization_id FROM dim_course WHERE course_id=?", (course_id,)) or {"course_id": course_id, "name": course_id}
    affected = dbm.query_one(conn, f"""
        SELECT COUNT(DISTINCT CASE WHEN x.requirement_type='必修' AND x.completion_status='failed' THEN x.student_id END) failed_students,
               COUNT(DISTINCT CASE WHEN x.requirement_type='必修' AND x.completion_status IN ('not_completed','unknown') AND x.is_overdue=1 THEN x.student_id END) candidate_students,
               COUNT(DISTINCT s.major_code) major_count
        FROM student_plan_course_status x
        JOIN dim_student s ON s.student_id=x.student_id
        WHERE x.course_id=? AND x.rule_version='growth-v1'{scope_sql}
    """, tuple([course_id] + scope_params)) or {}
    supply = dbm.query_one(conn, """
        SELECT COUNT(DISTINCT l.lesson_id) lesson_count,
               COUNT(DISTINCT lt.staff_id) teacher_count,
               SUM(COALESCE(l.capacity,0)) capacity,
               SUM(COALESCE(l.enrolled,0)) enrolled,
               GROUP_CONCAT(DISTINCT l.semester_id) semesters
        FROM teaching_lesson l
        LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        WHERE l.course_id=?
    """, (course_id,)) or {}
    substitutions = dbm.scalar(conn, """
        SELECT COUNT(DISTINCT substitution_id) FROM student_course_substitution
        WHERE original_course_id=? OR substitute_course_id=?
    """, (course_id, course_id)) or 0
    failed = affected.get("failed_students") or 0
    candidates = affected.get("candidate_students") or 0
    lesson_count = supply.get("lesson_count") or 0
    teacher_count = supply.get("teacher_count") or 0
    risk = "critical" if failed >= 10 or not lesson_count else "warning" if failed or candidates else "info"
    reasons = []
    if failed:
        reasons.append(f"该课程当前关联 {failed} 名明确未通过学生，是毕业准备核查中的可行动问题。")
    if candidates:
        reasons.append(f"另有 {candidates} 名学生属于缺结果候选，需要先核验选课、认定或方案适用范围。")
    if not lesson_count:
        reasons.append("当前历史教学任务中未发现教学班证据，需优先确认是否存在课程代码映射、替代课程或未来开课计划。")
    elif teacher_count <= 1:
        reasons.append("历史教学证据中教师覆盖较少，若下期开重修或补修班，需要提前确认师资容量。")
    if substitutions:
        reasons.append(f"已发现 {substitutions} 条课程替代关系，可作为学生个体核查时的重要证据。")
    if risk == "critical":
        intervention = {
            "status": "action_required", "label": "课程保障重点", "priority": "high",
            "priorityReasons": reasons[:3] or ["受影响学生规模或课程供给证据达到优先保障阈值。"],
        }
        primary_action = {
            "role": "教务处", "action": "确认该课程下一周期保障方案",
            "detail": "结合受影响学生名单、未来开课计划、教师容量和课程替代关系，确定增开教学班、调整容量或提供替代资源。",
            "timing": "下一教学周期排课资源锁定前", "expectedResult": "形成课程是否保障、保障方式和覆盖学生范围的明确结论",
        }
        consequence = "若未在排课资源锁定前形成保障方案，明确未通过学生可能缺少可执行的补修路径，并在毕业准备后期集中形成资源冲突。"
    elif failed or candidates:
        intervention = {
            "status": "watch", "label": "核查后观察", "priority": "medium",
            "priorityReasons": reasons[:3] or ["存在受影响学生，但当前供给证据尚未达到优先调整资源阈值。"],
        }
        primary_action = {
            "role": "二级学院", "action": "核实受影响学生与现有供给是否匹配",
            "detail": "先区分明确未通过和缺结果候选，再判断现有教学班、教师和替代资源是否足以覆盖真实需求。",
            "timing": "下一轮课程保障清单形成前", "expectedResult": "确认是否需要升级为校级课程保障事项",
        }
        consequence = "若不区分真实缺口和数据候选，可能高估课程资源需求；若忽略明确未通过学生，则可能低估补修需求。"
    else:
        intervention = {
            "status": "no_intervention", "label": "当前无需AI介入", "priority": "low",
            "priorityReasons": ["当前未发现该课程关联的明确未通过学生或到期缺结果候选。"],
        }
        primary_action = {
            "role": "教务处", "action": "维持常规课程供给观察", "detail": "后续数据更新后重新计算。",
            "timing": "下一数据更新周期", "expectedResult": "避免对常规课程增加不必要的保障核查",
        }
        consequence = "当前无需新增课程保障动作。"
    return ai_ok({
        "targetType": "graduationCourse",
        "targetId": course_id,
        "targetName": course.get("name") or course_id,
        "scenario": "graduation_course_supply",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk == "critical" else "rule",
        "sourceLabel": "AI辅助研判" if risk == "critical" else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk == "critical" else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": f"{course.get('name') or course_id}建议作为毕业准备课程保障对象核查：明确未通过 {failed} 人，缺结果候选 {candidates} 人，涉及 {affected.get('major_count') or 0} 个专业。",
        "intervention": intervention,
        "decision": {
            "headline": f"{course.get('name') or course_id}：{'应在排课资源锁定前形成课程保障结论' if risk == 'critical' else '先核实学生真实需求与现有供给是否匹配'}。",
            "whyNow": intervention["priorityReasons"],
            "impactScope": f"明确未通过 {failed} 人；缺结果候选 {candidates} 人；涉及 {affected.get('major_count') or 0} 个专业；历史教学班 {lesson_count} 个",
            "consequence": consequence,
        },
        "comparison": {
            "available": False,
            "baseline": "当前依据学生课程状态与历史教学任务快照判断保障优先级；未来开课计划尚未接入，不能判断供给变化趋势。",
            "changes": [],
        },
        "primaryAction": primary_action,
        "confidence": "高" if failed or candidates else "中",
        "profile": {"college": course.get("organization_id"), "major": f"{affected.get('major_count') or 0} 个专业"},
        "evidence": [
            {"label": "明确未通过学生", "value": f"{failed} 人", "detail": "可优先进入重修/补考/替代路径核查", "tone": "danger" if failed else "success"},
            {"label": "缺结果候选", "value": f"{candidates} 人", "detail": "需先核验选课与认定数据", "tone": "warning" if candidates else "success"},
            {"label": "历史教学班", "value": f"{lesson_count} 个", "detail": f"教师 {teacher_count} 人；容量 {supply.get('capacity') or 0}", "tone": "danger" if not lesson_count else "info"},
            {"label": "替代关系", "value": f"{substitutions} 条", "detail": "可用于学生个体课程替代核查", "tone": "info"},
        ],
        "reasons": reasons or ["当前未显示明显课程保障风险，可作为常规观察对象。"],
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "确认课程供给策略", "detail": "结合下学期开课计划、教师容量和重修资源，判断是否需要保障该课程。"},
            {"role": "二级学院", "priority": "high" if failed else "medium", "action": "核查受影响学生名单", "detail": "区分明确未通过和缺结果候选，避免把数据候选直接作为学生问题处理。"},
            {"role": "排课/教学运行人员", "priority": "medium", "action": "评估补修班或替代资源", "detail": "若受影响学生集中且教师容量不足，应提前准备课程资源方案。"},
        ],
        "nextActions": [
            "打开课程保障证据，查看历史教学班、教师、容量和替代关系。",
            "查看受影响学生名单，优先处理明确未通过学生。",
            "如无开课证据，核查课程代码映射和培养方案课程替代规则。",
        ],
        "limitations": ["当前未接入未来开课计划和重修班正式安排，课程保障建议需结合教务排课计划人工确认。"],
    })


@router.get("/insight/operation/course-offering/{course_id}")
def operation_course_offering_insight(course_id: str, semester: str = "2023-2024-1",
                                      user: dict = Depends(get_current_user),
                                      conn: sqlite3.Connection = Depends(get_v2_db)):
    course = dbm.query_one(conn, """
        SELECT course_id,name,category,nature,organization_id
        FROM dim_course WHERE course_id=?
    """, (course_id,)) or {"course_id": course_id, "name": course_id}
    offering = dbm.query_one(conn, """
        SELECT a.*,c.name course_name,c.category,c.nature,c.organization_id
        FROM agg_course_offering a
        LEFT JOIN dim_course c ON c.course_id=a.course_id
        WHERE a.semester_id=? AND a.course_id=?
    """, (semester, course_id))
    if not offering:
        offering = dbm.query_one(conn, """
            SELECT ? semester_id,l.course_id,COUNT(DISTINCT l.lesson_id) lesson_count,
                   COUNT(DISTINCT lt.staff_id) teacher_count,
                   SUM(COALESCE(l.capacity,0)) capacity,
                   SUM(COALESCE(l.enrolled,0)) enrolled,
                   COALESCE(MAX(c.name),MAX(l.course_name),l.course_id) course_name,
                   MAX(c.category) category,MAX(c.nature) nature,MAX(c.organization_id) organization_id
            FROM teaching_lesson l
            LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
            LEFT JOIN dim_course c ON c.course_id=l.course_id
            WHERE l.semester_id=? AND l.course_id=?
            GROUP BY l.course_id
        """, (semester, semester, course_id))
    if not offering:
        raise ApiError("暂无该课程开课供给数据", code=404, status_code=404)

    raw_metrics = dbm.query_one(conn, """
        SELECT r.lesson_count,r.capacity,r.enrolled,COALESCE(t.teacher_count,0) teacher_count
        FROM (
          SELECT COUNT(DISTINCT lesson_id) lesson_count,
                 SUM(COALESCE(capacity,0)) capacity,
                 SUM(COALESCE(enrolled,0)) enrolled
          FROM teaching_lesson
          WHERE semester_id=? AND course_id=?
        ) r
        CROSS JOIN (
          SELECT COUNT(DISTINCT lt.staff_id) teacher_count
          FROM teaching_lesson l
          LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
          WHERE l.semester_id=? AND l.course_id=?
        ) t
    """, (semester, course_id, semester, course_id))
    if raw_metrics and raw_metrics.get("lesson_count"):
        offering["lesson_count"] = raw_metrics.get("lesson_count") or 0
        offering["teacher_count"] = raw_metrics.get("teacher_count") or 0
        offering["capacity"] = raw_metrics.get("capacity") or 0
        offering["enrolled"] = raw_metrics.get("enrolled") or 0

    lesson_count = offering.get("lesson_count") or 0
    teacher_count = offering.get("teacher_count") or 0
    enrolled = offering.get("enrolled") or 0
    capacity = offering.get("capacity") or 0
    avg_size = round(enrolled / lesson_count, 1) if lesson_count else 0
    fill_rate = round(enrolled / capacity * 100, 1) if capacity else None
    schedule_cells = dbm.query(conn, """
        SELECT m.weekday,
               CASE WHEN m.period_start<=4 THEN '上午'
                    WHEN m.period_start<=8 THEN '下午' ELSE '晚上' END day_part,
               COUNT(DISTINCT m.meeting_id) meeting_count,
               COUNT(DISTINCT l.lesson_id) lesson_count
        FROM course_meeting m
        JOIN teaching_lesson l ON l.lesson_id=m.lesson_id
        WHERE l.semester_id=? AND l.course_id=?
        GROUP BY m.weekday,CASE WHEN m.period_start<=4 THEN '上午'
                    WHEN m.period_start<=8 THEN '下午' ELSE '晚上' END
        ORDER BY meeting_count DESC
    """, (semester, course_id))
    meeting_total = sum((r.get("meeting_count") or 0) for r in schedule_cells)
    top_cell = schedule_cells[0] if schedule_cells else {}
    evening = sum((r.get("meeting_count") or 0) for r in schedule_cells if r.get("day_part") == "晚上")
    evening_share = round(evening / meeting_total * 100, 1) if meeting_total else 0
    teacher_rows = dbm.query(conn, """
        SELECT COALESCE(s.display_name,lt.staff_id) teacher_name,lt.staff_id,
               COUNT(DISTINCT l.lesson_id) lesson_count,
               SUM(COALESCE(l.enrolled,0)) enrolled
        FROM teaching_lesson l
        LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id
        WHERE l.semester_id=? AND l.course_id=?
        GROUP BY lt.staff_id,COALESCE(s.display_name,lt.staff_id)
        ORDER BY lesson_count DESC,enrolled DESC
        LIMIT 5
    """, (semester, course_id))
    top_teacher = teacher_rows[0] if teacher_rows else {}

    attention: list[str] = []
    if avg_size >= 120:
        attention.append(f"平均班额 {avg_size} 人，已达到超大班核查区间")
    elif avg_size >= 80:
        attention.append(f"平均班额 {avg_size} 人，建议核查是否需要拆班或增加教学班")
    if teacher_count <= 1 and lesson_count >= 3:
        attention.append(f"{lesson_count} 个教学班主要由单一教师覆盖，需要核查教师连续授课和替补风险")
    if lesson_count == 1 and enrolled >= 80:
        attention.append("单班集中供给，若学生来源跨学院/跨专业，排课冲突和容量风险会被放大")
    if evening_share >= 30:
        attention.append(f"晚上时段占比 {evening_share}%，需要确认是否为课程特性或资源紧张导致")
    risk = "critical" if avg_size >= 120 or (teacher_count <= 1 and lesson_count >= 3) or (lesson_count == 1 and enrolled >= 120) else "warning" if attention else "info"
    enhanced = risk == "critical" or (avg_size >= 80 and teacher_count <= 2)
    summary = (
        f"{offering.get('course_name') or course.get('name') or course_id}在 {semester} 学期共有 {lesson_count} 个教学班、"
        f"{teacher_count} 名教师、{enrolled} 人次选课，平均班额 {avg_size} 人。"
        + ("建议作为本轮排课供给优化的优先核查课程。" if attention else "当前未发现明显供给压力，可作为常规观察对象。")
    )
    return ai_ok({
        "targetType": "operationCourseOffering",
        "targetId": course_id,
        "targetName": offering.get("course_name") or course.get("name") or course_id,
        "scenario": "operation_course_offering",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if enhanced else "rule",
        "sourceLabel": "AI辅助研判" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "高" if lesson_count and meeting_total else "中",
        "profile": {"college": offering.get("organization_id") or course.get("organization_id"),
                    "major": offering.get("category") or course.get("category"),
                    "semester": semester},
        "evidence": [
            {"label": "教学班", "value": f"{lesson_count} 个", "detail": "来自真实教学任务/开课聚合数据", "tone": "info"},
            {"label": "平均班额", "value": f"{avg_size} 人", "detail": "选课人次 ÷ 教学班数", "tone": "danger" if avg_size >= 120 else "warning" if avg_size >= 80 else "success"},
            {"label": "教师覆盖", "value": f"{teacher_count} 人", "detail": f"重点教师：{top_teacher.get('teacher_name') or '暂无'}", "tone": "danger" if teacher_count <= 1 and lesson_count >= 3 else "info"},
            {"label": "容量使用", "value": f"{fill_rate}%" if fill_rate is not None else "待核验", "detail": f"容量 {capacity}；选课 {enrolled}", "tone": "warning" if fill_rate and fill_rate >= 95 else "info"},
            {"label": "高频时段", "value": f"周{top_cell.get('weekday')} {top_cell.get('day_part')}" if top_cell else "暂无", "detail": f"晚上占比 {evening_share}%", "tone": "warning" if evening_share >= 30 else "info"},
        ],
        "reasons": attention or [
            "当前课程供给规模、班额、教师覆盖和时段分布未触发明显风险阈值，建议纳入常规运行观察。",
            "如果该课程属于体育、思政、数学、英语等重点公共课，仍建议结合学院需求和资源约束做专项核查。",
        ],
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "核查课程供给策略", "detail": "确认是否需要拆班、增开教学班、调整容量或提前协调跨学院公共课资源。"},
            {"role": "二级学院", "priority": "medium", "action": "确认学生修读需求", "detail": "结合年级、专业和培养方案要求，判断该课程是否存在集中修读或补修需求。"},
            {"role": "排课人员", "priority": "high" if evening_share >= 30 or avg_size >= 120 else "medium", "action": "优化时段与教师安排", "detail": "重点核查高频时段、晚上时段、单教师连续覆盖和教室容量是否会影响教学运行体验。"},
        ],
        "nextActions": [
            "查看完整课程清单中同类课程的班额和教师覆盖情况，判断是否为个别课程异常。",
            "对平均班额偏高课程，核查是否具备拆班、增加教师或调整容量的现实条件。",
            "对单教师多班覆盖课程，提前准备替补教师或课程团队保障方案。",
        ],
        "limitations": [
            "当前研判基于已接入教学任务、排课时段和教师覆盖数据，尚未纳入未来开课计划审批结果。",
            "班额阈值用于管理核查提示，不直接评价课程质量或教师教学效果。",
        ],
    })


@router.get("/insight/operation/classroom-occupancy")
def operation_classroom_occupancy_insight(semester: Optional[str] = None,
                                          building: Optional[str] = None,
                                          include_evening: bool = True,
                                          user: dict = Depends(get_current_user),
                                          conn: sqlite3.Connection = Depends(get_db)):
    if not dbm.scalar(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='fact_room_occupancy'"):
        raise ApiError("暂无实际教室占用数据", code=404, status_code=404)
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_room_occupancy")
    fact_conds, params = ["o.semester_id=?"], [sem]
    if building:
        fact_conds.append("o.building_name=?")
        params.append(building)
    where = " AND ".join(fact_conds)
    period_filter = "" if include_evening else " AND p.period_index<=8"
    summary = dbm.query_one(conn, f"""
        SELECT COUNT(DISTINCT o.occupancy_id) occupancyRecords,
               COUNT(DISTINCT o.room_name) observedRooms,
               COUNT(DISTINCT o.activity_date) observedDates,
               COUNT(DISTINCT CASE WHEN o.overlap_count>0 THEN o.occupancy_id END) overlapRecords,
               COUNT(DISTINCT CASE WHEN o.building_mapping_status='pending' THEN o.occupancy_id END) pendingMappingRecords,
               COUNT(DISTINCT CASE WHEN o.is_evening=1 THEN o.occupancy_id END) eveningRecords
        FROM fact_room_occupancy o
        WHERE {where}
    """, tuple(params)) or {}
    heat_rows = dbm.query(conn, f"""
        SELECT o.weekday,p.period_index,
               COUNT(DISTINCT o.room_name||'|'||o.activity_date) occupiedRoomDays
        FROM fact_room_occupancy o
        JOIN fact_room_occupancy_period p ON p.occupancy_id=o.occupancy_id
        WHERE {where}{period_filter}
        GROUP BY o.weekday,p.period_index
        ORDER BY occupiedRoomDays DESC
        LIMIT 5
    """, tuple(params))
    day_counts = {r["weekday"]: r["days"] for r in dbm.query(conn, """
        SELECT weekday,COUNT(DISTINCT activity_date) days
        FROM fact_room_occupancy
        WHERE semester_id=?
        GROUP BY weekday
    """, (sem,))}
    observed_rooms = summary.get("observedRooms") or 0
    for row in heat_rows:
        opportunities = observed_rooms * day_counts.get(row["weekday"], 0)
        row["observedUtilizationPct"] = round(row["occupiedRoomDays"] * 100 / opportunities, 1) if opportunities else 0
    buildings = dbm.query(conn, f"""
        SELECT COALESCE(o.building_name,'待映射') name,
               COUNT(DISTINCT o.room_name) observedRooms,
               COUNT(DISTINCT o.activity_date) observedDates,
               COUNT(DISTINCT o.occupancy_id) occupancyRecords,
               COUNT(DISTINCT o.room_name||'|'||o.activity_date||'|'||p.period_index) occupiedRoomSlots
        FROM fact_room_occupancy o
        LEFT JOIN fact_room_occupancy_period p ON p.occupancy_id=o.occupancy_id
        WHERE {where}{period_filter}
        GROUP BY COALESCE(o.building_name,'待映射')
        ORDER BY occupancyRecords DESC
        LIMIT 8
    """, tuple(params))
    period_count = 12 if include_evening else 8
    for row in buildings:
        denominator = (row.get("observedRooms") or 0) * (row.get("observedDates") or 0) * period_count
        row["observedLoadPct"] = round((row.get("occupiedRoomSlots") or 0) * 100 / denominator, 1) if denominator else 0
    top_building = buildings[0] if buildings else {}
    peak = heat_rows[0] if heat_rows else {}
    activity_rows = dbm.query(conn, f"""
        SELECT o.activity_type type,COUNT(DISTINCT o.occupancy_id) records
        FROM fact_room_occupancy o
        WHERE {where}
        GROUP BY o.activity_type
        ORDER BY records DESC
        LIMIT 4
    """, tuple(params))
    evening_records = summary.get("eveningRecords") or 0
    occupancy_records = summary.get("occupancyRecords") or 0
    evening_share = round(evening_records * 100 / occupancy_records, 1) if occupancy_records else 0
    top_load = top_building.get("observedLoadPct") or 0
    overlap = summary.get("overlapRecords") or 0
    pending_mapping = summary.get("pendingMappingRecords") or 0
    risk = "critical" if top_load >= 50 or overlap >= 100 or pending_mapping >= 100 else "warning" if top_load >= 30 or evening_share >= 15 or overlap else "info"
    reasons: list[str] = []
    if top_building:
        reasons.append(f"{top_building['name']} 的观察负荷最高，为 {top_load}%，应优先核查是否存在时段集中或活动集中占用。")
    if peak:
        reasons.append(f"最高占用时段出现在周{peak.get('weekday')}第 {peak.get('period_index')} 节，观察占用强度为 {peak.get('observedUtilizationPct')}%。")
    if evening_share:
        reasons.append(f"晚间占用记录占 {evening_share}%，建议结合“是否包含晚间”开关比较日间与晚间资源压力。")
    if overlap:
        reasons.append(f"存在 {overlap} 条时段重叠记录，应作为源数据核查线索，避免误判真实资源紧张。")
    if pending_mapping:
        reasons.append(f"存在 {pending_mapping} 条楼宇待映射记录，需先治理教室名称/楼宇映射后再用于正式资源决策。")
    target_name = f"{building}教室占用" if building else "全校教室占用"
    summary_text = (
        f"{target_name}在 {sem} 学期共观察到 {occupancy_records} 条实际占用记录，"
        f"覆盖 {summary.get('observedRooms') or 0} 间已观察教室、{summary.get('observedDates') or 0} 个日期。"
        + (f" 当前最高负荷楼宇为 {top_building.get('name')}，观察负荷 {top_load}%。" if top_building else "")
    )
    return ai_ok({
        "targetType": "operationClassroomOccupancy",
        "targetId": building or "all-buildings",
        "targetName": target_name,
        "scenario": "operation_classroom_occupancy",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI辅助研判" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary_text,
        "confidence": "高" if occupancy_records else "中",
        "profile": {"college": "教学运行", "major": "教室资源", "semester": sem},
        "evidence": [
            {"label": "实际占用记录", "value": f"{occupancy_records} 条", "detail": "课程、考试、自习及其他活动占用事件", "tone": "info"},
            {"label": "已观察教室", "value": f"{summary.get('observedRooms') or 0} 间", "detail": "不是学校正式可用教室总数", "tone": "info"},
            {"label": "最高楼宇负荷", "value": f"{top_load}%", "detail": top_building.get("name") or "暂无楼宇数据", "tone": "danger" if top_load >= 50 else "warning" if top_load >= 30 else "success"},
            {"label": "晚间占用", "value": f"{evening_records} 条", "detail": f"占全部记录 {evening_share}%", "tone": "warning" if evening_share >= 15 else "info"},
            {"label": "待核查记录", "value": f"{overlap + pending_mapping} 条", "detail": f"重叠 {overlap}；楼宇待映射 {pending_mapping}", "tone": "danger" if overlap + pending_mapping >= 100 else "warning" if overlap + pending_mapping else "success"},
        ],
        "reasons": reasons or ["当前筛选范围未发现明显教室占用压力，可作为常规运行观察对象。"],
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "识别资源压力楼宇与高峰时段", "detail": "优先查看高负荷楼宇、高峰节次和晚间占用，判断是否需要调整排课策略或开放更多资源。"},
            {"role": "排课人员", "priority": "high" if top_load >= 50 else "medium", "action": "优化楼宇与时段分配", "detail": "对高峰节次进行课程、考试、自习等活动分层核查，避免同一楼宇在同一时段过度集中。"},
            {"role": "数据治理人员", "priority": "high" if pending_mapping or overlap else "medium", "action": "处理楼宇映射和重叠记录", "detail": "先修正待映射教室和时段重叠记录，再把结果用于正式教室资源决策。"},
        ],
        "nextActions": [
            "切换“包含晚间”开关，比较日间资源压力和晚间资源使用结构。",
            "点开最高负荷楼宇的 AI 研判，确认压力来自课程教学、考试、自习还是临时活动。",
            "对待映射和重叠记录建立源数据核查清单，避免把数据问题误判为资源问题。",
        ],
        "focusItems": {"buildings": buildings[:5], "peakSlots": heat_rows[:5], "activityTypes": activity_rows},
        "limitations": [
            "当前结果基于已接入的实际教室占用记录，不等同于全校正式教室空闲率。",
            "分母使用已观察教室和实际采集日期，生产系统应接入正式可用教室清单、座位数和占用审批全量数据。",
        ],
    })


def _schedule_reason_ai_category(reason: str) -> dict:
    text = (reason or "").strip()
    rules = [
        ("公派/会议/培训", ["会议", "培训", "出差", "公派", "外出", "公务"], "warning"),
        ("教师个人或健康", ["病", "身体", "家庭", "个人", "请假"], "warning"),
        ("考试/竞赛/活动冲突", ["考试", "竞赛", "活动", "讲座", "答辩"], "info"),
        ("教学安排调整", ["教学计划", "计划", "节假日", "调休", "补课", "实践", "实验", "实习", "课程安排", "进度"], "info"),
        ("场地/设备/资源", ["教室", "场地", "设备", "容量", "停电", "网络"], "danger"),
        ("课程冲突调整", ["课程冲突", "冲突"], "warning"),
    ]
    for category, keywords, tone in rules:
        for keyword in keywords:
            if keyword in text:
                return {"category": category, "matchedKeyword": keyword, "tone": tone}
    return {"category": "其他待核验", "matchedKeyword": "", "tone": "info"}


def _schedule_scope(college: Optional[str], user: dict, conn: sqlite3.Connection, alias: str = "s") -> tuple[str, list]:
    conds: list[str] = []
    params: list = []
    col_scope, col_params = college_data_scope(user, conn)
    if col_scope:
        conds.append(f"{alias}." + col_scope)
        params.extend(col_params)
    if college:
        conds.append(f"{alias}.college_id=?")
        params.append(college)
    return " AND ".join(conds), params


@router.get("/insight/operation/schedule-changes")
def operation_schedule_changes_insight(semester: Optional[str] = None,
                                       college: Optional[str] = None,
                                       user: dict = Depends(get_current_user),
                                       conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_schedule_change")
    scope_sql, scope_params = _schedule_scope(college, user, conn, "s")
    conds = ["s.semester_id=?"]
    params: list = [sem]
    if scope_sql:
        conds.append(scope_sql)
        params.extend(scope_params)
    where = " AND ".join(conds)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM fact_schedule_change s WHERE {where}", tuple(params)) or 0
    if not total:
        raise ApiError("暂无调停课数据", code=404, status_code=404)
    stats = dbm.query_one(conn, f"""
        SELECT COUNT(*) total,
               COUNT(CASE WHEN s.kind='调课' THEN 1 END) change_count,
               COUNT(CASE WHEN s.kind='停课' THEN 1 END) stop_count,
               COALESCE(SUM(s.affected),0) affected,
               AVG(s.auto_approved) auto_approved,
               AVG(s.review_days) avg_review_days
        FROM fact_schedule_change s WHERE {where}
    """, tuple(params)) or {}
    raw_reasons = dbm.query(conn, f"""
        SELECT s.reason,COUNT(*) count
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.reason
        ORDER BY count DESC
        LIMIT 12
    """, tuple(params))
    semantic: dict[str, dict] = {}
    for row in raw_reasons:
        classified = _schedule_reason_ai_category(row.get("reason") or "")
        item = semantic.setdefault(classified["category"], {"name": classified["category"], "count": 0, "tone": classified["tone"], "rawReasons": []})
        item["count"] += row["count"]
        item["rawReasons"].append({"text": row.get("reason") or "未填写", "count": row["count"], "matchedKeyword": classified["matchedKeyword"]})
    semantic_rows = sorted(semantic.values(), key=lambda x: -x["count"])
    top_semantic = semantic_rows[0] if semantic_rows else {}
    monthly = dbm.query(conn, f"""
        SELECT s.month,COUNT(*) count,COALESCE(SUM(s.affected),0) affected
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.month
        ORDER BY count DESC
    """, tuple(params))
    top_month = monthly[0] if monthly else {}
    teacher_rows = dbm.query(conn, f"""
        SELECT s.teacher_id,COALESCE(t.name,s.teacher_id) teacher_name,COALESCE(t.dept,'') dept,
               COUNT(*) count,COALESCE(SUM(s.affected),0) affected
        FROM fact_schedule_change s
        LEFT JOIN dim_teacher t ON t.teacher_id=s.teacher_id
        WHERE {where}
        GROUP BY s.teacher_id,COALESCE(t.name,s.teacher_id),COALESCE(t.dept,'')
        ORDER BY count DESC,affected DESC
        LIMIT 5
    """, tuple(params))
    college_name = dbm.scalar(conn, "SELECT name FROM dim_college WHERE college_id=?", (college,)) if college else None
    change_count = stats.get("change_count") or 0
    stop_count = stats.get("stop_count") or 0
    affected = stats.get("affected") or 0
    stop_share = round(stop_count * 100 / total, 1) if total else 0
    auto_rate = round((stats.get("auto_approved") or 0) * 100, 1)
    risk = "critical" if stop_share >= 25 or affected >= 3000 or (teacher_rows and teacher_rows[0]["count"] >= 8) else "warning" if total >= 50 or stop_count or (top_semantic.get("count") or 0) >= total * 0.35 else "info"
    enhanced = risk in {"critical", "warning"}
    target_name = f"{college_name}调停课" if college_name else "当前调停课切片"
    summary = (
        f"{target_name}在 {sem} 学期共有 {total} 条调停课记录，其中调课 {change_count} 次、停课 {stop_count} 次，"
        f"影响 {affected} 人次。主要原因集中在“{top_semantic.get('name') or '暂无'}”，建议优先核查高频教师、集中月份和停课占比。"
    )
    reasons = [
        f"停课占比为 {stop_share}%，停课通常比调课更需要关注教学进度补偿和学生通知到达。",
        f"院系自动审核占比约 {auto_rate}%，可用于判断是否存在大量短时长、低风险调课。",
    ]
    if top_semantic:
        reasons.append(f"原因文本经语义归类后，“{top_semantic['name']}”占 {top_semantic['count']} 条，是本切片最主要的管理解释线索。")
    if top_month:
        reasons.append(f"调停课最集中月份为 {top_month['month']} 月，共 {top_month['count']} 条，建议结合考试周、实践周或大型活动安排核查。")
    if teacher_rows:
        reasons.append(f"最高频教师为 {teacher_rows[0]['teacher_name']}，本学期 {teacher_rows[0]['count']} 条记录，建议进入教师维度核查原因是否集中。")
    return ai_ok({
        "targetType": "operationScheduleChanges",
        "targetId": college or "current-schedule-change-filter",
        "targetName": target_name,
        "scenario": "operation_schedule_changes",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if enhanced else "rule",
        "sourceLabel": "AI辅助研判" if enhanced else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if enhanced else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高" if raw_reasons else "中",
        "profile": {"college": college_name or "全校/当前权限", "major": "调停课治理", "semester": sem},
        "evidence": [
            {"label": "调停课记录", "value": f"{total} 条", "detail": f"调课 {change_count}；停课 {stop_count}", "tone": "warning" if total >= 50 else "info"},
            {"label": "影响学生", "value": f"{affected} 人次", "detail": "调停课教学班关联学生人次", "tone": "danger" if affected >= 3000 else "warning" if affected else "info"},
            {"label": "主要原因", "value": top_semantic.get("name") or "暂无", "detail": f"{top_semantic.get('count') or 0} 条记录", "tone": top_semantic.get("tone") or "info"},
            {"label": "高峰月份", "value": f"{top_month.get('month')}月" if top_month else "暂无", "detail": f"{top_month.get('count') or 0} 条记录", "tone": "warning" if top_month else "info"},
            {"label": "自动审核", "value": f"{auto_rate}%", "detail": "院系自动审核占比", "tone": "success" if auto_rate >= 70 else "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "核查调停课集中原因", "detail": "优先看停课占比、影响学生人次和高峰月份，判断是否需要优化审核规则或教学运行安排。"},
            {"role": "二级学院", "priority": "high" if teacher_rows and teacher_rows[0]["count"] >= 8 else "medium", "action": "跟进高频教师和课程", "detail": "对高频教师逐条核查原始原因文本，区分正常公务冲突、健康因素、教学安排问题和资源问题。"},
            {"role": "排课人员", "priority": "medium", "action": "调整冲突高发时段", "detail": "结合月份趋势和原因分类，提前规避会议培训、考试活动、场地设备等冲突集中期。"},
        ],
        "nextActions": [
            "打开教师调课 TOP10 中前 3 名教师的 AI 研判，确认原因是否高度集中。",
            "核查停课记录是否已有补课安排或学生通知证据。",
            "按月份查看集中波峰是否与考试、实践、会议培训或大型活动相关。",
        ],
        "focusItems": {"reasons": semantic_rows[:5], "teachers": teacher_rows, "monthly": monthly},
        "limitations": [
            "当前原型使用规则证据与AI辅助文案解释原因文本，未调用外部大模型。",
            "生产系统应接入真实调课申请、审批记录、补课安排和通知到达证据，以支持闭环治理。",
        ],
    })


@router.get("/insight/operation/schedule-changes/teacher/{teacher_id}")
def operation_schedule_teacher_insight(teacher_id: str, semester: Optional[str] = None,
                                       user: dict = Depends(get_current_user),
                                       conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM fact_schedule_change")
    scope_sql, scope_params = _schedule_scope(None, user, conn, "s")
    conds = ["s.semester_id=?", "s.teacher_id=?"]
    params: list = [sem, teacher_id]
    if scope_sql:
        conds.append(scope_sql)
        params.extend(scope_params)
    where = " AND ".join(conds)
    teacher = dbm.query_one(conn, "SELECT teacher_id,name,dept,title FROM dim_teacher WHERE teacher_id=?", (teacher_id,)) or {"teacher_id": teacher_id, "name": teacher_id}
    stats = dbm.query_one(conn, f"""
        SELECT COUNT(*) total,COUNT(CASE WHEN s.kind='停课' THEN 1 END) stop_count,
               COALESCE(SUM(s.affected),0) affected,AVG(s.review_days) avg_review_days
        FROM fact_schedule_change s WHERE {where}
    """, tuple(params)) or {}
    total = stats.get("total") or 0
    if not total:
        raise ApiError("暂无该教师调停课数据或无权访问", code=404, status_code=404)
    reasons_raw = dbm.query(conn, f"""
        SELECT s.reason,COUNT(*) count,COALESCE(SUM(s.affected),0) affected
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.reason
        ORDER BY count DESC,affected DESC
    """, tuple(params))
    reason_items = []
    for row in reasons_raw:
        classified = _schedule_reason_ai_category(row.get("reason") or "")
        reason_items.append({**row, "semanticCategory": classified["category"], "tone": classified["tone"], "matchedKeyword": classified["matchedKeyword"]})
    top = reason_items[0] if reason_items else {}
    months = dbm.query(conn, f"""
        SELECT s.month,COUNT(*) count
        FROM fact_schedule_change s
        WHERE {where}
        GROUP BY s.month
        ORDER BY count DESC
    """, tuple(params))
    stop_count = stats.get("stop_count") or 0
    affected = stats.get("affected") or 0
    risk = "critical" if total >= 8 or stop_count >= 3 or affected >= 800 else "warning" if total >= 3 or stop_count else "info"
    summary = (
        f"{teacher.get('name') or teacher_id}在 {sem} 学期共有 {total} 条调停课记录，停课 {stop_count} 条，"
        f"影响 {affected} 人次。主要原因归类为“{top.get('semanticCategory') or '暂无'}”，建议核查是否属于可提前规避的安排冲突。"
    )
    return ai_ok({
        "targetType": "operationScheduleTeacher",
        "targetId": teacher_id,
        "targetName": teacher.get("name") or teacher_id,
        "scenario": "operation_schedule_teacher",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI辅助研判" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": teacher.get("dept"), "major": teacher.get("title"), "semester": sem},
        "evidence": [
            {"label": "调停课记录", "value": f"{total} 条", "detail": f"停课 {stop_count} 条", "tone": "danger" if total >= 8 else "warning" if total >= 3 else "info"},
            {"label": "影响学生", "value": f"{affected} 人次", "detail": "该教师调停课关联教学班学生人次", "tone": "danger" if affected >= 800 else "warning" if affected else "info"},
            {"label": "主要原因", "value": top.get("semanticCategory") or "暂无", "detail": top.get("reason") or "无原始原因", "tone": top.get("tone") or "info"},
            {"label": "集中月份", "value": f"{months[0]['month']}月" if months else "暂无", "detail": f"{months[0]['count']} 条记录" if months else "无月份分布", "tone": "warning" if months and months[0]["count"] >= 3 else "info"},
        ],
        "reasons": [
            "教师维度研判用于判断调停课是否集中在少数教师、少数原因或少数月份，避免只看全校总量。",
            f"该教师最高频原始原因是“{top.get('reason') or '暂无'}”，系统将其归类为“{top.get('semanticCategory') or '暂无'}”。",
            "如果原因集中在会议培训、公务外出或场地资源，应考虑提前排课避让；如果集中在个人健康，应以支持和替补安排为主。",
        ],
        "suggestions": [
            {"role": "二级学院", "priority": "high" if risk == "critical" else "medium", "action": "与教师确认高频原因", "detail": "核查是否存在可提前预判的会议培训、实践安排、健康因素或课程资源冲突。"},
            {"role": "教务处", "priority": "medium", "action": "优化审核与补课证据", "detail": "对停课和影响学生较多的记录，确认补课安排、审批依据和学生通知是否完整。"},
            {"role": "排课人员", "priority": "medium", "action": "下一轮排课规避冲突", "detail": "将高频月份和原因作为下一轮排课优化输入，减少同类调课重复发生。"},
        ],
        "nextActions": [
            "查看教师教学档案，结合课程团队和教师负荷判断是否存在替补资源不足。",
            "抽查原始调课申请文本，确认语义分类是否准确。",
            "若停课较多，补充核查补课安排和学生通知记录。",
        ],
        "focusItems": {"reasons": reason_items[:8], "months": months},
        "limitations": ["教师调停课频次不直接等同于教学质量问题，应结合原始原因、审批依据和补课安排综合判断。"],
    })


def _teacher_scope_filter(college: Optional[str], user: dict, conn: sqlite3.Connection) -> tuple[Optional[str], Optional[str]]:
    col_scope, col_params = college_data_scope(user, conn)
    scoped_college = college
    if col_scope and not scoped_college:
        row = dbm.query_one(conn, f"SELECT college_id,name FROM dim_college WHERE {col_scope}", tuple(col_params))
        if row:
            scoped_college = row["college_id"]
    if scoped_college:
        name = dbm.scalar(conn, "SELECT name FROM dim_college WHERE college_id=?", (scoped_college,))
        if not name:
            raise ApiError("学院不存在或无权访问", code=404, status_code=404)
        return scoped_college, name
    return None, None


def _teacher_title_map(conn: sqlite3.Connection) -> dict:
    prof = {r["teacher_id"]: r["norm_title"] for r in dbm.query(conn, "SELECT teacher_id,norm_title FROM fact_teacher_profile")}
    rows = dbm.query(conn, "SELECT teacher_id,title FROM dim_teacher")
    return {r["teacher_id"]: prof.get(r["teacher_id"]) or normalize_title(r.get("title")) for r in rows}


def _teacher_load_quality_issues(conn: sqlite3.Connection, semester: str) -> dict[str, dict]:
    rows = dbm.query(conn, """
        SELECT entity_id,affected_rows,severity,status,detail,recommendation
        FROM data_quality_issue
        WHERE domain='operation' AND issue_type='teacher_lesson_overflow'
          AND semester_id=? AND status IN ('open','reviewing')
    """, (semester,))
    return {r["entity_id"]: r for r in rows}


def _teacher_load_anomaly_ids(conn: sqlite3.Connection, semester: str) -> set[str]:
    ids = set(_teacher_load_quality_issues(conn, semester).keys())
    rows = dbm.query(conn, """
        SELECT teacher_id FROM agg_teacher_load
        WHERE semester_id=? AND (COALESCE(classes,0)>200 OR COALESCE(hours,0)>1000 OR COALESCE(courses,0)>20)
    """, (semester,))
    ids.update(r["teacher_id"] for r in rows)
    return ids


def _teacher_load_rows(conn: sqlite3.Connection, semester: str, college_name: Optional[str] = None,
                       title: Optional[str] = None, include_quality_issues: bool = False) -> list[dict]:
    title_of = _teacher_title_map(conn)
    anomaly_ids = _teacher_load_anomaly_ids(conn, semester)
    rows = dbm.query(conn, """
        SELECT a.teacher_id,COALESCE(t.name,a.teacher_id) name,t.dept,t.title,
               a.hours,a.courses,a.classes
        FROM agg_teacher_load a
        LEFT JOIN dim_teacher t ON t.teacher_id=a.teacher_id
        WHERE a.semester_id=?
    """, (semester,))
    result = []
    for row in rows:
        dept = clean_dept(row.get("dept")) or "未归属"
        norm_title = title_of.get(row["teacher_id"]) or normalize_title(row.get("title"))
        if college_name and dept != college_name:
            continue
        if title and norm_title != title:
            continue
        if not include_quality_issues and row["teacher_id"] in anomaly_ids:
            continue
        item = dict(row)
        item["dept"] = dept
        item["norm_title"] = norm_title
        item["hours"] = round(item.get("hours") or 0, 1)
        item["courses"] = item.get("courses") or 0
        item["classes"] = item.get("classes") or 0
        result.append(item)
    result.sort(key=lambda x: (x["hours"], x["courses"], x["classes"]), reverse=True)
    return result


@router.get("/insight/operation/teacher-load")
def operation_teacher_load_insight(semester: Optional[str] = None,
                                   college: Optional[str] = None,
                                   title: Optional[str] = None,
                                   user: dict = Depends(get_current_user),
                                   conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM agg_teacher_load")
    college_id, college_name = _teacher_scope_filter(college, user, conn)
    anomaly_ids = _teacher_load_anomaly_ids(conn, sem)
    rows = _teacher_load_rows(conn, sem, college_name, title)
    if not rows:
        raise ApiError("暂无教师负荷数据", code=404, status_code=404)
    total = len(rows)
    sum_hours = sum(r["hours"] for r in rows)
    sum_courses = sum(r["courses"] for r in rows)
    sum_classes = sum(r["classes"] for r in rows)
    avg_hours = round(sum_hours / total, 1) if total else 0
    avg_courses = round(sum_courses / total, 1) if total else 0
    avg_classes = round(sum_classes / total, 1) if total else 0
    overloaded = [r for r in rows if r["hours"] > 280 or r["courses"] > 5]
    top = rows[0]
    title_map: dict[str, dict] = {}
    for row in rows:
        item = title_map.setdefault(row["norm_title"] or "其他", {"title": row["norm_title"] or "其他", "teachers": 0, "hours": 0.0, "courses": 0.0, "overloaded": 0})
        item["teachers"] += 1
        item["hours"] += row["hours"]
        item["courses"] += row["courses"]
        if row in overloaded:
            item["overloaded"] += 1
    title_rows = []
    for item in title_map.values():
        n = item["teachers"] or 1
        title_rows.append({**item, "avgHours": round(item["hours"] / n, 1), "avgCourses": round(item["courses"] / n, 1)})
    title_rows.sort(key=lambda x: x["avgHours"], reverse=True)
    dept_map: dict[str, dict] = {}
    for row in rows:
        item = dept_map.setdefault(row["dept"], {"dept": row["dept"], "teachers": 0, "hours": 0.0, "courses": 0.0})
        item["teachers"] += 1
        item["hours"] += row["hours"]
        item["courses"] += row["courses"]
    dept_rows = []
    for item in dept_map.values():
        n = item["teachers"] or 1
        dept_rows.append({**item, "avgHours": round(item["hours"] / n, 1), "avgCourses": round(item["courses"] / n, 1)})
    dept_rows.sort(key=lambda x: x["avgHours"], reverse=True)
    overload_share = round(len(overloaded) * 100 / total, 1) if total else 0
    risk = "critical" if len(overloaded) >= 3 or top["hours"] >= 320 or avg_hours >= 220 else "warning" if overloaded or avg_hours >= 180 else "info"
    target_name = f"{college_name}教师负荷" if college_name else "当前教师负荷切片"
    if title:
        target_name += f" · {title}"
    summary = (
        f"{target_name}在 {sem} 学期共覆盖 {total} 名授课教师，人均 {avg_hours} 学时、"
        f"{avg_courses} 门课程、{avg_classes} 个教学班。当前识别 {len(overloaded)} 名高负荷核查对象，"
        f"最高负荷教师为 {top['name']}（{top['hours']} 学时、{top['courses']} 门课）。"
    )
    reasons = [
        "教师负荷研判用于定位需要优先人工核查的对象，不直接等同于学校正式超工作量认定。",
        f"当前高负荷核查对象占 {overload_share}%，建议结合学校工作量办法、合讲拆分、减免规则和课程团队实际承担情况判断。",
    ]
    if title_rows:
        reasons.append(f"按职称看，{title_rows[0]['title']} 人均学时最高，为 {title_rows[0]['avgHours']} 学时，可作为结构性投入核查线索。")
    if dept_rows and not college_name:
        reasons.append(f"按学院看，{dept_rows[0]['dept']} 人均学时最高，为 {dept_rows[0]['avgHours']} 学时，建议核查是否存在师资结构或公共课承担压力。")
    return ai_ok({
        "targetType": "operationTeacherLoad",
        "targetId": college_id or title or "current-teacher-load-filter",
        "targetName": target_name,
        "scenario": "operation_teacher_load",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI辅助研判" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": college_name or "全校/当前权限", "major": title or "全部职称", "semester": sem},
        "evidence": [
            {"label": "授课教师", "value": f"{total} 人", "detail": "当前筛选范围内有教学负荷记录的教师", "tone": "info"},
            {"label": "人均学时", "value": f"{avg_hours}", "detail": "总学时 ÷ 授课教师数", "tone": "danger" if avg_hours >= 220 else "warning" if avg_hours >= 180 else "success"},
            {"label": "高负荷对象", "value": f"{len(overloaded)} 人", "detail": "学时>280 或课程数>5 的优先核查对象", "tone": "danger" if overloaded else "success"},
            {"label": "最高负荷教师", "value": top["name"], "detail": f"{top['hours']} 学时；{top['courses']} 门课；{top['classes']} 个班", "tone": "danger" if top["hours"] >= 320 else "warning"},
            {"label": "已排除异常", "value": f"{len(anomaly_ids)} 人", "detail": "命中教师负荷异常或数据质量问题，未计入AI真实负荷排序", "tone": "warning" if anomaly_ids else "success"},
            {"label": "最高职称层", "value": title_rows[0]["title"] if title_rows else "暂无", "detail": f"人均 {title_rows[0]['avgHours']} 学时" if title_rows else "无职称统计", "tone": "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "核查高负荷教师清单", "detail": "优先查看学时高、课程数多、教学班多且学生覆盖人次大的教师，确认是否存在工作量口径差异或拆分规则。"},
            {"role": "二级学院", "priority": "high" if overloaded else "medium", "action": "评估课程团队保障", "detail": "结合课程团队、青年教师储备、职称结构和替补教师情况，判断高负荷是否会带来教学运行风险。"},
            {"role": "排课人员", "priority": "medium", "action": "优化下一轮授课分配", "detail": "将高负荷教师、公共课承担和多班连排情况作为下一轮教学任务安排和排课优化输入。"},
        ],
        "nextActions": [
            "打开 TOP10 高负荷教师的 AI 研判，核查课程构成和学生覆盖人次。",
            "按学院和职称切换筛选，判断高负荷是个体问题还是结构性师资压力。",
            "对高负荷且课程团队薄弱的课程，进入师资保障分析核查课程团队风险。",
        ],
        "focusItems": {"topTeachers": rows[:10], "titleLoad": title_rows, "deptLoad": dept_rows[:8]},
        "limitations": ["本研判用于管理核查排序，不替代学校正式工作量核算、超工作量认定或绩效结论。"],
    })


@router.get("/insight/operation/teacher-load/teacher/{teacher_id}")
def operation_teacher_load_teacher_insight(teacher_id: str, semester: Optional[str] = None,
                                           user: dict = Depends(get_current_user),
                                           conn: sqlite3.Connection = Depends(get_db)):
    sem = semester or dbm.scalar(conn, "SELECT MAX(semester_id) FROM agg_teacher_load")
    _, scoped_college_name = _teacher_scope_filter(None, user, conn)
    teacher = dbm.query_one(conn, "SELECT teacher_id,name,dept,title FROM dim_teacher WHERE teacher_id=?", (teacher_id,))
    if not teacher:
        raise ApiError("教师不存在", code=404, status_code=404)
    teacher_dept = clean_dept(teacher.get("dept")) or "未归属"
    if scoped_college_name and teacher_dept != scoped_college_name:
        raise ApiError("无权访问该教师负荷数据", code=403, status_code=403)
    load = dbm.query_one(conn, "SELECT teacher_id,hours,courses,classes FROM agg_teacher_load WHERE semester_id=? AND teacher_id=?", (sem, teacher_id))
    if not load:
        raise ApiError("暂无该教师负荷数据", code=404, status_code=404)
    quality_issue = _teacher_load_quality_issues(conn, sem).get(teacher_id)
    heuristic_anomaly = (load.get("classes") or 0) > 200 or (load.get("hours") or 0) > 1000 or (load.get("courses") or 0) > 20
    if quality_issue or heuristic_anomaly:
        return ai_ok({
            "targetType": "operationTeacherLoadDataQuality",
            "targetId": teacher_id,
            "targetName": teacher.get("name") or teacher_id,
            "scenario": "operation_teacher_load_teacher",
            "riskLevel": "critical",
            "riskLabel": RISK_LABEL["critical"],
            "riskTone": TONE["critical"],
            "source": "rule",
            "sourceLabel": "数据质量规则拦截",
            "generatedBy": "deterministic_rule_engine",
            "generatedAt": _now(),
            "summary": f"{teacher.get('name') or teacher_id}在 {sem} 学期命中教师教学班溢出数据质量问题：当前记录显示 {load.get('hours') or 0} 学时、{load.get('courses') or 0} 门课、{load.get('classes') or 0} 个教学班。该结果不应作为真实教师负荷结论，应优先核查源系统教师映射、通识课合并和教学班生成逻辑。",
            "confidence": "高",
            "profile": {"college": teacher_dept, "major": normalize_title(teacher.get("title")), "semester": sem},
            "evidence": [
                {"label": "异常教学班", "value": f"{load.get('classes') or 0} 个", "detail": "超过原型数据质量阈值 200", "tone": "danger"},
                {"label": "异常学时", "value": f"{load.get('hours') or 0}", "detail": "不进入AI真实负荷排序", "tone": "danger"},
                {"label": "质量状态", "value": quality_issue.get("status") if quality_issue else "heuristic", "detail": quality_issue.get("detail") if quality_issue else "启发式识别为疑似异常", "tone": "warning"},
            ],
            "reasons": [
                "该教师负荷记录远超正常教学任务范围，更可能是教师映射、公共课/通识课合并或教学班明细重复导致。",
                "AI 研判已将该对象从真实高负荷排序中排除，避免把数据质量问题误判为教师工作量问题。",
            ],
            "suggestions": [
                {"role": "数据治理人员", "priority": "high", "action": "核查源数据映射", "detail": "重点检查教师编号、课程合班、通识课教学班生成和教师-教学班关联是否重复。"},
                {"role": "教务处", "priority": "high", "action": "暂缓使用该记录做工作量判断", "detail": "在源数据修复和复核关闭前，不建议将该记录用于教师负荷、绩效或排课优化结论。"},
                {"role": "二级学院", "priority": "medium", "action": "确认真实承担情况", "detail": "可通过教师本人、课程团队和教学任务书确认真实承担课程与教学班范围。"},
            ],
            "nextActions": [
                "进入教学运行数据质量清单，查看 teacher_lesson_overflow 问题状态。",
                "核查该教师在源系统中的教师编号和课程关联关系。",
                "修复源数据后重新生成教师负荷聚合并复核关闭异常。",
            ],
            "limitations": ["该结果是数据质量拦截提示，不是教师负荷管理结论。"],
        })
    courses = dbm.query(conn, """
        SELECT l.course_id,COALESCE(MAX(c.name),l.course_id) course_name,
               COUNT(DISTINCT l.lesson_id) lessons,
               ROUND(SUM(COALESCE(l.total_hours,0)),1) hours,
               SUM(COALESCE(l.enrolled,0)) studentVisits,
               ROUND(AVG(NULLIF(l.enrolled,0)),1) avgClassSize
        FROM fact_lesson l
        LEFT JOIN dim_course c ON c.course_id=l.course_id
        WHERE l.semester_id=? AND l.teacher_id=?
        GROUP BY l.course_id
        ORDER BY hours DESC,studentVisits DESC
    """, (sem, teacher_id))
    title_of = _teacher_title_map(conn)
    norm_title = title_of.get(teacher_id) or normalize_title(teacher.get("title"))
    hours = round(load.get("hours") or 0, 1)
    course_count = load.get("courses") or 0
    class_count = load.get("classes") or 0
    student_visits = sum((r.get("studentVisits") or 0) for r in courses)
    avg_class = round(student_visits / class_count, 1) if class_count else 0
    all_rows = _teacher_load_rows(conn, sem, teacher_dept)
    rank = next((i + 1 for i, r in enumerate(all_rows) if r["teacher_id"] == teacher_id), None)
    top_course = courses[0] if courses else {}
    risk = "critical" if hours > 280 or course_count > 5 or class_count >= 12 else "warning" if hours >= 180 or course_count >= 4 else "info"
    summary = (
        f"{teacher.get('name') or teacher_id}在 {sem} 学期承担 {hours} 学时、{course_count} 门课程、"
        f"{class_count} 个教学班，覆盖 {student_visits} 学生人次。"
        f"在 {teacher_dept} 当前教师负荷中排名第 {rank or '-'}，建议结合课程构成和团队保障核查。"
    )
    reasons = [
        f"该教师最高负荷课程为“{top_course.get('course_name') or '暂无'}”，对应 {top_course.get('hours') or 0} 学时、{top_course.get('lessons') or 0} 个教学班。",
        "若课程数多且教学班分散，管理重点是排课冲突、备课压力和课程团队替补能力。",
        "若学生覆盖人次高，管理重点是答疑、实验/实践支撑、助教资源和教学质量保障。",
    ]
    return ai_ok({
        "targetType": "operationTeacherLoadTeacher",
        "targetId": teacher_id,
        "targetName": teacher.get("name") or teacher_id,
        "scenario": "operation_teacher_load_teacher",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI辅助研判" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": teacher_dept, "major": norm_title, "semester": sem},
        "evidence": [
            {"label": "总学时", "value": f"{hours}", "detail": "来自教学任务学时汇总", "tone": "danger" if hours > 280 else "warning" if hours >= 180 else "success"},
            {"label": "课程/教学班", "value": f"{course_count} 门 / {class_count} 班", "detail": "课程数和教学班数共同反映备课与授课压力", "tone": "danger" if course_count > 5 or class_count >= 12 else "info"},
            {"label": "学生覆盖", "value": f"{student_visits} 人次", "detail": f"平均班额 {avg_class}", "tone": "warning" if student_visits >= 800 else "info"},
            {"label": "学院内排名", "value": f"第 {rank or '-'}", "detail": "按当前学院总学时降序", "tone": "warning" if rank and rank <= 3 else "info"},
            {"label": "重点课程", "value": top_course.get("course_name") or "暂无", "detail": f"{top_course.get('hours') or 0} 学时；{top_course.get('studentVisits') or 0} 人次", "tone": "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "二级学院", "priority": "high" if risk == "critical" else "medium", "action": "核查课程团队和替补安排", "detail": "确认高负荷课程是否有课程团队、助教或替补教师支撑，避免形成高影响单点。"},
            {"role": "教务处", "priority": "medium", "action": "核对工作量口径", "detail": "结合学校工作量办法、合讲拆分、实验实践折算和减免规则，避免仅凭原始学时下结论。"},
            {"role": "排课人员", "priority": "medium", "action": "优化排课节奏", "detail": "核查是否存在多班连排、跨校区移动或高峰时段集中，必要时调整下一轮教学任务安排。"},
        ],
        "nextActions": [
            "查看课程构成证据，确认高学时是否集中在少数课程或多个小课程。",
            "进入师资保障分析，核查相关课程团队是否存在年龄/职称结构风险。",
            "如同时存在频繁调课，结合调课 AI 研判判断是否为负荷压力的外显信号。",
        ],
        "focusItems": {"courseBreakdown": courses},
        "limitations": ["教师个人负荷研判只用于管理支持和核查排序，不直接评价教师教学质量或绩效。"],
    })


def _faculty_course_attention(row: dict) -> list[str]:
    reasons: list[str] = []
    if (row.get("teacher_count") or 0) <= 1:
        reasons.append("single_teacher")
    if (row.get("unknown_title_count") or 0) > 0:
        reasons.append("title_incomplete")
    known = (row.get("teacher_count") or 0) - (row.get("unknown_title_count") or 0)
    if known > 0 and ((row.get("professor_count") or 0) + (row.get("associate_professor_count") or 0)) == 0:
        reasons.append("no_senior_title")
    return reasons


def _faculty_reason_label(reason: str) -> str:
    return {
        "single_teacher": "当期单一教师承担",
        "title_incomplete": "职称信息不完整",
        "no_senior_title": "已知成员无教授/副教授",
    }.get(reason, reason)


def _course_raw_offering(conn: sqlite3.Connection, semester: str, course_id: str) -> dict:
    return dbm.query_one(conn, """
        SELECT COUNT(DISTINCT l.lesson_id) lesson_count,
               SUM(COALESCE(l.enrolled,0)) enrolled,
               SUM(COALESCE(l.capacity,0)) capacity,
               SUM(COALESCE(l.total_hours,0)) total_hours
        FROM teaching_lesson l
        WHERE l.semester_id=? AND l.course_id=?
    """, (semester, course_id)) or {"lesson_count": 0, "enrolled": 0, "capacity": 0, "total_hours": 0}


@router.get("/insight/faculty-resource-risk")
def faculty_resource_risk_insight(semester: str = "2023-2024-1",
                                  user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_v2_db)):
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES:
        raise ApiError("当前角色没有V2全校师资专题访问范围", code=403, status_code=403)
    rows = dbm.query(conn, f"""
        SELECT t.*,COALESCE(c.name,t.course_id) course_name,c.organization_id,
               COALESCE(o.lesson_count,0) lesson_count,COALESCE(o.enrolled,0) enrolled
        FROM agg_course_team t
        LEFT JOIN dim_course c ON c.course_id=t.course_id
        LEFT JOIN (
            SELECT course_id,COUNT(DISTINCT lesson_id) lesson_count,SUM(COALESCE(enrolled,0)) enrolled
            FROM teaching_lesson WHERE semester_id=? GROUP BY course_id
        ) o ON o.course_id=t.course_id
        WHERE t.semester_id=?
    """, (semester, semester))
    if not rows:
        raise ApiError("暂无课程团队数据", code=404, status_code=404)
    for row in rows:
        row["attention_reasons"] = _faculty_course_attention(row)
    attention = [r for r in rows if r["attention_reasons"]]
    attention.sort(key=lambda x: (
        "single_teacher" not in x["attention_reasons"],
        "title_incomplete" not in x["attention_reasons"],
        -int(x.get("enrolled") or 0),
        x["course_id"],
    ))
    single = sum(1 for r in rows if "single_teacher" in r["attention_reasons"])
    title_gap = sum(1 for r in rows if "title_incomplete" in r["attention_reasons"])
    no_senior = sum(1 for r in rows if "no_senior_title" in r["attention_reasons"])
    high_impact = [r for r in attention if (
        "single_teacher" in r["attention_reasons"] and (
            int(r.get("enrolled") or 0) >= 300
            or (int(r.get("lesson_count") or 0) >= 3 and int(r.get("enrolled") or 0) >= 100)
        )
    )]
    high_impact.sort(key=lambda x: (-int(x.get("enrolled") or 0), x.get("course_id") or ""))
    affected_enrolled = sum((r.get("enrolled") or 0) for r in high_impact[:20])
    top = high_impact[0] if high_impact else attention[0] if attention else rows[0]
    risk = "critical" if len(high_impact) >= 10 else "warning" if attention else "info"
    summary = (
        f"{semester} 学期共识别 {len(rows)} 门有真实教学任务的课程团队，{len(attention)} 门进入候选核查池；"
        f"其中 {len(high_impact)} 门属于当期单教师且同时覆盖多班或大规模学生的高影响单点。职称信息不完整 {title_gap} 门首先按主数据问题处理，"
        f"建议优先核查 {top.get('course_name') or top.get('course_id')} 等学生覆盖较大的课程。"
    )
    reasons = [
        "课程团队风险关注的是教学运行保障，不直接评价课程质量或教师个人能力。",
        "单一教师承担表示当期教学任务存在备份能力核查需求，尤其是公共课、必修课或学生覆盖人次较高课程。",
        "职称信息不完整首先是主数据治理问题，不能据此直接判断团队梯队。",
        "已知成员无高职称只作为结构核查线索，需结合课程性质、教师资历、学院培养安排和课程团队建设实际判断。",
    ]
    return ai_ok({
        "targetType": "facultyResourceRisk",
        "targetId": "faculty-resource-risk",
        "targetName": "资源与师资风险专题",
        "scenario": "faculty_resource_risk",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI辅助研判" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": "全校", "major": "课程团队保障", "semester": semester},
        "evidence": [
            {"label": "真实团队课程", "value": f"{len(rows)} 门", "detail": "有真实教学任务教师关联的去重课程", "tone": "info"},
            {"label": "候选核查课程", "value": f"{len(attention)} 门", "detail": "命中任一单教师/职称缺口/无高职称线索，仅作为候选池", "tone": "warning" if attention else "success"},
            {"label": "高影响单点", "value": f"{len(high_impact)} 门", "detail": "当期仅1名实际授课教师，且选课≥300人次，或教学班≥3且选课≥100人次", "tone": "danger" if high_impact else "success"},
            {"label": "单一教师承担", "value": f"{single} 门", "detail": "优先核查备份教师和课程团队支撑", "tone": "danger" if single else "success"},
            {"label": "职称信息不完整", "value": f"{title_gap} 门", "detail": "优先补齐人事主数据", "tone": "warning" if title_gap else "success"},
            {"label": "重点覆盖人次", "value": f"{affected_enrolled} 人次", "detail": "TOP20 核查课程的选课人次合计", "tone": "warning" if affected_enrolled else "info"},
        ],
        "reasons": reasons,
        "suggestions": [
            {"role": "教务处", "priority": "high" if risk == "critical" else "medium", "action": "建立课程团队核查清单", "detail": "优先核查单教师承担且学生覆盖人次高的课程，确认备份教师、教学资料和应急替代机制。"},
            {"role": "二级学院", "priority": "high" if single else "medium", "action": "完善课程团队梯队", "detail": "对重点课程补充课程团队成员、青年教师培养和高职称教师指导安排。"},
            {"role": "人事/数据治理", "priority": "high" if title_gap else "medium", "action": "补齐教师职称主数据", "detail": "先处理职称缺失，再进行职称结构、人才梯队和课程团队风险判断。"},
        ],
        "nextActions": [
            "打开命中多项原因的课程 AI 研判，核查是否存在高影响单点。",
            "按学院导出课程团队核查清单，交由学院确认课程负责人和备份教师。",
            "补齐职称主数据后重新计算课程团队结构风险。",
        ],
        "focusItems": {"courses": (high_impact + [r for r in attention if r not in high_impact])[:10]},
        "limitations": [
            "当前没有教师年龄数据，因此不判断年龄断层。",
            "当前结果基于一个接入学期的真实教学任务，不等同于长期师资梯队结论。",
        ],
    })


@router.get("/insight/faculty-resource-risk/course/{course_id}")
def faculty_resource_course_insight(course_id: str, semester: str = "2023-2024-1",
                                    user: dict = Depends(get_current_user),
                                    conn: sqlite3.Connection = Depends(get_v2_db)):
    if user.get("role_id") not in V2_ALL_SCOPE_ROLES:
        raise ApiError("当前角色没有V2全校师资专题访问范围", code=403, status_code=403)
    row = dbm.query_one(conn, """
        SELECT t.*,COALESCE(c.name,t.course_id) course_name,c.organization_id,c.category,c.nature
        FROM agg_course_team t
        LEFT JOIN dim_course c ON c.course_id=t.course_id
        WHERE t.semester_id=? AND t.course_id=?
    """, (semester, course_id))
    if not row:
        raise ApiError("暂无该课程团队数据", code=404, status_code=404)
    raw = _course_raw_offering(conn, semester, course_id)
    members = dbm.query(conn, """
        SELECT DISTINCT s.staff_id,s.display_name,s.title,s.organization_id,s.status
        FROM teaching_lesson l
        JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        LEFT JOIN dim_staff s ON s.staff_id=lt.staff_id
        WHERE l.semester_id=? AND l.course_id=?
        ORDER BY s.title,s.staff_id
    """, (semester, course_id))
    reasons = _faculty_course_attention(row)
    teacher_count = row.get("teacher_count") or 0
    known = teacher_count - (row.get("unknown_title_count") or 0)
    senior = (row.get("professor_count") or 0) + (row.get("associate_professor_count") or 0)
    high_impact = "single_teacher" in reasons and (
        (raw.get("enrolled") or 0) >= 300
        or ((raw.get("lesson_count") or 0) >= 3 and (raw.get("enrolled") or 0) >= 100)
    )
    risk = "critical" if high_impact else "warning" if reasons else "info"
    reason_text = "、".join(_faculty_reason_label(r) for r in reasons) or "未命中明显团队风险线索"
    summary = (
        f"{row.get('course_name') or course_id}在 {semester} 学期有 {teacher_count} 名实际授课教师、"
        f"{raw.get('lesson_count') or 0} 个教学班、{raw.get('enrolled') or 0} 人次选课。"
        f"当前关注原因：{reason_text}。"
    )
    explain = []
    if "single_teacher" in reasons:
        explain.append("当期仅 1 名教师承担该课程教学任务，若课程为必修、公共课或覆盖学生较多，需要核查备份教师和教学资料交接机制。")
    if "title_incomplete" in reasons:
        explain.append("团队中存在职称缺失，当前不宜直接判断职称梯队，应先补齐人事主数据。")
    if "no_senior_title" in reasons:
        explain.append("已知职称成员中未见教授/副教授，建议结合课程性质核查高职称教师指导或课程负责人安排。")
    return ai_ok({
        "targetType": "facultyResourceCourse",
        "targetId": course_id,
        "targetName": row.get("course_name") or course_id,
        "scenario": "faculty_resource_course",
        "riskLevel": risk,
        "riskLabel": RISK_LABEL[risk],
        "riskTone": TONE[risk],
        "source": "ai_sample" if risk in {"critical", "warning"} else "rule",
        "sourceLabel": "AI辅助研判" if risk in {"critical", "warning"} else "规则研判兜底",
        "generatedBy": "offline_llm_curated_sample" if risk in {"critical", "warning"} else "deterministic_rule_engine",
        "generatedAt": _now(),
        "summary": summary,
        "confidence": "中高",
        "profile": {"college": row.get("organization_id"), "major": row.get("category") or row.get("nature"), "semester": semester},
        "evidence": [
            {"label": "实际授课教师", "value": f"{teacher_count} 人", "detail": "当期教学任务关联教师", "tone": "danger" if teacher_count <= 1 else "success"},
            {"label": "教学班/选课", "value": f"{raw.get('lesson_count') or 0} 班 / {raw.get('enrolled') or 0} 人次", "detail": "基于 teaching_lesson 去重口径；与单教师条件共同判断高影响单点", "tone": "danger" if high_impact else "info"},
            {"label": "职称已知", "value": f"{known} / {teacher_count}", "detail": f"缺失 {row.get('unknown_title_count') or 0} 人", "tone": "warning" if row.get("unknown_title_count") else "success"},
            {"label": "教授/副教授", "value": f"{senior} 人", "detail": "已知成员中的高级职称线索", "tone": "warning" if known > 0 and senior == 0 else "info"},
            {"label": "命中原因", "value": f"{len(reasons)} 项", "detail": reason_text, "tone": "danger" if "single_teacher" in reasons else "warning" if reasons else "success"},
        ],
        "reasons": explain or ["当前未发现明显课程团队保障风险，可作为常规观察对象。"],
        "suggestions": [
            {"role": "二级学院", "priority": "high" if risk == "critical" else "medium", "action": "确认课程团队与备份教师", "detail": "核查课程负责人、备份教师、教学资料和青年教师培养安排，避免高影响单点。"},
            {"role": "教务处", "priority": "medium", "action": "纳入重点课程保障清单", "detail": "对覆盖学生较多、必修或公共课程，建议纳入教学运行保障台账。"},
            {"role": "人事/数据治理", "priority": "high" if "title_incomplete" in reasons else "medium", "action": "补齐职称与组织归属", "detail": "职称缺失课程需先完成教师主数据治理，再判断职称结构风险。"},
        ],
        "nextActions": [
            "查看成员列表，确认是否存在未关联到系统的实际课程团队成员。",
            "若为单教师承担，确认下一学期是否已有备份教师或团队共建安排。",
            "若无高级职称，结合课程性质判断是否需要高职称教师指导或课程负责人调整。",
        ],
        "focusItems": {"members": members},
        "limitations": [
            "当前没有教师年龄数据，因此不判断年龄断层。",
            "单学期单教师承担不等同于长期人才危机，需要结合连续学期和学院确认信息。",
        ],
    })


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(dbm.scalar(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _safe_scalar(conn: sqlite3.Connection, sql: str, params=(), default=0):
    try:
        value = dbm.scalar(conn, sql, params)
        return default if value is None else value
    except Exception:
        return default


def _safe_query(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    try:
        return dbm.query(conn, sql, params)
    except Exception:
        return []


def _management_period_panel(period: str, payload: dict) -> dict:
    if period == "term":
        return {
            "title": "学期治理复盘与下学期准备",
            "question": "本学期发生了什么变化，哪些问题需要转化为下学期资源安排？",
            "items": payload.get("termIndicators") or [],
        }
    return {
        "title": "今日核查重点",
        "question": "今天应先确认哪些对象已经被学院看见并进入核查？",
        "items": [
            {"label": item.get("theme"), "value": item.get("summary"), "managementValue": item.get("why")}
            for item in (payload.get("priorities") or [])[:3]
        ],
    }


BRIEFING_ACTION_META = {
    "学生学业风险": {
        "owner": "二级学院、辅导员", "timing": "本周内",
        "action": "确认高风险学生是否已进入本轮核查名单",
        "expectedResult": "形成已确认的重点学生、主要课程问题和责任人员清单",
        "consequence": "若高风险学生持续未被学院看见，后续预警可能继续升级，帮扶窗口也会进一步缩短。",
    },
    "毕业准备核查": {
        "owner": "二级学院、教务处", "timing": "下一轮选课与开课安排前",
        "action": "区分明确未通过与待核验证据，确认课程处理路径",
        "expectedResult": "形成学生课程处理清单和需校级协调的课程保障清单",
        "consequence": "若未提前确认，学生可能错过补修窗口，课程资源问题会延后到毕业审核阶段暴露。",
    },
    "课程质量与运行压力": {
        "owner": "开课学院、教务处", "timing": "下一教学任务制定前",
        "action": "核查高影响课程的教学支持与重修资源",
        "expectedResult": "明确课程支持、重修安排和需要持续观察的指标",
        "consequence": "若只看排名不核查课程支持条件，集中未通过问题可能在后续学期重复出现。",
    },
    "课程团队保障": {
        "owner": "开课学院、教务处", "timing": "下一教学任务锁定前",
        "action": "确认高影响课程的真实团队与应急替代安排",
        "expectedResult": "形成需补充团队、备份教师或主数据的课程清单",
        "consequence": "若高影响单点未被确认，任务调整时可能缺少可替代的授课安排。",
    },
}


def _briefing_priority_signature(item: dict) -> str:
    return json.dumps({
        "theme": item.get("theme"), "level": item.get("level"),
        "summary": item.get("summary"),
    }, ensure_ascii=False, sort_keys=True)


def _enrich_briefing_priority(item: dict) -> dict:
    enriched = dict(item)
    meta = BRIEFING_ACTION_META.get(item.get("theme"), {})
    enriched.update({
        "owner": meta.get("owner", "相关业务责任部门"),
        "timing": meta.get("timing", "下一业务节点前"),
        "managementAction": meta.get("action", item.get("action") or "进入专题核查事实证据"),
        "expectedResult": meta.get("expectedResult", "形成已核实的问题清单和后续处理依据"),
        "consequence": meta.get("consequence", "若不核查，可能造成管理优先级不清或问题延后暴露。"),
        "impactScope": item.get("summary"),
        "signature": _briefing_priority_signature(item),
    })
    return enriched


def _build_management_events(current: list[dict], previous: Optional[list[dict]]) -> list[dict]:
    current_rows = [_enrich_briefing_priority(item) for item in current]
    if previous is None:
        return [{
            **item, "changeType": "baseline", "changeLabel": "首次纳入",
            "changeSummary": "首次建立管理基线，需先确认该事项是否已经进入现有工作安排。",
        } for item in current_rows[:3]]

    previous_rows = [_enrich_briefing_priority(item) for item in previous]
    previous_map = {item["theme"]: item for item in previous_rows}
    current_map = {item["theme"]: item for item in current_rows}
    events: list[dict] = []
    for item in current_rows:
        old = previous_map.get(item["theme"])
        if old is None:
            events.append({**item, "changeType": "new", "changeLabel": "新增",
                           "changeSummary": "相较上次快照新增为管理关注事项。"})
        elif old["signature"] != item["signature"]:
            old_level = old.get("level")
            new_level = item.get("level")
            change_type = "upgraded" if old_level != "high" and new_level == "high" else "changed"
            events.append({**item, "changeType": change_type,
                           "changeLabel": "升级" if change_type == "upgraded" else "发生变化",
                           "changeSummary": f"上次：{old.get('summary')}；本次：{item.get('summary')}"})
    for item in previous_rows:
        if item["theme"] not in current_map:
            events.append({**item, "changeType": "resolved", "changeLabel": "退出重点",
                           "level": "low", "changeSummary": "本次已不再进入管理重点，建议确认是否可以退出持续跟踪。",
                           "managementAction": "确认事项是否已具备退出跟踪的证据",
                           "timing": "本次更新后", "expectedResult": "确认退出或继续保留观察的理由"})
    order = {"upgraded": 0, "new": 1, "changed": 2, "resolved": 3, "baseline": 4}
    return sorted(events, key=lambda item: (order.get(item.get("changeType"), 9), 0 if item.get("level") == "high" else 1, item.get("rank", 99)))[:3]


def _management_scope_context(user: dict, conn: sqlite3.Connection,
                              v2_conn: sqlite3.Connection) -> dict:
    """Resolve one management-briefing scope for both legacy and V2 databases.

    V2 mappings are explicit. A scoped role without a valid mapping receives an
    empty V2 scope instead of silently falling back to school-wide data.
    """
    role_id = user.get("role_id") or ""
    scope_type = _safe_scalar(
        conn, "SELECT data_scope_type FROM sys_role WHERE role_id=?", (role_id,), "all"
    ) or "all"
    legacy_where, legacy_params = student_data_scope(user, conn, "s")
    if scope_type == "all":
        return {
            "type": "all", "label": "全校", "key": "all",
            "legacyStudentWhere": "", "legacyStudentParams": [],
            "v2StudentWhere": "", "v2StudentParams": [],
            "v2LessonWhere": "", "v2LessonParams": [],
        }

    mappings = _safe_query(v2_conn, """
        SELECT scope_type,source_scope_id,organization_id,major_code,class_code
        FROM access_scope_mapping
        WHERE role_id=? AND mapping_status='mapped'
        ORDER BY source_scope_id
    """, (role_id,))
    source_ids = [row.get("source_scope_id") for row in mappings if row.get("source_scope_id")]
    label = "、".join(source_ids) or "未映射范围"
    if scope_type == "college" and source_ids:
        names = _safe_query(
            conn,
            f"SELECT name FROM dim_college WHERE college_id IN ({','.join('?' * len(source_ids))}) ORDER BY name",
            tuple(source_ids),
        )
        label = "、".join(row.get("name") or "" for row in names) or label

    column_by_type = {
        "college": "organization_id", "major": "major_code", "class": "class_code",
    }
    mapping_column = column_by_type.get(scope_type)
    values = [row.get(mapping_column) for row in mappings if mapping_column and row.get(mapping_column)]
    if values:
        placeholders = ",".join("?" * len(values))
        v2_student_where = f"s.{mapping_column} IN ({placeholders})"
        # Teaching tasks expose a reliable organization scope. Other scoped roles
        # keep teaching/team aggregates empty rather than leaking school-wide data.
        v2_lesson_where = (
            f"tl.organization_id IN ({placeholders})" if scope_type == "college" else "1=0"
        )
        v2_lesson_params = list(values) if scope_type == "college" else []
    else:
        v2_student_where = "1=0"
        v2_lesson_where = "1=0"
        v2_lesson_params = []

    return {
        "type": scope_type, "label": label,
        "key": f"{scope_type}:{','.join(str(value) for value in values) or 'unmapped'}",
        "legacyStudentWhere": legacy_where or "1=0",
        "legacyStudentParams": legacy_params,
        "v2StudentWhere": v2_student_where,
        "v2StudentParams": list(values),
        "v2LessonWhere": v2_lesson_where,
        "v2LessonParams": v2_lesson_params,
    }


def _management_briefing_view(base: dict, period: str, user: dict, cache_hit: bool) -> dict:
    payload = json.loads(json.dumps(base, ensure_ascii=False))
    priorities = payload.get("priorities") or []
    ongoing = [_enrich_briefing_priority(item) for item in priorities[:3]]
    history_key = (user.get("username") or user.get("role_id"), period,
                   payload.get("semester", {}).get("grade"), payload.get("semester", {}).get("teaching"))
    previous = _MANAGEMENT_BRIEFING_HISTORY.get(history_key)
    events = _build_management_events(priorities, previous.get("priorities") if previous else None)
    now = _now()
    _MANAGEMENT_BRIEFING_HISTORY[history_key] = {"priorities": priorities, "capturedAt": now}

    no_change = previous is not None and not events
    payload.update({
        "period": period,
        "targetId": f"{period}-{payload.get('semester',{}).get('grade') or payload.get('semester',{}).get('teaching')}",
        "targetName": "AI管理要情",
        "headline": (
            "本次更新未发现新增、升级或退出的重大事项。" if no_change
            else f"本次识别 {len(events)} 项管理变化，先处理“{events[0].get('theme')}”。" if events
            else "当前未形成需要新增介入的管理事项。"
        ),
        "summary": (
            "当前数据与上次管理快照一致，不重复制造新任务；下方保留持续需处理事项供复核。" if no_change
            else "只呈现相对上次快照发生的变化，并把影响范围、责任角色、建议时点和证据入口放在同一事项中。"
        ),
        "changes": events,
        "changeCount": len(events),
        "noSignificantChange": no_change,
        "ongoingPriorities": ongoing,
        "snapshot": {
            "status": "unchanged" if no_change else "initial" if previous is None else "changed",
            "currentAt": now,
            "baselineAt": previous.get("capturedAt") if previous else None,
            "comparisonLabel": "首次建立基线" if previous is None else f"与 {previous.get('capturedAt')} 快照比较",
            "persistence": "原型阶段在当前服务进程内保留；生产系统写入AI管理快照表。",
        },
        "audience": (
            "教务处管理者 · 全校范围"
            if payload.get("scope", {}).get("type", "all") == "all"
            else f"二级学院管理者 · {payload.get('scope', {}).get('label', '授权范围')}"
        ),
        "periodPanel": _management_period_panel(period, payload),
        "cache": {"hit": cache_hit, "ttlSeconds": MANAGEMENT_BRIEFING_CACHE_TTL},
    })
    return payload


def _management_graduation_data(conn: sqlite3.Connection, student_where: str = "",
                                student_params: tuple = ()) -> tuple[dict, list[dict]]:
    """Load the two graduation aggregates in parallel with the legacy grade scan."""
    if not _table_exists(conn, "student_plan_course_status"):
        return {"available": False}, []
    where_sql = f"WHERE {student_where}" if student_where else ""
    graduation_row = dbm.query_one(conn, f"""
        SELECT COUNT(DISTINCT x.student_id) covered_students,
               COUNT(DISTINCT CASE WHEN x.requirement_type='必修' AND x.completion_status='failed' THEN x.student_id END) action_required_students,
               COUNT(DISTINCT CASE WHEN x.requirement_type='必修' AND x.completion_status IN ('not_completed','unknown')
                 AND CAST(COALESCE(NULLIF(x.suggested_term,''),'99') AS INTEGER)<=8 THEN x.student_id END) verification_students,
               COUNT(DISTINCT x.plan_id) plan_count
        FROM student_plan_course_status x
        JOIN dim_student s ON s.student_id=x.student_id
        {where_sql}
    """, student_params) or {}
    scoped_and = f" AND {student_where}" if student_where else ""
    graduation_courses = _safe_query(conn, f"""
        SELECT x.course_id,COALESCE(MAX(c.name),x.course_id) course_name,
               COUNT(DISTINCT CASE WHEN x.completion_status='failed' THEN x.student_id END) failed_students,
               COUNT(DISTINCT CASE WHEN x.completion_status IN ('not_completed','unknown')
                 AND CAST(COALESCE(NULLIF(x.suggested_term,''),'99') AS INTEGER)<=8 THEN x.student_id END) verification_students
        FROM student_plan_course_status x
        LEFT JOIN dim_course c ON c.course_id=x.course_id
        JOIN dim_student s ON s.student_id=x.student_id
        WHERE x.requirement_type='必修'
          {scoped_and}
        GROUP BY x.course_id
        HAVING failed_students>0 OR verification_students>0
        ORDER BY failed_students DESC, verification_students DESC
        LIMIT 6
    """, student_params)
    return {"available": True, **graduation_row}, graduation_courses


@router.get("/briefing/management")
def management_ai_briefing(period: str = "morning",
                           semester: Optional[str] = None,
                           user: dict = Depends(get_current_user),
                           conn: sqlite3.Connection = Depends(get_db),
                           v2_conn: sqlite3.Connection = Depends(get_v2_db)):
    """跨专题 AI 管理要情。

    该接口不替代正式业务审批，只把现有真实数据组织成管理优先级、证据和下一步动作。
    """
    legacy_semester = semester or _safe_scalar(conn, "SELECT MAX(semester_id) FROM fact_grade WHERE source='real'", default="")
    teaching_semester = semester or _safe_scalar(v2_conn, "SELECT MAX(semester_id) FROM teaching_lesson", default="2023-2024-1")
    scope = _management_scope_context(user, conn, v2_conn)
    # 本次更新与学期态势复用同一份重型跨库汇总，只在呈现层组织不同内容。
    cache_key = (legacy_semester, teaching_semester, user.get("role_id"), scope["key"])
    cached = _MANAGEMENT_BRIEFING_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < MANAGEMENT_BRIEFING_CACHE_TTL:
        # 缓存始终保存规则汇总原稿。这里做深拷贝，避免首次返回时的样本匹配
        # 反向污染缓存，导致学期态势错误继承本次更新的大模型样本标识。
        payload = _management_briefing_view(cached[1], period, user, True)
        return ai_ok(payload)

    # V2培养方案聚合与旧分析库的成绩聚合彼此独立，并行读取可缩短首次等待。
    with ThreadPoolExecutor(max_workers=1) as pool:
        graduation_future = pool.submit(
            _management_graduation_data, v2_conn,
            scope["v2StudentWhere"], tuple(scope["v2StudentParams"]),
        )
        legacy_scope_and = f" AND {scope['legacyStudentWhere']}" if scope["legacyStudentWhere"] else ""
        alert_stats = dbm.query_one(conn, f"""
            SELECT COUNT(DISTINCT a.student_id) active_students,
                   COUNT(*) active_records,
                   SUM(CASE WHEN a.level IN ('严重','高风险') THEN 1 ELSE 0 END) severe_records
            FROM fact_alert a JOIN dim_student s ON s.student_id=a.student_id
            WHERE COALESCE(a.is_active,1)=1 {legacy_scope_and}
        """, tuple(scope["legacyStudentParams"])) or {}
        active_alert_students = int(alert_stats.get("active_students") or 0)
        active_alerts = int(alert_stats.get("active_records") or 0)
        severe_alerts = int(alert_stats.get("severe_records") or 0)
        semester_grade_rows = _safe_query(conn, f"""
        WITH semester_grade AS (
            SELECT g.semester_id,COUNT(*) attempts,
                   SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failures,
                   SUM(CASE WHEN g.gpa IS NOT NULL THEN g.gpa ELSE 0 END) gpa_sum,
                   SUM(CASE WHEN g.gpa IS NOT NULL THEN 1 ELSE 0 END) gpa_count
            FROM fact_grade g JOIN dim_student s ON s.student_id=g.student_id
            WHERE g.source='real' AND g.is_pass IS NOT NULL {legacy_scope_and}
            GROUP BY g.semester_id
        )
        SELECT semester_id,attempts,failures,
               ROUND(failures*100.0/NULLIF(attempts,0),1) fail_rate,
               ROUND(gpa_sum/NULLIF(gpa_count,0),2) avg_gpa,
               SUM(attempts) OVER () total_attempts,
               SUM(failures) OVER () total_failures,
               ROUND(SUM(gpa_sum) OVER ()/NULLIF(SUM(gpa_count) OVER (),0),2) total_avg_gpa
        FROM semester_grade
        ORDER BY semester_id DESC
        LIMIT 2
        """, tuple(scope["legacyStudentParams"]))
        grade_rollup = semester_grade_rows[0] if semester_grade_rows else {}
        total_attempts = int(grade_rollup.get("total_attempts") or 0)
        total_failures = int(grade_rollup.get("total_failures") or 0)
        grade_stats = {
            "attempts": total_attempts,
            "failures": total_failures,
            "fail_rate": round(total_failures * 100.0 / total_attempts, 1) if total_attempts else 0,
            "avg_gpa": grade_rollup.get("total_avg_gpa"),
        }
        top_fail_courses = _safe_query(conn, f"""
            SELECT g.course_id,COALESCE(c.name,g.course_id) course_name,
                   COUNT(*) attempts,
                   SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) failures,
                   ROUND(SUM(CASE WHEN g.is_pass=0 THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) fail_rate
            FROM fact_grade g
            JOIN dim_student s ON s.student_id=g.student_id
            LEFT JOIN dim_course c ON c.course_id=g.course_id
            WHERE g.source='real' AND g.is_pass IS NOT NULL {legacy_scope_and}
            GROUP BY g.course_id,COALESCE(c.name,g.course_id)
            HAVING COUNT(*)>=30 AND failures>0
            ORDER BY failures DESC, fail_rate DESC
            LIMIT 6
        """, tuple(scope["legacyStudentParams"]))
        graduation, graduation_courses = graduation_future.result()

    room_summary = {"available": False}
    if scope["type"] == "all" and _table_exists(conn, "fact_room_occupancy"):
        room_semester = semester or _safe_scalar(conn, "SELECT MAX(semester_id) FROM fact_room_occupancy", default="")
        room_row = dbm.query_one(conn, """
            SELECT COUNT(*) occupancy_count,
                   COUNT(DISTINCT room_name) rooms,
                   COUNT(DISTINCT building_name) buildings,
                   SUM(CASE WHEN is_evening=1 THEN 1 ELSE 0 END) evening_count
            FROM fact_room_occupancy
            WHERE semester_id=?
        """, (room_semester,)) or {}
        room_summary = {"available": True, "semester": room_semester, **room_row}

    lesson_scope_and = f" AND {scope['v2LessonWhere']}" if scope["v2LessonWhere"] else ""
    teaching = dbm.query_one(v2_conn, f"""
        SELECT COUNT(DISTINCT lesson_id) lessons,
               COUNT(DISTINCT course_id) courses,
               SUM(COALESCE(enrolled,0)) enrolled
        FROM teaching_lesson tl
        WHERE semester_id=? {lesson_scope_and}
    """, (teaching_semester, *scope["v2LessonParams"])) or {}
    team_rows = _safe_query(v2_conn, f"""
        SELECT t.*,COALESCE(c.name,t.course_id) course_name,
               COALESCE(o.lesson_count,0) lesson_count,COALESCE(o.enrolled,0) enrolled
        FROM agg_course_team t
        LEFT JOIN dim_course c ON c.course_id=t.course_id
        LEFT JOIN (
            SELECT course_id,COUNT(DISTINCT lesson_id) lesson_count,SUM(COALESCE(enrolled,0)) enrolled
            FROM teaching_lesson WHERE semester_id=? GROUP BY course_id
        ) o ON o.course_id=t.course_id
        WHERE t.semester_id=?
          {"AND EXISTS (SELECT 1 FROM teaching_lesson tl WHERE tl.semester_id=t.semester_id AND tl.course_id=t.course_id AND " + scope["v2LessonWhere"] + ")" if scope["v2LessonWhere"] else ""}
    """, (teaching_semester, teaching_semester, *scope["v2LessonParams"]))
    for row in team_rows:
        row["attention_reasons"] = _faculty_course_attention(row)
    faculty_attention = [r for r in team_rows if r["attention_reasons"]]
    single_teacher_courses = sum(1 for r in faculty_attention if "single_teacher" in r["attention_reasons"])
    title_gap_courses = sum(1 for r in faculty_attention if "title_incomplete" in r["attention_reasons"])
    faculty_high_impact = [r for r in faculty_attention if (
        "single_teacher" in r["attention_reasons"] and (
            int(r.get("enrolled") or 0) >= 300
            or (int(r.get("lesson_count") or 0) >= 3 and int(r.get("enrolled") or 0) >= 100)
        )
    )]
    faculty_high_impact.sort(key=lambda x: (-int(x.get("enrolled") or 0), x.get("course_id") or ""))
    faculty_attention.sort(key=lambda x: (-int(x.get("enrolled") or 0), x.get("course_id") or ""))

    priorities = []
    if active_alert_students:
        priorities.append({
            "rank": 1,
            "theme": "学生学业风险",
            "level": "high" if severe_alerts or active_alert_students >= 300 else "medium",
            "summary": f"当前有 {active_alert_students} 名学生处于有效预警池，涉及 {active_alerts} 条预警记录。",
            "why": "这是最直接影响学生帮扶与学院响应的事项，应优先确认高风险学生是否已被看见。",
            "route": "/admin/alert",
            "routeQuery": {"level": "严重"},
            "action": "查看严重预警",
            "source": "fact_alert.student_id / is_active / level",
        })
    if graduation.get("available") and graduation.get("action_required_students"):
        priorities.append({
            "rank": 2,
            "theme": "毕业准备核查",
            "level": "high" if graduation.get("action_required_students", 0) >= 50 else "medium",
            "summary": f"{graduation.get('action_required_students',0)} 名学生存在必修课明确未通过，{graduation.get('verification_students',0)} 名学生存在到期缺证据。",
            "why": "该类问题更适合提前形成学院核查清单和课程保障清单，避免临近毕业集中暴露。",
            "route": "/admin/reports/graduation-readiness",
            "action": "进入毕业准备专题",
            "source": "student_plan_course_status.completion_status / requirement_type / is_overdue",
        })
    if top_fail_courses:
        top_course = top_fail_courses[0]
        priorities.append({
            "rank": 3,
            "theme": "课程质量与运行压力",
            "level": "medium",
            "summary": f"{top_course['course_name']} 累计未通过 {top_course['failures']} 人次，未通过率 {top_course['fail_rate']}%。",
            "why": "高影响课程需要结合开课供给、重修资源、教学支持与学生学习压力进行联合判断。",
            "route": "/admin/reports/course-quality",
            "routeQuery": {"courseId": top_course["course_id"]},
            "action": "查看课程质量专题",
            "source": "fact_grade.course_id / is_pass / gpa",
        })
    if faculty_attention:
        priorities.append({
            "rank": 4,
            "theme": "课程团队保障",
            "level": "medium" if single_teacher_courses < 10 else "high",
            "summary": f"{len(faculty_attention)} 门课程进入候选池，其中 {len(faculty_high_impact)} 门为当期单教师且同时覆盖多班或大规模学生的高影响单点。",
            "why": "候选池用于避免漏查；真正需要优先行动的是学生覆盖较大的单教师课程，不等同于教师评价。",
            "route": "/admin/reports/faculty-resource-risk",
            "routeQuery": {"focus": "high-impact"},
            "action": "查看师资保障专题",
            "source": "agg_course_team.teacher_count / unknown_title_count / senior_title_count",
        })
    priorities.sort(key=lambda x: (0 if x["level"] == "high" else 1, x["rank"]))
    for i, item in enumerate(priorities, start=1):
        item["rank"] = i

    headline = "今日建议优先看学生风险、毕业准备和课程保障三类事项。"
    if period == "term":
        headline = "本学期建议围绕学生帮扶、毕业准备、课程运行和师资保障形成联合治理清单。"
    elif priorities:
        headline = f"今日最值得先看的事项是：{priorities[0]['theme']}。"

    sections = [
        {
            "key": "student-risk",
            "title": "学生风险与帮扶响应",
            "insight": f"有效预警学生 {active_alert_students} 人，系统可进一步下钻到学生档案查看成长轨迹、挂科课程和历史预警。",
            "managementValue": "帮助教务处和学院把“有预警”转成“谁先看、看什么、由谁跟进”。",
            "route": "/admin/alert",
            "evidence": [
                {"label": "有效预警学生", "value": active_alert_students, "unit": "人", "source": "fact_alert.student_id / is_active"},
                {"label": "有效预警记录", "value": active_alerts, "unit": "条", "source": "fact_alert.alert_id / is_active"},
                {"label": "严重/高风险记录", "value": severe_alerts, "unit": "条", "source": "fact_alert.level / is_active"},
            ],
        },
        {
            "key": "graduation",
            "title": "毕业准备与课程保障",
            "insight": "培养方案完成证据已能形成学生核查清单和课程保障清单。" if graduation.get("available") else "当前未接入培养方案完成证据，暂不生成毕业准备判断。",
            "managementValue": "帮助学院提前处理必修未通过、到期缺证据和重修资源供给问题。",
            "route": "/admin/reports/graduation-readiness",
            "evidence": [
                {"label": "覆盖学生", "value": graduation.get("covered_students", 0), "unit": "人", "source": "student_plan_course_status.student_id"},
                {"label": "需处理学生", "value": graduation.get("action_required_students", 0), "unit": "人", "source": "student_plan_course_status.completion_status='failed' / requirement_type='必修'"},
                {"label": "待核验学生", "value": graduation.get("verification_students", 0), "unit": "人", "source": "student_plan_course_status.completion_status / suggested_term"},
            ],
        },
        {
            "key": "course-quality",
            "title": "课程质量与教学运行",
            "insight": f"真实成绩记录总体未通过率 {grade_stats.get('fail_rate') or 0}%，需重点关注累计影响学生较多的课程。",
            "managementValue": "把课程排名转为课程支持、重修安排、教学资源协调和学院协同核查。",
            "route": "/admin/reports/course-quality",
            "evidence": [
                {"label": "成绩记录", "value": grade_stats.get("attempts", 0), "unit": "条", "source": "fact_grade.grade_id / source='real'"},
                {"label": "未通过记录", "value": grade_stats.get("failures", 0), "unit": "条", "source": "fact_grade.is_pass=0 / source='real'"},
                {"label": "平均GPA", "value": grade_stats.get("avg_gpa") or "-", "unit": "", "source": "fact_grade.gpa / source='real'"},
            ],
        },
        {
            "key": "operation-resource",
            "title": "教学资源与课程团队",
            "insight": f"{teaching_semester} 学期接入 {teaching.get('courses',0)} 门课程、{teaching.get('lessons',0)} 个教学班；从 {len(faculty_attention)} 门候选课程中收敛出 {len(faculty_high_impact)} 门高影响团队课程。",
            "managementValue": "帮助排课与学院判断课程供给、教师负荷、课程团队和教室资源是否存在短板。",
            "route": "/admin/reports/faculty-resource-risk",
            "evidence": [
                {"label": "接入课程", "value": teaching.get("courses", 0), "unit": "门", "source": "teaching_lesson.course_id / semester_id"},
                {"label": "教学班", "value": teaching.get("lessons", 0), "unit": "个", "source": "teaching_lesson.lesson_id / semester_id"},
                {"label": "候选核查课程", "value": len(faculty_attention), "unit": "门", "source": "agg_course_team.teacher_count / unknown_title_count / senior_title_count"},
                {"label": "高影响团队课程", "value": len(faculty_high_impact), "unit": "门", "source": "agg_course_team.teacher_count / teaching_lesson.enrolled"},
            ],
        },
    ]

    current_semester_grade = semester_grade_rows[0] if semester_grade_rows else {}
    previous_semester_grade = semester_grade_rows[1] if len(semester_grade_rows) > 1 else {}
    fail_rate_delta = round((current_semester_grade.get("fail_rate") or 0) - (previous_semester_grade.get("fail_rate") or 0), 1) if previous_semester_grade else None
    gpa_delta = round((current_semester_grade.get("avg_gpa") or 0) - (previous_semester_grade.get("avg_gpa") or 0), 2) if previous_semester_grade else None
    term_indicators = [
        {"label": "成绩风险变化", "value": f"未通过率 {current_semester_grade.get('fail_rate','—')}%", "managementValue": f"较 {previous_semester_grade.get('semester_id','上一学期')} 变化 {fail_rate_delta:+.1f} 个百分点；用于判断课程支持压力是否扩大。" if fail_rate_delta is not None else "当前仅形成单学期口径，暂不输出趋势结论。", "source": "fact_grade.semester_id / is_pass"},
        {"label": "GPA变化", "value": f"平均GPA {current_semester_grade.get('avg_gpa','—')}", "managementValue": f"较 {previous_semester_grade.get('semester_id','上一学期')} 变化 {gpa_delta:+.2f}；用于判断总体成绩水平是否发生结构性变化。" if gpa_delta is not None else "当前仅形成单学期口径，暂不输出趋势结论。", "source": "fact_grade.semester_id / gpa"},
        {"label": "毕业准备", "value": f"{graduation.get('action_required_students',0)} 人明确需处理", "managementValue": "用于提前形成重修、补修与课程认定核查清单。", "source": "student_plan_course_status.completion_status / requirement_type"},
        {"label": "下学期师资保障", "value": f"{len(faculty_high_impact)} 门高影响团队课程", "managementValue": "从宽口径候选池中优先确认高覆盖单点课程的备份教师与开课连续性。", "source": "agg_course_team.teacher_count / teaching_lesson.enrolled"},
    ]

    payload = {
        "targetType": "managementBriefing",
        "targetId": f"{period}-{legacy_semester or teaching_semester}",
        "targetName": "AI管理要情（本次更新）" if period == "morning" else "AI管理要情（学期态势）",
        "scenario": "management_briefing",
        "source": "ai_sample",
        "sourceLabel": "AI辅助管理要情",
        "traceability": {
            "dataSources": ["fact_alert", "fact_grade", "student_plan_course_status", "teaching_lesson", "fact_room_occupancy", "agg_course_team"],
            "calculationLogic": "按当前接入数据汇总有效预警、培养方案必修课完成证据、课程未通过记录、教学任务、教室占用和课程团队风险，再按管理影响面生成优先级。",
            "rules": ["有效预警学生按 fact_alert.is_active 去重", "毕业准备按必修课明确未通过和到期缺证据识别", "课程质量按成绩记录未通过率和累计未通过人次识别", "课程团队只把单教师且覆盖不少于300人次，或覆盖不少于3个教学班且不少于100人次的课程列为高影响单点"],
            "formula": "管理优先级 = 高风险学生影响 + 毕业准备可行动问题 + 高影响课程 + 课程团队保障风险的综合排序",
            "boundary": "管理要情用于管理优先级提示，不替代毕业审核、教师评价或正式审批。",
        },
        "generatedBy": "offline_llm_curated_sample_with_rule_fallback",
        "generatedAt": _now(),
        "period": period,
        "scope": {"type": scope["type"], "label": scope["label"], "key": scope["key"]},
        "semester": {"grade": legacy_semester, "teaching": teaching_semester, "room": room_summary.get("semester")},
        "headline": headline,
        "summary": "本管理要情基于已接入成绩、预警、培养方案、教学任务、教室占用和课程团队数据，按快照差异组织管理优先级。",
        "metrics": [
            {"label": "有效预警学生", "value": active_alert_students, "unit": "人", "tone": "danger" if active_alert_students else "success", "hint": "当前仍处于有效状态的预警学生去重数"},
            {"label": "毕业需处理学生", "value": graduation.get("action_required_students", 0), "unit": "人", "tone": "warning", "hint": "培养方案必修课存在明确未通过证据的学生数"},
            {"label": "高影响挂科课程", "value": len(top_fail_courses), "unit": "门", "tone": "primary", "hint": "样本量达到阈值且累计未通过较多的课程"},
            {"label": "高影响团队课程", "value": len(faculty_high_impact), "unit": "门", "tone": "amber", "hint": "当期仅1名实际授课教师，且选课≥300人次，或教学班≥3且选课≥100人次"},
            {"label": "教室占用记录", "value": room_summary.get("occupancy_count", 0), "unit": "条", "tone": "teal", "hint": "实际教室占用数据记录数"},
        ],
        "priorities": priorities,
        "sections": sections,
        "briefs": [
            {"role": "教务处", "title": "先组织跨学院共性问题", "text": "优先看毕业准备、课程质量和课程团队中跨专业影响较大的事项，形成课程保障与重修资源清单。"},
            {"role": "二级学院", "title": "先确认本学院学生和课程", "text": "把学生核查名单、集中挂科课程和单点课程团队拆给专业负责人、班主任和课程负责人。"},
            {"role": "排课/运行人员", "title": "先看供给瓶颈", "text": "结合开课任务、教室占用、调课和教师负荷判断新学期排课优化空间。"},
            {"role": "辅导员/班主任", "title": "先看学生档案与成长轨迹", "text": "对历史预警、低年级受挫和毕业准备缺口叠加的学生进行优先关注。"},
        ],
        "termIndicators": term_indicators,
        "focusItems": {
            "topFailCourses": top_fail_courses,
            "graduationCourses": graduation_courses,
            "facultyCourses": (faculty_high_impact + [r for r in faculty_attention if r not in faculty_high_impact])[:6],
        },
        "nextActions": [
            "先处理优先级清单第一项，进入对应专题查看证据和名单。",
            "把毕业准备与集中挂科课程合并看，判断是否需要重修班、补修资源或替代关系核查。",
            "把课程团队风险与教师负荷、排课偏好结合看，形成下一学期课程保障清单。",
        ],
        "limitations": [
            "当前管理要情是原型阶段的 AI 辅助管理研判，不替代正式审批、毕业审核或教师评价。",
            "少量演示对象使用已审校的离线大模型输出，其余对象使用确定性规则实时生成；页面会明确标注生成方式。",
            "管理要情准确度依赖成绩、预警、培养方案、教学任务、教室占用和教师主数据的完整性。",
        ],
        "cache": {"hit": False, "ttlSeconds": MANAGEMENT_BRIEFING_CACHE_TTL},
    }
    _MANAGEMENT_BRIEFING_CACHE[cache_key] = (
        time.time(), json.loads(json.dumps(payload, ensure_ascii=False))
    )
    return ai_ok(_management_briefing_view(payload, period, user, False))


def _simulation_priority(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _decision_simulation_base_data(conn: sqlite3.Connection, teaching_semester: str,
                                   limit: int, student_scope: str,
                                   student_scope_params: list,
                                   lesson_scope: str, lesson_scope_params: list,
                                   scope_type: str) -> dict:
    """Load the parameter-independent decision evidence once per data scope."""
    student_scope_and = f" AND {student_scope}" if student_scope else ""
    rows = dbm.query(conn, f"""
        SELECT x.course_id,
               COALESCE(MAX(c.name),x.course_id) course_name,
               COALESCE(MAX(x.module),'') module,
               COUNT(DISTINCT CASE WHEN x.completion_status='failed' THEN x.student_id END) failed_students,
               COUNT(DISTINCT CASE WHEN x.completion_status IN ('not_completed','unknown') AND COALESCE(x.is_overdue,0)=1 THEN x.student_id END) verification_students,
               COUNT(DISTINCT x.student_id) involved_students,
               COUNT(DISTINCT s.major_code) major_count
        FROM student_plan_course_status x
        JOIN dim_student s ON s.student_id=x.student_id
        LEFT JOIN dim_course c ON c.course_id=x.course_id
        WHERE x.rule_version='growth-v1' AND x.requirement_type='必修'
          {student_scope_and}
        GROUP BY x.course_id
        HAVING failed_students>0 OR verification_students>0
        ORDER BY failed_students DESC, verification_students DESC, major_count DESC
        LIMIT ?
    """, tuple([*student_scope_params, limit]))
    if not rows:
        raise ApiError("暂无可模拟的毕业准备课程缺口", code=404, status_code=404)

    course_ids = [row["course_id"] for row in rows]
    marks = ",".join("?" for _ in course_ids)
    impacted_unique_students = _safe_scalar(conn, f"""
        SELECT COUNT(DISTINCT x.student_id)
        FROM student_plan_course_status x
        JOIN dim_student s ON s.student_id=x.student_id
        WHERE x.rule_version='growth-v1' AND x.requirement_type='必修'
          AND x.course_id IN ({marks})
          AND (x.completion_status='failed' OR (x.completion_status IN ('not_completed','unknown') AND COALESCE(x.is_overdue,0)=1))
          {student_scope_and}
    """, tuple([*course_ids, *student_scope_params]))
    impacted_unique_majors = _safe_scalar(conn, f"""
        SELECT COUNT(DISTINCT s.major_code)
        FROM student_plan_course_status x
        JOIN dim_student s ON s.student_id=x.student_id
        WHERE x.rule_version='growth-v1' AND x.requirement_type='必修'
          AND x.course_id IN ({marks})
          AND (x.completion_status='failed' OR (x.completion_status IN ('not_completed','unknown') AND COALESCE(x.is_overdue,0)=1))
          {student_scope_and}
    """, tuple([*course_ids, *student_scope_params]))
    lesson_scope_and = f" AND {lesson_scope}" if lesson_scope else ""
    supply = {row["course_id"]: row for row in _safe_query(conn, f"""
        SELECT l.course_id,COUNT(DISTINCT l.lesson_id) lesson_count,
               COUNT(DISTINCT lt.staff_id) teacher_count,
               SUM(COALESCE(l.capacity,0)) capacity,SUM(COALESCE(l.enrolled,0)) enrolled
        FROM teaching_lesson l
        LEFT JOIN lesson_teacher lt ON lt.lesson_id=l.lesson_id
        WHERE l.semester_id=? AND l.course_id IN ({marks}) {lesson_scope_and}
        GROUP BY l.course_id
    """, tuple([teaching_semester] + course_ids + lesson_scope_params))}
    teams = {row["course_id"]: row for row in _safe_query(conn, f"""
        SELECT * FROM agg_course_team
        WHERE semester_id=? AND course_id IN ({marks})
    """, tuple([teaching_semester] + course_ids))} if scope_type == "all" else {}
    substitutions = {row["course_id"]: row["substitution_count"] for row in _safe_query(conn, f"""
        SELECT original_course_id course_id,COUNT(DISTINCT substitution_id) substitution_count
        FROM student_course_substitution
        WHERE original_course_id IN ({marks})
        GROUP BY original_course_id
    """, tuple(course_ids))}
    return {
        "rows": rows, "impactedUniqueStudents": impacted_unique_students,
        "impactedUniqueMajors": impacted_unique_majors, "supply": supply,
        "teams": teams, "substitutions": substitutions,
    }


@router.get("/simulation/graduation-course-support")
def graduation_course_support_simulation(semester: Optional[str] = None,
                                         limit: int = 12,
                                         added_classes: int = 3,
                                         class_capacity: int = 30,
                                         available_teachers: int = 3,
                                         priority_focus: str = "balanced",
                                         problem_type: str = "graduation",
                                         user: dict = Depends(get_current_user),
                                         conn: sqlite3.Connection = Depends(get_v2_db)):
    """AI 决策模拟：毕业准备课程保障与重修资源配置。

    输出的是管理测算，用于比较方案优先级，不作为毕业审核、开课审批或资源承诺。
    """
    student_scope, student_scope_params = _v2_student_scope(user, conn, "s")
    student_scope_and = f" AND {student_scope}" if student_scope else ""
    scope_mappings = _safe_query(
        conn,
        "SELECT scope_type,organization_id,major_code,class_code FROM access_scope_mapping "
        "WHERE role_id=? AND mapping_status='mapped'",
        (user.get("role_id"),),
    ) if user.get("role_id") not in V2_ALL_SCOPE_ROLES else []
    scope_type = scope_mappings[0].get("scope_type") if scope_mappings else "all"
    organization_ids = [row.get("organization_id") for row in scope_mappings if row.get("organization_id")]
    if scope_type == "college" and organization_ids:
        lesson_scope = f"l.organization_id IN ({','.join('?' * len(organization_ids))})"
        lesson_scope_params = organization_ids
    elif scope_type == "all":
        lesson_scope, lesson_scope_params = "", []
    else:
        # Major/class roles have a reliable student scope, but teaching_lesson does
        # not expose a stable major/class key. Keep supply empty instead of using
        # school-wide resources in a scoped decision.
        lesson_scope, lesson_scope_params = "1=0", []
    if not _table_exists(conn, "student_plan_course_status"):
        raise ApiError("暂无培养方案完成状态数据，无法进行毕业准备模拟", code=404, status_code=404)

    teaching_semester = semester or _safe_scalar(conn, "SELECT MAX(semester_id) FROM teaching_lesson", default="2023-2024-1")
    limit = max(5, min(int(limit or 12), 30))
    added_classes = max(0, min(int(added_classes or 0), 20))
    class_capacity = max(15, min(int(class_capacity or 30), 120))
    available_teachers = max(0, min(int(available_teachers or 0), 20))
    priority_focus = priority_focus if priority_focus in {"balanced", "failed", "verification"} else "balanced"
    problem_type = problem_type if problem_type in {"graduation", "course_support", "faculty_assurance"} else "graduation"
    scope_key = "all" if not student_scope else f"{scope_type}:{','.join(str(x) for x in student_scope_params)}"
    cache_key = (teaching_semester, limit, added_classes, class_capacity, available_teachers,
                 priority_focus, problem_type, user.get("role_id"), scope_key)
    cached = _DECISION_SIMULATION_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < DECISION_SIMULATION_CACHE_TTL:
        payload = dict(cached[1])
        payload["cache"] = {"hit": True, "ttlSeconds": DECISION_SIMULATION_CACHE_TTL}
        return ai_ok(payload)

    base_key = (teaching_semester, limit, user.get("role_id"), scope_key)
    base_cached = _DECISION_SIMULATION_BASE_CACHE.get(base_key)
    if base_cached and time.time() - base_cached[0] < MANAGEMENT_BRIEFING_CACHE_TTL:
        base_data = json.loads(json.dumps(base_cached[1], ensure_ascii=False))
        base_cache_hit = True
    else:
        base_data = _decision_simulation_base_data(
            conn, teaching_semester, limit, student_scope, student_scope_params,
            lesson_scope, lesson_scope_params, scope_type,
        )
        _DECISION_SIMULATION_BASE_CACHE[base_key] = (
            time.time(), json.loads(json.dumps(base_data, ensure_ascii=False))
        )
        base_cache_hit = False
    rows = base_data["rows"]
    impacted_unique_students = base_data["impactedUniqueStudents"]
    impacted_unique_majors = base_data["impactedUniqueMajors"]
    supply = base_data["supply"]
    teams = base_data["teams"]
    substitutions = base_data["substitutions"]

    course_items = []
    totals = {
        "failedStudents": 0,
        "verificationStudents": 0,
        "involvedStudents": 0,
        "majorCoverage": 0,
    }
    usable_added_classes = min(added_classes, available_teachers)
    for row_index, row in enumerate(rows):
        cid = row["course_id"]
        sup = supply.get(cid, {})
        team = teams.get(cid, {})
        failed = int(row.get("failed_students") or 0)
        verify = int(row.get("verification_students") or 0)
        majors = int(row.get("major_count") or 0)
        capacity = int(sup.get("capacity") or 0)
        enrolled = int(sup.get("enrolled") or 0)
        spare = max(capacity - enrolled, 0)
        lesson_count = int(sup.get("lesson_count") or 0)
        teacher_count = int(team.get("teacher_count") or sup.get("teacher_count") or 0)
        subst = int(substitutions.get(cid) or 0)
        team_reasons = _faculty_course_attention(team) if team else []
        bottlenecks = []
        if failed >= 10:
            bottlenecks.append("明确未通过学生较多")
        if verify >= 10:
            bottlenecks.append("到期缺证据学生较多")
        if lesson_count == 0:
            bottlenecks.append("当前无开课供给证据")
        if teacher_count <= 1:
            bottlenecks.append("课程团队备份能力需核查")
        if subst == 0:
            bottlenecks.append("暂无课程替代关系证据")

        new_class_capacity = class_capacity if row_index < usable_added_classes and failed > spare else 0
        retake_capacity = spare + new_class_capacity
        retake_impact = min(failed, retake_capacity)
        recognition_impact = min(verify, max(subst * 5, round(verify * (0.35 if subst else 0.12))))
        tutoring_impact = min(failed, max(0, round(failed * 0.22) + min(lesson_count, 3) * 2))
        team_impact = min(failed + verify, 18 if teacher_count <= 1 else 8 if "title_incomplete" in team_reasons else 0)

        courses_score = failed * 2.2 + verify * 1.2 + majors * 5
        if lesson_count == 0:
            courses_score += 18
        if teacher_count <= 1:
            courses_score += 14
        if subst == 0:
            courses_score += 5

        raw_course_name = row.get("course_name") or cid
        course_name_mapped = raw_course_name != cid
        course_items.append({
            "courseId": cid,
            "courseName": raw_course_name if course_name_mapped else f"课程名称待映射（{cid}）",
            "courseNameMapped": course_name_mapped,
            "module": row.get("module") or "未标明模块",
            "failedStudents": failed,
            "verificationStudents": verify,
            "involvedStudents": int(row.get("involved_students") or 0),
            "majorCount": majors,
            "lessonCount": lesson_count,
            "teacherCount": teacher_count,
            "capacity": capacity,
            "enrolled": enrolled,
            "spareSeats": spare,
            "plannedAddedCapacity": new_class_capacity,
            "substitutionCount": subst,
            "bottlenecks": bottlenecks or ["常规关注"],
            "priority": _simulation_priority(courses_score),
            "priorityScore": round(courses_score, 1),
            "estimatedImpact": {
                "retakeClass": retake_impact,
                "recognitionAudit": recognition_impact,
                "learningSupport": tutoring_impact,
                "teamAssurance": team_impact,
            },
        })
        totals["failedStudents"] += failed
        totals["verificationStudents"] += verify
        totals["involvedStudents"] += int(row.get("involved_students") or 0)
        totals["majorCoverage"] += majors

    course_items.sort(key=lambda item: (-item["priorityScore"], -item["failedStudents"], -item["verificationStudents"]))
    for index, item in enumerate(course_items):
        item["priority"] = "high" if index < 3 else "medium" if index < 7 else "low"

    def sum_impact(key: str) -> int:
        return int(sum(item["estimatedImpact"][key] for item in course_items))

    focus_weights = {
        "balanced": {"retakeClass": 1.0, "recognitionAudit": 1.0, "learningSupport": 1.0, "teamAssurance": 1.0},
        "failed": {"retakeClass": 1.35, "recognitionAudit": 0.75, "learningSupport": 1.15, "teamAssurance": 1.0},
        "verification": {"retakeClass": 0.75, "recognitionAudit": 1.35, "learningSupport": 0.8, "teamAssurance": 0.9},
    }[priority_focus]
    problem_weights = {
        "graduation": {"retakeClass": 1.1, "recognitionAudit": 1.4, "learningSupport": 0.7, "teamAssurance": 0.6},
        "course_support": {"retakeClass": 2.0, "recognitionAudit": 0.01, "learningSupport": 3.0, "teamAssurance": 0.4},
        "faculty_assurance": {"retakeClass": 0.05, "recognitionAudit": 0.005, "learningSupport": 0.05, "teamAssurance": 5.0},
    }[problem_type]
    scenarios = [
        {
            "id": "retake-class",
            "title": "方案A：优先开设重修/补修班",
            "score": round(sum_impact("retakeClass") * 2.5 * focus_weights["retakeClass"] * problem_weights["retakeClass"], 1),
            "estimatedStudents": sum_impact("retakeClass"),
            "costLevel": "较高",
            "implementationDifficulty": "中高",
            "bestFor": "明确未通过学生较多、且课程仍有师资或教室供给空间的必修课。",
            "logic": "按课程明确未通过人数、当前余量和最小开班规模估算可覆盖学生，不承诺最终通过。",
            "resourceUse": f"计划新增 {usable_added_classes} 个班，每班 {class_capacity} 人，最多使用 {available_teachers} 名教师",
            "remainingGap": max(totals["failedStudents"] - sum_impact("retakeClass"), 0),
            "remainingLabel": "仍待安排重修/补修的人次",
            "uncertainty": "中：教师、教室和学生实际选课意愿尚需确认",
            "decisionCondition": "已确认教师和教室资源，且课程缺口足以形成有效开班规模",
            "notRecommendedWhen": "缺口主要来自认定未回写，或无法落实教师与教室时",
            "source": "student_plan_course_status、teaching_lesson、lesson_teacher",
            "evidenceBasis": [{"source": "student_plan_course_status.completion_status；teaching_lesson.capacity/enrolled；lesson_teacher.staff_id", "usage": "按明确未通过人数、现有余量和本次输入的班级/教师约束测算可覆盖人次。"}],
            "actions": ["确认课程负责人和开班容量", "优先安排覆盖多专业的必修课", "同步通知学院形成学生名单"],
        },
        {
            "id": "recognition-audit",
            "title": "方案B：课程替代/认定集中核查",
            "score": round(sum_impact("recognitionAudit") * 3.2 * focus_weights["recognitionAudit"] * problem_weights["recognitionAudit"], 1),
            "estimatedStudents": sum_impact("recognitionAudit"),
            "costLevel": "较低",
            "implementationDifficulty": "中",
            "bestFor": "到期缺证据较多、且可能存在课程替代、转专业、认定或数据未回写的课程。",
            "logic": "按到期缺证据人数与已有替代关系线索估算核查收益，核心价值是先排除数据证据缺口。",
            "resourceUse": "主要消耗教务、学院和数据核验人员工时，不直接占用开班容量",
            "remainingGap": max(totals["verificationStudents"] - sum_impact("recognitionAudit"), 0),
            "remainingLabel": "仍待核验的证据缺口人次",
            "uncertainty": "中：替代关系、转专业和历史认定记录可能尚未完整接入",
            "decisionCondition": "到期缺证据规模较大，且学院能够组织课程认定与数据回写核查",
            "notRecommendedWhen": "学生已有明确未通过证据、问题本质是课程供给不足时",
            "source": "student_plan_course_status、student_course_substitution、curriculum_plan_course",
            "evidenceBasis": [{"source": "student_plan_course_status.is_overdue/completion_status；student_course_substitution.original_course_id", "usage": "按到期缺证据人数及替代关系线索估算优先核验规模。"}],
            "actions": ["核对替代课程关系", "补录已通过但未回写的认定记录", "将仍未通过学生转入重修资源清单"],
        },
        {
            "id": "learning-support",
            "title": "方案C：学习支持与过程帮扶",
            "score": round(sum_impact("learningSupport") * 2.1 * focus_weights["learningSupport"] * problem_weights["learningSupport"], 1),
            "estimatedStudents": sum_impact("learningSupport"),
            "costLevel": "中",
            "implementationDifficulty": "中",
            "bestFor": "课程挂科率较高但仍有正常开课供给，适合通过答疑、助教、学习小组改善通过机会。",
            "logic": "按明确未通过人数和当前教学班数量估算可被学习支持覆盖的学生规模。",
            "resourceUse": "需要课程团队、助教或答疑时段，未计入新增教师编制",
            "remainingGap": max(totals["failedStudents"] - sum_impact("learningSupport"), 0),
            "remainingLabel": "未被本轮学习支持覆盖的人次",
            "uncertainty": "较高：当前只能估算可触达规模，不能预测学生最终通过",
            "decisionCondition": "课程正常开设且课程团队能够提供答疑、助教或学习资源",
            "notRecommendedWhen": "课程没有稳定开课供给，或学生首先需要正式重修资格时",
            "source": "student_plan_course_status、teaching_lesson",
            "evidenceBasis": [{"source": "student_plan_course_status.completion_status；teaching_lesson.lesson_id", "usage": "按明确未通过人数和现有教学班数量估算学习支持覆盖规模。"}],
            "actions": ["组织课程答疑和学习资源包", "把学生名单推送给学院和课程团队", "关注重复挂科和低年级受挫学生"],
        },
        {
            "id": "team-assurance",
            "title": "方案D：课程团队保障核查",
            "score": round(sum_impact("teamAssurance") * 2.8 * focus_weights["teamAssurance"] * problem_weights["teamAssurance"], 1),
            "estimatedStudents": sum_impact("teamAssurance"),
            "costLevel": "中",
            "implementationDifficulty": "中高",
            "bestFor": "单教师承担、职称信息不完整或课程团队备份能力不足的高影响课程。",
            "logic": "该方案主要降低教学连续性风险，估算覆盖的是被保障动作影响的课程缺口学生规模。",
            "resourceUse": f"最多按 {available_teachers} 名可协调教师评估备份能力",
            "remainingGap": max(totals["failedStudents"] + totals["verificationStudents"] - sum_impact("teamAssurance"), 0),
            "remainingLabel": "仍未获得团队保障的课程缺口人次",
            "uncertainty": "中高：教师实际可协调时间与学院内部替代安排尚未接入",
            "decisionCondition": "课程属于高影响单点，且学院有可协调的备份教师或课程资料",
            "notRecommendedWhen": "课程仅为正常的单班单教师授课，未形成高覆盖或多班影响时",
            "source": "agg_course_team、lesson_teacher、teaching_lesson",
            "evidenceBasis": [{"source": "agg_course_team.teacher_count/unknown_title_count；teaching_lesson.enrolled", "usage": "按教师单点、职称证据和学生影响面估算团队保障核查规模。"}],
            "actions": ["确认备份教师和课程资料", "核查下学期是否具备稳定开课能力", "补齐教师职称与团队主数据"],
        },
    ]
    scenarios.sort(key=lambda x: (-x["score"], -x["estimatedStudents"]))
    for index, scenario_item in enumerate(scenarios):
        scenario_item["rank"] = index + 1
        scenario_item["priority"] = "high" if index == 0 else "medium" if index == 1 else "low"
        scenario_item["recommended"] = index == 0

    best = scenarios[0]
    problem_meta = {
        "graduation": {
            "title": "毕业准备：先核验还是先开班",
            "question": "面对必修课明确未通过和到期缺证据，先做认定核查还是先组织重修资源？",
            "goal": "在毕业审核前尽快区分数据证据问题与真实课程缺口，减少临近毕业集中暴露。",
            "why": f"当前有 {totals['failedStudents']} 个明确未通过课程人次、{totals['verificationStudents']} 个到期缺证据课程人次，两类问题需要不同处理路径。",
            "route": "/admin/reports/graduation-readiness",
            "routeLabel": "进入毕业准备专题核查",
        },
        "course_support": {
            "title": "课程支持：有限资源优先投入哪些课程",
            "question": "新增班级、答疑和助教资源有限时，应优先支持哪些高影响必修课程？",
            "goal": "把课程排名转成可执行的重修、补修和学习支持资源清单。",
            "why": f"本次候选课程涉及 {impacted_unique_students} 名去重学生，课程缺口在专业覆盖、开课供给和团队保障上存在明显差异。",
            "route": "/admin/reports/course-quality",
            "routeLabel": "进入课程质量专题核查",
        },
        "faculty_assurance": {
            "title": "师资保障：有限备份能力优先保障哪些课程",
            "question": "可协调教师有限时，应优先为哪些高影响课程建立备份与连续开课保障？",
            "goal": "优先降低高覆盖、多教学班课程的教学连续性风险，而不是把所有单教师课程都列为问题。",
            "why": f"候选课程中需结合教师人数、教学班和学生影响面识别真正的高影响单点，当前可协调教师上限为 {available_teachers} 名。",
            "route": "/admin/reports/faculty-resource-risk",
            "routeLabel": "进入师资保障专题核查",
        },
    }[problem_type]
    summary = (
        f"本次围绕“{problem_meta['title']}”选取 {len(course_items)} 门课程。"
        f"系统建议先把“{best['title']}”作为候选方案，预计影响 {best['estimatedStudents']} 人次；"
        "是否采用仍需核查资源条件和课程级证据。"
    )

    payload = {
        "targetType": "decisionSimulation",
        "targetId": f"graduation-course-support-{teaching_semester}",
        "targetName": f"AI决策模拟：{problem_meta['title']}",
        "scenario": "graduation_course_support",
        "source": "ai_sample",
        "sourceLabel": "AI辅助决策模拟",
        "traceability": {
            "dataSources": ["student_plan_course_status", "curriculum_plan_course", "teaching_lesson", "lesson_teacher", "agg_course_team", "student_course_substitution"],
            "calculationLogic": "先筛选必修课中存在明确未通过或到期缺证据的课程，再叠加开课容量、教师覆盖、课程团队和替代关系，比较不同管理动作的可核查覆盖规模和实施难度。",
            "rules": ["明确未通过来自 completion_status='failed'", "到期缺证据来自 completion_status in ('not_completed','unknown') 且 is_overdue=1", "重修/补修测算优先参考课程缺口人数和当前开课余量", "认定核查测算优先参考到期缺证据人数和替代关系线索", "课程团队保障测算优先参考单教师或职称信息缺口"],
            "formula": "方案优先级 = 预计优先核查人次 × 管理收益权重，并结合成本、实施难度和课程团队瓶颈调整。",
            "boundary": "模拟结果是管理测算，不是学生最终通过预测、毕业结论或开课承诺。",
        },
        "generatedBy": "offline_llm_curated_sample_with_rule_simulation",
        "generatedAt": _now(),
        "semester": teaching_semester,
        "problem": {"type": problem_type, **problem_meta},
        "parameters": {
            "addedClasses": added_classes,
            "classCapacity": class_capacity,
            "availableTeachers": available_teachers,
            "usableAddedClasses": usable_added_classes,
            "priorityFocus": priority_focus,
        },
        "scope": {
            "uniqueStudents": impacted_unique_students,
            "uniqueMajors": impacted_unique_majors,
            "courseMajorRelations": totals["majorCoverage"],
            "dataScope": scope_key,
        },
        "summary": summary,
        "metrics": [
            {"label": "模拟课程", "value": len(course_items), "unit": "门", "hint": "必修课中存在明确未通过或到期缺证据的重点课程"},
            {"label": "涉及学生", "value": impacted_unique_students, "unit": "人", "hint": "本次模拟课程中涉及问题证据的去重学生数"},
            {"label": "明确未通过", "value": totals["failedStudents"], "unit": "人次", "hint": "按课程汇总，可能包含同一学生多门课程"},
            {"label": "到期缺证据", "value": totals["verificationStudents"], "unit": "人次", "hint": "建议学期已到但尚无通过/失败/认定证据"},
            {"label": "覆盖专业", "value": impacted_unique_majors, "unit": "个", "hint": f"去重专业数；另有课程—专业关系 {totals['majorCoverage']} 专业次"},
        ],
        "scenarios": scenarios,
        "courses": course_items,
        "recommendation": {
            "bestScenarioId": best["id"],
            "bestScenarioTitle": best["title"],
            "reason": f"在当前管理目标和资源约束下，该方案预计影响 {best['estimatedStudents']} 人次，且与“{problem_meta['goal']}”最匹配；采用前仍需人工确认输入资源和证据条件。",
            "combinedStrategy": "建议先做课程替代/认定核查排除证据缺口，再对明确未通过集中的课程组织重修或补修班；对单教师承担课程同步做团队保障核查。",
        },
        "decisionChecklist": [
            "确认候选课程和学生范围是否与学院掌握情况一致",
            "确认方案所需教师、班级容量或核验人员是否真实可用",
            "进入对应专题核查课程级证据后，再形成正式业务安排",
        ],
        "nextActions": [
            "按优先级导出课程清单，交由学院确认学生名单和课程负责人。",
            "先核查到期缺证据，避免把数据缺口误判为学生未完成。",
            "对明确未通过学生较多的课程评估重修班容量、教师与教室资源。",
            "对单教师承担课程确认备份教师和下学期开课稳定性。",
        ],
        "limitations": [
            "模拟结果是管理测算，不是预测承诺，也不代表学生最终通过或毕业结论。",
            "当前未接入完整选课过程、学生个人意愿、教师实际可用时间和教室排课冲突，因此容量估算需人工核查。",
            "同一学生可能出现在多门课程中，课程层面的覆盖人数存在人次口径，正式行动前需生成去重学生名单。",
        ],
        "cache": {"hit": False, "baseHit": base_cache_hit, "ttlSeconds": DECISION_SIMULATION_CACHE_TTL},
    }
    _DECISION_SIMULATION_CACHE[cache_key] = (time.time(), payload)
    return ai_ok(payload)
