<template>
  <div>
    <!-- 数据时效声明：快照数据，非实时 -->
    <el-alert type="warning" :closable="false" show-icon class="freshness-alert"
      :title="`本专题基于 ${stats.snapshot_semester || '—'} 学期教学快照（非实时数据）`"
      description="单人依赖判定以该学期开课快照为准；本学期新调整的教学任务不在检查范围内。" />

    <!-- 判别矩阵：教师数 × 修读规模。展示克制——检查过的正常项也如实呈现 -->
    <section class="sa-card matrix-card">
      <div class="sa-card-title">
        单人依赖判别矩阵
        <span class="extra">X=修读规模，Y=承担教师数；落在左上象限的才是保险缺口</span>
      </div>
      <div class="matrix">
        <div class="mx-corner"></div>
        <div class="mx-col-head">小班（&lt;{{ midLine }}人）</div>
        <div class="mx-col-head">中规模（{{ midLine }}–{{ highLine - 1 }}人）</div>
        <div class="mx-col-head">大规模（≥{{ highLine }}人）</div>

        <div class="mx-row-head">1人承担</div>
        <div class="mx-cell excluded">
          <span class="mx-count">{{ excludedSmall }} 门</span>
          <span class="mx-note">正常形态，明示排除</span>
        </div>
        <div class="mx-cell mid">
          <span class="mx-count">{{ midCourses.length }} 门</span>
          <span class="mx-note">中风险 · 关注</span>
          <div class="mx-dots">
            <span v-for="c in midCourses" :key="c.course_id" class="mx-dot mid"
              :title="`${c.course_name}（${c.enrolled}人）`"></span>
          </div>
        </div>
        <div class="mx-cell high">
          <span class="mx-count">{{ highCourses.length }} 门</span>
          <span class="mx-note">高风险 · 校级保险缺口</span>
          <div class="mx-dots">
            <span v-for="c in highCourses" :key="c.course_id" class="mx-dot high"
              :title="`${c.course_name}（${c.enrolled}人）`"></span>
          </div>
        </div>

        <div class="mx-row-head">≥2人承担</div>
        <div class="mx-cell ok" :style="{ gridColumn: 'span 3' }">
          有备份主讲，不在本Skill检查范围内，不输出信号
        </div>
      </div>
      <p class="matrix-foot">
        本次检查 {{ stats.snapshot_semester }} 学期单人承担课程共
        {{ (highCourses.length + midCourses.length + excludedSmall) || '—' }} 门：
        高风险 {{ highCourses.length }} 门、中风险 {{ midCourses.length }} 门、判定正常（小班）{{ excludedSmall }} 门。
      </p>
    </section>

    <!-- 高风险课程清单 -->
    <section class="sa-card">
      <div class="sa-card-title">单人依赖课程清单 <span class="extra">按修读规模降序；备份成本相对影响面极低</span></div>
      <el-table :data="courseRows" size="small" stripe>
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.level === 'high' ? 'danger' : 'warning'" effect="plain">
              {{ row.level === 'high' ? '高风险' : '中风险' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="course_name" label="课程" min-width="180" show-overflow-tooltip />
        <el-table-column prop="enrolled" label="修读人数" width="100" sortable />
        <el-table-column prop="lesson_count" label="教学班" width="80" />
        <el-table-column prop="organization_id" label="开课单位" width="130">
          <template #default="{ row }">{{ row.organization_id || '未登记' }}</template>
        </el-table-column>
        <el-table-column label="建议" min-width="220">
          <template #default>明确备份主讲人选或配置助教，纳入下一轮排课检查项</template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 排除说明：这个Skill的价值有一半在排除里 -->
    <section class="sa-card exclusions-card">
      <div class="sa-card-title">检查过但判定正常 <span class="extra">误报不是无害的，误报会杀死真报</span></div>
      <ul class="ex-list">
        <li v-for="(ex, i) in result.exclusions || []" :key="i">
          <b>{{ ex.what }}</b><p>{{ ex.why }}</p>
        </li>
      </ul>
    </section>

    <!-- 职称数据完整性 -->
    <RiskCard v-if="titleGapSignal" :signal="titleGapSignal" @evidence="emit('evidence', $event)" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DecisionSignal, SkillSection } from '@/types/decision'
import RiskCard from '../components/cards/RiskCard.vue'

const props = defineProps<{ result: SkillSection & { run_at?: string } }>()
const emit = defineEmits<{ evidence: [signal: DecisionSignal] }>()

const stats = computed(() => props.result.summary_stats || {})
const overview = computed(() =>
  props.result.signals.find(s => s.signal_type === 'single_teacher_overview'))
const overviewCtx = computed(() => (overview.value?.context || {}) as Record<string, any>)
const titleGapSignal = computed(() =>
  props.result.signals.find(s => s.signal_type === 'title_data_gap'))

const highCourses = computed<any[]>(() => overviewCtx.value.high_courses || [])
const midCourses = computed<any[]>(() => overviewCtx.value.mid_courses || [])
const highLine = computed(() => overviewCtx.value.high_enrolled_line || 300)
const midLine = 30

const excludedSmall = computed(() =>
  Math.max(0, (stats.value.courses_in_snapshot || 0)
    - highCourses.value.length - midCourses.value.length))

const courseRows = computed(() => [
  ...highCourses.value.map(c => ({ ...c, level: 'high' })),
  ...midCourses.value.map(c => ({ ...c, level: 'mid' })),
].sort((a, b) => b.enrolled - a.enrolled))
</script>

<style scoped>
.freshness-alert { margin-bottom: 14px; }
.matrix-card { margin-bottom: 14px; }
.matrix { display: grid; grid-template-columns: 90px 1fr 1fr 1fr; gap: 6px; }
.mx-col-head, .mx-row-head { font-size: 11px; color: #909399; display: flex;
  align-items: center; justify-content: center; text-align: center; padding: 6px 4px; }
.mx-row-head { justify-content: flex-end; padding-right: 10px; }
.mx-cell { border: 1px dashed #dcdfe6; border-radius: 8px; min-height: 86px; padding: 10px;
  display: flex; flex-direction: column; gap: 4px; align-items: center; justify-content: center; }
.mx-cell.high { border: 1px solid #f5c6cb; background: #fdf4f4; }
.mx-cell.mid { border: 1px solid #f3e3b3; background: #fffdf5; }
.mx-cell.excluded { background: #f8fafc; }
.mx-cell.ok { background: #f0f9eb; color: #529b2e; font-size: 12px; min-height: 44px; }
.mx-count { font-size: 18px; font-weight: 700; color: #303133; }
.mx-note { font-size: 11px; color: #909399; }
.mx-dots { display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }
.mx-dot { width: 10px; height: 10px; border-radius: 50%; cursor: default; }
.mx-dot.high { background: #c45656; }
.mx-dot.mid { background: #e6a23c; }
.matrix-foot { margin: 10px 0 0; font-size: 12px; color: #606266; }
.exclusions-card { margin-bottom: 14px; }
.ex-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
.ex-list li { background: #f8fafc; border-radius: 8px; padding: 10px 14px; }
.ex-list b { font-size: 13px; color: #303133; }
.ex-list p { margin: 4px 0 0; font-size: 12px; color: #606266; line-height: 1.6; }
</style>
