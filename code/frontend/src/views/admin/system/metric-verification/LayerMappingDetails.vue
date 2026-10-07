<template>
  <section class="layer-mapping" aria-label="当前层的库表字段与加工关系">
    <div class="section-heading"><h5>库表与字段</h5><span class="muted">{{ dialectLabel }} · {{ layer.grain || '统计粒度待登记' }}</span></div>
    <div v-if="primaryBindings.length" class="binding-grid">
      <article v-for="item in primaryBindings" :key="item.binding.id || `${item.node.id}:${item.binding.objectName}`" class="binding-card">
        <div class="binding-heading"><strong>{{ qualifiedName(item.binding) }}</strong><span class="binding-status" :class="item.binding.status">{{ bindingStatus(item.binding.status) }}</span></div>
        <p class="muted">{{ roleLabel(item.node) }} · 粒度：{{ item.node.grain || '待登记' }}</p>
        <p v-if="!item.binding.schema" class="muted">数据库或 schema 未登记</p>
        <div class="field-list" aria-label="已登记字段"><code v-for="field in fields(item.binding, item.node)" :key="field.logical" :class="{ used: usedByQuery(item.binding, field.physical) }" :title="usedByQuery(item.binding, field.physical) ? '当前 SQL 使用的字段' : '已登记字段'">{{ field.logical === field.physical ? field.physical : `${field.logical} → ${field.physical}` }}</code><span v-if="!fields(item.binding, item.node).length" class="muted">字段待登记</span></div>
      </article>
    </div>
    <p v-else class="muted">本层尚无 {{ dialectLabel }} 物理库表绑定。{{ virtualNodes.map(item => item.logicalName).join('、') || '请根据已登记的直接来源核对。' }}</p>
    <p v-if="query?.dependencies?.length && primaryBindings.length" class="field-legend">深色字段为当前 SQL 使用的字段；“结构已核实”表示库表字段存在。</p>
    <details v-if="secondaryBindings.length" class="other-bindings"><summary>查看 {{ otherDialects }} 对照与设计依据（{{ secondaryBindings.length }}个对象）</summary><article v-for="item in secondaryBindings" :key="item.binding.id || item.node.id" class="design-binding"><strong>{{ qualifiedName(item.binding) }}</strong><span class="binding-status">{{ bindingStatus(item.binding.status) }} · {{ item.binding.dialect || '方言未知' }}</span><p class="muted">粒度：{{ item.node.grain || '待登记' }}</p><p class="field-text">{{ fields(item.binding, item.node).map(field => field.logical === field.physical ? field.physical : `${field.logical} → ${field.physical}`).join(' · ') || '字段待登记' }}</p></article></details>

    <div v-if="relations.length" class="processing"><h5>本层已登记的加工依据</h5><p class="muted">下列关联与处理步骤来自已登记的映射及查询方案；本次执行条件以下方所选 SQL 为准。</p>
      <article v-for="relation in relations" :key="relation.step.id" class="processing-step">
        <div class="relation-path"><span class="step-kind">{{ kindLabel(relation.step.kind) }}</span><strong>{{ relation.inputs.map(nodeName).join('、') }} → {{ nodeName(relation.step.outputNodeId) }}</strong></div>
        <p v-if="relation.descriptions[0]">{{ relation.descriptions[0] }}</p>
        <p v-if="relation.step.join?.keys?.length" class="join-keys"><strong>{{ joinLabel(relation.step.join.type) }}：</strong><code v-for="(key, index) in relation.step.join.keys" :key="index">{{ fieldName(key.left) }} = {{ fieldName(key.right) }}</code></p>
        <p v-if="relation.step.join?.snapshotCondition"><strong>时点与批次：</strong>{{ readableText(relation.step.join.snapshotCondition) }}</p>
        <details v-if="relation.step.physicalPredicate" class="predicate"><summary>筛选与分组条件</summary><pre>{{ readableText(relation.step.physicalPredicate) }}</pre></details>
        <div v-for="group in relation.fieldGroups" :key="group.expression" class="field-mapping">
          <p v-if="group.expression" class="mapping-basis">{{ readableText(group.expression) }}</p>
          <ul><li v-for="field in group.rows.slice(0, 4)" :key="`${field.from}:${field.to}:${field.queryId || ''}`"><code>{{ fieldName(field.from) }}</code><span aria-label="映射为"> → </span><code>{{ fieldName(field.to) }}</code><small v-if="field.queryId" class="field-query">查询依据：{{ queryTitle(field.queryId) }}</small></li></ul>
          <details v-if="group.rows.length > 4"><summary>其余 {{ group.rows.length - 4 }} 处字段对应</summary><ul><li v-for="field in group.rows.slice(4)" :key="`${field.from}:${field.to}:${field.queryId || ''}`"><code>{{ fieldName(field.from) }}</code> → <code>{{ fieldName(field.to) }}</code><small v-if="field.queryId" class="field-query">查询依据：{{ queryTitle(field.queryId) }}</small></li></ul></details>
        </div>
        <details v-if="relation.descriptions.length > 1"><summary>补充加工说明（{{ relation.descriptions.length - 1 }}项）</summary><ul><li v-for="description in relation.descriptions.slice(1)" :key="description">{{ description }}</li></ul></details>
        <details v-if="relation.evidence.length" class="step-evidence"><summary>依据：{{ relation.evidence.slice(0, 2).map(item => item.label).join('；') }}{{ relation.evidence.length > 2 ? ` 等${relation.evidence.length}条` : '' }}</summary><article v-for="item in relation.evidence" :key="item.key"><strong>{{ item.label }}</strong><pre>{{ item.excerpt || '该依据未保存原文摘录。' }}</pre></article></details>
      </article>
    </div>
    <p v-else class="muted">当前层尚未登记关联键或加工步骤，请依据 SQL 和需求补齐映射。</p>
    <div v-if="layer.id === 'application'" class="application-binding"><strong>{{ actualSummary }}</strong><details v-if="metric.actualBinding?.reason"><summary>应用结果对应说明</summary><p>{{ metric.actualBinding.reason }}</p></details></div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MappingLineageNode, MappingMetric, MappingPhysicalBinding, MappingProcessingStep, MappingSource, VerificationLayer, VerificationQuery } from '@/types/metricVerification'
const props = defineProps<{ metric: MappingMetric; layer: VerificationLayer; query?: VerificationQuery; sources?: MappingSource[] }>()
const nodes = computed(() => props.metric.lineage?.nodes || [])
const layerNodes = computed(() => nodes.value.filter(node => node.layer === props.layer.id))
const bindings = computed(() => layerNodes.value.flatMap(node => (node.physicalBindings || []).map(binding => ({ node, binding }))))
const dialect = computed(() => props.query?.dialect?.toLowerCase() || bindings.value.find(item => item.binding.status === 'observed')?.binding.dialect?.toLowerCase() || bindings.value[0]?.binding.dialect?.toLowerCase() || '')
const dialectLabel = computed(() => dialect.value ? dialect.value.toUpperCase() : '数据库方言待登记')
const primaryBindings = computed(() => bindings.value.filter(item => !item.binding.dialect || item.binding.dialect.toLowerCase() === dialect.value))
const secondaryBindings = computed(() => bindings.value.filter(item => item.binding.dialect && item.binding.dialect.toLowerCase() !== dialect.value))
const otherDialects = computed(() => [...new Set(secondaryBindings.value.map(item => item.binding.dialect?.toUpperCase()))].join(' / '))
const virtualNodes = computed(() => layerNodes.value.filter(node => !node.physicalBindings?.length))
function preferredNode(node?: MappingLineageNode) { return !node?.physicalBindings?.length || node.physicalBindings.some(binding => !binding.dialect || binding.dialect.toLowerCase() === dialect.value) }
function referenceNode(value: string) { return nodes.value.find(node => value === node.id || value.startsWith(`${node.id}.`)) }
function preferredReference(value: string) { return preferredNode(referenceNode(value)) }
function qualifiedName(binding: MappingPhysicalBinding) { return [binding.schema, binding.objectName].filter(Boolean).join('.') }
function nodeName(id: string) {
  const node = nodes.value.find(item => item.id === id)
  if (!node) return id
  const binding = node.physicalBindings?.find(item => item.dialect?.toLowerCase() === dialect.value) || node.physicalBindings?.[0]
  return binding ? qualifiedName(binding) : node.logicalName
}
function fieldName(reference: string) {
  const node = referenceNode(reference)
  if (!node) return reference
  const field = reference.slice(node.id.length + 1)
  const binding = node.physicalBindings?.find(item => item.dialect?.toLowerCase() === dialect.value) || node.physicalBindings?.[0]
  return `${nodeName(node.id)}${field ? `.${binding?.fieldMap?.[field] || field}` : ''}`
}
function readableText(value: string) {
  let text = value
  for (const node of [...nodes.value].sort((a, b) => b.id.length - a.id.length)) text = text.replaceAll(node.id, nodeName(node.id))
  return text
}
function fields(binding: MappingPhysicalBinding, node: MappingLineageNode) {
  return Object.entries(binding.fieldMap || Object.fromEntries((node.fields || []).map(field => [field, field])))
    .map(([logical, physical]) => ({ logical, physical })).sort((a, b) => Number(usedByQuery(binding, b.physical)) - Number(usedByQuery(binding, a.physical)))
}
function usedByQuery(binding: MappingPhysicalBinding, field: string) { return Boolean(props.query?.dependencies?.some(item => item.bindingId === binding.id && item.columns.includes(field))) }
function bindingStatus(status?: string) { return ({ observed: '结构已核实', design_only: '设计依据', drifted: '结构差异待核对' } as Record<string, string>)[status || ''] || '结构未核实' }
function roleLabel(node: MappingLineageNode) { return ({ related_application_object: '相关应用对象，未绑定指标实值', expected_result: '需求复算结果', application_actual: '应用实际结果', business_input: '输入数据' } as Record<string, string>)[node.role || ''] || node.logicalName }
function kindLabel(kind: string) { return ({ filter: '筛选', join: '关联', map: '字段映射', deduplicate: '去重', aggregate: '汇总', calculate: '计算', rank: '排序', bucket: '分组', select_result: '读取结果' } as Record<string, string>)[kind] || '加工' }
function joinLabel(type?: string) { return ({ inner: '内关联', left: '左关联', right: '右关联', full: '全关联', cross: '交叉关联' } as Record<string, string>)[type?.toLowerCase() || ''] || '关联键' }
function queryTitle(id: string) { return props.layer.queries.find(query => query.id === id)?.title || id }
function fieldGroups(step: MappingProcessingStep) {
  const groups = new Map<string, NonNullable<MappingProcessingStep['fieldMappings']>>()
  const seen = new Set<string>()
  for (const field of step.fieldMappings || []) {
    if (!preferredReference(field.from) || !preferredReference(field.to)) continue
    const key = `${field.from}:${field.to}:${field.expression || ''}:${field.queryId || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    const expression = field.expression || ''
    groups.set(expression, [...(groups.get(expression) || []), field])
  }
  return [...groups].map(([expression, rows]) => ({ expression, rows }))
}
function stepEvidence(step: MappingProcessingStep) {
  const references = new Set(step.evidenceRefs || [])
  return (props.sources || []).flatMap(source => (source.evidence || []).filter(item => references.has(item.id)).map(item => {
    const title = (source.title || '已登记依据').replace('106-教学数据总览功能指标详细需求说明', '106需求').replace('中国矿业大学学业分析平台数据库设计文档', '数据库设计')
    const section = item.locator?.section ? ` §${item.locator.section}` : item.locator?.heading ? ` · ${item.locator.heading.replace(/^#+\s*/u, '')}` : ''
    return { key: `${source.id}:${item.id}`, label: `${title}${section}`, excerpt: item.excerpt }
  }))
}
const relations = computed(() => {
  const seenDescriptions = new Set<string>()
  return (props.metric.processing?.steps || []).filter(step => [step.outputNodeId, ...step.inputNodeIds].some(id => layerNodes.value.some(node => node.id === id)))
    .map(step => {
      const inputs = step.inputNodeIds.filter(id => preferredNode(nodes.value.find(node => node.id === id)))
      const descriptions = (Array.isArray(step.description) ? step.description : step.description ? [step.description] : []).map(readableText).filter(text => {
        if (seenDescriptions.has(text)) return false
        seenDescriptions.add(text); return true
      })
      return { step, inputs: [...new Set(inputs)], descriptions, fieldGroups: fieldGroups(step), evidence: stepEvidence(step) }
    }).filter(item => item.inputs.length && preferredNode(nodes.value.find(node => node.id === item.step.outputNodeId)))
})
const actualSummary = computed(() => {
  if (props.layer.mappingMode === 'reference_from_fact') return '本层结果是事实层参考复算，应用实际值需另行核对。'
  if (props.metric.actualBinding?.status === 'mapped') return '已登记应用结果绑定；请按相同范围与统计时点核对实值。'
  if (props.metric.actualBinding?.status === 'manual_observed') return '已关联真实页面观测；应用数据库结果与统计时点仍需核对。'
  return '应用指标实值尚未绑定；相关表的记录不能替代该指标结果。'
})
</script>

<style scoped>
.step-evidence pre,.predicate pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:260px; overflow:auto; padding:10px; background:var(--el-fill-color-lighter); font-family:inherit; font-size:12px; line-height:1.6; }.step-evidence article { margin:10px 0; }.field-query { display:block; color:var(--el-text-color-secondary); }
.layer-mapping { margin:14px 0; font-size:13px; line-height:1.6; }.section-heading,.binding-heading { display:flex; justify-content:space-between; gap:8px; align-items:baseline; flex-wrap:wrap; } h5 { margin:0; font-size:13px; }.muted,.field-legend { color:var(--el-text-color-secondary); font-size:12px; }.binding-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr)); gap:10px; margin-top:10px; }.binding-card { min-width:0; padding:12px; border:1px solid var(--el-border-color-light); border-radius:6px; }.binding-heading strong { font-family:Consolas,monospace; overflow-wrap:anywhere; }.binding-status { flex-shrink:0; color:var(--el-text-color-secondary); font-size:11px; }.binding-status.observed { color:var(--el-color-success-dark-2); }.binding-status.drifted { color:var(--el-color-warning-dark-2); }.binding-card p { margin:5px 0; }.field-list { display:flex; gap:5px; flex-wrap:wrap; margin-top:8px; }.field-list code { background:var(--el-fill-color-light); padding:2px 5px; border-radius:3px; color:var(--el-text-color-secondary); overflow-wrap:anywhere; }.field-list code.used { color:var(--el-text-color-primary); border:1px solid var(--el-border-color); }.field-legend { margin:6px 0; }.design-binding { padding:10px 0; border-bottom:1px solid var(--el-border-color-lighter); }.design-binding>.binding-status { margin-left:10px; }.field-text { overflow-wrap:anywhere; font-family:Consolas,monospace; }.processing { margin-top:16px; }.processing-step { padding:10px 0; border-bottom:1px solid var(--el-border-color-lighter); }.relation-path { display:flex; gap:8px; align-items:baseline; }.relation-path strong { font-weight:500; overflow-wrap:anywhere; }.step-kind { color:var(--el-color-primary); white-space:nowrap; font-size:12px; }.processing-step p { margin:6px 0; overflow-wrap:anywhere; }.join-keys code { display:block; padding-left:12px; overflow-wrap:anywhere; }.predicate code { white-space:pre-wrap; overflow-wrap:anywhere; }.field-mapping ul { list-style:none; margin:5px 0; padding:0; }.field-mapping li { margin:4px 0; overflow-wrap:anywhere; }.mapping-basis { color:var(--el-text-color-secondary); font-size:12px; }.application-binding { padding:10px 12px; margin-top:12px; border-left:3px solid var(--el-color-warning); background:var(--el-color-warning-light-9); }.application-binding strong { font-weight:500; } details { margin:8px 0; } summary { cursor:pointer; color:var(--el-color-primary); } code { font-family:Consolas,monospace; font-size:12px; } @media(max-width:600px) { .relation-path { flex-direction:column; gap:3px; }.binding-heading { align-items:flex-start; }.binding-card { padding:10px; } }
</style>
