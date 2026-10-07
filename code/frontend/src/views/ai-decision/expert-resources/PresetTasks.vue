<template>
  <section class="preset-tasks">
    <header class="heading"><div><h2>专家预设任务</h2><p>先保存分析条件并试跑，再人工正式生成；启用自动运行时补充周期、窗口和服务授权。</p></div><el-button type="primary" :disabled="busy||!briefingTasks.length" @click="create">新增预设</el-button></header>
    <p v-if="error" class="notice error" role="alert">{{ error }} <el-button link @click="load">刷新</el-button></p>
    <p class="notice">首期开放课程首修观察 C-BRIEF-01。这里维护业务问题与执行周期；服务预算及授权在“后台处理服务”维护。</p>
    <p v-if="!briefingTasks.length&&!loading" class="muted">该专家当前没有已登记的预设简报任务。其他业务能力可在专家问策中按实际发布状态使用。</p>
    <el-empty v-if="!items.length&&!loading" description="还没有预设任务" :image-size="60" />
    <article v-for="preset in items" :key="preset.id" class="preset-card">
      <div class="card-title"><div><h3>{{ preset.name }}</h3><p>{{ preset.question }}</p><small>{{ scopeLabel(preset) }} · {{ preset.taskId }} · 修订 {{ preset.revision }}</small></div><el-tag effect="plain" :type="preset.enabled?'success':'info'">{{ preset.enabled?'自动运行已启用':preset.state==='needs_validation'?'分析条件待验证':'自动运行未启用' }}</el-tag></div>
      <div class="status-line"><span>试跑：{{ preset.trialValid?'当前条件已验证':preset.trialExecutionId?'已有试跑，请核对适用性':'尚未试跑' }}</span><span v-if="preset.latestExecution">最近执行：{{ stateLabel(preset.latestExecution.state) }}</span><span v-if="preset.latestExecution?.explanationState">解释：{{ explanationStateLabel(preset.latestExecution.explanationState) }}</span></div>
      <p v-if="preset.automaticPauseReason||preset.invalidReason||preset.reason" class="warning">{{ preset.automaticPauseReason||preset.invalidReason||preset.reason }}</p>
      <div class="buttons"><el-button :disabled="busy" @click="edit(preset)">编辑</el-button><el-button :disabled="busy" @click="action(preset,'trial')">试跑候选</el-button><el-button type="primary" plain :disabled="busy" @click="action(preset,'run')">人工正式生成</el-button><el-button v-if="!preset.enabled" :disabled="busy" @click="prepareEnable(preset)">启用自动并生成首期</el-button><el-button v-else :disabled="busy" @click="action(preset,'pause')">停用自动</el-button><el-button :disabled="busy" @click="openRecords(preset)">执行记录</el-button><el-button :disabled="busy" @click="prepareCorrection(preset)">修正历史简报</el-button><el-button v-if="preset.currentPublicationId" link @click="router.push({path:'/admin/reports/decision',query:{publicationId:preset.currentPublicationId}})">查看正式简报</el-button><el-button type="danger" link :disabled="busy||preset.enabled||preset.canDelete===false" @click="remove(preset)">删除</el-button></div>
    </article>
    <el-dialog v-model="editorOpen" :title="editing?'编辑预设任务':'新增预设任务'" width="min(760px,95vw)" append-to-body :close-on-click-modal="false">
      <p v-if="editorError" class="notice error" role="alert">{{ editorError }}</p>
      <el-form label-position="top" :disabled="busy||!!pendingEnable">
        <div class="form-grid"><el-form-item label="业务名称（必填）"><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="预设编号（必填，创建后固定）"><el-input v-model="form.id" :disabled="!!editing" placeholder="例如 C-BRIEF-01" maxlength="100" /></el-form-item></div>
        <el-form-item label="要持续关注的问题（必填）"><el-input v-model="form.question" type="textarea" :rows="3" maxlength="1500" /></el-form-item>
        <el-form-item label="业务任务（必填）"><el-select v-model="form.taskId" @change="form.input={}"><el-option v-for="task in briefingTasks" :key="task.taskId" :value="task.taskId" :label="task.title" :disabled="!task.available" /></el-select></el-form-item>
        <div class="form-grid"><el-form-item label="业务学期（必填）"><el-select v-model="form.input.semester_id" filterable placeholder="选择有真实数据的学期"><el-option v-for="item in options.semesters" :key="item.id" :value="item.id" :label="item.name" /></el-select></el-form-item><el-form-item label="开课院系（留空为全校，需全校权限）"><el-select v-model="form.input.college_id" clearable filterable placeholder="授权开课院系"><el-option v-for="item in options.colleges" :key="item.id" :value="item.id" :label="item.name" /></el-select></el-form-item></div>
        <p class="muted">固定按开课院系统计全部课程，不设置单课筛选。业务学期、范围或方法变化后，需要重新试跑；显示名称和周期调整保留同条件事实。</p>
        <details class="automatic-fields" :open="requireAutomatic"><summary>自动运行设置（人工试跑与正式生成可留空）</summary>
          <el-form-item label="服务委托授权（启用自动时必填）"><el-select v-model="form.grantId" clearable placeholder="选择有效授权"><el-option v-for="grant in activeGrants" :key="grant.grantId||grant.id" :value="grant.grantId||grant.id" :label="`${grant.name||grant.grantId||grant.id} · 至${date(grant.validUntil||grant.expiresAt)}`" /></el-select><el-button link @click="router.push('/admin/system/background-processing')">管理授权</el-button></el-form-item>
          <el-form-item label="执行周期（启用自动时必填）"><el-radio-group v-model="scheduleKind"><el-radio value="weekly">每周</el-radio><el-radio value="test_interval">验证用途：每5分钟</el-radio></el-radio-group></el-form-item>
          <div v-if="scheduleKind==='weekly'" class="form-grid"><el-form-item label="星期"><el-select v-model="weekday"><el-option v-for="(label,index) in weekdays" :key="index" :value="index" :label="label" /></el-select></el-form-item><el-form-item label="时间（Asia/Shanghai）"><el-time-picker v-model="time" format="HH:mm" value-format="HH:mm" /></el-form-item></div>
          <p v-else class="warning">短周期仅用于真实到期验证，完成后停用并恢复正式每周计划；不将验证周期当正式业务频率。</p>
          <div class="form-grid"><el-form-item label="生效开始（启用自动时必填）"><el-date-picker v-model="windowStart" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item><el-form-item label="生效结束（启用自动时必填）"><el-date-picker v-model="windowEnd" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item></div>
        </details>
      </el-form>
      <template #footer><el-button :disabled="busy" @click="editorOpen=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!basicValid" @click="save">{{ pendingEnable?'按原请求确认自动启用':requireAutomatic?'保存设置并启用自动首期':'保存预设草稿' }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="correctionOpen" title="重新生成修正结果" width="min(650px,94vw)" append-to-body><p>以当前真实数据重新运行，并关联被更正的同任务、同学期及同学院发布；原事实和撤回记录保留。</p><el-select v-model="correctionPublicationId" placeholder="选择需要更正的历史发布" style="width:100%"><el-option v-for="p in correctionPublications" :key="p.publicationId" :value="p.publicationId" :label="`${p.name||p.publicationId} · ${date(p.publishedAt||p.createdAt)} · ${p.status==='withdrawn'?'已撤回':'原发布'}`" /></el-select><p v-if="correctionError" class="notice error">{{ correctionError }}</p><el-empty v-if="!correctionPublications.length&&!busy" description="本范围没有可关联的历史发布" :image-size="50" /><template #footer><el-button :disabled="busy" @click="correctionOpen=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!correctionPublicationId" @click="runCorrection">重新查询并正式生成修正</el-button></template></el-dialog>
    <el-drawer v-model="recordsOpen" :title="`执行记录 · ${recordPreset?.name||''}`" size="min(940px,96vw)">
      <p v-if="recordsError" class="notice error">{{ recordsError }}</p><el-button :loading="recordsLoading" @click="loadRecords">刷新实际状态</el-button>
      <article v-for="(run,index) in executions" :key="run.id||run.executionId" class="execution-record"><div class="card-title"><div><b>{{ stateLabel(run.state) }}</b><p>{{ run.summary }}</p><small>{{ run.triggerType||run.purpose||'当前身份执行' }} · {{ date(run.createdAt) }}</small></div><el-tag v-if="run.workerFinished===false" type="info">工作进程尚未结束</el-tag></div><p v-if="run.factsState||run.explanationState" class="muted">事实：{{ stateLabel(run.factsState||run.state) }} · 解释：{{ explanationStateLabel(run.explanationState) }}</p><p v-if="run.failureCode" class="error">{{ run.failureCode }}</p><details v-if="run.outcome" :open="index===0"><summary>查看本次保存结果与依据</summary><RunResult :run="run.outcome" :options="options" :preset-id="run.purpose==='briefing_trial'?recordPreset?.id:undefined" :publication-id="run.outcome.result?.publicationId" mode="test" /></details><el-button v-if="run.publicationId" link @click="router.push({path:'/admin/reports/decision',query:{publicationId:run.publicationId}})">查看正式结果</el-button></article>
      <el-pagination layout="prev, pager, next" :page-size="20" :total="recordTotal" :current-page="recordPage" @current-change="recordPage=$event;loadRecords()" />
    </el-drawer>
  </section>
</template>
<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,reactive,ref,watch} from 'vue'
import {useRouter} from 'vue-router'
import {ElMessageBox} from 'element-plus'
import {expertResourcesApi as api,explanationStateLabel,type BriefingPreset,type BriefingPublication} from '@/api/aiDecision/expertResources'
import type {BusinessTask,ExpertExecution,ResourceOptions} from '@/types/expertResources'
import RunResult from './RunResult.vue'
const props=defineProps<{expertId:string}>(),router=useRouter(),items=ref<BriefingPreset[]>([]),tasks=ref<BusinessTask[]>([]),options=ref<ResourceOptions>({plans:[],semesters:[],colleges:[]}),grants=ref<Record<string,any>[]>([]),loading=ref(false),busy=ref(false),error=ref(''),editorError=ref(''),editing=ref<BriefingPreset|null>(null),editorOpen=ref(false),requireAutomatic=ref(false)
const form=reactive({id:'C-BRIEF-01',name:'课程首修观察',question:'当前学期哪些已接入课程的首修通过率低于同范围参照，需要进一步核对？',taskId:'C-PERFORMANCE',input:{} as Record<string,any>,grantId:''}),scheduleKind=ref<'weekly'|'test_interval'>('weekly'),weekday=ref(0),time=ref('09:00'),windowStart=ref(''),windowEnd=ref(''),weekdays=['周一','周二','周三','周四','周五','周六','周日']
const recordsOpen=ref(false),recordPreset=ref<BriefingPreset|null>(null),executions=ref<ExpertExecution[]>([]),recordTotal=ref(0),recordPage=ref(1),recordsLoading=ref(false),recordsError=ref('')
const correctionOpen=ref(false),correctionPreset=ref<BriefingPreset|null>(null),correctionPublications=ref<BriefingPublication[]>([]),correctionPublicationId=ref(''),correctionError=ref('')
const pendingEnable=ref<BriefingPreset|null>(null)
let refreshedExecution='';let epoch=0,recordRequest=0,recordTimer:ReturnType<typeof setTimeout>|undefined;const operationIds=new Map<string,string>()
function operationId(key:string){let id=operationIds.get(key);if(!id){id=crypto.randomUUID();operationIds.set(key,id)}return id}
const briefingTasks=computed(()=>tasks.value.filter(t=>t.expertId===props.expertId&&t.taskId==='C-PERFORMANCE')),activeGrants=computed(()=>grants.value.filter(g=>(g.state==='active'||g.status==='active')&&new Date(g.validUntil||g.expiresAt).getTime()>Date.now())),basicValid=computed(()=>!!form.id.trim()&&!!form.name.trim()&&!!form.question.trim()&&briefingTasks.value.some(t=>t.taskId===form.taskId)&&!!form.input.semester_id)
function date(value?:string){if(!value)return '未记录';const d=new Date(value);return Number.isNaN(d.getTime())?value:d.toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}
function stateLabel(s:string){return ({queued:'等待执行',running:'执行中',completed:'已完成',partial:'部分完成',blocked:'条件未满足',failed:'执行失败',cancelled:'已取消',needs_input:'需要输入'} as Record<string,string>)[s]||s}
function scopeLabel(p:BriefingPreset){return `${options.value.semesters.find(s=>String(s.id)===String(p.input.semester_id))?.name||p.input.semester_id} · ${options.value.colleges.find(c=>String(c.id)===String(p.input.college_id))?.name||'授权全范围'}`}
async function load(){const current=++epoch;loading.value=true;error.value='';const values=await Promise.allSettled([api.presets(props.expertId),api.tasks(),api.options(),api.processing()]);if(current!==epoch)return;if(values[0].status==='fulfilled')items.value=values[0].value.items;else error.value=(values[0].reason as Error).message;if(values[1].status==='fulfilled')tasks.value=values[1].value.items;if(values[2].status==='fulfilled')options.value=values[2].value;if(values[3].status==='fulfilled')grants.value=values[3].value.grants||[];loading.value=false}
function create(){editing.value=null;requireAutomatic.value=false;Object.assign(form,{id:'C-BRIEF-01',name:'课程首修观察',question:'当前学期哪些已接入课程的首修通过率低于同范围参照，需要进一步核对？',taskId:'C-PERFORMANCE',input:{},grantId:''});windowStart.value='';windowEnd.value='';scheduleKind.value='weekly';weekday.value=0;time.value='09:00';editorError.value='';editorOpen.value=true}
function edit(p:BriefingPreset){editing.value=p;requireAutomatic.value=false;Object.assign(form,{id:p.id,name:p.name,question:p.question,taskId:p.taskId,input:{...p.input},grantId:p.grantId||''});scheduleKind.value=p.schedule?.kind||'weekly';weekday.value=p.schedule?.weekday??0;time.value=p.schedule?.time||'09:00';windowStart.value=p.activeWindow?.start||'';windowEnd.value=p.activeWindow?.end||'';editorError.value='';editorOpen.value=true}
function prepareEnable(p:BriefingPreset){if(!p.trialValid){error.value='当前分析条件尚未验证，请先试跑候选。自动首期与人工正式生成都使用当前条件的有效试跑。';return}edit(p);requireAutomatic.value=true}
async function save(){
  if(!basicValid.value)return;editorError.value=''
  if(pendingEnable.value){busy.value=true;const saved=pendingEnable.value,key=`${saved.id}/enable/${saved.revision}`;try{await api.presetAction(saved.id,'enable',saved.revision,operationId(key));operationIds.delete(key);pendingEnable.value=null;editorOpen.value=false;await load()}catch(e){editorError.value=`原自动启用尚未确认：${(e as Error).message}`}finally{busy.value=false}return}
  if(requireAutomatic.value&&(!form.grantId||!windowStart.value||!windowEnd.value||(scheduleKind.value==='weekly'&&!time.value))){editorError.value='启用自动运行需有效授权、周期及生效起止时间。';return}
  if(windowStart.value&&windowEnd.value&&new Date(windowEnd.value)<=new Date(windowStart.value)){editorError.value='生效结束必须晚于开始。';return}
  busy.value=true
  const body={id:form.id,name:form.name,question:form.question,expertId:props.expertId,taskId:form.taskId,input:{semester_id:String(form.input.semester_id),college_id:String(form.input.college_id||''),course_id:''},scope:form.input.college_id?{type:'college',collegeIds:[String(form.input.college_id)]}:{type:'all',collegeIds:[]},collegeMeaning:'course_opening',serviceId:'expert-resources',grantId:form.grantId||null,schedule:(windowStart.value||windowEnd.value||requireAutomatic.value)?scheduleKind.value==='weekly'?{kind:'weekly',weekday:weekday.value,time:time.value,timezone:'Asia/Shanghai'}:{kind:'test_interval',intervalMinutes:5,timezone:'Asia/Shanghai'}:null,activeWindow:windowStart.value&&windowEnd.value?{start:windowStart.value,end:windowEnd.value}:null}
  try{const saved=editing.value?await api.savePreset(editing.value.id,{...body,expectedRevision:editing.value.revision}):await api.createPreset(body);editing.value=saved;if(requireAutomatic.value){pendingEnable.value=saved;const key=`${saved.id}/enable/${saved.revision}`;await api.presetAction(saved.id,'enable',saved.revision,operationId(key));operationIds.delete(key);pendingEnable.value=null}editorOpen.value=false;await load()}catch(e){editorError.value=(e as Error).message;if(pendingEnable.value){try{const list=await api.presets(props.expertId),actual=list.items.find(p=>p.id===pendingEnable.value?.id);if(actual){editing.value=actual;pendingEnable.value=null;if(actual.enabled){editorOpen.value=false;await load()}else editorError.value+='。服务器确认自动尚未启用，请修正设置后再试。'}}catch{/* retain original request until the server can confirm its state */}}}finally{busy.value=false}
}
async function action(p:BriefingPreset,a:'trial'|'run'|'enable'|'pause',replace?:string){
  busy.value=true;error.value='';const key=`${p.id}/${a}/${p.revision}/${replace||''}`
  try{await api.presetAction(p.id,a,p.revision,operationId(key),replace);operationIds.delete(key);await load();if(a==='trial'||a==='run'||a==='enable')await openRecords(items.value.find(item=>item.id===p.id)||p);return true}catch(e){error.value=`${(e as Error).message}。若响应未确认，请刷新记录核对原操作。`;return false}finally{busy.value=false}
}
async function prepareCorrection(p:BriefingPreset){correctionPreset.value=p;correctionPublicationId.value='';correctionError.value='';correctionPublications.value=[];correctionOpen.value=true;busy.value=true;try{const values=await api.publications({semesterId:p.input.semester_id,collegeId:p.input.college_id,history:true,limit:100});correctionPublications.value=values.items.filter(x=>x.presetId===p.id);if(values.total>100)correctionError.value='本次列出最近100个发布，请按学期和学院缩小范围后再核对。'}catch(e){correctionError.value=(e as Error).message}finally{busy.value=false}}
async function runCorrection(){if(!correctionPreset.value||!correctionPublicationId.value)return;if(await action(correctionPreset.value,'run',correctionPublicationId.value))correctionOpen.value=false;else correctionError.value=error.value}
async function remove(p:BriefingPreset){try{await ElMessageBox.confirm(`删除预设“${p.name}”？存在有效引用或活动执行时，服务端会拒绝。`,'删除预设',{type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'});busy.value=true;await api.removePreset(p.id,p.revision);await load()}catch(e){if(e!=='cancel'&&e!=='close')error.value=(e as Error).message}finally{busy.value=false}}
async function openRecords(p:BriefingPreset){recordPreset.value=p;recordPage.value=1;executions.value=[];refreshedExecution='';recordsOpen.value=true;await loadRecords()}
async function loadRecords(){
  if(!recordPreset.value)return
  clearTimeout(recordTimer)
  const request=++recordRequest,current=epoch
  recordsLoading.value=true;recordsError.value=''
  try{
    const value=await api.presetExecutions(recordPreset.value.id,(recordPage.value-1)*20,20)
    if(request!==recordRequest||current!==epoch)return
    executions.value=value.items;recordTotal.value=value.total??value.items.length
    const latest=value.items[0],latestId=latest?.executionId||latest?.id
    if(latest&&latestId&&!['queued','running'].includes(latest.state)&&latest.workerFinished!==false&&latestId!==refreshedExecution){
      const actual=await api.presets(props.expertId)
      if(request!==recordRequest||current!==epoch)return
      items.value=actual.items
      recordPreset.value=actual.items.find(p=>p.id===recordPreset.value?.id)||recordPreset.value
      refreshedExecution=latestId
    }
    if(recordsOpen.value&&value.items.some(x=>['queued','running'].includes(x.state)||x.workerFinished===false))recordTimer=setTimeout(()=>void loadRecords(),1800)
  }catch(e){if(request===recordRequest)recordsError.value=(e as Error).message}
  finally{if(request===recordRequest)recordsLoading.value=false}
}
watch(()=>props.expertId,()=>{editorOpen.value=false;recordsOpen.value=false;void load()});watch(recordsOpen,open=>{if(!open){clearTimeout(recordTimer);recordRequest++}})
onMounted(load);onBeforeUnmount(()=>{epoch++;recordRequest++;clearTimeout(recordTimer)})
</script>
<style scoped>
.preset-tasks{color:#324965}.heading,.card-title{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.heading h2{font-size:17px;margin:0 0 10px}.heading p,.card-title p{font-size:13px;color:#708198;line-height:1.8;margin:6px 0 10px}.preset-card{border:1px solid #e0e7ef;border-radius:8px;padding:19px;margin:16px 0;background:white}.preset-card h3{font-size:16px;margin:0}.card-title small{color:#8190a4;font-size:11px}.buttons,.status-line{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}.buttons>.el-button{margin:0}.status-line{font-size:12px;color:#6b7e96}.notice{background:#f4f7fb;border-radius:6px;padding:13px;line-height:1.8;font-size:13px}.error{color:#ac3542;background:#fff2f3}.warning{color:#96712b;line-height:1.8;font-size:12px}.muted{font-size:12px;color:#7c8ba0;line-height:1.8}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.form-grid .el-select,.form-grid .el-date-editor{width:100%}.automatic-fields{border-top:1px solid #e5ecf3;padding-top:15px;margin-top:20px}.automatic-fields summary{cursor:pointer;margin-bottom:16px;font-size:13px}.execution-record{border:1px solid #e0e7ef;border-radius:7px;padding:16px;margin:18px 0}@media(max-width:650px){.heading,.card-title{flex-wrap:wrap}.form-grid{grid-template-columns:1fr}.buttons{gap:8px}}
</style>
