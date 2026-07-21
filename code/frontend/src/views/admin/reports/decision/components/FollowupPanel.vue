<template>
  <section class="sa-card followup-card">
    <div class="sa-card-title">
      上次建议追踪
      <span class="extra">追踪状态 × 信号是否仍存在，复核项排在最前</span>
    </div>
    <el-table :data="items" stripe>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-tag size="small" :type="stateMeta(row.state).tag" effect="plain">{{ stateMeta(row.state).label }}</el-tag>
          <el-tag size="small" :type="TRACKING_META[row.status]?.tag || 'info'" effect="plain" class="status-tag">
            {{ TRACKING_META[row.status]?.label || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="事项" min-width="220">
        <template #default="{ row }">
          <b>{{ row.headline }}</b>
          <p class="meta">{{ row.entity?.name }} · {{ row.skill_id }}</p>
        </template>
      </el-table-column>
      <el-table-column label="建议动作" min-width="200">
        <template #default="{ row }">
          {{ row.action?.what }}
          <p class="meta">{{ row.action?.owner }} · {{ row.action?.when }}</p>
        </template>
      </el-table-column>
      <el-table-column label="跟踪记录" min-width="160">
        <template #default="{ row }">
          <span>{{ row.assignee || '—' }}</span>
          <p class="meta">{{ row.note || row.state_note }}</p>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.state === 'signal_gone'" link type="success" size="small"
            @click="act(row, 'done')">确认完成</el-button>
          <el-button v-if="row.state === 'recheck'" link type="primary" size="small"
            @click="act(row, 'in_progress')">重新跟进</el-button>
          <el-button v-if="row.state === 'active'" link type="success" size="small"
            @click="act(row, 'done')">完成</el-button>
          <el-button v-if="row.state === 'active' || row.state === 'signal_gone'" link size="small"
            @click="act(row, 'dismissed')">忽略</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup lang="ts">
import type { FollowupItem, TagType } from '@/types/decision'
import { TRACKING_META } from '@/types/decision'

defineProps<{ items: FollowupItem[] }>()
const emit = defineEmits<{ track: [status: string, note: string, item: FollowupItem] }>()

// el-table 模板中的 row 为 DefaultRow，在此收敛回领域类型
function act(row: any, status: string) {
  const note = status === 'in_progress' ? '复核后仍需跟进' : ''
  emit('track', status, note, row as FollowupItem)
}

function stateMeta(state: string): { label: string; tag: TagType } {
  return ({
    recheck: { label: '需复核', tag: 'danger' },
    active: { label: '跟进中', tag: 'warning' },
    signal_gone: { label: '信号已消失', tag: 'primary' },
    closed: { label: '已闭环', tag: 'success' },
    dismissed: { label: '已忽略', tag: 'info' },
  } as Record<string, { label: string; tag: TagType }>)[state] || { label: state, tag: 'info' }
}
</script>

<style scoped>
.followup-card { margin-bottom: 14px; }
.status-tag { margin-left: 4px; }
.meta { margin: 3px 0 0; color: #909399; font-size: 11px; line-height: 1.5; }
</style>
