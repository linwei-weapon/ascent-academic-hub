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

    <el-skeleton :loading="loading" animated :rows="8">
      <section class="hero-card">
        <div class="ai-mark">AI</div>
        <div class="hero-main">
          <div class="hero-label">{{ data.targetName || 'AI管理简报' }}</div>
          <h3>{{ data.headline }}</h3>
          <p>{{ data.summary }}</p>
          <div class="hero-meta">
            <span>{{ data.sourceLabel }}</span>
            <span>生成时间：{{ formatTime(data.generatedAt) }}</span>
            <span>成绩学期：{{ data.semester?.grade || '—' }}</span>
            <span>教学任务：{{ data.semester?.teaching || '—' }}</span>
          </div>
        </div>
      </section>

      <div class="metric-grid">
        <div v-for="m in data.metrics || []" :key="m.label" class="metric-card" :class="m.tone">
          <span>{{ m.label }}</span>
          <b>{{ m.value }}<small>{{ m.unit }}</small></b>
          <p>{{ m.hint }}</p>
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
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="go(row.route)">{{ row.action || '进入专题' }}</el-button>
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
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getManagementBriefing } from '@/utils/ai'

const router = useRouter()
const loading = ref(false)
const period = ref<'morning' | 'term'>('morning')
const data = reactive<any>({})

function formatTime(value?: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 19)
}

function go(path?: string) {
  if (path) router.push(path)
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
