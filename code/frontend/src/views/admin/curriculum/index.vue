<template>
  <div v-loading="optionsLoading" element-loading-text="正在读取可用培养方案…" element-loading-background="rgba(248,250,252,.82)">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">基于真实培养方案与学生课程记录，核查方案结构、学分要求和学生执行情况</p>
      </div>
      <div v-if="['plan','progress'].includes(activeTab)" class="plan-filter-area">
        <div class="filter-scope-label">当前分析方案 <span>同时作用于“方案结构与要求”和“学生进度核查”</span></div>
        <div class="plan-filters">
        <el-select v-model="college" placeholder="学院" clearable filterable @change="resetCollege">
          <el-option v-for="x in colleges" :key="x" :label="x" :value="x" />
        </el-select>
        <el-select v-model="grade" placeholder="年级" clearable @change="resetGrade">
          <el-option v-for="x in grades" :key="x" :label="`${x}级`" :value="x" />
        </el-select>
        <el-select v-model="major" placeholder="专业" clearable filterable @change="resetMajor">
          <el-option v-for="x in majorNames" :key="x" :label="x" :value="x" />
        </el-select>
        <el-select v-model="selectedMajor" placeholder="培养方案" filterable style="width:260px" @change="onPlanChanged">
          <el-option v-for="x in availablePlans" :key="x.planId" :label="`${x.planName} · ${x.coverageLabel}`" :value="x.planId" />
        </el-select>
        </div>
      </div>
    </div>
    <BusinessPageContext
      source="培养方案、学籍、成绩、教学任务与课程替代数据"
      :loading="pageLoading"
      :period="analysisPeriod"
    />

    <el-tabs v-model="activeTab">
      <el-tab-pane label="方案执行总览" name="overview">
        <el-alert type="success" :closable="false" show-icon title="当前授权范围的方案执行总览" description="以下卡片和表格按当前工作身份的数据权限计算，不受单个培养方案查看条件影响。" style="margin-bottom:10px" />
        <el-alert type="info" :closable="false" show-icon :title="overview.definition.boundary" style="margin-bottom:14px" />
        <div class="sa-kpi-row" v-loading="overviewLoading" element-loading-text="正在汇总方案覆盖与执行状态…">
          <KpiCard label="已接入方案" :value="`${overview.summary.activePlans || 0}个`" hint="当前授权范围可见的已接入培养方案数" tone="primary" />
          <KpiCard label="可进行规则核查方案" :value="`${overview.summary.reviewablePlans || 0}个`" :hint="overview.definition.reviewablePlans" tone="teal" />
          <KpiCard label="适用学生绑定率" :value="overview.summary.bindingRate == null ? '—' : `${overview.summary.bindingRate}%`" :hint="overview.definition.bindingRate" tone="teal" />
          <KpiCard label="明确培养要求问题" :value="`${overview.summary.actionRequiredStudents || 0}人`" :hint="overview.definition.actionRequiredStudents" tone="danger" />
          <KpiCard label="数据候选学生" :value="`${overview.summary.verificationStudents || 0}人`" :hint="overview.definition.verificationStudents" tone="amber" />
        </div>
        <div class="sa-card" style="margin-top:16px">
          <div class="sa-card-title">学院方案执行关注 <span class="extra">按明确问题、数据候选、绑定待核验依次排序</span></div>
          <DataTable :columns="collegeColumns" :data="overview.colleges" storage-key="curriculum:college-overview"
            :max-business-columns="7" :config-version="2" size="small" stripe v-loading="overviewLoading">
            <template #col-bindingRate="{row}">{{row.bindingRate == null ? '—' : `${row.bindingRate}%`}}</template>
            <template #col-actionRequired="{row}"><el-button link type="danger" :disabled="!row.actionRequired" @click="openStudents({college_name:row.collegeName,status:'明确需处理'},`${row.collegeName}｜明确问题`)">{{row.actionRequired}}</el-button></template>
            <template #col-verification="{row}"><el-button link type="warning" :disabled="!row.verification" @click="openStudents({college_name:row.collegeName,status:'数据候选'},`${row.collegeName}｜数据候选`)">{{row.verification}}</el-button></template>
            <template #col-bindingReview="{row}"><el-button link type="warning" :disabled="!row.bindingReview" @click="openStudents({college_name:row.collegeName,status:'方案绑定待核验'},`${row.collegeName}｜绑定待核验`)">{{row.bindingReview}}</el-button></template>
            <template #col-action="{row}"><el-button link type="primary" @click="openStudents({college_name:row.collegeName},`${row.collegeName}｜适用范围学生`)">核查名单</el-button></template>
          </DataTable>
        </div>
        <el-row :gutter="16" style="margin-top:16px">
          <el-col :span="13"><div class="sa-card">
            <div class="sa-card-title">专业执行关注 <span class="extra">用于定位学院内部重点专业</span></div>
            <DataTable :columns="majorColumns" :data="overview.majors" storage-key="curriculum:major-overview"
              :max-business-columns="6" :config-version="2" size="small" stripe max-height="420" v-loading="overviewLoading">
              <template #col-bindingRate="{row}">{{row.bindingRate == null ? '—' : `${row.bindingRate}%`}}</template>
              <template #col-action="{row}"><el-button link type="primary" @click="openStudents({major_code:row.majorCode},`${row.majorName}｜执行核查`)">核查名单</el-button></template>
            </DataTable>
          </div></el-col>
          <el-col :span="11"><div class="sa-card">
            <div class="sa-card-title">必修课程瓶颈 <span class="extra">按影响学生数排序</span></div>
            <DataTable :columns="courseColumns" :data="overview.bottleneckCourses" storage-key="curriculum:bottleneck-courses"
              :max-business-columns="4" :config-version="2" size="small" stripe max-height="420"
              v-loading="courseLoading" element-loading-text="正在按需提取课程证据…">
              <template #col-action="{row}"><el-button link type="primary" @click="openStudents({course_id:row.courseId},row.courseName)">学生</el-button></template>
            </DataTable>
          </div></el-col>
        </el-row>
      </el-tab-pane>
      <el-tab-pane label="方案结构与要求" name="plan">
        <template v-if="hasPlan">
          <el-alert type="info" :closable="false" style="margin-bottom:14px"
            :title="`${plan.dataSource || '培养方案'}：${plan.coverageNote || '按专业与年级匹配适用方案'}`" />
          <div class="sa-kpi-row">
            <KpiCard v-for="k in planKpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="k.tone" />
          </div>

          <section class="sa-card" style="margin-bottom:16px">
            <div class="sa-card-title">模块要求与课程池 <span class="extra">课程池记录学分只描述可选范围，不等同学生应修学分</span></div>
            <DataTable :columns="moduleStructureColumns" :data="moduleSummary"
              storage-key="curriculum:plan-modules" :max-business-columns="7"
              :config-version="2" size="small" stripe v-loading="planLoading">
              <template #col-ruleLabel="{row}"><el-tag size="small" :type="row.ruleType==='not_assessable'?'info':'success'">{{row.ruleLabel}}</el-tag></template>
              <template #col-recordedCredits="{row}">{{Number(row.recordedCredits||0).toFixed(1)}}</template>
              <template #col-action="{row}"><el-button link type="primary" @click="openModuleCourses(row)">课程明细</el-button></template>
            </DataTable>
          </section>

          <div class="sa-card plan-text-card" style="margin-bottom:16px" v-if="plan.graduationRequirements.length">
            <div class="sa-card-title">毕业要求说明 <span class="extra">方案文本，不作为学生达成度结论</span></div>
            <el-alert type="info" :closable="false" show-icon title="当前仅展示培养方案原文"
              description="待学校提供‘毕业要求指标点—支撑课程—评价环节—实际结果’结构化数据后，才能计算达成度。当前不用课程平均分或通过率替代。" />
            <el-collapse class="requirement-collapse">
              <el-collapse-item :title="`查看方案原文（${plan.graduationRequirements.length}条）`" name="requirements">
                <div v-for="(r,i) in plan.graduationRequirements" :key="i" class="grad-row">
                  <el-tag size="small" type="info">{{ i+1 }}</el-tag><span>{{ r }}</span>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div class="sa-card" v-if="plan.degreeRequirement">
            <div class="sa-card-title">学位授予条件</div>
            <p style="font-size:13px;color:#475569;line-height:1.7">{{ plan.degreeRequirement }}</p>
          </div>
        </template>
        <el-empty v-else description="" :image-size="100">
          <template #description>
            <div style="font-size:13px;color:#64748B">暂无该专业培养方案数据</div>
            <div style="font-size:11px;color:#94A3B8;margin-top:4px">可切换方案查看其课程表与原文覆盖状态</div>
          </template>
        </el-empty>
      </el-tab-pane>

      <el-tab-pane label="学生进度核查" name="progress">
        <ProgressView v-if="activeTab === 'progress'" :major-id="selectedMajor" />
      </el-tab-pane>
      <el-tab-pane label="毕业准备与课程保障" name="graduation-readiness">
        <div v-if="activeTab === 'graduation-readiness'" class="embedded-topic"><GraduationReadiness /></div>
      </el-tab-pane>
    </el-tabs>
    <el-drawer v-model="moduleDrawer.visible" :title="`${moduleDrawer.module?.name || ''}｜课程池明细`" size="820px">
      <el-alert type="info" :closable="false" show-icon title="课程池明细用于解释方案结构；选修池课程不等同每名学生都必须完成。" style="margin-bottom:12px" />
      <DataTable :columns="moduleCourseColumns" :data="moduleDrawer.module?.courses || []"
        storage-key="curriculum:module-courses" :max-business-columns="6"
        :config-version="2" :pagination="true" :default-page-size="20" size="small">
        <template #col-suggestedTerm="{row}">{{row.suggestedTerm || '—'}}</template>
      </DataTable>
    </el-drawer>
    <el-drawer v-model="studentDialog.visible" :title="`${studentDialog.title}｜方案执行学生名单`" size="980px">
      <el-alert type="info" :closable="false" :title="studentDialog.definition" style="margin-bottom:12px" />
      <DataTable :columns="studentListColumns" :data="studentDialog.items"
        storage-key="curriculum:management-students" :max-business-columns="7"
        :config-version="2" :page-size="studentDialog.pageSize" @update:page-size="onStudentPageSize"
        size="small" stripe v-loading="studentDialog.loading" element-loading-text="正在加载核查名单…">
        <template #col-evidenceStatus="{row}"><el-tag size="small" :type="row.evidenceStatus==='明确需处理'?'danger':row.evidenceStatus==='数据候选'||row.evidenceStatus==='方案绑定待核验'?'warning':'info'">{{row.evidenceStatus}}</el-tag></template>
        <template #col-action="{row}"><el-button v-if="row.coverageStatus==='matched'" link type="primary" @click="studentProfile(row)">执行详情</el-button><span v-else class="sa-faint">先核验绑定</span></template>
      </DataTable>
      <el-pagination v-if="studentDialog.total" v-model:current-page="studentDialog.page"
        :page-size="studentDialog.pageSize" :total="studentDialog.total"
        layout="total, prev, pager, next" class="drawer-pager" @current-change="loadStudentPage" />
    </el-drawer>
    <el-drawer v-model="studentEvidence.visible" :title="`${studentEvidence.data.student?.display_name || ''}｜培养方案执行详情`" size="760px" append-to-body>
      <div v-loading="studentEvidence.loading">
        <el-alert type="warning" :closable="false" show-icon title="这是方案执行核查，不是学生综合档案" :description="studentEvidence.data.boundary" />
        <el-descriptions class="student-evidence-summary" :column="2" border>
          <el-descriptions-item label="学号">{{ studentEvidence.data.student?.student_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="年级">{{ studentEvidence.data.student?.entry_grade || '—' }}</el-descriptions-item>
          <el-descriptions-item label="专业">{{ studentEvidence.data.student?.major_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="培养方案">{{ studentEvidence.data.student?.plan_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="明确未通过">{{ studentEvidence.data.summary?.failed_courses || 0 }} 门</el-descriptions-item>
          <el-descriptions-item label="到期缺结果候选">{{ studentEvidence.data.summary?.candidate_courses || 0 }} 门</el-descriptions-item>
          <el-descriptions-item label="无历史开课证据">{{ studentEvidence.data.summary?.courses_without_offering || 0 }} 门</el-descriptions-item>
          <el-descriptions-item label="有课程替代证据">{{ studentEvidence.data.summary?.courses_with_substitution || 0 }} 门</el-descriptions-item>
        </el-descriptions>
        <h4 class="evidence-title">明确未通过必修课程 <small>可直接进入重修与课程保障核查</small></h4>
        <DataTable :columns="failedEvidenceColumns" :data="studentEvidence.data.failed_courses || []"
          storage-key="curriculum:overview-student-failed-evidence" :max-business-columns="5"
          :config-version="2" size="small" empty-text="当前没有明确未通过必修课程" />
        <h4 class="evidence-title">到期缺结果记录候选 <small>必须先核验选课、免修与认定数据</small></h4>
        <DataTable :columns="candidateEvidenceColumns" :data="studentEvidence.data.candidate_courses || []"
          storage-key="curriculum:overview-student-candidate-evidence" :max-business-columns="4"
          :config-version="2" size="small" max-height="280" empty-text="当前没有到期缺结果候选" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import KpiCard from '@/components/KpiCard.vue'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import ProgressView from './Progress.vue'
import GraduationReadiness from '../reports/GraduationReadiness.vue'
import { useBusinessPageTitle } from '@/utils/businessPage'

const route = useRoute()
const router = useRouter()
const pageTitle = useBusinessPageTitle('/admin/curriculum', '培养质量分析')
const allPlans = ref<any[]>([])
const college = ref('')
const grade = ref<number | ''>('')
const major = ref('')
const selectedMajor = ref('')
const curriculumTabs = new Set(['overview','plan','progress','graduation-readiness'])
const activeTab = ref(curriculumTabs.has(String(route.query.tab)) ? String(route.query.tab) : 'overview')
const selectedPlanPeriod = computed(() => {
  const plan = allPlans.value.find((item:any) => item.planId === selectedMajor.value)
  return plan ? `当前方案：${plan.planName}` : '尚未选择培养方案'
})
const analysisPeriod = computed(() => {
  if (activeTab.value === 'overview') return '当前授权范围总览'
  if (activeTab.value === 'graduation-readiness') return '当前授权范围毕业准备核查'
  return selectedPlanPeriod.value
})
watch(activeTab, tab => {
  const query = { ...route.query }
  if (tab === 'overview') delete query.tab
  else query.tab = tab
  router.replace({ path:'/admin/curriculum', query })
  loadActiveTab(tab)
})
const optionsLoading=ref(false),overviewLoading=ref(false),courseLoading=ref(false),planLoading=ref(false)
const overviewLoaded=ref(false),courseLoaded=ref(false)
const pageLoading=computed(()=>optionsLoading.value||(activeTab.value==='overview'&&overviewLoading.value)||(activeTab.value==='plan'&&planLoading.value))
const overview = reactive<any>({ summary:{}, colleges:[], majors:[], bottleneckCourses:[], definition:{ boundary:'' } })
const studentDialog = reactive<any>({visible:false,loading:false,title:'',items:[],definition:'',params:{},page:1,pageSize:50,total:0})
const studentEvidence = reactive<any>({visible:false,loading:false,data:{student:{},summary:{},failed_courses:[],candidate_courses:[],boundary:''}})
const moduleDrawer=reactive<any>({visible:false,module:null})
const collegeColumns:DataTableColumn[]=[
  {key:'collegeName',label:'学院',minWidth:180,fixed:'left',required:true,region:'identity'},
  {key:'applicableStudents',label:'适用学生',width:90,align:'right'},
  {key:'bindingRate',label:'正确绑定率',width:100,align:'right',required:true},
  {key:'actionRequired',label:'明确问题',width:90,align:'right'},
  {key:'verification',label:'数据候选',width:90,align:'right'},
  {key:'bindingReview',label:'绑定待核验',width:105,align:'right'},
  {key:'outsideSourceScope',label:'方案源未覆盖',width:110,align:'right',defaultVisible:false},
  {key:'action',label:'操作',width:90,fixed:'right',required:true,region:'action'},
]
const majorColumns:DataTableColumn[]=[
  {key:'collegeName',label:'学院',minWidth:140,fixed:'left',required:true,region:'identity'},
  {key:'majorName',label:'专业',minWidth:150,fixed:'left',required:true,region:'identity'},
  {key:'applicableStudents',label:'适用学生',width:90,align:'right'},
  {key:'bindingRate',label:'正确绑定率',width:100,align:'right'},
  {key:'actionRequired',label:'明确问题',width:90,align:'right'},
  {key:'verification',label:'数据候选',width:90,align:'right'},
  {key:'bindingReview',label:'绑定待核验',width:105,align:'right',defaultVisible:false},
  {key:'action',label:'操作',width:105,fixed:'right',required:true,region:'action'},
]
const courseColumns:DataTableColumn[]=[
  {key:'courseName',label:'课程',minWidth:170,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'actionRequiredStudents',label:'明确未通过学生',width:120,align:'right',required:true},
  {key:'verificationStudents',label:'数据候选学生',width:110,align:'right'},
  {key:'affectedMajors',label:'涉及专业',width:85,align:'right'},
  {key:'action',label:'操作',width:70,fixed:'right',required:true,region:'action'},
]
const moduleStructureColumns:DataTableColumn[]=[
  {key:'name',label:'模块',minWidth:180,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'nature',label:'性质',width:110},
  {key:'ruleLabel',label:'采用规则',minWidth:190,required:true,tooltip:true},
  {key:'courseCount',label:'课程池',width:85,align:'right'},
  {key:'recordedCredits',label:'课程池记录学分',width:125,align:'right'},
  {key:'sourceReference',label:'规则来源',minWidth:180,defaultVisible:false,tooltip:true},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const moduleCourseColumns:DataTableColumn[]=[
  {key:'courseId',label:'课程代码',width:130,fixed:'left',required:true,region:'identity'},
  {key:'courseName',label:'课程名称',minWidth:210,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'requirementType',label:'性质',width:80},
  {key:'credits',label:'学分',width:75,align:'right'},
  {key:'suggestedTerm',label:'建议学期',width:90},
  {key:'organizationId',label:'开课单位代码',width:120,defaultVisible:false},
]
const studentListColumns:DataTableColumn[]=[
  {key:'studentId',label:'学号',width:130,fixed:'left',required:true,region:'identity'},
  {key:'name',label:'姓名',width:90,fixed:'left',required:true,region:'identity'},
  {key:'grade',label:'年级',width:75},
  {key:'collegeName',label:'学院',minWidth:140},
  {key:'majorName',label:'专业',minWidth:140},
  {key:'completedModules',label:'已达到模块',width:100,align:'right'},
  {key:'assessableModules',label:'可核查模块',width:100,align:'right'},
  {key:'failedRequired',label:'明确未通过',width:100,align:'right'},
  {key:'verificationRequired',label:'数据候选',width:90,align:'right'},
  {key:'evidenceStatus',label:'状态',width:140,required:true},
  {key:'action',label:'操作',width:85,fixed:'right',required:true,region:'action'},
]
const failedEvidenceColumns:DataTableColumn[]=[
  {key:'course_name',label:'课程',minWidth:160,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'effective_score',label:'成绩',width:70,align:'right'},
  {key:'lesson_count',label:'历史教学班',width:100,align:'right'},
  {key:'substitution_count',label:'替代证据',width:90,align:'right'},
  {key:'reason',label:'核查原因与动作',minWidth:280,required:true,tooltip:true},
]
const candidateEvidenceColumns:DataTableColumn[]=[
  {key:'course_name',label:'课程',minWidth:160,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'suggested_term',label:'建议学期',width:90},
  {key:'lesson_count',label:'历史教学班',width:100,align:'right'},
  {key:'reason',label:'核查原因与动作',minWidth:300,required:true,tooltip:true},
]
function openModuleCourses(row:any){moduleDrawer.module=row;moduleDrawer.visible=true}

async function loadOverview(){
  if(overviewLoaded.value)return
  overviewLoading.value=true
  try{Object.assign(overview,await http.get('/v2/curriculum/management-overview'));overviewLoaded.value=true}
  finally{overviewLoading.value=false}
  if(!courseLoaded.value){
    courseLoading.value=true
    try{const result=await http.get('/v2/curriculum/management-courses?limit=20');overview.bottleneckCourses=result.items||[];courseLoaded.value=true}
    finally{courseLoading.value=false}
  }
}
function loadActiveTab(tab:string){
  if(tab==='overview')loadOverview()
  else if(tab==='plan')loadPlan()
}

async function openStudents(params:Record<string,string>, title:string) {
  studentDialog.visible=true;studentDialog.title=title;studentDialog.params=params;studentDialog.page=1
  await loadStudentPage()
}
async function loadStudentPage(){
  studentDialog.loading=true
  try {
    const query=new URLSearchParams(studentDialog.params)
    query.set('limit',String(studentDialog.pageSize))
    query.set('offset',String((studentDialog.page-1)*studentDialog.pageSize))
    const data=await http.get('/v2/curriculum/management-students?'+query.toString())
    Object.assign(studentDialog,{items:data.items||[],definition:data.definition||'',total:data.total||0})
  } finally { studentDialog.loading=false }
}
function onStudentPageSize(value:number){studentDialog.pageSize=value;studentDialog.page=1;loadStudentPage()}
async function studentProfile(row:any) {
  studentEvidence.visible=true; studentEvidence.loading=true
  studentEvidence.data={student:{display_name:row.name,student_id:row.studentId},summary:{},failed_courses:[],candidate_courses:[],boundary:''}
  try { studentEvidence.data=await http.get('/v2/topics/graduation-readiness/student/'+encodeURIComponent(row.studentId)) }
  finally { studentEvidence.loading=false }
}

const colleges = computed(() => [...new Set(allPlans.value.map(x => x.collegeName))].sort())
const collegePlans = computed(() => allPlans.value.filter(x => !college.value || x.collegeName === college.value))
const grades = computed(() => [...new Set<number>(collegePlans.value.map(x => x.grade))].sort((a,b) => b-a))
const gradePlans = computed(() => collegePlans.value.filter(x => grade.value === '' || x.grade === grade.value))
const majorNames = computed(() => [...new Set<string>(gradePlans.value.map(x => x.majorName))].sort())
const availablePlans = computed(() => gradePlans.value.filter(x => !major.value || x.majorName === major.value))

function pickFirst() { selectedMajor.value = availablePlans.value[0]?.planId || ''; onPlanChanged() }
function resetCollege() { grade.value=''; major.value=''; pickFirst() }
function resetGrade() { major.value=''; pickFirst() }
function resetMajor() { pickFirst() }
function onPlanChanged(){if(activeTab.value==='plan')loadPlan()}

const plan = reactive<any>({
  name: '', grade: '', college: '', totalCredits: 0, requiredCredits: 0,
  electiveMinCredits: 0, practiceCredits: 0, modules: [], graduationRequirements: [], degreeRequirement: '',
  planVersion: '', applicableGrade: '', dataSource: '', coverageNote: '',
  courseCount: 0, moduleCount: 0, graduationMinimumCredits: null, creditNote: '',
  requiredMinimumCredits:null, electiveMinimumCredits:null, practiceMinimumCredits:null,
  moduleRequirements: [], coverageLabel:'',
})
const hasPlan = ref(true)

function resetPlan() {
  Object.assign(plan, {
    name: '', grade: '', college: '', totalCredits: 0, requiredCredits: 0,
    electiveMinCredits: 0, practiceCredits: 0, modules: [], graduationRequirements: [], degreeRequirement: '',
    planVersion: '', applicableGrade: '', dataSource: '', coverageNote: '',
    courseCount: 0, moduleCount: 0, graduationMinimumCredits: null, creditNote: '',
    requiredMinimumCredits:null, electiveMinimumCredits:null, practiceMinimumCredits:null,
    moduleRequirements: [], coverageLabel:'',
  })
}

const planKpis = computed(() => [
  { label: '毕业最低学分', value: plan.graduationMinimumCredits ?? '待核验', formula: '只采用方案原文明示的毕业最低要求；未结构化时不推算', tone: 'amber' as const },
  { label: '课程模块', value: `${plan.moduleCount}个`, formula: '按方案课程表模块字段去重', tone: 'primary' as const },
  { label: '有明确规则模块', value: `${plan.modules.filter((x:any)=>x.ruleType!=='not_assessable').length}/${plan.moduleCount}个`, formula: '可按最低学分、最低门数或逐门必修评价的模块数', tone: 'teal' as const },
  { label: '课程池课程', value: `${plan.courseCount}门`, formula: '结构化方案课程表全部课程行，包含选修备选范围，不作为学生应修门数', tone: 'primary' as const },
  { label: '方案证据状态', value: plan.coverageLabel || '待核验', formula: '说明方案原文、课程表和规则的接入完整程度', tone: 'amber' as const },
])

const moduleSummary = computed(() => plan.modules || [])

async function loadPlan() {
  if (!selectedMajor.value) { hasPlan.value = false; resetPlan(); return }
  planLoading.value = true
  try {
    const d = await http.get('/v2/curriculum/plans/' + selectedMajor.value)
    if (d?.plan) {
      Object.assign(plan, {
        name: d.plan.planName, grade: `${d.plan.grade}级`, college: college.value,
        totalCredits: d.creditEvidence?.recordedCourseCredits ?? 0, requiredCredits: '待核验',
        electiveMinCredits: '待核验', practiceCredits: '待核验',
        courseCount: d.courses?.length || 0, moduleCount: d.modules?.length || 0,
        graduationMinimumCredits: d.creditEvidence?.graduationMinimumCredits,
        requiredMinimumCredits: d.creditEvidence?.requiredMinimumCredits,
        electiveMinimumCredits: d.creditEvidence?.electiveMinimumCredits,
        practiceMinimumCredits: d.creditEvidence?.practiceMinimumCredits,
        moduleRequirements: d.moduleRequirements || [],
        creditNote: d.creditEvidence?.note || '',
        modules: d.modules || [],
        graduationRequirements: d.requirements.map((x:any) => x.text),
        degreeRequirement: d.creditEvidence?.degreeRequirement || '',
        planVersion: d.plan.version || d.plan.planId,
        dataSource: d.creditEvidence?.sourceFile ? `真实培养方案原文（${d.creditEvidence.sourceFile}）` : '结构化方案课程表',
        coverageNote: `${d.coverage?.label || '覆盖状态待确认'}；${d.evidence.boundaryNote}`,
        coverageLabel: d.coverage?.label || '待核验',
      })
      hasPlan.value = true
    }
    else { hasPlan.value = false; resetPlan() }
  } catch {
    hasPlan.value = false; resetPlan()
  } finally { planLoading.value = false }
}

onMounted(async () => {
  optionsLoading.value = true
  try {
    const d = await http.get('/v2/curriculum/options')
    allPlans.value = d.plans || []
    const requested=allPlans.value.find(x=>x.planId===String(route.query.plan_id||''))
    const first = requested || allPlans.value.find(x => x.requirementCount > 0) || allPlans.value[0]
    if (first) {
      college.value=first.collegeName; grade.value=first.grade; major.value=first.majorName
      selectedMajor.value=first.planId
    }
  } catch { hasPlan.value=false; resetPlan() }
  finally { optionsLoading.value=false }
  loadActiveTab(activeTab.value)
})
</script>

<style scoped>
.sa-head-row { display:block; margin-bottom:14px; }
.plan-filter-area { width:100%; margin-top:12px; padding:10px 12px; border:1px solid #dbeafe; border-radius:9px; background:#f8fbff; }
.filter-scope-label { margin-bottom:8px; color:#334155; font-size:12px; font-weight:600; }
.filter-scope-label span { margin-left:8px; color:#64748b; font-weight:400; }
.plan-filters { display:flex; gap:8px; flex-wrap:nowrap; align-items:center; width:100%; }
.plan-filters .el-select { width:180px; flex:0 0 180px; }
.plan-filters .el-select:last-child { width:300px !important; flex:1 1 300px; }
@media (max-width:900px) { .plan-filters { overflow-x:auto; padding-bottom:4px; } }
.grad-row { padding: 8px 0; border-bottom: 1px solid var(--sa-border); font-size: 13px; display: flex; gap: 8px; align-items: flex-start; color: #334155; }
.grad-row:last-child { border-bottom: none; }
.plan-text-card :deep(.el-alert) { margin-bottom: 8px; }
.requirement-collapse { border-top:0; }
.requirement-collapse :deep(.el-collapse-item__header) { color:#475569; font-size:13px; }
.student-evidence-summary { margin:14px 0 18px; }
.embedded-topic :deep(.crumb),
.embedded-topic :deep(.sa-page-title),
.embedded-topic :deep(.sa-page-sub),
.embedded-topic :deep(.el-breadcrumb) { display:none; }
.evidence-title { margin:20px 0 10px; color:#1e293b; }
.evidence-title small { margin-left:8px; color:#64748b; font-weight:400; }
.module-collapse { border-top:0; }
.module-collapse-title { display:flex; justify-content:space-between; align-items:center; width:100%; padding-right:14px; }
.module-collapse-title b { color:#334155; font-size:13px; }
.module-collapse-title span { color:#64748b; font-size:12px; font-variant-numeric:tabular-nums; }
.module-course-table + .module-course-table { margin-top:12px; }
.submodule-name { margin:0 0 6px; color:#475569; font-size:12px; font-weight:600; }
</style>
