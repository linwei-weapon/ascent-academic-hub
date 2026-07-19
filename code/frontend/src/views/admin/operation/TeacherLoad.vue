<template>
  <div>
    <div class="sa-head-row">
      <div><h2 class="sa-page-title">教师教学负荷分析</h2><p class="sa-page-sub">真实教学任务 · {{ semesterLabel }}</p></div>
      <div class="filters">
        <el-select v-model="fTitle" size="small" clearable placeholder="全部职称" style="width:130px" @change="load"><el-option v-for="t in titles" :key="t" :label="t" :value="t" /></el-select>
        <el-select v-model="fSemester" size="small" style="width:200px" @change="load"><el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" /></el-select>
      </div>
    </div>
    <div v-if="collegeFilter" class="filter-banner"><span>当前学院：<b>{{ collegeFilter.name }}</b></span><el-button size="small" type="primary" text @click="clearCollegeFilter">返回全校</el-button></div>

    <div class="sa-kpi-row"><KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="tone(k.label)" /></div>
    <div class="ai-toolbar"><el-button size="small" type="primary" plain @click="openLoadAi()">生成当前负荷重点</el-button></div>

    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12"><div class="sa-card">
        <div class="sa-card-title">职称维度教学投入 <KpiLabel label="" formula="人数包含未授课教师；人均学时按实际授课教师计算" /></div>
        <el-table :data="data.titleLoad" size="small" height="310">
          <el-table-column prop="title" label="职称" /><el-table-column prop="count" label="人数" width="62" align="right" />
          <el-table-column prop="avgHours" label="人均学时" width="86" align="right" /><el-table-column prop="avgCourses" label="人均课程" width="86" align="right" />
          <el-table-column label="授课率" width="82" align="right"><template #default="{row}">{{ row.teachingRate }}%</template></el-table-column>
          <el-table-column label="提示" min-width="100"><template #default="{row}"><el-tag :type="row.status==='ok'?'success':'warning'" size="small">{{ row.note }}</el-tag></template></el-table-column>
        </el-table>
      </div></el-col>
      <el-col :span="12"><div class="sa-card">
        <div class="sa-card-title">高负荷核查 TOP10 <KpiLabel label="" :formula="data.topTeacherPolicy.ranking" /></div>
        <el-alert type="info" :closable="false" :title="data.topTeacherPolicy.boundary" style="margin-bottom:8px" />
        <el-table :data="data.topTeachers" size="small" height="250">
          <el-table-column prop="rank" label="#" width="42" align="center" />
          <el-table-column label="教师" min-width="130"><template #default="{row}"><span class="link" @click="openReview(row)">{{ row.name }}</span><div class="sa-faint meta">{{ row.title }} · {{ row.dept }}</div></template></el-table-column>
          <el-table-column prop="hours" label="总学时" width="68" align="right" /><el-table-column prop="lessons" label="教学班" width="68" align="right" />
          <el-table-column label="管理关注" width="100"><template #default="{row}"><el-tag size="small" :type="teacherNeedsAi(row)?'danger':'warning'">{{teacherNeedsAi(row)?'AI重点':'需核查'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="78"><template #default="{row}"><el-button text type="primary" size="small" @click="openReview(row)">核查</el-button></template></el-table-column>
        </el-table>
      </div></el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">各学院教学负荷对比 <KpiLabel label="" formula="按实际授课教师统计人均学时和人均课程；点击学院进入该学院范围" /></div>
      <el-table :data="data.deptLoad" size="small" @row-click="goCollege" row-class-name="row-clickable">
        <el-table-column prop="dept" label="学院" min-width="170"><template #default="{row}"><span class="link">{{ row.dept }}</span></template></el-table-column>
        <el-table-column prop="teacherCount" label="授课教师" width="90" align="right" /><el-table-column prop="avgHours" label="人均学时" width="90" align="right" /><el-table-column prop="avgCourses" label="人均课程" width="90" align="right" />
        <el-table-column label="管理关注" width="100"><template #default="{row,$index}"><el-tag size="small" :type="$index<3?'danger':row.loadLevel>60?'warning':'info'">{{$index<3?'优先核查':row.loadLevel>60?'需关注':'常规'}}</el-tag></template></el-table-column>
        <el-table-column label="相对负荷水平" min-width="220"><template #default="{row}"><el-progress :percentage="row.loadLevel" :stroke-width="10" :color="row.loadLevel>80?'#E11D48':row.loadLevel>60?'#D97706':'#0D9488'" /></template></el-table-column>
      </el-table>
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
      <div class="actions"><span v-if="!teacherNeedsAi(selected)" class="sa-faint">当前不在本轮前三名 AI 重点，先核查课程构成即可。</span><el-button v-else type="primary" plain @click="openTeacherAi(selected)">查看 AI 负荷研判</el-button><el-button type="primary" @click="goTeacher(selected)">查看教师完整档案</el-button></div>
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
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import { getTeacherLoadAIInsight, getTeacherLoadTeacherAIInsight } from '@/utils/ai'

const route=useRoute(), router=useRouter()
const fSemester=inject<Ref<string>>('operationSemester',ref('')), fTitle=ref(''), semesters=ref<SemesterOpt[]>([]), titles=ref<string[]>([])
const kpis=ref<any[]>([]), drawer=ref(false), selected=ref<any>({})
const aiDrawerVisible=ref(false), aiLoading=ref(false), aiInsight=ref<any>(null)
const collegeFilter=computed(()=>{ const id=String(route.query.college||''); return COLLEGE_MAP[id]?{id,name:COLLEGE_MAP[id]}:null })
const semesterLabel=computed(()=>semesters.value.find(x=>x.value===fSemester.value)?.label||'')
const data=reactive<any>({titleLoad:[],topTeachers:[],deptLoad:[],topTeacherPolicy:{ranking:'按总学时降序',boundary:'仅用于定位优先核查对象，不等同于超负荷认定。'}})
async function load(){ const p=new URLSearchParams(); if(collegeFilter.value)p.set('college',collegeFilter.value.id); if(fSemester.value)p.set('semester',fSemester.value); if(fTitle.value)p.set('title',fTitle.value); const d=await http.get('/admin/operation/teacher-load?'+p); if(d){kpis.value=d.kpis||[];Object.assign(data,d)} }
function clearCollegeFilter(){router.replace({query:{}})}
function goCollege(row:any){router.push({query:{college:row.id}})}
function openReview(row:any){selected.value=row;drawer.value=true}
function teacherNeedsAi(row:any){return Number(row?.rank||999)<=3}
function goTeacher(row:any){router.push({path:'/admin/faculty/'+row.id,query:fSemester.value?{semester:fSemester.value}:{}})}
async function openLoadAi(row?:any){aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getTeacherLoadAIInsight({semester:fSemester.value,college:row?.id || collegeFilter.value?.id,title:fTitle.value||undefined})}finally{aiLoading.value=false}}
async function openTeacherAi(row:any){const id=row?.id||row?.teacher_id||row?.teacherId;if(!id)return;aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getTeacherLoadTeacherAIInsight(id,fSemester.value)}finally{aiLoading.value=false}}
function tone(label:string):'primary'|'teal'|'danger'|'amber'{return label.includes('过载')?'amber':label.includes('授课率')?'teal':'primary'}
watch(()=>route.query.college,load)
onMounted(async()=>{const meta=await getFilterMeta();semesters.value=meta.semesters.slice().reverse();titles.value=meta.titles||[];if(!fSemester.value)fSemester.value=meta.current;await load()})
</script>

<style scoped>
.sa-head-row,.filters,.filter-banner,.actions{display:flex}.sa-head-row,.filter-banner{justify-content:space-between;align-items:center}.sa-head-row{margin-bottom:14px}.filters{gap:8px}.filter-banner{background:#eef2ff;border:1px solid #c7d2fe;border-radius:10px;padding:8px 14px;margin-bottom:12px;font-size:12px;color:var(--sa-primary)}.ai-toolbar{display:flex;justify-content:flex-end;margin:-4px 0 12px}.link{color:var(--sa-primary);cursor:pointer;font-weight:500}.link:hover{text-decoration:underline}.meta{font-size:11px;margin-top:2px}.actions{align-items:center;justify-content:flex-end;gap:8px;margin-top:16px}.actions .sa-faint{margin-right:auto}:deep(.row-clickable){cursor:pointer}:deep(.row-clickable:hover){background:#eef2ff!important}
</style>
