<template>
  <div v-loading="loading" element-loading-text="正在汇总实际教室占用记录，请稍候…" element-loading-background="rgba(248,250,252,.82)">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">实际教室占用分析</h2>
      </div>
      <div class="filters">
        <el-select v-model="fBuilding" size="small" clearable filterable placeholder="全部楼宇" style="width:160px" @change="load">
          <el-option v-for="b in buildingOptions" :key="b" :label="b" :value="b" />
        </el-select>
        <div class="evening-switch">
          <span>包含晚间</span><el-switch v-model="includeEvening" @change="load" />
        </div>
      </div>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon class="boundary"
      title="教室占用数据加载失败" :description="loadError">
      <template #default><el-button link type="primary" @click="load">重新加载</el-button></template>
    </el-alert>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :sub="k.sub" :hint="k.hint" :tone="k.tone" />
    </div>
    <div class="ai-toolbar">
      <el-button size="small" type="primary" plain @click="openClassroomAi()">生成当前资源重点</el-button>
    </div>

    <el-row :gutter="16" class="section-row">
      <el-col :span="15">
        <div class="sa-card full-height">
          <div class="sa-card-title">
            实际占用时序热力图
            <el-tooltip placement="top" effect="dark">
              <template #content>
                <div class="metric-tooltip-content">
                  <div v-for="rule in heatmapMetricRules" :key="rule">{{ rule }}</div>
                  <div class="metric-tooltip-note">{{ heatmapMetricScopeNote }}</div>
                </div>
              </template>
              <el-icon class="metric-help" tabindex="0" aria-label="查看实际占用时序热力图指标说明"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <EChart v-if="data.heatmap.length" :option="heatOption" :height="360" />
          <el-empty v-else description="当前条件下暂无实际占用记录" :image-size="72" />
        </div>
      </el-col>
      <el-col :span="9">
        <div class="sa-card full-height">
          <div class="sa-card-title">占用活动构成 <KpiLabel label="" formula="按每条实际教室占用事件分类计数；同一事件跨多个节次只计一次" /></div>
          <EChart v-if="data.activityTypes.length" :option="activityOption" :height="360" />
          <el-empty v-else description="暂无活动分类数据" :image-size="72" />
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">楼宇实际占用负荷 <KpiLabel label="" formula="楼宇负荷=已占用教室日节次÷该楼宇已观测教室数×实际采集日期数×纳入节次数" /></div>
      <div class="chart-note">优先关注占用负荷高且记录量大的楼宇；“待映射”表示源教室名称尚不能可靠归属楼宇。</div>
      <DataTable :columns="buildingCols" :data="data.buildings" storage-key="operation:classroom-buildings"
        size="small" stripe max-height="430" :max-business-columns="5">
        <template #header-occupiedRoomSlots>
          <span class="metric-header">
            占用教室日节次
            <el-tooltip placement="top" effect="dark">
              <template #content>
                <div class="metric-tooltip-content">
                  <div>{{ occupiedRoomSlotsHelp }}</div>
                  <div class="metric-tooltip-note">{{ buildingPeriodScopeNote }}</div>
                </div>
              </template>
              <el-icon class="metric-help" tabindex="0" aria-label="查看占用教室日节次指标说明"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
        </template>
        <template #header-observedLoadPct>
          <span class="metric-header">
            观测负荷
            <el-tooltip placement="top" effect="dark">
              <template #content>
                <div class="metric-tooltip-content">
                  <div>{{ buildingObservedLoadHelp }}</div>
                  <div class="metric-tooltip-note">{{ buildingObservedRoomScopeNote }}</div>
                </div>
              </template>
              <el-icon class="metric-help" tabindex="0" aria-label="查看楼宇观测负荷指标说明"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
        </template>
        <template #col-observedLoadPct="{row}"><el-progress :percentage="row.observedLoadPct" :stroke-width="9" :color="loadColor(row.observedLoadPct)" /></template>
        <template #header-attention>
          <span class="metric-header">
            管理关注
            <el-tooltip placement="top" effect="dark">
              <template #content>
                <div v-for="rule in buildingAttentionRules" :key="rule">{{ rule }}</div>
              </template>
              <el-icon class="metric-help" tabindex="0" aria-label="查看管理关注规则"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
        </template>
        <template #col-attention="{row}"><el-tag size="small" :type="buildingAttention(row).type">{{ buildingAttention(row).label }}</el-tag></template>
        <template #col-actions="{row}"><el-button link type="primary" @click="openBuildingReview(row)">详情</el-button></template>
      </DataTable>
    </div>

    <el-alert v-if="data.summary.overlapRecords || data.summary.pendingMappingRecords" class="quality" type="warning" :closable="false" show-icon
      :title="`待核查：${fmt(data.summary.overlapRecords)} 条时段重叠，${fmt(data.summary.pendingMappingRecords)} 条楼宇待映射`" />
    <el-drawer v-model="buildingDrawerVisible" :title="`${selectedBuilding.name || '楼宇'}｜实际占用信息`" size="680px">
      <el-descriptions :column="3" border style="margin:14px 0"><el-descriptions-item label="已观测教室">{{ selectedBuilding.observedRooms || 0 }}</el-descriptions-item><el-descriptions-item label="采集日期">{{ selectedBuilding.observedDates || 0 }}</el-descriptions-item><el-descriptions-item label="占用记录">{{ selectedBuilding.occupancyRecords || 0 }}</el-descriptions-item><el-descriptions-item label="占用教室日节次">{{ selectedBuilding.occupiedRoomSlots || 0 }}</el-descriptions-item><el-descriptions-item label="观测负荷">{{ selectedBuilding.observedLoadPct || 0 }}%</el-descriptions-item><el-descriptions-item label="管理关注"><el-tag :type="buildingAttention(selectedBuilding).type">{{ buildingAttention(selectedBuilding).label }}</el-tag></el-descriptions-item></el-descriptions>
      <div v-if="buildingNeedsAi(selectedBuilding)" class="review-actions"><el-button type="primary" plain @click="openClassroomAi(selectedBuilding)">查看资源研判</el-button></div>
    </el-drawer>
    <AIInsightDrawer
      v-model="aiDrawerVisible"
      :insight="aiInsight"
      :loading="aiLoading"
      title="教室资源研判"
      hide-intervention-tag
      hide-decision-meta
      hide-baseline
      hide-consequence
      hide-expected-result
      hide-no-comparison-tag
      hide-trace
      hide-evidence-help
      hide-evidence-source
      show-all-evidence
    />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, reactive, ref, watch, type Ref } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { http } from '@/utils/http'
import { getFilterMeta } from '@/utils/meta'
import EChart from '@/components/EChart.vue'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { getClassroomOccupancyAIInsight } from '@/utils/ai'

const loading = ref(false)
const loadError = ref('')
const fSemester = inject<Ref<string>>('operationSemester', ref(''))
const fBuilding = ref('')
const includeEvening = ref(true)
const buildingOptions = ref<string[]>([])
const data = reactive<any>({ summary: {}, heatmap: [], buildings: [], activityTypes: [] })
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)
const buildingDrawerVisible = ref(false)
const selectedBuilding = ref<any>({})
const weekdays: Record<number,string> = { 1:'周一', 2:'周二', 3:'周三', 4:'周四', 5:'周五', 6:'周六', 7:'周日' }
const activityLabels: Record<string,string> = {
  course:'课程教学', exam:'考试考务', self_study:'自习使用', admission_review:'招生复试',
  teaching_other:'其他教学', event:'会议活动', other:'其他占用',
}
const heatmapMetricRules = [
  '1. 观测负荷 =【当前学期所有教室星期几第几节（星期一第一节）被占用的所有去重（有可能存在某个教室同一天同一节的重复占用记录）记录】 ÷ 【当前观测教室总数 × 该星期几（当期学期所有的星期一）出现的日期数】 × 100%',
  '2. 占用教室日数 = 当前学期所有教室星期几第几节（星期一第一节）被占用的所有去重（有可能存在某个教室同一天同一节的重复占用记录）记录',
]
const heatmapMetricScopeNote = '口径说明：上述“所有教室”指当前筛选范围内已观测教室；该星期日期数按当前学期全量占用记录统计。'
const occupiedRoomSlotsHelp = '占用教室日节次 = 当前学期该教学楼所有教室所有星期所有节次被占用的所有去重（有可能存在某个教室同一天同一节的重复占用记录）记录'
const buildingPeriodScopeNote = '口径说明：上述“所有节次”指当前纳入节次；包含晚间时为第1—12节，关闭晚间时为第1—8节。'
const buildingObservedLoadHelp = '观测负荷 =【占用教室日节次】 ÷ 【当前学期该教学楼所有教室总数 × 观测日期数 × 纳入节次数】 × 100%'
const buildingObservedRoomScopeNote = '口径说明：上述“所有教室总数”指当前学期该教学楼实际出现过占用的已观测教室数。'
const buildingAttentionRules = [
  '1. 负载率 ≥45% 且记录数 ≥100：重点关注；',
  '2. 负载率 ≥30%：需关注；',
  '3. 教学楼为“待映射”：数据核验；',
  '4. 其余：常规。',
]
const buildingCols:DataTableColumn[] = [
  {key:'name',label:'楼宇',minWidth:170,required:true,region:'identity',fixed:'left'},
  {key:'observedRooms',label:'已观测教室',width:120,align:'right',required:true},
  {key:'observedDates',label:'采集日期',width:105,align:'right'},
  {key:'occupancyRecords',label:'占用记录',width:120,align:'right',required:true},
  {key:'occupiedRoomSlots',label:'占用教室日节次',width:145,align:'right'},
  {key:'observedLoadPct',label:'观测负荷',minWidth:220,required:true},
  {key:'attention',label:'管理关注',width:100},
  {key:'actions',label:'操作',width:80,required:true,region:'action',fixed:'right'},
]

function fmt(value: number) { return Number(value || 0).toLocaleString('zh-CN') }
function loadColor(value: number) { return value >= 50 ? '#DC2626' : value >= 30 ? '#D97706' : '#0D9488' }
function buildingNeedsAi(row:any) { return row?.name !== '待映射' && Number(row?.observedLoadPct || 0) >= 45 && Number(row?.occupancyRecords || 0) >= 100 }
function buildingAttention(row:any):{label:string;type:'danger'|'warning'|'info'} { if(row?.name==='待映射')return{label:'数据核验',type:'warning'};if(buildingNeedsAi(row))return{label:'重点关注',type:'danger'};if(Number(row?.observedLoadPct||0)>=30)return{label:'需关注',type:'warning'};return{label:'常规',type:'info'} }
function openBuildingReview(row:any) { selectedBuilding.value=row; buildingDrawerVisible.value=true }

const kpis = computed(() => {
  const s = data.summary || {}
  const peak = Math.max(0, ...(data.heatmap || []).map((x:any) => Number(x.observedUtilizationPct || 0)))
  return [
    { label:'实际占用记录', value:fmt(s.occupancyRecords), sub:'', hint:'每条教室占用事件计一次，不按跨越节次重复计数', tone:'primary' },
    { label:'已观测教室', value:fmt(s.observedRooms), sub:'', hint:'仅说明本批数据的观测覆盖；正式利用率分母须来自权威可用教室清单', tone:'teal' },
    { label:'最高时段负荷', value:`${peak}%`, sub:'', hint:'所有星期×节次网格中的最高观测占用比例', tone:'danger' },
    { label:'晚间占用记录', value:fmt(s.eveningRecords), sub:includeEvening.value?'已纳入当前分析':'', hint:'开始时间在18:00后或覆盖第9—12节的占用事件', tone:'amber' },
  ]
})

const heatOption = computed(() => {
  const periods = includeEvening.value ? Array.from({length:12},(_,i)=>i+1) : Array.from({length:8},(_,i)=>i+1)
  const days = [1,2,3,4,5,6,7]
  const lookup = new Map((data.heatmap || []).map((x:any) => [`${x.weekday}-${x.period}`, x]))
  const cells:any[] = []
  days.forEach((day,x) => periods.forEach((period,y) => {
    const row:any = lookup.get(`${day}-${period}`)
    cells.push([x,y,row?.observedUtilizationPct || 0,row?.occupiedRoomDays || 0])
  }))
  return {
    grid:{left:58,right:18,top:10,bottom:48},
    tooltip:{formatter:(p:any)=>`${weekdays[days[p.data[0]]]} 第${periods[p.data[1]]}节<br/>观测负荷：<b>${p.data[2]}%</b><br/>占用教室日数：${p.data[3]}`},
    xAxis:{type:'category',data:days.map(d=>weekdays[d]),splitArea:{show:true}},
    yAxis:{type:'category',inverse:true,data:periods.map(p=>`第${p}节`),splitArea:{show:true}},
    visualMap:{type:'piecewise',dimension:2,selectedMode:false,orient:'horizontal',left:'center',bottom:0,itemWidth:18,itemHeight:10,textStyle:{color:'#64748b'},
      pieces:[{lt:15,label:'低 <15%',color:'#BFDBFE'},{gte:15,lt:30,label:'中低 15—30%',color:'#86D9C6'},{gte:30,lt:45,label:'中高 30—45%',color:'#FBBF24'},{gte:45,label:'高 ≥45%',color:'#DC2626'}]},
    series:[{type:'heatmap',data:cells,label:{show:true,color:'#334155',fontWeight:600,formatter:(p:any)=>p.data[2] ? `${p.data[2]}%` : ''},itemStyle:{borderColor:'#fff',borderWidth:2}}],
  }
})

const activityOption = computed(() => ({
  tooltip:{trigger:'item',formatter:'{b}<br/>{c} 条（{d}%）'},
  legend:{bottom:0,type:'scroll'},
  series:[{type:'pie',radius:['40%','68%'],center:['50%','43%'],label:{formatter:'{b}\n{c} 条'},
    data:(data.activityTypes || []).map((x:any)=>({name:activityLabels[x.type] || x.type,value:x.records}))}],
}))

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const params = new URLSearchParams({ include_evening:String(includeEvening.value) })
    if (fSemester.value) params.set('semester', fSemester.value)
    if (fBuilding.value) params.set('building', fBuilding.value)
    const result = await http.get<any>('/admin/operation/classroom-occupancy?' + params.toString())
    Object.assign(data, result || { summary:{}, heatmap:[], buildings:[], activityTypes:[] })
    if (!fBuilding.value) buildingOptions.value = (result?.buildings || []).map((x:any)=>x.name).filter((x:string)=>x && x !== '待映射')
  } catch (error:any) {
    loadError.value = error?.message || '教室占用数据加载失败，请稍后重试。'
  } finally { loading.value = false }
}

async function openClassroomAi(row?: any) {
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getClassroomOccupancyAIInsight({
      semester: fSemester.value,
      building: row?.name || fBuilding.value || undefined,
      includeEvening: includeEvening.value,
    })
  } finally { aiLoading.value = false }
}

onMounted(async () => {
  const meta = await getFilterMeta()
  if (!fSemester.value) fSemester.value = meta.current
  await load()
})
watch(fSemester, (value, oldValue) => {
  if (oldValue && value !== oldValue) load()
})
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:14px}.filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.evening-switch{height:32px;display:flex;align-items:center;gap:8px;padding:0 10px;border:1px solid #dcdfe6;border-radius:4px;color:#475569;font-size:13px}.boundary{margin-bottom:14px}.ai-toolbar{display:flex;justify-content:flex-end;margin:-4px 0 12px}.section-row{margin-bottom:16px}.full-height{height:100%;box-sizing:border-box}.chart-note{font-size:12px;color:#64748b;margin:4px 0 8px}.quality{margin-top:14px}.review-actions{display:flex;align-items:center;justify-content:flex-end;margin-top:16px}.metric-header{display:inline-flex;align-items:center;gap:4px}.metric-help{color:#64748b;cursor:help}.metric-tooltip-content{max-width:520px;line-height:1.65}.metric-tooltip-content>div+div{margin-top:8px}.metric-tooltip-note{color:#cbd5e1}
</style>
