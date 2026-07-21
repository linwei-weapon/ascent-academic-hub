<template>
  <el-dialog :model-value="visible" width="560px" append-to-body
    :title="signal ? `证据卡 · ${signal.entity.name}` : '证据卡'"
    @update:model-value="emit('update:visible', $event)">
    <template v-if="signal">
      <p class="headline">{{ signal.headline }}</p>

      <div class="fact-grid">
        <div v-for="[k, v] in allFacts" :key="k" class="fact-cell">
          <span>{{ k }}</span><b>{{ v }}</b>
        </div>
      </div>

      <el-descriptions :column="1" border size="small" class="ev-desc">
        <el-descriptions-item label="数据表">{{ signal.evidence.table }}</el-descriptions-item>
        <el-descriptions-item label="筛选条件">{{ signal.evidence.condition }}</el-descriptions-item>
        <el-descriptions-item label="数据时效">{{ signal.evidence.freshness }}</el-descriptions-item>
        <el-descriptions-item label="置信度">{{ confidenceLabel(signal) }}</el-descriptions-item>
        <el-descriptions-item label="口径边界">{{ signal.data_boundary }}</el-descriptions-item>
        <el-descriptions-item v-if="signal.related?.length" label="关联信号">
          {{ signal.related.join('、') }}
        </el-descriptions-item>
      </el-descriptions>

      <div v-if="signal.suggested_questions?.length" class="questions">
        <span class="q-label">可追问</span>
        <el-button v-for="q in signal.suggested_questions" :key="q" link type="primary" size="small"
          @click="emit('ask', q, signal)">{{ q }}</el-button>
      </div>
    </template>

    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
      <el-button v-if="signal?.evidence.verify_route" type="primary" @click="goVerify">
        前往管理分析核验
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { DecisionSignal } from '@/types/decision'
import { confidenceLabel } from './signalMeta'

const props = defineProps<{ visible: boolean; signal: DecisionSignal | null }>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  ask: [question: string, signal: DecisionSignal]
}>()
const router = useRouter()

const allFacts = computed(() => Object.entries(props.signal?.facts || {}))

function goVerify() {
  if (props.signal?.evidence.verify_route) {
    emit('update:visible', false)
    router.push(props.signal.evidence.verify_route)
  }
}
</script>

<style scoped>
.headline { margin: 0 0 12px; font-size: 14px; line-height: 1.6; color: #303133; }
.fact-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }
.fact-cell { background: #f5f7fa; border-radius: 8px; padding: 8px 10px; }
.fact-cell span { display: block; color: #909399; font-size: 11px; }
.fact-cell b { display: block; margin-top: 3px; color: #303133; font-size: 13px; }
.ev-desc { margin-bottom: 12px; }
.questions { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
.q-label { color: #909399; font-size: 11px; }
</style>
