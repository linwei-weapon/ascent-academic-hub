<template>
  <!-- 方案卡：动作为主体。用于上次建议追踪与处置视图：谁、做什么、何时前、为什么 -->
  <article class="action-card" :class="`state-${item.state || 'active'}`">
    <div class="ac-head">
      <el-tag v-if="item.state" size="small" :type="stateMeta.tag" effect="plain">{{ stateMeta.label }}</el-tag>
      <el-tag size="small" :type="TRACKING_META[item.status]?.tag || 'info'" effect="plain">
        {{ TRACKING_META[item.status]?.label || item.status }}
      </el-tag>
      <span class="ac-entity">{{ item.entity?.name }} · {{ item.skill_id }}</span>
    </div>

    <h4 class="headline">{{ item.headline }}</h4>

    <div class="action-box">
      <div><span>建议责任</span><b>{{ item.action?.owner || '—' }}</b></div>
      <div><span>时限</span><b class="when">{{ item.action?.when || '—' }}</b></div>
      <p>{{ item.action?.what }}</p>
      <small v-if="item.action?.rationale">{{ item.action.rationale }}</small>
    </div>

    <p v-if="item.assignee || item.note" class="record">
      跟踪记录：{{ item.assignee || '—' }}<template v-if="item.note"> · {{ item.note }}</template>
      <template v-if="item.updated_at"> · {{ item.updated_at.slice(0, 16).replace('T', ' ') }}</template>
    </p>
    <p v-if="item.state_note" class="state-note">{{ item.state_note }}</p>

    <div class="ops">
      <el-button v-if="item.state === 'signal_gone'" link type="success" size="small"
        @click="act('done')">确认完成</el-button>
      <el-button v-if="item.state === 'recheck'" link type="primary" size="small"
        @click="act('in_progress', '复核后仍需跟进')">重新跟进</el-button>
      <template v-if="item.state === 'active' || !item.state">
        <el-button v-if="item.status !== 'in_progress'" link size="small" @click="act('in_progress')">处理中</el-button>
        <el-button link type="success" size="small" @click="act('done')">完成</el-button>
        <el-button link size="small" @click="act('dismissed')">忽略</el-button>
      </template>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FollowupItem, TagType } from '@/types/decision'
import { TRACKING_META } from '@/types/decision'

const props = defineProps<{ item: FollowupItem }>()
const emit = defineEmits<{ track: [status: string, note: string, item: FollowupItem] }>()

const stateMeta = computed((): { label: string; tag: TagType } => {
  return ({
    recheck: { label: '需复核', tag: 'danger' },
    active: { label: '跟进中', tag: 'warning' },
    signal_gone: { label: '信号已消失', tag: 'primary' },
    closed: { label: '已闭环', tag: 'success' },
    dismissed: { label: '已忽略', tag: 'info' },
  } as Record<string, { label: string; tag: TagType }>)[props.item.state]
    || { label: props.item.state, tag: 'info' }
})

function act(status: string, note = '') {
  emit('track', status, note, props.item)
}
</script>

<style scoped>
.action-card { background: #fff; border: 1px solid #e4e7ed; border-radius: 10px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.action-card.state-recheck { border-color: #f5c6cb; background: linear-gradient(90deg, #fdf4f4, #fff 45%); }
.ac-head { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.ac-entity { margin-left: auto; color: #909399; font-size: 11px; }
.headline { margin: 0; font-size: 13px; line-height: 1.55; color: #303133; }
.action-box { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px;
  background: #eef2ff; border-radius: 8px; padding: 10px 12px; }
.action-box span { display: block; color: #94a3b8; font-size: 11px; }
.action-box b { font-size: 12px; color: #3730a3; }
.action-box b.when { color: #b45309; }
.action-box p, .action-box small { grid-column: 1 / -1; margin: 2px 0 0; font-size: 12px;
  color: #334155; line-height: 1.6; }
.action-box small { color: #64748b; }
.record { margin: 0; font-size: 11px; color: #606266; }
.state-note { margin: 0; font-size: 11px; color: #b45309; }
.ops { display: flex; gap: 2px; justify-content: flex-end; }
</style>
