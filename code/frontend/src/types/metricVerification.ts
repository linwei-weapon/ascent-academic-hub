/** 指标核验接口契约。记录数与判断均来自后端或人工记录，不在前端推导验收结果。 */
export type VerificationLayerId = 'source' | 'fact' | 'application'
export type VerificationModuleId = 'teaching-overview' | 'ai-briefing'
export type VerificationQueryKind = 'count' | 'detail' | 'calculate'
export type VerificationJudgment = '符合' | '有差异' | '条件不足'

export interface VerificationRequirement {
  id: string
  section: string
  title: string
  area: string
  category: string
  description: string
  acceptanceCriteria: string[]
  metricIds: string[]
  pagePaths: string[]
  source: { startLine: number; endLine: number }
  issues: string[]
}

export interface VerificationMetric {
  id: string
  name: string
  type: string
  definition: string
  formula: string
  grain: string
  unit: string
  numerator?: string
  denominator?: string
  scope: string[]
  nullPolicy: string
  sourceSections: string[]
  issues: string[]
  mappingStatus: string
  mappingNote?: string
  managementUse?: string
  calculationSteps?: string[]
  boundaryChecks?: string[]
  pageVerification?: { path: string; expectedResult: string; numerator: string | null; denominator: string | null; unit: string; requirementIds: string[]; steps: string[]; specificCheck: string }
  calculationVariants?: { id: string; name: string; sourceSections: string[]; formula: string; unit: string; boundary: string }[]
}

export interface VerificationCapabilities {
  execute: boolean
  records: boolean
  mappingManage?: boolean
  environment: string
  limitations: string[]
}

export interface VerificationCatalog {
  mappingRevisionId?: string
  module: { id: string; name: string; sourceDocument?: string; version?: string }
  requirements: VerificationRequirement[]
  metrics: VerificationMetric[]
  capabilities: VerificationCapabilities
  indicatorSystem?: {
    version: string
    pages: { id: string; name: string }[]
    entries: VerificationIndicatorEntry[]
  }
}

export interface VerificationIndicatorEntry {
  id: string
  metricId: string
  evidenceMetricIds?: string[]
  requirementId: string
  pageId: string
  group: string
  name: string
  meaning: string
  formula: string
  components: string[]
  sourceSections: string[]
  aliases: string[]
  status: 'explicit' | 'confirmed' | 'pending'
  pendingIssues: string[]
  comparisonKind: 'scalar' | 'distribution' | 'ranking' | 'series' | 'collection'
}

export interface VerificationComparison {
  expectedExecutionId?: string | null
  scope: string
  period: string
  asOf: string
  dataVersion?: string
  coverage: 'display' | 'fact_application' | 'full_chain'
  startLayer: VerificationLayerId | 'manual'
  actualSource: string
  actualObservedAt: string
  expectedSource: string
  expectedObservedAt: string
  comparisonRule: string
  rows: { label: string; unit: string; actual: string; expected: string; expectedKey?: string | null; difference?: string | null }[]
}

export type VerificationExpectedDraft = Pick<VerificationComparison, 'expectedExecutionId' | 'scope' | 'period' | 'dataVersion' | 'startLayer' | 'expectedSource' | 'expectedObservedAt' | 'rows'> & { parameters: VerificationParameters }

export interface VerificationParameter {
  name: string
  label: string
  type: 'string' | 'integer' | 'number'
  required: boolean
  source?: string
}

export interface VerificationQuery {
  id: string
  title?: string
  scenarioPurpose?: string
  kind: VerificationQueryKind
  dialect: string
  sql: string
  parameters: VerificationParameter[]
  executable: boolean
  blockedReason?: string
  version: string
  purpose?: string
  dependencies?: { bindingId: string; columns: string[] }[]
}

export interface VerificationLayer {
  id: VerificationLayerId
  metricResultStatus?: string
  name: string
  tables: string[]
  grain: string
  transform: string[]
  issues: string[]
  status: string
  applicability?: string
  mappingMode?: string
  directSource?: string
  applicabilityReason?: string
  closureReason?: string
  remainingGaps?: string[]
  queries: VerificationQuery[]
}

export interface VerificationParameterOptions {
  parameters: Record<string, {
    items: { value: string; label: string }[]
    truncated: boolean
    source: string
    error?: string
  }>
}

export interface MetricVerificationQueries {
  mappingRevisionId?: string
  mappingSources?: MappingSource[]
  sourceManifest?: MappingSource[]
  mappingMetric?: MappingMetric
  metricId: string
  layers: VerificationLayer[]
}

export type VerificationParameters = Record<string, string | number | null>

export interface VerificationExecution {
  mappingRevisionId?: string
  executionUse?: 'verification' | 'definition_validation'
  validationCaseId?: string
  resultDisclosure?: 'withheld' | 'revealed' | 'not_applicable'
  retainedEvidence?: boolean
  evidenceRef?: string
  id: string
  scenarioId?: string
  /** 查询可能成功但执行证据存储失败；此时不得用于保存“符合”判断。 */
  evidenceSaved: boolean
  status: 'success' | 'error'
  queryId: string
  metricId: string
  layer: VerificationLayerId
  queryKind: VerificationQueryKind
  /** 执行时的结果来源语义，保留到历史证据，避免将参考复算误读为应用实值。 */
  mappingMode?: string
  directSource?: string
  metricResultStatus?: string
  metricResultReason?: string
  executedAt: string
  durationMs: number
  recordCount: number | null
  columns: string[]
  rows: Record<string, unknown>[]
  metrics: Record<string, unknown>
  parameters: VerificationParameters
  sqlVersion: string
  message?: string
  truncated: boolean
}

/** 已保存的执行摘要，不含学生等原始明细行。current 由后端按当前定义判断。 */
export interface StoredVerificationEvidence extends Omit<VerificationExecution, 'rows' | 'evidenceSaved'> {
  requirementId: string
  returnedRows: number
  queryChecksum: string
  current: boolean
}

export interface VerificationRecordInput {
  mappingRevisionId?: string
  requirementId: string
  metricId?: string
  scenarioId?: string
  comparison?: VerificationComparison
  judgment: VerificationJudgment
  comment: string
  evidenceIds: string[]
}

export interface VerificationRecord extends VerificationRecordInput {
  id: string
  createdAt: string
  createdBy?: string
  current?: boolean
}

/** 数据库映射快照；只保留消费端展示与核算所需字段。 */
export interface MappingRule {
  id: string
  name: string
  definition: Record<string, unknown> | string
  questionIds?: string[]
}
export interface MappingPhysicalBinding {
  id?: string; environmentId?: string; connectionRef?: string; dialect?: string
  schema?: string | null; objectName: string; fieldMap?: Record<string, string>; status?: string
  checkedAt?: string | null; evidenceRefs?: string[]
}
export interface MappingLineageNode {
  id: string; logicalName: string; layer: VerificationLayerId; grain?: string | null
  role?: string; objectType?: string; fields?: string[]; physicalBindings?: MappingPhysicalBinding[] | null
}
export interface MappingProcessingStep {
  id: string; kind: string; inputNodeIds: string[]; outputNodeId: string
  description?: string | string[]; physicalPredicate?: string | null; definitionFields?: string[]
  fieldMappings?: { from: string; to: string; expression?: string; queryId?: string }[] | null
  join?: { type?: string; keys?: { left: string; right: string }[]; snapshotCondition?: string } | null
  evidenceRefs?: string[]
}
export interface MappingMetric {
  id: string
  name: string
  businessCategory?: string
  definition: {
    meaning?: string; formula?: string; businessPurpose?: string; unit?: string
    scope?: unknown; grain?: unknown; nullPolicy?: unknown; precision?: unknown
    components?: { key: string; name: string; expression?: string; metricRef?: string }[]
    ruleRefs?: string[]; metricRefs?: { metricId: string; appliesTo?: string; parameterBindings?: { targetParameter: string; sourceParameter?: string | null; literalValue?: unknown }[] }[]
  }
  lineage?: { nodes: MappingLineageNode[] }
  processing?: { steps: MappingProcessingStep[] }
  actualBinding?: { status: string; kind?: string | null; reason?: string; queryId?: string | null; evidenceRefs?: string[] }
  status?: Record<string, string>
  verificationPlan?: { caseIds?: string[]; closureStatus?: string; comparison?: { requiredConditions?: string[]; actualValueMode?: string } }
}
export interface MappingResultColumn { key: string; label?: string; dataType?: string; unit?: string; semanticRole?: string }
export interface MappingValidationCase {
  id: string; metricId: string; title: string
  samplePlan?: { requirement?: string; scopeReason?: string | null; parameters?: VerificationParameters | null }
  execution: { queryId: string; status?: string; executionId?: string | null }
}
export interface MappingQuestion {
  id: string; title: string; status: string; contextHash: string
  problem?: string; affectedMetricIds?: string[]; ownerRole?: string
  options?: { id: string; label: string; effect?: string }[]
  customAnswerAllowed?: boolean
  answers?: { answerId?: string; rawAnswer: string; recordedAt?: string; recordedBy?: string }[]
  appliedRevisionId?: string | null
}
export interface MappingMetricObservation {
  metricId: string; metricLabel?: string | null; locator?: string | null
  value?: string | number | boolean | null; unit?: string | null
  filterContext?: { scope?: unknown; semesterLabel?: string | null; semesterId?: string | null } | null
  identityContext?: { user?: string | null; activeIdentity?: string | null } | null
  observedAt?: string | null; observedAtPrecision?: string | null
  pageLoadedAt?: string | null; dataAsOf?: string | null; dataNature?: string | null
  supportingDisplay?: {
    displayedValue?: string | null; displayedCount?: string | null; displayedAttemptCount?: string | null
    semanticRole?: string | null; studentsWithGpa?: number | null; precision?: string | null
    displayedDistribution?: { bucket: string; sharePercent: string | number | null }[]
  } | null
  limitations?: string[]
}
export interface MappingSource {
  id: string; kind?: string; title?: string; location?: string | null
  evidence?: { id: string; status?: string; excerpt?: string; locator?: { section?: string; heading?: string; lineStart?: number; lineEnd?: number }; metricObservation?: MappingMetricObservation }[]
}
export interface MappingPackage {
  packageId: string; schemaVersion: string; analysisId: string; moduleId: string; environmentId: string; template: boolean
  projectId?: string; moduleName?: string; baseRevisionId?: string | null
  inputManifest?: { delivery?: { mode?: 'analyze_only' | 'save_draft' | 'activate' } }
  pendingAnswers?: unknown[]
  metrics: MappingMetric[]; sharedRules?: MappingRule[]; questions?: MappingQuestion[]
  sourceManifest?: MappingSource[]
  validationCases?: MappingValidationCase[]
  queries: { id: string; metricId: string; sql?: string; resultContract?: { shape?: string; columns: MappingResultColumn[] } }[]
}
export interface MappingRevision {
  revisionId: string; packageId?: string; packageHash?: string; createdAt?: string; current?: boolean
  package: MappingPackage
  baseRevisionId?: string | null; readbackVerified?: boolean; state?: 'draft' | 'saved'; idempotent?: boolean
  validation?: { valid: boolean; warnings?: { path?: string; message: string; blocksActivation?: boolean }[] }
}
export interface MappingHead {
  revisionId: string | null; lockVersion: number; projectId: string; moduleId: VerificationModuleId
  environmentId: string; legacyMode: boolean; legacyReason?: string
}
export interface VerificationAccess {
  authorized: boolean; canExecute: boolean; mappingManage: boolean
}
export interface MappingActivation {
  revisionId: string; packageHash?: string; state: 'active'; idempotent: boolean; lockVersion: number
}
export interface MappingRegistration {
  registered: boolean; pagePath: string
  mappingRef: { moduleId: VerificationModuleId; revisionId: string; packageHash: string; current: boolean }
  metrics: { metricCode: string; version: string | null; definitionStatus: string | null; implementationStatus: string | null
    enabled: boolean; pageRef: string; registered: boolean; semanticSignature?: string }[]
}
export interface MappingAnswerSubmission {
  submissionId: string; questionContextHash: string; rawAnswer: string
  choiceId?: string | null; customAnswer?: string | null
  scope?: string; effectiveFrom?: string | null; opinionSourceRef?: string
}
export interface IndependentExpectationInput {
  method: string; basisRef?: string; derivation: string; rows: Record<string, unknown>[]
  inputContentHash: string; resultKnownBeforeCalculation: boolean
}
export interface RetainedVerificationEvidence {
  id: string; mappingRevisionId?: string; metricId: string; caseId?: string
  capture: Record<string, unknown>; scope: unknown
  datasets: {
    queryId: string; countQueryId?: string; role: string; sql: string; sqlChecksum: string; countSql?: string
    parameters: VerificationParameters; columns: MappingResultColumn[]; rows: Record<string, unknown>[]
    matchedRecordCount: number | null; returnedRecordCount: number; complete: boolean; truncated: boolean
  }[]
  integrity: { contentHash: string; byteCount: number; persistedAt: string; readbackVerified: boolean }
  resultDisclosure: 'withheld' | 'revealed' | 'not_applicable'
  expected: (IndependentExpectationInput & { determinedAt?: string; determinedByRef?: string }) | null
  testedResult: { queryId: string; sql: string; sqlChecksum: string; parameters: VerificationParameters; columns: MappingResultColumn[]; rows: Record<string, unknown>[]; complete: boolean; truncated: boolean } | null
  validation: { status: 'pending' | 'match' | 'different' | 'inconclusive'; differences: unknown[] }
}
