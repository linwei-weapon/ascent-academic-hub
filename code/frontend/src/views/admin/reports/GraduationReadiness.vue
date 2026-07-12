<template>
  <div>
    <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item><el-breadcrumb-item>毕业准备核查与课程保障</el-breadcrumb-item></el-breadcrumb>
    <h2 class="sa-page-title">毕业准备核查与课程保障</h2>
    <p class="sa-page-sub">面向教务处和学院定位毕业准备中的学生课程缺口，并核查阻塞课程的开课、师资、重修与替代资源。</p>
    <el-alert type="warning" :closable="false" show-icon title="本页是毕业审核准备工具，不是毕业审核结论" :description="definition.boundary" />
    <el-alert class="scope-alert" type="info" :closable="false" show-icon title="管理口径分为明确问题与数据候选" description="“明确未通过”来自已发布的不及格成绩，可进入核查名单；“到期缺证据候选”仅表示当前没有结果记录，可能包含未选、免修认定未接入或方案课程并非个人实际应修，不能直接认定为缺修。" />

    <div class="filters">
      <el-select v-model="draftStatus" clearable placeholder="全部学生"><el-option label="高年级重点核查" value="high_grade_action"/><el-option label="有必修课未通过" value="action_required"/><el-option label="到期缺证据候选（待核验）" value="verification_required"/><el-option label="当前未发现明显缺口" value="evidence_complete"/></el-select>
      <el-button type="primary" :loading="loading" @click="applyFilter">应用筛选</el-button><el-button :disabled="loading" @click="reset">重置</el-button>
      <span class="hint">选择条件后点击“应用筛选”，页面不会自动反复刷新</span>
    </div>

    <el-skeleton :loading="initialLoading" animated :rows="4">
      <div class="kpis"><div v-for="x in kpis" :key="x.label" class="kpi"><span>{{x.label}} <el-tooltip :content="x.help"><span class="help">?</span></el-tooltip></span><b>{{x.value}}</b><small>{{x.note}}</small></div></div>
    </el-skeleton>

    <div class="grid">
      <section class="sa-card" v-loading="loading"><div class="sa-card-title">各专业毕业准备核查概览 <span class="extra">表中均为去重学生人数，不是成绩条数</span></div>
        <el-table :data="data.majors" size="small" max-height="420"><el-table-column prop="major_name" label="专业" min-width="170" show-overflow-tooltip/><el-table-column prop="students" label="覆盖学生数" width="95"/><el-table-column label="平均必修完成率" width="125"><template #default="{row}">{{row.avg_completion_rate}}%</template></el-table-column><el-table-column prop="failed_students" label="有必修课未通过学生数" width="155"/><el-table-column prop="verification_students" label="有到期课程待核验学生数" width="170"/></el-table>
      </section>
      <section class="sa-card" v-loading="loading"><div class="sa-card-title">需要优先核查的必修课程 <span class="extra">数字表示涉及该课程的去重学生数</span></div>
        <el-table :data="data.courses" size="small" max-height="420"><el-table-column prop="course_name" label="课程" min-width="160" show-overflow-tooltip/><el-table-column prop="failed_students" label="明确未通过学生" width="120"/><el-table-column prop="major_count" label="涉及专业" width="80"/><el-table-column prop="lesson_count" label="教学班" width="70"/><el-table-column prop="teacher_count" label="教师" width="60"/><el-table-column label="保障优先级" width="95"><template #default="{row}"><el-tag :type="row.supply_priority==='高'?'danger':row.supply_priority==='中'?'warning':'info'">{{row.supply_priority}}</el-tag></template></el-table-column><el-table-column label="核查原因" min-width="180"><template #default="{row}">{{(row.supply_reasons||[]).join('；')||'常规观察'}}</template></el-table-column><el-table-column label="操作" width="105" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openSupply(row)">保障证据</el-button></template></el-table-column></el-table>
      </section>
    </div>

    <section class="sa-card" v-loading="loading"><div class="sa-card-title">学生核查名单 <span class="extra">分页只更新本表，不遮挡整个页面</span></div>
      <el-table :data="data.students" stripe><el-table-column prop="student_id" label="学号" width="130"/><el-table-column prop="display_name" label="姓名" width="90"/><el-table-column prop="major_name" label="专业" min-width="150"/><el-table-column prop="entry_grade" label="年级" width="70"/><el-table-column label="已完成必修/应修必修" width="155"><template #default="{row}">{{row.required_completed}} / {{row.required_courses}}</template></el-table-column><el-table-column label="必修完成率" width="145"><template #default="{row}"><el-progress :percentage="row.completion_rate" :stroke-width="8"/></template></el-table-column><el-table-column prop="explicit_required_failures" label="未通过必修课" width="105"/><el-table-column prop="due_required_gaps" label="到期待核验课程" width="115"/><el-table-column label="建议核查原因" width="150"><template #default="{row}"><el-tag :type="tagType(row.readiness_status)">{{statusName[row.readiness_status]}}</el-tag></template></el-table-column><el-table-column label="操作" width="90" fixed="right"><template #default="{row}"><el-button link type="primary" @click="student(row)">查看档案</el-button></template></el-table-column></el-table>
      <el-pagination v-if="data.total" v-model:current-page="page" :page-size="50" :total="data.total" layout="total, prev, pager, next" @current-change="load"/>
    </section>

    <section class="sa-card definition"><div class="sa-card-title">指标口径与管理动作</div><p><b>方案覆盖可核查学生：</b>已关联到培养方案且生成学生—课程状态的去重学生。管理用途是判断本专题覆盖面，不代表学生总数。</p><p><b>高年级明确未通过：</b>{{definition.high_grade_attention}} 管理动作是优先确认补考、重修、替代课程和开课资源。</p><p><b>全部年级明确未通过：</b>{{definition.action_required}} 管理动作是按专业和课程识别共性瓶颈。</p><p><b>到期缺证据候选：</b>{{definition.verification_required}} 该指标只用于补充数据核验，不直接形成学生处理结论。</p><p><b>必修完成率：</b>{{definition.completion_rate}}</p><p><b>课程保障优先级：</b>{{definition.supply_priority}}</p><p><b>统计单位：</b>{{definition.number_unit}}</p></section>

    <el-dialog v-model="supplyVisible" :title="supply.course?.courseName ? supply.course.courseName+'：课程保障证据' : '课程保障证据'" width="760px">
      <el-descriptions :column="3" border><el-descriptions-item label="明确未通过">{{supply.affected?.actionRequiredStudents||0}} 人</el-descriptions-item><el-descriptions-item label="缺证据候选">{{supply.affected?.verificationStudents||0}} 人</el-descriptions-item><el-descriptions-item label="涉及专业">{{supply.affected?.affectedMajors||0}} 个</el-descriptions-item><el-descriptions-item label="历史开课">{{supply.offerings?.length||0}} 个学期</el-descriptions-item><el-descriptions-item label="替代关系">{{supply.substitutions?.length||0}} 条</el-descriptions-item><el-descriptions-item label="未来开课计划">{{supply.availability?.hasFuturePlanEvidence?'已有证据':'暂无证据'}}</el-descriptions-item></el-descriptions>
      <el-alert class="dialog-alert" type="info" :closable="false" title="证据边界" :description="supply.boundary||'结合下一学期开课计划、教师容量、重修班和课程替代规则，确认是否需要增加课程资源。'"/>
      <el-table :data="supply.offerings||[]" size="small" max-height="250"><el-table-column prop="semesterId" label="学期" width="120"/><el-table-column prop="lessonCount" label="教学班" width="85"/><el-table-column prop="teacherCount" label="教师" width="75"/><el-table-column prop="capacity" label="容量" width="80"/><el-table-column prop="enrolled" label="已选人数" width="90"/><el-table-column prop="schedules" label="排课时段" min-width="180" show-overflow-tooltip/></el-table>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import{computed,onMounted,reactive,ref}from'vue';import{useRouter}from'vue-router';import{http}from'@/utils/http'
const router=useRouter(),loading=ref(false),initialLoading=ref(true),draftStatus=ref('high_grade_action'),status=ref('high_grade_action'),page=ref(1),requestId=ref(0),supplyVisible=ref(false)
const data=reactive<any>({summary:{},majors:[],courses:[],students:[],total:0}),definition=reactive<any>({})
const supply=reactive<any>({})
const statusName:any={action_required:'存在明确未通过课程',verification_required:'存在到期缺记录课程',evidence_complete:'当前未发现明显缺口'}
const kpis=computed(()=>[{label:'方案覆盖可核查学生',value:(data.summary.covered_students||0)+' 人',note:(data.summary.plan_count||0)+' 个培养方案；仅表示数据覆盖',help:'已关联培养方案并生成课程状态的去重学生人数，不是全校在籍学生数。'},{label:'高年级明确未通过',value:(data.summary.high_grade_attention_students||0)+' 人',note:'优先核查重修与开课保障',help:definition.high_grade_attention||''},{label:'全部年级明确未通过',value:(data.summary.action_required_students||0)+' 人',note:(data.summary.explicit_required_failures||0)+' 条学生－必修课记录',help:definition.action_required||'至少有一门必修课存在明确未通过成绩的去重学生。'},{label:'到期缺证据候选',value:(data.summary.verification_students||0)+' 人',note:'仅作数据核验，不认定缺修',help:definition.verification_required||''},{label:'未发现明确问题',value:(data.summary.evidence_complete_students||0)+' 人',note:'不等同毕业审核通过',help:definition.evidence_complete||''}])
function tagType(s:string){return s==='action_required'?'danger':s==='verification_required'?'warning':'success'}
function applyFilter(){status.value=draftStatus.value;page.value=1;load()}function reset(){draftStatus.value='high_grade_action';status.value='high_grade_action';page.value=1;load()}
async function load(){const id=++requestId.value;loading.value=true;try{const q=new URLSearchParams({limit:'50',offset:String((page.value-1)*50)});if(status.value)q.set('readiness',status.value);const r=await http.get<any>('/v2/topics/graduation-readiness?'+q);if(id!==requestId.value)return;Object.assign(data,r);Object.assign(definition,r.definition)}finally{if(id===requestId.value){loading.value=false;initialLoading.value=false}}}
function student(row:any){router.push({path:'/admin/student/'+row.student_id,query:{returnTo:'/admin/reports/graduation-readiness',returnLabel:'毕业准备核查与课程保障专题'}})}
async function openSupply(row:any){const r=await http.get<any>('/v2/curriculum/course-supply/'+encodeURIComponent(row.course_id));Object.assign(supply,r);supplyVisible.value=true}
onMounted(load)
</script>
<style scoped>.crumb{margin-bottom:8px}.filters{display:flex;gap:10px;align-items:center;margin:14px 0}.filters .el-select{width:220px}.hint{font-size:12px;color:#94a3b8}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px}.kpi span,.kpi small{display:block;color:#64748b}.kpi b{display:block;font-size:24px;margin:6px 0;color:#0f172a}.help{display:inline-flex!important;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#e2e8f0;color:#475569;font-size:11px;cursor:help}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.sa-card{margin-bottom:14px}.definition p{color:#475569;font-size:13px;line-height:1.8}.el-pagination{justify-content:flex-end;margin-top:12px}@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}</style>
