// 补考前后课程通过情况对比：维护原报表编号、查询条件和结果列，计算仍由后端负责。
import type { BasicReportDefinition } from '@/types/basicReports'
import { c, rate } from '../shared/reportColumns'

export const reportDefinition: BasicReportDefinition = {
    reportId: 'RPT-05', slug: 'rpt-05', title: '补考前后课程通过情况对比', path: '/admin/basic-reports/course-makeup-comparison', requiredFilters: ['semesterId'],
    columns: [c('course', '科目'), c('majorName', '专业'), c('majorStudentCount', '专业人数'), c('failedBeforeStudents', '挂科人数'), rate('failedBeforeRate', '专业挂科率'), c('failedBeforeCourseTotal', '挂科总人数'), rate('failedBeforeCourseRate', '总挂科率'), c('failedAfterStudents', '挂科人数'), rate('failedAfterRate', '专业挂科率'), c('failedAfterCourseTotal', '挂科总人数'), rate('failedAfterCourseRate', '总挂科率'), c('makeupPassedStudents', '补考通过人数')],
    mergeBy: { course: 'courseKey', failedBeforeCourseTotal: 'courseKey', failedBeforeCourseRate: 'courseKey', failedAfterCourseTotal: 'courseKey', failedAfterCourseRate: 'courseKey' },
  }
