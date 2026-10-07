import type { ExpertResource, ResourceSchema } from '@/types/expertResources'

export const inputLabels: Record<string, string> = {
  plan_id: '培养方案', target_plan_id: '对照培养方案', semester_id: '学期', college_id: '学院', limit: '展示数量',
  previewLimit: '预览记录数', comparisonMode: '比较口径', course_id: '指定课程编号（可选）',
}

export function inputProblems(schema: ResourceSchema | undefined, input: Record<string, unknown>): string[] {
  const missing = (schema?.required || []).filter(key => key !== 'skill_id' &&
    (input[key] == null || (typeof input[key] === 'string' && !String(input[key]).trim())))
  const problems = missing.length ? [`请选择或填写：${missing.map(key => schemaFieldLabel(key, schema?.properties?.[key], true)).join('、')}`] : []
  if (input.plan_id && input.target_plan_id && input.plan_id === input.target_plan_id) problems.push('来源方案与对照方案请选择不同的培养方案。')
  return problems
}

export function transportLabel(value: unknown): string {
  const labels: Record<string, string> = { internal: '内置服务', internal_mcp: '内置 MCP 服务', streamable_http: '可流式 HTTP', 'streamable-http': '可流式 HTTP', http: 'HTTP', stdio: '标准输入输出', sse: '服务端事件流' }
  return typeof value === 'string' ? labels[value] || value : '未登记'
}

export function resourceDate(value: unknown, empty = '未记录'): string {
  if (typeof value !== 'string' || !value) return empty
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

export function describeContent(value: unknown): string {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return String(value ?? '')
  const record = value as Record<string, unknown>
  const text = record.text ?? record.description ?? record.statement
  if (typeof text === 'string') return text
  return Object.entries(record).filter(([key]) => !['id', 'group', 'title'].includes(key))
    .map(([key, item]) => `${key}：${typeof item === 'string' ? item : JSON.stringify(item)}`).join('；')
}

export const schemaLabels: Record<string, string> = {
  ...inputLabels, status:'执行状态',summary:'结果摘要',scope:'实际分析范围',data:'业务数据',tables:'证据表格',
  sources:'数据来源',limitations:'适用边界',missingEvidence:'待补依据',schemaVersion:'结构版本',taskId:'业务任务',
  resultKind:'结果性质',facts:'事实指标',coverage:'覆盖与未知',evidence:'保存证据',conditions:'核验条件',issues:'待明确事项',
  comparisonCapability:'结果可比性',publishMode:'结果发布方式',publicationGate:'发布条件',validationBasis:'核验依据',
  observationState:'课程观察状态',observationExclusions:'排除与未知记录',observationExclusionCounts:'排除与未知数量',
  observations:'首修观察课程',observationCount:'首修观察课程数',observationBaseline:'同范围首修参照',
  course_id:'课程编号',course_name:'课程名称',first_attempts:'首修人次',first_pass:'首修通过人次',
  first_unpassed:'首修未通过人次',first_pass_pct:'首修通过率（%）',ruleRef:'正式规则版本',populationRef:'授权对象群体',
  year:'适用年度',resultRef:'保存结果引用',baselineRef:'基线结果',currentRef:'对照结果',conditionIds:'核验条件范围',
  factId:'指标标识',name:'名称',value:'指标值',sourceRefs:'来源引用',evidenceId:'证据标识',records:'保存记录',
  retentionComplete:'证据是否完整留存',environment:'查询环境',frozenInput:'本轮保存输入',independentRecompute:'独立复算',
  mappingRef:'指标映射引用',metricRefs:'指标引用',threeLayerCheck:'三层数据核对',rowCount:'记录数',sha256:'内容校验值',
}

export const schemaDescriptions: Record<string, string> = {
  conditions:'逐项核验条件及结果；本任务未做条件核验时可为空。',
  coverage:'说明分析对象、实际观察、可评价、未知和排除情况，以及输入完整性。',
  evidence:'本轮保存的数据依据及留存完整性，与页面预览条数分别说明。',
  facts:'事实指标的标识、名称、数值及来源引用；空值和未知理由按实际结果保留。',
  issues:'本轮发现、需补充资料或业务确认的事项；不表示已自动完成处置。',
  comparisonCapability:'说明已保存结果能否比较及其时间、范围和口径限制。',
  resultKind:'区分事实查询、限定条件核验和显式假设分析。',
  schemaVersion:'返回结构的版本，用于校验与读取已保存结果。',
  validationBasis:'本轮范围、登记指标、保存输入、独立复算及三层核对的实际依据。',
  factId:'本结果中的稳定指标标识。',name:'返回对象的名称。',value:'实际返回值；类型与空值含义按具体指标定义。',
  sourceRefs:'引用本轮返回的来源或证据标识。',evidenceId:'本轮证据的标识。',
  records:'实际留存的证据记录。',retentionComplete:'是否完整留存本轮所需记录；不能由预览条数推断。',
}

export function schemaFieldLabel(key: string, field?: ResourceSchema, required = false): string {
  const label = field?.title || schemaLabels[key] || key
  return required ? label.replace(/（可选）|\(可选\)/g, '') : label
}

export function resourceReadiness(resource: ExpertResource): string {
  if (resource.deletedAt) return '已删除，可在维护列表恢复。历史版本保留。'
  if (!resource.enabled) return '已停用，当前不可用于新分析。'
  if (resource.kind === 'mcps' && resource.draft.content.accessType && resource.draft.content.accessType !== 'internal') return '仅登记配置，外部执行尚未接入。'
  if (resource.kind === 'experts' && resource.published && resource.readiness?.canRun === false) return resource.readiness.runReasons?.join('；') || '现行版本暂不可执行。'
  if (resource.published) return resource.draft.version !== resource.published.version ? '现行版本已发布；新草稿尚未生效。' : '现行版本已发布。查看测试页可核对草稿的验证状态。'
  return resource.readiness?.reasons?.find(reason => !reason.includes('核对') && !reason.includes('测试')) || '草稿待测试与发布，尚未供业务使用。'
}
