<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item>
      <el-breadcrumb-item>AI管理简报</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="brief-head">
      <div>
        <h2 class="sa-page-title">AI管理晨报 / 学期简报</h2>
        <p class="sa-page-sub">
          把预警、毕业准备、课程质量、教学运行、教室占用和课程团队数据组织成管理优先级、证据和下一步动作。
        </p>
      </div>
      <div class="head-actions">
        <el-radio-group v-model="period" size="small" @change="load">
          <el-radio-button label="morning">管理晨报</el-radio-button>
          <el-radio-button label="term">学期简报</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="loading" @click="load">重新生成</el-button>
      </div>
    </div>

    <el-alert
      v-if="loading && !hasData"
      class="loading-alert"
      type="info"
      :closable="false"
      show-icon
      title="正在生成AI管理简报"
      description="正在汇总预警、成绩、培养方案、教学任务、教室占用和课程团队数据，生成管理优先级与可追溯证据。"
    />
    <el-alert
      v-else-if="loading"
      class="loading-alert"
      type="info"
      :closable="false"
      show-icon
      title="正在更新简报，当前结果将保留到新结果完成"
    />

    <el-skeleton :loading="loading && !hasData" animated :rows="8">
      <section class="hero-card">
        <div class="ai-mark">AI</div>
        <div class="hero-main">
          <div class="hero-label">{{ data.targetName || 'AI管理简报' }}</div>
          <h3>{{ data.headline }}</h3>
          <p>{{ data.summary }}</p>
          <div class="hero-meta">
            <span>{{ sourceLabelText }}</span>
            <span>生成时间：{{ formatTime(data.generatedAt) }}</span>
            <span>成绩学期：{{ data.semester?.grade || '—' }}</span>
            <span>教学任务：{{ data.semester?.teaching || '—' }}</span>
          </div>
        </div>
      </section>

      <section v-if="data.periodPanel" class="period-panel sa-card">
        <div class="period-panel-head">
          <div><b>{{ data.periodPanel.title }}</b><span>{{ data.periodPanel.question }}</span></div>
          <el-tag type="info" effect="plain">{{ period === 'morning' ? '当前快照' : '学期趋势' }}</el-tag>
        </div>
        <div class="period-item-grid">
          <article v-for="item in data.periodPanel.items || []" :key="item.label">
            <span>{{ item.label }}</span>
            <b>{{ item.value }}</b>
            <p>{{ item.managementValue }}</p>
            <small v-if="item.source">业务来源：{{ businessSource(item.source) }}</small>
          </article>
        </div>
      </section>

      <div class="metric-grid">
        <div v-for="m in data.metrics || []" :key="m.label" class="metric-card" :class="m.tone">
          <span>{{ m.label }}</span>
          <b>{{ m.value }}<small>{{ m.unit }}</small></b>
          <p>{{ m.managementValue || m.hint }}</p>
          <small v-if="m.source">业务来源：{{ m.businessSource || businessSource(m.source) }}</small>
        </div>
      </div>

      <section class="sa-card">
        <div class="sa-card-title">AI给出的管理优先级</div>
        <el-table :data="data.priorities || []" stripe>
          <el-table-column prop="rank" label="顺序" width="70" />
          <el-table-column label="事项" min-width="150">
            <template #default="{ row }">
              <div class="priority-title">
                <el-tag :type="row.level === 'high' ? 'danger' : 'warning'" size="small">
                  {{ row.level === 'high' ? '高优先级' : '中优先级' }}
                </el-tag>
                <b>{{ row.theme }}</b>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="summary" label="AI摘要" min-width="260" />
          <el-table-column prop="why" label="为什么要看" min-width="280" />
          <el-table-column label="依据来源" min-width="180">
            <template #default="{ row }">
              <span class="source-text">{{ row.businessSource || businessSource(row.source || listText(trace.dataSources)) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="go(row.route, row.routeQuery)">{{ row.action || '进入专题' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <div class="section-grid">
        <section v-for="s in data.sections || []" :key="s.key" class="brief-section">
          <div class="section-top">
            <h3>{{ s.title }}</h3>
            <el-button link type="primary" @click="go(s.route)">查看专题</el-button>
          </div>
          <p class="insight">{{ s.insight }}</p>
          <p class="value">{{ s.managementValue }}</p>
          <div class="evidence-row">
            <div v-for="e in s.evidence || []" :key="e.label" class="evidence">
              <span>{{ e.label }}</span>
              <b>{{ e.value }}<small>{{ e.unit }}</small></b>
              <em v-if="e.source">业务来源：{{ e.businessSource || businessSource(e.source) }}</em>
            </div>
          </div>
        </section>
      </div>

      <section class="sa-card">
        <div class="sa-card-title">不同角色今天该怎么用</div>
        <div class="role-grid">
          <div v-for="b in data.briefs || []" :key="b.role" class="role-card">
            <span>{{ b.role }}</span>
            <b>{{ b.title }}</b>
            <p>{{ b.text }}</p>
          </div>
        </div>
      </section>

      <section class="sa-card trace-card">
        <div class="sa-card-title">AI研判追溯</div>
        <div class="trace-overview">
          <div><span>业务数据</span><b>{{ trace.businessDataSources || businessSource(listText(trace.dataSources)) }}</b></div>
          <div><span>规则与时点</span><b>{{ trace.ruleVersion || '—' }} · {{ formatTime(trace.asOfTime) }}</b></div>
        </div>
        <el-collapse class="trace-collapse">
          <el-collapse-item name="technical-trace" title="查看完整计算口径与技术追溯">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="技术来源">{{ listText(trace.dataSources) }}</el-descriptions-item>
              <el-descriptions-item label="生成方式">{{ trace.generationMethod || sourceLabelText }}</el-descriptions-item>
              <el-descriptions-item label="计算逻辑">{{ trace.calculationLogic || '—' }}</el-descriptions-item>
              <el-descriptions-item label="命中规则">{{ listText(trace.rules) }}</el-descriptions-item>
              <el-descriptions-item label="阈值说明">{{ listText(trace.thresholds) }}</el-descriptions-item>
              <el-descriptions-item label="公式/口径">{{ trace.formula || '—' }}</el-descriptions-item>
              <el-descriptions-item label="使用边界">{{ trace.boundary || '—' }}</el-descriptions-item>
              <el-descriptions-item label="解释来源">{{ explanationSourceText }}</el-descriptions-item>
            </el-descriptions>
          </el-collapse-item>
        </el-collapse>
      </section>

      <section class="sa-card">
        <div class="sa-card-title">建议下一步动作</div>
        <ol class="action-list">
          <li v-for="a in data.nextActions || []" :key="a">{{ a }}</li>
        </ol>
        <el-alert
          v-if="data.limitations?.length"
          type="info"
          :closable="false"
          show-icon
          title="边界说明"
          :description="data.limitations.join('；')"
        />
      </section>
    </el-skeleton>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getManagementBriefing } from '@/utils/ai'

const router = useRouter()
const loading = ref(false)
const period = ref<'morning' | 'term'>('morning')
const data = reactive<any>({})
const hasData = computed(() => Boolean(data.targetName))

const sourceLabelText = computed(() => normalizeSourceLabel(data.sourceLabel || 'AI辅助管理简报'))
const trace = computed(() => data.traceability || {})
const explanationSourceText = computed(() => {
  const sources = data.explanationSources || trace.value.explanationSources || []
  if (!Array.isArray(sources) || !sources.length) return '—'
  return sources.map((x: any) => `${x.name || '解释'}：${x.source || '—'}${x.usage ? `（${x.usage}）` : ''}`).join('；')
})

function normalizeSourceLabel(label: string) {
  if (label === '离线大模型研判样本') return label
  return String(label || '').replace('AI增强', 'AI辅助').replace('样本', '')
}

function listText(value: any) {
  if (Array.isArray(value)) return value.join('；')
  return value || '—'
}

const businessSourceMap: Record<string, string> = {
  fact_alert: '学业预警记录', fact_grade: '学生成绩明细', student_plan_course_status: '学生培养方案课程完成证据',
  teaching_lesson: '教学任务与教学班', fact_room_occupancy: '实际教室占用记录', agg_course_team: '课程团队结构汇总',
}
function businessSource(value: any) {
  const raw = String(value || '')
  const labels = Object.entries(businessSourceMap).filter(([key]) => raw.includes(key)).map(([, label]) => label)
  return [...new Set(labels)].join('、') || raw || '当前页面业务数据'
}

function formatTime(value?: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 19)
}

function go(path?: string, query?: Record<string, string>) {
  if (path) router.push({ path, query: query || {} })
}

async function load() {
  loading.value = true
  try {
    const result = await getManagementBriefing({ period: period.value })
    Object.keys(data).forEach((key) => delete data[key])
    Object.assign(data, result)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.brief-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.head-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-top: 12px;
}

.loading-alert {
  margin: 12px 0;
}
.trace-overview { display:grid; grid-template-columns:1.3fr 1fr; gap:10px; margin-bottom:8px; }
.trace-overview > div { padding:10px 12px; border:1px solid #e2e8f0; border-radius:9px; background:#f8fafc; }
.trace-overview span { display:block; color:#64748b; font-size:11px; }
.trace-overview b { display:block; margin-top:4px; color:#334155; font-size:12px; line-height:1.55; }
.trace-collapse { border-top:0; }
.trace-collapse :deep(.el-collapse-item__header) { height:40px; color:#4f46e5; font-size:12px; font-weight:600; }
.period-panel { margin: 0 0 14px; }
.period-panel-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:12px; }
.period-panel-head b { display:block; color:#1e293b; font-size:14px; }
.period-panel-head span { display:block; margin-top:4px; color:#64748b; font-size:12px; }
.period-item-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.period-item-grid article { padding:11px 12px; border:1px solid #e2e8f0; border-radius:10px; background:#f8fafc; }
.period-item-grid article > span { display:block; color:#64748b; font-size:11px; }
.period-item-grid article > b { display:block; margin-top:5px; color:#1e293b; font-size:14px; line-height:1.45; }
.period-item-grid p { margin:5px 0 0; color:#64748b; font-size:11px; line-height:1.55; }
.period-item-grid small { display:block; margin-top:5px; color:#94a3b8; font-size:10px; }
@media (max-width: 1100px) { .period-item-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }

.hero-card {
  display: flex;
  gap: 18px;
  padding: 20px;
  border-radius: 16px;
  background: linear-gradient(135deg, #eef2ff 0%, #f8fafc 52%, #ecfeff 100%);
  border: 1px solid #dbeafe;
  box-shadow: 0 10px 30px rgba(79, 70, 229, 0.08);
  margin: 12px 0 14px;
}

.ai-mark {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: #4f46e5;
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 800;
  letter-spacing: .08em;
}

.hero-label {
  font-size: 12px;
  color: #4f46e5;
  font-weight: 700;
}

.hero-main h3 {
  margin: 5px 0 8px;
  color: #0f172a;
  font-size: 22px;
}

.hero-main p {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.8;
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  color: #64748b;
  font-size: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.metric-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  border-top: 4px solid #4f46e5;
}

.metric-card.danger { border-top-color: #e11d48; }
.metric-card.warning,
.metric-card.amber { border-top-color: #d97706; }
.metric-card.teal { border-top-color: #0d9488; }
.metric-card.success { border-top-color: #16a34a; }

.metric-card span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.metric-card b {
  display: block;
  margin: 6px 0;
  font-size: 24px;
  color: #0f172a;
}

.metric-card small {
  margin-left: 3px;
  font-size: 12px;
  color: #64748b;
}

.metric-card p {
  margin: 0;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.5;
}

.metric-card > small,
.source-text {
  display: block;
  margin-top: 6px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.5;
}

.priority-title {
  display: flex;
  gap: 8px;
  align-items: center;
}

.section-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 14px 0;
}

.brief-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
}

.section-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-top h3 {
  margin: 0;
  color: #1e293b;
  font-size: 16px;
}

.insight {
  color: #334155;
  font-size: 13px;
  line-height: 1.7;
  margin: 10px 0 6px;
}

.value {
  color: #64748b;
  font-size: 12px;
  line-height: 1.7;
  margin: 0 0 12px;
}

.evidence-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.evidence {
  background: #f8fafc;
  border-radius: 9px;
  padding: 10px;
}

.evidence span {
  color: #64748b;
  font-size: 11px;
}

.evidence b {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 18px;
}

.evidence small {
  font-size: 11px;
  color: #64748b;
  margin-left: 2px;
}

.evidence em {
  display: block;
  margin-top: 5px;
  color: #94a3b8;
  font-size: 11px;
  font-style: normal;
  line-height: 1.5;
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.role-card {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  background: #f8fafc;
}

.role-card span {
  color: #4f46e5;
  font-size: 12px;
  font-weight: 700;
}

.role-card b {
  display: block;
  margin: 6px 0;
  color: #1e293b;
}

.role-card p,
.action-list {
  color: #475569;
  font-size: 13px;
  line-height: 1.8;
}

.trace-card {
  margin-bottom: 14px;
}

@media (max-width: 1100px) {
  .brief-head,
  .head-actions {
    display: block;
  }

  .metric-grid,
  .section-grid,
  .role-grid {
    grid-template-columns: 1fr;
  }
}
</style>
