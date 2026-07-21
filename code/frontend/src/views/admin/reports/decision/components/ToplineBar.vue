<template>
  <section class="topline-bar" :class="`urgency-${briefing.urgency}`">
    <div class="verdict">
      <el-tag :type="urgencyTag" effect="dark" class="urgency-tag">{{ urgencyLabel }}</el-tag>
      <h3 class="topline">{{ briefing.topline }}</h3>
      <p class="rationale">{{ briefing.urgency_rationale }}</p>
    </div>
    <div class="meta">
      <div class="meta-row">
        <el-tag size="small" :type="briefing.generation_method === 'llm_enhanced' ? 'primary' : 'info'" effect="plain">
          {{ briefing.generation_method === 'llm_enhanced' ? 'LLM增强' : '规则生成' }}
        </el-tag>
        <el-tag v-if="briefing.cache_hit" size="small" type="success" effect="plain">快照复用</el-tag>
      </div>
      <div class="meta-row muted">生成于 {{ formatTime(briefing.generated_at) }}</div>
      <div class="meta-row muted">数据学期 {{ briefing.semester }} · 指纹 {{ shortFp }}</div>
      <div class="meta-row muted" v-if="freshnessText">口径：{{ freshnessText }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DecisionBriefing, TagType } from '@/types/decision'

const props = defineProps<{ briefing: DecisionBriefing }>()

const urgencyLabel = computed(() => ({ critical: '紧急处置', elevated: '本周重点', normal: '常规推进' }[props.briefing.urgency]))
const urgencyTag = computed((): TagType => ({ critical: 'danger', elevated: 'warning', normal: 'success' }[props.briefing.urgency] as TagType))
const shortFp = computed(() => (props.briefing.snapshot_fingerprint || '').slice(0, 8))
const freshnessText = computed(() => {
  const parts = Object.entries(props.briefing.data_freshness || {})
    .filter(([, v]) => v && v !== props.briefing.semester)
    .map(([k, v]) => `${k}:${v}`)
  return parts.length ? `部分Skill为快照数据（${parts.join('，')}）` : ''
})

function formatTime(value: string): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.topline-bar { display: flex; justify-content: space-between; gap: 24px; padding: 20px 24px;
  border-radius: 10px; background: #fff; border: 1px solid #e4e7ed; border-left: 5px solid #909399; }
.topline-bar.urgency-critical { border-left-color: #c45656; background: linear-gradient(90deg, #fdf1f1, #fff 40%); }
.topline-bar.urgency-elevated { border-left-color: #e6a23c; background: linear-gradient(90deg, #fdf8ee, #fff 40%); }
.topline-bar.urgency-normal { border-left-color: #67c23a; }
.verdict { flex: 1; min-width: 0; }
.urgency-tag { margin-bottom: 8px; }
.topline { margin: 0 0 8px; font-size: 19px; line-height: 1.5; }
.rationale { margin: 0; color: #606266; font-size: 13px; }
.meta { flex-shrink: 0; text-align: right; display: flex; flex-direction: column; gap: 6px; }
.meta-row { display: flex; gap: 6px; justify-content: flex-end; font-size: 12px; }
.muted { color: #909399; }
</style>
