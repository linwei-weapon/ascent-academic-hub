<template>
  <div class="scheme-page">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">分析方案管理</h2>
        <p class="sa-page-sub">把产品标准管理方法配置为学校方案，经过数据检查和影响预览后发布生效。</p>
      </div>
      <div class="head-actions">
        <input ref="fileInput" class="hidden-file" type="file" accept=".json,application/json" @change="importPackage" />
        <el-button @click="fileInput?.click()">导入方案包</el-button>
        <el-button @click="$router.push('/admin/settings')">
          模型接入：{{ data.llm?.ready ? '已就绪' : '未就绪' }}
        </el-button>
        <el-button type="primary" @click="$router.push('/admin/reports/decision')">查看实际运行结果</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="boundary-alert"
      :title="data.boundary || '学校方案不改变正式指标和数据权限。'" />

    <div v-if="error" class="load-error">
      <el-result icon="warning" title="分析方案暂时无法加载" :sub-title="error">
        <template #extra><el-button type="primary" @click="load">重新加载</el-button></template>
      </el-result>
    </div>

    <template v-else>
      <div v-if="initialLoading" class="sa-card">
        <el-skeleton animated :rows="8" />
        <p class="loading-copy">正在核对产品模板、学校版本、数据就绪状态和适用角色…</p>
      </div>

      <template v-else>
        <div class="summary-grid">
          <button v-for="card in cards" :key="card.key" type="button"
            :class="{active:activeCard===card.key}" @click="selectCard(card.key)">
            <span>{{ card.label }} <el-tooltip :content="card.help"><el-icon><InfoFilled /></el-icon></el-tooltip></span>
            <b>{{ card.value }}</b>
            <small>{{ card.action }}</small>
          </button>
        </div>

        <div v-if="loading" class="updating-bar">正在更新方案状态，当前结果暂时保留…</div>

        <el-tabs v-model="activeTab" class="scheme-tabs">
          <el-tab-pane label="正在使用" name="active">
            <div class="template-grid">
              <article v-for="skill in filteredSkills" :key="skill.skill_id" class="template-card">
                <div class="template-head">
                  <div>
                    <span class="template-label">{{ skill.active_scheme ? '学校方案' : '产品标准方案' }}</span>
                    <h3>{{ skill.active_scheme?.scheme_name || skill.name }}</h3>
                  </div>
                  <el-tag :type="skill.active_scheme ? 'success' : 'info'" effect="plain">
                    {{ skill.config_version === 'product_default' ? '产品默认' : skill.config_version }}
                  </el-tag>
                </div>
                <p class="management-question">{{ skill.management_question }}</p>
                <div class="template-state">
                  <span><i :class="skill.data_readiness?.ready ? 'ok' : 'bad'"></i>
                    {{ skill.data_readiness?.ready ? '数据已就绪' : `缺少 ${skill.data_readiness?.missing_required?.length || 0} 项必需数据` }}
                  </span>
                  <span>适用 {{ roleSummary(skill.active_scheme?.roleIds || data.roleIds) }}</span>
                </div>
                <div class="template-actions">
                  <el-button @click="openDetail(skill)">查看方案</el-button>
                  <el-button type="primary" @click="openEditor(skill)">
                    {{ skill.active_scheme ? '调整学校方案' : '配置学校方案' }}
                  </el-button>
                  <el-button v-if="skill.active_scheme" type="danger" plain @click="retireActive(skill)">停用</el-button>
                </div>
              </article>
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`草稿与发布（${draftRows.length}）`" name="drafts">
            <div class="sa-card table-card">
              <DataTable :columns="draftColumns" :data="draftRows" storage-key="system:analysis-scheme-drafts"
                :max-business-columns="6" :config-version="1" pagination :default-page-size="10"
                size="small" stripe empty-text="暂无待发布草稿；可从“正在使用”基于产品模板创建">
                <template #col-scheme="{row}">
                  <div class="main-cell">{{ row.scheme_name }}</div>
                  <div class="sub-cell">{{ row.skill_name }} · {{ row.version_no }}</div>
                </template>
                <template #col-test_status="{row}">
                  <el-tag size="small" effect="plain" :type="testTag(row.test_status)">
                    {{ testLabel(row.test_status) }}
                  </el-tag>
                </template>
                <template #col-roleIds="{row}">{{ roleSummary(row.roleIds) }}</template>
                <template #col-action="{row}">
                  <div class="row-actions">
                    <el-button link @click="openEditor(skillOf(row.skill_id), row)">编辑</el-button>
                    <el-button link type="warning" :loading="testingId===row.config_id" @click="testDraft(row)">检查</el-button>
                    <el-button link type="primary" :disabled="row.test_status!=='passed'" @click="publishDraft(row)">发布</el-button>
                  </div>
                </template>
              </DataTable>
            </div>
          </el-tab-pane>

          <el-tab-pane label="版本与变更" name="history">
            <div class="sa-card table-card">
              <DataTable :columns="historyColumns" :data="historyRows" storage-key="system:analysis-scheme-history"
                :max-business-columns="7" :config-version="1" pagination :default-page-size="10"
                size="small" stripe empty-text="尚无学校方案版本，当前全部使用产品标准方案">
                <template #col-scheme="{row}">
                  <div class="main-cell">{{ row.scheme_name }}</div>
                  <div class="sub-cell">{{ row.skill_name }} · {{ row.version_no }}</div>
                </template>
                <template #col-status="{row}">
                  <el-tag size="small" effect="plain" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
                </template>
                <template #col-roleIds="{row}">{{ roleSummary(row.roleIds) }}</template>
                <template #col-action="{row}">
                  <div class="row-actions">
                    <el-button link @click="exportPackage(row)">导出</el-button>
                    <el-button v-if="row.status!=='draft'" link type="warning" @click="rollback(row)">基于此版本回滚</el-button>
                  </div>
                </template>
              </DataTable>
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </template>

    <el-drawer v-model="detailVisible" :title="detailSkill?.name || '方案详情'" size="660px">
      <template v-if="detailSkill">
        <section class="detail-section">
          <h3>要解决的管理问题</h3>
          <p>{{ detailSkill.management_question }}</p>
          <p class="muted">{{ detailSkill.description }}</p>
        </section>
        <section class="detail-section">
          <h3>当前采用方式</h3>
          <div class="fact-grid">
            <div><span>配置来源</span><b>{{ detailSkill.active_scheme ? '学校已发布方案' : '产品标准方案' }}</b></div>
            <div><span>生效版本</span><b>{{ detailSkill.config_version }}</b></div>
            <div><span>数据状态</span><b>{{ detailSkill.data_readiness?.ready ? '已就绪' : '存在缺项' }}</b></div>
            <div><span>适用角色</span><b>{{ roleSummary(detailSkill.active_scheme?.roleIds || data.roleIds) }}</b></div>
          </div>
        </section>
        <section class="detail-section">
          <h3>管理参数</h3>
          <div v-for="key in boundKeys(detailSkill)" :key="key" class="parameter-row">
            <div><b>{{ fieldMeta(key).label }}</b><span>{{ fieldMeta(key).meaning }}</span></div>
            <div><strong>{{ fmt(detailSkill.active_config[key]) }}</strong>
              <small>产品默认 {{ fmt(detailSkill.default_config[key]) }}</small></div>
          </div>
        </section>
        <section class="detail-section">
          <h3>数据要求与边界</h3>
          <div v-for="item in detailSkill.data_readiness?.items || []" :key="`${item.database}:${item.table}`" class="readiness-row">
            <el-tag size="small" :type="item.available ? 'success' : (item.required ? 'danger' : 'info')" effect="plain">
              {{ item.available ? '可用' : item.required ? '缺失' : '可降级' }}
            </el-tag>
            <span>{{ item.purpose }}（{{ item.table }}）</span>
          </div>
          <p class="muted">{{ detailSkill.data_boundary }}</p>
        </section>
      </template>
    </el-drawer>

    <el-drawer v-model="editorVisible" :title="editorTitle" size="720px" :before-close="closeEditor">
      <template v-if="editSkill">
        <el-alert type="info" :closable="false" show-icon :title="editSkill.management_question" />
        <el-form label-width="190px" class="scheme-form">
          <el-form-item label="学校方案名称" required>
            <el-input v-model="form.name" maxlength="80" show-word-limit />
          </el-form-item>
          <el-form-item v-for="key in boundKeys(editSkill)" :key="key" :label="fieldMeta(key).label">
            <el-input-number v-if="isNumber(editSkill, key)" v-model="form.values[key]"
              :min="editSkill.config_bounds[key].min" :max="editSkill.config_bounds[key].max"
              :precision="editSkill.config_bounds[key].type==='int' ? 0 : 2"
              :step="editSkill.config_bounds[key].type==='int' ? 1 : 0.05" />
            <el-select v-else-if="editSkill.config_bounds[key].type==='list'" v-model="form.values[key]"
              multiple filterable allow-create default-first-option style="width:100%" />
            <el-input v-else v-model="form.values[key]" />
            <div class="field-help">
              {{ fieldMeta(key).meaning }} · 产品默认 {{ fmt(editSkill.default_config[key]) }}
              <template v-if="rangeText(editSkill,key)"> · 允许范围 {{ rangeText(editSkill,key) }}</template>
            </div>
          </el-form-item>
          <el-form-item label="适用角色" required>
            <el-checkbox-group v-model="form.roleIds" class="role-list">
              <el-checkbox v-for="role in data.roleIds || []" :key="role" :value="role">{{ roleLabel(role) }}</el-checkbox>
            </el-checkbox-group>
            <div class="field-help">只决定哪些工作身份采用本方案；学院、班级和学生范围仍由服务端实时鉴权。</div>
          </el-form-item>
          <el-form-item label="变更原因" required>
            <el-input v-model="form.reason" type="textarea" :rows="3" maxlength="200" show-word-limit
              placeholder="说明为什么调整、希望解决什么管理问题" />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="closeEditor()">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDraft">保存草稿</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="testVisible" title="发布前检查与影响预览" width="680px">
      <template v-if="testResult">
        <el-result :icon="testResult.passed ? 'success' : 'warning'"
          :title="testResult.passed ? '方案可以发布' : '方案暂不能发布'"
          :sub-title="`检查版本 ${testResult.testedVersion} · ${testResult.testedScope}`" />
        <div class="check-grid">
          <div v-for="(passed,key) in testResult.checks" :key="String(key)">
            <span>{{ checkLabel(String(key)) }}</span>
            <el-tag size="small" :type="passed ? 'success' : 'danger'">{{ passed ? '通过' : '未通过' }}</el-tag>
          </div>
        </div>
        <el-alert v-if="testResult.issues?.length" type="warning" :closable="false" show-icon
          :title="testResult.issues.join('；')" class="test-alert" />
        <section v-if="testResult.impact?.available" class="impact-box">
          <h3>相对当前生效方案的结果变化</h3>
          <div>
            <span>全部管理信号 <b>{{ testResult.impact.currentSignals }}</b> → <b>{{ testResult.impact.draftSignals }}</b></span>
            <span>高优先级信号 <b>{{ testResult.impact.currentHighPriority }}</b> → <b>{{ testResult.impact.draftHighPriority }}</b></span>
          </div>
          <p>{{ testResult.boundary }}</p>
        </section>
      </template>
      <template #footer>
        <el-button @click="testVisible=false">关闭</el-button>
        <el-button v-if="testResult?.passed && testedRow" type="primary" @click="publishDraft(testedRow)">发布此方案</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { ROLE_LABELS } from '@/store/role'
import {
  createSkillConfigDraft, exportSkillConfig, getDecisionSkillConfigs,
  importSkillConfig, publishSkillConfig, retireSkillConfig,
  rollbackSkillConfig, testSkillConfig, updateSkillConfigDraft,
} from '@/utils/decision'

const loading = ref(false)
const initialLoading = ref(true)
const error = ref('')
const activeTab = ref('active')
const activeCard = ref('')
const data = reactive<any>({items:[],summary:{},roleIds:[],llm:{}})
const detailVisible = ref(false)
const detailSkill = ref<any>(null)
const editorVisible = ref(false)
const editSkill = ref<any>(null)
const editVersion = ref<any>(null)
const saving = ref(false)
const baseline = ref('')
const form = reactive<any>({name:'',values:{},roleIds:[],reason:''})
const testingId = ref(0)
const testVisible = ref(false)
const testResult = ref<any>(null)
const testedRow = ref<any>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const FIELD_META:Record<string,{label:string;meaning:string}> = {
  target_grade:{label:'目标毕业年级',meaning:'确定毕业缺口核查所覆盖的目标年级'},
  near_grad_terms:{label:'临近毕业学期',meaning:'用于识别需要优先核查的临近毕业阶段'},
  coordination_min_students:{label:'校级协调最小人数',meaning:'达到该影响规模时上升为校级课程保障事项'},
  coordination_min_majors:{label:'校级协调最小专业数',meaning:'达到该专业覆盖面时提示跨学院协调'},
  structural_gap_min_students:{label:'结构性缺口最小人数',meaning:'识别影响面较大的培养方案课程缺口'},
  max_course_signals:{label:'重点课程数量上限',meaning:'控制首轮管理注意力聚焦的课程数量'},
  persistent_multiplier:{label:'持续偏高倍数',meaning:'课程未通过率相对学校基线的持续偏高判定倍数'},
  persistent_floor:{label:'持续偏高最低未通过率',meaning:'避免低基数课程因倍数放大被误判'},
  spike_multiplier:{label:'异常上升倍数',meaning:'识别单学期未通过率明显上升'},
  spike_delta_pp:{label:'异常上升百分点',meaning:'本学期相对历史基线的百分点变化阈值'},
  min_sample:{label:'最小有效样本量',meaning:'样本不足时不形成正式趋势判断'},
  high_impact_students:{label:'高影响学生人数',meaning:'用于识别需要优先配置教学支持资源的课程'},
  required_weight:{label:'必修课程权重',meaning:'排序时提高必修课程对毕业进度的影响权重'},
  improve_delta_pp:{label:'改善判定百分点',meaning:'识别课程未通过率显著改善的变化'},
  fail_per_required:{label:'每门必修未通过得分',meaning:'预警优先级中必修未通过的计分权重'},
  fail_cap:{label:'必修未通过得分上限',meaning:'限制单一因素对总优先级的过度放大'},
  gpa_drop_mild:{label:'GPA轻度下降阈值',meaning:'识别相邻学期学业表现的轻度下降'},
  gpa_drop_severe:{label:'GPA显著下降阈值',meaning:'识别需要优先核查的明显下降'},
  trend_mild:{label:'轻度趋势得分',meaning:'学业表现轻度下滑进入优先序的附加分'},
  trend_severe:{label:'显著趋势得分',meaning:'学业表现明显下滑进入优先序的附加分'},
  stall_days:{label:'预警滞留天数',meaning:'预警长期未变化时进入滞留核查'},
  stall_score:{label:'预警滞留得分',meaning:'滞留事项在本周核查队列中的附加权重'},
  stale_days:{label:'预警陈旧天数',meaning:'识别长期未更新的历史预警证据'},
  top_n:{label:'本周优先核查人数',meaning:'控制本周管理队列的可执行规模'},
  high_enrolled:{label:'大规模课程人数',meaning:'师资单点风险中的高影响课程人数界线'},
  mid_enrolled:{label:'中规模课程人数',meaning:'识别多班次但教师保障不足的课程'},
  title_gap_ratio:{label:'职称信息缺口比例',meaning:'教师职称证据不足时只提示核验，不下风险结论'},
}

const cards = computed(() => [
  {key:'templates',label:'产品标准方案',value:data.summary?.templates || 0,help:'随产品交付、无需初始化即可使用的管理分析模板。',action:'查看全部管理场景'},
  {key:'school',label:'学校生效方案',value:data.summary?.schoolActive || 0,help:'已发布并被适用角色实际采用的学校版本。',action:'核查学校个性化覆盖'},
  {key:'drafts',label:'待发布草稿',value:data.summary?.drafts || 0,help:'尚未发布或仍需完成发布前检查的版本。',action:'进入草稿与发布'},
  {key:'attention',label:'需要处理',value:data.summary?.attention || 0,help:'数据未就绪或尚未通过发布前检查的事项。',action:'优先完成检查'},
])
const filteredSkills = computed(() => {
  if (activeCard.value === 'school') return data.items.filter((item:any) => item.active_scheme)
  if (activeCard.value === 'attention') return data.items.filter((item:any) =>
    !item.data_readiness?.ready || item.versions?.some((row:any) => row.status==='draft' && row.test_status!=='passed'))
  return data.items
})
const draftRows = computed(() => data.items.flatMap((skill:any) =>
  (skill.versions || []).filter((row:any) => row.status==='draft').map((row:any) => ({...row,skill_id:skill.skill_id,skill_name:skill.name}))))
const historyRows = computed(() => data.items.flatMap((skill:any) =>
  (skill.versions || []).map((row:any) => ({
    ...row, action_type:row.action, skill_id:skill.skill_id, skill_name:skill.name,
  }))))

const draftColumns:DataTableColumn[] = [
  {key:'scheme',label:'学校方案',required:true,region:'identity',fixed:'left',minWidth:220},
  {key:'test_status',label:'发布前检查',width:125},
  {key:'roleIds',label:'适用角色',minWidth:210},
  {key:'change_reason',label:'变更原因',minWidth:230,tooltip:true},
  {key:'created_by',label:'创建人',width:110,defaultVisible:false},
  {key:'created_at',label:'创建时间',minWidth:170},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:190},
]
const historyColumns:DataTableColumn[] = [
  {key:'scheme',label:'方案版本',required:true,region:'identity',fixed:'left',minWidth:220},
  {key:'status',label:'状态',width:105},
  {key:'roleIds',label:'适用角色',minWidth:210},
  {key:'change_reason',label:'变更原因',minWidth:230,tooltip:true},
  {key:'action_type',label:'形成方式',width:105,defaultVisible:false},
  {key:'created_by',label:'创建人',width:105,defaultVisible:false},
  {key:'published_by',label:'发布人',width:105,defaultVisible:false},
  {key:'published_at',label:'发布时间',minWidth:170},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:215},
]

const editorTitle = computed(() => editVersion.value ? `编辑草稿 · ${editVersion.value.version_no}` : `配置学校方案 · ${editSkill.value?.name || ''}`)
function fieldMeta(key:string) { return FIELD_META[key] || {label:key,meaning:'学校可调整的管理分析参数'} }
function fmt(value:any) { return Array.isArray(value) ? value.join('、') : String(value ?? '—') }
function boundKeys(skill:any) { return Object.keys(skill?.config_bounds || {}) }
function isNumber(skill:any,key:string) { return ['int','float'].includes(skill.config_bounds[key]?.type) }
function rangeText(skill:any,key:string) {
  const bound=skill.config_bounds[key]
  return isNumber(skill,key) ? `${bound.min}—${bound.max}` : ''
}
function roleLabel(role:string) { return (ROLE_LABELS as any)[role] || role }
function roleSummary(roles:string[]) {
  if (!roles?.length) return '未指定'
  return roles.length === (data.roleIds?.length || 0) ? '全部管理角色'
    : roles.slice(0,3).map(roleLabel).join('、') + (roles.length>3 ? ` 等${roles.length}类` : '')
}
function skillOf(id:string) { return data.items.find((item:any) => item.skill_id===id) }
function testLabel(status:string) { return ({passed:'已通过',failed:'未通过',untested:'待检查'} as any)[status] || '待检查' }
function testTag(status:string) { return status==='passed'?'success':status==='failed'?'danger':'warning' }
function statusLabel(status:string) { return ({published:'生效中',retired:'历史版本',draft:'草稿'} as any)[status] || status }
function statusTag(status:string) { return status==='published'?'success':status==='draft'?'warning':'info' }
function checkLabel(key:string) {
  return ({parameterBoundary:'参数在允许范围',dataReadiness:'依赖数据已就绪',roleBoundary:'适用角色有效',
    protocolCurrent:'分析协议为当前版本',sampleRun:'当前学校数据试运行成功'} as any)[key] || key
}

async function load() {
  loading.value=true
  error.value=''
  try { Object.assign(data, await getDecisionSkillConfigs()) }
  catch (e:any) { error.value=e?.message || '请检查后端服务和数据连接' }
  finally { loading.value=false;initialLoading.value=false }
}
function selectCard(key:string) {
  activeCard.value=activeCard.value===key?'':key
  if (key==='drafts') activeTab.value='drafts'
  else activeTab.value='active'
}
function openDetail(skill:any) { detailSkill.value=skill;detailVisible.value=true }
function openEditor(skill:any,row:any=null) {
  if (!skill) return
  editSkill.value=skill
  editVersion.value=row
  form.name=row?.scheme_name || `${skill.name}学校方案`
  form.values={}
  const source=row?.config || skill.active_config || skill.default_config
  for (const key of boundKeys(skill)) form.values[key]=Array.isArray(source[key])?[...source[key]]:source[key]
  form.roleIds=[...(row?.roleIds || skill.active_scheme?.roleIds || data.roleIds || [])]
  form.reason=row?.change_reason || ''
  baseline.value=JSON.stringify({name:form.name,values:form.values,roleIds:form.roleIds,reason:form.reason})
  editorVisible.value=true
}
function currentForm() { return JSON.stringify({name:form.name,values:form.values,roleIds:form.roleIds,reason:form.reason}) }
async function closeEditor(done?:()=>void) {
  if (currentForm()!==baseline.value) {
    try { await ElMessageBox.confirm('当前调整尚未保存，确认关闭？','放弃未保存调整',{type:'warning'}) }
    catch { return }
  }
  editorVisible.value=false
  done?.()
}
function overrideOf() {
  const out:Record<string,any>={}
  for (const key of boundKeys(editSkill.value)) {
    if (JSON.stringify(form.values[key] ?? null)!==JSON.stringify(editSkill.value.default_config[key] ?? null)) out[key]=form.values[key]
  }
  return out
}
async function saveDraft() {
  if (!form.name.trim() || form.reason.trim().length<2 || !form.roleIds.length) {
    ElMessage.warning('请填写方案名称、变更原因并至少选择一个适用角色')
    return
  }
  saving.value=true
  try {
    const body={override:overrideOf(),changeReason:form.reason.trim(),schemeName:form.name.trim(),roleIds:[...form.roleIds]}
    if (editVersion.value) await updateSkillConfigDraft(editSkill.value.skill_id,editVersion.value.config_id,body)
    else await createSkillConfigDraft(editSkill.value.skill_id,body.override,body.changeReason,body.schemeName,body.roleIds)
    ElMessage.success('草稿已保存；完成发布前检查后才会生效')
    baseline.value=currentForm()
    editorVisible.value=false
    activeTab.value='drafts'
    await load()
  } finally { saving.value=false }
}
async function testDraft(row:any) {
  testingId.value=row.config_id
  testedRow.value=row
  try {
    testResult.value=await testSkillConfig(row.skill_id,row.config_id)
    testVisible.value=true
    await load()
    testedRow.value=draftRows.value.find((item:any)=>item.config_id===row.config_id) || row
  } finally { testingId.value=0 }
}
async function publishDraft(row:any) {
  if (row.test_status!=='passed') { ElMessage.warning('请先完成并通过发布前检查');return }
  await ElMessageBox.confirm('发布后，所选角色的决策简报和专题分析将采用此方案；未选角色继续使用产品默认。确认发布？',
    '发布学校分析方案',{type:'warning',confirmButtonText:'发布'})
  await publishSkillConfig(row.skill_id,row.config_id)
  ElMessage.success('学校方案已发布并进入实际运行链')
  testVisible.value=false
  activeTab.value='active'
  await load()
}
async function retireActive(skill:any) {
  const {value}=await ElMessageBox.prompt('停用后适用角色将回退产品标准方案。请填写停用原因：','停用学校方案',
    {type:'warning',inputPlaceholder:'必填',inputValidator:v=>(v||'').trim().length>=2||'请填写停用原因'})
  await retireSkillConfig(skill.skill_id,skill.active_scheme.config_id,(value||'').trim())
  ElMessage.success('学校方案已停用，相关角色已回退产品标准方案')
  await load()
}
async function rollback(row:any) {
  const {value}=await ElMessageBox.prompt(`将以 ${row.version_no} 为蓝本生成新的生效版本。请填写回滚原因：`,'回滚方案',
    {type:'warning',inputPlaceholder:'必填',inputValidator:v=>(v||'').trim().length>=2||'请填写回滚原因'})
  await rollbackSkillConfig(row.skill_id,row.config_id,(value||'').trim())
  ElMessage.success('已生成新的回滚发布版本')
  activeTab.value='active'
  await load()
}
async function exportPackage(row:any) {
  const pkg=await exportSkillConfig(row.skill_id,row.config_id)
  const blob=new Blob([JSON.stringify(pkg,null,2)],{type:'application/json;charset=utf-8'})
  const url=URL.createObjectURL(blob)
  const link=document.createElement('a')
  link.href=url
  link.download=`${row.scheme_name}-${row.version_no}.json`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('方案包已导出；不包含业务数据和模型密钥')
}
async function importPackage(event:Event) {
  const input=event.target as HTMLInputElement
  const file=input.files?.[0]
  input.value=''
  if (!file) return
  try {
    const pkg=JSON.parse(await file.text())
    const {value}=await ElMessageBox.prompt('导入只会生成草稿，仍需重新检查后发布。请填写导入原因：','导入分析方案包',
      {inputPlaceholder:'必填',inputValidator:v=>(v||'').trim().length>=2||'请填写导入原因'})
    await importSkillConfig(pkg,(value||'').trim())
    ElMessage.success('方案包已导入为草稿')
    activeTab.value='drafts'
    await load()
  } catch (e:any) {
    if (e==='cancel' || e==='close') return
    ElMessage.error(e?.message || '方案包无法识别')
  }
}
onMounted(load)
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}.head-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.hidden-file{display:none}.boundary-alert{margin-bottom:14px}.load-error{background:#fff;border:1px solid var(--sa-border);border-radius:12px}.loading-copy{text-align:center;color:#64748b;font-size:12px}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}.summary-grid button{padding:16px;text-align:left;background:#fff;border:1px solid var(--sa-border);border-radius:12px;cursor:pointer}.summary-grid button:hover,.summary-grid button.active{border-color:#6366f1;box-shadow:0 5px 16px rgba(79,70,229,.09)}.summary-grid span,.summary-grid small{display:flex;align-items:center;gap:4px;color:#64748b;font-size:12px}.summary-grid b{display:block;margin:7px 0;font-size:26px;color:#1e293b}.updating-bar{margin-bottom:10px;padding:8px 12px;border-radius:8px;background:#eef2ff;color:#4f46e5;font-size:12px}.template-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.template-card{padding:18px;background:#fff;border:1px solid var(--sa-border);border-radius:13px}.template-head{display:flex;justify-content:space-between;gap:12px}.template-label{font-size:11px;color:#6366f1}.template-card h3{margin:5px 0 0;color:#1e293b}.management-question{min-height:44px;color:#475569;font-size:13px;line-height:1.7}.template-state{display:flex;gap:18px;flex-wrap:wrap;padding:10px 0;border-top:1px solid #eef2f7;color:#64748b;font-size:12px}.template-state i{display:inline-block;width:7px;height:7px;margin-right:5px;border-radius:50%}.template-state i.ok{background:#10b981}.template-state i.bad{background:#ef4444}.template-actions{display:flex;gap:8px;margin-top:10px}.table-card{padding:12px}.main-cell{font-weight:650;color:#1e293b}.sub-cell{margin-top:3px;color:#94a3b8;font-size:11px}.row-actions{display:flex;white-space:nowrap}.detail-section{padding:4px 0 18px;border-bottom:1px solid #eef2f7}.detail-section h3{margin:10px 0;color:#1e293b;font-size:15px}.detail-section p{color:#475569;line-height:1.75}.muted{color:#64748b!important;font-size:12px}.fact-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fact-grid div{padding:11px;background:#f8fafc;border-radius:8px}.fact-grid span,.fact-grid b{display:block}.fact-grid span{color:#94a3b8;font-size:11px}.fact-grid b{margin-top:5px;color:#334155;font-size:13px}.parameter-row,.readiness-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:10px 0;border-bottom:1px dashed #e2e8f0}.parameter-row b,.parameter-row span,.parameter-row strong,.parameter-row small{display:block}.parameter-row span,.parameter-row small{margin-top:3px;color:#94a3b8;font-size:11px}.parameter-row strong{text-align:right;color:#4f46e5}.readiness-row{justify-content:flex-start;color:#475569;font-size:12px}.scheme-form{margin-top:18px}.field-help{width:100%;color:#94a3b8;font-size:11px;line-height:1.6}.role-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 12px}.check-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.check-grid>div{display:flex;justify-content:space-between;padding:10px 12px;background:#f8fafc;border-radius:8px}.test-alert{margin-top:12px}.impact-box{margin-top:14px;padding:14px;background:#f8fafc;border-radius:10px}.impact-box h3{margin:0 0 10px;font-size:14px}.impact-box>div{display:flex;gap:28px}.impact-box p{margin:10px 0 0;color:#64748b;font-size:11px}.impact-box b{color:#4f46e5}
@media(max-width:1100px){.summary-grid,.template-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sa-head-row{display:block}.head-actions{justify-content:flex-start;margin-top:10px}}
@media(max-width:720px){.summary-grid,.template-grid,.fact-grid,.check-grid{grid-template-columns:1fr}.role-list{grid-template-columns:1fr}}
</style>
