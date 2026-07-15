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
      <el-button type="primary" :loading="loading" @click="load">重新模拟</el-button>
    </div>

    <el-skeleton :loading="loading" animated :rows="8">
      <section class="hero-card">
        <div>
          <span class="hero-label">{{ data.sourceLabel || 'AI增强决策模拟样本' }}</span>
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
          <p>{{ m.hint }}</p>
        </div>
      </div>

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
            <span>预计优先覆盖学生/人次</span>
          </div>
          <p class="best-for">{{ s.bestFor }}</p>
          <p class="logic">{{ s.logic }}</p>
          <ol>
            <li v-for="a in s.actions || []" :key="a">{{ a }}</li>
          </ol>
        </article>
      </section>

      <section class="sa-card">
        <div class="sa-card-title">课程保障模拟清单</div>
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
import { onMounted, reactive, ref } from 'vue'
import { getGraduationCourseSupportSimulation } from '@/utils/ai'

const loading = ref(false)
const data = reactive<any>({})

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
    const result = await getGraduationCourseSupportSimulation({ limit: 12 })
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
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
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

.tag {
  margin: 2px;
}

.two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
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
