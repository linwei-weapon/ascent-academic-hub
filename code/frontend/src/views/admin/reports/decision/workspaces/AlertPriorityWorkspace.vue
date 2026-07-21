<template>
  <div>
    <!-- 概览：注意力分配全景 -->
    <section class="ap-overview">
      <div class="ov-item"><span>活动预警</span><b>{{ stats.active_alerts || 0 }}条</b></div>
      <div class="ov-item danger"><span>严重级</span><b>{{ levelCount('严重') }}条</b></div>
      <div class="ov-item warn"><span>警告级</span><b>{{ levelCount('警告') }}条</b></div>
      <div class="ov-item"><span>提醒级</span><b>{{ levelCount('提醒') }}条</b></div>
      <div class="ov-item danger"><span>滞留超期未认领</span><b>{{ stats.stale_critical || 0 }}条</b></div>
      <div class="ov-item"><span>未认领总数</span><b>{{ stats.unclaimed || 0 }}条</b></div>
    </section>

    <!-- 本周优先介入队列：不做全量列表，只有排序+合成理由 -->
    <section class="sa-card queue-card">
      <div class="sa-card-title">
        本周优先介入队列
        <span class="extra">评分融合 预警等级 × 必修未通过 × GPA环比 × 滞留时长；按队列顺序安排谈话</span>
      </div>
      <el-empty v-if="!queue.length" description="本周无优先介入对象" :image-size="60" />
      <div v-else class="queue-list">
        <div v-for="item in queue" :key="item.student_id" class="queue-row"
          :class="{ top: item.rank <= 3 }">
          <span class="q-rank">{{ item.rank }}</span>
          <div class="q-main">
            <div class="q-name">
              <b>{{ item.student_name || item.student_id }}</b>
              <span class="q-id">{{ item.student_id }} · {{ item.college_id }}</span>
              <el-tag size="small" :type="item.level === '严重' ? 'danger' : item.level === '警告' ? 'warning' : 'info'"
                effect="plain">{{ item.level }}</el-tag>
              <el-tag v-if="item.days_open >= 14" size="small" type="danger" effect="plain">滞留{{ item.days_open }}天</el-tag>
            </div>
            <p class="q-reasons">{{ (item.reasons || []).join('；') }}</p>
            <p v-if="item.trigger_detail" class="q-trigger">{{ item.trigger_detail }}</p>
          </div>
          <div class="q-score">
            <span>综合评分</span><b>{{ item.score }}</b>
          </div>
        </div>
      </div>
      <p v-if="queueSignal" class="queue-foot">
        全校 {{ queueSignal.facts['全校活动预警'] }} 活动预警中合成本周队列 {{ queue.length }} 人；其余在预警工作台按常规流程处理。
        <el-button link type="primary" size="small" @click="emit('evidence', queueSignal)">评分口径与证据</el-button>
      </p>
    </section>

    <!-- 滞留严重预警 -->
    <section v-if="staleSignal" class="sa-card">
      <div class="sa-card-title">滞留超期 <span class="extra">严重级预警长期无人认领，干预机制在这些个案上已失效</span></div>
      <RiskCard :signal="staleSignal" @evidence="emit('evidence', $event)" />
      <el-table v-if="staleList.length" :data="staleList" size="small" stripe class="stale-table">
        <el-table-column prop="student_id" label="学号" width="110" />
        <el-table-column prop="student_name" label="姓名" width="100" />
        <el-table-column prop="college_id" label="学院" width="110" />
        <el-table-column prop="days_open" label="滞留天数" width="90" sortable />
        <el-table-column prop="trigger_detail" label="触发规则" min-width="200" show-overflow-tooltip />
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DecisionSignal, SkillSection } from '@/types/decision'
import RiskCard from '../components/cards/RiskCard.vue'

const props = defineProps<{ result: SkillSection & { run_at?: string } }>()
const emit = defineEmits<{ evidence: [signal: DecisionSignal] }>()

const stats = computed(() => props.result.summary_stats || {})
const queueSignal = computed(() =>
  props.result.signals.find(s => s.signal_type === 'priority_queue'))
const staleSignal = computed(() =>
  props.result.signals.find(s => s.signal_type === 'stale_critical'))

const queue = computed<any[]>(() => queueSignal.value?.context?.queue || [])
const staleList = computed<any[]>(() => staleSignal.value?.context?.stale || [])

function levelCount(level: string): number {
  return (stats.value.by_level || {})[level] || 0
}
</script>

<style scoped>
.ap-overview { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 14px; }
.ov-item { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 10px 12px; }
.ov-item span { display: block; color: #909399; font-size: 11px; }
.ov-item b { display: block; margin-top: 4px; font-size: 17px; color: #303133; }
.ov-item.danger b { color: #c45656; }
.ov-item.warn b { color: #b88230; }
.queue-card { margin-bottom: 14px; }
.queue-list { display: flex; flex-direction: column; gap: 8px; }
.queue-row { display: flex; gap: 12px; align-items: flex-start; border: 1px solid #ebeef5;
  border-radius: 8px; padding: 10px 12px; }
.queue-row.top { border-color: #f5c6cb; background: linear-gradient(90deg, #fdf6f6, #fff 50%); }
.q-rank { flex-shrink: 0; width: 26px; height: 26px; border-radius: 8px; background: #0f172a;
  color: #fff; font-weight: 700; font-size: 13px; display: grid; place-items: center; }
.queue-row:not(.top) .q-rank { background: #94a3b8; }
.q-main { flex: 1; min-width: 0; }
.q-name { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.q-name b { font-size: 14px; color: #303133; }
.q-id { color: #909399; font-size: 11px; }
.q-reasons { margin: 4px 0 0; font-size: 12px; color: #b45309; line-height: 1.5; }
.q-trigger { margin: 2px 0 0; font-size: 11px; color: #909399; }
.q-score { flex-shrink: 0; text-align: right; }
.q-score span { display: block; color: #909399; font-size: 10px; }
.q-score b { font-size: 18px; color: #0f172a; }
.queue-foot { margin: 10px 0 0; font-size: 12px; color: #606266; }
.stale-table { margin-top: 10px; }
@media (max-width: 1100px) { .ap-overview { grid-template-columns: repeat(3, 1fr); } }
</style>
