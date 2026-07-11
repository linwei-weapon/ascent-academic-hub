<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/reports'}">报表中心</el-breadcrumb-item>
      <el-breadcrumb-item>自定义报表</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title">自定义报表</h2>
    <p class="sa-page-sub">选择指标与维度，生成聚合报表 · 支持导出 Excel / PDF / CSV</p>

    <div class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">报表配置</div>
      <el-row :gutter="20" style="margin-top:6px">
        <el-col :span="8">
          <div class="cfg-label">选择指标 <span class="sa-faint">（可多选）</span></div>
          <el-checkbox-group v-model="form.selectedMetrics" size="small">
            <div v-for="g in metricGroups" :key="g.group" class="metric-group">
              <div class="metric-group-name">{{ g.group }}</div>
              <el-checkbox v-for="m in g.items" :key="m.id" :value="m.id" class="metric-cb">{{ m.name }}</el-checkbox>
            </div>
          </el-checkbox-group>
        </el-col>
        <el-col :span="8">
          <div class="cfg-label">选择维度</div>
          <el-radio-group v-model="form.dimension" size="small">
            <el-radio v-for="d in dimOptions" :key="d.id" :value="d.id" class="dim-radio">{{ d.name }}</el-radio>
          </el-radio-group>
          <div class="cfg-label" style="margin-top:18px">时间范围</div>
          <el-select v-model="form.semester" size="small" style="width:200px">
            <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-col>
        <el-col :span="8">
          <div class="cfg-label">导出格式</div>
          <el-radio-group v-model="form.exportFormat" size="small">
            <el-radio value="excel">Excel (.xlsx)</el-radio>
            <el-radio value="pdf">PDF</el-radio>
            <el-radio value="csv">CSV</el-radio>
          </el-radio-group>
          <div class="cfg-label" style="margin-top:18px">图表类型</div>
          <el-radio-group v-model="form.chartType" size="small">
            <el-radio value="auto">自动推荐</el-radio>
            <el-radio value="bar">柱状图</el-radio>
            <el-radio value="line">折线图</el-radio>
            <el-radio value="table">表格</el-radio>
          </el-radio-group>
        </el-col>
      </el-row>
      <div style="margin-top:18px;display:flex;justify-content:flex-end;gap:8px;align-items:center">
        <span v-if="selectedSummary" class="sa-faint" style="font-size:12px;margin-right:auto">已选：{{ selectedSummary }}</span>
        <el-button size="small" @click="exportReport">导出报表</el-button>
      </div>
    </div>

    <div class="sa-card" style="margin-top:14px">
      <div class="sa-card-title">报表预览</div>
      <el-empty :image-size="100">
        <template #description>
          <div style="font-size:13px;color:#64748B">报表聚合服务尚未接入</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            自定义指标 × 维度的实时聚合需后端聚合引擎支持，当前未接入该服务，<br />
            无法生成预览数据。已固化的常用报表请在<span class="link" @click="$router.push('/admin/reports')">报表中心</span>查看。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'

// 自定义报表的实时聚合依赖后端聚合引擎，当前无对应数据源；配置面板保留，预览/导出不构造假数据，按空态/动作占位处理。
const form = reactive({
  selectedMetrics: [] as string[], dimension: 'college', semester: '',
  exportFormat: 'excel', chartType: 'auto',
})

const semesters = ref<SemesterOpt[]>([])
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  form.semester = meta.current
})

const metricGroups = [
  { group: '学生指标', items: [
    { id: 'K001', name: '在籍学生数' }, { id: 'K002', name: '预警学生数' }, { id: 'K003', name: 'GPA均值' },
    { id: 'K004', name: '挂科率' }, { id: 'K005', name: '毕业率' }, { id: 'K006', name: '学位授予率' },
  ] },
  { group: '教学指标', items: [
    { id: 'K007', name: '开课门数' }, { id: 'K008', name: '教学班数' }, { id: 'K009', name: '平均班额' },
    { id: 'K010', name: '教室利用率' }, { id: 'K011', name: '调停课率' },
  ] },
  { group: '师资指标', items: [
    { id: 'K012', name: '专任教师数' }, { id: 'K013', name: '教授上课率' }, { id: 'K014', name: '生师比' },
    { id: 'K015', name: '博士比' },
  ] },
  { group: '实践指标', items: [
    { id: 'K016', name: '实验开出率' }, { id: 'K017', name: '毕业论文优秀率' }, { id: 'K018', name: '创新学分完成率' },
  ] },
]
const metricOptions = metricGroups.flatMap(g => g.items)
const dimOptions = [
  { id: 'college', name: '按学院' }, { id: 'major', name: '按专业' }, { id: 'grade', name: '按年级' },
  { id: 'semester', name: '按学期' }, { id: 'courseType', name: '按课程类别' },
]

const selectedSummary = computed(() => {
  const metrics = form.selectedMetrics.map(id => metricOptions.find(m => m.id === id)?.name).filter(Boolean)
  const dim = dimOptions.find(d => d.id === form.dimension)?.name
  if (!metrics.length) return ''
  return `${metrics.join('、')} · ${dim}`
})

function exportReport() {
  if (!form.selectedMetrics.length) { window.alert('请先选择至少一个指标'); return }
  window.alert(`导出自定义报表（${selectedSummary.value}）\n将在接入聚合与导出服务后实现`)
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
