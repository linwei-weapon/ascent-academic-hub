import type { DataTableColumn } from '@/components/DataTable.vue'

export type BasicReportFilter = 'semesterId' | 'entryGrade' | 'organizationId' | 'majorCode' | 'classCode'

export interface BasicReportDefinition {
  reportId: string
  slug: string
  title: string
  path: string
  requiredFilters: BasicReportFilter[]
  columns: DataTableColumn[]
  mergeBy?: Record<string, string>
}

const pct = (_row: any, _column: any, value: number | null) => value == null ? '—' : `${(value * 100).toFixed(2)}%`
const dash = (_row: any, _column: any, value: any) => value == null || value === '' ? '—' : value
const c = (key: string, label: string, extra: Partial<DataTableColumn> = {}): DataTableColumn => ({
  key, label, minWidth: 120, tooltip: true, formatter: dash, required: true, ...extra,
})
const rate = (key: string, label: string) => c(key, label, { align: 'right', formatter: pct })
const base: BasicReportFilter[] = ['semesterId', 'entryGrade']

export const reportDefinitions: Record<string, BasicReportDefinition> = {
  '/admin/basic-reports/failure-overview': {
    reportId: 'RPT-01', slug: 'rpt-01', title: '年级总体挂科情况', path: '/admin/basic-reports/failure-overview', requiredFilters: base,
    columns: [c('category', '本科生', { minWidth: 300, fixed: 'left', region: 'identity' }), c('gender', '性别', { width: 90 }), c('countDisplay', '人数'), c('rateDisplay', '比例', { minWidth: 190, align: 'right' })],
    mergeBy: { category: 'categoryKey' },
  },
  '/admin/basic-reports/major-makeup-comparison': {
    reportId: 'RPT-02', slug: 'rpt-02', title: '各专业补考前后挂科率比较', path: '/admin/basic-reports/major-makeup-comparison', requiredFilters: base,
    columns: [c('majorName', '专业名称', { minWidth: 180, fixed: 'left', region: 'identity' }), c('studentCountDisplay', '专业人数'), c('failedBeforeDisplay', '已挂人数'), rate('failedBeforeRate', '挂科率（补考前）'), c('failedAfterDisplay', '在挂人数'), rate('failedAfterRate', '挂科率（补考后）'), rate('passRate', '通过率')],
  },
  '/admin/basic-reports/major-gender-failure': {
    reportId: 'RPT-03', slug: 'rpt-03', title: '各专业整体与男女挂科率比较', path: '/admin/basic-reports/major-gender-failure', requiredFilters: base,
    columns: [c('majorName', '专业', { minWidth: 220, fixed: 'left', region: 'identity' }), c('studentCountDisplay', '专业人数'), c('failedStudentsDisplay', '整体挂科人数'), rate('failureRate', '整体挂科率'), c('maleFailureDisplay', '男生挂科率', { minWidth: 180 }), c('femaleFailureDisplay', '女生挂科率', { minWidth: 180 })],
  },
  '/admin/basic-reports/class-failure-count': {
    reportId: 'RPT-04A', slug: 'rpt-04a', title: '各班级挂科门数具体情况', path: '/admin/basic-reports/class-failure-count', requiredFilters: base,
    columns: [c('classCode', '班级', { minWidth: 180, fixed: 'left', region: 'identity' }), c('studentCount', '总人数'), c('oneToTwo', '1-2科'), c('threeToFive', '3-5科'), c('sixOrMore', '5科以上')],
  },
  '/admin/basic-reports/class-score-distribution': {
    reportId: 'RPT-04B', slug: 'rpt-04b', title: '各班级成绩分布', path: '/admin/basic-reports/class-score-distribution', requiredFilters: [...base, 'organizationId', 'majorCode'],
    columns: [c('classCode', '班级', { minWidth: 180, fixed: 'left', region: 'identity' }), c('rankedStudents', '总人数'), c('top20Display', '专业前20%', { minWidth: 150 }), c('top20To50Display', '专业前20-50%', { minWidth: 170 }), c('top50To80Display', '专业前50-80%', { minWidth: 170 }), c('bottom20Display', '专业后20%', { minWidth: 150 })],
  },
  '/admin/basic-reports/course-makeup-comparison': {
    reportId: 'RPT-05', slug: 'rpt-05', title: '补考前后课程通过情况对比', path: '/admin/basic-reports/course-makeup-comparison', requiredFilters: ['semesterId'],
    columns: [c('course', '科目'), c('majorName', '专业'), c('majorStudentCount', '专业人数'), c('failedBeforeStudents', '挂科人数'), rate('failedBeforeRate', '专业挂科率'), c('failedBeforeCourseTotal', '挂科总人数'), rate('failedBeforeCourseRate', '总挂科率'), c('failedAfterStudents', '挂科人数'), rate('failedAfterRate', '专业挂科率'), c('failedAfterCourseTotal', '挂科总人数'), rate('failedAfterCourseRate', '总挂科率'), c('makeupPassedStudents', '补考通过人数')],
    mergeBy: { course: 'courseKey', failedBeforeCourseTotal: 'courseKey', failedBeforeCourseRate: 'courseKey', failedAfterCourseTotal: 'courseKey', failedAfterCourseRate: 'courseKey' },
  },
  '/admin/basic-reports/cet4-pass': {
    reportId: 'RPT-06', slug: 'rpt-06', title: '各班大学英语四级通过情况', path: '/admin/basic-reports/cet4-pass', requiredFilters: base,
    columns: [c('classCode', '班级', { minWidth: 180, fixed: 'left', region: 'identity' }), c('studentCount', '总人数'), c('cet4PassedStudents', '四级通过人数'), rate('cet4PassRate', '四级通过率'), c('cet4PassRateRank', '四级通过率排行', { minWidth: 140, align: 'center', required: true })],
  },
  '/admin/basic-reports/focus-students': {
    reportId: 'RPT-07', slug: 'rpt-07', title: '重点关注学生名单', path: '/admin/basic-reports/focus-students', requiredFilters: ['semesterId'],
    columns: [c('sequence', '序号', { width: 76, fixed: 'left', region: 'identity' }), c('name', '姓名', { fixed: 'left', region: 'identity' }), c('studentId', '学号', { minWidth: 145, fixed: 'left', region: 'identity' }), c('majorClass', '专业班级', { minWidth: 220 }), c('mentor', '导师'), c('failedCredits', '挂科学分'), c('unresolvedCourseCount', '挂科门数'), c('courseEvidence', '具体情况', { minWidth: 390, tooltip: false })],
  },
  '/admin/basic-reports/academic-warning-roster': {
    reportId: 'RPT-08', slug: 'rpt-08', title: '校级学业警示学生名单', path: '/admin/basic-reports/academic-warning-roster', requiredFilters: ['semesterId'],
    columns: [c('sequence', '序号', { width: 76, fixed: 'left', region: 'identity' }), c('name', '姓名', { fixed: 'left', region: 'identity' }), c('studentId', '学号', { minWidth: 145, fixed: 'left', region: 'identity' }), c('majorClass', '专业班级', { minWidth: 220 }), c('mentor', '导师'), c('failedCredits', '挂科学分'), c('unresolvedCourseCount', '挂科门数'), c('courseEvidence', '具体情况', { minWidth: 390, tooltip: false })],
  },
}
