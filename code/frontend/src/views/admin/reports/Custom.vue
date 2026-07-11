<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/reports'}">报表中心</el-breadcrumb-item>
      <el-breadcrumb-item>自定义报表</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title">自定义报表</h2>
    <p class="sa-page-sub">基于真实学生、成绩与预警数据进行受控聚合</p>

    <el-alert title="仅开放已有可靠数据口径的指标；不可用指标不会用模拟值代替" type="info" :closable="false" show-icon style="margin-top:14px" />

    <div class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">报表配置</div>
      <el-row :gutter="20" style="margin-top:6px">
        <el-col :span="12">
          <div class="cfg-label">选择指标 <span class="sa-faint">（可多选）</span></div>
          <el-checkbox-group v-model="form.selectedMetrics" size="small">
            <div v-for="g in metricGroups" :key="g.group" class="metric-group">
              <div class="metric-group-name">{{ g.group }}</div>
              <el-checkbox v-for="m in g.items" :key="m.id" :value="m.id" class="metric-cb">{{ m.name }}</el-checkbox>
            </div>
          </el-checkbox-group>
        </el-col>
        <el-col :span="12">
          <div class="cfg-label">选择维度</div>
          <el-radio-group v-model="form.dimension" size="small">
            <el-radio v-for="d in dimOptions" :key="d.id" :value="d.id" class="dim-radio">{{ d.name }}</el-radio>
          </el-radio-group>
          <div class="cfg-label" style="margin-top:18px">时间范围</div>
          <el-select v-model="form.semester" size="small" style="width:200px">
            <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-col>
      </el-row>
      <div class="cfg-label" style="margin-top:10px">暂不可用指标</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <el-tag v-for="m in unavailableMetrics" :key="m" type="info" effect="plain" size="small">{{ m }}</el-tag>
      </div>
      <div style="margin-top:18px;display:flex;justify-content:flex-end;gap:8px;align-items:center">
        <span v-if="selectedSummary" class="sa-faint" style="font-size:12px;margin-right:auto">已选：{{ selectedSummary }}</span>
        <el-button size="small" type="primary" :loading="loading" :disabled="!form.selectedMetrics.length" @click="generateReport">生成报表</el-button>
      </div>
    </div>

    <div class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">报表预览</div>
      <div v-if="rows.length" style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:10px">
        <el-button size="small" @click="exportReport('csv')">导出 CSV</el-button>
        <el-button size="small" @click="exportReport('pdf')">打印/另存为 PDF</el-button>
      </div>
      <el-table v-if="rows.length" :data="rows" size="small" border>
        <el-table-column v-for="col in columns" :key="col.prop" :prop="col.prop" :label="col.label" min-width="120" />
      </el-table>
      <el-empty v-else :image-size="100">
        <template #description>
          <div style="font-size:13px;color:#64748B">选择指标后生成报表</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            当前支持在籍学生数、预警学生数、GPA 均值与挂科率，<br />
            更多固定口径请在<span class="link" @click="$router.push('/admin/reports')">报表中心</span>查看。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { http } from '@/utils/http'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import { exportCsv, printReport, type ExportCol } from '@/utils/export'

const form = reactive({
  selectedMetrics: [] as string[], dimension: 'college', semester: '',
})
const loading = ref(false)
const rows = ref<any[]>([])
const columns = ref<{ prop: string; label: string }[]>([])

const semesters = ref<SemesterOpt[]>([])
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  form.semester = meta.current
})

const metricGroups = [
  { group: '学生指标', items: [
    { id: 'K001', name: '在籍学生数' }, { id: 'K002', name: '预警学生数' }, { id: 'K003', name: 'GPA均值' },
    { id: 'K004', name: '挂科率' },
  ] },
]
const unavailableMetrics = ['毕业率', '学位授予率', '开课门数', '教学班数', '平均班额', '教室利用率', '调停课率', '专任教师数', '教授上课率', '生师比', '博士比', '实验开出率', '毕业论文优秀率', '创新学分完成率']
const metricOptions = metricGroups.flatMap(g => g.items)
const dimOptions = [
  { id: 'college', name: '按学院' }, { id: 'major', name: '按专业' }, { id: 'grade', name: '按年级' },
]

const selectedSummary = computed(() => {
  const metrics = form.selectedMetrics.map(id => metricOptions.find(m => m.id === id)?.name).filter(Boolean)
  const dim = dimOptions.find(d => d.id === form.dimension)?.name
  if (!metrics.length) return ''
  return `${metrics.join('、')} · ${dim}`
})

async function generateReport() {
  if (!form.selectedMetrics.length) return
  loading.value = true
  try {
    const qs = new URLSearchParams({
      metrics: form.selectedMetrics.join(','), dimension: form.dimension,
    })
    if (form.semester) qs.set('semester', form.semester)
    const data: any = await http.get('/admin/reports/custom?' + qs.toString())
    rows.value = data?.rows || []
    columns.value = data?.columns || []
  } finally {
    loading.value = false
  }
}

function exportReport(format: string) {
  if (!rows.value.length) return
  if (format === 'pdf') { printReport(); return }
  exportCsv('自定义报表', columns.value as ExportCol[], rows.value)
}

</script>

<style scoped>
.cfg-label { font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 8px; }
.metric-group { margin-bottom: 10px; }
.metric-group-name { font-size: 11px; color: #94A3B8; margin-bottom: 3px; }
.metric-cb { display: block; margin-bottom: 2px; }
.dim-radio { display: block; margin-bottom: 6px; }
.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
</style>
