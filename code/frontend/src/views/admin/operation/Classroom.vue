<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">教室资源利用率分析</h2>
        <p class="sa-page-sub">数据来源：真实楼栋利用率基线 + 固定种子模拟星期/节次分布 · 排课情景分析</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
        <el-select v-model="fRoomType" size="small" style="width:140px" clearable placeholder="全部教室类型" @change="load">
          <el-option v-for="t in roomTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="fBuilding" size="small" style="width:140px" clearable filterable placeholder="全部楼栋" @change="load">
          <el-option v-for="b in buildings" :key="b" :label="b" :value="b" />
        </el-select>
        <el-select v-model="fSemester" size="small" style="width:180px" @change="load">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </div>
    </div>

    <div class="sa-kpi-row">
      <KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :sub="k.sub" :hint="k.formula" :tone="kpiTone(k.label)" />
    </div>

    <el-alert type="success" :closable="false" show-icon style="margin-bottom:12px"
      title="V2 教室资源可用基数"
      :description="`现有房间 ${v2Rooms.summary.total_rooms || 0} 间；按“可用、非虚拟、座位数大于0”口径，可用于利用率分母的教室 ${v2Rooms.summary.usable_rooms || 0} 间。可用数量由上游主数据提供，本系统只消费和分析。`" />
    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">分楼宇可用教室基数 <span class="extra">V2真实房间与楼宇主数据</span></div>
      <el-table :data="v2Rooms.buildings" size="small" stripe max-height="300">
        <el-table-column prop="building" label="教学楼" min-width="180" />
        <el-table-column prop="total_rooms" label="房间总数" width="110" align="right" />
        <el-table-column prop="usable_rooms" label="可用教室数" width="120" align="right" />
        <el-table-column prop="usable_seats" label="可用座位数" width="120" align="right" />
      </el-table>
    </div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="14">
        <div class="sa-card">
          <div class="sa-card-title">
            利用率热力图
            <span class="extra">颜色越深利用率越高</span>
          </div>
          <EChart v-if="hasHeatmap" :option="heatOption" :height="260" />
          <div v-else class="sa-faint" style="font-size:12px">暂无热力图数据</div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">分教学楼利用率 <KpiLabel label="" formula="该教学楼已占用教室时段÷可用时段×100%" /></div>
          <EChart v-if="data.buildings.length" :option="buildingOption" :height="Math.max(140, data.buildings.length*26)" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
        </div>
        <div class="sa-card">
          <div class="sa-card-title">分类型利用率 <KpiLabel label="" formula="按教室类型(普通/多媒体/实验室/体育)统计" /></div>
          <EChart v-if="data.types.length" :option="typeOption" :height="Math.max(120, data.types.length*30)" />
          <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
        </div>
      </el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title" style="display:flex;justify-content:space-between">
        <span>时段余量情景分析 <span class="extra">用于方案比较，不代表真实空闲</span></span>
        <div style="display:flex;gap:8px">
          <el-select v-model="fDay" size="small" clearable placeholder="全部星期" style="width:110px" @change="loadCapacity">
            <el-option v-for="(d,i) in days" :key="d" :label="d" :value="i+1" />
          </el-select>
          <el-select v-model="fPeriod" size="small" clearable placeholder="全部节次" style="width:110px" @change="loadCapacity">
            <el-option v-for="p in periods" :key="p.key" :label="p.label" :value="p.key" />
          </el-select>
          <el-button size="small" type="primary" :disabled="!fBuilding||!fDay||!fPeriod" @click="loadCandidates">生成调度候选</el-button>
        </div>
      </div>
      <el-alert type="info" :closable="false" :title="capacity.dataLimitation" style="margin-bottom:10px" />
      <div class="sa-faint" style="font-size:12px;margin-bottom:8px">平均余量 {{ capacity.summary.avgRemainingPct }}% · 余量充足时段 {{ capacity.summary.availableCount }}/{{ capacity.summary.slotCount }}</div>
      <el-table :data="capacity.slots" size="small" stripe max-height="360">
        <el-table-column prop="building" label="教学楼" min-width="130" />
        <el-table-column prop="roomType" label="类型" width="110" />
        <el-table-column prop="dayLabel" label="星期" width="80" />
        <el-table-column prop="periodLabel" label="节次" width="90" />
        <el-table-column label="已用/余量" min-width="180"><template #default="{row}"><el-progress :percentage="row.usedPct" :stroke-width="8" /><span class="sa-faint">余量 {{ row.remainingPct }}%</span></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{row}"><el-tag size="small" :type="row.status==='余量充足'?'success':row.status==='可协调'?'warning':'danger'">{{ row.status }}</el-tag></template></el-table-column>
      </el-table>
      <template v-if="candidateLoaded">
        <el-alert type="warning" :closable="false" :title="candidates.warning" style="margin:14px 0 10px" />
        <div class="sa-card-title">课程调度情景候选 <span class="extra">仅情景模拟，按模拟余量和班额排序</span></div>
        <el-table :data="candidates.candidates" size="small" stripe max-height="400">
          <el-table-column prop="courseId" label="课程代码" width="130" />
          <el-table-column prop="courseName" label="课程名称" min-width="180" />
          <el-table-column prop="dept" label="开课单位" min-width="150" />
          <el-table-column prop="avgEnrolled" label="平均班额" width="90" align="right" />
          <el-table-column prop="priorityScore" label="筛选分" width="80" align="right" />
          <el-table-column label="结论" width="100"><template #default="{row}"><el-tag type="warning" size="small">{{ row.readiness }}</el-tag></template></el-table-column>
          <el-table-column label="待核验约束" min-width="220"><template #default="{row}">{{ row.unverifiedConstraints.join('、') }}</template></el-table-column>
        </el-table>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { reactive, ref, computed, onMounted } from 'vue'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'

const days = ['周一', '周二', '周三', '周四', '周五']
const periods = [
  { label: '1-2节', key: 1 }, { label: '3-4节', key: 2 },
  { label: '5-6节', key: 3 }, { label: '7-8节', key: 4 },
]
const fSemester = ref('')
const fRoomType = ref('')
const fBuilding = ref('')
const fDay = ref<number|''>('')
const fPeriod = ref<number|''>('')
const semesters = ref<SemesterOpt[]>([])
const roomTypes = ref<string[]>([])
const buildings = ref<string[]>([])

const kpis = ref<any[]>([])
const data = reactive<{heatmap:Record<string,Record<string,number>>;buildings:any[];types:any[]}>({
  heatmap: {}, buildings: [], types: [],
})
const capacity = reactive<any>({slots:[],summary:{slotCount:0,avgRemainingPct:0,availableCount:0},dataLimitation:''})
const candidates = reactive<any>({candidates:[],warning:''})
const candidateLoaded = ref(false)
const v2Rooms = reactive<any>({ summary: {}, buildings: [], denominator: '' })

async function loadCandidates() {
  if (!fBuilding.value || !fDay.value || !fPeriod.value) return
  const params = new URLSearchParams({semester:fSemester.value,building:fBuilding.value,day:String(fDay.value),period:String(fPeriod.value)})
  const d = await http.get('/admin/operation/reschedule-candidates?' + params.toString())
  Object.assign(candidates, d || {candidates:[]}); candidateLoaded.value = true
}

async function loadCapacity() {
  candidateLoaded.value = false
  const params = new URLSearchParams()
  if (fSemester.value) params.set('semester', fSemester.value)
  if (fBuilding.value) params.set('building', fBuilding.value)
  if (fDay.value) params.set('day', String(fDay.value))
  if (fPeriod.value) params.set('period', String(fPeriod.value))
  const d = await http.get('/admin/operation/capacity-slots?' + params.toString())
  Object.assign(capacity, d || {slots:[],summary:{}})
}

async function load() {
  const params = new URLSearchParams()
  if (fSemester.value) params.set('semester', fSemester.value)
  if (fRoomType.value) params.set('room_type', fRoomType.value)
  if (fBuilding.value) params.set('building', fBuilding.value)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const d = await http.get('/admin/operation/classroom' + qs)
  // 切学期可能命中空数据，重置以避免残留上一次结果
  data.heatmap = {}; data.buildings = []; data.types = []
  if (d) { kpis.value = d.kpis || []; Object.assign(data, d) }
  await loadCapacity()
}
onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = meta.semesters.slice().reverse()
  roomTypes.value = meta.roomTypes || []
  buildings.value = meta.buildings || []
  fSemester.value = meta.current
  const roomSummary = await http.get<any>('/v2/rooms/summary')
  if (roomSummary) Object.assign(v2Rooms, roomSummary)
  await load()
})

function kpiTone(label: string): 'primary'|'teal'|'danger'|'amber' {
  if (label.includes('高峰')) return 'danger'
  if (label.includes('教学楼数')) return 'teal'
  return 'primary'
}

const hasHeatmap = computed(() => Object.keys(data.heatmap || {}).length > 0)

const heatOption = computed(() => {
  const cells: any[] = []
  let maxV = 100
  days.forEach((d, x) => {
    periods.forEach((p, y) => {
      const v = data.heatmap?.[d]?.[p.key]
      if (v !== undefined && v !== null) { cells.push([x, y, v]); maxV = Math.max(maxV, v) }
    })
  })
  return {
    grid: { left: 60, right: 16, top: 10, bottom: 50, containLabel: false },
    tooltip: { position: 'top', formatter: (p: any) => `${days[p.value[0]]} ${periods[p.value[1]].label}：${p.value[2]}%` },
    xAxis: { type: 'category', data: days, axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false }, splitArea: { show: true } },
    yAxis: { type: 'category', data: periods.map(p => p.label), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false }, splitArea: { show: true } },
    visualMap: { min: 0, max: maxV, calculable: true, orient: 'horizontal', left: 'center', bottom: 4, itemHeight: 80, textStyle: { color: '#64748B', fontSize: 11 }, inRange: { color: ['#ecfdf5', '#fef3c7', '#fecaca', '#E11D48'] } },
    series: [{
      type: 'heatmap', data: cells,
      label: { show: true, formatter: (p: any) => p.value[2] + '%', color: '#334155', fontSize: 11 },
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.2)' } },
    }],
  }
})

function utilColor(p: number) { return p > 85 ? '#E11D48' : p > 60 ? '#D97706' : '#0D9488' }

const buildingOption = computed(() => {
  const b = [...(data.buildings || [])].reverse()
  return {
    grid: { left: 6, right: 30, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}：{c}%' },
    xAxis: { type: 'value', max: 100, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: b.map((x: any) => x.name), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '56%', itemStyle: { borderRadius: [0, 4, 4, 0] },
      data: b.map((x: any) => ({ value: x.pct, itemStyle: { color: utilColor(x.pct) } })),
      label: { show: true, position: 'right', formatter: '{c}%', color: '#64748B', fontSize: 11 },
    }],
  }
})

const typeOption = computed(() => {
  const t = [...(data.types || [])].reverse()
  return {
    grid: { left: 6, right: 30, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}：{c}%' },
    xAxis: { type: 'value', max: 100, axisLabel: { color: '#94A3B8', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: t.map((x: any) => x.name), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [{
      type: 'bar', barWidth: '50%', itemStyle: { color: '#4F46E5', borderRadius: [0, 4, 4, 0] },
      data: t.map((x: any) => x.pct),
      label: { show: true, position: 'right', formatter: '{c}%', color: '#64748B', fontSize: 11 },
    }],
  }
})
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>
