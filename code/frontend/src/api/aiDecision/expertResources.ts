import { http as sharedHttp, getActiveIdentity, getToken } from '@/utils/http'
import type { ExpertResource, ResourceCatalog, ResourceKind, ResourceContent, ResourceOptions, ResourceRun, ResourceResearch, BusinessTask, ExpertModel, ExecutionRequest, ExpertExecution, RetainedEvidence, ExpertRule, ResearchIssue } from '@/types/expertResources'

const base = '/admin/expert-resources'
async function protectIdentity<T>(operation: () => Promise<T>): Promise<T> {
  const identity = getActiveIdentity(), token = getToken()
  const result = await operation()
  if (identity !== getActiveIdentity() || token !== getToken()) throw new Error('工作身份已变化，请在当前身份下重新查询。')
  return result
}
const http = {
  get: <T>(url: string) => protectIdentity(() => sharedHttp.get<T>(url)),
  post: <T>(url: string, body: unknown) => protectIdentity(() => sharedHttp.post<T>(url, body)),
  del: <T>(url: string) => protectIdentity(() => sharedHttp.del<T>(url)),
  put: <T>(url: string, body: unknown) => protectIdentity(() => sharedHttp.put<T>(url, body)),
}
const path = (kind: ResourceKind, id: string) => `${base}/resources/${kind}/${encodeURIComponent(id)}`
const query = (values: Record<string, unknown>) => new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== '').map(([key, value]) => [key, String(value)])).toString()
export type ConversationRequest = ExecutionRequest & { expertSelection?: 'per_turn'; upgradeToVersion?: string; readMode?: 'live'|'saved'; publicationId?: string; sourceResultId?: string; objectId?: string }
export interface BriefingPreset {
  id: string; revision: number; name: string; question: string; expertId: string; taskId: string; input: Record<string, any>;
  scope: {type:'all'|'college';collegeIds:string[]}; collegeMeaning: 'course_opening'; serviceId: string; grantId?: string;
  schedule?: {kind:'weekly'|'test_interval';weekday?:number;time?:string;timezone:string;intervalMinutes?:number}|null;
  activeWindow?: {start:string;end:string}|null; enabled?:boolean; state?:string; trialValid?:boolean; trialExecutionId?:string;
  currentPublicationId?:string; latestExecution?:ExpertExecution; analysisSignature?:string; canDelete?:boolean; [key:string]:any
}
export interface BriefingPublication {
  id?:string; publicationId:string; publicationSequence:number; revision:number; presetId:string; name?:string; question?:string;
  expertId?:string; state?:string; status?:string; applicable?:boolean; withdrawReason?:string; resultId:string;
  outcome?:ResourceRun; input?:Record<string,any>; scope?:Record<string,any>; createdAt?:string; dataUpdatedAt?:string;
  explanationState?:string; explanationVersion?:number; latestExecution?:ExpertExecution; [key:string]:any
}
export interface ProcessingConfig {serviceId:string;name:string;environment:string;dataConfigRef:string;modelConfigRef:string;automaticEnabled:boolean;timeoutSeconds:number;retryLimit:number;[key:string]:any}
export interface ProcessingView {revision:number;draft:ProcessingConfig;effective:ProcessingConfig|null;status:Record<string,any>;grants:Array<Record<string,any>>;[key:string]:any}
export function explanationStateLabel(state?: string): string {
  return ({completed:'已完成',success:'已完成',failed:'说明失败，事实保留',interrupted:'说明已中断，事实保留',
    pending:'等待说明',running:'正在说明',not_configured:'真实模型未配置',unavailable:'真实模型未配置',
    not_executed:'未执行说明',not_requested:'本轮未请求AI说明',budget_exhausted:'预算不足，事实保留',
    reference_invalid:'来源引用已失效，未追加说明'} as Record<string,string>)[state||''] || '以事实模式呈现'
}
export const expertResourcesApi = {
  rules: () => http.get<{items:ExpertRule[];canImportConfirmation?:boolean}>(`${base}/rules`),
  createRule: (payload:Record<string,unknown>) => http.post<ExpertRule>(`${base}/rules`,{payload}),
  saveRule: (id:string,version:string,revision:number,payload:Record<string,unknown>) => http.put<ExpertRule>(`${base}/rules/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`,{revision,payload}),
  ruleAction: (id:string,version:string,action:'confirm'|'test'|'publish'|'withdraw',body:Record<string,unknown>) => http.post<ExpertRule>(`${base}/rules/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/${action}`,body),
  issues: (id:string) => http.get<{items:ResearchIssue[]}>(`${base}/research/${encodeURIComponent(id)}/issues`),
  issueEvent: (id:string,issueId:string,body:{revision:number;type:'source_added'|'deferred'|'scope_corrected'|'reopened';sourceRef?:Record<string,unknown>;reason?:string}) => http.post<ResearchIssue>(`${base}/research/${encodeURIComponent(id)}/issues/${encodeURIComponent(issueId)}/events`,body),
  tasks: () => http.get<{items:BusinessTask[]}>(`${base}/tasks`),
  models: () => http.get<{items:ExpertModel[]}>(`${base}/models`),
  execute: (body:ConversationRequest) => http.post<ExpertExecution>(`${base}/executions`,body),
  execution: (id:string) => http.get<ExpertExecution>(`${base}/executions/${encodeURIComponent(id)}`),
  executionRequest: (clientRequestId:string) => http.get<{found:boolean;execution?:ExpertExecution}>(`${base}/execution-requests/${encodeURIComponent(clientRequestId)}`),
  cancelExecution: (id:string) => http.post<ExpertExecution>(`${base}/executions/${encodeURIComponent(id)}/cancel`,{}),
  result: (id:string) => http.get<ResourceRun>(`${base}/results/${encodeURIComponent(id)}`),
  evidence: (resultId:string,evidenceId:string,offset=0,limit=20) => http.get<RetainedEvidence>(`${base}/results/${encodeURIComponent(resultId)}/evidence/${encodeURIComponent(evidenceId)}?offset=${offset}&limit=${limit}`),
  catalog: () => http.get<ResourceCatalog>(`${base}/catalog`),
  inspectPackage: (input:{filename:string;zipBase64:string}) => http.post<{filename:string;frontMatter:{name:string;version:string;description:string};files:Array<{path:string;size:number;text?:string}>;skillType?:string;warnings?:string[]}>(`${base}/skills/package/inspect`,input),
  package: (input:{filename:string;zipBase64:string;resourceId?:string;revision?:number;displayName?:string;category?:string}) => http.post<ExpertResource>(`${base}/skills/package`,input),
  create: (kind: ResourceKind, input: { id?: string; name: string; templateId?: string; category?: string; summary?: string; content?: ResourceContent }) => http.post<ExpertResource>(`${base}/resources/${kind}`, input),
  copy: (kind: ResourceKind, id: string, revision: number, input: { id?: string; name: string }) => http.post<ExpertResource>(`${path(kind,id)}/copy`, { revision, ...input }),
  remove: (kind: ResourceKind, id: string, revision: number) => http.del<ExpertResource>(`${path(kind,id)}?revision=${revision}`),
  restore: (kind: ResourceKind, id: string, revision: number) => http.post<ExpertResource>(`${path(kind,id)}/restore`, { revision }),
  archived: (kind: ResourceKind) => http.get<{items: ExpertResource[]}>(`${base}/archived?kind=${kind}`),
  references: (kind: ResourceKind, id: string) => http.get<NonNullable<ExpertResource['references']>>(`${path(kind,id)}/references`),
  options: () => http.get<ResourceOptions>(`${base}/options`),
  courseOptions: (semesterId:string,collegeId?:string) => http.get<{items:NonNullable<ResourceOptions['courses']>}>(`${base}/options/courses?semester_id=${encodeURIComponent(semesterId)}${collegeId?`&college_id=${encodeURIComponent(collegeId)}`:''}`),
  resource: (kind: ResourceKind, id: string) => http.get<ExpertResource>(path(kind, id)),
  save: (kind: ResourceKind, id: string, revision: number, content: ResourceContent) => http.put<ExpertResource>(path(kind, id), { revision, content }),
  test: (kind: ResourceKind, id: string, revision: number, input: Record<string, unknown>) => http.post<ExpertResource>(`${path(kind, id)}/test`, { revision, input }),
  review: (kind: ResourceKind, id: string, revision: number, runId: string, accepted: boolean, note: string) => http.post<ExpertResource>(`${path(kind, id)}/review`, { revision, runId, accepted, note }),
  publish: (kind: ResourceKind, id: string, revision: number) => http.post<ExpertResource>(`${path(kind, id)}/publish`, { revision }),
  enabled: (kind: ResourceKind, id: string, enabled: boolean) => http.post<ExpertResource>(`${path(kind, id)}/enabled`, { enabled }),
  researchList: (search='',offset=0,limit=30) => http.get<ResourceResearch[] | { items: ResourceResearch[]; total?:number }>(`${base}/research?${query({search,offset,limit})}`),
  research: (id: string) => http.get<ResourceResearch>(`${base}/research/${encodeURIComponent(id)}`),
  createResearch: (expertId: string, input: Record<string, unknown>, question: string) => http.post<ResourceResearch>(`${base}/research`, { expertId, input, question }),
  turn: (id: string, input: Record<string, unknown>, question: string) => http.post<ResourceResearch>(`${base}/research/${encodeURIComponent(id)}/turn`, { input, question }),
  presets: (expertId?:string) => http.get<{items:BriefingPreset[]}>(`${base}/briefing/presets?${query({expertId})}`),
  createPreset: (body:Record<string,unknown>) => http.post<BriefingPreset>(`${base}/briefing/presets`,body),
  savePreset: (id:string,body:Record<string,unknown>) => http.put<BriefingPreset>(`${base}/briefing/presets/${encodeURIComponent(id)}`,body),
  removePreset: (id:string,expectedRevision:number) => http.del<unknown>(`${base}/briefing/presets/${encodeURIComponent(id)}?${query({expectedRevision})}`),
  presetAction: (id:string,action:'trial'|'run'|'enable'|'pause',expectedRevision:number,clientRequestId:string,replacesPublicationId?:string) => http.post<ExpertExecution|BriefingPreset>(`${base}/briefing/presets/${encodeURIComponent(id)}/${action}`,{expectedRevision,clientRequestId,replacesPublicationId}),
  presetExecutions: (id:string,offset=0,limit=20) => http.get<{items:ExpertExecution[];total?:number}>(`${base}/briefing/presets/${encodeURIComponent(id)}/executions?${query({offset,limit})}`),
  presetExecutionEvidence: (presetId:string,executionId:string,evidenceId:string,offset=0,limit=20) => http.get<RetainedEvidence>(`${base}/briefing/presets/${encodeURIComponent(presetId)}/executions/${encodeURIComponent(executionId)}/evidence/${encodeURIComponent(evidenceId)}?${query({offset,limit})}`),
  publications: (filters:Record<string,unknown>={}) => http.get<{items:BriefingPublication[];total:number;[key:string]:any}>(`${base}/briefing/publications?${query(filters)}`),
  publication: (id:string) => http.get<BriefingPublication>(`${base}/briefing/publications/${encodeURIComponent(id)}`),
  publicationEvidence: (id:string,evidenceId:string,offset=0,limit=20) => http.get<RetainedEvidence>(`${base}/briefing/publications/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}?${query({offset,limit})}`),
  withdrawPublication: (id:string,expectedRevision:number,reason:string,clientRequestId:string) => http.post<BriefingPublication>(`${base}/briefing/publications/${encodeURIComponent(id)}/withdraw`,{expectedRevision,reason,clientRequestId}),
  processing: () => http.get<ProcessingView>(`${base}/processing/config`),
  processingExecutions: (offset=0,limit=20) => http.get<{items:ExpertExecution[];total:number}>(`${base}/processing/executions?${query({offset,limit})}`),
  saveProcessing: (body:ProcessingConfig&{expectedRevision:number}) => http.put<ProcessingView>(`${base}/processing/config`,body),
  checkProcessing: (expectedRevision:number) => http.post<Record<string,any>>(`${base}/processing/check`,{expectedRevision}),
  applyProcessing: (expectedRevision:number) => http.post<ProcessingView>(`${base}/processing/apply`,{expectedRevision}),
  createGrant: (body:Record<string,unknown>) => http.post<Record<string,any>>(`${base}/processing/grants`,body),
  renewGrant: (id:string,expectedRevision:number,validUntil:string) => http.put<Record<string,any>>(`${base}/processing/grants/${encodeURIComponent(id)}`,{expectedRevision,validUntil}),
  revokeGrant: (id:string,expectedRevision:number) => http.del<unknown>(`${base}/processing/grants/${encodeURIComponent(id)}?${query({expectedRevision})}`),
  recheckRecovery: () => http.post<Record<string,any>>(`${base}/processing/recovery/recheck`,{}),
}
