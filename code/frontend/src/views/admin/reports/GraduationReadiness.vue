<template>
  <div>
    <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/curriculum">培养质量分析</el-breadcrumb-item><el-breadcrumb-item>毕业准备与课程保障</el-breadcrumb-item></el-breadcrumb>
    <h2 class="sa-page-title">毕业准备与课程保障</h2>
    <p class="sa-page-sub">从已确认的培养要求问题出发，形成学生核查和下一周期课程保障准备清单。</p>
    <el-alert type="info" :closable="false" show-icon title="本页是毕业准备核查工具，不是毕业或学位审核结论" :description="definition.boundary" />

    <el-skeleton :loading="initialLoading" animated :rows="4">
      <div class="kpis">
        <div v-for="x in kpis" :key="x.label" class="kpi" :class="{action:!!x.filter}" @click="useKpi(x)">
          <span>{{x.label}} <el-tooltip :content="x.help"><el-icon class="help"><InfoFilled/></el-icon></el-tooltip></span>
          <b>{{x.value}}</b><small>{{x.note}}</small>
          <el-button v-if="x.filter" link type="primary">查看学生名单 →</el-button><em v-else>范围或口径指标</em>
        </div>
      </div>
    </el-skeleton>

    <div class="grid">
      <section class="sa-card">
        <div class="sa-card-title">各专业毕业准备概览 <span class="extra">专业表不受下方学生名单筛选影响</span></div>
        <DataTable :columns="majorColumns" :data="data.majors" storage-key="curriculum:graduation-majors"
          :max-business-columns="6" :config-version="2" :pagination="true" :default-page-size="10"
          size="small" v-loading="initialLoading">
          <template #col-moduleRuleCoverageRate="{row}">{{row.module_rule_coverage_rate}}%</template>
          <template #col-action="{row}"><el-button link type="primary" @click="inspectMajor(row)">核查学生</el-button></template>
        </DataTable>
      </section>
      <section class="sa-card">
        <div class="sa-card-title">课程保障待确认清单 <span class="extra">按明确未通过影响人数排序；不直接判定供给不足</span></div>
        <DataTable :columns="courseColumns" :data="data.courses" storage-key="curriculum:graduation-courses"
          :max-business-columns="7" :config-version="2" :pagination="true" :default-page-size="10"
          size="small" v-loading="initialLoading">
          <template #col-supply_priority="{row}"><el-tag size="small" type="warning">{{row.supply_priority}}</el-tag></template>
          <template #col-supply_reasons="{row}">{{(row.supply_reasons||[]).join('；')||'按学生候选情况观察'}}</template>
          <template #col-action="{row}"><el-button link type="primary" @click="openSupply(row)">保障证据</el-button></template>
        </DataTable>
      </section>
    </div>

    <section class="sa-card student-section">
      <div class="sa-card-title">学生核查名单 <span class="extra">以下条件只作用于本名单，不改变上方专业与课程统计</span></div>
      <div class="filters">
        <el-select v-model="draftStatus" clearable placeholder="全部证据状态">
          <el-option label="高年级明确问题" value="high_grade_action"/>
          <el-option label="全部年级明确问题" value="action_required"/>
          <el-option label="数据候选（待核验）" value="verification_required"/>
          <el-option label="当前未发现到期问题" value="evidence_complete"/>
        </el-select>
        <el-button type="primary" :loading="listLoading" @click="applyFilter">应用名单条件</el-button>
        <el-button :disabled="listLoading||(!status&&!activeMajor)" @click="reset">清除全部条件</el-button>
        <span v-if="activeMajor" class="active-scope">当前专业：<el-tag closable @close="clearMajor">{{activeMajorName}}</el-tag></span>
        <span v-else class="hint">当前显示全部授权范围</span>
      </div>
      <DataTable :columns="studentColumns" :data="data.students" storage-key="curriculum:graduation-students"
        :max-business-columns="8" :config-version="2" :page-size="pageSize"
        @update:page-size="changePageSize" size="small" stripe
        v-loading="listLoading" element-loading-text="正在按名单条件提取学生证据…">
        <template #col-moduleProgress="{row}">{{row.completed_modules}} / {{row.assessable_modules}}</template>
        <template #col-evidence="{row}"><span v-if="row.explicit_required_failures">{{row.explicit_required_failures}}门明确未通过，涉及{{row.explicit_gap_modules}}个未达到模块</span><span v-else-if="row.due_required_gaps">{{row.due_required_gaps}}门缺结果候选，涉及{{row.candidate_modules}}个模块</span><span v-else>当前未发现明确问题或到期候选</span></template>
        <template #col-status="{row}"><el-tag size="small" :type="row.readiness_status==='action_required'?'danger':row.readiness_status==='verification_required'?'warning':'success'">{{statusName[row.readiness_status]}}</el-tag></template>
        <template #col-action="{row}"><el-button link type="primary" @click="student(row)">核查证据</el-button></template>
      </DataTable>
      <el-pagination v-if="data.total" v-model:current-page="page" :page-size="pageSize" :total="data.total"
        layout="total, prev, pager, next" class="pager" @current-change="loadStudents"/>
    </section>

    <el-collapse class="definition">
      <el-collapse-item title="查看指标口径、数据来源和适用边界" name="definition">
        <p><b>明确问题：</b>{{definition.action_required}}</p>
        <p><b>数据候选：</b>{{definition.verification_required}}</p>
        <p><b>模块规则可核查率：</b>{{definition.module_rule_coverage}}</p>
        <p><b>课程保障待确认：</b>{{definition.supply_priority}}</p>
        <p><b>统计单位：</b>{{definition.number_unit}}</p>
      </el-collapse-item>
    </el-collapse>

    <el-drawer v-model="studentVisible" :title="studentEvidence.student?.display_name ? `${studentEvidence.student.display_name}｜毕业准备核查证据` : '毕业准备核查证据'" size="900px">
      <div v-loading="studentDrawerLoading" element-loading-text="正在加载学生模块与课程证据…" class="drawer-body">
        <el-alert type="warning" :closable="false" title="核查边界" :description="studentEvidence.boundary"/>
        <el-descriptions class="drawer-summary" :column="4" border>
          <el-descriptions-item label="学号">{{studentEvidence.student?.student_id}}</el-descriptions-item>
          <el-descriptions-item label="年级">{{studentEvidence.student?.entry_grade}}</el-descriptions-item>
          <el-descriptions-item label="专业">{{studentEvidence.student?.major_name}}</el-descriptions-item>
          <el-descriptions-item label="培养方案">{{studentEvidence.student?.plan_name}}</el-descriptions-item>
          <el-descriptions-item label="明确未通过">{{studentEvidence.summary?.failed_courses||0}}门</el-descriptions-item>
          <el-descriptions-item label="数据候选">{{studentEvidence.summary?.candidate_courses||0}}门</el-descriptions-item>
          <el-descriptions-item label="历史开课无证据">{{studentEvidence.summary?.courses_without_offering||0}}门</el-descriptions-item>
          <el-descriptions-item label="课程替代证据">{{studentEvidence.summary?.courses_with_substitution||0}}门</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-actions"><el-button v-if="selectedStudentNeedsAi" type="primary" plain @click="openStudentAi({student_id:studentEvidence.student?.student_id})">AI归纳核查重点</el-button></div>
        <h4>明确问题课程</h4>
        <DataTable :columns="evidenceCourseColumns" :data="studentEvidence.failed_courses||[]" storage-key="curriculum:graduation-failed-evidence" :max-business-columns="6" :config-version="2" size="small"/>
        <h4>数据候选课程</h4>
        <DataTable :columns="candidateCourseColumns" :data="studentEvidence.candidate_courses||[]" storage-key="curriculum:graduation-candidate-evidence" :max-business-columns="6" :config-version="2" size="small"/>
      </div>
    </el-drawer>

    <el-drawer v-model="supplyVisible" :title="supply.course?.courseName ? `${supply.course.courseName}｜课程保障证据` : '课程保障证据'" size="860px">
      <div v-loading="supplyDrawerLoading" element-loading-text="正在加载历史开课、替代和影响学生证据…" class="drawer-body">
        <el-alert type="info" :closable="false" title="证据边界" :description="supply.boundary"/>
        <el-descriptions class="drawer-summary" :column="3" border>
          <el-descriptions-item label="明确未通过">{{supply.affected?.actionRequiredStudents||0}}人</el-descriptions-item>
          <el-descriptions-item label="数据候选">{{supply.affected?.verificationStudents||0}}人</el-descriptions-item>
          <el-descriptions-item label="涉及专业">{{supply.affected?.affectedMajors||0}}个</el-descriptions-item>
          <el-descriptions-item label="历史开课学期">{{supply.offerings?.length||0}}个</el-descriptions-item>
          <el-descriptions-item label="替代关系">{{supply.substitutions?.length||0}}条</el-descriptions-item>
          <el-descriptions-item label="下一周期计划">尚未接入</el-descriptions-item>
        </el-descriptions>
        <h4>已接入历史开课记录</h4>
        <DataTable :columns="offeringColumns" :data="supply.offerings||[]" storage-key="curriculum:graduation-supply" :max-business-columns="6" :config-version="2" size="small"/>
        <h4>受影响学生</h4>
        <DataTable :columns="supplyStudentColumns" :data="supplyStudents" storage-key="curriculum:graduation-supply-students" :max-business-columns="5" :config-version="2" size="small">
          <template #col-action="{row}"><el-button link type="primary" @click="student({student_id:row.studentId})">核查学生</el-button></template>
        </DataTable>
      </div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="毕业准备AI研判" />
  </div>
</template>

<script setup lang="ts">
import{computed,onMounted,reactive,ref}from'vue'
import{InfoFilled}from'@element-plus/icons-vue'
import{http}from'@/utils/http'
import{getGraduationStudentAIInsight}from'@/utils/ai'
import AIInsightDrawer from'@/components/AIInsightDrawer.vue'
import DataTable,{type DataTableColumn}from'@/components/DataTable.vue'

const initialLoading=ref(true),listLoading=ref(false),draftStatus=ref(''),status=ref(''),page=ref(1),pageSize=ref(50)
const supplyVisible=ref(false),studentVisible=ref(false),activeMajor=ref(''),activeMajorName=ref('')
const studentDrawerLoading=ref(false),supplyDrawerLoading=ref(false)
const aiDrawerVisible=ref(false),aiLoading=ref(false),aiInsight=ref<any>(null)
const data=reactive<any>({summary:{},majors:[],courses:[],students:[],total:0}),definition=reactive<any>({})
const supply=reactive<any>({}),studentEvidence=reactive<any>({}),supplyStudents=ref<any[]>([])
const selectedStudentNeedsAi=computed(()=>Number(studentEvidence.summary?.failed_courses||0)>0)
const statusName:any={action_required:'明确需处理',verification_required:'数据候选',evidence_complete:'当前未发现到期问题'}

const majorColumns:DataTableColumn[]=[
  {key:'major_name',label:'专业',minWidth:160,fixed:'left',required:true,region:'identity'},
  {key:'students',label:'覆盖学生',width:90,align:'right'},
  {key:'module_rule_coverage_rate',label:'模块规则可核查率',width:135,align:'right'},
  {key:'all_modules_met_students',label:'可核查模块均达到',width:130,align:'right'},
  {key:'failed_students',label:'明确问题学生',width:110,align:'right',required:true},
  {key:'verification_students',label:'数据候选学生',width:110,align:'right'},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const courseColumns:DataTableColumn[]=[
  {key:'course_name',label:'课程',minWidth:180,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'failed_students',label:'明确未通过学生',width:120,align:'right',required:true},
  {key:'verification_students',label:'数据候选学生',width:110,align:'right'},
  {key:'major_count',label:'涉及专业',width:85,align:'right'},
  {key:'lesson_count',label:'历史教学班',width:100,align:'right'},
  {key:'teacher_count',label:'历史授课教师',width:105,align:'right'},
  {key:'supply_priority',label:'保障状态',width:90},
  {key:'supply_reasons',label:'进入清单原因',minWidth:230,tooltip:true},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const studentColumns:DataTableColumn[]=[
  {key:'student_id',label:'学号',width:130,fixed:'left',required:true,region:'identity'},
  {key:'display_name',label:'姓名',width:90,fixed:'left',required:true,region:'identity'},
  {key:'major_name',label:'专业',minWidth:145},
  {key:'entry_grade',label:'年级',width:75},
  {key:'moduleProgress',label:'已达到/可核查模块',width:145},
  {key:'completed_credits',label:'已认可学分',width:100,align:'right'},
  {key:'explicit_required_failures',label:'明确未通过',width:100,align:'right'},
  {key:'due_required_gaps',label:'数据候选',width:90,align:'right'},
  {key:'evidence',label:'本行核查重点',minWidth:260,required:true,tooltip:true},
  {key:'status',label:'状态',width:120},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const evidenceCourseColumns:DataTableColumn[]=[
  {key:'course_name',label:'课程',minWidth:170,fixed:'left',required:true,region:'identity'},
  {key:'module',label:'模块',minWidth:130},{key:'module_rule',label:'模块规则',minWidth:160},
  {key:'effective_score',label:'成绩',width:70,align:'right'},{key:'last_semester',label:'最近学期',width:110},
  {key:'reason',label:'核查原因与动作',minWidth:280,required:true,tooltip:true},
]
const candidateCourseColumns:DataTableColumn[]=[
  {key:'course_name',label:'课程',minWidth:170,fixed:'left',required:true,region:'identity'},
  {key:'module',label:'模块',minWidth:130},{key:'module_rule',label:'模块规则',minWidth:160},
  {key:'suggested_term',label:'建议学期',width:90},{key:'reason',label:'核查原因与动作',minWidth:300,required:true,tooltip:true},
]
const offeringColumns:DataTableColumn[]=[
  {key:'semesterId',label:'学期',width:120,fixed:'left',required:true,region:'identity'},
  {key:'lessonCount',label:'教学班',width:85,align:'right'},{key:'teacherCount',label:'教师',width:75,align:'right'},
  {key:'capacity',label:'容量',width:80,align:'right'},{key:'enrolled',label:'已选人数',width:90,align:'right'},
  {key:'schedules',label:'排课时段',minWidth:180,tooltip:true},
]
const supplyStudentColumns:DataTableColumn[]=[
  {key:'studentId',label:'学号',width:130,fixed:'left',required:true,region:'identity'},
  {key:'name',label:'姓名',width:90,fixed:'left',required:true,region:'identity'},
  {key:'majorName',label:'专业',minWidth:150},{key:'failedRequired',label:'明确未通过',width:100,align:'right'},
  {key:'verificationRequired',label:'数据候选',width:90,align:'right'},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const kpis=computed(()=>[
  {label:'方案覆盖可核查学生',value:(data.summary.covered_students||0)+'人',note:(data.summary.plan_count||0)+'个方案',help:'年级、专业与方案绑定一致并生成模块摘要的去重学生数。'},
  {label:'高年级明确问题',value:(data.summary.high_grade_attention_students||0)+'人',note:'优先核查重修与课程保障',help:definition.high_grade_attention||'',filter:'high_grade_action'},
  {label:'全部年级明确问题',value:(data.summary.action_required_students||0)+'人',note:'模块未达到且有明确证据',help:definition.action_required||'',filter:'action_required'},
  {label:'数据候选学生',value:(data.summary.verification_students||0)+'人',note:'先核验选课、缓修与认定',help:definition.verification_required||'',filter:'verification_required'},
  {label:'模块规则可核查率',value:(data.summary.module_rule_coverage_rate||0)+'%',note:'反映当前规则数据覆盖',help:definition.module_rule_coverage||''},
])

async function loadInitial(){initialLoading.value=true;try{const r=await requestData();applyData(r,true)}finally{initialLoading.value=false}}
function requestData(){const q=new URLSearchParams({limit:String(pageSize.value),offset:String((page.value-1)*pageSize.value)});if(status.value)q.set('readiness',status.value);if(activeMajor.value)q.set('major_code',activeMajor.value);return http.get<any>('/v2/topics/graduation-readiness?'+q)}
function applyData(r:any,includeOverview=false){data.students=r.students||[];data.total=r.total||0;if(includeOverview||!data.majors.length){data.summary=r.summary||{};data.majors=r.majors||[];data.courses=r.courses||[];Object.assign(definition,r.definition||{})}}
async function loadStudents(){listLoading.value=true;try{applyData(await requestData())}finally{listLoading.value=false}}
function applyFilter(){status.value=draftStatus.value;page.value=1;loadStudents()}
function reset(){draftStatus.value='';status.value='';activeMajor.value='';activeMajorName.value='';page.value=1;loadStudents()}
function useKpi(x:any){if(!x.filter)return;draftStatus.value=x.filter;status.value=x.filter;page.value=1;loadStudents()}
function inspectMajor(row:any){activeMajor.value=row.major_code;activeMajorName.value=row.major_name;page.value=1;loadStudents()}
function clearMajor(){activeMajor.value='';activeMajorName.value='';page.value=1;loadStudents()}
function changePageSize(value:number){pageSize.value=value;page.value=1;loadStudents()}
async function student(row:any){studentVisible.value=true;studentDrawerLoading.value=true;try{Object.assign(studentEvidence,await http.get<any>('/v2/topics/graduation-readiness/student/'+encodeURIComponent(row.student_id)))}finally{studentDrawerLoading.value=false}}
async function openSupply(row:any){supplyVisible.value=true;supplyDrawerLoading.value=true;try{const id=encodeURIComponent(row.course_id);const[r,s]=await Promise.all([http.get<any>('/v2/curriculum/course-supply/'+id),http.get<any>('/v2/curriculum/management-students?course_id='+id+'&limit=100')]);Object.assign(supply,r);supplyStudents.value=s.items||[]}finally{supplyDrawerLoading.value=false}}
async function openStudentAi(row:any){const sid=row.student_id;if(!sid)return;aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getGraduationStudentAIInsight(sid)}finally{aiLoading.value=false}}
onMounted(loadInitial)
</script>

<style scoped>
.crumb{margin-bottom:8px}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:14px 0}.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}.kpi.action{cursor:pointer}.kpi span,.kpi small{display:block;color:#64748b}.kpi b{display:block;font-size:24px;margin:6px 0;color:#0f172a}.kpi em{font-size:12px;color:#94a3b8;font-style:normal}.help{display:inline-flex!important;color:#64748b}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.student-section{margin-top:14px}.filters{display:flex;gap:10px;align-items:center;margin-bottom:12px}.filters .el-select{width:220px}.hint,.active-scope{font-size:12px;color:#64748b}.definition{margin-top:14px}.definition p{font-size:13px;color:#475569;line-height:1.8}.pager{justify-content:flex-end;margin-top:12px}.drawer-body{min-height:340px}.drawer-summary{margin:14px 0}.drawer-actions{display:flex;justify-content:flex-end;margin-bottom:10px}@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style>
