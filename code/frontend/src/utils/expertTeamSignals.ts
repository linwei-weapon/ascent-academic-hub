import type { TeamResult } from './expertTeam'

export interface TeamSignal { label: string; value: number | null; unit: string; note: string; tableId: string }
export function teamSignals(result: TeamResult): TeamSignal[] {
  const card = (label: string, value: unknown, unit: string, note: string, tableId: string): TeamSignal => ({
    label, value: typeof value === 'number' && Number.isFinite(value) ? value : null, unit, note,
    tableId: result.tables.some(t => t.id === tableId) ? tableId : '',
  })
  const table = (id: string) => result.tables.find(t => t.id === id)
  if (result.expert_id === 'graduation' && result.snapshot) {
    const s = result.snapshot, c = s.counts
    return [card('本次涉及学生', s.population, '人', '当前授权、方案绑定的在校学生', 'readiness'),
      card('已有课程或模块缺口', c?.explicit_gap, '人', '准备状态，不是最终资格结论', 'readiness'),
      card('到期记录待确认', c?.candidate, '人', '记录待确认不等于不符合', 'record_classes'),
      card('方案适用待确认', c?.binding_issue, '人', '先明确方案及适用年级', 'record_classes')]
  }
  if (result.expert_id === 'course') {
    const performance = table('performance')
    if (performance) return [card('本学期有记录课程', performance.rows.length, '门', '符合本次首次修读统计条件', 'performance'),
      card('有未通过记录的课程', performance.rows.filter(r => typeof r.fails === 'number' && r.fails > 0).length, '门', '用于选择研究对象，不是质量排名', 'performance')]
    const current = table('course_current')?.rows[0]
    if (current) return [card('本课涉及学生', current.students, '人', '本学期同课程去重学生', 'course_current'),
      card('首次修读未通过学生', current.failed_students, '人', '不是当前最终欠课人数', 'class_distribution'),
      card('首次修读未通过率', current.fail_rate, '%', '按记录人次计算，不是学生比例', 'course_current')]
    const trend = table('trend')
    return trend ? [card('有记录的学期', trend.rows.length, '个', '截至所选学期；不补齐空缺学期', 'trend')] : []
  }
  const c = result.comparison
  if (result.expert_id === 'program' && result.scenario === 'sequence') {
    const rows = table('schedule')?.rows
    return rows ? [card('本次展示课程', rows.length, '门', '课程安排，不代表全部必须修读', 'schedule')] : []
  }
  if (result.expert_id === 'program' && c) return [
    card('共同课程', c.focus_shared, '门', result.focus_label || '本次比较口径', 'layers'),
    card('双方去重后的课程并集', c.focus_union, '门', '与共同课程使用相同范围', 'courses'),
    card('课程代码重合比例', c.focus_similarity, '%', '不等于教学内容相似度', 'comparison')]
  if (result.expert_id === 'transfer' && c) return [
    card('目标逐门必修', c.target_required, '门', '方案层面的要求，组合课程另列', 'transition_summary'),
    card('来源也列出同代码', c.potential_required, '门', '不等于所选学生已获认定', 'transition_summary'),
    card('来源未列出同代码', c.additional_required, '门', '不是个人正式补修清单', 'additional')]
  return []
}
