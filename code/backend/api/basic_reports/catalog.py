"""九张基础报表的稳定目录；菜单、接口和前端均使用这些标识。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportDefinition:
    report_id: str
    slug: str
    title: str
    menu_path: str
    kind: str
    supports_detail: bool = False
    required_filters: tuple[str, ...] = ("semesterId", "entryGrade")
    result_columns: tuple[tuple[str, str], ...] = ()
    merge_by: tuple[tuple[str, str], ...] = ()


REPORTS = {
    item.report_id: item for item in (
        ReportDefinition(
            "RPT-01", "rpt-01", "年级总体挂科情况",
            "/admin/basic-reports/failure-overview", "aggregate",
            result_columns=(("category", "本科生"), ("gender", "性别"),
                            ("countDisplay", "人数"), ("rateDisplay", "比例")),
            merge_by=(("category", "categoryKey"),),
        ),
        ReportDefinition("RPT-02", "rpt-02", "各专业补考前后挂科率比较",
                         "/admin/basic-reports/major-makeup-comparison", "aggregate",
                         result_columns=(("majorName", "专业名称"), ("studentCountDisplay", "专业人数"),
                                         ("failedBeforeDisplay", "已挂人数"), ("failedBeforeRate", "挂科率（补考前）"),
                                         ("failedAfterDisplay", "在挂人数"), ("failedAfterRate", "挂科率（补考后）"),
                                         ("passRate", "通过率"))),
        ReportDefinition("RPT-03", "rpt-03", "各专业整体与男女挂科率比较",
                         "/admin/basic-reports/major-gender-failure", "aggregate",
                         result_columns=(("majorName", "专业"), ("studentCountDisplay", "专业人数"),
                                         ("failedStudentsDisplay", "整体挂科人数"), ("failureRate", "整体挂科率"),
                                         ("maleFailureDisplay", "男生挂科率"), ("femaleFailureDisplay", "女生挂科率"))),
        ReportDefinition("RPT-04A", "rpt-04a", "各班级挂科门数具体情况",
                         "/admin/basic-reports/class-failure-count", "distribution",
                         required_filters=("semesterId", "entryGrade"),
                         result_columns=(("classCode", "班级"), ("studentCount", "总人数"),
                                         ("oneToTwo", "1-2科"), ("threeToFive", "3-5科"),
                                         ("sixOrMore", "5科以上"))),
        ReportDefinition("RPT-04B", "rpt-04b", "各班级成绩分布",
                         "/admin/basic-reports/class-score-distribution", "distribution",
                         required_filters=("semesterId", "entryGrade", "organizationId", "majorCode"),
                         result_columns=(("classCode", "班级"), ("rankedStudents", "总人数"),
                                         ("top20Display", "专业前20%"), ("top20To50Display", "专业前20-50%"),
                                         ("top50To80Display", "专业前50-80%"), ("bottom20Display", "专业后20%"))),
        ReportDefinition("RPT-05", "rpt-05", "补考前后课程通过情况对比",
                         "/admin/basic-reports/course-makeup-comparison", "aggregate",
                         required_filters=("semesterId",),
                         result_columns=(("course", "科目"), ("majorName", "专业"), ("majorStudentCount", "专业人数"),
                                         ("failedBeforeStudents", "挂科人数"), ("failedBeforeRate", "专业挂科率"),
                                         ("failedBeforeCourseTotal", "挂科总人数"), ("failedBeforeCourseRate", "总挂科率"),
                                         ("failedAfterStudents", "挂科人数"), ("failedAfterRate", "专业挂科率"),
                                         ("failedAfterCourseTotal", "挂科总人数"), ("failedAfterCourseRate", "总挂科率"),
                                         ("makeupPassedStudents", "补考通过人数")),
                         merge_by=(("course", "courseKey"), ("failedBeforeCourseTotal", "courseKey"),
                                   ("failedBeforeCourseRate", "courseKey"), ("failedAfterCourseTotal", "courseKey"),
                                   ("failedAfterCourseRate", "courseKey"))),
        ReportDefinition("RPT-06", "rpt-06", "各班大学英语四级通过情况",
                         "/admin/basic-reports/cet4-pass", "aggregate",
                         result_columns=(("classCode", "班级"), ("studentCount", "总人数"),
                                         ("cet4PassedStudents", "四级通过人数"), ("cet4PassRate", "四级通过率"),
                                         ("cet4PassRateRank", "四级通过率排行"))),
        ReportDefinition("RPT-07", "rpt-07", "重点关注学生名单",
                         "/admin/basic-reports/focus-students", "roster", True,
                         required_filters=("semesterId",),
                         result_columns=(("sequence", "序号"), ("name", "姓名"), ("studentId", "学号"),
                                         ("majorClass", "专业班级"), ("mentor", "导师"),
                                         ("failedCredits", "挂科学分"), ("unresolvedCourseCount", "挂科门数"),
                                         ("courseEvidence", "具体情况"))),
        ReportDefinition("RPT-08", "rpt-08", "校级学业警示学生名单",
                         "/admin/basic-reports/academic-warning-roster", "roster", True,
                         required_filters=("semesterId",),
                         result_columns=(("sequence", "序号"), ("name", "姓名"), ("studentId", "学号"),
                                         ("majorClass", "专业班级"), ("mentor", "导师"),
                                         ("failedCredits", "挂科学分"), ("unresolvedCourseCount", "挂科门数"),
                                         ("courseEvidence", "具体情况"))),
    )
}
REPORT_BY_SLUG = {item.slug: item for item in REPORTS.values()}


def get_report(slug: str) -> ReportDefinition:
    try:
        return REPORT_BY_SLUG[slug.lower()]
    except KeyError as exc:
        raise KeyError(f"unknown basic report: {slug}") from exc
