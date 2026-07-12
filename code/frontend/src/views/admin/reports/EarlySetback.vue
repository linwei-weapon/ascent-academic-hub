<template>
  <div v-loading="loading">
    <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item><el-breadcrumb-item>学业风险与低年级受挫</el-breadcrumb-item></el-breadcrumb>
    <div class="head"><div><h2 class="sa-page-title">学业风险与低年级受挫</h2><p class="sa-page-sub">识别大一首次受挫及后续恢复状态，支持从群体问题下钻到学生证据。</p></div></div>
    <el-alert type="info" :closable="false" show-icon :title="definition.first_year || '口径加载中'" :description="definition.boundary" />
    <div class="filters"><el-select v-model="grade" clearable placeholder="全部入学年级" @change="load"><el-option v-for="x in grades" :key="x" :label="x+'级'" :value="x" /></el-select><el-button type="primary" @click="load">刷新专题</el-button></div>
    <div class="kpis">
      <div v-for="x in kpis" :key="x.label" class="kpi"><span>{{ x.label }}</span><b>{{ x.value }}</b><small>{{ x.note }}</small></div>
    </div>
    <div class="grid">
      <section class="sa-card"><div class="sa-card-title">年级受挫比例</div><div v-for="x in data.by_grade" :key="x.entry_grade" class="bar-row"><span>{{ x.entry_grade }}级</span><el-progress :percentage="rate(x.setback_students,x.eligible_students)" :stroke-width="12" /><em>{{ x.setback_students }}/{{ x.eligible_students }}</em></div></section>
      <section class="sa-card"><div class="sa-card-title">大一受挫集中课程 TOP10</div><el-table :data="data.courses" size="small" max-height="330"><el-table-column prop="course_name" label="课程" min-width="180" show-overflow-tooltip/><el-table-column prop="affected_students" label="学生数" width="80"/><el-table-column prop="failed_attempts" label="挂科门次" width="90"/></el-table></section>
    </div>
    <section class="sa-card"><div class="sa-card-title">专业集中度 <span class="extra">优先核查人数多且持续困难集中的专业</span></div><el-table :data="data.by_major" size="small"><el-table-column prop="major_name" label="专业" min-width="180"/><el-table-column prop="eligible_students" label="有效学生"/><el-table-column prop="setback_students" label="大一受挫"/><el-table-column prop="persistent_students" label="持续困难"/><el-table-column label="受挫比例"><template #default="{row}">{{ rate(row.setback_students,row.eligible_students) }}%</template></el-table-column></el-table></section>
    <section class="sa-card"><div class="sa-card-title">重点学生证据清单 <span class="extra">仅用于核查与关注，不自动建立处置任务</span></div><el-table :data="data.students" stripe><el-table-column prop="student_id" label="学号" width="130"/><el-table-column prop="display_name" label="姓名" width="100"/><el-table-column prop="major_name" label="专业" min-width="150"/><el-table-column prop="entry_grade" label="年级" width="75"/><el-table-column prop="first_setback_semester" label="首次受挫学期" width="130"/><el-table-column prop="first_year_failures" label="大一挂科" width="85"/><el-table-column prop="later_failures" label="后续挂科" width="85"/><el-table-column label="恢复状态" width="100"><template #default="{row}"><el-tag :type="tagType(row.recovery_status)">{{ statusName[row.recovery_status] }}</el-tag></template></el-table-column><el-table-column label="操作" width="100" fixed="right"><template #default="{row}"><el-button link type="primary" @click="student(row)">查看档案</el-button></template></el-table-column></el-table><el-pagination v-if="data.total" v-model:current-page="page" :page-size="50" :total="data.total" layout="total, prev, pager, next" @current-change="load" /></section>
    <section class="sa-card definition"><div class="sa-card-title">统计口径与管理解释</div><p><b>受挫：</b>{{ definition.setback }}</p><p><b>已恢复：</b>{{ definition.recovered }}；<b>恢复中：</b>{{ definition.recovering }}；<b>持续困难：</b>{{ definition.persistent }}；<b>待观察：</b>{{ definition.pending_observation }}</p></section>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { http } from '@/utils/http'
const router=useRouter(), loading=ref(false), grade=ref<number>(), page=ref(1)
const data=reactive<any>({summary:{},by_grade:[],by_major:[],courses:[],students:[],total:0}), definition=reactive<any>({})
const grades=computed(()=>data.by_grade.map((x:any)=>x.entry_grade))
const statusName:any={recovered:'已恢复',recovering:'恢复中',persistent:'持续困难',pending_observation:'待观察'}
const kpis=computed(()=>[{label:'有效学生',value:data.summary.eligible_students||0,note:'具有有效入学年'}, {label:'大一受挫学生',value:data.summary.setback_students||0,note:(data.summary.setback_rate||0)+'%'}, {label:'已恢复',value:data.summary.recovered_students||0,note:'后续未再挂科'}, {label:'持续困难',value:data.summary.persistent_students||0,note:'后续挂科门次增加'}, {label:'待观察',value:data.summary.pending_students||0,note:'暂无后续成绩'}])
function rate(a:number,b:number){return b?Math.round(a*1000/b)/10:0}
function tagType(s:string){return s==='persistent'?'danger':s==='recovered'?'success':s==='recovering'?'warning':'info'}
async function load(){loading.value=true;try{const q=new URLSearchParams({limit:'50',offset:String((page.value-1)*50)});if(grade.value)q.set('entry_grade',String(grade.value));const r=await http.get<any>('/v2/topics/early-setback?'+q);Object.assign(data,r);Object.assign(definition,r.definition)}finally{loading.value=false}}
function student(row:any){router.push({path:'/admin/student/'+row.student_id,query:{returnTo:'/admin/reports/early-setback',returnLabel:'低年级受挫专题'}})}
onMounted(load)
</script>
<style scoped>
.crumb{margin-bottom:8px}.head{display:flex;justify-content:space-between}.filters{display:flex;gap:10px;margin:14px 0}.filters .el-select{width:180px}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}.kpi span,.kpi small{display:block;color:#64748b}.kpi b{display:block;font-size:26px;margin:6px 0;color:#0f172a}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.sa-card{margin-bottom:14px}.bar-row{display:grid;grid-template-columns:70px 1fr 85px;gap:10px;align-items:center;margin:18px 0}.bar-row em{font-style:normal;text-align:right;color:#64748b}.definition p{font-size:13px;color:#475569;line-height:1.8}.el-pagination{justify-content:flex-end;margin-top:12px}@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style>
