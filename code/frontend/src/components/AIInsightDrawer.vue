<template>
  <el-drawer
    :model-value="modelValue"
    :title="title"
    size="560px"
    class="ai-insight-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="loading" class="ai-loading">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="正在生成AI辅助研判"
        description="系统正在汇总成绩、预警、培养方案、教学任务等证据，并组织结论、原因和建议动作。"
      />
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else-if="insight" class="ai-body">
      <div class="ai-hero">
        <div>
          <div class="ai-target">{{ insight.targetName || insight.targetId }}</div>
          <div class="ai-meta">
            {{ insight.profile?.college || '当前对象' }}
            <span v-if="insight.profile?.major"> · {{ insight.profile.major }}</span>
            <span v-if="insight.generatedAt"> · {{ shortTime(insight.generatedAt) }}</span>
          </div>
        </div>
        <el-tag :type="tagType(insight.riskTone || insight.riskLevel)" effect="light">
          {{ insight.riskLabel || insight.riskLevel || 'AI研判' }}
        </el-tag>
      </div>

      <div class="ai-summary">
        <div class="ai-summary-label">AI研判结论</div>
        <p>{{ insight.summary }}</p>
        <div class="ai-source">
          <span>{{ sourceLabel }}</span>
          <span>证据充分度：{{ insight.confidence || '中' }}</span>
        </div>
      </div>

      <section v-if="insight.evidence?.length" class="ai-section">
        <h4>关键证据</h4>
        <div class="evidence-grid">
          <div v-for="item in insight.evidence" :key="item.label" class="evidence-card" :class="item.tone">
            <span>{{ item.label }}</span>
            <b>{{ item.value }}</b>
            <small>{{ item.detail }}</small>
          </div>
        </div>
      </section>

      <section v-if="insight.reasons?.length" class="ai-section">
        <h4>为什么需要关注</h4>
        <ul class="ai-list">
          <li v-for="item in insight.reasons" :key="item">{{ item }}</li>
        </ul>
      </section>

      <section v-if="insight.suggestions?.length" class="ai-section">
        <h4>分角色建议</h4>
        <div class="suggestion-list">
          <div v-for="item in insight.suggestions" :key="item.role + item.action" class="suggestion-item">
            <div class="suggestion-head">
              <b>{{ item.role }}</b>
              <el-tag size="small" :type="priorityType(item.priority)" effect="plain">
                {{ priorityLabel(item.priority) }}
              </el-tag>
            </div>
            <div class="suggestion-action">{{ item.action }}</div>
            <p>{{ item.detail }}</p>
          </div>
        </div>
      </section>

      <section v-if="insight.nextActions?.length" class="ai-section">
        <h4>建议核查动作</h4>
        <ol class="ai-list numbered">
          <li v-for="item in insight.nextActions" :key="item">{{ item }}</li>
        </ol>
      </section>

      <section class="ai-section trace-section">
        <h4>研判追溯</h4>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="数据来源">{{ trace.dataSources }}</el-descriptions-item>
          <el-descriptions-item label="计算逻辑">{{ trace.calculationLogic }}</el-descriptions-item>
          <el-descriptions-item label="命中规则">{{ trace.rules }}</el-descriptions-item>
          <el-descriptions-item label="公式/口径">{{ trace.formula }}</el-descriptions-item>
          <el-descriptions-item label="使用边界">{{ trace.boundary }}</el-descriptions-item>
        </el-descriptions>
      </section>

      <el-alert
        v-if="insight.limitations?.length"
        class="ai-limit"
        type="info"
        :closable="false"
        show-icon
        title="使用边界"
        :description="insight.limitations.join('；')"
      />
    </div>

    <el-empty v-else description="暂无AI研判内容" :image-size="90" />
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modelValue: boolean
  insight?: any
  loading?: boolean
  title?: string
}>()

const emit = defineEmits<{(e: 'update:modelValue', value: boolean): void}>()

const sourceLabel = computed(() => normalizeSourceLabel(props.insight?.sourceLabel || '规则研判'))

const trace = computed(() => {
  const t = props.insight?.traceability || {}
  return {
    dataSources: listText(t.dataSources) || inferDataSources(props.insight),
    calculationLogic: t.calculationLogic || '根据当前对象的关键证据、命中原因和管理建议生成AI辅助研判。',
    rules: listText(t.rules) || inferRules(props.insight),
    formula: t.formula || '综合风险等级、关键证据数量、影响范围和管理优先级形成结论。',
    boundary: t.boundary || (props.insight?.limitations || ['仅用于管理核查和决策辅助，不替代正式审批或业务结论。']).join('；'),
  }
})

function listText(value: any) {
  return Array.isArray(value) ? value.join('；') : (value || '')
}

function normalizeSourceLabel(label: string) {
  return String(label || '')
    .replace('AI增强研判样本', 'AI辅助研判')
    .replace('AI增强管理简报样本', 'AI辅助管理简报')
    .replace('AI增强决策模拟样本', 'AI辅助决策模拟')
    .replace('AI增强', 'AI辅助')
    .replace('样本', '')
}

function inferDataSources(insight: any) {
  const scenario = insight?.scenario || ''
  if (scenario.includes('graduation')) return '培养方案完成证据、成绩记录、课程供给、课程替代关系'
  if (scenario.includes('faculty')) return '教学任务、课程团队、教师职称主数据'
  if (scenario.includes('teacher_load')) return '教师教学任务、学时、教学班、学生覆盖人次'
  if (scenario.includes('classroom')) return '实际教室占用、楼宇、时段、活动类型'
  if (scenario.includes('schedule')) return '调停课记录、原因文本、教师与教学班信息'
  if (scenario.includes('alert') || scenario.includes('student')) return '学生成绩、预警记录、学业轨迹、课程记录'
  return '当前页面已接入的业务数据与统计证据'
}

function inferRules(insight: any) {
  const parts = []
  if (insight?.riskLabel) parts.push(`风险等级：${insight.riskLabel}`)
  if (insight?.evidence?.length) parts.push(`关键证据 ${insight.evidence.length} 项`)
  if (insight?.reasons?.length) parts.push(`命中原因 ${insight.reasons.length} 项`)
  return parts.join('；') || '按当前对象证据完整度、影响范围和管理优先级生成'
}

function tagType(t: string) {
  return t === 'danger' || t === 'critical' ? 'danger' : t === 'warning' ? 'warning' : t === 'success' || t === 'low' ? 'success' : 'info'
}
function priorityType(p: string) {
  return p === 'high' ? 'danger' : p === 'medium' ? 'warning' : 'info'
}
function priorityLabel(p: string) {
  return p === 'high' ? '优先' : p === 'medium' ? '关注' : '观察'
}
function shortTime(v: string) {
  return String(v).replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.ai-loading { padding: 4px 2px; }
.ai-loading .el-alert { margin-bottom: 12px; }
.ai-body { color: var(--sa-text); }
.ai-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--sa-border);
  border-radius: 10px;
  background: #fff;
  margin-bottom: 12px;
}
.ai-target { font-size: 17px; font-weight: 700; color: #1e293b; }
.ai-meta { margin-top: 4px; font-size: 12px; color: #64748b; line-height: 1.5; }
.ai-summary {
  padding: 13px 14px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  margin-bottom: 14px;
}
.ai-summary-label { font-size: 12px; color: #4f46e5; font-weight: 700; margin-bottom: 6px; }
.ai-summary p { margin: 0; font-size: 13px; line-height: 1.8; color: #334155; }
.ai-source { display: flex; justify-content: space-between; gap: 10px; margin-top: 9px; color: #94a3b8; font-size: 11px; }
.ai-section { margin: 16px 0; }
.ai-section h4 { margin: 0 0 9px; font-size: 14px; color: #1e293b; }
.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.evidence-card {
  min-width: 0;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #fff;
}
.evidence-card span { display: block; font-size: 11px; color: #64748b; }
.evidence-card b { display: block; margin-top: 4px; color: #1e293b; font-size: 15px; word-break: break-word; }
.evidence-card small { display: block; margin-top: 4px; color: #94a3b8; font-size: 11px; line-height: 1.5; }
.evidence-card.danger { border-color: #fecdd3; background: #fff5f7; }
.evidence-card.warning { border-color: #fed7aa; background: #fff7ed; }
.evidence-card.success { border-color: #bbf7d0; background: #f0fdf6; }
.ai-list { margin: 0; padding-left: 18px; color: #475569; font-size: 13px; line-height: 1.75; }
.ai-list li { margin-bottom: 5px; }
.numbered { padding-left: 20px; }
.suggestion-list { display: grid; gap: 9px; }
.suggestion-item {
  padding: 10px 12px;
  border: 1px solid var(--sa-border);
  border-radius: 9px;
  background: #fff;
}
.suggestion-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.suggestion-head b { font-size: 13px; color: #1e293b; }
.suggestion-action { margin-top: 6px; font-size: 13px; font-weight: 600; color: #4f46e5; }
.suggestion-item p { margin: 4px 0 0; font-size: 12px; color: #64748b; line-height: 1.6; }
.trace-section :deep(.el-descriptions__label) { width: 86px; color: #64748b; }
.trace-section :deep(.el-descriptions__content) { color: #475569; font-size: 12px; line-height: 1.65; }
.ai-limit { margin-top: 14px; }
</style>
