export type DashboardHistoryMetric = {
  id: string
  label: string
  unit: string
  chart: 'ratio' | 'gpa'
  color: string
}

export const DASHBOARD_HISTORY_METRICS: Record<string, DashboardHistoryMetric> = {
  valid_result_coverage_rate: {
    id: 'valid_result_coverage_rate',
    label: '有效成绩覆盖率',
    unit: '%',
    chart: 'ratio',
    color: '#4f46e5',
  },
  current_fail_student_rate: {
    id: 'current_fail_student_rate',
    label: '挂科学生率',
    unit: '%',
    chart: 'ratio',
    color: '#e11d48',
  },
  average_student_gpa: {
    id: 'average_student_gpa',
    label: '学生平均 GPA',
    unit: '',
    chart: 'gpa',
    color: '#4f46e5',
  },
  active_alert_student_rate: {
    id: 'active_alert_student_rate',
    label: '有效预警学生率',
    unit: '%',
    chart: 'ratio',
    color: '#d97706',
  },
  first_pass_rate: {
    id: 'first_pass_rate',
    label: '首次通过率',
    unit: '%',
    chart: 'ratio',
    color: '#0d9488',
  },
  makeup_pass_rate: {
    id: 'makeup_pass_rate',
    label: '补考通过率',
    unit: '%',
    chart: 'ratio',
    color: '#4f46e5',
  },
  retake_pass_rate: {
    id: 'retake_pass_rate',
    label: '重修通过率',
    unit: '%',
    chart: 'ratio',
    color: '#d97706',
  },
  public_required_first_pass_rate: {
    id: 'public_required_first_pass_rate',
    label: '公共必修首次通过率',
    unit: '%',
    chart: 'ratio',
    color: '#0d9488',
  },
}

export const SUMMARY_HISTORY_METRIC_IDS: Record<string, string> = {
  result_coverage: 'valid_result_coverage_rate',
  current_fail_rate: 'current_fail_student_rate',
  average_gpa: 'average_student_gpa',
  active_alert_rate: 'active_alert_student_rate',
}
