<template>
  <div>
    <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/curriculum">培养质量分析</el-breadcrumb-item><el-breadcrumb-item>毕业准备与课程保障</el-breadcrumb-item></el-breadcrumb>
    <h2 class="sa-page-title">毕业准备与课程保障</h2>
    <p class="sa-page-sub">从已确认的培养要求问题出发，形成学生核查和下一周期课程保障准备清单。</p>

    <div class="global-filters">
      <el-select v-model="draftGlobal.grades" multiple collapse-tags collapse-tags-tooltip placeholder="年级" clearable @change="onGradesChanged">
        <el-option v-for="x in filterOptions.grades" :key="x" :label="`${x}级`" :value="x" />
      </el-select>
      <el-select v-model="draftGlobal.organizationId" placeholder="学院" clearable filterable @change="onCollegeChanged">
        <el-option v-for="x in filterOptions.colleges" :key="x.value" :label="x.label" :value="x.value" />
      </el-select>
      <el-select v-model="draftGlobal.majorCode" placeholder="专业" clearable filterable @change="onMajorChanged">
        <el-option v-for="x in availableMajors" :key="x.value" :label="x.label" :value="x.value" />
      </el-select>
      <el-select v-model="draftGlobal.planId" placeholder="培养方案" clearable filterable class="plan-select">
        <el-option v-for="x in availablePlans" :key="x.value" :label="x.label" :value="x.value" />
      </el-select>
      <el-button type="primary" :loading="initialLoading" @click="applyGlobalFilters">查询</el-button>
      <el-button :disabled="initialLoading" @click="resetGlobalFilters">重置</el-button>
    </div>
    <div v-if="filterOptionsError&&!allFilterOptionsReady" class="filter-error">
      <span>{{filterOptionsError}}</span><el-button link type="primary" @click="loadFilterOptions">重试</el-button>
    </div>

    <el-skeleton :loading="initialLoading" animated :rows="4">
      <div class="kpis">
        <div v-for="x in kpis" :key="x.label" class="kpi" :class="{action:!!x.filter}" @click="useKpi(x)">
          <span>{{x.label}} <el-tooltip :content="x.help"><el-icon class="help"><InfoFilled/></el-icon></el-tooltip></span>
          <b>{{x.value}}</b><small>{{x.note}}</small>
          <el-button v-if="x.filter" link type="primary" @click.stop="useKpi(x)">查看学生名单 →</el-button>
        </div>
      </div>
    </el-skeleton>

    <div class="grid">
      <section class="sa-card">
        <div class="sa-card-title">各专业毕业准备概览</div>
        <div class="table-horizontal-scroll">
          <div class="major-table-width">
            <DataTable :columns="majorColumns" :data="data.majors" storage-key="curriculum:graduation-majors"
              :max-business-columns="6" :config-version="2" :pagination="true" :default-page-size="10"
              size="small" v-loading="initialLoading">
              <template #col-moduleRuleCoverageRate="{row}">{{row.module_rule_coverage_rate}}%</template>
              <template #col-action="{row}"><el-button link type="primary" @click="inspectMajor(row)">核查学生</el-button></template>
            </DataTable>
          </div>
        </div>
      </section>
      <section class="sa-card">
        <div class="sa-card-title">课程保障待确认清单 <span class="extra">按必修未通过影响人数排序；不直接判定供给不足</span></div>
        <div class="table-horizontal-scroll">
          <div class="course-table-width">
            <DataTable :columns="courseColumns" :data="data.courses" storage-key="curriculum:graduation-courses"
              :max-business-columns="7" :config-version="2" :pagination="true" :default-page-size="10"
              size="small" v-loading="initialLoading">
              <template #col-supply_priority="{row}"><el-tag size="small" type="warning">{{row.supply_priority}}</el-tag></template>
              <template #col-supply_reasons="{row}">{{(row.supply_reasons||[]).join('；')||'按学生候选情况观察'}}</template>
              <template #col-action="{row}"><el-button link type="primary" @click="openSupply(row)">保障证据</el-button></template>
            </DataTable>
          </div>
        </div>
      </section>
    </div>

    <section ref="studentSection" class="sa-card student-section">
      <div class="sa-card-title">学生核查名单</div>
      <div class="filters">
        <el-select v-model="draftStatus" clearable placeholder="全部证据状态">
          <el-option label="高年级必修未通过" value="high_grade_action"/>
          <el-option label="全部年级必修未通过" value="action_required"/>
          <el-option label="过期漏修" value="verification_required"/>
          <el-option label="当前未发现到期问题" value="evidence_complete"/>
        </el-select>
        <el-button type="primary" :loading="listLoading" @click="applyFilter">查询</el-button>
        <el-button :disabled="listLoading||(!status&&!activeMajor)" @click="reset">重置</el-button>
        <span v-if="activeMajor" class="active-scope">当前专业：<el-tag closable @close="clearMajor">{{activeMajorName}}</el-tag></span>
      </div>
      <DataTable :columns="studentColumns" :data="data.students" storage-key="curriculum:graduation-students"
        :max-business-columns="8" :config-version="2" :page-size="pageSize"
        @update:page-size="changePageSize" size="small" stripe
        v-loading="listLoading" element-loading-text="正在按名单条件提取学生证据…">
        <template #col-moduleProgress="{row}">{{row.completed_modules}} / {{row.assessable_modules}}</template>
        <template #col-evidence="{row}"><span v-if="row.explicit_required_failures">{{row.explicit_required_failures}}门必修未通过，涉及{{row.explicit_gap_modules}}个未达到模块</span><span v-else-if="row.due_required_gaps">{{row.due_required_gaps}}门过期漏修，涉及{{row.candidate_modules}}个模块</span><span v-else>当前未发现必修未通过或过期漏修</span></template>
        <template #col-status="{row}"><el-tag size="small" :type="row.readiness_status==='action_required'?'danger':row.readiness_status==='verification_required'?'warning':'success'">{{statusName[row.readiness_status]}}</el-tag></template>
        <template #col-action="{row}"><el-button link type="primary" @click="student(row)">核查证据</el-button></template>
      </DataTable>
      <el-pagination v-if="data.total" v-model:current-page="page" :page-size="pageSize" :total="data.total"
        layout="total, prev, pager, next" class="pager" @current-change="loadStudents"/>
    </section>

    <el-drawer v-model="studentVisible" :title="studentEvidence.student?.display_name ? `${studentEvidence.student.display_name}｜毕业准备核查证据` : '毕业准备核查证据'" size="900px">
      <div v-loading="studentDrawerLoading" element-loading-text="正在加载学生模块与课程证据…" class="drawer-body">
        <el-descriptions class="drawer-summary" :column="4" border>
          <el-descriptions-item label="学号">{{studentEvidence.student?.student_id}}</el-descriptions-item>
          <el-descriptions-item label="年级">{{studentEvidence.student?.entry_grade}}</el-descriptions-item>
          <el-descriptions-item label="专业">{{studentEvidence.student?.major_name}}</el-descriptions-item>
          <el-descriptions-item label="培养方案">{{studentEvidence.student?.plan_name}}</el-descriptions-item>
          <el-descriptions-item label="必修未通过">{{studentEvidence.summary?.failed_courses||0}}门</el-descriptions-item>
          <el-descriptions-item label="过期漏修">{{studentEvidence.summary?.candidate_courses||0}}门</el-descriptions-item>
          <el-descriptions-item label="历史开课无证据">{{studentEvidence.summary?.courses_without_offering||0}}门</el-descriptions-item>
          <el-descriptions-item label="课程替代证据">{{studentEvidence.summary?.courses_with_substitution||0}}门</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-actions"><el-button v-if="selectedStudentNeedsAi" type="primary" plain @click="openStudentAi({student_id:studentEvidence.student?.student_id})">归纳核查重点</el-button></div>
        <h4>必修未通过课程</h4>
        <DataTable :columns="evidenceCourseColumns" :data="studentEvidence.failed_courses||[]" storage-key="curriculum:graduation-failed-evidence" :max-business-columns="6" :config-version="2" size="small"/>
        <h4>过期漏修课程</h4>
        <DataTable :columns="candidateCourseColumns" :data="studentEvidence.candidate_courses||[]" storage-key="curriculum:graduation-candidate-evidence" :max-business-columns="6" :config-version="2" size="small"/>
      </div>
    </el-drawer>

    <el-drawer v-model="supplyVisible" :title="supply.course?.courseName ? `${supply.course.courseName}｜课程保障证据` : '课程保障证据'" size="860px">
      <div v-loading="supplyDrawerLoading" element-loading-text="正在加载历史开课、替代和影响学生证据…" class="drawer-body">
        <el-descriptions class="drawer-summary" :column="3" border>
          <el-descriptions-item label="必修未通过">{{supply.affected?.actionRequiredStudents||0}}人</el-descriptions-item>
          <el-descriptions-item label="过期漏修">{{supply.affected?.verificationStudents||0}}人</el-descriptions-item>
          <el-descriptions-item label="涉及专业">{{supply.affected?.affectedMajors||0}}个</el-descriptions-item>
          <el-descriptions-item label="历史开课学期">{{supply.offerings?.length||0}}个</el-descriptions-item>
          <el-descriptions-item label="替代关系">{{supply.substitutions?.length||0}}条</el-descriptions-item>
          <el-descriptions-item label="下一周期计划">尚未接入</el-descriptions-item>
        </el-descriptions>
        <h4>已接入历史开课记录</h4>
        <DataTable :columns="offeringColumns" :data="supply.offerings||[]" storage-key="curriculum:graduation-supply" :max-business-columns="6" :config-version="2" size="small"/>
        <h4>受影响学生</h4>
        <DataTable :columns="supplyStudentColumns" :data="supplyStudents" storage-key="curriculum:graduation-supply-students" :max-business-columns="5" :config-version="2" size="small" v-loading="supplyStudentsLoading">
          <template #col-action="{row}"><el-button link type="primary" @click="student({student_id:row.studentId})">核查学生</el-button></template>
        </DataTable>
        <el-pagination :current-page="supplyPage" :page-size="supplyPageSize" :page-sizes="[10,20,50,100]"
          :total="supplyStudentTotal" layout="total, sizes, prev, pager, next" class="pager"
          @size-change="changeSupplyPageSize" @current-change="changeSupplyPage"/>
      </div>
    </el-drawer>
    <AIInsightDrawer
      v-model="aiDrawerVisible"
      :insight="aiInsight"
      :loading="aiLoading"
      title="毕业准备研判"
      hide-intervention-tag
      hide-decision-meta
      hide-baseline
      hide-consequence
      hide-expected-result
      hide-no-comparison-tag
      hide-trace
      hide-trace-shortcut
      hide-evidence-help
      hide-evidence-source
      show-all-evidence
    />
  </div>
</template>

<script setup lang="ts">
import{computed,nextTick,onMounted,reactive,ref}from'vue'
import{InfoFilled}from'@element-plus/icons-vue'
import{http}from'@/utils/http'
import{getGraduationStudentAIInsight}from'@/utils/ai'
import AIInsightDrawer from'@/components/AIInsightDrawer.vue'
import DataTable,{type DataTableColumn}from'@/components/DataTable.vue'

const initialLoading=ref(true),listLoading=ref(false),draftStatus=ref(''),status=ref(''),page=ref(1),pageSize=ref(50)
const supplyVisible=ref(false),studentVisible=ref(false),activeMajor=ref(''),activeMajorName=ref('')
const supplyPage=ref(1),supplyPageSize=ref(50),supplyStudentTotal=ref(0),supplyCourseId=ref('')
const studentSection=ref<HTMLElement|null>(null)
const studentDrawerLoading=ref(false),supplyDrawerLoading=ref(false),supplyStudentsLoading=ref(false)
const aiDrawerVisible=ref(false),aiLoading=ref(false),aiInsight=ref<any>(null)
const data=reactive<any>({summary:{},majors:[],courses:[],students:[],total:0}),definition=reactive<any>({})
const filterOptions=reactive<any>({grades:[],colleges:[],majors:[],plans:[]})
const filterOptionsError=ref('')
const draftGlobal=reactive<any>({grades:[],organizationId:'',majorCode:'',planId:''})
const appliedGlobal=reactive<any>({grades:[],organizationId:'',majorCode:'',planId:''})
const supply=reactive<any>({}),studentEvidence=reactive<any>({}),supplyStudents=ref<any[]>([])
let overviewRequestSeq=0,listRequestSeq=0,studentRequestSeq=0,supplyRequestSeq=0,supplyStudentRequestSeq=0
const selectedStudentNeedsAi=computed(()=>Number(studentEvidence.summary?.failed_courses||0)>0)
const statusName:any={action_required:'必修未通过',verification_required:'过期漏修',evidence_complete:'当前未发现到期问题'}
const filterOptionKeys=['grades','colleges','majors','plans'] as const
const allFilterOptionsReady=computed(()=>filterOptionKeys.every(key=>filterOptions[key].length>0))
const availableMajors=computed(()=>filterOptions.majors.filter((x:any)=>!draftGlobal.organizationId||x.organizationId===draftGlobal.organizationId))
const availablePlans=computed(()=>filterOptions.plans.filter((x:any)=>(!draftGlobal.organizationId||x.organizationId===draftGlobal.organizationId)&&(!draftGlobal.majorCode||x.majorCode===draftGlobal.majorCode)&&(!draftGlobal.grades.length||draftGlobal.grades.includes(x.grade))))

const majorColumns:DataTableColumn[]=[
  {key:'major_name',label:'专业',minWidth:160,fixed:'left',required:true,region:'identity'},
  {key:'students',label:'覆盖学生',width:90,align:'right'},
  {key:'module_rule_coverage_rate',label:'模块规则可核查率',width:135,align:'right'},
  {key:'all_modules_met_students',label:'可核查模块均达到',width:130,align:'right'},
  {key:'failed_students',label:'必修未通过学生',width:120,align:'right',required:true},
  {key:'verification_students',label:'过期漏修学生',width:110,align:'right'},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const courseColumns:DataTableColumn[]=[
  {key:'course_name',label:'课程',minWidth:180,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'failed_students',label:'必修未通过学生',width:120,align:'right',required:true},
  {key:'verification_students',label:'过期漏修学生',width:110,align:'right'},
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
  {key:'explicit_required_failures',label:'必修未通过',width:100,align:'right'},
  {key:'due_required_gaps',label:'过期漏修',width:90,align:'right'},
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
  {key:'majorName',label:'专业',minWidth:150},{key:'failedRequired',label:'必修未通过',width:100,align:'right'},
  {key:'verificationRequired',label:'过期漏修',width:90,align:'right'},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const kpis=computed(()=>[
  {label:'方案覆盖可核查学生',value:(data.summary.covered_students||0)+'人',note:(data.summary.plan_count||0)+'个方案',help:'年级、专业与方案绑定一致并生成模块摘要的去重学生数。'},
  {label:'高年级必修未通过',value:(data.summary.high_grade_attention_students||0)+'人',note:'优先核查重修与课程保障',help:definition.high_grade_attention||'',filter:'high_grade_action'},
  {label:'全部年级必修未通过',value:(data.summary.action_required_students||0)+'人',note:'模块未达到且有成绩证据',help:definition.action_required||'',filter:'action_required'},
  {label:'过期漏修学生',value:(data.summary.verification_students||0)+'人',note:'先核验选课、缓修与认定',help:definition.verification_required||'',filter:'verification_required'},
  {label:'模块规则可核查率',value:(data.summary.module_rule_coverage_rate||0)+'%',note:'反映当前规则数据覆盖',help:definition.module_rule_coverage||''},
])

async function loadInitial(){await Promise.all([loadFilterOptions(),loadOverview()])}
function mergeFilterOptions(incoming:any,overwrite=false){
  for(const key of filterOptionKeys){
    const values=incoming?.[key]
    if(Array.isArray(values)&&values.length&&(overwrite||!filterOptions[key].length))filterOptions[key]=values
  }
  if(allFilterOptionsReady.value)filterOptionsError.value=''
}
async function loadFilterOptions(){
  if(allFilterOptionsReady.value)return
  filterOptionsError.value=''
  try{
    const options=await http.get<any>('/v2/curriculum/options')
    const rows=options.overviewFilters||[]
    const majorCodes=new Map(rows.map((row:any)=>[`${row.grade}|${row.collegeName}|${row.majorName}`,row.majorCode]))
    const plans=(options.plans||[])
      .filter((plan:any)=>Number(plan.studentCount||0)>0&&plan.grade!=null&&plan.collegeId)
      .map((plan:any)=>({value:plan.planId,label:plan.planName,grade:plan.grade,majorCode:plan.majorCode||majorCodes.get(`${plan.grade}|${plan.collegeName}|${plan.majorName}`)||'',organizationId:plan.collegeId,majorName:plan.majorName,collegeName:plan.collegeName}))
    const colleges=new Map<string,string>(),majors=new Map<string,any>()
    for(const plan of plans){
      colleges.set(plan.organizationId,plan.collegeName)
      if(plan.majorCode)majors.set(`${plan.organizationId}|${plan.majorCode}`,{value:plan.majorCode,label:plan.majorName,organizationId:plan.organizationId})
    }
    mergeFilterOptions({
      grades:[...new Set(plans.map((plan:any)=>plan.grade))].sort((a:any,b:any)=>b-a),
      colleges:[...colleges].map(([value,label])=>({value,label})).sort((a,b)=>a.label.localeCompare(b.label,'zh-CN')),
      majors:[...majors.values()].sort((a,b)=>a.label.localeCompare(b.label,'zh-CN')),
      plans,
    })
    if(!allFilterOptionsReady.value)filterOptionsError.value='查询条件加载失败，请重试'
  }catch{
    if(!allFilterOptionsReady.value)filterOptionsError.value='查询条件加载失败，请重试'
  }
}
function appendGlobalParams(q:URLSearchParams,includeListMajor=true){if(appliedGlobal.grades.length)q.set('grades',appliedGlobal.grades.join(','));if(appliedGlobal.organizationId)q.set('organization_id',appliedGlobal.organizationId);const majorCode=includeListMajor?(activeMajor.value||appliedGlobal.majorCode):appliedGlobal.majorCode;if(majorCode)q.set('major_code',majorCode);if(appliedGlobal.planId)q.set('plan_id',appliedGlobal.planId);return q}
function requestData(){const q=appendGlobalParams(new URLSearchParams({limit:String(pageSize.value),offset:String((page.value-1)*pageSize.value)}));if(status.value)q.set('readiness',status.value);return http.get<any>('/v2/topics/graduation-readiness?'+q)}
function applyData(r:any,includeOverview=false,includeStudents=true){if(includeStudents){data.students=r.students||[];data.total=r.total||0}if(r.filterOptions)mergeFilterOptions(r.filterOptions,true);if(includeOverview||!data.majors.length){data.summary=r.summary||{};data.majors=r.majors||[];data.courses=r.courses||[];Object.assign(definition,r.definition||{})}}
async function loadOverview(){const requestId=++overviewRequestSeq;const listRequestId=++listRequestSeq;listLoading.value=false;initialLoading.value=true;try{const r=await requestData();if(requestId===overviewRequestSeq)applyData(r,true,listRequestId===listRequestSeq)}finally{if(requestId===overviewRequestSeq)initialLoading.value=false}}
async function loadStudents(){const requestId=++listRequestSeq;listLoading.value=true;try{const r=await requestData();if(requestId===listRequestSeq)applyData(r)}finally{if(requestId===listRequestSeq)listLoading.value=false}}
async function applyGlobalFilters(){Object.assign(appliedGlobal,{grades:[...draftGlobal.grades],organizationId:draftGlobal.organizationId,majorCode:draftGlobal.majorCode,planId:draftGlobal.planId});activeMajor.value='';activeMajorName.value='';page.value=1;await loadOverview()}
async function resetGlobalFilters(){Object.assign(draftGlobal,{grades:[],organizationId:'',majorCode:'',planId:''});Object.assign(appliedGlobal,{grades:[],organizationId:'',majorCode:'',planId:''});draftStatus.value='';status.value='';activeMajor.value='';activeMajorName.value='';page.value=1;await loadOverview()}
function onCollegeChanged(){if(draftGlobal.majorCode&&!availableMajors.value.some((x:any)=>x.value===draftGlobal.majorCode))draftGlobal.majorCode='';draftGlobal.planId=''}
function onGradesChanged(){if(draftGlobal.planId&&!availablePlans.value.some((x:any)=>x.value===draftGlobal.planId))draftGlobal.planId=''}
function onMajorChanged(){draftGlobal.planId=''}
async function scrollToStudents(){await nextTick();studentSection.value?.scrollIntoView({behavior:'smooth',block:'start'})}
async function applyFilter(){status.value=draftStatus.value;page.value=1;await loadStudents();scrollToStudents()}
async function reset(){draftStatus.value='';status.value='';activeMajor.value='';activeMajorName.value='';page.value=1;await loadStudents()}
async function useKpi(x:any){if(!x.filter)return;activeMajor.value='';activeMajorName.value='';draftStatus.value=x.filter;status.value=x.filter;page.value=1;await loadStudents();scrollToStudents()}
async function inspectMajor(row:any){draftStatus.value='';status.value='';activeMajor.value=row.major_code;activeMajorName.value=row.major_name;page.value=1;await loadStudents();scrollToStudents()}
async function clearMajor(){activeMajor.value='';activeMajorName.value='';page.value=1;await loadStudents()}
function changePageSize(value:number){pageSize.value=value;page.value=1;loadStudents()}
async function student(row:any){const requestId=++studentRequestSeq;studentVisible.value=true;studentDrawerLoading.value=true;try{const r=await http.get<any>('/v2/topics/graduation-readiness/student/'+encodeURIComponent(row.student_id));if(requestId===studentRequestSeq)Object.assign(studentEvidence,r)}finally{if(requestId===studentRequestSeq)studentDrawerLoading.value=false}}
async function loadSupplyStudents(){const courseId=supplyCourseId.value;if(!courseId)return;const requestId=++supplyStudentRequestSeq;supplyStudentsLoading.value=true;const studentQuery=appendGlobalParams(new URLSearchParams(),false);studentQuery.set('course_id',courseId);studentQuery.set('limit',String(supplyPageSize.value));studentQuery.set('offset',String((supplyPage.value-1)*supplyPageSize.value));try{const s=await http.get<any>('/v2/curriculum/management-students?'+studentQuery);if(requestId===supplyStudentRequestSeq){supplyStudents.value=s.items||[];supplyStudentTotal.value=s.total||0}}finally{if(requestId===supplyStudentRequestSeq)supplyStudentsLoading.value=false}}
function changeSupplyPageSize(value:number){supplyPageSize.value=value;supplyPage.value=1;loadSupplyStudents()}
function changeSupplyPage(value:number){supplyPage.value=value;loadSupplyStudents()}
async function openSupply(row:any){const requestId=++supplyRequestSeq;supplyCourseId.value=row.course_id;supplyPage.value=1;supplyStudents.value=[];supplyStudentTotal.value=0;supplyVisible.value=true;supplyDrawerLoading.value=true;try{const id=encodeURIComponent(row.course_id);const context=appendGlobalParams(new URLSearchParams(),false);const supplyQuery=context.toString();const[r]=await Promise.all([http.get<any>('/v2/curriculum/course-supply/'+id+(supplyQuery?'?'+supplyQuery:'')),loadSupplyStudents()]);if(requestId===supplyRequestSeq)Object.assign(supply,r)}finally{if(requestId===supplyRequestSeq)supplyDrawerLoading.value=false}}
async function openStudentAi(row:any){const sid=row.student_id;if(!sid)return;aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getGraduationStudentAIInsight(sid)}finally{aiLoading.value=false}}
onMounted(loadInitial)
</script>

<style scoped>
.crumb{margin-bottom:8px}.global-filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0}.global-filters .el-select{width:180px}.global-filters .plan-select{width:260px}.filter-error{display:flex;align-items:center;gap:8px;margin:-6px 0 10px;color:#c2410c;font-size:13px}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:14px 0}.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}.kpi.action{cursor:pointer}.kpi span,.kpi small{display:block;color:#64748b}.kpi b{display:block;font-size:24px;margin:6px 0;color:#0f172a}.help{display:inline-flex!important;color:#64748b}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid>.sa-card{min-width:0}.table-horizontal-scroll{width:100%;max-width:100%;overflow-x:auto;overflow-y:hidden;padding-bottom:4px}.major-table-width{min-width:1040px}.course-table-width{min-width:1280px}.student-section{margin-top:14px;scroll-margin-top:16px}.filters{display:flex;gap:10px;align-items:center;margin-bottom:12px}.filters .el-select{width:220px}.active-scope{font-size:12px;color:#64748b}.pager{justify-content:flex-end;margin-top:12px}.drawer-body{min-height:340px}.drawer-summary{margin:14px 0}.drawer-actions{display:flex;justify-content:flex-end;margin-bottom:10px}@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style>
