<template>
  <div :class="['traj-card', { 'sa-card': !grouped, 'traj-card--grouped': grouped }]">
    <div v-if="showHeader" class="sa-card-title">
      <span>同类预警后续轨迹
        <span class="extra">历史统计分布，不构成个体预测</span>
      </span>
      <el-popover placement="left" width="420" trigger="click">
        <template #reference>
          <el-button link type="primary" size="small">口径说明</el-button>
        </template>
        <div style="font-size:12px;line-height:1.7;color:#475569">
          <b style="display:block;margin-bottom:6px">统计口径（固定披露）</b>
          {{ methodology.text }}
          <div v-if="methodology.dataRange" style="margin-top:8px;color:#94a3b8;font-size:11px">
            数据范围：预警 {{ methodology.dataRange.alertCreatedAt?.min || '—' }} ~ {{ methodology.dataRange.alertCreatedAt?.max || '—' }}
            · 成绩学期 {{ methodology.dataRange.gradeSemesters?.first || '—' }} ~ {{ methodology.dataRange.gradeSemesters?.last || '—' }}
          </div>
        </div>
      </el-popover>
    </div>

    <div v-if="loading" class="sa-faint" style="font-size:12px">加载同类轨迹…</div>
    <div v-else-if="!bucket" class="sa-faint" style="font-size:12px">当前条件下暂无同类轨迹统计</div>
    <template v-else>
      <div class="traj-meta">
        <span>{{ bucket.ruleName }}（{{ bucket.ruleId }} × {{ bucket.level }}）</span>
        <span>历史样本 <b class="tnum">{{ bucket.sampleSize }}</b> 条 / {{ bucket.studentCount }} 名学生</span>
        <el-tag v-if="bucket.lowConfidence" type="warning" size="small" effect="plain">样本量&lt;10，低置信</el-tag>
      </div>

      <div class="traj-row">
        <div class="traj-label">事件解除/关闭占比</div>
        <div class="traj-bar"><div class="seg" :style="segStyle(bucket.resolved.ratio, '#0D9488')"></div></div>
        <div class="traj-val tnum">{{ pct(bucket.resolved.ratio) }}<span class="sa-faint">（{{ bucket.resolved.count }}条）</span></div>
      </div>

      <div class="traj-post" v-if="bucket.post">
        <template v-if="bucket.post.observable">
          <div class="traj-row">
            <div class="traj-label">GPA 变化（均值 {{ fmtMean(bucket.post.gpaDelta.mean) }}）</div>
            <div class="traj-bar">
              <div class="seg" :style="segStyle(bucket.post.gpaDelta.upRatio, '#0D9488')"></div>
              <div class="seg" :style="segStyle(bucket.post.gpaDelta.flatRatio, '#94A3B8')"></div>
              <div class="seg" :style="segStyle(bucket.post.gpaDelta.downRatio, '#E11D48')"></div>
            </div>
            <div class="traj-val tnum">升{{ pct(bucket.post.gpaDelta.upRatio) }} / 平{{ pct(bucket.post.gpaDelta.flatRatio) }} / 降{{ pct(bucket.post.gpaDelta.downRatio) }}</div>
          </div>
          <div class="traj-row">
            <div class="traj-label">后续学期新增未通过</div>
            <div class="traj-bar">
              <div class="seg" :style="segStyle(bucket.post.newFail.zeroRatio, '#0D9488')"></div>
              <div class="seg" :style="segStyle(bucket.post.newFail.oneRatio, '#F97316')"></div>
              <div class="seg" :style="segStyle(bucket.post.newFail.twoPlusRatio, '#E11D48')"></div>
            </div>
            <div class="traj-val tnum">0门{{ pct(bucket.post.newFail.zeroRatio) }} / 1门{{ pct(bucket.post.newFail.oneRatio) }} / 2+门{{ pct(bucket.post.newFail.twoPlusRatio) }}</div>
          </div>
          <div class="traj-row">
            <div class="traj-label">风险升级（同级或更高新预警）</div>
            <div class="traj-bar"><div class="seg" :style="segStyle(bucket.post.escalate.ratio, '#E11D48')"></div></div>
            <div class="traj-val tnum">{{ pct(bucket.post.escalate.ratio) }}<span class="sa-faint">（{{ bucket.post.escalate.count }}条）</span></div>
          </div>
        </template>
      </div>

      <div class="traj-grad" v-if="bucket.gradOutcome && bucket.gradOutcome.sample">
        <div class="traj-sub">
          毕业结果分布（有毕业结果数据的 {{ bucket.gradOutcome.sample }} 名学生子集；
          来源：{{ srcText(bucket.gradOutcome.sourceCounts) }}）
        </div>
        <div v-for="g in bucket.gradOutcome.dist" :key="g.status" class="traj-row">
          <div class="traj-label">{{ g.status }}</div>
          <div class="traj-bar"><div class="seg" :style="segStyle(g.ratio, '#4F46E5')"></div></div>
          <div class="traj-val tnum">{{ pct(g.ratio) }}<span class="sa-faint">（{{ g.count }}人）</span></div>
        </div>
      </div>

      <div class="traj-disclaimer">历史统计分布，不构成个体预测；样本量与口径见「口径说明」。</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { http } from '@/utils/http'

const props = withDefaults(defineProps<{
  ruleId?: string
  level?: string
  showHeader?: boolean
  grouped?: boolean
}>(), {
  showHeader: true,
  grouped: false,
})

const loading = ref(false)
const bucket = ref<any>(null)
const methodology = ref<any>({ text: '' })

function pct(x: any) { return `${Math.round((Number(x) || 0) * 1000) / 10}%` }
function fmtMean(m: any) { return m === null || m === undefined ? '—' : (m > 0 ? `+${m}` : `${m}`) }
function segStyle(ratio: any, color: string) {
  const p = Math.max(0, Math.min(1, Number(ratio) || 0)) * 100
  return { width: `${p}%`, background: color, display: p > 0 ? 'block' : 'none' }
}
function srcText(counts: any) {
  const parts: string[] = []
  if (counts?.real) parts.push(`真实数据 ${counts.real} 人`)
  if (counts?.sim) parts.push(`合成演示数据 ${counts.sim} 人`)
  return parts.join('、') || '—'
}

async function load() {
  if (!props.ruleId || !props.level) { bucket.value = null; return }
  loading.value = true
  bucket.value = null
  try {
    const d = await http.get(`/admin/alerts/trajectory?rule_id=${encodeURIComponent(props.ruleId)}&level=${encodeURIComponent(props.level)}`)
    methodology.value = d?.methodology || { text: '' }
    bucket.value = (d?.buckets || [])[0] || null
  } catch {
    bucket.value = null
  } finally {
    loading.value = false
  }
}
watch(() => [props.ruleId, props.level], load, { immediate: true })
</script>

<style scoped>
.traj-card :deep(.sa-card-title) { display: flex; justify-content: space-between; align-items: center; }
.traj-card:not(.traj-card--grouped) { margin-bottom: 12px; }
.traj-card--grouped { padding: 16px 18px; }
.traj-card--grouped + .traj-card--grouped { border-top: 1px solid var(--sa-border); }
.traj-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; font-size: 12px; color: var(--sa-muted); margin-bottom: 10px; }
.traj-sub { font-size: 12px; color: var(--sa-muted); margin: 8px 0 6px; }
.traj-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.traj-label { flex: none; width: 168px; font-size: 12px; color: var(--sa-text); }
.traj-bar { flex: 1; display: flex; height: 10px; background: #f1f5f9; border-radius: 5px; overflow: hidden; }
.traj-bar .seg { height: 100%; }
.traj-val { flex: none; min-width: 150px; text-align: right; font-size: 12px; color: var(--sa-text); }
.traj-val .sa-faint { font-size: 11px; }
.traj-disclaimer { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--sa-border); font-size: 11px; color: #B45309; }
</style>
