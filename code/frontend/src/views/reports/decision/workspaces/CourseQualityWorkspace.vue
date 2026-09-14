<template>
  <div>
    <!-- 概览条：基线与四态分流统计 -->
    <section class="cq-overview">
      <div class="ov-item"><span>全校基线未通过率</span><b>{{ stats.baseline_fail_rate }}%</b></div>
      <div class="ov-item"><span>可比课程</span><b>{{ stats.comparable_courses || 0 }}门</b></div>
      <div class="ov-item danger"><span>持续偏高</span><b>{{ stats.persistent_courses || 0 }}门</b></div>
      <div class="ov-item warn"><span>显著恶化</span><b>{{ stats.spike_courses || 0 }}门</b></div>
      <div class="ov-item warn"><span>高影响面</span><b>{{ stats.high_impact_courses || 0 }}门</b></div>
      <div class="ov-item good"><span>趋势向好</span><b>{{ stats.improving_courses || 0 }}门</b></div>
    </section>

    <!-- 课程卡片：状态大标签 + 趋势缩略图为卡片主体 + 证据包 -->
    <div class="cq-grid">
      <article v-for="sig in courseSignals" :key="sig.signal_id" class="course-card" :class="stateOf(sig).cls">
        <div class="cc-head">
          <el-tag :type="stateOf(sig).tag" effect="dark" size="small">{{ stateOf(sig).label }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ sig.facts['课程属性'] }}</el-tag>
          <el-tag v-if="sig.facts['课程类别']" size="small" :type="sig.facts['课程类别']==='公共必修'?'warning':'info'" effect="plain">{{ sig.facts['课程类别'] }}</el-tag>
          <span class="cc-action-when">{{ sig.action.when }}</span>
        </div>

        <h4 class="cc-title">{{ sig.entity.name }}</h4>
        <p class="cc-headline">{{ sig.headline }}</p>

        <!-- 趋势缩略图（卡片主体）：近4学期未通过率 + 基线 -->
        <div class="trend-box">
          <svg :viewBox="`0 0 ${SVG_W} ${SVG_H}`" class="trend-svg" preserveAspectRatio="none">
            <line :x1="0" :y1="yOf(stats.baseline_fail_rate || 0)" :x2="SVG_W" :y2="yOf(stats.baseline_fail_rate || 0)"
              stroke="#c0c4cc" stroke-dasharray="4 3" stroke-width="1" />
            <polyline :points="trendPoints(sig)" fill="none" :stroke="stateOf(sig).color" stroke-width="2" />
            <circle v-for="(p, i) in trendCoords(sig)" :key="i" :cx="p[0]" :cy="p[1]" r="2.6"
              :fill="stateOf(sig).color" />
          </svg>
          <div class="trend-labels">
            <span v-for="h in historyOf(sig)" :key="h.semester">{{ h.semester.slice(2, 7) }}<br><b>{{ h.rate }}%</b></span>
            <span class="baseline-label">基线 {{ stats.baseline_fail_rate }}%</span>
          </div>
        </div>

        <!-- 证据包：可带去教研会议的弹药 -->
        <div class="evidence-pack">
          <div v-if="sig.context?.score_band" class="ep-row">
            <span>挂科分数段</span>
            <b>集中在 {{ sig.context.score_band.band }} 分段（占 {{ sig.context.score_band.pct }}%）</b>
          </div>
          <div v-if="sig.context?.prereq" class="ep-row"><span>先修链</span><b>{{ sig.context.prereq }}</b></div>
          <div class="ep-row">
            <span>本学期</span>
            <b>{{ sig.facts['本学期未通过率'] }} · {{ sig.facts['未通过人数'] }} / {{ sig.facts['修读人数'] }}</b>
          </div>
          <div v-if="hasLayeredRates(sig)" class="ep-row">
            <span>三分层</span>
            <b>首次 {{ sig.facts['首次通过率'] }} · 补考 {{ sig.facts['补考通过率'] }} · 重修 {{ sig.facts['重修通过率'] }}（全校累计口径）</b>
          </div>
        </div>

        <div class="cc-action">
          <span>{{ sig.action.owner }}</span>
          <p>{{ sig.action.what }}</p>
        </div>
        <p class="cc-consequence">暂不处理：{{ sig.consequence }}</p>

        <div class="cc-foot">
          <el-button link type="primary" size="small" @click="emit('evidence', sig)">完整证据</el-button>
          <el-button v-if="sig.evidence.verify_route" link size="small" @click="goVerify(sig)">核验路由</el-button>
        </div>
      </article>
    </div>
    <el-empty v-if="!courseSignals.length" description="当前无结构性课程质量信号，全部课程处于正常区间" :image-size="70" />

    <!-- 积极变化 -->
    <section v-if="improvingSignal" class="sa-card improving-card">
      <div class="sa-card-title">趋势向好 <span class="extra">同比改善明显，可在教研例会通报</span></div>
      <p class="imp-headline">{{ improvingSignal.headline }}</p>
      <div class="imp-list">
        <span v-for="c in improvingCourses" :key="c.course_id" class="imp-item">
          {{ c.course_name }} <b>{{ c.from }}% → {{ c.to }}%</b>
        </span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { DecisionSignal, SkillSection, TagType } from '@/types/decision'

const props = defineProps<{ result: SkillSection & { run_at?: string } }>()
const emit = defineEmits<{ evidence: [signal: DecisionSignal] }>()
const router = useRouter()

const SVG_W = 260
const SVG_H = 64
const SVG_PAD = 6

const stats = computed(() => props.result.summary_stats || {})
const courseSignals = computed(() =>
  props.result.signals.filter(s => s.signal_type.startsWith('course_')))
const improvingSignal = computed(() =>
  props.result.signals.find(s => s.signal_type === 'improving'))
const improvingCourses = computed<any[]>(() => improvingSignal.value?.context?.courses || [])

const STATE_META: Record<string, { label: string; tag: TagType; cls: string; color: string }> = {
  persistent: { label: '持续偏高 · 建议立项复盘', tag: 'danger', cls: 'st-persistent', color: '#c45656' },
  spike: { label: '显著恶化 · 先核查数据', tag: 'warning', cls: 'st-spike', color: '#b88230' },
  high_impact: { label: '高影响面 · 配置支持', tag: 'warning', cls: 'st-impact', color: '#e6a23c' },
}

function stateOf(sig: DecisionSignal) {
  const key = sig.signal_type.replace('course_', '')
  return STATE_META[key] || { label: key, tag: 'info' as TagType, cls: '', color: '#909399' }
}

function historyOf(sig: DecisionSignal): { semester: string; rate: number }[] {
  return sig.context?.history || []
}

// M1：三分层通过率 facts 为可选附加证据，后端未附带时不渲染该行
function hasLayeredRates(sig: DecisionSignal): boolean {
  return sig.facts?.['首次通过率'] != null || sig.facts?.['补考通过率'] != null || sig.facts?.['重修通过率'] != null
}

function yOf(rate: number): number {
  const max = Math.max(30, ...courseSignals.value.flatMap(s => historyOf(s).map(h => h.rate)))
  return SVG_H - SVG_PAD - (Math.min(rate, max) / max) * (SVG_H - SVG_PAD * 2)
}

function trendCoords(sig: DecisionSignal): [number, number][] {
  const hist = historyOf(sig)
  if (!hist.length) return []
  const step = hist.length > 1 ? (SVG_W - SVG_PAD * 2) / (hist.length - 1) : 0
  return hist.map((h, i) => [SVG_PAD + i * step, yOf(h.rate)])
}

function trendPoints(sig: DecisionSignal): string {
  return trendCoords(sig).map(([x, y]) => `${x},${y}`).join(' ')
}

function goVerify(sig: DecisionSignal) {
  if (sig.evidence.verify_route) router.push(sig.evidence.verify_route)
}
</script>

<style scoped>
.cq-overview { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 14px; }
.ov-item { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 10px 12px; }
.ov-item span { display: block; color: #909399; font-size: 11px; }
.ov-item b { display: block; margin-top: 4px; font-size: 17px; color: #303133; }
.ov-item.danger b { color: #c45656; }
.ov-item.warn b { color: #b88230; }
.ov-item.good b { color: #67c23a; }
.cq-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.course-card { background: #fff; border: 1px solid #e4e7ed; border-left: 4px solid #909399;
  border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 9px; }
.course-card.st-persistent { border-left-color: #c45656; }
.course-card.st-spike { border-left-color: #b88230; }
.course-card.st-impact { border-left-color: #e6a23c; }
.cc-head { display: flex; gap: 6px; align-items: center; }
.cc-action-when { margin-left: auto; color: #b45309; font-size: 11px; }
.cc-title { margin: 0; font-size: 16px; color: #303133; }
.cc-headline { margin: 0; font-size: 12px; color: #606266; line-height: 1.6; }
.trend-box { background: #f8fafc; border-radius: 8px; padding: 10px 12px 6px; }
.trend-svg { width: 100%; height: 64px; display: block; }
.trend-labels { display: flex; justify-content: space-between; font-size: 10px; color: #909399;
  text-align: center; padding-top: 2px; }
.trend-labels b { color: #606266; }
.baseline-label { align-self: center; }
.evidence-pack { display: flex; flex-direction: column; gap: 5px; background: #eef2ff;
  border-radius: 8px; padding: 9px 12px; }
.ep-row { display: flex; gap: 10px; font-size: 12px; }
.ep-row span { flex-shrink: 0; color: #94a3b8; font-size: 11px; width: 60px; padding-top: 1px; }
.ep-row b { color: #3730a3; font-weight: 500; }
.cc-action { font-size: 12px; }
.cc-action span { color: #94a3b8; font-size: 11px; }
.cc-action p { margin: 2px 0 0; color: #334155; line-height: 1.6; }
.cc-consequence { margin: 0; font-size: 12px; color: #9f1239; }
.cc-foot { display: flex; justify-content: flex-end; gap: 4px; border-top: 1px dashed #ebeef5; padding-top: 6px; }
.improving-card { margin-bottom: 14px; }
.imp-headline { margin: 0 0 10px; font-size: 13px; color: #303133; }
.imp-list { display: flex; flex-wrap: wrap; gap: 8px; }
.imp-item { background: #f0f9eb; border-radius: 6px; padding: 4px 10px; font-size: 12px; color: #529b2e; }
.imp-item b { margin-left: 6px; }
@media (max-width: 1100px) { .cq-overview { grid-template-columns: repeat(3, 1fr); } .cq-grid { grid-template-columns: 1fr; } }
</style>
