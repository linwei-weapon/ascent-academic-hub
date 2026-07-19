<template>
  <div class="business-context" :class="{ 'is-loading': loading, 'has-error': !!error }" role="status" aria-live="polite">
    <div class="context-main">
      <span class="context-label">当前分析上下文</span>
      <el-tag size="small" effect="plain">{{ roleLabel }}</el-tag>
      <el-tag size="small" effect="plain" type="info">{{ scopeLabel }}</el-tag>
      <el-tag v-if="period" size="small" effect="plain" type="info">{{ period }}</el-tag>
      <span v-if="source" class="context-source">来源：{{ source }}</span>
    </div>
    <div class="context-state">
      <span v-if="loading" class="state loading"><i />正在更新数据，请稍候</span>
      <span v-else-if="error" class="state error">{{ error }}</span>
      <span v-else class="state ready">{{ updatedAt ? `页面数据更新于 ${updatedAt}` : '数据已按当前权限范围加载' }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { authStore } from '@/store/auth'

defineProps<{
  period?: string
  source?: string
  loading?: boolean
  error?: string
  updatedAt?: string
}>()

const roleLabel = computed(() => authStore.user?.permissionContext?.activeRoleName || authStore.user?.roleName || '当前身份')
const scopeLabel = computed(() => {
  const detail = authStore.user?.permissionContext?.detailScope as any
  const type = detail?.type
  const ids = detail?.sourceScopeIds || []
  if (type === 'all') return '明细范围：全校'
  if (type === 'college') return `明细范围：${authStore.user?.scope?.collegeName || '本学院'}`
  if (type === 'major') return '明细范围：本专业'
  if (type === 'class') return `明细范围：${ids.length || authStore.user?.scope?.classIds?.length || 0}个行政班`
  if (type === 'staff_relation') return '明细范围：所带学生'
  if (type === 'teacher') return '明细范围：所授学生'
  return '明细范围：待核验'
})
</script>

<style scoped>
.business-context{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:38px;margin:8px 0 14px;padding:7px 12px;border:1px solid #e2e8f0;border-radius:9px;background:#f8fafc;color:#475569;font-size:12px}
.context-main,.context-state{display:flex;align-items:center;gap:8px;min-width:0}
.context-label{font-weight:700;color:#334155;white-space:nowrap}
.context-source{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#64748b}
.state{white-space:nowrap}
.state.ready{color:#64748b}
.state.error{color:#b91c1c}
.state.loading{display:flex;align-items:center;gap:6px;color:#4338ca;font-weight:600}
.state.loading i{width:7px;height:7px;border-radius:50%;background:#4f46e5;animation:pulse 1s ease-in-out infinite}
.is-loading{border-color:#c7d2fe;background:#eef2ff}
.has-error{border-color:#fecaca;background:#fef2f2}
@keyframes pulse{0%,100%{opacity:.35;transform:scale(.8)}50%{opacity:1;transform:scale(1.15)}}
@media(max-width:900px){.business-context{align-items:flex-start;flex-direction:column}.context-main{flex-wrap:wrap}.context-state{align-self:flex-end}}
</style>
