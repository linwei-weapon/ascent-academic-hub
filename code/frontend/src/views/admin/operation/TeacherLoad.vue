<template>
  <div v-loading="loading && !!kpis.length" element-loading-text="正在按新条件更新教师负荷，当前结果暂时保留…">
    <div class="sa-head-row">
      <div><h2 class="sa-page-title">教师教学负荷分析</h2><p class="sa-page-sub">真实教学任务 · {{ semesterLabel }}</p></div>
      <div class="filters">
        <el-select v-model="fTitle" size="small" clearable placeholder="全部职称" style="width:130px" @change="load"><el-option v-for="t in titles" :key="t" :label="t" :value="t" /></el-select>
      </div>
    </div>
    <div v-if="collegeFilter" class="filter-banner"><span>当前学院：<b>{{ collegeFilter.name }}</b></span><el-button size="small" type="primary" text @click="clearCollegeFilter">返回全校</el-button></div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="教师负荷加载失败"
      :description="loadError" style="margin-bottom:12px"><template #default><el-button link type="primary" @click="load">重新加载</el-button></template></el-alert>
    <div v-else-if="loading && !kpis.length" class="sa-card" style="margin-bottom:12px"><el-skeleton :rows="8" animated /></div>
    <el-alert type="info" :closable="false" show-icon :title="data.workloadPolicy.statement" style="margin-bottom:12px" />
    <el-alert v-if="data.dataQuality.excludedTeachers" type="warning" :closable="false" show-icon
      :title="`已排除 ${data.dataQuality.excludedTeachers} 名教师异常记录`"
      :description="data.dataQuality.policy" style="margin-bottom:12px" />

    <div class="sa-kpi-row"><KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="tone(k.label)" /></div>
    <div class="ai-toolbar"><el-button size="small" type="primary" plain @click="openLoadAi()">生成当前负荷重点</el-button></div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12"><div class="sa-card">
        <div class="sa-card-title">职称维度教学任务 <KpiLabel label="" formula="仅统计当前学期有有效教学任务的教师；不计算在岗教师上课率" /></div>
        <DataTable :columns="titleCols" :data="data.titleLoad" storage-key="operation:teacher-load-title" size="small" height="310" :max-business-columns="5" />
      </div></el-col>
      <el-col :span="12"><div class="sa-card">
        <div class="sa-card-title">负荷核查队列 <KpiLabel label="" :formula="data.topTeacherPolicy.ranking" /></div>
        <el-alert type="info" :closable="false" :title="data.topTeacherPolicy.boundary" style="margin-bottom:8px" />
        <DataTable :columns="teacherCols" :data="data.topTeachers" storage-key="operation:teacher-load-review" size="small" height="250" :max-business-columns="3">
          <template #col-name="{row}"><span class="link" @click="openReview(row)">{{ row.name }}</span><div class="sa-faint meta">{{ row.title }} · {{ row.dept }}</div></template>
          <template #col-attention="{row}"><el-tag size="small" :type="teacherNeedsAi(row)?'danger':'warning'">{{teacherNeedsAi(row)?'AI重点':'需核查'}}</el-tag></template>
          <template #col-actions="{row}"><el-button text type="primary" size="small" @click="openReview(row)">核查</el-button></template>
        </DataTable>
      </div></el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">各学院教学负荷对比 <KpiLabel label="" formula="按实际授课教师统计中位学时、P90学时和人均课程；相对负荷按学院P90归一化，仅用于安排核查顺序" /></div>
      <DataTable :columns="deptCols" :data="data.deptLoad" storage-key="operation:teacher-load-college" size="small"
        :max-business-columns="5" @row-click="goCollege" row-class-name="row-clickable">
        <template #col-dept="{row}"><span class="link">{{ row.dept }}</span></template>
        <template #col-attention="{row,$index}"><el-tag size="small" :type="$index<3?'danger':row.loadLevel>60?'warning':'info'">{{$index<3?'优先核查':row.loadLevel>60?'需关注':'常规'}}</el-tag></template>
        <template #col-loadLevel="{row}"><el-progress :percentage="row.loadLevel" :stroke-width="10" :color="row.loadLevel>80?'#E11D48':row.loadLevel>60?'#D97706':'#0D9488'" /></template>
      </DataTable>
    </div>

    <el-drawer v-model="drawer" :title="`${selected.name || ''}｜教学负荷核查`" size="720px">
      <el-alert type="warning" :closable="false" show-icon :title="data.topTeacherPolicy.boundary" />
      <el-descriptions :column="3" border size="small" style="margin:14px 0">
        <el-descriptions-item label="总学时">{{ selected.hours || 0 }}</el-descriptions-item><el-descriptions-item label="课程数">{{ selected.courses || 0 }}</el-descriptions-item><el-descriptions-item label="教学班数">{{ selected.lessons || 0 }}</el-descriptions-item>
        <el-descriptions-item label="学生覆盖人次">{{ selected.studentVisits || 0 }}</el-descriptions-item><el-descriptions-item label="平均班额">{{ selected.avgClassSize || 0 }}</el-descriptions-item><el-descriptions-item label="当前排名">第 {{ selected.rank || '-' }} 位</el-descriptions-item>
      </el-descriptions>
      <div class="sa-card-title">课程构成证据</div>
      <el-table :data="selected.courseBreakdown || []" size="small">
        <el-table-column prop="courseName" label="课程" min-width="190" show-overflow-tooltip /><el-table-column prop="hours" label="学时" width="70" align="right" /><el-table-column prop="lessons" label="教学班" width="75" align="right" /><el-table-column prop="studentVisits" label="学生人次" width="86" align="right" /><el-table-column prop="avgClassSize" label="平均班额" width="82" align="right" />
      </el-table>
      <div class="actions"><span v-if="!teacherNeedsAi(selected)" class="sa-faint">当前不在本轮前三名 AI 重点，先核查课程构成即可。</span><el-button v-else type="primary" plain @click="openTeacherAi(selected)">查看 AI 负荷研判</el-button></div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="教师负荷AI研判" />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, reactive, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '@/utils/http'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import { COLLEGE_MAP } from '@/constants/colleges'
import { getFilterMeta } from '@/utils/meta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { getTeacherLoadAIInsight, getTeacherLoadTeacherAIInsight } from '@/utils/ai'

const route=useRoute(), router=useRouter()
const titleCols:DataTableColumn[]=[
  {key:'title',label:'职称',minWidth:100,required:true,region:'identity',fixed:'left'},
  {key:'count',label:'授课教师',width:82,align:'right',required:true},
  {key:'medianHours',label:'中位学时',width:86,align:'right',required:true},
  {key:'p90Hours',label:'P90学时',width:86,align:'right',required:true},
  {key:'avgCourses',label:'人均课程',width:86,align:'right'},
  {key:'avgClasses',label:'人均教学班',width:92,align:'right'},
  {key:'note',label:'口径说明',minWidth:135,tooltip:true},
]
const teacherCols:DataTableColumn[]=[
  {key:'rank',label:'#',width:42,align:'center',required:true,region:'identity',fixed:'left'},
  {key:'name',label:'教师',minWidth:130,required:true,region:'identity',fixed:'left'},
  {key:'hours',label:'总学时',width:68,align:'right',required:true},
  {key:'lessons',label:'教学班',width:68,align:'right'},
  {key:'attention',label:'管理关注',width:100,required:true},
  {key:'actions',label:'操作',width:78,required:true,region:'action',fixed:'right'},
]
const deptCols:DataTableColumn[]=[
  {key:'dept',label:'学院',minWidth:170,required:true,region:'identity',fixed:'left'},
  {key:'teacherCount',label:'授课教师',width:90,align:'right',required:true},
  {key:'medianHours',label:'中位学时',width:90,align:'right',required:true},
  {key:'p90Hours',label:'P90学时',width:90,align:'right',required:true},
  {key:'avgCourses',label:'人均课程',width:90,align:'right'},
  {key:'attention',label:'管理关注',width:100},
  {key:'loadLevel',label:'相对负荷水平',minWidth:220,required:true},
]
const fSemester=inject<Ref<string>>('operationSemester',ref('')), fTitle=ref(''), titles=ref<string[]>([])
const kpis=ref<any[]>([]), drawer=ref(false), selected=ref<any>({})
const loading=ref(false),loadError=ref('')
const aiDrawerVisible=ref(false), aiLoading=ref(false), aiInsight=ref<any>(null)
const collegeFilter=computed(()=>{ const id=String(route.query.college||''); return COLLEGE_MAP[id]?{id,name:COLLEGE_MAP[id]}:null })
const semesterLabel=computed(()=>fSemester.value||'未选择学期')
const data=reactive<any>({titleLoad:[],topTeachers:[],deptLoad:[],dataQuality:{excludedTeachers:0,policy:''},workloadPolicy:{statement:'尚未配置学校正式工作量办法，本页不输出达标、未达标或超负荷认定。'},topTeacherPolicy:{ranking:'按当前范围统计分布形成有限核查队列',boundary:'仅用于定位优先核查对象，不等同于超负荷认定。'}})
async function load(){loading.value=true;loadError.value='';try{const p=new URLSearchParams();if(collegeFilter.value)p.set('college',collegeFilter.value.id);if(fSemester.value)p.set('semester',fSemester.value);if(fTitle.value)p.set('title',fTitle.value);const d=await http.get('/admin/operation/teacher-load?'+p);if(d){kpis.value=d.kpis||[];Object.assign(data,d)}}catch(error:any){loadError.value=error?.message||'教师负荷数据加载失败，请稍后重试。'}finally{loading.value=false}}
function clearCollegeFilter(){router.replace({query:{}})}
function goCollege(row:any){router.push({query:{college:row.id}})}
function openReview(row:any){selected.value=row;drawer.value=true}
function teacherNeedsAi(row:any){return Number(row?.rank||999)<=3}
async function openLoadAi(row?:any){aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getTeacherLoadAIInsight({semester:fSemester.value,college:row?.id || collegeFilter.value?.id,title:fTitle.value||undefined})}finally{aiLoading.value=false}}
async function openTeacherAi(row:any){const id=row?.id||row?.teacher_id||row?.teacherId;if(!id)return;aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getTeacherLoadTeacherAIInsight(id,fSemester.value)}finally{aiLoading.value=false}}
function tone(label:string):'primary'|'teal'|'danger'|'amber'{return label.includes('排除异常')?'amber':label.includes('P90')?'amber':label.includes('有效授课')?'teal':'primary'}
watch(()=>route.query.college,load)
watch(fSemester,(value,oldValue)=>{if(oldValue&&value!==oldValue)load()})
onMounted(async()=>{const meta=await getFilterMeta();titles.value=meta.titles||[];if(!fSemester.value)fSemester.value=meta.current;await load()})
</script>

<style scoped>
.sa-head-row,.filters,.filter-banner,.actions{display:flex}.sa-head-row,.filter-banner{justify-content:space-between;align-items:center}.sa-head-row{margin-bottom:14px}.filters{gap:8px}.filter-banner{background:#eef2ff;border:1px solid #c7d2fe;border-radius:10px;padding:8px 14px;margin-bottom:12px;font-size:12px;color:var(--sa-primary)}.ai-toolbar{display:flex;justify-content:flex-end;margin:-4px 0 12px}.link{color:var(--sa-primary);cursor:pointer;font-weight:500}.link:hover{text-decoration:underline}.meta{font-size:11px;margin-top:2px}.actions{align-items:center;justify-content:flex-end;gap:8px;margin-top:16px}.actions .sa-faint{margin-right:auto}:deep(.row-clickable){cursor:pointer}:deep(.row-clickable:hover){background:#eef2ff!important}
</style>
