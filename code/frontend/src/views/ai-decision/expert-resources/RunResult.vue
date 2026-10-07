<template>
  <section class="run-result" aria-label="真实执行结果">
    <header class="result-heading"><div><span class="eyebrow">{{ mode === 'test' ? '测试记录' : '研究结果' }}</span><h3>{{ run.summary || result.summary || statusText }}</h3></div><el-tag :type="passed ? 'success' : blocked ? 'warning' : ['queued','running','cancelled'].includes(run.execution?.state||run.state)?'info':'danger'" effect="plain">{{ statusText }}</el-tag></header>
    <div class="result-meta"><span v-if="time">执行时间：{{ date(time) }}</span><span v-if="version">使用版本：{{ version }}</span><span v-if="run.runId || run.id">记录：{{ run.runId || run.id }}</span></div>
    <div v-if="scope" class="scope-line"><b>本次范围</b><span>{{ scope }}</span></div>
    <div v-if="run.referenceState==='invalid'" class="notice warning"><b>来源已失效，以下为原保存结果</b><p>{{ run.referenceReason || '原结果保留供历史核查，不能再作为有效分析依据。' }}</p></div>
    <section v-if="result.interpretation" class="source-section"><h4>{{ explanationCourse?`${explanationCourse.course_name || explanationCourse.course_id} · 原结果说明`:'结果解释' }}</h4><template v-if="explanationCourse"><div class="fact-grid"><div><span>首修人次</span><strong>{{ cell(explanationCourse.first_attempts) }}</strong></div><div><span>首修通过人次</span><strong>{{ cell(explanationCourse.first_pass) }}</strong></div><div><span>首修未通过人次</span><strong>{{ cell(explanationCourse.first_unpassed) }}</strong></div><div><span>首修通过率</span><strong>{{ cell(explanationCourse.first_pass_pct) }}%</strong></div></div><p>首修未通过人次大于0，且通过率低于同范围参照 {{ cell(result.observationBaseline?.ratePct) }}%，因此进入观察集合。它是该次观察的第 {{ explanationCourseIndex+1 }} 项，共 {{ result.observations.length }} 项。</p><p class="muted">按首修未通过人次降序、原始通过率升序及课程编码排序。数字来自原保存事实；人次按选课记录统计，来源覆盖与历史批次状态见下方依据。</p><details><summary>查看完整说明与判断边界</summary><p>{{ interpretationText }}</p></details></template><p v-else>{{ interpretationText }}</p></section>
    <nav class="result-actions" aria-label="结果核查入口"><el-button v-if="sources.length" link @click="showSources">查看数据来源与口径</el-button><el-button v-if="resultId && evidence.length" link @click="showEvidence">查看保存证据</el-button><el-button v-if="result.issues?.length" link @click="emit('show-issues')">查看待明确事项（{{ result.issues.length }}）</el-button></nav><p v-if="allowCourseAnalysis" class="next-step">点击课程名称查看单课；比例未知的记录可在待明确事项中核查。</p><p v-if="run.error" class="failure">{{ run.error }}</p>
    <p v-if="run.coverage?.note" class="muted">{{ run.coverage.note }}</p>
    <p v-if="result.resultKind" class="muted">结果性质：{{ ({facts:'事实分析',rule_check:'规则核验',scenario:'假设情景'} as Record<string,string>)[result.resultKind] || result.resultKind }}</p><section v-if="result.coverage" class="notice"><b>本次可核范围与未知</b><p v-if="planComparison">已观察双方课程安排 {{ result.coverage.observedPopulation ?? '未确认' }} 条；合并识别 {{ result.coverage.evaluablePopulation ?? '未确认' }} 种课程；未知课程编号 {{ result.coverage.unknownCount ?? '未确认' }} 条。</p><p v-else>已观察 {{ result.coverage.observedPopulation ?? '未确认' }}；可核 {{ result.coverage.evaluablePopulation ?? '未确认' }}；未知 {{ result.coverage.unknownCount ?? '未确认' }}。{{ result.coverage.note || result.coverage.reason }}</p><p v-if="planComparison">本次仅核对课程结构；相同编号不代表内容等价，课程目录学分不能作为认定或补修结论。</p><p>来源业务覆盖：{{ describe(result.coverage.sourceCoverage) || '需依据确认，保存证据完整不代表来源覆盖完整' }}</p></section><section v-if="conditions.length" class="conditions"><h4>本次已核条件</h4><article v-for="condition in conditions" :key="condition.conditionId"><el-tag :type="condition.state==='satisfied'?'success':condition.state==='not_satisfied'?'danger':'warning'">{{ conditionText(condition.state) }}</el-tag> {{ condition.name || condition.conditionId }}<p>{{ condition.reason }}</p><small>要求：{{ cell(condition.required) }} · 已观察：{{ cell(condition.observed) }}</small></article><p class="muted">状态只针对所列条件，不代表整体毕业或学位批准。</p></section><div v-if="facts.length" class="fact-grid"><div v-for="fact in facts" :key="fact.label"><span>{{ fact.label }}</span><strong>{{ fact.value }}</strong></div></div>
    <section v-for="(table, index) in tables" :key="index" class="data-section"><div class="table-title"><h4>{{ table.title || '数据明细' }}</h4><span>{{ table.totalRows ?? table.total ?? table.rows.length }} 条<span v-if="(table.totalRows || table.total) > table.rows.length">，本次展示 {{ table.rows.length }} 条</span></span></div><p v-if="planComparison" class="muted">课程目录学分仅供结构查看；未确认的方案字段见全部字段，本次不核验正式学分。</p><el-checkbox v-if="allowCourseAnalysis || planComparison" v-model="showAllColumns">显示全部字段</el-checkbox><div class="table-scroll" tabindex="0" :aria-label="table.title || '数据明细'"><table><thead><tr><th v-for="column in displayColumns(table.columns)" :key="column.key" :class="{'course-column':(allowCourseAnalysis||planComparison)&&column.key==='course_name'}">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in table.rows" :key="rowIndex"><td v-for="column in displayColumns(table.columns)" :key="column.key" :class="{'course-column':(allowCourseAnalysis||planComparison)&&column.key==='course_name'}"><button v-if="allowCourseAnalysis&&column.key==='course_name'&&row.course_id" class="course-link" :aria-label="`查看${row.course_name || row.course_id}的单课表现`" @click="emit('inspect-course',row)">{{ row.course_name || row.course_id }}<small>编号 {{ row.course_id }}</small></button><span v-else-if="planComparison&&column.key==='course_name'" class="course-name">{{ tableCell(row,column.key) }}<small>编号 {{ row.course_id || '未提供' }}</small></span><template v-else>{{ tableCell(row,column.key) }}</template></td></tr><tr v-if="!table.rows.length"><td :colspan="table.columns.length || 1" class="empty-cell">本次查询未返回记录</td></tr></tbody></table></div><p v-if="table.note" class="muted">{{ table.note }}</p></section>
    <div v-if="missing.length" class="notice warning"><b>本次仍需补充的资料</b><ul><li v-for="item in missing" :key="item">{{ item }}</li></ul></div>
    <details v-if="sources.length" ref="sourcesPanel" class="source-section"><summary>数据来源与口径 · {{ sources.length }} 项</summary><article v-for="(source,index) in sources" :key="index" class="source-card"><b>{{ source.name }}</b><dl v-if="source.structured"><template v-if="source.database"><dt>所属数据库</dt><dd>{{ source.database }}</dd></template><dt>查询时间</dt><dd>{{ source.queriedAt ? date(source.queriedAt) : '未提供' }}</dd><dt>数据更新时间</dt><dd>{{ source.dataUpdatedAt ? date(source.dataUpdatedAt) : '未提供' }}</dd><template v-if="source.rule"><dt>计算口径</dt><dd>{{ source.rule }}</dd></template></dl><p v-if="source.note">{{ source.note }}</p><a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.linkTitle || '查看来源说明' }} ↗</a></article></details>
    <section v-if="limitations.length" class="source-section"><h4>适用边界</h4><ul><li v-for="item in limitations" :key="item">{{ item }}</li></ul></section>
    <section v-if="result.recommendations?.length" class="source-section"><h4>可供讨论的建议</h4><article v-for="(recommendation,index) in result.recommendations" :key="index"><p>{{ describe(recommendation) }}</p></article></section><section v-if="resultId && evidence.length" ref="evidencePanel" class="source-section" tabindex="-1"><h4>本次保存证据</h4><RetainedEvidence v-for="item in evidence" :key="item.evidenceId" :result-id="resultId" :item="item" :publication-id="publicationId" :preset-id="presetId" /></section><details v-if="run.trace?.length" class="trace"><summary>查看执行过程 · {{ run.trace.length }} 步</summary><ol><li v-for="(step, index) in run.trace" :key="index"><b>{{ step.title || step.name || step.step || `步骤 ${index + 1}` }}</b><span>{{ step.summary || step.message || step.description || executionState(step.status) }}</span><code v-if="step.tool">{{ step.tool }}</code><small v-if="step.durationMs != null || step.elapsedMs != null">耗时 {{ step.durationMs ?? step.elapsedMs }} ms</small></li></ol></details>
    <p v-if="mode === 'test' && passed" class="review-note">执行已完成。发布前还需核对结果是否符合业务要求。</p>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import RetainedEvidence from './RetainedEvidence.vue'
import type { ResourceOptions, ResourceRun } from '@/types/expertResources'
const props = defineProps<{ run: ResourceRun; version?: string; mode?: 'test' | 'research'; options?: ResourceOptions; allowCourseAnalysis?:boolean; publicationId?:string; presetId?:string }>()
const emit=defineEmits<{'inspect-course':[row:Record<string,unknown>];'show-issues':[]}>()
const sourcesPanel=ref<HTMLDetailsElement|null>(null),evidencePanel=ref<HTMLElement|null>(null),showAllColumns=ref(false)
async function showSources(){await nextTick();if(sourcesPanel.value){sourcesPanel.value.open=true;sourcesPanel.value.scrollIntoView({block:'start'});sourcesPanel.value.querySelector('summary')?.focus()}}
async function showEvidence(){await nextTick();evidencePanel.value?.scrollIntoView({block:'start'});evidencePanel.value?.focus({preventScroll:true})}
watch(()=>props.run.id,()=>{showAllColumns.value=false})
const result = computed(() => props.run.result || {})
const interpretationText=computed(()=>typeof result.value.interpretation==='string'?result.value.interpretation:result.value.interpretation?.text||result.value.interpretation?.summary||describe(result.value.interpretation))
const explanationCourseIndex=computed(()=>{const id=result.value.interpretation?.objectRef?.course_id;return id==null||!Array.isArray(result.value.observations)?-1:result.value.observations.findIndex((row:Record<string,unknown>)=>String(row.course_id)===String(id))})
const explanationCourse=computed(()=>explanationCourseIndex.value<0?null:result.value.observations[explanationCourseIndex.value])
const planComparison=computed(()=>props.mode==='research'&&result.value.scope?.comparisonMode==='all_course_ids')
const passed = computed(() => {const state=props.run.execution?.state||props.run.state;return state?state==='completed':['passed', 'succeeded', 'success', 'completed'].includes(props.run.status)})
const blocked = computed(() => ['blocked', 'limited', 'partial', 'needs_input', 'missing_evidence'].includes(props.run.execution?.state||props.run.state||props.run.status))
const statusText = computed(() => ({queued:'等待执行',running:'执行中',needs_input:'需要补充条件',partial:'部分结果',completed:'执行完成',blocked:'条件未满足',failed:'执行失败',cancelled:'已取消'}[String(props.run.execution?.state||props.run.state)]|| (passed.value ? '执行完成' : blocked.value ? '条件未满足' : props.run.status === 'running' ? '执行中' : '执行失败')))
const conditionText=(state:string)=>({satisfied:'满足',not_satisfied:'不满足',unknown:'未知',not_applicable:'不适用',met:'满足',unmet:'不满足'}[state]||'未知')
const resultId=computed(()=>props.run.resultId||result.value.resultId||props.run.execution?.resultId)
const evidence=computed(()=>Array.isArray(result.value.evidence)?result.value.evidence:[])
const conditions=computed(()=>Array.isArray(result.value.conditions)?result.value.conditions:[])
const time = computed(() => props.run.finishedAt || props.run.createdAt || result.value.executedAt || result.value.dataTime)
const labels: Record<string,string> = { plan_id:'方案编号',plan_name:'培养方案',course_id:'课程编号',course_name:'课程名称',course_code:'课程代码',credits:'学分',credit:'学分',semester_id:'学期',semester:'学期',college_id:'学院编号',college_name:'学院',student_count:'学生数',record_count:'记录数',row_count:'记录数',count:'数量',total:'总记录数',shared_count:'共同课程数',source_count:'来源课程数',target_count:'对照课程数',similarity:'相似度',overlap_rate:'重合率',grade:'年级',major_name:'专业',required:'必修',course_type:'课程类型',status:'状态',name:'名称',value:'结果',label:'项目',title:'名称',ruleVersion:'规则版本',database:'所属数据库',table:'数据表',queryTime:'查询时间',data_time:'数据时间' }
const cell = (value: unknown): string => value == null || value === '' ? '未提供' : typeof value === 'boolean' ? value ? '是' : '否' : typeof value === 'object' ? JSON.stringify(value) : String(value)
function describe(value: unknown): string { if (value == null) return ''; if (typeof value !== 'object') return String(value); return Object.entries(value as Record<string,unknown>).filter(([,v]) => v != null && v !== '').map(([k,v]) => `${labels[k] || k}：${cell(v)}`).join(' · ') }
function planLabel(value: unknown): string {
  if (!value || typeof value !== 'object') return typeof value === 'string' ? value : '选定的培养方案'
  const plan=value as Record<string,unknown>
  const name=plan.plan_name || plan.name || '选定的培养方案'
  return `${name}${plan.grade==null || plan.grade==='' ? '' : `（${plan.grade}级）`}`
}
const scope = computed(() => {
  const scope=result.value.scope || props.run.scope
  if (typeof scope==='string') return scope
  if (!scope || typeof scope!=='object') return ''
  const parts:string[]=[]
  if(scope.plan)parts.push(`培养方案：${planLabel(scope.plan)}`)
  if(scope.targetPlan)parts.push(`对照方案：${planLabel(scope.targetPlan)}`)
  const semester=scope.semester_name || props.options?.semesters.find(item=>String(item.id)===String(scope.semester_id))?.name
  const college=scope.college_name || props.options?.colleges.find(item=>String(item.id)===String(scope.college_id))?.name
  if(semester)parts.push(`学期：${semester}`)
  else if(scope.semester_id)parts.push('本次选择的学期')
  if(college)parts.push(`学院：${college}`)
  else if(scope.college_id)parts.push('本次选择的授权学院')
  if(scope.course_id){const course=props.options?.courses?.find(item=>String(item.id)===String(scope.course_id));parts.push(course?`课程：${course.name}（${scope.course_id}）`:`课程编号：${scope.course_id}`)}
  if(!scope.plan&&!scope.targetPlan&&!scope.college_id)parts.push('当前身份授权范围')
  if(scope.environment)parts.push(`环境：${scope.environment}`)
  return parts.join(' · ')
})
function safeUrl(value:unknown):string { if(typeof value!=='string')return '';try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:''}catch{return ''} }
const sources = computed(() => {
  const values=Array.isArray(result.value.sources)?result.value.sources:result.value.sources?[result.value.sources]:[]
  return values.map((source:unknown)=>{
    if(!source || typeof source!=='object')return {name:cell(source),structured:false}
    const item=source as Record<string,any>
    return {name:cell(item.name || item.title || item.table || '数据来源'),structured:true,database:item.database,
      queriedAt:item.queriedAt || item.queryTime,dataUpdatedAt:item.dataUpdatedAt || item.updated_at,
      rule:item.rule || item.method,note:item.note,url:safeUrl(item.url || item.sourceUrl),linkTitle:item.linkTitle}
  })
})
const limitations = computed(() => (result.value.limitations || []).map((item: unknown) => describe(item)))
const missing = computed(() => [...new Set([...(props.run.missingEvidence || []), ...(result.value.missingEvidence || [])])])
const facts = computed(() => {
  const values=result.value.facts
  // 多对象指标在明细表按对象呈现，不能把同名指标平铺成无归属的卡片。
  const objectRefs=Array.isArray(values)?new Set(values.filter((fact:any)=>fact.objectRef).map((fact:any)=>JSON.stringify(fact.objectRef))):new Set()
  if(Array.isArray(values)&&objectRefs.size<=1)return values.map((fact:any)=>({label:fact.name||fact.factId,value:fact.value==null?'未知':`${cell(fact.value)}${fact.unit||''}`}))
  return Object.entries(result.value.data || {}).filter(([key,value]) => !['rows','columns','tables','columnLabels','scopeFingerprint','scope_fingerprint','identityId','identity_id','跨行唯一学生人数'].includes(key) && (value===null || typeof value !== 'object')).map(([key,value]) => ({label: result.value.columnLabels?.[key] || labels[key] || key, value:value==null?'未知':cell(value)}))
})
const tables = computed(() => {
  const explicit = result.value.tables || result.value.data?.tables
  if (Array.isArray(explicit)) return explicit.map((table: any) => ({...table, rows:table.rows || [], columns: table.columns || Object.keys(table.rows?.[0] || {}).map(key => ({key,label:labels[key] || key}))}))
  const rows = result.value.data?.rows || result.value.rows
  if (!Array.isArray(rows)) return []
  const columns = result.value.columns || result.value.data?.columns || [...new Set(rows.flatMap(row => Object.keys(row)))].map(key => ({key,label:result.value.columnLabels?.[key] || labels[key] || key}))
  return [{ title:result.value.dataTitle || '查询数据', rows, columns, total:result.value.data?.total, note:result.value.dataNote }]
})
function tableCell(row:Record<string,unknown>,key:string){if(key==='rate_reason'&&!row[key])return row.first_pass_pct==null?'原因未记录':'—';if(key==='suggested_term'){const term=/^TERM_(\d+)$/.exec(String(row[key]));if(term)return `第${term[1]}学期`}return cell(row[key])}
function displayColumns(columns:Array<{key:string;label:string}>){
  if(showAllColumns.value)return columns
  if(planComparison.value){const keys=['course_name','对照状态','module','credits','suggested_term'];return keys.flatMap(key=>columns.filter(column=>column.key===key))}
  if(!props.allowCourseAnalysis)return columns
  const labels:Record<string,string>={course_name:'课程',first_pass_pct:'首修通过率（%）',first_attempts:'首修人次',first_pass:'首修通过人次',failures:'未通过次数',rate_reason:'比例未知或冲突原因'}
  return Object.entries(labels).filter(([key])=>columns.some(column=>column.key===key)).map(([key,label])=>({key,label}))
}
const date = (value:string) => Number.isNaN(new Date(value).getTime()) ? value : new Date(value).toLocaleString('zh-CN', {hour12:false,timeZone:'Asia/Shanghai'})
const executionState=(value:unknown)=>({passed:'完成',completed:'完成',blocked:'条件未满足',failed:'失败',running:'执行中'}[String(value)] || '已记录')
</script>
<style scoped>
.result-actions{display:flex;flex-wrap:wrap;gap:8px 16px;margin:12px 0}.result-actions .el-button{margin:0}.next-step{color:#526176;font-size:13px}.source-section{scroll-margin-top:16px}.course-link{border:0;background:none;padding:0;font:inherit;text-align:left;color:#344b77;text-decoration:underline;cursor:pointer;min-width:140px}.course-name{display:block;min-width:140px}.course-name small{display:block;color:#64748b;font-size:11px}.course-link small{display:block;text-decoration:none;color:#64748b;font-size:11px}.course-link:focus-visible{outline:2px solid #344b77;outline-offset:3px}td.course-column{position:sticky;left:0;background:#fff;z-index:1}th.course-column{left:0;z-index:2}.run-result{color:#334155;font-size:14px;line-height:1.75}.result-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}.eyebrow{font-size:12px;color:#64748b}.result-heading h3{font-size:18px;line-height:1.65;margin:5px 0 12px;color:#172b4d;font-weight:600}.result-meta{font-size:12px;color:#64748b;display:flex;gap:8px 20px;flex-wrap:wrap;overflow-wrap:anywhere}.scope-line{background:#f6f8fb;border:1px solid #e4e8ef;border-radius:6px;padding:10px 14px;display:flex;gap:14px;margin:16px 0}.scope-line b{flex-shrink:0}.fact-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}.fact-grid>div{border:1px solid #e2e8f0;padding:12px 16px;border-radius:6px}.fact-grid span{display:block;font-size:12px;color:#64748b}.fact-grid strong{display:block;font-size:22px;margin-top:3px;color:#273f65}.data-section{margin:22px 0}.table-title{display:flex;gap:16px;justify-content:space-between;align-items:center;margin-bottom:8px}.table-title h4,.source-section h4{font-size:14px;margin:0;font-weight:600}.table-title>span,.muted{font-size:12px;color:#64748b}.table-scroll{overflow:auto;max-height:540px;border:1px solid #e2e8f0;border-radius:6px}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}th{background:#f5f7fa;position:sticky;top:0;font-weight:600;white-space:nowrap;color:#475569}th,td{padding:10px 13px;border-bottom:1px solid #e7ebf0;min-width:90px;max-width:350px;overflow-wrap:anywhere}.empty-cell{text-align:center;padding:25px;color:#64748b}.notice{padding:12px 16px;border-radius:6px;margin:16px 0}.warning{background:#fff8ea;color:#79591e}.notice ul,.source-section ul{padding-left:20px;margin:5px 0 0}.source-section{border-top:1px solid #e4e8ef;padding-top:14px;margin-top:18px;font-size:13px;color:#526176}.trace{margin-top:20px;font-size:13px;color:#526176}.trace summary{cursor:pointer}.trace li{margin:10px 0}.trace span,.trace small{display:block}.trace small{color:#64748b}.review-note{font-size:13px;color:#526176;margin:20px 0 0}.failure{background:#fef2f2;padding:12px;color:#991b1b;border-radius:5px}summary:focus-visible,.table-scroll:focus-visible{outline:2px solid #344b77;outline-offset:3px}@media(max-width:650px){.scope-line,.result-heading{flex-direction:column;gap:5px}.fact-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.source-card{padding:14px 0;border-bottom:1px solid #e8edf3;overflow-wrap:anywhere}.source-card:last-child{border-bottom:0}.source-card>b{font-weight:550;color:#425a78}.source-card dl{display:grid;grid-template-columns:105px minmax(0,1fr);gap:6px 12px;margin:10px 0}.source-card dt{color:#7b8798}.source-card dd{margin:0;white-space:pre-wrap}.source-card p{font-size:12px;color:#75849a;line-height:1.8;margin:8px 0 0}.source-card a{display:inline-block;margin-top:7px;color:#344b77;text-decoration:underline}.trace code{display:block;font-size:11px;color:#6c7c92;margin-top:4px}@media(max-width:560px){.source-card dl{grid-template-columns:1fr;gap:3px}.source-card dd{margin-bottom:7px}}
</style>
