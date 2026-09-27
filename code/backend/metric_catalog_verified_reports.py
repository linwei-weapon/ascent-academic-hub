"""Code-verified metric seeds for the nine basic reports.

The report catalogue is deliberately modelled from the current report service,
Vue column definitions, exporter and contract tests.  The confirmation Markdown
is only a comparison source; report-only calculations use explicit ``BR-*``
identities so that similarly named rates with different denominators are not
silently merged.
"""
from __future__ import annotations


def _page(
    report_path: str,
    feature_name: str,
    source_ref: str,
    *,
    usage_type: str = "table",
    occurrence: str | None = None,
    description: str = "",
) -> dict:
    return {
        "module_path": report_path,
        "feature_name": feature_name,
        "feature_description": description or f"基础报表“{feature_name}”使用位置。",
        "usage_type": usage_type,
        "occurrence_key": occurrence or f"{usage_type}:{feature_name}",
        "source_ref": source_ref,
    }


def _metric(
    metric_id: str,
    name: str,
    formula: str,
    description: str,
    boundary: str,
    grain: str,
    source_ref: str,
    pages: list[dict],
    *,
    unit: str = "人",
    data_source: str = "dim_student / fact_grade",
) -> dict:
    return {
        "metric_id": metric_id,
        "metric_code": metric_id,
        "technical_kpi_id": metric_id.lower().replace("-", "_"),
        "domain": "基础报表",
        "name": name,
        "description": description,
        "formula": formula,
        "boundary": boundary,
        "management_value": description,
        "definition_status": "published",
        "implementation_status": "verified",
        "data_source": data_source,
        "grain": grain,
        "update_cycle": "成绩、学籍或考试数据同步后",
        "version": "1.0",
        "source_kind": "formal",
        "source_ref": source_ref,
        "unit": unit,
        "pages": pages,
    }


RPT01 = "/admin/basic-reports/failure-overview"
RPT02 = "/admin/basic-reports/major-makeup-comparison"
RPT03 = "/admin/basic-reports/major-gender-failure"
RPT04A = "/admin/basic-reports/class-failure-count"
RPT04B = "/admin/basic-reports/class-score-distribution"
RPT05 = "/admin/basic-reports/course-makeup-comparison"
RPT06 = "/admin/basic-reports/cet4-pass"
RPT07 = "/admin/basic-reports/focus-students"
RPT08 = "/admin/basic-reports/academic-warning-roster"

SERVICE = "code/backend/api/basic_reports/service.py"
DEFINITIONS = "code/frontend/src/views/basic-reports"
EXPORTER = "code/backend/api/basic_reports/exporter.py"


EXTRA_VERIFIED_METRICS: tuple[dict, ...] = (
    _metric(
        "BR-VALID-RESULT-STUDENT-COUNT", "有效成绩学生数（基础报表）",
        "所选学期与授权范围内至少有一条有效成绩的去重学生数",
        "作为成绩类学生比例的可观测总体。",
        "有效成绩要求已发布、未作废且通过状态明确；不等于全部在籍学生。",
        "学生×学期×授权范围", f"{SERVICE}#_grade_state",
        [],
    ),
    _metric(
        "BR-FIRST-FAIL-STUDENT-COUNT", "补考前挂科学生数",
        "至少一门课程首次普通考试有效结果不及格的去重学生数",
        "观察首次考试阶段受到不及格影响的学生规模。",
        "按学生去重；首次结果与后续补考、重修结果分开。",
        "学生×学期×授权范围", f"{SERVICE}#_grade_state",
        [
            _page(RPT01, "已挂人数", f"{DEFINITIONS}/failure-overview/reportDefinition.ts", description="年级总体补考前挂科学生数。"),
            _page(RPT02, "已挂人数", f"{DEFINITIONS}/major-makeup-comparison/reportDefinition.ts", description="专业补考前挂科学生数。"),
            _page(RPT01, "已挂人数导出", EXPORTER, usage_type="export"),
            _page(RPT02, "已挂人数导出", EXPORTER, usage_type="export"),
        ],
    ),
    _metric(
        "BR-CURRENT-FAIL-STUDENT-COUNT", "补考后仍挂科学生数",
        "首次普通考试不及格，且截至所选学期相关课程仍不存在通过结果的去重学生数",
        "观察首次不及格学生经补考或重修后仍未解决的规模。",
        "只在首次不及格学生课程闭合集合内判断后续状态，所以人数不大于补考前挂科学生数。",
        "学生×学期×授权范围", f"{SERVICE}#_grade_state",
        [
            _page(RPT01, "在挂人数", f"{DEFINITIONS}/failure-overview/reportDefinition.ts"),
            _page(RPT02, "在挂人数", f"{DEFINITIONS}/major-makeup-comparison/reportDefinition.ts"),
            _page(RPT01, "在挂人数导出", EXPORTER, usage_type="export"),
            _page(RPT02, "在挂人数导出", EXPORTER, usage_type="export"),
        ],
    ),
    _metric(
        "BR-RPT01-FIRST-FAIL-RATE", "年级补考前挂科学生率",
        "补考前挂科学生数 ÷ 有效成绩学生数",
        "比较年级总体首次考试挂科学生比例。",
        "分母是有有效成绩学生，不是年级全部在籍学生；性别行比例仍使用总体有效成绩学生作为分母。",
        "年级×学期×授权范围", f"{SERVICE}#_report_01",
        [
            _page(RPT01, "已挂人数比例", f"{DEFINITIONS}/failure-overview/reportDefinition.ts"),
            _page(RPT01, "已挂人数比例导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT01-CURRENT-FAIL-RATE", "年级补考后在挂学生率",
        "补考后仍挂科学生数 ÷ 有效成绩学生数",
        "比较年级总体仍未解决课程的学生比例。",
        "分母是有有效成绩学生，不是年级全部在籍学生；性别行比例使用同一总体分母。",
        "年级×学期×授权范围", f"{SERVICE}#_report_01",
        [
            _page(RPT01, "在挂人数比例", f"{DEFINITIONS}/failure-overview/reportDefinition.ts"),
            _page(RPT01, "在挂人数比例导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT02-FIRST-FAIL-RATE", "专业补考前挂科学生率",
        "专业补考前挂科学生数 ÷ 专业授权在籍学生数",
        "比较各专业首次考试挂科学生占在籍学生的比例。",
        "分母包括所选专业授权范围内在籍学生，和RPT-01、RPT-03的有效成绩分母不同。",
        "专业×年级×学期", f"{SERVICE}#_report_02",
        [
            _page(RPT02, "挂科率（补考前）", f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue"),
            _page(RPT02, "挂科率（补考前）表头公式", f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue", usage_type="tooltip"),
            _page(RPT02, "挂科率（补考前）导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT02-CURRENT-FAIL-RATE", "专业补考后在挂学生率",
        "专业补考后仍挂科学生数 ÷ 专业授权在籍学生数",
        "比较各专业首次挂科学生在后续考试后仍未解决的在籍学生比例。",
        "只判断首次挂科闭合集合；分母是专业在籍学生。",
        "专业×年级×学期", f"{SERVICE}#_report_02",
        [
            _page(RPT02, "挂科率（补考后）", f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue"),
            _page(RPT02, "挂科率（补考后）表头公式", f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue", usage_type="tooltip"),
            _page(RPT02, "挂科率（补考后）导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT02-NON-CURRENT-FAIL-RATE", "专业非在挂学生率",
        "（专业授权在籍学生数－补考后仍挂科学生数）÷专业授权在籍学生数",
        "展示当前不在首次挂科未解决集合中的专业学生比例。",
        "页面简称“通过率”，但它不是参加补考学生中的补考通过率。",
        "专业×年级×学期", f"{SERVICE}#_report_02",
        [
            _page(RPT02, "通过率", f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue"),
            _page(RPT02, "通过率表头公式", f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue", usage_type="tooltip"),
            _page(RPT02, "通过率导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-GENDER-CURRENT-FAIL-RATE", "分性别当前挂科学生率",
        "指定性别当前仍有未通过课程的学生数 ÷ 该性别有效成绩学生数",
        "比较专业内不同性别学生的当前挂科比例。",
        "性别缺失学生单独计入质量信息；不能与RPT-01性别行占总体的比例合并。",
        "专业×性别×年级×学期", f"{SERVICE}#_report_03",
        [
            _page(RPT03, "男生挂科率", f"{DEFINITIONS}/major-gender-failure/reportDefinition.ts", occurrence="table:maleFailureRate"),
            _page(RPT03, "女生挂科率", f"{DEFINITIONS}/major-gender-failure/reportDefinition.ts", occurrence="table:femaleFailureRate"),
            _page(RPT03, "分性别挂科率导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-FAIL-COURSE-BAND-STUDENT-COUNT", "挂科课程门数分档学生数",
        "先计算每名学生截至所选学期当前未通过的不同课程数，再按1至2门、3至5门、6门及以上分档统计人数",
        "识别不同挂科门数区间的班级学生规模。",
        "课程按学生去重并取当前有效状态；页面“5科以上”实际执行6门及以上。",
        "行政班×挂科门数档×学期", f"{SERVICE}#_report_04a",
        [
            _page(RPT04A, "1-2科", f"{DEFINITIONS}/class-failure-count/reportDefinition.ts", occurrence="table:oneToTwo"),
            _page(RPT04A, "3-5科", f"{DEFINITIONS}/class-failure-count/reportDefinition.ts", occurrence="table:threeToFive"),
            _page(RPT04A, "6科及以上", f"{DEFINITIONS}/class-failure-count/reportDefinition.ts", occurrence="table:sixOrMore"),
            _page(RPT04A, "挂科门数分档导出", EXPORTER, usage_type="export"),
        ],
    ),
    _metric(
        "BR-WEIGHTED-SCORE", "学生学分加权成绩",
        "Σ（有效成绩×课程学分）÷Σ课程学分；学分合计为0时退化为有效成绩算术平均",
        "作为专业内成绩排序和档位划分的基础值。",
        "只纳入所选学期有效数值成绩；该值当前不直接显示，但实际决定排名档位。",
        "学生×学期", f"{SERVICE}#_report_04b",
        [], unit="分",
    ),
    _metric(
        "BR-RANKED-STUDENT-COUNT", "可参与专业成绩排名学生数",
        "所选专业和学期内存在有效成绩、能够计算学分加权成绩的去重学生数",
        "说明成绩档位实际覆盖人数。",
        "不等于行政班全部学生数；无有效成绩学生不进入排名。",
        "行政班×专业×学期", f"{SERVICE}#_report_04b",
        [
            _page(RPT04B, "总人数（可排名）", f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts", occurrence="table:rankedStudents"),
            _page(RPT04B, "可排名人数导出", EXPORTER, usage_type="export"),
        ],
    ),
    _metric(
        "BR-MAJOR-SCORE-BAND-STUDENT-COUNT", "专业成绩档位班级学生数",
        "学生按专业内学分加权成绩稳定排序后切分前20%、20%至50%、50%至80%和后20%，再按行政班统计人数",
        "比较班级学生在专业成绩序列中的分布。",
        "档位按专业总体确定，不是在每个班级内重新排名；同分仍按学号稳定排序。",
        "行政班×专业成绩档×学期", f"{SERVICE}#_report_04b",
        [
            _page(RPT04B, "专业前20%人数", f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts", occurrence="table:top20"),
            _page(RPT04B, "专业20%-50%人数", f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts", occurrence="table:top20To50"),
            _page(RPT04B, "专业50%-80%人数", f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts", occurrence="table:top50To80"),
            _page(RPT04B, "专业后20%人数", f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts", occurrence="table:bottom20"),
            _page(RPT04B, "专业成绩档位导出", EXPORTER, usage_type="export"),
        ],
    ),
    _metric(
        "BR-RPT05-MAJOR-FIRST-FAIL-RATE", "课程专业首次挂科学生率",
        "该专业该课程首次考试不及格学生数 ÷ 该专业该课程首次结果明确学生数",
        "比较课程在不同专业学生中的首次考试挂科比例。",
        "分母不是页面同列的专业在籍人数，也不同于RPT-02专业挂科率分母。",
        "课程×专业×学期", f"{SERVICE}#_report_05",
        [
            _page(RPT05, "补考前专业挂科率", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedBeforeRate"),
            _page(RPT05, "补考前专业挂科率导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT05-COURSE-FIRST-FAIL-RATE", "课程总体首次挂科学生率",
        "该课程跨专业首次考试不及格去重学生数 ÷ 该课程首次结果明确去重学生数",
        "观察课程总体首次考试挂科比例。",
        "跨专业按学生去重；不能由各专业比例简单平均。",
        "课程×学期", f"{SERVICE}#_report_05",
        [
            _page(RPT05, "补考前课程总挂科率", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedBeforeCourseRate"),
            _page(RPT05, "补考前课程总挂科率导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT05-MAJOR-CURRENT-FAIL-RATE", "课程专业补考后挂科学生率",
        "该专业该课程首次不及格且截至所选学期仍未通过学生数 ÷ 该专业该课程首次结果明确学生数",
        "比较课程在各专业中的补考后未解决比例。",
        "仅在首次结果明确总体中计算，和专业全部在籍学生分母不同。",
        "课程×专业×学期", f"{SERVICE}#_report_05",
        [
            _page(RPT05, "补考后专业挂科率", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedAfterRate"),
            _page(RPT05, "补考后专业挂科率导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT05-COURSE-CURRENT-FAIL-RATE", "课程总体补考后挂科学生率",
        "该课程跨专业首次不及格且截至所选学期仍未通过去重学生数 ÷ 该课程首次结果明确去重学生数",
        "观察课程总体补考后仍未解决的学生比例。",
        "跨专业按学生去重；不能由专业比例直接汇总。",
        "课程×学期", f"{SERVICE}#_report_05",
        [
            _page(RPT05, "补考后课程总挂科率", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedAfterCourseRate"),
            _page(RPT05, "补考后课程总挂科率导出", EXPORTER, usage_type="export"),
        ], unit="%",
    ),
    _metric(
        "BR-RPT05-MAKEUP-PASSED-STUDENT-COUNT", "课程补考通过学生数",
        "该课程首次考试不及格且至少存在一次明确通过补考记录的去重学生数",
        "观察补考后已有明确通过证据的学生规模。",
        "这是人数，不是补考通过率；多次补考通过仍按学生去重。",
        "课程×专业×学期", f"{SERVICE}#_report_05",
        [
            _page(RPT05, "补考通过人数", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:makeupPassedStudents"),
            _page(RPT05, "补考通过人数导出", EXPORTER, usage_type="export"),
        ],
    ),
    _metric(
        "BR-CET4-PASSED-STUDENT-COUNT", "大学英语四级累计通过学生数",
        "截至所选学期至少一次大学英语四级通过的去重学生数",
        "观察班级累计四级通过规模。",
        "重复通过只计一次；所选学期是累计截止点。",
        "行政班×截至学期", f"{SERVICE}#_report_06",
        [
            _page(RPT06, "四级通过人数", f"{DEFINITIONS}/cet4-pass/reportDefinition.ts"),
            _page(RPT06, "四级通过人数导出", EXPORTER, usage_type="export"),
        ], data_source="dim_student / external_exam_result",
    ),
    _metric(
        "BR-CET4-PASS-RATE", "大学英语四级累计通过率",
        "大学英语四级累计通过学生数 ÷ 授权班级本科在籍学生数",
        "比较各班截至所选学期的四级累计通过水平。",
        "分母是授权本科在籍学生，不是参加四级考试学生。",
        "行政班×截至学期", f"{SERVICE}#_report_06",
        [
            _page(RPT06, "四级通过率", f"{DEFINITIONS}/cet4-pass/reportDefinition.ts"),
            _page(RPT06, "四级通过率导出", EXPORTER, usage_type="export"),
        ], unit="%", data_source="dim_student / external_exam_result",
    ),
    _metric(
        "BR-CET4-PASS-RATE-RANK", "班级四级累计通过率排名",
        "按四级累计通过率降序执行稠密排名，同率同名次",
        "定位当前范围内四级累计通过率相对位置。",
        "排名仅在当前授权范围和筛选后的班级集合内有效。",
        "行政班×截至学期×授权比较范围", f"{SERVICE}#_report_06",
        [
            _page(RPT06, "四级通过率排行", f"{DEFINITIONS}/cet4-pass/reportDefinition.ts"),
            _page(RPT06, "通过率前三名视觉标记", f"{DEFINITIONS}/cet4-pass/Cet4PassTable.vue", usage_type="style"),
            _page(RPT06, "四级通过率排行导出", EXPORTER, usage_type="export"),
        ], unit="名次", data_source="dim_student / external_exam_result",
    ),
    _metric(
        "BR-R2-UNRESOLVED-COURSE-COUNT", "最近两学期未解决课程门数",
        "最近两个学期内存在不及格记录，且截至所选学期不存在任何通过记录的不同课程数",
        "作为重点关注和校级学业警示名单的课程风险证据。",
        "RPT-07与RPT-08当前共用同一R2/R2W算法；不能据报表名称制造第二套名单算法。",
        "学生×截至学期", f"{SERVICE}#_report_07",
        [
            _page(RPT07, "挂科门数", f"{DEFINITIONS}/focus-students/reportDefinition.ts"),
            _page(RPT08, "挂科门数", f"{DEFINITIONS}/academic-warning-roster/reportDefinition.ts"),
            _page(RPT07, "挂科门数导出", EXPORTER, usage_type="export"),
            _page(RPT08, "挂科门数导出", EXPORTER, usage_type="export"),
        ], unit="门",
    ),
    _metric(
        "BR-R2-UNRESOLVED-FAILED-CREDITS", "最近两学期未解决挂科学分",
        "最近两学期未解决课程各取最新失败证据后合计课程学分",
        "说明重点关注名单中尚未解决课程对应的学分规模。",
        "同一课程只采用最新失败证据；课程学分缺失时按当前服务规则处理。",
        "学生×截至学期", f"{SERVICE}#_report_07",
        [
            _page(RPT07, "挂科学分", f"{DEFINITIONS}/focus-students/reportDefinition.ts"),
            _page(RPT08, "挂科学分", f"{DEFINITIONS}/academic-warning-roster/reportDefinition.ts"),
            _page(RPT07, "挂科学分导出", EXPORTER, usage_type="export"),
            _page(RPT08, "挂科学分导出", EXPORTER, usage_type="export"),
        ], unit="学分",
    ),
)


VERIFIED_ALIASES: tuple[dict, ...] = (
    {"metric_id": "BR-RPT02-NON-CURRENT-FAIL-RATE", "alias": "通过率", "alias_type": "ambiguous_display", "source_ref": f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue"},
    {"metric_id": "BR-FAIL-COURSE-BAND-STUDENT-COUNT", "alias": "5科以上", "alias_type": "incorrect_display", "source_ref": f"{DEFINITIONS}/class-failure-count/reportDefinition.ts"},
    {"metric_id": "BR-RANKED-STUDENT-COUNT", "alias": "总人数", "alias_type": "ambiguous_display", "source_ref": f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts"},
)


VERIFIED_DEPENDENCIES: tuple[dict, ...] = (
    {"source_metric_id": "BR-RPT01-FIRST-FAIL-RATE", "target_metric_id": "BR-FIRST-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "补考前挂科学生数是该比例分子。", "source_ref": f"{SERVICE}#_report_01"},
    {"source_metric_id": "BR-RPT01-FIRST-FAIL-RATE", "target_metric_id": "BR-VALID-RESULT-STUDENT-COUNT", "relation_type": "denominator", "description": "有效成绩学生数是该比例分母。", "source_ref": f"{SERVICE}#_report_01"},
    {"source_metric_id": "BR-RPT01-CURRENT-FAIL-RATE", "target_metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "补考后仍挂科学生数是该比例分子。", "source_ref": f"{SERVICE}#_report_01"},
    {"source_metric_id": "BR-RPT01-CURRENT-FAIL-RATE", "target_metric_id": "BR-VALID-RESULT-STUDENT-COUNT", "relation_type": "denominator", "description": "有效成绩学生数是该比例分母。", "source_ref": f"{SERVICE}#_report_01"},
    {"source_metric_id": "BR-RPT02-FIRST-FAIL-RATE", "target_metric_id": "BR-FIRST-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "专业补考前挂科学生数是分子。", "source_ref": f"{SERVICE}#_report_02"},
    {"source_metric_id": "BR-RPT02-FIRST-FAIL-RATE", "target_metric_id": "O-01", "relation_type": "denominator", "description": "专业授权在籍学生数是分母。", "source_ref": f"{SERVICE}#_report_02"},
    {"source_metric_id": "BR-RPT02-CURRENT-FAIL-RATE", "target_metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "专业补考后仍挂科学生数是分子。", "source_ref": f"{SERVICE}#_report_02"},
    {"source_metric_id": "BR-RPT02-CURRENT-FAIL-RATE", "target_metric_id": "O-01", "relation_type": "denominator", "description": "专业授权在籍学生数是分母。", "source_ref": f"{SERVICE}#_report_02"},
    {"source_metric_id": "BR-RPT02-NON-CURRENT-FAIL-RATE", "target_metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", "relation_type": "component", "description": "页面通过率由专业人数减去仍挂科学生数后计算。", "source_ref": f"{SERVICE}#_report_02"},
    {"source_metric_id": "BR-RPT02-NON-CURRENT-FAIL-RATE", "target_metric_id": "O-01", "relation_type": "denominator", "description": "专业授权在籍学生数同时作为差值基数与分母。", "source_ref": f"{SERVICE}#_report_02"},
    {"source_metric_id": "BR-MAJOR-SCORE-BAND-STUDENT-COUNT", "target_metric_id": "BR-WEIGHTED-SCORE", "relation_type": "ranking_input", "description": "专业成绩档位由学生学分加权成绩排序产生。", "source_ref": f"{SERVICE}#_report_04b"},
    {"source_metric_id": "BR-MAJOR-SCORE-BAND-STUDENT-COUNT", "target_metric_id": "BR-RANKED-STUDENT-COUNT", "relation_type": "population", "description": "档位切分总体是可参与专业成绩排名的学生。", "source_ref": f"{SERVICE}#_report_04b"},
    {"source_metric_id": "BR-RPT05-MAJOR-FIRST-FAIL-RATE", "target_metric_id": "BR-FIRST-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "课程专业首次挂科学生数是分子。", "source_ref": f"{SERVICE}#_report_05"},
    {"source_metric_id": "BR-RPT05-COURSE-FIRST-FAIL-RATE", "target_metric_id": "BR-FIRST-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "课程跨专业首次挂科去重学生数是分子。", "source_ref": f"{SERVICE}#_report_05"},
    {"source_metric_id": "BR-RPT05-MAJOR-CURRENT-FAIL-RATE", "target_metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "课程专业补考后仍挂科学生数是分子。", "source_ref": f"{SERVICE}#_report_05"},
    {"source_metric_id": "BR-RPT05-COURSE-CURRENT-FAIL-RATE", "target_metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", "relation_type": "numerator", "description": "课程跨专业补考后仍挂科去重学生数是分子。", "source_ref": f"{SERVICE}#_report_05"},
    {"source_metric_id": "BR-CET4-PASS-RATE", "target_metric_id": "BR-CET4-PASSED-STUDENT-COUNT", "relation_type": "numerator", "description": "累计通过学生数是累计通过率分子。", "source_ref": f"{SERVICE}#_report_06"},
    {"source_metric_id": "BR-CET4-PASS-RATE", "target_metric_id": "O-01", "relation_type": "denominator", "description": "授权班级本科在籍学生数是累计通过率分母。", "source_ref": f"{SERVICE}#_report_06"},
    {"source_metric_id": "BR-CET4-PASS-RATE-RANK", "target_metric_id": "BR-CET4-PASS-RATE", "relation_type": "ranking_input", "description": "班级排名按累计通过率降序计算。", "source_ref": f"{SERVICE}#_report_06"},
)


VERIFIED_RULE_BINDINGS: tuple[dict, ...] = (
    {"metric_id": "BR-R2-UNRESOLVED-COURSE-COUNT", "rule_type": "academic_alert", "rule_id": "R2", "role": "input", "description": "未解决课程门数达到3门进入严重重点关注。", "source_ref": "code/backend/api/basic_reports/rule_registry.py#R2"},
    {"metric_id": "BR-R2-UNRESOLVED-COURSE-COUNT", "rule_type": "academic_alert", "rule_id": "R2W", "role": "input", "description": "未解决课程门数等于2门进入警告关注。", "source_ref": "code/backend/api/basic_reports/rule_registry.py#R2W"},
)


# Cross-module usages for stable metrics already defined by the teaching catalog.
VERIFIED_USAGE_POINTS: tuple[dict, ...] = (
    {"metric_id": "O-01", **_page(RPT01, "年级总人数", f"{DEFINITIONS}/failure-overview/reportDefinition.ts", occurrence="table:studentCount")},
    {"metric_id": "O-01", **_page(RPT02, "专业人数", f"{DEFINITIONS}/major-makeup-comparison/reportDefinition.ts", occurrence="table:studentCount")},
    {"metric_id": "O-01", **_page(RPT03, "专业人数", f"{DEFINITIONS}/major-gender-failure/reportDefinition.ts", occurrence="table:studentCount")},
    {"metric_id": "O-01", **_page(RPT04A, "班级总人数", f"{DEFINITIONS}/class-failure-count/reportDefinition.ts", occurrence="table:studentCount")},
    {"metric_id": "O-01", **_page(RPT05, "专业人数", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:majorStudentCount")},
    {"metric_id": "O-01", **_page(RPT06, "班级总人数", f"{DEFINITIONS}/cet4-pass/reportDefinition.ts", occurrence="table:studentCount")},
    {"metric_id": "O-10", **_page(RPT03, "整体挂科率", f"{DEFINITIONS}/major-gender-failure/reportDefinition.ts", occurrence="table:failureRate")},
    {"metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", **_page(RPT03, "整体挂科人数", f"{DEFINITIONS}/major-gender-failure/reportDefinition.ts", occurrence="table:failedStudents")},
    {"metric_id": "BR-FIRST-FAIL-STUDENT-COUNT", **_page(RPT05, "补考前专业挂科人数", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedBeforeStudents")},
    {"metric_id": "BR-FIRST-FAIL-STUDENT-COUNT", **_page(RPT05, "补考前课程挂科总人数", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedBeforeCourseTotal")},
    {"metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", **_page(RPT05, "补考后专业挂科人数", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedAfterStudents")},
    {"metric_id": "BR-CURRENT-FAIL-STUDENT-COUNT", **_page(RPT05, "补考后课程挂科总人数", f"{DEFINITIONS}/course-makeup-comparison/reportDefinition.ts", occurrence="table:failedAfterCourseTotal")},
)


VERIFIED_ISSUES: tuple[dict, ...] = (
    {"metric_id": "BR-FAIL-COURSE-BAND-STUDENT-COUNT", "issue_type": "display_formula_mismatch", "severity": "error", "status": "open", "description": "RPT-04A页面及导出显示“5科以上”，后端实际分档条件是未通过课程数大于等于6。", "source_ref": f"{SERVICE}#_report_04a"},
    {"metric_id": "BR-RANKED-STUDENT-COUNT", "issue_type": "display_semantic_mismatch", "severity": "error", "status": "open", "description": "RPT-04B列名“总人数”绑定rankedStudents，仅包含有有效成绩且可排名学生，不是班级全部学生。", "source_ref": f"{DEFINITIONS}/class-score-distribution/reportDefinition.ts"},
    {"metric_id": "BR-RPT05-MAKEUP-PASSED-STUDENT-COUNT", "issue_type": "rule_output_mismatch", "severity": "warning", "status": "open", "description": "规则登记BR-MAKEUP-PASS描述补考通过率，当前报表实际输出补考通过去重学生数，未输出该通过率。", "source_ref": "code/backend/api/basic_reports/rule_registry.py#BR-MAKEUP-PASS"},
    {"metric_id": "BR-R2-UNRESOLVED-COURSE-COUNT", "issue_type": "shared_algorithm_different_report_names", "severity": "warning", "status": "open", "description": "RPT-07与RPT-08当前共用_report_07及R2/R2W算法；校级学业警示是否应有独立正式来源仍需业务确认。", "source_ref": f"{SERVICE}#build_report"},
    {"metric_id": "BR-RPT02-NON-CURRENT-FAIL-RATE", "issue_type": "ambiguous_name", "severity": "warning", "status": "open", "description": "页面简称“通过率”，其公式不是补考通过学生数除以参加补考学生数，容易与正式补考通过率混淆。", "source_ref": f"{DEFINITIONS}/major-makeup-comparison/MajorMakeupComparisonTable.vue"},
)
