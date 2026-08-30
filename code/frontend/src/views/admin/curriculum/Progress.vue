<template>
  <div>
    <div v-if="!planName" class="sa-faint empty-plan">请先选择培养方案</div>
    <template v-else>
      <div class="sa-kpi-row">
        <KpiCard label="方案覆盖学生" :value="summary.coveredStudents" hint="方案年级、专业与学生绑定一致并生成模块摘要的去重学生数" tone="primary" />
        <KpiCard label="模块规则可核查率" :value="`${summary.moduleRuleCoverageRate}%`" :hint="definition.moduleRuleCoverageRate" tone="teal" />
        <KpiCard label="可核查模块均达到" :value="summary.allModulesMetStudents" :hint="definition.allModulesMet" tone="teal" />
        <KpiCard label="必修未通过学生" :value="summary.actionRequiredStudents" :hint="definition.actionRequired" tone="danger" />
        <KpiCard label="过期漏修学生" :value="summary.verificationStudents" :hint="definition.verificationRequired" tone="amber" />
      </div>
      <section class="sa-card">
        <div class="sa-card-title">学生模块进度核查 <span class="extra">当前列表 {{ filteredProgress.length }} 人</span></div>
        <DataTable :columns="studentColumns" :data="filteredProgress"
          storage-key="curriculum:student-progress" :max-business-columns="8"
          :config-version="3" :pagination="true" :default-page-size="20"
          stripe size="small" v-loading="loading" element-loading-text="正在计算学生模块进度…">
          <template #toolbar>
            <div class="filters">
              <el-input v-model="keyword" placeholder="搜索学号或姓名" clearable />
              <el-select v-model="statusFilter" placeholder="全部状态" clearable>
                <el-option label="必修未通过" value="明确需处理" />
                <el-option label="过期漏修" value="数据候选" />
                <el-option label="当前未发现到期问题" value="当前未发现到期问题" />
              </el-select>
              <el-button @click="exportCsv">导出</el-button>
            </div>
          </template>
          <template #col-moduleProgress="{row}"><b class="tnum">{{row.completedModules}}</b><span class="sa-faint"> / {{row.assessableModules}} 个</span></template>
          <template #col-earnedCredits="{row}">{{ Number(row.earnedCredits || 0).toFixed(1) }}</template>
          <template #col-failedRequired="{row}"><b :class="row.failedRequired?'risk':'sa-faint'">{{row.failedRequired}}</b> 门</template>
          <template #col-verificationRequired="{row}">{{row.verificationRequired}} 门</template>
          <template #col-status="{row}"><el-tag size="small" :type="statusTag(row.status)">{{statusLabel(row.status)}}</el-tag></template>
          <template #col-statusReason="{row}">{{statusReasonLabel(row)}}</template>
          <template #col-action="{row}"><el-button link type="primary" @click="openStudent(row)">详情</el-button></template>
        </DataTable>
      </section>
    </template>

    <el-drawer v-model="detailVisible" :title="`${selectedStudent.name || ''}｜培养方案进度核查`" size="920px">
      <div v-loading="detailLoading" element-loading-text="正在加载模块与课程证据…" class="drawer-body">
        <el-alert v-if="detailError" type="error" :closable="false" show-icon title="详情加载失败" class="drawer-alert">
          <template #default><el-button size="small" @click="loadStudentDetail">重新加载</el-button></template>
        </el-alert>
        <template v-else>
          <el-descriptions :column="4" border size="small" class="drawer-summary">
            <el-descriptions-item label="学号">{{selectedStudent.studentId}}</el-descriptions-item>
            <el-descriptions-item label="年级">{{selectedStudent.grade || '—'}}</el-descriptions-item>
            <el-descriptions-item label="当前学习学期">第{{selectedStudent.currentStudyTerm || '—'}}学期</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag size="small" :type="statusTag(selectedStudent.status)">{{statusLabel(selectedStudent.status)}}</el-tag></el-descriptions-item>
            <el-descriptions-item label="可核查模块">{{selectedStudent.assessableModules || 0}}个</el-descriptions-item>
            <el-descriptions-item label="已达到模块">{{selectedStudent.completedModules || 0}}个</el-descriptions-item>
            <el-descriptions-item label="已认可学分">{{Number(selectedStudent.earnedCredits || 0).toFixed(1)}}</el-descriptions-item>
            <el-descriptions-item label="规则覆盖率">{{selectedStudent.ruleCoverageRate || 0}}%</el-descriptions-item>
          </el-descriptions>
          <el-tabs v-model="detailTab">
            <el-tab-pane name="modules">
              <template #label>
                <span class="tab-label-with-help">模块完成核查（{{moduleProgress.length}}）
                  <el-tooltip content="逐一核查该学生培养方案中的所有模块；优先比较已认可学分与最低学分，其次比较已完成门数与最低门数，最后核查模块内必修课程是否全部通过或认定" placement="top">
                    <el-icon class="tab-help-icon" tabindex="0" aria-label="查看模块完成核查计算说明"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <DataTable :columns="moduleColumns" :data="moduleProgress"
                storage-key="curriculum:student-module-detail" :max-business-columns="7"
                :config-version="2" size="small">
                <template #col-progress="{row}"><span v-if="row.target != null"><b>{{row.achieved}}</b> / {{row.target}}</span><span v-else>—</span></template>
                <template #col-evidenceStatus="{row}"><el-tag size="small" :type="moduleTag(row.evidenceStatus)">{{moduleStatus(row.evidenceStatus)}}</el-tag></template>
              </DataTable>
            </el-tab-pane>
            <el-tab-pane :label="`必修未通过课程（${failedCourses.length}）`" name="failed">
              <DataTable :columns="failedColumns" :data="failedCourses" storage-key="curriculum:student-failed-courses"
                :max-business-columns="5" :config-version="2" size="small" empty-text="没有必修未通过课程" />
            </el-tab-pane>
            <el-tab-pane :label="`过期漏修课程（${verificationCourses.length}）`" name="verification">
              <DataTable :columns="candidateColumns" :data="verificationCourses" storage-key="curriculum:student-candidate-courses"
                :max-business-columns="5" :config-version="2" size="small" empty-text="没有过期漏修课程" />
            </el-tab-pane>
            <el-tab-pane name="all">
              <template #label>
                <span class="tab-label-with-help">全部课程证据
                  <el-tooltip content="该学生当前绑定培养方案中，所有课程及其最新结果状态的记录数，包括通过、替代或认定、未通过、尚无完成证据和证据未知" placement="top">
                    <el-icon class="tab-help-icon" tabindex="0" aria-label="查看全部课程证据计算说明"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <DataTable :columns="allCourseColumns" :data="detailCourses" storage-key="curriculum:student-all-plan-courses"
                :max-business-columns="6" :config-version="2" :pagination="true" :default-page-size="20" size="small">
                <template #col-completion_status="{row}"><el-tag size="small" :type="courseTag(row.completion_status)">{{courseStatus(row.completion_status)}}</el-tag></template>
              </DataTable>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { http } from '@/utils/http'
import { QuestionFilled } from '@element-plus/icons-vue'
import KpiCard from '@/components/KpiCard.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'

const props = defineProps<{ majorId: string }>()
const loading=ref(false), planName=ref(''), planVersion=ref(''), progress=ref<any[]>([])
const summary=ref<any>({coveredStudents:0,moduleRuleCoverageRate:0,allModulesMetStudents:0,actionRequiredStudents:0,verificationStudents:0})
const definition=ref<any>({boundary:''}), keyword=ref(''), statusFilter=ref('')
const detailVisible=ref(false), detailLoading=ref(false), detailError=ref(false), detailTab=ref('modules')
const selectedStudent=ref<any>({}), detailCourses=ref<any[]>([]), moduleProgress=ref<any[]>([])

const studentColumns:DataTableColumn[]=[
  {key:'studentId',label:'学号',width:130,fixed:'left',required:true,region:'identity'},
  {key:'name',label:'姓名',width:90,fixed:'left',required:true,region:'identity'},
  {key:'grade',label:'年级',width:75},
  {key:'currentStudyTerm',label:'学习学期',width:90},
  {key:'moduleProgress',label:'已达到/可核查模块',width:145,required:true},
  {key:'earnedCredits',label:'已认可学分',width:105,align:'right'},
  {key:'failedRequired',label:'必修未通过',width:105,align:'right'},
  {key:'verificationRequired',label:'过期漏修',width:95,align:'right'},
  {key:'status',label:'状态',width:125,required:true},
  {key:'statusReason',label:'状态原因',minWidth:260,required:true,tooltip:true},
  {key:'action',label:'操作',width:70,fixed:'right',required:true,region:'action'},
]
const moduleColumns:DataTableColumn[]=[
  {key:'module',label:'模块',minWidth:170,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'ruleLabel',label:'采用规则',minWidth:190,required:true,tooltip:true},
  {key:'progress',label:'完成进度',width:110},
  {key:'earnedCredits',label:'已认可学分',width:105,align:'right'},
  {key:'completedCourses',label:'完成课程',width:90,align:'right'},
  {key:'failedRequired',label:'必修未通过',width:100,align:'right'},
  {key:'verificationRequired',label:'过期漏修',width:90,align:'right'},
  {key:'sourceReference',label:'规则来源',minWidth:160,defaultVisible:false,tooltip:true},
  {key:'evidenceStatus',label:'判断',width:100,required:true},
]
const baseCourseColumns:DataTableColumn[]=[
  {key:'course_id',label:'课程代码',width:125,fixed:'left',required:true,region:'identity'},
  {key:'course_name',label:'课程',minWidth:180,fixed:'left',required:true,region:'identity',tooltip:true},
  {key:'module',label:'模块',minWidth:140,tooltip:true},
  {key:'suggested_term',label:'建议学期',width:90},
]
const failedColumns=[...baseCourseColumns,{key:'effective_score',label:'有效成绩',width:90,align:'right'}]
const candidateColumns=[...baseCourseColumns,{key:'requirement_type',label:'性质',width:80}]
const allCourseColumns=[...baseCourseColumns,{key:'requirement_type',label:'性质',width:80},{key:'completion_status',label:'完成证据',width:125,required:true}]

const failedModules=computed(()=>new Set(moduleProgress.value.filter(x=>x.evidenceStatus==='explicit_gap').map(x=>x.module)))
const candidateModules=computed(()=>new Set(moduleProgress.value.filter(x=>x.evidenceStatus==='candidate').map(x=>x.module)))
const failedCourses=computed(()=>detailCourses.value.filter(x=>failedModules.value.has(x.module)&&x.requirement_type==='必修'&&x.completion_status==='failed'))
const verificationCourses=computed(()=>detailCourses.value.filter(x=>candidateModules.value.has(x.module)&&x.requirement_type==='必修'&&['not_completed','unknown'].includes(x.completion_status)&&Number(x.is_overdue)===1))
const filteredProgress=computed(()=>progress.value.filter(row=>
  (!keyword.value||String(row.studentId).toLowerCase().includes(keyword.value.toLowerCase())||(row.name||'').includes(keyword.value))&&
  (!statusFilter.value||row.status===statusFilter.value)))

async function load(planId:string){
  if(!planId){planName.value='';progress.value=[];return}
  loading.value=true
  try{const data=await http.get<any>(`/v2/curriculum/progress/${planId}?limit=1000`);planName.value=data.plan?.planName||planId;planVersion.value=data.plan?.planId||'';progress.value=data.students||[];summary.value=data.summary||{};definition.value=data.definition||{}}
  finally{loading.value=false}
}
async function openStudent(row:any){selectedStudent.value=row;detailVisible.value=true;detailTab.value='modules';await loadStudentDetail()}
async function loadStudentDetail(){
  detailLoading.value=true;detailError.value=false
  try{const d=await http.get<any>(`/v2/students/${encodeURIComponent(selectedStudent.value.studentId)}/plan-courses?limit=1000`);detailCourses.value=d?.items||[];moduleProgress.value=d?.moduleProgress||[]}
  catch{detailError.value=true}finally{detailLoading.value=false}
}
function exportCsv(){const header=['学号','姓名','年级','方案','已达到模块','可核查模块','已认可学分','必修未通过','过期漏修','状态','状态原因'];const rows=filteredProgress.value.map(r=>[r.studentId,r.name,r.grade,planVersion.value,r.completedModules,r.assessableModules,r.earnedCredits,r.failedRequired,r.verificationRequired,statusLabel(r.status),statusReasonLabel(r)]);const csv='\uFEFF'+[header,...rows].map(row=>row.map(v=>`"${String(v??'').replace(/"/g,'""')}"`).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`学生模块进度_${planVersion.value}.csv`;a.click();URL.revokeObjectURL(url)}
function statusLabel(s:string){return s==='明确需处理'?'必修未通过':s==='数据候选'?'过期漏修':s}
function statusReasonLabel(row:any){
  const reason=String(row.statusReason||'').trim()
  if(reason)return reason
  if(row.status==='明确需处理')return `存在${Number(row.failedRequired||0)}门当前有效成绩仍为未通过的必修课程`
  if(row.status==='数据候选')return `存在${Number(row.verificationRequired||0)}门建议修读学期已过但尚未形成明确修读结果的必修课程`
  if(row.status==='当前未发现到期问题')return '当前未发现必修未通过或到期缺修读结果'
  return '当前方案执行证据需要进一步核验'
}
function statusTag(s:string):'success'|'danger'|'warning'|'info'{return s==='明确需处理'?'danger':s==='数据候选'?'warning':'success'}
function moduleStatus(s:string){return({explicit_gap:'必修未通过',candidate:'过期漏修',not_due:'尚未到期',complete:'已达到',not_assessable:'暂不可评价'} as any)[s]||s}
function moduleTag(s:string):'success'|'danger'|'warning'|'info'{return s==='explicit_gap'?'danger':s==='candidate'?'warning':s==='complete'?'success':'info'}
function courseStatus(s:string){return({passed:'成绩通过',recognized:'替代/认定',failed:'明确未通过',not_completed:'尚无完成证据',unknown:'证据未知'} as any)[s]||s||'未知'}
function courseTag(s:string):'success'|'danger'|'warning'|'info'{return ['passed','recognized'].includes(s)?'success':s==='failed'?'danger':s==='not_completed'?'warning':'info'}
onMounted(()=>load(props.majorId))
watch(()=>props.majorId,v=>load(v))
</script>

<style scoped>
.empty-plan{text-align:center;padding:60px}.filters{display:flex;gap:8px}.filters .el-input{width:210px}.filters .el-select{width:170px}.risk{color:#dc2626}.drawer-body{min-height:360px}.drawer-summary{margin:14px 0}.drawer-alert{margin-top:10px}.tab-label-with-help{display:inline-flex;align-items:center;gap:4px}.tab-help-icon{color:#64748b;cursor:help;font-size:14px}
</style>
