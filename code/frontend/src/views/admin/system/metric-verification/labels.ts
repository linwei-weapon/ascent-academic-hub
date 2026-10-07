/** 仅转换展示文字；筛选值、指标编号和后端状态保持原始契约。 */
const categoryLabels: Record<string, string> = {
  ai: 'AI 研判', display: '展示规则', interaction: '交互操作',
  metric: '指标计算', permission: '权限控制', rule: '业务规则',
}
const metricTypeLabels: Record<string, string> = {
  average: '均值', count: '数量', difference: '变化值', distribution: '分布',
  ranking: '排名', ratio: '比率', sum: '合计',
}
const statusLabels: Record<string, string> = {
  documented: '文档关系已登记', blocked: '核验条件待补齐',
  needs_confirmation: '映射待确认', pending: '待核实', unmapped: '映射待建立',
  partial: '部分映射已登记', mapped: '映射已登记',
  success: '查询成功', error: '查询失败',
  not_applicable: '不适用',
}
const parameterSourceLabels: Record<string, string> = {
  business: '业务筛选条件', batch: '数据批次：需与本次核验范围一致',
  policy: '计算口径参数：请采用已确认的业务规则',
}
const readable = (labels: Record<string, string>, value: string, fallback: string) =>
  labels[value] || (/[\u4e00-\u9fff]/.test(value) ? value : fallback)

export const categoryLabel = (value: string) => readable(categoryLabels, value, '其他需求')
export const metricTypeLabel = (value: string) => readable(metricTypeLabels, value, '指标类型待确认')
export const statusLabel = (value: string) => readable(statusLabels, value, '状态待核实')
export const parameterSourceLabel = (value: string) => readable(parameterSourceLabels, value, '查询范围参数')
export const definitionStatus = (value: string) => ({ explicit: '原文明确', confirmed: '用户已确认', pending: '口径待明确' }[value] || '状态待明确')

const resultFieldLabels: Record<string, string> = {
  matched_records: '匹配记录数', metric_value: '复算结果', candidate_metric_value: '候选复算结果',
  source_records: '原始成绩记录数', attempts: '分组中的原始人次', first_attempts: '首修人次N', first_pass: '首修通过人次P',
  record_versions: '课程×学期记录数', included_courses: '有效课程数', rule_version: '加工版本', calculated_at: '聚合计算时间',
  numerator: '分子', denominator: '分母', candidate_numerator: '候选分子', candidate_denominator: '候选分母',
  candidate_valid_attempts: '候选有效成绩人次', student_count: '学生数', attempt_count: '成绩人次',
  candidate_valid_students: '候选有效成绩学生数', candidate_delta_pp: '较上期变化（百分点）',
  course_code: '课程代码', course_name: '课程名称', semester_name: '学期名称',
  semester_start_date: '学期开始时间', attempt_id: '成绩记录标识', is_pass: '通过标记',
  is_published: '发布标记', is_void: '作废标记', grade_status: '成绩状态原值',
  state: '源端状态原值', attempt_type: '修读类型原值', is_retake: '重修标记',
  published_date_time: '发布时间', input_date_time: '录入时间', source: '数据来源',
  candidate_rank: '候选名次', comparable_colleges: '可比学院数',
  profile_ever_passed_value: '历史通过课程门数', growth_current_passed_value: '当前通过课程门数',
  candidate_passed_attempt_credits: '候选通过记录学分和',
  semester_id: '学期标识', organization_id: '组织标识', college_id: '应用表学院键', course_id: '课程标识',
  student_id: '学生标识', credits: '学分', gpa: '绩点', score: '成绩',
  deviation_pp: '偏离（百分点）', estimated_excess_students: '估算超额影响人数',
}
export const resultFieldLabel = (value: string) => resultFieldLabels[value.toLowerCase()] || value
