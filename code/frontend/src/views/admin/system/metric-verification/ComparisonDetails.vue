<template>
  <div class="comparison-details">
    <dl><dt>范围与期间</dt><dd>{{ comparison.scope || '未填写' }} · {{ comparison.period || '未填写期间' }}</dd><dt>统计时点</dt><dd>{{ comparison.asOf || '未填写' }}<span v-if="comparison.dataVersion"> · {{ comparison.dataVersion }}</span></dd><dt>结论覆盖</dt><dd>{{ coverageName }} · 复算起点：{{ startName }}</dd><dt>应用实际来源</dt><dd>{{ comparison.actualSource || '未取得' }}<small>{{ comparison.actualObservedAt || '未取得时间' }}</small></dd><dt>需求复算来源</dt><dd>{{ comparison.expectedSource || '未取得' }}<small>{{ comparison.expectedObservedAt || '未取得时间' }}</small></dd><dt>比较规则</dt><dd>{{ comparison.comparisonRule || '未填写' }}</dd></dl>
    <article v-for="(row, index) in comparison.rows" :key="index"><strong>{{ row.label || '比较项未命名' }} <span class="unit">{{ row.unit }}</span></strong><div class="saved-values"><div><span>应用实际</span><p>{{ row.actual || '未取得' }}</p></div><div><span>需求复算</span><p>{{ row.expected || '未取得' }}</p></div><div><span>服务端差异</span><p>{{ row.difference ?? '未取得差异' }}</p></div></div></article>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { VerificationComparison } from '@/types/metricVerification'
const props = defineProps<{ comparison: VerificationComparison }>()
const coverageName = computed(() => ({ display: '页面结果核对', fact_application: '事实层至应用结果', full_chain: '完整三层关系' }[props.comparison.coverage]))
const startName = computed(() => ({ source: '贴源层', fact: '事实层', application: '应用层', manual: '人工取得的独立依据' }[props.comparison.startLayer]))
</script>
<style scoped>
.comparison-details { font-size:12px; min-width:0; } dl { display:grid; grid-template-columns:95px minmax(0,1fr); gap:8px 12px; line-height:1.7; } dt { color:var(--el-text-color-secondary); } dd { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; } small { display:block; color:var(--el-text-color-secondary); } article { background:var(--el-fill-color-lighter); border-radius:4px; padding:12px; margin-top:10px; }.unit { font-weight:400; margin-left:8px; color:var(--el-text-color-secondary); }.saved-values { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:10px; }.saved-values span { color:var(--el-text-color-secondary); }.saved-values p { white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.7; margin:6px 0; } @media(max-width:700px) { .saved-values { grid-template-columns:1fr; } }
</style>
