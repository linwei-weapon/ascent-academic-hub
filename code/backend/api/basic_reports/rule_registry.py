"""报表字段计算规则登记。

这里不是第二套指标中心，而是代码侧的可追溯清单。existing 表示复用既有
实现或指标；query_time 表示本期只在查询快照中计算且不落业务表。
"""
from __future__ import annotations

RULE_VERSION = "basic-report-v1.5"

RULES = {
    "BR-STUDENT-SCOPE": {
        "provenance": "existing",
        "source": "permission_context.v2_student_scope + dim_student",
        "formula": "本科、在校、所选入学年级且处于当前身份授权范围的去重学生",
        "boundary": "使用当前组织归属；范围缺失时拒绝，不回退全校",
    },
    "BR-VALID-GRADE": {
        "provenance": "existing",
        "source": "v2_course_pass_builder.valid_attempts",
        "formula": "is_published=1 AND is_void=0 AND is_pass IS NOT NULL",
        "boundary": "is_pass 优先使用教务源明确状态，不以页面临时分数线重判",
    },
    "BR-FIRST-RESULT": {
        "provenance": "existing",
        "source": "pass-stat-v1",
        "formula": "regular/deferred/空修读类型中的首次有效结果",
        "boundary": "当前数据修读类型为 regular/makeup/retake",
    },
    "BR-EFFECTIVE-ASOF": {
        "provenance": "query_time",
        "source": "grade-effective-v1 的所选学期截止变体",
        "formula": "同一学生课程有通过结果则取通过，否则取最近未通过",
        "boundary": "本报表查询限定所选学期；版本 basic-report-v1.5",
    },
    "BR-RETAINED-DEMOTED": {
        "provenance": "existing",
        "source": "student_status_event + dim_semester",
        "formula": "截至所选学期末存在正式“留级/降级”异动、且当前行政班责任年级等于所选年级的去重学生数；分别统计总人数、已挂、在挂及男女组",
        "boundary": "括号口径与入学年级主体人数分开计算；当前未有独立责任年级字段，v1.1严格解析行政班年级段，缺失时回退异动后年级；保留学籍不计入",
    },
    "BR-MAKEUP-PASS": {
        "provenance": "existing",
        "source": "G-13 / pass-stat-v1",
        "formula": "明确通过的补考人次 ÷ 结果明确的补考人次",
        "boundary": "不使用补考前后人数差值冒充补考通过人数",
    },
    "BR-MAJOR-MAKEUP-COMPARISON": {
        "provenance": "query_time",
        "source": "RPT-02 用户确认口径 + pass-stat-v1 + student_status_event",
        "formula": "在同一所选学期内，已挂人数为普通考试首次不及格学生；在挂人数仅统计上述集合中同一学生课程经后续有效成绩后仍未通过的学生；专业人数、已挂人数、在挂人数分别展示主人数（留降级人数）；补考前挂科率=已挂人数÷专业人数；补考后挂科率=在挂人数÷专业人数；通过率=(专业人数-在挂人数)÷专业人数",
        "boundary": "补考前后使用同一学年学期、同一学生课程集合，在挂人数不得大于已挂人数；只有重修记录而没有所选学期普通考试首次不及格记录的学生不进入本报表前后比较集合；括号留降级人数沿用 BR-RETAINED-DEMOTED 且不并入主人数和比率分母",
    },
    "BR-WEIGHTED-SCORE": {
        "provenance": "query_time",
        "source": "0728基础报表需求 5.5",
        "formula": "SUM(有效成绩×学分)/SUM(学分)，无学分时退化为算术平均",
        "boundary": "同分按稳定学号次序排列；无成绩学生单列",
    },
    "BR-CET4-CUMULATIVE": {
        "provenance": "existing",
        "source": "datasource/构造数据/{semester}.db.external_exams",
        "formula": "截至所选学期至少一次全国大学英语四级 is_passed=1 的去重学生数 ÷ 授权班级本科生数",
        "boundary": "按学期顺序累计，重复通过只计1人；查询与导出使用同一源文件版本指纹",
    },
    "BR-FOCUS-R2": {
        "provenance": "existing",
        "source": "sys_alert_rule R2/R2W + fact_alert active + fact_grade + dim_course",
        "formula": "截至所选学期的最近2学期内，不同且尚未通过课程：R2≥3门，R2W=2门；后续已有通过记录的课程移除",
        "boundary": "名单成员使用已发布活动预警；课程明细按同一R2/R2W口径复算；本模块不生成、处置或回写预警",
    },
}


REPORT_RULES = {
    "RPT-01": ["BR-STUDENT-SCOPE", "BR-VALID-GRADE", "BR-FIRST-RESULT", "BR-EFFECTIVE-ASOF", "BR-RETAINED-DEMOTED"],
    "RPT-02": ["BR-STUDENT-SCOPE", "BR-VALID-GRADE", "BR-FIRST-RESULT", "BR-EFFECTIVE-ASOF", "BR-RETAINED-DEMOTED", "BR-MAJOR-MAKEUP-COMPARISON"],
    "RPT-03": ["BR-STUDENT-SCOPE", "BR-VALID-GRADE", "BR-EFFECTIVE-ASOF"],
    "RPT-04A": ["BR-STUDENT-SCOPE", "BR-VALID-GRADE", "BR-EFFECTIVE-ASOF"],
    "RPT-04B": ["BR-STUDENT-SCOPE", "BR-VALID-GRADE", "BR-WEIGHTED-SCORE"],
    "RPT-05": ["BR-STUDENT-SCOPE", "BR-VALID-GRADE", "BR-FIRST-RESULT", "BR-MAKEUP-PASS"],
    "RPT-06": ["BR-STUDENT-SCOPE", "BR-CET4-CUMULATIVE"],
    "RPT-07": ["BR-STUDENT-SCOPE", "BR-FOCUS-R2"],
    "RPT-08": ["BR-STUDENT-SCOPE", "BR-FOCUS-R2"],
}


def rules_for(report_id: str) -> list[dict]:
    return [{"ruleId": key, **RULES[key]} for key in REPORT_RULES[report_id]]
