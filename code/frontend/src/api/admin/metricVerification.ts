import { http } from '@/utils/http'
import type {
  MetricVerificationQueries, VerificationCatalog, VerificationExecution, VerificationExpectedDraft,
  StoredVerificationEvidence, VerificationComparison, VerificationParameterOptions, VerificationParameters, VerificationRecord, VerificationRecordInput,
  MappingRevision, MappingQuestion, MappingAnswerSubmission, IndependentExpectationInput, RetainedVerificationEvidence,
  VerificationModuleId,
  MappingPackage, MappingHead, MappingActivation, MappingRegistration, VerificationAccess,
} from '@/types/metricVerification'

const base = '/admin/metric-verification'

export function getVerificationCatalog(moduleId: VerificationModuleId = 'teaching-overview'): Promise<VerificationCatalog> {
  return http.get<VerificationCatalog>(`${base}/catalog${revisionQuery(undefined, moduleId)}`)
}

function revisionQuery(mappingRevisionId?: string, moduleId: VerificationModuleId = 'teaching-overview') {
  const query = new URLSearchParams({ moduleId })
  if (mappingRevisionId) query.set('mappingRevisionId', mappingRevisionId)
  return `?${query}`
}

export async function getMetricVerificationQueries(metricId: string, mappingRevisionId?: string, moduleId?: VerificationModuleId): Promise<MetricVerificationQueries> {
  const response = await http.get<MetricVerificationQueries>(`${base}/metrics/${encodeURIComponent(metricId)}/queries${revisionQuery(mappingRevisionId, moduleId)}`)
  return { ...response, sourceManifest: response.mappingSources ?? response.sourceManifest ?? [] }
}

export function executeVerificationQuery(
  queryId: string,
  body: { requirementId: string; scenarioId?: string; parameters: VerificationParameters; limit: number; sqlVersion: string; mappingRevisionId?: string; executionUse?: 'verification' | 'definition_validation'; validationCaseId?: string },
  signal?: AbortSignal,
  moduleId?: VerificationModuleId,
): Promise<VerificationExecution> {
  return http.post<VerificationExecution>(`${base}/queries/${encodeURIComponent(queryId)}/execute${revisionQuery(undefined, moduleId)}`, body, { signal })
}

export function getVerificationRecords(requirementId: string, mappingRevisionId?: string, moduleId?: VerificationModuleId): Promise<{ items: VerificationRecord[] }> {
  return http.get<{ items: VerificationRecord[] }>(`${base}/requirements/${encodeURIComponent(requirementId)}/records${revisionQuery(mappingRevisionId, moduleId)}`)
}

export function getRecentVerificationRecords(mappingRevisionId?: string, moduleId?: VerificationModuleId): Promise<{ items: VerificationRecord[] }> {
  return http.get<{ items: VerificationRecord[] }>(`${base}/records/recent${revisionQuery(mappingRevisionId, moduleId)}`)
}

export function getVerificationQueryOptions(queryId: string, requirementId: string, mappingRevisionId?: string, moduleId: VerificationModuleId = 'teaching-overview'): Promise<VerificationParameterOptions> {
  const query = new URLSearchParams({ requirementId, moduleId })
  if (mappingRevisionId) query.set('mappingRevisionId', mappingRevisionId)
  return http.get<VerificationParameterOptions>(`${base}/queries/${encodeURIComponent(queryId)}/options?${query}`)
}

export function getVerificationExecutions(requirementId: string, mappingRevisionId?: string, moduleId?: VerificationModuleId): Promise<{ items: StoredVerificationEvidence[] }> {
  return http.get<{ items: StoredVerificationEvidence[] }>(`${base}/requirements/${encodeURIComponent(requirementId)}/executions${revisionQuery(mappingRevisionId, moduleId)}`)
}

export function saveVerificationRecord(body: VerificationRecordInput, moduleId?: VerificationModuleId): Promise<VerificationRecord> {
  return http.post<VerificationRecord>(`${base}/records${revisionQuery(undefined, moduleId)}`, body)
}

export function previewVerificationComparison(body: VerificationComparison, moduleId?: VerificationModuleId): Promise<VerificationComparison> {
  return http.post<VerificationComparison>(`${base}/comparisons/preview${revisionQuery(undefined, moduleId)}`, body)
}

export function importVerificationExpected(body: { requirementId: string; scenarioId: string; executionId: string; mappingRevisionId?: string }, moduleId?: VerificationModuleId): Promise<VerificationExpectedDraft> {
  return http.post<VerificationExpectedDraft>(`${base}/comparisons/from-execution${revisionQuery(undefined, moduleId)}`, body)
}

export function getMappingRevision(revisionId: string, moduleId?: VerificationModuleId): Promise<MappingRevision> {
  return http.get<MappingRevision>(`${base}/mapping/revisions/${encodeURIComponent(revisionId)}${revisionQuery(undefined, moduleId)}`)
}

export function getMappingHead(moduleId: VerificationModuleId): Promise<MappingHead> {
  return http.get<MappingHead>(`${base}/mapping/head${revisionQuery(undefined, moduleId)}`)
}

export function getVerificationAccess(moduleId: VerificationModuleId): Promise<VerificationAccess> {
  return http.get<VerificationAccess>(`${base}/access${revisionQuery(undefined, moduleId)}`)
}

export function saveMappingPackage(body: MappingPackage, moduleId: VerificationModuleId): Promise<MappingRevision> {
  return http.post<MappingRevision>(`${base}/mapping/packages${revisionQuery(undefined, moduleId)}`, body)
}

export function activateMappingRevision(body: { revisionId: string; expectedHeadRevisionId: string | null }, moduleId: VerificationModuleId): Promise<MappingActivation> {
  return http.post<MappingActivation>(`${base}/mapping/activate${revisionQuery(undefined, moduleId)}`, body)
}

export function getMappingRegistration(revisionId: string, moduleId: 'ai-briefing'): Promise<MappingRegistration> {
  return http.get<MappingRegistration>(`${base}/mapping/registrations/${encodeURIComponent(revisionId)}${revisionQuery(undefined, moduleId)}`)
}

export function getMappingQuestions(mappingRevisionId?: string, moduleId?: VerificationModuleId): Promise<{ items: MappingQuestion[] }> {
  return http.get<{ items: MappingQuestion[] }>(`${base}/mapping/questions${revisionQuery(mappingRevisionId, moduleId)}`)
}

export function submitMappingAnswer(questionId: string, body: MappingAnswerSubmission, moduleId?: VerificationModuleId): Promise<{ answerId: string; questionStatus?: string }> {
  return http.post<{ answerId: string; questionStatus?: string }>(`${base}/mapping/questions/${encodeURIComponent(questionId)}/answers${revisionQuery(undefined, moduleId)}`, body)
}

export function getRetainedVerificationEvidence(executionId: string, moduleId?: VerificationModuleId): Promise<RetainedVerificationEvidence> {
  return http.get<RetainedVerificationEvidence>(`${base}/executions/${encodeURIComponent(executionId)}/evidence${revisionQuery(undefined, moduleId)}`)
}

export function submitIndependentExpectation(executionId: string, body: IndependentExpectationInput, moduleId?: VerificationModuleId): Promise<RetainedVerificationEvidence> {
  return http.post<RetainedVerificationEvidence>(`${base}/executions/${encodeURIComponent(executionId)}/independent-expectation${revisionQuery(undefined, moduleId)}`, body)
}
