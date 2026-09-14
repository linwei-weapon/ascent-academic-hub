<template>
  <div>
    <div class="sa-head-row">
      <div><h2 class="sa-page-title">例外规则治理</h2><p class="sa-page-sub">草稿 → 提交 → 质量审核 → 校领导激活；激活前不参与合规计算</p></div>
      <el-button v-if="permissions.edit" type="primary" @click="dialog=true">新建变更单</el-button>
    </div>
    <el-alert title="权限分离" type="info" :closable="false" style="margin-bottom:12px"
      description="教务处/教研科创建并提交，质量办审核，校领导激活；全过程保留审计轨迹。" />
    <el-table :data="rows" stripe size="small" v-loading="loading">
      <el-table-column prop="change_id" label="#" width="60" />
      <el-table-column label="类型" width="120"><template #default="{row}">{{ typeName[row.rule_type] || row.rule_type }}</template></el-table-column>
      <el-table-column prop="reason" label="变更原因" min-width="180" />
      <el-table-column prop="created_by" label="创建人" width="110" />
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="statusType(row.status)" size="small">{{ statusName[row.status] || row.status }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="230"><template #default="{row}">
        <el-button link type="primary" @click="preview(row)">影响试算</el-button>
        <el-button v-if="permissions.edit && row.status==='draft'" link type="primary" @click="act(row,'submit')">提交</el-button>
        <template v-if="permissions.review && row.status==='submitted'">
          <el-button link type="success" @click="review(row,true)">通过</el-button><el-button link type="danger" @click="review(row,false)">驳回</el-button>
        </template>
        <el-button v-if="permissions.activate && row.status==='approved'" link type="danger" @click="act(row,'activate')">激活</el-button>
        <el-button link @click="detail(row)">详情</el-button>
      </template></el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建例外规则变更单" width="650px">
      <el-form label-width="100px">
        <el-form-item label="规则类型"><el-select v-model="form.ruleType" style="width:100%"><el-option label="课程替代" value="course_equivalence"/><el-option label="学分/免修认定" value="credit_recognition"/><el-option label="课程组" value="course_group"/></el-select></el-form-item>
        <el-form-item v-if="form.ruleType!=='credit_recognition'" label="培养方案"><el-select v-model="form.planKey" filterable style="width:100%" @change="resetDependent"><el-option v-for="p in options.plans" :key="p.majorId+'-'+p.grade" :label="`${p.majorName} · ${p.grade}级`" :value="p.majorId+'|'+p.grade" /></el-select></el-form-item>
        <template v-if="form.ruleType==='course_equivalence'">
          <el-form-item label="目标课程"><el-select v-model="form.targetCourseId" filterable style="width:100%"><el-option v-for="c in planCourses" :key="c.courseId" :label="`${c.courseName}（${c.courseId}）`" :value="c.courseId" /></el-select></el-form-item>
          <el-form-item label="替代课程"><el-select v-model="form.substituteCourseId" filterable allow-create style="width:100%"><el-option v-for="c in options.courses" :key="c.majorId+c.courseId" :label="`${c.courseName}（${c.courseId}）`" :value="c.courseId" /></el-select></el-form-item>
        </template>
        <template v-else-if="form.ruleType==='credit_recognition'">
          <el-form-item label="学生"><el-select v-model="form.studentId" filterable style="width:100%"><el-option v-for="s in options.students" :key="s.studentId" :label="`${s.studentId} · ${s.name} · ${s.grade}级`" :value="s.studentId" /></el-select></el-form-item>
          <el-form-item label="认定类型"><el-select v-model="form.recognitionType" style="width:100%"><el-option v-for="v in ['免修','转学分','跨专业认定','其他']" :key="v" :label="v" :value="v" /></el-select></el-form-item>
          <el-form-item label="目标课程"><el-select v-model="form.targetCourseId" clearable filterable style="width:100%"><el-option v-for="c in studentCourses" :key="c.courseId" :label="`${c.courseName}（${c.courseId}）`" :value="c.courseId" /></el-select></el-form-item>
          <el-form-item label="认定学分"><el-input-number v-model="form.credits" :min="0.5" :max="20" :step="0.5" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="课程组编号"><el-input v-model="form.groupId" /></el-form-item><el-form-item label="课程组名称"><el-input v-model="form.groupName" /></el-form-item>
          <el-form-item label="所属模块"><el-select v-model="form.module" style="width:100%"><el-option v-for="m in planModules" :key="m.module" :label="m.module" :value="m.module" /></el-select></el-form-item>
          <el-form-item label="组内课程"><el-select v-model="form.courseIds" multiple filterable style="width:100%"><el-option v-for="c in planCourses" :key="c.courseId" :label="`${c.courseName}（${c.courseId}）`" :value="c.courseId" /></el-select></el-form-item>
          <el-form-item label="最低门数"><el-input-number v-model="form.minCourses" :min="1" /></el-form-item><el-form-item label="最低学分"><el-input-number v-model="form.minCredits" :min="0" :step="0.5" /></el-form-item>
        </template>
        <el-form-item label="审批单号"><el-input v-model="form.approvalRef" placeholder="课程替代和学分认定必填" /></el-form-item>
        <el-form-item label="变更原因"><el-input v-model="form.reason" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" @click="create">保存草稿</el-button></template>
    </el-dialog>
    <el-dialog v-model="detailDialog" title="变更详情与审计轨迹" width="720px">
      <pre class="payload">{{ JSON.stringify(current?.payload, null, 2) }}</pre>
      <el-timeline><el-timeline-item v-for="a in current?.auditTrail || []" :key="a.operated_at+a.action" :timestamp="a.operated_at">{{ a.action }} · {{ a.operator }}<span v-if="a.detail"> · {{ a.detail }}</span></el-timeline-item></el-timeline>
    </el-dialog>
    <el-dialog v-model="previewDialog" title="激活前影响试算" width="520px">
      <el-alert title="以下为估算结果，规则尚未激活" type="warning" :closable="false" style="margin-bottom:14px" />
      <el-descriptions :column="1" border>
        <el-descriptions-item label="可能受影响学生">{{ previewData.impactedStudents }} 人</el-descriptions-item>
        <el-descriptions-item label="预计累计学分变化">{{ previewData.aggregateCreditDelta }} 学分</el-descriptions-item>
        <el-descriptions-item label="计算说明">{{ previewData.detail }}</el-descriptions-item>
        <el-descriptions-item label="冲突检查"><el-tag :type="previewData.conflict?'danger':'success'">{{ previewData.conflict || '未发现冲突' }}</el-tag></el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'
const rows=ref<any[]>([]), loading=ref(false), dialog=ref(false), detailDialog=ref(false), previewDialog=ref(false), current=ref<any>()
const previewData=reactive<any>({})
const permissions=reactive({edit:false,review:false,activate:false,audit:false})
const options=reactive<any>({plans:[],courses:[],students:[],modules:[]})
const form=reactive<any>({ruleType:'course_equivalence',planKey:'',targetCourseId:'',substituteCourseId:'',studentId:'',recognitionType:'免修',credits:2,groupId:'',groupName:'',module:'',courseIds:[],minCourses:1,minCredits:0,approvalRef:'',reason:''})
const typeName:any={course_equivalence:'课程替代',credit_recognition:'学分/免修认定',course_group:'课程组'}
const statusName:any={draft:'草稿',submitted:'待审核',approved:'审核通过',rejected:'已驳回',activated:'已激活'}
const planParts=computed(()=>form.planKey.split('|')), planCourses=computed(()=>options.courses.filter((c:any)=>c.majorId===planParts.value[0]&&String(c.grade)===planParts.value[1])), planModules=computed(()=>options.modules.filter((m:any)=>m.majorId===planParts.value[0]&&String(m.grade)===planParts.value[1]))
const selectedStudent=computed(()=>options.students.find((s:any)=>s.studentId===form.studentId)), studentCourses=computed(()=>selectedStudent.value?options.courses.filter((c:any)=>c.majorId===selectedStudent.value.majorId&&String(c.grade)===String(selectedStudent.value.grade)):[])
function resetDependent(){form.targetCourseId='';form.module='';form.courseIds=[]}
function statusType(s:string){return s==='activated'?'success':s==='rejected'?'danger':s==='approved'?'warning':'info'}
async function load(){loading.value=true;try{const [d,o]=await Promise.all([http.get<any>('/admin/curriculum/rule-changes'),http.get<any>('/admin/curriculum/rule-options')]);rows.value=d.list||[];Object.assign(permissions,d.permissions||{});Object.assign(options,o||{})}finally{loading.value=false}}
async function create(){const [majorId,grade]=planParts.value;let payload:any
  if(form.ruleType==='course_equivalence')payload={majorId,grade,targetCourseId:form.targetCourseId,substituteCourseId:form.substituteCourseId,approvalRef:form.approvalRef}
  else if(form.ruleType==='credit_recognition')payload={studentId:form.studentId,recognitionType:form.recognitionType,targetCourseId:form.targetCourseId||undefined,credits:form.credits,approvalRef:form.approvalRef}
  else payload={groupId:form.groupId,majorId,grade,groupName:form.groupName,module:form.module,minCourses:form.minCourses,minCredits:form.minCredits,courseIds:form.courseIds}
  await http.post('/admin/curriculum/rule-changes',{ruleType:form.ruleType,payload,reason:form.reason});dialog.value=false;form.reason='';await load()}
async function act(row:any,action:string){await ElMessageBox.confirm(action==='activate'?'激活后将立即参与学生合规计算，确认继续？':'确认提交质量审核？','确认');await http.post(`/admin/curriculum/rule-changes/${row.change_id}/${action}`,{});await load()}
async function review(row:any,approved:boolean){const r=await ElMessageBox.prompt('请输入审核意见','质量审核',{inputValue:approved?'审核通过':'资料或规则需修订'});await http.post(`/admin/curriculum/rule-changes/${row.change_id}/review`,{approved,comment:r.value});await load()}
async function detail(row:any){current.value=await http.get(`/admin/curriculum/rule-changes/${row.change_id}`);detailDialog.value=true}
async function preview(row:any){Object.assign(previewData,await http.get(`/admin/curriculum/rule-changes/${row.change_id}/preview`));previewDialog.value=true}
onMounted(load)
</script>
<style scoped>.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start}.payload{background:#f8fafc;padding:12px;border-radius:6px;white-space:pre-wrap}</style>
