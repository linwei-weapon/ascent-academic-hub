<template>
  <!-- 风险卡：代价前置突出，用于观察项与风险信号。判断+依据紧凑，代价为主体 -->
  <article class="risk-card" :class="`sev-${signal.severity}`">
    <div class="sig-head">
      <el-tag size="small" :type="severityMeta(signal).tag" effect="dark">{{ severityMeta(signal).label }}</el-tag>
      <el-tag size="small" :type="changeMeta(signal).tag" effect="plain">{{ changeMeta(signal).label }}</el-tag>
      <span class="when">时限：{{ signal.action.when || '—' }}</span>
    </div>

    <h4 class="headline">{{ signal.headline }}</h4>

    <p class="consequence">
      <span class="c-label">代价</span>{{ signal.consequence }}
    </p>

    <div class="facts">
      <button v-for="[k, v] in factEntries(signal, 3)" :key="k" class="fact" type="button"
        title="点击查看证据" @click="emit('evidence', signal)">
        <em>{{ k }}</em><b>{{ v }}</b>
      </button>
    </div>

    <div class="sig-foot">
      <span class="evidence" :title="evidenceTitle(signal)">
        {{ signal.entity.name }} · 置信{{ confidenceLabel(signal) }}
      </span>
      <div class="ops">
        <el-button link type="primary" size="small" @click="emit('evidence', signal)">证据</el-button>
        <el-button link size="small" @click="goWorkspace">专题</el-button>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { DecisionSignal } from '@/types/decision'
import { severityMeta, changeMeta, confidenceLabel, factEntries, evidenceTitle } from './signalMeta'

const props = defineProps<{ signal: DecisionSignal }>()
const emit = defineEmits<{ evidence: [signal: DecisionSignal] }>()
const router = useRouter()

function goWorkspace() {
  router.push(`/admin/reports/decision/skills/${props.signal.skill_id}`)
}
</script>

<style scoped>
.risk-card { background: #fff; border: 1px solid #e4e7ed; border-left: 4px solid #909399;
  border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.risk-card.sev-critical { border-left-color: #c45656; background: linear-gradient(90deg, #fdf4f4, #fff 45%); }
.risk-card.sev-high { border-left-color: #e6a23c; background: linear-gradient(90deg, #fdf8ee, #fff 45%); }
.risk-card.sev-medium { border-left-color: #b88230; }
.sig-head { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.when { margin-left: auto; color: #b45309; font-size: 11px; }
.headline { margin: 0; font-size: 13px; line-height: 1.55; color: #303133; }
.consequence { margin: 0; font-size: 12px; color: #9f1239; line-height: 1.6;
  background: #fef2f2; border-radius: 6px; padding: 8px 10px; }
.c-label { display: inline-block; margin-right: 8px; font-weight: 700; font-size: 11px; }
.facts { display: flex; flex-wrap: wrap; gap: 6px; }
.fact { background: #f5f7fa; border: 1px solid transparent; border-radius: 6px; padding: 3px 8px;
  font-size: 11px; cursor: pointer; transition: border-color .15s; }
.fact:hover { border-color: #4f46e5; }
.fact em { font-style: normal; color: #909399; margin-right: 5px; }
.fact b { color: #4f46e5; }
.sig-foot { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.evidence { color: #909399; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { flex-shrink: 0; display: flex; gap: 2px; }
</style>
