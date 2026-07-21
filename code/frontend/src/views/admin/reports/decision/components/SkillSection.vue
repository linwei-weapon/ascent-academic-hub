<template>
  <section class="sa-card skill-section">
    <div class="skill-head">
      <div class="skill-title">
        <h3>{{ section.skill_name }}</h3>
        <p>{{ section.management_question }}</p>
      </div>
      <div class="skill-meta">
        <el-tag size="small" :type="section.data_readiness?.ready ? 'success' : 'danger'" effect="plain">
          {{ section.data_readiness?.ready ? '数据就绪' : '数据缺失' }}
        </el-tag>
        <el-tag size="small" type="info" effect="plain">配置 {{ section.config_version }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ section.signals.length }} 项信号</el-tag>
        <el-button type="primary" plain size="small" @click="goWorkspace">进入专题工作区</el-button>
      </div>
    </div>

    <div v-if="statEntries.length" class="stats">
      <span v-for="[k, v] in statEntries" :key="k" class="stat"><em>{{ statLabel(k) }}</em><b>{{ v }}</b></span>
    </div>

    <el-empty v-if="!section.signals.length" description="本专题当前无异常信号" :image-size="60" />
    <div v-else class="signals">
      <ConclusionCard v-for="sig in section.signals" :key="sig.signal_id" :signal="sig"
        @evidence="sig2 => emit('evidence', sig2)"
        @track="(s, n, sig2) => emit('track', s, n, sig2)" />
    </div>

    <el-collapse v-if="section.exclusions?.length || section.data_boundary" class="boundary">
      <el-collapse-item name="boundary" title="口径边界与显式排除项">
        <p v-if="section.data_boundary" class="boundary-text">{{ section.data_boundary }}</p>
        <ul v-if="section.exclusions?.length">
          <li v-for="(ex, i) in section.exclusions" :key="i">
            <b>{{ ex.what }}</b> — {{ ex.why }}
          </li>
        </ul>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { DecisionSignal, SkillSection } from '@/types/decision'
import ConclusionCard from './cards/ConclusionCard.vue'

const props = defineProps<{ section: SkillSection }>()
const emit = defineEmits<{
  track: [status: string, note: string, signal: DecisionSignal]
  evidence: [signal: DecisionSignal]
}>()
const router = useRouter()

const STAT_LABELS: Record<string, string> = {
  snapshot_semester: '数据学期',
  target_grade: '目标届',
  blocked_students: '受阻学生',
  suspected_students: '待核验学生',
  active_alerts: '活动预警',
  queue_size: '本周队列',
  stale_critical: '滞留严重',
  courses_in_snapshot: '快照课程',
  single_teacher_high: '大规模单人',
  single_teacher_mid: '中规模单人',
}

const statEntries = computed(() =>
  Object.entries(props.section.summary_stats || {})
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
    .slice(0, 8))

function statLabel(key: string): string {
  return STAT_LABELS[key] || key
}

function goWorkspace() {
  router.push(`/admin/reports/decision/skills/${props.section.skill_id}`)
}
</script>

<style scoped>
.skill-section { margin-bottom: 14px; }
.skill-head { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }
.skill-title h3 { margin: 0; font-size: 16px; color: #303133; }
.skill-title p { margin: 5px 0 0; color: #909399; font-size: 12px; }
.skill-meta { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.stats { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.stat { background: #f5f7fa; border-radius: 6px; padding: 4px 10px; font-size: 12px; }
.stat em { font-style: normal; color: #909399; margin-right: 6px; }
.stat b { color: #303133; }
.signals { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.boundary { margin-top: 12px; }
.boundary-text { margin: 0 0 8px; color: #606266; font-size: 12px; line-height: 1.6; }
.boundary ul { margin: 0; padding-left: 18px; color: #606266; font-size: 12px; line-height: 1.8; }
@media (max-width: 1100px) { .signals { grid-template-columns: 1fr; } }
</style>
