<!-- 专家团研究工作区：保留来源提交的业务与交互，归入 AI 管理决策模块。 -->
<template>
  <section class="research-result" :class="{ limited: result.status === 'blocked' }" :aria-label="result.title">
    <div class="result-meta"><span>{{ result.status === 'reference' ? '已有分析说明' : actualNames || '本轮分析' }}</span><span>{{ result.scope_label }}</span></div>
    <div class="result-tabs" role="group" aria-label="本轮分析阅读内容"><button :aria-pressed="view === 'summary'" @click="view = 'summary'">分析意见</button><button :aria-pressed="view === 'data'" @click="view = 'data'">课程与数据</button></div>
    <div v-show="view === 'summary'">
    <section v-if="result.critical_issues?.length" class="critical-issues" aria-label="影响判断的资料问题"><b>这项资料问题会影响判断</b><p v-for="issue in result.critical_issues" :key="issue.plan">{{ issue.plan }}：{{ issue.text }}</p><button class="link" @click="$emit('sources', result, 'documents')">查看对应原文</button></section>
    <h3>{{ result.headline || result.title }}</h3>
    <p v-if="result.decision_summary" class="decision-summary">{{ result.decision_summary }}</p>
    <p v-if="result.body && result.body !== result.headline" class="body-text">{{ result.body }}</p>
    <p v-if="result.management_note && result.management_note !== result.body" class="management-note"><b>建议下一步</b>{{ result.management_note }}</p>
    <p class="data-date">{{ result.data_time_note || '资料时间' }}<template v-if="result.data_time"> · {{ date(result.data_time) }}</template><template v-if="result.semester"> · {{ result.semester }}</template></p>
    <details v-if="result.discussion_points?.length" class="discussion-points" aria-label="建议讨论的事项"><summary>具体讨论事项 · {{ result.discussion_points.length }}项</summary><article v-for="point in result.discussion_points" :key="point.title"><b>{{ point.title }}</b><p>{{ point.detail }}</p><p class="quiet">需了解：{{ point.needed }}</p><button class="link" @click="$emit('sources', result, point.source)">{{ point.source === 'documents' ? '查看相关原文' : '查看对应课程' }}</button></article></details>
    </div>
    <div v-show="view === 'data'">
    <p v-if="result.request_receipt" class="request-receipt">{{ result.request_receipt }}</p>
    <div v-if="scopeStats.length" class="scope-facts" aria-label="本轮课程数量概览"><div v-for="item in scopeStats" :key="item.label"><span>{{ item.label }}</span><b>{{ item.value }}<small>门</small></b></div></div>
    <details v-if="recommendation?.candidates.length" class="candidate-list"><summary>为什么选择这些对照专业</summary><p class="quiet">{{ recommendation.method }} {{ recommendation.boundary }}</p><button v-for="plan in recommendation.candidates" :key="plan.plan_id" :disabled="readonly || busy || plan.plan_id === result.comparison?.target.plan_id" @click="$emit('compare', plan.plan_id)"><span><b>{{ plan.major_name }}</b><small>已明确课程共同 {{ plan.shared }} 门 / 并集 {{ plan.union }} 门（{{ plan.subset_overlap }}%）</small><small>分类待明确 {{ plan.source_pending }} / {{ plan.target_pending }} 门，未计入</small></span><span>{{ plan.plan_id === result.comparison?.target.plan_id ? '当前对象' : '改为比较此专业' }}</span></button></details>
    <details v-if="result.candidates?.length" class="candidate-list" :open="['paths', 'similarity'].includes(result.scenario)">
      <summary class="section-caption">其他可比较专业 · 按本轮口径，展开不会改变当前对象</summary>
      <button v-for="candidate in result.candidates" :key="candidate.plan_id" :disabled="readonly || busy" @click="$emit('compare', candidate.plan_id)">
        <span><b>{{ candidate.major_name }}</b><small>{{ candidate.grade }}级 · {{ candidate.plan_name }}</small></span>
        <span v-if="result.expert_id === 'transfer'">逐门必修覆盖 {{ candidate.required_coverage == null ? '未提供' : candidate.required_coverage + '%' }}</span>
        <span v-else>课程结构重合 {{ candidate.focus_similarity ?? candidate.structural_similarity ?? '未提供' }}{{ candidate.focus_similarity == null && candidate.structural_similarity == null ? '' : '%' }}</span>
        <small v-if="!readonly">比较 →</small>
      </button>
    </details>
    <div v-for="table in result.tables || []" :key="table.id" class="result-table">
      <details :open="expandedTables.has(table.id) || primaryTables.includes(table.id)" @toggle="toggleTable(table.id, $event)">
        <summary>{{ table.title }} <small>{{ table.rows.length }}项</small></summary>
        <div class="table-scroll" tabindex="0" :aria-label="table.title + '，可横向滚动'"><table>
          <thead><tr><th v-for="column in table.columns" :key="column.key">{{ column.label }}</th></tr></thead>
          <tbody><tr v-for="(row, index) in table.rows.slice(0, expandedRows.has(table.id) ? undefined : 5)" :key="index"><td v-for="column in table.columns" :key="column.key">{{ cell(row[column.key]) }}</td></tr></tbody>
        </table></div>
        <p v-if="!table.rows.length" class="quiet">当前范围未返回相关记录，不能据此推定所有条件满足。</p>
        <button v-if="table.rows.length > 5" class="link expand" @click="toggleRows(table.id)">{{ expandedRows.has(table.id) ? '收起明细' : `展开全部${table.rows.length}项` }}</button>
        <p v-if="table.note" class="quiet">{{ table.note }}</p>
      </details>
    </div>
    </div>
    <details v-if="result.missing?.length" class="missing" :open="result.status === 'blocked'">
      <summary>尚需明确 · {{ result.missing.length }}项</summary>
      <ul><li v-for="text in result.missing" :key="text">{{ text }} <button v-if="!readonly" class="link" @click="$emit('question', text)">留为待明确</button></li></ul>
    </details>
    <details v-if="result.limitations?.length" class="boundaries"><summary>适用条件</summary><ul><li v-for="text in result.limitations" :key="text">{{ text }}</li></ul></details>
    <div class="result-tools">
      <button v-if="!hideSources" class="link" @click="$emit('sources', result)">查看本轮资料与计算方法</button>
      <button v-if="!readonly" class="link" @click="$emit('adopt', result.headline + (result.management_note ? '\n' + result.management_note : ''))">纳入我的意见</button>
    </div>
    <div v-if="!readonly && result.suggestions?.length" class="next-actions"><button v-for="text in result.suggestions.slice(0, 2)" :key="text" @click="$emit('prefill', text)">{{ text }}</button></div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ComparatorRecommendation, ResearchExpert, ResearchResult } from '@/types/expertResearch'
const props = defineProps<{ result: ResearchResult; experts: ResearchExpert[]; busy?: boolean; readonly?: boolean; hideSources?: boolean }>()
defineEmits<{ sources: [result: ResearchResult, target?: string]; compare: [id: string]; question: [text: string]; adopt: [text: string]; prefill: [text: string] }>()
const expandedTables = ref(new Set<string>()), expandedRows = ref(new Set<string>())
const view = ref<'summary' | 'data'>('summary')
const recommendation = computed(() => (props.result as ResearchResult & { comparison_recommendation?: ComparatorRecommendation }).comparison_recommendation)
const primaryTables = ['selected_shared', 'options', 'course_options', 'course_current', 'diagnosis_questions', 'bottlenecks', 'transition_summary', 'transition_schedule', 'readiness', 'performance']
const scopeStats = computed(() => {
  const rows = props.result.tables?.find(t => t.id === 'scope_summary')?.rows || []
  return [{ key: '来源已纳入课程', label: props.result.comparison?.source.major_name || '本专业' }, { key: '比较方已纳入课程', label: props.result.comparison?.target.major_name || '对照专业' }, { key: '双方共同课程', label: '双方共同课程' }].flatMap(item => { const row = rows.find(r => r.item === item.key); return row ? [{ label: item.label, value: row.value }] : [] })
})
const actualNames = computed(() => (props.result.actual_experts || (props.result.expert_id ? [props.result.expert_id] : [])).map(id => props.experts.find(e => e.id === id)?.name || '历史分析视角').join('、'))
const cell = (value: unknown) => value == null || value === '' ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value)
const date = (value: string) => Number.isNaN(new Date(value).getTime()) ? value : new Date(value).toLocaleString('zh-CN', { hour12: false })
function toggleRows(id: string) { expandedRows.value.has(id) ? expandedRows.value.delete(id) : expandedRows.value.add(id) }
function toggleTable(id: string, event: Event) { (event.target as HTMLDetailsElement).open ? expandedTables.value.add(id) : expandedTables.value.delete(id) }
</script>

<style lang="scss" scoped>
.research-result{padding:8px 0 18px;color:#283246}.result-meta{display:flex;gap:12px;flex-wrap:wrap;color:#7b8090;font-size:12px;margin-bottom:12px}.research-result h3{font-size:20px;line-height:1.65;font-weight:600;margin:0 0 14px;color:#252a3b}.body-text,.management-note{white-space:pre-wrap;line-height:1.95;font-size:16px;margin:12px 0;overflow-wrap:anywhere}.management-note{color:#4b4766}.data-date,.quiet{font-size:12px;line-height:1.8;color:#778092}.section-caption{font-size:13px;color:#72778a}.candidate-list{margin:20px 0}.candidate-list>button{display:flex;align-items:center;justify-content:space-between;gap:14px;width:100%;border:0;border-bottom:1px solid #e9e9f0;background:#fafaff;text-align:left;padding:13px 14px;color:#4a4565;font:inherit;font-size:13px;cursor:pointer}.candidate-list b{display:block;font-weight:550}.candidate-list small{display:block;color:#848397;font-size:12px;margin-top:3px}.missing{padding:13px 16px;background:#fffaf0;border-left:3px solid #d6b66d;margin:18px 0;font-size:14px;line-height:1.9;color:#795f2d}.missing ul,.boundaries ul{padding-left:20px}.result-table{margin:15px 0;border-top:1px solid #e6e8ee}.result-table summary{font-size:14px;font-weight:550;padding:13px 0;cursor:pointer}.result-table summary small{font-size:12px;font-weight:400;color:#858c99;margin-left:9px}.table-scroll{overflow-x:auto;border:1px solid #e6e8ee;border-radius:7px}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}th{background:#f7f7fa;color:#677084;font-weight:500;white-space:nowrap;padding:11px 13px}td{border-top:1px solid #eeeef4;padding:11px 13px;line-height:1.8;min-width:72px;max-width:300px;overflow-wrap:anywhere}.boundaries{font-size:13px;color:#737b8b;line-height:1.8;margin:16px 0}.boundaries summary{cursor:pointer}.result-tools{display:flex;gap:20px;flex-wrap:wrap;margin-top:18px}.link{border:0;background:none;color:#6552aa;font:inherit;font-size:13px;cursor:pointer;padding:3px 0}.link:hover{text-decoration:underline}.expand{margin-top:9px}.next-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}.next-actions button{border:1px solid #ddd8ed;background:#faf9ff;color:#625480;border-radius:7px;padding:9px 12px;font:inherit;font-size:13px;cursor:pointer}.limited h3{color:#826627}button:disabled{opacity:.6;cursor:not-allowed}button:focus-visible,summary:focus-visible,.table-scroll:focus-visible{outline:2px solid #7963be;outline-offset:3px}@media(max-width:700px){.candidate-list>button{align-items:flex-start;flex-direction:column;gap:6px}.research-result h3{font-size:18px}}
.result-meta,.data-date,.quiet,.boundaries{color:#667085}.candidate-list small,.result-table summary small{color:#6f687a}
.management-note{padding:12px 16px;background:#f8fafc;border-left:3px solid #a5b4fc;color:#334155}.management-note>b{display:block;font-size:14px;color:#4f46e5;margin-bottom:4px}.link{color:#4f46e5;min-height:32px}.result-meta{color:#475569}.research-result h3{color:#1e293b}.boundaries,.quiet{font-size:13px}.next-actions button{border-color:#c7d2fe;color:#4f46e5;background:#f8faff}
.request-receipt{font-size:13px;line-height:1.8;color:#625577;background:#f7f5fb;border-radius:7px;padding:10px 12px}.critical-issues{padding:14px 16px;border-left:3px solid #b89041;background:#fff9ec;font-size:14px;line-height:1.8;margin:16px 0;color:#725525}.critical-issues p{margin:8px 0}.decision-summary{font-size:16px;line-height:1.9;color:#42435b}.discussion-points{margin:20px 0}.discussion-points h4{font-size:15px;margin:0 0 8px}.discussion-points article{padding:12px 0;border-bottom:1px solid #ece9f0;font-size:14px;line-height:1.85}.discussion-points article b{font-weight:550}.discussion-points p{margin:7px 0}
.result-tabs{display:flex;gap:20px;border-bottom:1px solid #e2e8f0;margin-bottom:18px}.result-tabs button{border:0;border-bottom:2px solid transparent;background:none;padding:8px 0;font:inherit;font-size:14px;color:#64748b;cursor:pointer}.result-tabs button[aria-pressed=true]{color:#4f46e5;border-bottom-color:#4f46e5;font-weight:600}.research-result h3{font-size:20px;line-height:1.65;margin-bottom:10px}.body-text,.decision-summary{font-size:15px;line-height:1.85;margin:10px 0}.management-note{font-size:14px;line-height:1.8;padding:10px 14px}.discussion-points{margin:16px 0;font-size:14px;color:#334155}.discussion-points summary{cursor:pointer;padding:8px 0}.result-table{margin:6px 0}.result-table summary{padding:10px 0}.result-tools{margin-top:12px}.next-actions{margin-top:12px}.request-receipt{color:#475569;background:#f8fafc}.result-meta{margin-bottom:5px}.research-result{padding-top:0}.data-date{margin:8px 0}.missing{padding:9px 13px;margin:14px 0}.boundaries{margin:10px 0}
.scope-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid #e2e8f0;border-radius:8px;margin:12px 0 18px}.scope-facts>div{padding:12px 16px;display:flex;flex-direction:column;gap:7px}.scope-facts>div+div{border-left:1px solid #e2e8f0}.scope-facts span{color:#64748b;font-size:13px}.scope-facts b{color:#1e293b;font-size:23px;font-weight:600}.scope-facts small{font-weight:400;font-size:12px;margin-left:6px;color:#64748b}.scope-facts>div:last-child{background:#f5f7ff}.scope-facts>div:last-child b{color:#4f46e5}
</style>
