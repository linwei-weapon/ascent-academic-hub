<!-- 教学运行分析：ScheduleAnalysis 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div v-loading="loading && !!data.semester" element-loading-text="正在读取当前范围的排课结构…">
    <div class="head"><h2 class="sa-page-title">重点课程排课分析</h2></div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon
      title="排课结构加载失败" :description="loadError" style="margin-bottom:14px">
      <template #default><el-button link type="primary" @click="load">重新加载</el-button></template>
    </el-alert>
    <div v-else-if="loading && !data.semester" class="sa-card loading-card">
      <el-skeleton :rows="8" animated />
    </div>
    <el-empty v-else-if="!data.semester" description="当前工作身份没有已接入的排课结构数据" />
    <template v-else>
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
      <div class="sa-card-title">重点课程组排课均衡分布情况 <KpiLabel label="" :formula="data.definition.focus" /></div>
      <AppTable :columns="focusCols" :data="data.focusSummary" storage-key="operation:schedule-focus"  :max-business-columns="6" :show-density="true" :show-column-settings="true" :pagination="false">
        <template #col-peakShare="{row}"><span :class="row.peakShare>=20?'warn':''">{{ row.peakShare }}%</span></template>
        <template #col-eveningShare="{row}">{{ row.eveningShare }}%</template>
        <template #col-actions="{row}"><el-button text type="primary" @click="openGroup(row.group)">查看课程</el-button></template>
      </AppTable>
    </div>

    <div class="sa-card">
      <div class="tabs"><div class="sa-card-title">重点课程时段热力图</div><el-radio-group v-model="activeGroup" size="small"><el-radio-button v-for="g in groups" :key="g" :label="g" /></el-radio-group></div>
      <EChart v-if="groupCells.length" :option="heatOption(groupCells)" :height="300" /><el-empty v-else description="当前口径下暂无排课片段" />
    </div>

    <el-drawer v-model="drawer" :title="`${drawerGroup}｜课程排课情况`" size="860px">
      <AppTable :data="drawerCourses" :columns="[]" storage-key="teaching-analysis:operation:scheduleanalysis:2" :pagination="false">
        <template #columns>
        <el-table-column prop="course_name" label="课程" min-width="190" show-overflow-tooltip align="center" header-align="center"/><el-table-column prop="lesson_count" label="教学班" min-width="75" align="center" header-align="center"/><el-table-column prop="meeting_count" label="排课片段" min-width="85" align="center" header-align="center"/><el-table-column prop="teacher_count" label="教师" min-width="65" align="center" header-align="center"/><el-table-column prop="student_visits" label="学生人次" min-width="86" align="center" header-align="center"/><el-table-column prop="avg_class_size" label="平均班额" min-width="82" align="center" header-align="center"/><el-table-column label="晚间片段" min-width="82" align="center" header-align="center"><template #default="{row}">{{ row.evening_meetings }}</template></el-table-column><el-table-column prop="weekday_coverage" label="覆盖星期" min-width="82" align="center" header-align="center"/>
              </template>
      </AppTable>
    </el-drawer>
    </template>
  </div>
</template>

<script setup lang="ts">
import * as operationApi from '@/api/teachingAnalysis/operation'

import { computed, inject, reactive, ref, watch, type Ref } from 'vue'

import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import EChart from '@/components/EChart.vue'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'

const groups=['体育课','思政课','数学类','英语类']; const activeGroup=ref('体育课'),drawer=ref(false),drawerGroup=ref('')
const focusCols:AppTableColumn[]=[
  {key:'group',label:'课程组',minWidth:100,required:true,region:'identity',fixed:'left'},
  {key:'courseCount',label:'课程门数',minWidth:90,align:'center'},
  {key:'lessonCount',label:'教学班',minWidth:82,align:'center',required:true},
  {key:'meetingCount',label:'排课片段',minWidth:90,align:'center'},
  {key:'studentVisits',label:'学生人次',minWidth:95,align:'center'},
  {key:'peakSlot',label:'最集中时段',minWidth:120,required:true},
  {key:'peakShare',label:'峰值占比',minWidth:96,align:'center'},
  {key:'eveningShare',label:'晚间占比',minWidth:96,align:'center'},
  {key:'actions',label:'操作',width:90,required:true,region:'action',fixed:'right'},
]
const sharedSemester=inject<Ref<string>>('operationSemester',ref(''))
const operationContext=inject<Ref<any>>('operationDataContext',ref(null))
const loading=ref(false),loadError=ref('');let requestId=0
const data=reactive<any>({semester:'',summary:{},cells:[],focus:[],focusSummary:[],focusCourses:[],definition:{meeting:'',focus:'',boundary:''}})
const meetingTooltip = [
  '1. 排课片段：以星期为单位，一次连续节次为一个片段',
  '2. 排课片段举例：',
  '• 每周：周一 1~2节次，周三2~4节次，算2个片段',
  '• 每周：周一 1~4节次，算1个片段',
  '• 每周：周一 1~4节次，周二 1~4节次，算2个片段',
  '• 单周：周一 1~4节次，周二 1~4节次；双周：周二1~4节次，周四 1~2节次，算3个片段',
  '• 第1周：周一 1~3节次；第3周：周一 7~8节次；第10周：周一 1~3节次；第16周：周一 2~4节次；第18周：周一 2~3节次；算3个片段',
].join('\n')
const kpis=computed(()=>[
  {label:'教学班总数',value:`${data.summary.lessons||0}个`,hint:'真实教学任务中的教学班数量',tone:'primary'},
  {label:'排课片段',value:`${data.summary.meetings||0}条`,hint:meetingTooltip,tone:'teal'},
  {label:'峰值时段占比',value:`${data.summary.peakShare||0}%`,hint:data.definition.peak,tone:(data.summary.peakShare||0)>=12?'amber':'primary'},
  {label:'晚间排课占比',value:`${data.summary.eveningShare||0}%`,hint:data.definition.evening,tone:(data.summary.eveningShare||0)>15?'amber':'primary'},
])
const peakLabel=computed(()=>data.summary.peak?`周${data.summary.peak.weekday} · ${data.summary.peak.day_part}`:'—')
const focusCourseCount=computed(()=>data.focusSummary.reduce((n:number,x:any)=>n+(x.courseCount||0),0))
const groupCells=computed(()=>data.focus.filter((x:any)=>x.course_group===activeGroup.value))
const drawerCourses=computed(()=>data.focusCourses.filter((x:any)=>x.course_group===drawerGroup.value))
function openGroup(group:string){drawerGroup.value=group;drawer.value=true}
function heatOption(cells:any[]){const days=['周一','周二','周三','周四','周五','周六','周日'],parts=['上午','下午','晚上'];const points=cells.map(x=>[x.weekday-1,parts.indexOf(x.day_part),x.meeting_count]);const max=Math.max(1,...cells.map(x=>x.meeting_count));return{tooltip:{formatter:(p:any)=>`${days[p.data[0]]} ${parts[p.data[1]]}<br/>排课片段：<b>${p.data[2]}</b>`},grid:{left:58,right:25,top:10,bottom:45},xAxis:{type:'category',data:days},yAxis:{type:'category',data:parts,inverse:true},visualMap:{min:0,max,calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#EEF2FF','#93C5FD','#3B82F6','#1D4ED8']}},series:[{type:'heatmap',data:points,label:{show:true,formatter:(p:any)=>p.data[2]}}]}}
// 按当前页面上下文读取数据，沿用原加载状态和异常处理。
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
    const result=await operationApi.getScheduleStrategy<any>(semester)
    if(id===requestId)Object.assign(data,result)
  }catch(error:any){
    if(id===requestId){
      Object.assign(data,{semester:'',summary:{},cells:[],focus:[],focusSummary:[],focusCourses:[]})
      loadError.value=error?.message||'排课结构数据加载失败，请稍后重试。'
    }
  }finally{if(id===requestId)loading.value=false}
}
// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
watch([operationContext,sharedSemester],load,{immediate:true})
</script>

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.head,.tabs {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.head {
  margin-bottom: 14px;
}

.full-height {
  height: 100%;
}

.insight {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px;
  padding: 12px 0;
  border-bottom: 1px solid var(--sa-border);
  span {
    font-size: 18px;
    font-weight: 700;
    color: #1e3a5f;
  }
  small {
    grid-column: 1/3;
    color: #64748b;
    line-height: 1.5;
  }
}

.warn {
  color: #d97706;
  font-weight: 600;
}

.tabs {
  margin-bottom: 8px;
}

.loading-card {
  margin-bottom: 14px;
}
</style>
