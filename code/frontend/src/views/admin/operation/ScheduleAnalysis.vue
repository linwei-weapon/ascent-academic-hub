<template>
  <div v-loading="loading && !!data.semester" element-loading-text="正在读取当前范围的排课结构…">
    <div class="head"><div><h2 class="sa-page-title">重点课程排课分析</h2><p class="sa-page-sub">基于真实课表复盘时段分布，为下一轮排课提供核查线索</p></div><el-tag type="success">{{ data.semester || '加载中' }}</el-tag></div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon
      title="排课结构加载失败" :description="loadError" style="margin-bottom:14px">
      <template #default><el-button link type="primary" @click="load">重新加载</el-button></template>
    </el-alert>
    <div v-else-if="loading && !data.semester" class="sa-card loading-card">
      <el-skeleton :rows="8" animated />
    </div>
    <el-empty v-else-if="!data.semester" description="当前工作身份没有已接入的排课结构数据" />
    <template v-else>
    <el-alert type="info" :closable="false" show-icon :title="data.definition.boundary" style="margin-bottom:14px" />
    <div class="sa-kpi-row"><KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.hint" :tone="k.tone" /></div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="15"><div class="sa-card">
        <div class="sa-card-title">全校排课时段分布 <KpiLabel label="" :formula="data.definition.meeting" /></div>
        <EChart v-if="data.cells.length" :option="heatOption(data.cells)" :height="290" />
      </div></el-col>
      <el-col :span="9"><div class="sa-card full-height">
        <div class="sa-card-title">管理核查提示</div>
        <div class="insight"><b>峰值时段</b><span>{{ peakLabel }}</span><small>峰值占比只反映集中程度，需结合教室占用判断资源压力。</small></div>
        <div class="insight"><b>晚间排课</b><span>{{ data.summary.eveningShare || 0 }}%</span><small>可结合学校作息判断是否需要迁移或保留。</small></div>
        <div class="insight"><b>重点课程</b><span>{{ focusCourseCount }} 门</span><small>体育、思政、数学和英语按临时关键词口径识别。</small></div>
      </div></el-col>
    </el-row>

    <div class="sa-card" style="margin-bottom:16px">
      <div class="sa-card-title">重点课程组排课均衡核查 <KpiLabel label="" :formula="data.definition.focus" /></div>
      <DataTable :columns="focusCols" :data="data.focusSummary" storage-key="operation:schedule-focus" size="small" :max-business-columns="6">
        <template #col-peakShare="{row}"><span :class="row.peakShare>=20?'warn':''">{{ row.peakShare }}%</span></template>
        <template #col-eveningShare="{row}">{{ row.eveningShare }}%</template>
        <template #col-actions="{row}"><el-button text type="primary" @click="openGroup(row.group)">查看课程</el-button></template>
      </DataTable>
    </div>

    <div class="sa-card">
      <div class="tabs"><div class="sa-card-title">重点课程时段热力图</div><el-radio-group v-model="activeGroup" size="small"><el-radio-button v-for="g in groups" :key="g" :label="g" /></el-radio-group></div>
      <EChart v-if="groupCells.length" :option="heatOption(groupCells)" :height="300" /><el-empty v-else description="当前口径下暂无排课片段" />
    </div>

    <el-drawer v-model="drawer" :title="`${drawerGroup}｜课程排课核查`" size="860px">
      <el-alert type="info" :closable="false" title="课程明细用于识别排课规模、晚间安排和星期集中度；不能单独判定排课不合理。" />
      <el-table :data="drawerCourses" size="small" style="margin-top:12px">
        <el-table-column prop="course_name" label="课程" min-width="190" show-overflow-tooltip /><el-table-column prop="lesson_count" label="教学班" width="75" align="right" /><el-table-column prop="meeting_count" label="排课片段" width="85" align="right" /><el-table-column prop="teacher_count" label="教师" width="65" align="right" /><el-table-column prop="student_visits" label="学生人次" width="86" align="right" /><el-table-column prop="avg_class_size" label="平均班额" width="82" align="right" /><el-table-column label="晚间片段" width="82" align="right"><template #default="{row}">{{ row.evening_meetings }}</template></el-table-column><el-table-column prop="weekday_coverage" label="覆盖星期" width="82" align="right" />
      </el-table>
    </el-drawer>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, reactive, ref, watch, type Ref } from 'vue'
import { http } from '@/utils/http'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import EChart from '@/components/EChart.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'

const groups=['体育课','思政课','数学类','英语类']; const activeGroup=ref('体育课'),drawer=ref(false),drawerGroup=ref('')
const focusCols:DataTableColumn[]=[
  {key:'group',label:'课程组',width:100,required:true,region:'identity',fixed:'left'},
  {key:'courseCount',label:'课程门数',width:90,align:'right'},
  {key:'lessonCount',label:'教学班',width:82,align:'right',required:true},
  {key:'meetingCount',label:'排课片段',width:90,align:'right'},
  {key:'studentVisits',label:'学生人次',width:95,align:'right'},
  {key:'peakSlot',label:'最集中时段',width:120,required:true},
  {key:'peakShare',label:'峰值占比',width:96,align:'right'},
  {key:'eveningShare',label:'晚间占比',width:96,align:'right'},
  {key:'actions',label:'操作',width:90,required:true,region:'action',fixed:'right'},
]
const sharedSemester=inject<Ref<string>>('operationSemester',ref(''))
const operationContext=inject<Ref<any>>('operationDataContext',ref(null))
const loading=ref(false),loadError=ref('');let requestId=0
const data=reactive<any>({semester:'',summary:{},cells:[],focus:[],focusSummary:[],focusCourses:[],definition:{meeting:'',focus:'',boundary:''}})
const kpis=computed(()=>[
  {label:'教学班总数',value:`${data.summary.lessons||0}个`,hint:'真实教学任务中的教学班数量',tone:'primary'},
  {label:'排课片段',value:`${data.summary.meetings||0}条`,hint:data.definition.meeting,tone:'teal'},
  {label:'峰值时段占比',value:`${data.summary.peakShare||0}%`,hint:data.definition.peak,tone:(data.summary.peakShare||0)>=12?'amber':'primary'},
  {label:'晚间排课占比',value:`${data.summary.eveningShare||0}%`,hint:data.definition.evening,tone:(data.summary.eveningShare||0)>15?'amber':'primary'},
])
const peakLabel=computed(()=>data.summary.peak?`周${data.summary.peak.weekday} · ${data.summary.peak.day_part}`:'—')
const focusCourseCount=computed(()=>data.focusSummary.reduce((n:number,x:any)=>n+(x.courseCount||0),0))
const groupCells=computed(()=>data.focus.filter((x:any)=>x.course_group===activeGroup.value))
const drawerCourses=computed(()=>data.focusCourses.filter((x:any)=>x.course_group===drawerGroup.value))
function openGroup(group:string){drawerGroup.value=group;drawer.value=true}
function heatOption(cells:any[]){const days=['周一','周二','周三','周四','周五','周六','周日'],parts=['上午','下午','晚上'];const points=cells.map(x=>[x.weekday-1,parts.indexOf(x.day_part),x.meeting_count]);const max=Math.max(1,...cells.map(x=>x.meeting_count));return{tooltip:{formatter:(p:any)=>`${days[p.data[0]]} ${parts[p.data[1]]}<br/>排课片段：<b>${p.data[2]}</b>`},grid:{left:58,right:25,top:10,bottom:45},xAxis:{type:'category',data:days},yAxis:{type:'category',data:parts},visualMap:{min:0,max,calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#EEF2FF','#93C5FD','#3B82F6','#1D4ED8']}},series:[{type:'heatmap',data:points,label:{show:true,formatter:(p:any)=>p.data[2]}}]}}
async function load(){
  const domain=operationContext.value?.domains?.scheduleStructure
  if(!domain)return
  const periods:string[]=domain.periods||[]
  const semester=periods.includes(sharedSemester.value)?sharedSemester.value:(domain.periodTo||'')
  if(!semester){
    Object.assign(data,{semester:'',summary:{},cells:[],focus:[],focusSummary:[],focusCourses:[]})
    return
  }
  const id=++requestId;loading.value=true;loadError.value=''
  try{
    const result=await http.get<any>(`/v2/topics/schedule-strategy?semester=${encodeURIComponent(semester)}`)
    if(id===requestId)Object.assign(data,result)
  }catch(error:any){
    if(id===requestId){
      Object.assign(data,{semester:'',summary:{},cells:[],focus:[],focusSummary:[],focusCourses:[]})
      loadError.value=error?.message||'排课结构数据加载失败，请稍后重试。'
    }
  }finally{if(id===requestId)loading.value=false}
}
watch([operationContext,sharedSemester],load,{immediate:true})
</script>

<style scoped>
.head,.tabs{display:flex;justify-content:space-between;align-items:center}.head{margin-bottom:14px}.full-height{height:100%}.insight{display:grid;grid-template-columns:1fr auto;gap:4px;padding:12px 0;border-bottom:1px solid var(--sa-border)}.insight span{font-size:18px;font-weight:700;color:#1e3a5f}.insight small{grid-column:1/3;color:#64748b;line-height:1.5}.warn{color:#d97706;font-weight:600}.tabs{margin-bottom:8px}
.loading-card{margin-bottom:14px}
</style>
