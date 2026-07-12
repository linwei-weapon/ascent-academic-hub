<template>
  <div>
    <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item><el-breadcrumb-item>培养方案完成与毕业准备度</el-breadcrumb-item></el-breadcrumb>
    <h2 class="sa-page-title">培养方案完成与毕业准备度</h2>
    <p class="sa-page-sub">查看必修课完成记录、明确未通过课程和已经到期但仍需核验的课程记录。</p>
    <el-alert type="warning" :closable="false" show-icon title="本页是毕业审核准备工具，不是毕业审核结论" :description="definition.boundary" />

    <div class="filters">
      <el-select v-model="draftStatus" clearable placeholder="全部学生"><el-option label="有必修课未通过" value="action_required"/><el-option label="有到期课程待核验" value="verification_required"/><el-option label="当前未发现明显缺口" value="evidence_complete"/></el-select>
      <el-button type="primary" :loading="loading" @click="applyFilter">应用筛选</el-button><el-button :disabled="loading" @click="reset">重置</el-button>
      <span class="hint">选择条件后点击“应用筛选”，页面不会自动反复刷新</span>
    </div>

    <el-skeleton :loading="initialLoading" animated :rows="4">
      <div class="kpis"><div v-for="x in kpis" :key="x.label" class="kpi"><span>{{x.label}} <el-tooltip :content="x.help"><span class="help">?</span></el-tooltip></span><b>{{x.value}}</b><small>{{x.note}}</small></div></div>
    </el-skeleton>

    <div class="grid">
      <section class="sa-card" v-loading="loading"><div class="sa-card-title">各专业必修课完成情况 <span class="extra">表中人数均为去重学生人数</span></div>
        <el-table :data="data.majors" size="small" max-height="420"><el-table-column prop="major_name" label="专业" min-width="170" show-overflow-tooltip/><el-table-column prop="students" label="覆盖学生数" width="95"/><el-table-column label="平均必修完成率" width="125"><template #default="{row}">{{row.avg_completion_rate}}%</template></el-table-column><el-table-column prop="failed_students" label="有必修课未通过学生数" width="155"/><el-table-column prop="verification_students" label="有到期课程待核验学生数" width="170"/></el-table>
      </section>
      <section class="sa-card" v-loading="loading"><div class="sa-card-title">需要优先核查的必修课程 <span class="extra">数字表示涉及该课程的去重学生数</span></div>
        <el-table :data="data.courses" size="small" max-height="420"><el-table-column prop="course_name" label="课程" min-width="180" show-overflow-tooltip/><el-table-column prop="failed_students" label="明确未通过学生数" width="135"/><el-table-column prop="verification_students" label="到期缺记录学生数" width="135"/><el-table-column prop="major_count" label="涉及专业数" width="95"/></el-table>
      </section>
    </div>

    <section class="sa-card" v-loading="loading"><div class="sa-card-title">学生核查名单 <span class="extra">分页只更新本表，不遮挡整个页面</span></div>
      <el-table :data="data.students" stripe><el-table-column prop="student_id" label="学号" width="130"/><el-table-column prop="display_name" label="姓名" width="90"/><el-table-column prop="major_name" label="专业" min-width="150"/><el-table-column prop="entry_grade" label="年级" width="70"/><el-table-column label="已完成必修/应修必修" width="155"><template #default="{row}">{{row.required_completed}} / {{row.required_courses}}</template></el-table-column><el-table-column label="必修完成率" width="145"><template #default="{row}"><el-progress :percentage="row.completion_rate" :stroke-width="8"/></template></el-table-column><el-table-column prop="explicit_required_failures" label="未通过必修课" width="105"/><el-table-column prop="due_required_gaps" label="到期待核验课程" width="115"/><el-table-column label="建议核查原因" width="150"><template #default="{row}"><el-tag :type="tagType(row.readiness_status)">{{statusName[row.readiness_status]}}</el-tag></template></el-table-column><el-table-column label="操作" width="90" fixed="right"><template #default="{row}"><el-button link type="primary" @click="student(row)">查看档案</el-button></template></el-table-column></el-table>
      <el-pagination v-if="data.total" v-model:current-page="page" :page-size="50" :total="data.total" layout="total, prev, pager, next" @current-change="load"/>
    </section>

    <section class="sa-card definition"><div class="sa-card-title">这些数字是什么意思</div><p><b>平均必修完成率：</b>{{definition.completion_rate}}</p><p><b>有必修课未通过学生数：</b>{{definition.action_required}}</p><p><b>有到期课程待核验学生数：</b>{{definition.verification_required}}</p><p><b>统计单位：</b>{{definition.number_unit}}</p></section>
  </div>
</template>
<script setup lang="ts">
import{computed,onMounted,reactive,ref}from'vue';import{useRouter}from'vue-router';import{http}from'@/utils/http'
const router=useRouter(),loading=ref(false),initialLoading=ref(true),draftStatus=ref(''),status=ref(''),page=ref(1),requestId=ref(0)
const data=reactive<any>({summary:{},majors:[],courses:[],students:[],total:0}),definition=reactive<any>({})
const statusName:any={action_required:'存在明确未通过课程',verification_required:'存在到期缺记录课程',evidence_complete:'当前未发现明显缺口'}
const kpis=computed(()=>[{label:'培养方案覆盖学生',value:(data.summary.covered_students||0)+' 人',note:(data.summary.plan_count||0)+' 个培养方案',help:'已成功关联培养方案并进入本专题统计的去重学生人数。'},{label:'平均必修完成率',value:(data.summary.avg_completion_rate||0)+'%',note:'只统计必修课',help:definition.completion_rate||'每名学生必修课完成率的平均值。'},{label:'有必修课未通过',value:(data.summary.action_required_students||0)+' 人',note:(data.summary.explicit_required_failures||0)+' 个学生-课程记录',help:definition.action_required||'至少有一门必修课明确未通过的学生人数。'},{label:'有到期课程待核验',value:(data.summary.verification_students||0)+' 人',note:(data.summary.due_required_gaps||0)+' 个学生-课程记录',help:definition.verification_required||'已经到建议修读学期但尚无完成记录的学生人数。'},{label:'当前未发现明显缺口',value:(data.summary.evidence_complete_students||0)+' 人',note:'不等同毕业审核通过',help:definition.evidence_complete||'当前数据中未发现明确未通过或到期缺记录。'}])
function tagType(s:string){return s==='action_required'?'danger':s==='verification_required'?'warning':'success'}
function applyFilter(){status.value=draftStatus.value;page.value=1;load()}function reset(){draftStatus.value='';status.value='';page.value=1;load()}
async function load(){const id=++requestId.value;loading.value=true;try{const q=new URLSearchParams({limit:'50',offset:String((page.value-1)*50)});if(status.value)q.set('readiness',status.value);const r=await http.get<any>('/v2/topics/graduation-readiness?'+q);if(id!==requestId.value)return;Object.assign(data,r);Object.assign(definition,r.definition)}finally{if(id===requestId.value){loading.value=false;initialLoading.value=false}}}
function student(row:any){router.push({path:'/admin/student/'+row.student_id,query:{returnTo:'/admin/reports/graduation-readiness',returnLabel:'培养方案与毕业准备度专题'}})}onMounted(load)
</script>
<style scoped>.crumb{margin-bottom:8px}.filters{display:flex;gap:10px;align-items:center;margin:14px 0}.filters .el-select{width:220px}.hint{font-size:12px;color:#94a3b8}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}.kpi span,.kpi small{display:block;color:#64748b}.kpi b{display:block;font-size:24px;margin:6px 0;color:#0f172a}.help{display:inline-flex!important;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#e2e8f0;color:#475569;font-size:11px;cursor:help}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.sa-card{margin-bottom:14px}.definition p{color:#475569;font-size:13px;line-height:1.8}.el-pagination{justify-content:flex-end;margin-top:12px}@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}</style>
