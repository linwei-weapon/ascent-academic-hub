<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item>
      <el-breadcrumb-item>AI决策模拟</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="sim-head">
      <div>
        <h2 class="sa-page-title">AI决策模拟：毕业准备课程保障</h2>
        <p class="sa-page-sub">
          基于培养方案完成证据、必修课未通过、开课供给、课程替代和课程团队情况，对重修资源、认定核查和课程团队保障进行方案比较。
        </p>
      </div>
      <el-button type="primary" :loading="loading" @click="load">按当前约束测算</el-button>
    </div>

    <section class="simulation-controls sa-card">
      <div class="control-title">
        <div>
          <b>资源约束与管理侧重点</b>
          <span>调整后重新测算各方案覆盖规模、剩余缺口和实施优先级</span>
        </div>
        <el-tag type="info" effect="plain">测算参数，不写入业务数据</el-tag>
      </div>
      <div class="control-grid">
        <label><span>可新增班级</span><el-input-number v-model="params.addedClasses" :min="0" :max="20" /></label>
        <label><span>单班计划容量</span><el-input-number v-model="params.classCapacity" :min="15" :max="120" :step="5" /></label>
        <label><span>可协调教师</span><el-input-number v-model="params.availableTeachers" :min="0" :max="20" /></label>
        <label><span>本轮优先目标</span>
          <el-select v-model="params.priorityFocus">
            <el-option label="均衡处理" value="balanced" />
            <el-option label="优先处理明确未通过" value="failed" />
            <el-option label="优先核验缺证据" value="verification" />
          </el-select>
        </label>
      </div>
      <div class="control-foot">
        当前最多可形成 <b>{{ Math.min(params.addedClasses, params.availableTeachers) }}</b> 个新增班，计划新增容量
        <b>{{ Math.min(params.addedClasses, params.availableTeachers) * params.classCapacity }}</b> 人次。
      </div>
    </section>

    <el-alert
      v-if="loading"
      class="loading-alert"
      type="info"
      :closable="false"
      show-icon
      title="正在进行AI决策模拟"
      description="正在汇总必修课缺口、开课供给、课程替代和课程团队约束，测算不同管理动作的覆盖规模与实施边界。"
    />

    <el-skeleton :loading="loading" animated :rows="8">
      <section class="hero-card">
        <div>
          <span class="hero-label">{{ sourceLabelText }}</span>
          <h3>{{ data.targetName }}</h3>
          <p>{{ data.summary }}</p>
        </div>
        <div class="hero-badge">
          <span>模拟学期</span>
          <b>{{ data.semester || '—' }}</b>
        </div>
      </section>

      <div class="metric-grid">
        <div v-for="m in data.metrics || []" :key="m.label" class="metric-card">
          <span>{{ m.label }}</span>
          <b>{{ m.value }}<small>{{ m.unit }}</small></b>
          <p>{{ m.managementValue || m.hint }}</p>
          <small v-if="m.source">业务来源：{{ m.businessSource || businessSource(m.source) }}</small>
        </div>
      </div>

      <el-alert
        class="scope-alert"
        type="info"
        :closable="false"
        show-icon
        title="口径说明"
        description="“涉及学生”为去重学生数；“明确未通过、到期缺证据、预计优先核查”为课程人次，同一学生多门课程会重复计算。"
      />

      <section class="sa-card">
        <div class="sa-card-title">AI推荐策略</div>
        <div class="recommendation">
          <div>
            <span>优先方案</span>
            <b>{{ data.recommendation?.bestScenarioTitle || '—' }}</b>
            <p>{{ data.recommendation?.reason }}</p>
          </div>
          <div>
            <span>组合打法</span>
            <p>{{ data.recommendation?.combinedStrategy }}</p>
          </div>
        </div>
      </section>

      <section class="scenario-grid">
        <article v-for="s in data.scenarios || []" :key="s.id" class="scenario-card" :class="s.priority">
          <div class="scenario-top">
            <el-tag :type="priorityType(s.priority)" effect="plain">{{ priorityLabel(s.priority) }}</el-tag>
            <span>{{ s.costLevel }}成本 · {{ s.implementationDifficulty }}难度</span>
          </div>
          <h3>{{ s.title }}</h3>
          <div class="impact">
            <b>{{ s.estimatedStudents }}</b>
            <span>预计优先核查人次</span>
          </div>
          <p class="best-for">{{ s.bestFor }}</p>
          <p class="logic">{{ s.logic }}</p>
          <div class="scenario-result">
            <span>资源使用：{{ s.resourceUse || '—' }}</span>
            <span>测算后剩余缺口：<b>{{ s.remainingGap ?? '—' }}</b> 人次</span>
          </div>
          <div v-if="s.evidenceBasis?.length" class="basis-list">
            <div v-for="b in s.evidenceBasis" :key="b.source + b.usage" class="basis-item">
              <span>依据来源：{{ businessSource(b.source) }}</span>
              <small>{{ b.usage }}</small>
            </div>
          </div>
          <ol>
            <li v-for="a in s.actions || []" :key="a">{{ a }}</li>
          </ol>
        </article>
      </section>

      <section class="sa-card">
        <div class="sa-card-title">课程保障模拟清单</div>
        <div v-if="data.scope" class="table-scope">
          覆盖 {{ data.scope.uniqueStudents }} 名去重学生、{{ data.scope.uniqueMajors }} 个去重专业；
          课程—专业关系共 {{ data.scope.courseMajorRelations }} 专业次。
        </div>
        <el-table :data="data.courses || []" stripe>
          <el-table-column prop="courseName" label="课程" min-width="180" />
          <el-table-column prop="module" label="模块" min-width="130" />
          <el-table-column prop="failedStudents" label="明确未通过" width="110" align="right" />
          <el-table-column prop="verificationStudents" label="到期缺证据" width="110" align="right" />
          <el-table-column prop="majorCount" label="专业数" width="80" align="right" />
          <el-table-column label="供给/团队" width="150">
            <template #default="{ row }">
              {{ row.lessonCount }} 班 / {{ row.teacherCount }} 教师
            </template>
          </el-table-column>
          <el-table-column prop="substitutionCount" label="替代关系" width="90" align="right" />
          <el-table-column label="优先级" width="100">
            <template #default="{ row }">
              <el-tag :type="priorityType(row.priority)" size="small">{{ priorityLabel(row.priority) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="瓶颈判断" min-width="220">
            <template #default="{ row }">
              <el-tag v-for="b in row.bottlenecks || []" :key="b" size="small" class="tag" type="warning" effect="plain">
                {{ b }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="sa-card trace-card">
        <div class="sa-card-title">AI模拟追溯</div>
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
        <div class="sa-card-title">落地动作与边界</div>
        <div class="two-cols">
          <ol>
            <li v-for="a in data.nextActions || []" :key="a">{{ a }}</li>
          </ol>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="模拟边界"
            :description="(data.limitations || []).join('；')"
          />
        </div>
      </section>
    </el-skeleton>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { getGraduationCourseSupportSimulation } from '@/utils/ai'

const loading = ref(false)
const data = reactive<any>({})
const params = reactive({
  addedClasses: 3,
  classCapacity: 30,
  availableTeachers: 3,
  priorityFocus: 'balanced' as 'balanced' | 'failed' | 'verification',
})

const sourceLabelText = computed(() => normalizeSourceLabel(data.sourceLabel || 'AI辅助决策模拟'))
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
  student_plan_course_status: '学生培养方案课程完成证据', curriculum_plan_course: '培养方案课程要求',
  teaching_lesson: '教学任务与教学班', lesson_teacher: '教学班授课教师', agg_course_team: '课程团队结构汇总',
  student_course_substitution: '课程替代与认定关系', dim_student: '学生学籍信息',
}
function businessSource(value: any) {
  const raw = String(value || '')
  const labels = Object.entries(businessSourceMap).filter(([key]) => raw.includes(key)).map(([, label]) => label)
  return [...new Set(labels)].join('、') || raw || '当前页面业务数据'
}
function formatTime(value?: string) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 19)
}

function priorityType(priority: string) {
  if (priority === 'high') return 'danger'
  if (priority === 'medium') return 'warning'
  return 'info'
}

function priorityLabel(priority: string) {
  if (priority === 'high') return '高优先级'
  if (priority === 'medium') return '中优先级'
  return '低优先级'
}

async function load() {
  loading.value = true
  try {
    const result = await getGraduationCourseSupportSimulation({ limit: 12, ...params })
    Object.keys(data).forEach((key) => delete data[key])
    Object.assign(data, result)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sim-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.loading-alert {
  margin: 12px 0;
}

.simulation-controls { margin: 12px 0; }
.trace-overview { display:grid; grid-template-columns:1.3fr 1fr; gap:10px; margin-bottom:8px; }
.trace-overview > div { padding:10px 12px; border:1px solid #e2e8f0; border-radius:9px; background:#f8fafc; }
.trace-overview span { display:block; color:#64748b; font-size:11px; }
.trace-overview b { display:block; margin-top:4px; color:#334155; font-size:12px; line-height:1.55; }
.trace-collapse { border-top:0; }
.trace-collapse :deep(.el-collapse-item__header) { height:40px; color:#4f46e5; font-size:12px; font-weight:600; }
.control-title { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:12px; }
.control-title b { display:block; color:#1e293b; font-size:14px; }
.control-title span { display:block; margin-top:4px; color:#64748b; font-size:12px; }
.control-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.control-grid label { display:grid; gap:6px; color:#64748b; font-size:12px; }
.control-grid :deep(.el-input-number), .control-grid :deep(.el-select) { width:100%; }
.control-foot { margin-top:10px; color:#64748b; font-size:12px; }
.control-foot b { color:#4f46e5; }
.scenario-result { display:grid; gap:4px; margin:8px 0; padding:8px 10px; border-radius:8px; background:#f8fafc; color:#64748b; font-size:11px; line-height:1.5; }
.scenario-result b { color:#d97706; }
.table-scope { margin:-2px 0 10px; color:#64748b; font-size:12px; }
@media (max-width: 1100px) { .control-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  margin: 12px 0 14px;
  padding: 20px;
  border-radius: 16px;
  background: linear-gradient(135deg, #fff7ed 0%, #f8fafc 50%, #eef2ff 100%);
  border: 1px solid #fed7aa;
  box-shadow: 0 10px 28px rgba(217, 119, 6, .08);
}

.hero-label {
  color: #d97706;
  font-size: 12px;
  font-weight: 700;
}

.hero-card h3 {
  margin: 6px 0 8px;
  color: #0f172a;
  font-size: 22px;
}

.hero-card p {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.8;
}

.hero-badge {
  min-width: 130px;
  align-self: center;
  padding: 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, .75);
  text-align: center;
}

.hero-badge span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.hero-badge b {
  display: block;
  margin-top: 5px;
  color: #0f172a;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.scope-alert {
  margin-bottom: 14px;
}

.metric-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-top: 4px solid #d97706;
  border-radius: 12px;
  padding: 14px;
}

.metric-card span {
  color: #64748b;
  font-size: 12px;
}

.metric-card b {
  display: block;
  margin: 6px 0;
  color: #0f172a;
  font-size: 24px;
}

.metric-card small {
  color: #64748b;
  font-size: 12px;
  margin-left: 3px;
}

.metric-card p {
  margin: 0;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.5;
}

.metric-card > small {
  display: block;
  margin-top: 6px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.5;
}

.recommendation {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 14px;
}

.recommendation > div {
  padding: 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.recommendation span {
  display: block;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 700;
}

.recommendation b {
  display: block;
  margin: 7px 0;
  color: #1e293b;
  font-size: 17px;
}

.recommendation p,
.two-cols,
.scenario-card p,
.scenario-card ol {
  color: #475569;
  font-size: 13px;
  line-height: 1.75;
}

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 14px 0;
}

.scenario-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-top: 4px solid #94a3b8;
  border-radius: 12px;
  padding: 16px;
}

.scenario-card.high { border-top-color: #e11d48; }
.scenario-card.medium { border-top-color: #d97706; }

.scenario-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  color: #94a3b8;
  font-size: 12px;
}

.scenario-card h3 {
  margin: 10px 0;
  color: #1e293b;
  font-size: 17px;
}

.impact {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}

.impact b {
  color: #e11d48;
  font-size: 28px;
}

.impact span {
  color: #64748b;
  font-size: 12px;
}

.logic {
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;
}

.basis-list {
  display: grid;
  gap: 7px;
  margin: 10px 0;
}

.basis-item {
  padding: 9px 10px;
  border: 1px dashed #fed7aa;
  border-radius: 8px;
  background: #fffbeb;
}

.basis-item span,
.basis-item small {
  display: block;
  color: #92400e;
  font-size: 11px;
  line-height: 1.5;
}

.basis-item small {
  margin-top: 4px;
  color: #a16207;
}

.tag {
  margin: 2px;
}

.two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.trace-card {
  margin-bottom: 14px;
}

@media (max-width: 1100px) {
  .sim-head,
  .hero-card {
    display: block;
  }

  .metric-grid,
  .recommendation,
  .scenario-grid,
  .two-cols {
    grid-template-columns: 1fr;
  }
}
</style>
