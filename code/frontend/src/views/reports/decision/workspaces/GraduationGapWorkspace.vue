<template>
  <div>
    <!-- 顶部时限条：时间窗口型价值，毕业审核前必须完成分流 -->
    <section class="deadline-bar">
      <div class="dl-main">
        <span class="dl-grade">{{ stats.target_grade }}届在校应届</span>
        <span class="dl-when">关键时点：毕业审核启动前</span>
      </div>
      <div class="dl-stats">
        <span>校级协调 <b>{{ stats.coordination_courses || 0 }}</b> 门</span>
        <span>学院处置 <b>{{ stats.college_courses || 0 }}</b> 门</span>
        <span>结构性待核验 <b>{{ stats.structural_courses || 0 }}</b> 门</span>
        <span>受阻学生 <b>{{ stats.blocked_students || 0 }}</b> 人</span>
      </div>
    </section>

    <!-- 双列分流：视觉强制区分「待处理」与「待核验」，防止误把核验类当处理类 -->
    <div class="two-lane">
      <section class="lane lane-action">
        <div class="lane-head">
          <h3>待处理 <span>明确未通过，硬证据，可直接进入处理通道</span></h3>
          <el-tag type="danger" effect="dark">{{ overviewCtx.blocked_total || 0 }} 人</el-tag>
        </div>
        <template v-if="gapSignals.length">
          <ConclusionCard v-for="sig in gapSignals" :key="sig.signal_id" :signal="sig"
            class="lane-card" :trackable="false" @evidence="sig2 => emit('evidence', sig2)" />
        </template>
        <el-empty v-else description="当前无待处理课程缺口" :image-size="60" />
        <el-table v-if="blockedStudents.length" :data="blockedStudents" size="small" stripe
          class="lane-table" max-height="320">
          <el-table-column prop="student_id" label="学号" width="110" />
          <el-table-column prop="course_name" label="未通过课程" min-width="140" show-overflow-tooltip />
          <el-table-column prop="major_name" label="专业" min-width="120" show-overflow-tooltip />
        </el-table>
        <p v-if="blockedOverflow" class="lane-note">仅展示前 {{ blockedStudents.length }} 条，完整名单见核验路由</p>
      </section>

      <section class="lane lane-verify">
        <div class="lane-head">
          <h3>待核验 <span>疑似方案映射/成绩回写问题，集中核验而非按缺修处理</span></h3>
          <el-tag type="warning" effect="dark">{{ overviewCtx.suspected_total || 0 }} 人</el-tag>
        </div>
        <template v-if="verifySignals.length">
          <ConclusionCard v-for="sig in verifySignals" :key="sig.signal_id" :signal="sig"
            class="lane-card" :trackable="false" @evidence="sig2 => emit('evidence', sig2)" />
        </template>
        <el-empty v-else description="当前无待核验缺口" :image-size="60" />
        <el-table v-if="suspectedStudents.length" :data="suspectedStudents" size="small" stripe
          class="lane-table" max-height="320">
          <el-table-column prop="student_id" label="学号" width="110" />
          <el-table-column prop="course_name" label="缺证据课程" min-width="140" show-overflow-tooltip />
          <el-table-column prop="major_name" label="专业" min-width="120" show-overflow-tooltip />
        </el-table>
        <p v-if="suspectedOverflow" class="lane-note">仅展示前 {{ suspectedStudents.length }} 条，完整名单见核验路由</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DecisionSignal, SkillSection } from '@/types/decision'
import ConclusionCard from '../components/cards/ConclusionCard.vue'

const props = defineProps<{ result: SkillSection & { run_at?: string } }>()
const emit = defineEmits<{ evidence: [signal: DecisionSignal] }>()

const stats = computed(() => props.result.summary_stats || {})
const overview = computed(() =>
  props.result.signals.find(s => s.signal_type === 'blocked_overview'))
const overviewCtx = computed(() => (overview.value?.context || {}) as Record<string, any>)

const gapSignals = computed(() =>
  props.result.signals.filter(s => s.signal_type === 'course_gap'))
const verifySignals = computed(() =>
  props.result.signals.filter(s =>
    s.signal_type === 'structural_gap' || s.signal_type === 'verification_pool'))

const blockedStudents = computed<any[]>(() => overviewCtx.value.blocked_students || [])
const suspectedStudents = computed<any[]>(() => overviewCtx.value.suspected_students || [])
const blockedOverflow = computed(() =>
  (overviewCtx.value.blocked_total || 0) > blockedStudents.value.length)
const suspectedOverflow = computed(() =>
  (overviewCtx.value.suspected_total || 0) > suspectedStudents.value.length)
</script>

<style scoped>
.deadline-bar { display: flex; justify-content: space-between; gap: 16px; align-items: center;
  background: linear-gradient(90deg, #fdf1f1, #fff 60%); border: 1px solid #f5c6cb;
  border-left: 5px solid #c45656; border-radius: 10px; padding: 14px 18px; margin-bottom: 14px; }
.dl-main { display: flex; flex-direction: column; gap: 4px; }
.dl-grade { font-size: 17px; font-weight: 700; color: #303133; }
.dl-when { font-size: 12px; color: #9f1239; }
.dl-stats { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: #606266; }
.dl-stats b { color: #c45656; font-size: 15px; }
.two-lane { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.lane { border-radius: 10px; padding: 14px; }
.lane-action { background: #fff; border: 1px solid #f5c6cb; }
.lane-verify { background: #fffdf5; border: 1px solid #f3e3b3; }
.lane-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.lane-head h3 { margin: 0; font-size: 15px; color: #303133; }
.lane-head h3 span { display: block; margin-top: 4px; font-size: 11px; font-weight: 400; color: #909399; }
.lane-card { margin-bottom: 10px; }
.lane-table { margin-top: 10px; }
.lane-note { margin: 6px 0 0; font-size: 11px; color: #909399; }
@media (max-width: 1100px) { .two-lane { grid-template-columns: 1fr; } }
</style>
