<template>
  <el-drawer
    :model-value="modelValue"
    :title="title"
    size="600px"
    class="ai-insight-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="loading" class="ai-loading">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="正在形成管理研判"
        description="系统正在核对分析范围、管理介入条件、关键证据和当前角色可执行的核查动作。"
      />
      <el-skeleton :rows="7" animated />
    </div>

    <div v-else-if="view" class="ai-body">
      <header class="object-head">
        <div>
          <div class="object-name">{{ view.targetName }}</div>
          <div class="object-meta">
            {{ view.targetMeta }}
            <span v-if="view.generatedAt"> · 数据时点 {{ shortTime(view.generatedAt) }}</span>
          </div>
        </div>
        <el-tag :type="statusTagType(view.intervention.status)" effect="light" size="large">
          {{ view.intervention.label }}
        </el-tag>
      </header>

      <template v-if="view.intervention.status !== 'no_intervention'">
        <section class="decision-card" :class="view.intervention.priority">
          <div class="section-kicker">管理结论</div>
          <h3>{{ view.decision.headline }}</h3>
          <div class="decision-meta">
            <span>{{ view.sourceLabel }}</span>
            <span>证据充分度：{{ view.confidence }}</span>
          </div>
        </section>

        <section class="ai-section why-section">
          <div class="section-title-row">
            <h4>为什么现在看</h4>
            <el-tag v-if="!view.comparison.available" type="info" effect="plain" size="small">无可比变化基准</el-tag>
          </div>
          <ul v-if="view.comparison.available && view.comparison.changes.length" class="signal-list">
            <li v-for="item in view.comparison.changes.slice(0, 3)" :key="item">{{ item }}</li>
          </ul>
          <ul v-else class="signal-list">
            <li v-for="item in view.decision.whyNow.slice(0, 3)" :key="item">{{ item }}</li>
          </ul>
          <div class="baseline-note">
            <b>{{ view.comparison.available ? '比较基准' : '判断边界' }}</b>
            <span>{{ view.comparison.baseline }}</span>
          </div>
          <div class="impact-line"><b>影响范围</b><span>{{ view.decision.impactScope || '当前对象' }}</span></div>
          <div class="impact-line consequence"><b>暂不核查的影响</b><span>{{ view.decision.consequence }}</span></div>
        </section>

        <section class="primary-action">
          <div class="action-head">
            <div>
              <span>建议当前角色先做</span>
              <h4>{{ view.primaryAction.action }}</h4>
            </div>
            <el-tag type="primary" effect="plain">{{ view.primaryAction.role }}</el-tag>
          </div>
          <p v-if="view.primaryAction.detail">{{ view.primaryAction.detail }}</p>
          <div class="action-result-grid">
            <div><span>建议时点</span><b>{{ view.primaryAction.timing || '下一业务节点前' }}</b></div>
            <div><span>预期形成</span><b>{{ view.primaryAction.expectedResult || '已核实的问题清单和处理依据' }}</b></div>
          </div>
        </section>

        <section v-if="view.focusItems.length" class="ai-section">
          <div class="section-title-row">
            <h4>优先核查对象</h4>
            <span class="section-help">只展示当前范围排序靠前的对象</span>
          </div>
          <div class="focus-list">
            <button v-for="item in view.focusItems.slice(0, 10)" :key="focusKey(item)" type="button" @click="emit('focus-item-click', item)">
              <div><b>{{ item.name || item.course_name || item.courseName || item.student_id }}</b><span>{{ item.college || item.module || '' }}</span></div>
              <p>{{ focusReason(item) }}</p>
              <span class="focus-action">查看该对象研判 →</span>
            </button>
          </div>
        </section>

        <section v-if="view.evidence.length" class="ai-section">
          <div class="section-title-row">
            <h4>支撑本次判断的关键证据</h4>
            <span class="section-help">首屏最多展示3项</span>
          </div>
          <div class="evidence-grid">
            <article v-for="item in view.evidence.slice(0, 3)" :key="item.label" :class="item.tone">
              <span>{{ item.label }}</span>
              <b>{{ item.value }}</b>
              <p>{{ item.detail }}</p>
              <small>来源：{{ item.businessSource || item.source || '当前页面业务数据' }}</small>
            </article>
          </div>
        </section>

        <section v-if="view.alternativeActions.length" class="ai-section">
          <h4>首要核查后的备选动作</h4>
          <div class="alternative-list">
            <div v-for="item in view.alternativeActions" :key="item.role + item.action">
              <b>{{ item.action }}</b>
              <span>{{ item.role || '相关业务人员' }}</span>
              <p v-if="item.detail">{{ item.detail }}</p>
            </div>
          </div>
        </section>
      </template>

      <section v-else class="no-intervention">
        <div class="no-icon">✓</div>
        <div>
          <h3>当前未发现需要AI介入的管理事项</h3>
          <p>{{ view.decision.headline }}</p>
          <small>这不代表业务对象没有任何问题，只表示当前证据未达到本场景的AI管理介入条件。</small>
        </div>
      </section>

      <section class="trace-section">
        <el-collapse>
          <el-collapse-item name="trace" title="查看完整数据来源、计算口径与使用边界">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="业务数据">{{ trace.businessDataSources || listText(trace.dataSources) }}</el-descriptions-item>
              <el-descriptions-item label="分析范围">{{ trace.scope || view.targetName }}</el-descriptions-item>
              <el-descriptions-item label="规则与时点">{{ trace.ruleVersion || '—' }} · {{ shortTime(trace.asOfTime || view.generatedAt) }}</el-descriptions-item>
              <el-descriptions-item label="生成方式">{{ trace.generationMethod || view.sourceLabel }}</el-descriptions-item>
              <el-descriptions-item label="计算逻辑">{{ trace.calculationLogic || '—' }}</el-descriptions-item>
              <el-descriptions-item label="命中规则">{{ listText(trace.rules) }}</el-descriptions-item>
              <el-descriptions-item label="阈值说明">{{ listText(trace.thresholds) }}</el-descriptions-item>
              <el-descriptions-item label="公式/口径">{{ trace.formula || '—' }}</el-descriptions-item>
              <el-descriptions-item label="解释来源">{{ explanationSourceText }}</el-descriptions-item>
              <el-descriptions-item label="使用边界">{{ trace.boundary || listText(view.limitations) }}</el-descriptions-item>
            </el-descriptions>
          </el-collapse-item>
        </el-collapse>
      </section>
    </div>

    <el-empty v-else description="暂无AI管理研判内容" :image-size="90" />
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { authStore } from '@/store/auth'
import { normalizeAIInsight } from '@/utils/aiInsight'

const props = defineProps<{
  modelValue: boolean
  insight?: any
  loading?: boolean
  title?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'focus-item-click', item: any): void
}>()

const view = computed(() => normalizeAIInsight(props.insight, authStore.user?.roleName || ''))
const trace = computed(() => view.value?.traceability || {})
const explanationSourceText = computed(() => {
  const sources = view.value?.explanationSources || []
  if (!sources.length) return '—'
  return sources.map((item: any) => `${item.name || '解释'}：${item.source || '—'}${item.usage ? `（${item.usage}）` : ''}`).join('；')
})

function statusTagType(status: string) {
  if (status === 'action_required') return 'danger'
  if (status === 'verification_required') return 'warning'
  if (status === 'watch') return 'info'
  return 'success'
}

function listText(value: any) {
  if (Array.isArray(value)) return value.join('；')
  return value || '—'
}

function shortTime(value?: string) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '—'
}

function focusKey(item: any) {
  return item.student_id || item.course_id || item.id || `${item.name}-${item.type}`
}

function focusReason(item: any) {
  if (Array.isArray(item.priorityReasons) && item.priorityReasons.length) {
    return item.priorityReasons.slice(0, 3).join('；')
  }
  const parts = [item.level, item.type]
  if (Number(item.failed_courses) > 0) parts.push(`未通过${item.failed_courses}门`)
  if (item.avg_gpa !== null && item.avg_gpa !== undefined) parts.push(`GPA ${item.avg_gpa}`)
  return parts.filter(Boolean).join(' · ') || item.reason || item.summary || '命中当前范围优先核查条件'
}
</script>

<style scoped>
.ai-loading { padding: 4px 2px; }
.ai-loading .el-alert { margin-bottom: 14px; }
.ai-body { color: var(--sa-text); }
.object-head { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; margin-bottom:12px; }
.object-name { color:#0f172a; font-size:18px; font-weight:700; }
.object-meta { margin-top:5px; color:#64748b; font-size:12px; line-height:1.55; }
.decision-card { padding:16px; border:1px solid #e2e8f0; border-left:4px solid #64748b; border-radius:12px; background:#f8fafc; }
.decision-card.high { border-left-color:#e11d48; background:#fff7f8; }
.decision-card.medium { border-left-color:#d97706; background:#fffbeb; }
.decision-card.low { border-left-color:#0d9488; background:#f0fdfa; }
.section-kicker { color:#64748b; font-size:11px; font-weight:700; letter-spacing:.08em; }
.decision-card h3 { margin:7px 0 10px; color:#1e293b; font-size:17px; line-height:1.65; }
.decision-meta { display:flex; justify-content:space-between; gap:12px; color:#64748b; font-size:11px; }
.ai-section { margin:18px 0; }
.ai-section h4 { margin:0 0 10px; color:#1e293b; font-size:14px; }
.section-title-row { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; }
.section-title-row h4 { margin:0; }
.section-help { color:#94a3b8; font-size:11px; }
.signal-list { margin:0; padding-left:20px; color:#334155; font-size:13px; line-height:1.75; }
.signal-list li { margin-bottom:5px; }
.baseline-note { display:grid; grid-template-columns:70px 1fr; gap:8px; margin-top:9px; padding:9px 10px; border-radius:8px; background:#f8fafc; color:#64748b; font-size:11px; line-height:1.55; }
.baseline-note b { color:#475569; }
.impact-line { display:grid; grid-template-columns:105px 1fr; gap:8px; margin-top:9px; color:#475569; font-size:12px; line-height:1.6; }
.impact-line b { color:#1e293b; }
.impact-line.consequence { padding-top:9px; border-top:1px dashed #e2e8f0; }
.primary-action { margin:18px 0; padding:15px; border:1px solid #c7d2fe; border-radius:12px; background:#f7f7ff; }
.action-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
.action-head span { color:#4f46e5; font-size:11px; font-weight:700; }
.action-head h4 { margin:5px 0 0; color:#1e293b; font-size:16px; }
.primary-action > p { margin:10px 0 0; color:#475569; font-size:12px; line-height:1.7; }
.action-result-grid { display:grid; grid-template-columns:1fr 1.5fr; gap:9px; margin-top:12px; }
.action-result-grid > div { padding:9px 10px; border:1px solid #e0e7ff; border-radius:8px; background:#fff; }
.action-result-grid span { display:block; color:#64748b; font-size:11px; }
.action-result-grid b { display:block; margin-top:4px; color:#334155; font-size:12px; line-height:1.55; }
.evidence-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
.evidence-grid article { min-width:0; padding:11px; border:1px solid #e2e8f0; border-radius:9px; background:#fff; }
.evidence-grid article.danger { border-color:#fecdd3; background:#fff7f8; }
.evidence-grid article.warning { border-color:#fed7aa; background:#fffbeb; }
.evidence-grid article > span { display:block; color:#64748b; font-size:11px; }
.evidence-grid article > b { display:block; margin-top:5px; color:#1e293b; font-size:16px; word-break:break-word; }
.evidence-grid article p { margin:5px 0 0; color:#64748b; font-size:11px; line-height:1.5; }
.evidence-grid article small { display:block; margin-top:7px; color:#94a3b8; font-size:10px; line-height:1.45; }
.focus-list { display:grid; gap:8px; }
.focus-list button { width:100%; padding:11px 12px; border:1px solid #e2e8f0; border-radius:9px; background:#fff; text-align:left; cursor:pointer; }
.focus-list button:hover { border-color:#a5b4fc; background:#f8f7ff; }
.focus-list button > div { display:flex; justify-content:space-between; gap:10px; }
.focus-list button b { color:#1e293b; font-size:13px; }
.focus-list button span { color:#64748b; font-size:11px; }
.focus-list button p { margin:5px 0 0; color:#475569; font-size:12px; }
.focus-list .focus-action { display:block; margin-top:6px; color:#4f46e5; font-size:11px; }
.alternative-list { display:grid; gap:8px; }
.alternative-list > div { padding:10px 12px; border:1px solid #e2e8f0; border-radius:9px; background:#fff; }
.alternative-list b { color:#334155; font-size:12px; }
.alternative-list span { margin-left:8px; color:#4f46e5; font-size:11px; }
.alternative-list p { margin:5px 0 0; color:#64748b; font-size:11px; line-height:1.55; }
.no-intervention { display:flex; gap:12px; padding:18px; border:1px solid #bbf7d0; border-radius:12px; background:#f0fdf4; }
.no-icon { display:flex; align-items:center; justify-content:center; flex:none; width:28px; height:28px; border-radius:50%; background:#0d9488; color:#fff; font-weight:700; }
.no-intervention h3 { margin:2px 0 7px; color:#166534; font-size:16px; }
.no-intervention p { margin:0; color:#475569; font-size:12px; line-height:1.65; }
.no-intervention small { display:block; margin-top:7px; color:#64748b; font-size:11px; }
.trace-section { margin-top:16px; border-top:1px solid #e2e8f0; }
.trace-section :deep(.el-collapse-item__header) { color:#4f46e5; font-size:12px; font-weight:600; }
.trace-section :deep(.el-descriptions__label) { width:92px; color:#64748b; }
.trace-section :deep(.el-descriptions__content) { color:#475569; font-size:12px; line-height:1.6; }
@media (max-width: 900px) {
  .evidence-grid, .action-result-grid { grid-template-columns:1fr; }
}
</style>
