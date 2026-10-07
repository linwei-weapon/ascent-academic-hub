export type ResourceKind = 'experts' | 'skills' | 'mcps'
export interface ResourceSchema { type?: string | string[]; title?: string; description?: string; required?: string[]; properties?: Record<string, ResourceSchema>; enum?: Array<string | number>; default?: unknown; items?: ResourceSchema }
export interface ResourceTool { name: string; title?: string; description?: string; inputSchema?: ResourceSchema; outputSchema?: ResourceSchema; [key: string]: unknown }
export interface ResourceContent {
  expertCode?:string; icon?:string; modelId?:string; executionMode?:'deterministic'|'llm'; engine?:string; expertType?:'single'|'orchestrator'; childExpertIds?:string[]; maxIters?:number; sandboxEnabled?:boolean; personaPrompt?:string; welcomeMessage?:string;
  httpConfig?:{method?:string;requestMapping?:string;responseMapping?:string};
  accessType?:'internal'|'native'|'http'; serviceUrl?:string; requestHeaders?:Array<{name:string;value?:string;hasValue?:boolean}>; skillType?:'code'|'prompt'; package?:{filename:string;files:Array<{path:string;size:number;text?:string}>;frontMatter:{name:string;version:string;description:string}};
  name?: string; summary?: string; category?: string; purpose?: string; instructions?: string;
  responsibilities?: string[]; boundaries?: string[]; starterQuestions?: string[]; skillIds?: string[]; plannedSkillIds?: string[];
  inputSchema?: ResourceSchema; outputSchema?: ResourceSchema; steps?: Array<string | Record<string, unknown>>;
  rules?: Array<string | Record<string, unknown>>; missingEvidence?: string[];
  toolBindings?: Array<{ serverId: string; toolName: string }>; tools?: ResourceTool[];
  execution?: { handler?: string; mode?: string; [key: string]: unknown }; transport?: string; endpoint?: string;
  examples?: Array<Record<string, unknown>>; references?: Array<string | Record<string, unknown>>;
  [key: string]: unknown
}
export interface ResourceRun {
  id?: string; runId?: string; status: string; summary?: string; result?: Record<string, any>; trace?: Array<Record<string, any>>;
  missingEvidence?: string[]; error?: string; createdAt?: string; finishedAt?: string; revision?: number;
  input?: Record<string, unknown>; [key: string]: any
}
export interface ExpertResource {
  policyDomains?: string[];
  deletedAt?: string | null; references?: {items: Array<{kind:ResourceKind;id:string;name:string;relation:string;version?:string}>;historyCount:number;canDelete:boolean};
  id: string; kind: ResourceKind; name: string; summary: string; category: string; enabled: boolean;
  draft: { version: string; revision: number; content: ResourceContent; test?: ResourceRun; review?: { accepted: boolean; runId?: string; note?: string; [key: string]: unknown } };
  published?: { version: string; content: ResourceContent; publishedAt?: string; dependencies?: {skills?:Array<Record<string,any>>;mcps?:Array<Record<string,any>>;snapshot?:unknown[]}; [key: string]: unknown } | null;
  dependencies?: { skills?: Array<Record<string, any>>; mcps?: Array<Record<string, any>>; snapshot?: unknown[] }; readiness?: { ready?: boolean; canPublish?: boolean; canRun?: boolean; runReasons?: string[]; reasons?: string[]; missingEvidence?: string[]; [key: string]: unknown };
  [key: string]: unknown
}
export interface ResourceCatalog { experts: ExpertResource[]; skills: ExpertResource[]; mcps: ExpertResource[]; environment?: string; storage?: string; canManage?: boolean; [key: string]: unknown }
export interface ResourceOptions { plans: Array<{ id: string; name: string; grade?: string | number }>; semesters: Array<{ id: string; name: string }>; colleges: Array<{ id: string; name: string }>; courses?: Array<{id:string;name:string;college_id?:string}>; [key: string]: unknown }
export interface ResourceResearch { id: string; title?: string; question?: string; expertId: string; expertName?: string; expertVersion?: string; input?: Record<string, unknown>; createdAt?: string; updatedAt?: string; runs?: ResourceRun[]; turns?: Array<{ question?: string; run?: ResourceRun; [key: string]: any }>; [key: string]: any }

export type ExecutionState = 'queued'|'running'|'needs_input'|'completed'|'partial'|'blocked'|'failed'|'cancelled'
export interface BusinessTask {taskId:string;expertId:string;skillId:string;title:string;inputSchema:ResourceSchema;resultKind:string;available:boolean;reason?:string}
export interface ExpertModel {id:string;label?:string;name?:string;enabled?:boolean;available?:boolean;reason?:string}
export interface ExecutionRequest {clientRequestId:string;expertId:string;researchId?:string;expectedTurn:number;mode:'selected_task'|'question'|'clarification_answer';question:string;input:Record<string,unknown>;context?:Record<string,unknown>;originalTurnId?:string;clarificationId?:string;answer?:unknown;retryOfExecutionId?:string}
export interface ExpertExecution {id?:string;executionId?:string;researchId:string;turnId:string;taskId?:string;state:ExecutionState;failureCode?:string;summary?:string;outcome?:ResourceRun;resultId?:string;clarification?:{clarificationId:string;question:string;options?:Array<string|{id:string;label:string}>};[key:string]:any}
export interface RetainedEvidence {evidenceId:string;totalRows:number;returnedRows:number;rows:Array<Record<string,unknown>>;sourceRefs:unknown[];retentionComplete:boolean}

export interface ExpertRule {ruleId:string;version:string;revision:number;status:string;payload:Record<string,any>;source?:unknown;confirmation?:Record<string,any>;tests?:unknown;[key:string]:any}
export interface ResearchIssue {issueId:string;revision:number;originalTurnId?:string;title?:string;summary?:string;reason?:string;preparationState?:string;resolutionState?:string;neededEvidence?:unknown;[key:string]:any}
