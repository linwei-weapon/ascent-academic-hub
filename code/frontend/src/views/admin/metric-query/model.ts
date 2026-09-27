export interface SelectNode {
  id: string
  label: string
  count?: number
  children?: SelectNode[]
}

export interface MetricUsage {
  level1: string
  level2: string
  level3: string
  functionPoint: string
  description: string
  path: string
}

export interface MetricRow {
  id: string
  name: string
  description: string
  formula: string
  tags: SelectNode[]
  usages: MetricUsage[]
  usageText: string
  referencedMetricCount: number | null
  dependentMetricCount: number | null
  usagePointCount: number | null
}

export interface MetricRule {
  name: string
  type: string
  condition: string
  warningLevel: string
  version: string
  status: string
  description: string
}

export interface MetricIssue {
  type: string
  severity: string
  status: string
  description: string
  sourceRef: string
}

export interface MetricSpecification {
  available: boolean
  qualityStatus: string
  qualityIssues: string[]
  statisticalObject: string
  statisticalScope: string
  calculationType: string
  numerator: string
  denominator: string
  deduplicationRules: string[]
  inclusionRules: string[]
  exclusionRules: string[]
  boundaryRules: string[]
  nullHandling: string
  precision: string
  timePoint: string
}

export interface MetricListModel {
  items: MetricRow[]
  modules: SelectNode[]
  tags: SelectNode[]
  total: number
  page: number
  pageSize: number
}

export interface MetricDetailModel {
  metric: MetricRow
  specification: MetricSpecification
  dependencies: MetricRow[]
  dependents: MetricRow[]
  usages: MetricUsage[]
  rules: MetricRule[]
  issues: MetricIssue[]
}

type AnyRecord = Record<string, any>

const specificationIssueLabels: Record<string, string> = {
  statistical_object_unconfirmed: '统计对象缺少明确证据',
  statistical_scope_unconfirmed: '统计范围缺少明确证据',
  deduplication_unconfirmed: '去重业务键尚未确认',
  inclusion_unconfirmed: '纳入条件尚未完整确认',
  exclusion_unconfirmed: '排除条件尚未完整确认',
  null_handling_unconfirmed: '空值处理尚未确认',
  precision_unconfirmed: '单位、精度或舍入规则尚未确认',
  data_as_of_unconfirmed: '统计时点尚未确认',
  data_source_unconfirmed: '数据来源尚未确认',
  numerator_unconfirmed: '分子口径尚未确认',
  denominator_unconfirmed: '分母口径尚未确认',
  denominator_zero_unconfirmed: '零分母处理尚未确认',
  candidate_not_code_verified: '仅来自文档候选，尚未完成代码与页面核验',
}

const specificationFieldLabels: Record<string, string> = {
  statisticalObject: '统计对象',
  statisticalScope: '统计范围',
  deduplicationRule: '去重规则',
  inclusionRule: '纳入规则',
  exclusionRule: '排除规则',
  nullHandlingRule: '空值处理',
  precisionRule: '精度规则',
  dataAsOfRule: '统计时点',
  dataSources: '数据来源',
  numerator: '分子口径',
  denominator: '分母口径',
  denominatorZeroRule: '零分母处理',
  catalogStatus: '目录状态',
}

const calculationTypeLabels: Record<string, string> = {
  count: '计数',
  ratio: '比例',
  average: '平均值',
  median: '中位数',
  rank: '排名',
  distribution: '分布',
  status: '状态/判定',
  formula: '公式计算',
  paired_count: '并列计数',
  unknown: '待确认',
}

function record(value: unknown): AnyRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {}
}

function first(source: AnyRecord, keys: string[], fallback: any = ''): any {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== '') return source[key]
  }
  return fallback
}

function list(value: unknown): any[] {
  if (Array.isArray(value)) return value
  if (typeof value !== 'string' || !value.trim()) return []
  try {
    const parsed = JSON.parse(value)
    if (Array.isArray(parsed)) return parsed
  } catch { /* 兼容逗号分隔的旧字段 */ }
  return value.split(/[,，;；]/).map(item => item.trim()).filter(Boolean)
}

function textValue(value: unknown, fallback = '—'): string {
  if (value === undefined || value === null || value === '') return fallback
  if (Array.isArray(value)) {
    const values = value.map(item => textValue(item, '')).filter(Boolean)
    return values.length ? values.join('；') : fallback
  }
  if (typeof value !== 'object') return String(value)
  const item = record(value)
  const direct = first(item, [
    'description', 'text', 'value', 'label', 'name', 'definition', 'expression',
    'formula', 'rule', 'content',
  ], '')
  if (direct !== '') return textValue(direct, fallback)
  const entries = Object.entries(item)
    .filter(([, entryValue]) => entryValue !== undefined && entryValue !== null && entryValue !== '')
    .map(([key, entryValue]) => `${key}：${textValue(entryValue, '')}`)
    .filter(itemText => !itemText.endsWith('：'))
  return entries.length ? entries.join('；') : fallback
}

function textRules(value: unknown): string[] {
  if (value === undefined || value === null || value === '') return []
  if (Array.isArray(value)) {
    return value.flatMap(textRules).filter((item, index, values) => values.indexOf(item) === index)
  }
  if (typeof value === 'string') {
    const source = value.trim()
    if (!source) return []
    try {
      const parsed = JSON.parse(source)
      if (Array.isArray(parsed)) return textRules(parsed)
    } catch { /* 普通规则文本保持原义 */ }
    return source.split(/(?:\r?\n)+|[；;]/).map(item => item.trim()).filter(Boolean)
  }
  const normalized = textValue(value, '')
  return normalized ? [normalized] : []
}

function nullableCount(value: unknown): number | null {
  if (value === '' || value === undefined || value === null) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeSelectNode(value: unknown): SelectNode {
  if (typeof value === 'string' || typeof value === 'number') {
    return { id: String(value), label: String(value) }
  }
  const item = record(value)
  const children = list(first(item, ['children', 'items', 'nodes'], []))
    .map(normalizeSelectNode)
  return {
    id: String(first(item, ['id', 'value', 'tag_id', 'tagId', 'module_id', 'moduleId', 'code', 'label', 'name'])),
    label: String(first(item, ['label', 'name', 'title', 'value', 'id'], '—')),
    count: nullableCount(first(item, ['count', 'metric_count', 'metricCount'], null)) ?? undefined,
    children: children.length ? children : undefined,
  }
}

function normalizeTags(value: unknown): SelectNode[] {
  return list(value).map(normalizeSelectNode).filter(item => item.id || item.label)
}

export function normalizeUsage(value: unknown): MetricUsage {
  const item = record(value)
  return {
    level1: String(first(item, ['level1', 'level_1', 'level_1_name', 'first_level_module', 'module_level_1', 'module_l1', 'primary_module'], '—')),
    level2: String(first(item, ['level2', 'level_2', 'level_2_name', 'second_level_module', 'module_level_2', 'module_l2', 'secondary_module'], '—')),
    level3: String(first(item, ['level3', 'level_3', 'level_3_name', 'third_level_module', 'module_level_3', 'module_l3', 'tertiary_module'], '—')),
    functionPoint: String(first(item, ['functionPoint', 'function_point', 'display_name', 'page_name', 'name', 'page_path'], '—')),
    description: String(first(item, ['description', 'function_description', 'evidence_note', 'note'], '—')),
    path: String(first(item, ['path', 'page_path', 'route'], '')),
  }
}

function usageSummary(usages: MetricUsage[]): string {
  return usages
    .map(item => [item.level1, item.level2, item.level3, item.functionPoint].filter(part => part && part !== '—').join(' / '))
    .filter(Boolean)
    .join('；')
}

export function normalizeMetric(value: unknown): MetricRow {
  const item = record(value)
  const rawUsages = first(item, ['usages', 'usage_points', 'usagePoints', 'module_function_points', 'bindings', 'page_refs'], [])
  const usages = list(rawUsages).map(normalizeUsage)
  const description = first(item, ['description', 'detailed_description', 'detailedDescription', 'detail', 'definition', 'management_value', 'managementValue', 'boundary'], '—')
  const fallbackUsage = first(item, ['usage_text', 'usageText', 'usage_summary', 'usageSummary', 'used_in'], '')
  return {
    id: String(first(item, ['id', 'metric_id', 'metricId', 'code', 'technical_kpi_id'], '')),
    name: String(first(item, ['name', 'metric_name', 'metricName', 'display_name'], '未命名指标')),
    description: String(description || '—'),
    formula: String(first(item, ['formula', 'calculation_formula', 'calculationFormula', 'formula_text'], '—')),
    tags: normalizeTags(first(item, ['tags', 'tag_list', 'tagList', 'tag_names', 'tagNames'], [])),
    usages,
    usageText: String(fallbackUsage || usageSummary(usages) || '—'),
    referencedMetricCount: nullableCount(first(item, [
      'referencedMetricCount', 'referenced_metric_count', 'dependencyCount', 'dependency_count', 'references_count',
      'reference_count',
    ], null)),
    dependentMetricCount: nullableCount(first(item, [
      'dependentMetricCount', 'dependent_metric_count', 'dependentCount', 'dependent_count', 'referenced_by_count',
      'referenced_count', 'used_by_count',
    ], null)),
    usagePointCount: nullableCount(first(item, [
      'usagePointCount', 'usage_point_count', 'functionPointCount', 'function_point_count', 'page_count',
      'usage_count', 'used_function_point_count',
    ], usages.length || null)),
  }
}

function unwrap(value: unknown): AnyRecord {
  const root = record(value)
  return record(root.data || root.detail || root.impact || root)
}

export function normalizeMetricList(value: unknown): MetricListModel {
  const data = unwrap(value)
  const pagination = record(data.pagination)
  const facets = record(data.facets || data.filters)
  return {
    items: list(first(data, ['items', 'rows', 'metrics'], [])).map(normalizeMetric),
    modules: list(first(facets, ['modules', 'module_tree', 'moduleTree'], [])).map(normalizeSelectNode),
    tags: list(first(facets, ['tags', 'tag_options', 'tagOptions'], [])).map(normalizeSelectNode),
    total: Number(first(pagination, ['total'], first(data, ['total'], 0))) || 0,
    page: Number(first(pagination, ['page', 'current'], first(data, ['page'], 1))) || 1,
    pageSize: Number(first(pagination, ['page_size', 'pageSize', 'size'], first(data, ['page_size', 'pageSize'], 20))) || 20,
  }
}

function normalizeRule(value: unknown): MetricRule {
  const item = record(value)
  return {
    name: String(first(item, ['name', 'rule_name', 'ruleName'], '—')),
    type: String(first(item, ['type', 'rule_type', 'ruleType'], '—')),
    condition: String(first(item, ['condition', 'trigger_condition', 'triggerCondition', 'expression'], '—')),
    warningLevel: String(first(item, ['warningLevel', 'warning_level', 'level', 'severity'], '—')),
    version: String(first(item, ['version', 'rule_version', 'ruleVersion'], '—')),
    status: String(first(item, ['status', 'status_label', 'statusLabel'], '—')),
    description: String(first(item, ['description', 'note', 'boundary'], '—')),
  }
}

function normalizeIssue(value: unknown): MetricIssue {
  const item = record(value)
  return {
    type: String(first(item, ['type', 'issue_type', 'issueType'], '—')),
    severity: String(first(item, ['severity', 'level'], '—')),
    status: String(first(item, ['status', 'status_label', 'statusLabel'], '—')),
    description: String(first(item, ['description', 'message', 'note'], '—')),
    sourceRef: String(first(item, ['sourceRef', 'source_ref', 'evidence'], '—')),
  }
}

function normalizeSpecification(detail: AnyRecord, metric: AnyRecord): MetricSpecification {
  const raw = first(detail, [
    'specification', 'metric_specification', 'metricSpecification',
    'calculation_specification', 'calculationSpecification',
  ], null)
  const specification = record(raw)
  const quality = record(first(specification, ['quality', 'qualityResult', 'quality_result'], {}))
  const available = raw !== null && raw !== undefined && Object.keys(specification).length > 0
  const pick = (keys: string[], metricKeys: string[] = keys): unknown => {
    const specValue = first(specification, keys, undefined)
    return specValue === undefined ? first(metric, metricKeys, undefined) : specValue
  }
  return {
    available,
    qualityStatus: textValue(first(quality, ['status'], first(metric, [
      'specificationStatus', 'specification_status',
    ], 'needs_review')), 'needs_review'),
    qualityIssues: list(first(quality, ['issues', 'qualityIssues', 'quality_issues'], []))
      .map((value) => {
        const issue = record(value)
        if (!Object.keys(issue).length) return textValue(value, '')
        const rawField = textValue(first(issue, ['field'], ''), '')
        const field = specificationFieldLabels[rawField] || rawField
        const message = textValue(first(issue, ['message', 'description'], ''), '')
        const code = textValue(first(issue, ['code'], ''), '')
        return [field, message || specificationIssueLabels[code] || code].filter(Boolean).join('：')
      })
      .filter(Boolean),
    statisticalObject: textValue(pick([
      'statisticalObject', 'statistical_object', 'statisticsObject', 'statistics_object',
      'subject', 'populationObject', 'population_object', 'entity',
    ])),
    statisticalScope: textValue(pick([
      'statisticalScope', 'statistical_scope', 'statisticsScope', 'statistics_scope',
      'scope', 'population', 'applicableScope', 'applicable_scope', 'scopeRule', 'scope_rule',
    ], ['statisticalScope', 'statistical_scope', 'scope'])),
    calculationType: (() => {
      const value = textValue(pick([
        'calculationType', 'calculation_type', 'calcType', 'calc_type',
        'aggregationType', 'aggregation_type', 'aggregation', 'type',
      ], ['calculationType', 'calculation_type', 'calcType', 'calc_type', 'value_type']))
      return calculationTypeLabels[value] || value
    })(),
    numerator: textValue(pick([
      'numerator', 'numeratorDefinition', 'numerator_definition',
      'numeratorRule', 'numerator_rule', 'numeratorExpression', 'numerator_expression',
    ])),
    denominator: textValue(pick([
      'denominator', 'denominatorDefinition', 'denominator_definition',
      'denominatorRule', 'denominator_rule', 'denominatorExpression', 'denominator_expression',
    ])),
    deduplicationRules: textRules(pick([
      'deduplicationRules', 'deduplication_rules', 'deduplicationRule', 'deduplication_rule',
      'deduplication', 'dedupRule', 'dedup_rule', 'distinctRule', 'distinct_rule',
    ])),
    inclusionRules: textRules(pick([
      'inclusionRules', 'inclusion_rules', 'inclusionRule', 'inclusion_rule',
      'inclusions', 'included', 'includeRules', 'include_rules', 'include',
    ])),
    exclusionRules: textRules(pick([
      'exclusionRules', 'exclusion_rules', 'exclusionRule', 'exclusion_rule',
      'exclusions', 'excluded', 'excludeRules', 'exclude_rules', 'exclude',
    ])),
    boundaryRules: textRules(pick([
      'boundaryRules', 'boundary_rules', 'boundaryRule', 'boundary_rule',
      'boundaries', 'boundary', 'applicableBoundary', 'applicable_boundary',
    ], ['boundaryRules', 'boundary_rules', 'boundaries', 'boundary'])),
    nullHandling: textValue(pick([
      'nullHandling', 'null_handling', 'nullHandlingRule', 'null_handling_rule',
      'nullRule', 'null_rule',
      'missingValueHandling', 'missing_value_handling', 'zeroDenominatorRule', 'zero_denominator_rule',
    ])),
    precision: textValue(pick([
      'precision', 'precisionRule', 'precision_rule', 'decimalPlaces', 'decimal_places',
      'roundingRule', 'rounding_rule',
    ])),
    timePoint: textValue(pick([
      'timePoint', 'time_point', 'statisticalTime', 'statistical_time',
      'timeBasis', 'time_basis', 'timeWindow', 'time_window', 'asOfRule', 'as_of_rule',
      'dataAsOfRule', 'data_as_of_rule',
      'observationPoint', 'observation_point',
    ])),
  }
}

export function normalizeMetricDetail(detailValue: unknown, impactValue?: unknown): MetricDetailModel {
  const detail = unwrap(detailValue)
  const impact = unwrap(impactValue)
  const metricSource = record(first(detail, ['metric', 'definition'], detail))
  const dependencies = list(first(impact, ['dependencies', 'referenced_metrics', 'referencedMetrics'],
    first(detail, ['dependencies', 'referenced_metrics', 'referencedMetrics'], []))).map(normalizeMetric)
  const dependents = list(first(impact, ['dependents', 'referenced_by', 'referencedBy', 'referencing_metrics', 'referencingMetrics', 'used_by_metrics'],
    first(detail, ['dependents', 'referenced_by', 'referencedBy', 'referencing_metrics', 'referencingMetrics', 'used_by_metrics'], []))).map(normalizeMetric)
  const usages = list(first(impact, ['usages', 'usage_points', 'usagePoints'],
    first(detail, ['usages', 'usage_points', 'usagePoints', 'bindings'], []))).map(normalizeUsage)
  const rules = list(first(impact, ['rules', 'warning_rules', 'warningRules', 'trigger_rules', 'triggerRules'],
    first(detail, ['rules', 'warning_rules', 'warningRules', 'trigger_rules', 'triggerRules'], []))).map(normalizeRule)
  const issues = list(first(detail, ['issues', 'verification_issues', 'verificationIssues'], []))
    .map(normalizeIssue)
  const metric = normalizeMetric({ ...metricSource, usages })
  const specification = normalizeSpecification(detail, metricSource)
  if (metric.referencedMetricCount === null && (dependencies.length || 'dependencies' in impact || 'dependencies' in detail)) {
    metric.referencedMetricCount = dependencies.length
  }
  if (metric.dependentMetricCount === null && (dependents.length || 'dependents' in impact || 'dependents' in detail)) {
    metric.dependentMetricCount = dependents.length
  }
  if (metric.usagePointCount === null && usages.length) metric.usagePointCount = usages.length
  return { metric, specification, dependencies, dependents, usages, rules, issues }
}

export function countText(value: number | null): string {
  return value === null ? '—' : String(value)
}
