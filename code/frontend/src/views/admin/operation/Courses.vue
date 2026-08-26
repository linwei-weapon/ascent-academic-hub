<template>
  <div v-loading="loading && hasResults" element-loading-text="正在按新条件更新开课供给，当前结果暂时保留…">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">开课与排课结果统计</h2>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
        <el-select v-model="fCollege" size="small" style="width:160px" clearable placeholder="全部学院">
          <el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select v-model="fCampus" size="small" style="width:120px" clearable placeholder="全部校区">
          <el-option v-for="c in campuses" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="fNature" size="small" style="width:130px" clearable placeholder="课程性质">
          <el-option v-for="n in courseNatures" :key="n" :label="n" :value="n" />
        </el-select>
        <el-select v-model="fCategory" size="small" style="width:130px" clearable placeholder="课程类别">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="fSize" size="small" style="width:140px" clearable placeholder="班额档">
          <el-option v-for="s in sizeBuckets" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button type="primary" size="small" :loading="loading" @click="applyFilters">查询</el-button>
        <el-button size="small" @click="resetFilters">重置</el-button>
      </div>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon style="margin-bottom:12px"
      title="开课供给加载失败" :description="loadError">
      <template #default><el-button link type="primary" @click="load">重新加载</el-button></template>
    </el-alert>
    <div v-else-if="loading && !hasResults" class="sa-card" style="margin-bottom:12px"><el-skeleton :rows="8" animated /></div>

    <el-alert v-if="data.dataQuality.excludedLessons" type="warning" :closable="false" show-icon style="margin-bottom:12px"
      :title="`数据质量排除：${data.dataQuality.excludedTeachers} 名异常教师、${data.dataQuality.excludedLessons} 条排课记录未计入统计`"
      :description="`${data.dataQuality.reason}（阈值>${data.dataQuality.threshold}）`" />
    <el-collapse v-if="data.dataQuality.excludedTeachers" style="margin-bottom:12px">
      <el-collapse-item :title="`查看 ${data.dataQuality.excludedTeachers} 条数据质量问题明细`" name="quality">
        <el-table v-if="qualityIssues.length" :data="qualityIssues" size="small" stripe max-height="300">
          <el-table-column prop="semester_id" label="学期" width="120" />
          <el-table-column label="教师" width="150"><template #default="{row}">{{ row.entity_name || row.entity_id }}（{{ row.entity_id }}）</template></el-table-column>
          <el-table-column prop="affected_rows" label="影响记录" width="90" align="right" />
          <el-table-column prop="detail" label="问题说明" min-width="210" />
          <el-table-column prop="recommendation" label="处置建议" min-width="250" />
        </el-table>
        <el-empty v-else description="数据质量问题明细暂未返回，请刷新页面重试" :image-size="64" />
      </el-collapse-item>
    </el-collapse>

    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">
        <span>开课保障关注 TOP10 <KpiLabel label="" formula="按大班额、单一教师多班覆盖和单班集中供给排序，不是课程质量排名" /></span>
        <el-button size="small" type="primary" plain @click="openOfferingDrawer">查看全部 {{ data.totalCourses }} 门</el-button>
      </div>
      <DataTable :columns="offeringTopCols" :data="decisionOfferings.slice(0,10)" storage-key="operation:courses-top10" size="small" stripe>
        <template #col-attention="{row}"><el-tag size="small" :type="offeringAttentionLevel(row).type">{{ offeringAttentionLevel(row).label }}</el-tag></template>
        <template #col-reasons="{row}"><span v-if="row.attention.length">{{ row.attention.join('；') }}</span><span v-else class="sa-faint">规模较大，建议常规关注</span></template>
        <template #col-actions="{row}"><el-button link type="primary" @click.stop="openOfferingReview(row)">详情</el-button></template>
      </DataTable>
    </div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="k.tone" />
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">学院教学供给规模</div>
          <DataTable :columns="deptCourseCols" :data="data.deptCourses" storage-key="operation:courses-college"
            size="small" :max-business-columns="2">
            <template #col-name="{row}"><span>{{ row.name }}</span></template>
            <template #col-courseCount="{row}">
              <div class="tnum" style="font-weight:700;font-size:14px;color:#1E293B">{{ row.courseCount }} <span style="font-size:12px;font-weight:400">门</span></div>
              <div class="sa-faint" style="font-size:11px">{{ row.lessonCount }} 个教学班</div>
            </template>
            <template #col-pct="{row}">
              <div style="display:flex;align-items:center;gap:10px">
                <el-progress :percentage="row.pct" :stroke-width="10" :color="pctColor(row.pct)" style="flex:1" />
                <span class="tnum" style="font-weight:700;font-size:13px;min-width:34px;text-align:right">{{ row.pct }}%</span>
              </div>
            </template>
          </DataTable>
          <div class="table-foot">
            <span style="width:150px">合计</span>
            <span style="width:130px;font-weight:700;color:#1E293B" class="tnum">{{ totalCourses }} 门</span>
            <span style="flex:1;font-weight:700;color:#1E293B">100%</span>
          </div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="right-stack">
          <div class="sa-card" style="margin-bottom:16px">
            <div class="sa-card-title">课程类别分布 <KpiLabel label="" formula="按课程性质统计（去重课程计数）" /></div>
            <EChart v-if="data.typeDist.length" :option="typeOption" :height="200" />
            <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          </div>
          <div class="sa-card">
            <div class="sa-card-title">班额分布 <KpiLabel label="" formula="按教学班选课人数分组：小班<30·中班30-60·大班60-120·超大班>120" /></div>
            <EChart v-if="data.sizeDist.length" :option="sizeOption" :height="180" />
            <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-drawer v-model="offeringDrawer.visible" title="全部课程开课情况" size="980px">
      <div class="drawer-toolbar">
        <el-input v-model="offeringDrawer.keyword" clearable placeholder="输入课程代码或名称" style="width:260px" @keyup.enter="searchOfferings" @clear="searchOfferings" />
        <el-button type="primary" @click="searchOfferings">查询</el-button>
        <span>共 {{ offeringDrawer.total }} 门课程 · {{ offeringDrawer.semester }}</span>
      </div>
      <DataTable :columns="offeringAllCols" :data="offeringDrawer.items" storage-key="operation:courses-all"
        size="small" stripe v-loading="offeringDrawer.loading" max-height="620" :page-size="offeringDrawer.pageSize"
        :default-page-size="20" :max-business-columns="6" @update:page-size="onOfferingPageSize">
        <template #col-avgClassSize="{row}">{{ row.lesson_count ? Math.round(row.enrolled/row.lesson_count) : 0 }}</template>
        <template #col-attention="{row}"><el-tag size="small" :type="offeringAttentionLevel(row).type">{{ offeringAttentionLevel(row).label }}</el-tag></template>
        <template #col-actions="{row}"><el-button link type="primary" @click="openOfferingReview(row)">详情</el-button></template>
      </DataTable>
      <el-pagination v-model:current-page="offeringDrawer.page" :page-size="offeringDrawer.pageSize" :total="offeringDrawer.total" layout="total,prev,pager,next" style="justify-content:flex-end;margin-top:14px" @current-change="loadOfferingPage" />
    </el-drawer>
    <el-drawer v-model="offeringReviewVisible" :title="`${selectedOffering.course_name || '课程'}｜开课保障信息`" size="720px">
      <el-descriptions :column="3" border style="margin-bottom:14px">
        <el-descriptions-item label="课程代码">{{ selectedOffering.course_id || '—' }}</el-descriptions-item>
        <el-descriptions-item label="教学班">{{ selectedOffering.lesson_count || 0 }} 个</el-descriptions-item>
        <el-descriptions-item label="授课教师">{{ selectedOffering.teacher_count || 0 }} 人</el-descriptions-item>
        <el-descriptions-item label="选课人次">{{ selectedOffering.enrolled || 0 }}</el-descriptions-item>
        <el-descriptions-item label="平均班额">{{ selectedOffering.avgClassSize || 0 }} 人</el-descriptions-item>
        <el-descriptions-item label="管理关注"><el-tag :type="offeringAttentionLevel(selectedOffering).type">{{ offeringAttentionLevel(selectedOffering).label }}</el-tag></el-descriptions-item>
      </el-descriptions>
      <div class="review-reasons">
        <b>本次关注内容</b>
        <ul v-if="selectedOffering.attention?.length"><li v-for="item in selectedOffering.attention" :key="item">{{ item }}</li></ul>
        <p v-else>当前未命中明确运行异常线索，按常规开课供给查看即可。</p>
      </div>
      <div v-if="offeringNeedsAi(selectedOffering)" class="review-actions">
        <el-button type="primary" plain @click="openOfferingAi(selectedOffering)">查看开课保障研判</el-button>
      </div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="开课保障研判" />
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, computed, watch, onMounted, inject, type Ref } from 'vue'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { getFilterMeta } from '@/utils/meta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { getOperationCourseAIInsight } from '@/utils/ai'

const fSemester = inject<Ref<string>>('operationSemester', ref(''))
const fCollege = ref('')
const fCampus = ref('')
const fNature = ref('')
const fCategory = ref('')
const fSize = ref('')
const colleges = ref<{value:string;label:string}[]>([])
const campuses = ref<string[]>([])
const courseNatures = ref<string[]>([])
const categories = ref<string[]>([])
const sizeBuckets = ref<string[]>([])

const kpis = ref<any[]>([])
const data = reactive<{deptCourses:any[];typeDist:any[];sizeDist:any[];trend:any[];totalCourses:number;focusCourses:any[];courseSummary:any;qualityIssues:any[];dataQuality:any}>({
  deptCourses: [], typeDist: [], sizeDist: [], trend: [], totalCourses: 0,
  focusCourses: [], courseSummary: {}, qualityIssues: [], dataQuality: {},
})
const qualityIssues = computed(() => data.qualityIssues || [])
const loading = ref(false)
const loadError = ref('')
const offeringDrawer = reactive<any>({ visible:false, loading:false, items:[], total:0, semester:'', keyword:'', page:1, pageSize:20 })
const offeringReviewVisible = ref(false)
const selectedOffering = ref<any>({})
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)
function offeringWithAttention(row:any) {
  const avgClassSize = row.lesson_count ? Math.round(row.enrolled / row.lesson_count) : 0
  const attention:string[] = []
  if (avgClassSize >= 120) attention.push('平均班额≥120，关注是否需要拆班')
  else if (avgClassSize >= 80) attention.push('平均班额偏大')
  if (row.teacher_count === 1 && row.lesson_count >= 3) attention.push('多班次由单一教师覆盖')
  if (row.lesson_count === 1 && row.enrolled >= 80) attention.push('单班集中供给')
  return { ...row, avgClassSize, attention }
}
function offeringNeedsAi(row:any) {
  return row?.aiPriority === true
}
function offeringAttentionLevel(row:any):{label:string;type:'danger'|'warning'|'info'} {
  const normalized = row?.attention ? row : offeringWithAttention(row || {})
  if (offeringNeedsAi(normalized)) return { label:'重点关注', type:'danger' }
  if ((normalized.attention || []).length) return { label:'需关注', type:'warning' }
  return { label:'常规', type:'info' }
}
const decisionOfferings = computed(() => (data.focusCourses || [])
  .map(offeringWithAttention)
  .map((row:any,index:number) => ({ ...row, aiPriority:index < 3 })))
const hasResults = computed(() => !!kpis.value.length || !!data.totalCourses)

// 开课保障关注 TOP10 表列定义（M6 DataTable）
const offeringTopCols: DataTableColumn[] = [
  { key: 'course_id', label: '课程代码', width: 140, region:'identity', fixed:'left' },
  { key: 'course_name', label: '课程名称', minWidth: 190, required:true, region:'identity', fixed:'left' },
  { key: 'lesson_count', label: '教学班', width: 85, align: 'right', required:true },
  { key: 'teacher_count', label: '教师数', width: 80, align: 'right' },
  { key: 'enrolled', label: '选课人次', width: 90, align: 'right', required:true },
  { key: 'avgClassSize', label: '平均班额', width: 90, align: 'right', required:true },
  { key: 'attention', label: '管理关注', width: 95, required:true },
  { key: 'reasons', label: '优先关注原因', minWidth: 250 },
  { key: 'actions', label: '操作', width: 88, required:true, region:'action', fixed:'right' },
]
const deptCourseCols:DataTableColumn[] = [
  {key:'name',label:'学院',width:150,required:true,region:'identity',fixed:'left'},
  {key:'courseCount',label:'开课门数',width:130,required:true},
  {key:'pct',label:'教学班占全校比例',minWidth:240,required:true},
]
const offeringAllCols:DataTableColumn[] = [
  {key:'course_id',label:'课程代码',width:140,region:'identity',fixed:'left'},
  {key:'course_name',label:'课程名称',minWidth:200,required:true,region:'identity',fixed:'left'},
  {key:'category',label:'类别',width:110},
  {key:'nature',label:'性质',width:110},
  {key:'lesson_count',label:'教学班',width:80,align:'right',required:true},
  {key:'teacher_count',label:'教师',width:70,align:'right'},
  {key:'enrolled',label:'选课人次',width:90,align:'right',required:true},
  {key:'avgClassSize',label:'平均班额',width:90,align:'right',required:true},
  {key:'attention',label:'管理关注',width:95,required:true},
  {key:'actions',label:'操作',width:88,required:true,region:'action',fixed:'right'},
]
function buildCourseParams() {
  const params = new URLSearchParams()
  if (fSemester.value) params.set('semester', fSemester.value)
  if (fCollege.value) params.set('college', fCollege.value)
  if (fCampus.value) params.set('campus', fCampus.value)
  if (fNature.value) params.set('course_nature', fNature.value)
  if (fCategory.value) params.set('category', fCategory.value)
  if (fSize.value) params.set('size', fSize.value)
  return params
}
async function loadOfferingPage() {
  offeringDrawer.loading = true
  try {
    const params = buildCourseParams()
    params.set('limit', String(offeringDrawer.pageSize))
    params.set('offset', String((offeringDrawer.page - 1) * offeringDrawer.pageSize))
    params.set('sort', 'scale')
    if (offeringDrawer.keyword.trim()) params.set('keyword',offeringDrawer.keyword.trim())
    const result = await http.get<any>('/admin/operation/courses/offerings?' + params.toString())
    Object.assign(offeringDrawer,{items:result?.items||[],total:result?.total||0})
  } finally { offeringDrawer.loading = false }
}
function onOfferingPageSize(value:number) {
  offeringDrawer.pageSize = value
  offeringDrawer.page = 1
  loadOfferingPage()
}
async function openOfferingDrawer() {
  offeringDrawer.visible = true; offeringDrawer.semester = fSemester.value; offeringDrawer.page = 1; offeringDrawer.keyword = ''
  await loadOfferingPage()
}
async function searchOfferings() { offeringDrawer.page = 1; await loadOfferingPage() }
function openOfferingReview(row:any) {
  selectedOffering.value = offeringWithAttention(row)
  offeringReviewVisible.value = true
}
async function openOfferingAi(row:any) {
  const courseId = row.course_id || row.courseId
  if (!courseId) return
  const semester = row.semester_id || row.semester || offeringDrawer.semester || fSemester.value
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try { aiInsight.value = await getOperationCourseAIInsight(courseId, semester) }
  finally { aiLoading.value = false }
}
const totalCourses = computed(() => data.totalCourses)
function applyFilters() { load() }
function resetFilters() {
  fCollege.value = ''
  fCampus.value = ''
  fNature.value = ''
  fCategory.value = ''
  fSize.value = ''
  load()
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
  const params = buildCourseParams()
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await http.get('/admin/operation/courses' + qs)
  if (d) { kpis.value = d.kpis || []; Object.assign(data, d) }
  } catch (error:any) {
    loadError.value = error?.message || '开课供给数据加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  const meta = await getFilterMeta()
  colleges.value = meta.colleges || []
  campuses.value = meta.campuses || []
  courseNatures.value = meta.courseNature || []
  categories.value = meta.categories || []
  sizeBuckets.value = meta.sizeBuckets || []
  if (!fSemester.value) fSemester.value = meta.current
  await load()
})
watch(fSemester, (value, oldValue) => {
  if (oldValue && value !== oldValue) load()
})

function pctColor(p: number) { return p >= 12 ? '#4F46E5' : p >= 6 ? '#6366F1' : '#0D9488' }

const TYPE_COLORS = ['#4F46E5', '#0D9488', '#D97706', '#6366F1', '#0EA5E9', '#94A3B8', '#A855F7', '#E11D48']
const typeOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 门（{d}%）' },
  legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748B', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['48%', '74%'], center: ['34%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, label: { show: false },
    data: (data.typeDist || []).map((t: any, i: number) => ({ name: t.name, value: t.count, itemStyle: { color: TYPE_COLORS[i % TYPE_COLORS.length] } })),
  }],
}))

const sizeOption = computed(() => {
  const sd = data.sizeDist || []
  return {
    grid: { left: 6, right: 16, top: 10, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any) => { const s = sd[ps[0].dataIndex]; return `${s.label}<br/>${s.count} 班 · ${s.pct}%` } },
    xAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: sd.map((s: any) => s.label), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '54%', itemStyle: { borderRadius: [0, 4, 4, 0] },
      data: sd.map((s: any) => ({ value: s.count, itemStyle: { color: s.color } })),
      label: { show: true, position: 'right', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
  }
})

</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.lvl-tag { font-size: 10px; padding: 2px 8px; border-radius: 99px; min-width: 56px; text-align: center; }
.table-foot { display: flex; align-items: center; padding: 10px 12px; background: #f8fafc; border-top: 2px solid var(--sa-border-2); font-size: 12px; color: #475569; font-weight: 600; }
.management-note { margin:10px 0 0; padding-top:10px; border-top:1px solid var(--sa-border); color:#64748B; font-size:12px; line-height:1.7; }
.drawer-toolbar { display:flex; align-items:center; gap:8px; margin-bottom:12px; }
.drawer-toolbar span { margin-left:auto; color:#64748b; font-size:12px; }
.review-reasons { padding:14px; border:1px solid #e2e8f0; border-radius:10px; background:#f8fafc; color:#475569; font-size:13px; line-height:1.8; }
.review-reasons ul { margin:8px 0 0; padding-left:20px; }
.review-reasons p { margin:8px 0 0; }
.review-actions { display:flex; align-items:center; justify-content:flex-end; margin-top:16px; }
</style>
