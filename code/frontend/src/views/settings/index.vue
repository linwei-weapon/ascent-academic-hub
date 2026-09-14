<template>
  <div>
    <div v-if="!embedded" class="sa-head-row">
      <div>
        <el-breadcrumb v-if="alertRules&&!embedded" separator="/" style="margin-bottom:8px"><el-breadcrumb-item :to="{path:'/admin/alert'}">学业预警监控</el-breadcrumb-item><el-breadcrumb-item>预警规则治理</el-breadcrumb-item></el-breadcrumb>
        <h2 class="sa-page-title">{{alertRules?'预警规则治理':'系统设置'}}</h2>
        <p class="sa-page-sub">{{alertRules?'管理预警规则阈值、变更试算、审核发布与激活，所有变更均进入治理流程。':'维护学期与运行环境等系统级参数；业务规则已归入对应业务模块。'}}</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="sa-tabs">
      <!-- 预警规则配置 -->
      <el-tab-pane v-if="alertRules" label="预警规则" name="rules">
        <el-alert v-if="ruleLoadError" type="error" :closable="false" show-icon
          title="生产规则与变更单加载失败" :description="ruleLoadError" style="margin-bottom:12px"/>
        <div class="sa-card" v-loading="rulesLoading"
          element-loading-text="正在加载生产规则、权限和变更流程…">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div class="sa-card-title" style="margin:0">预警规则配置 <span class="extra">引擎内置规则 · 阈值可调</span></div>
          </div>
          <el-table :data="rules" size="small">
            <el-table-column prop="name" label="规则名称" width="150" />
            <el-table-column prop="level" label="预警等级" width="90">
              <template #default="{row}">
                <el-tag :type="row.level==='严重'?'danger':row.level==='警告'?'warning':'info'" size="small">{{ row.level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="判定阈值" min-width="300">
              <template #default="{row}">
                <span v-if="row.conditions.length" class="cond-line">
                  <span v-for="(c,i) in row.conditions" :key="c.key">
                    <span v-if="i>0" class="cond-join">{{ row.id==='R6' ? '且' : '·' }}</span>
                    <span class="cond-var">{{ c.label }}</span>
                    <span class="cond-op">{{ c.op }}</span>
                    <b class="cond-val">{{ fmt(c.value) }}</b><span class="cond-unit">{{ c.unit }}</span>
                  </span>
                </span>
                <span v-else style="font-size:12px;color:#94A3B8">{{ row.params || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="enabled" label="启用" width="64">
              <template #default="{row}">
                <el-switch v-model="row.enabled" size="small" :disabled="!row.editable||!hasPerm('edit')" @change="onRuleToggle(row)" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{row}">
                <el-button size="small" text type="primary" :disabled="!row.editable||!hasPerm('edit')" @click="openRuleDialog(row)">编辑阈值</el-button>
              </template>
            </el-table-column>
            <el-table-column prop="enabled" label="来源" width="70">
              <template #default="{row}">
                <el-tag v-if="row.triggerType==='discovered'" size="small" type="warning">自发现</el-tag>
                <span v-else class="sa-faint" style="font-size:12px">内置</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="sa-card-title" style="font-size:13px;margin-top:20px">规则变更单</div>
          <el-table :data="changes" size="small" empty-text="暂无规则变更单">
            <el-table-column prop="changeId" label="编号" width="70" />
            <el-table-column prop="ruleId" label="规则" width="70" />
            <el-table-column prop="reason" label="变更原因" min-width="180" />
            <el-table-column label="状态" width="90">
              <template #default="{row}"><el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="影响试算" min-width="190">
              <template #default="{row}">
                <span v-if="row.impact?.candidateStatus==='evaluated'">
                  候选 {{ row.impact.candidateStudents }} · 新增 {{ row.impact.newStudents }} · 退出 {{ row.impact.exitedStudents }}
                  <el-tag size="small" :type="row.isFresh?'success':'danger'" style="margin-left:6px">{{ row.isFresh ? '数据有效' : '已过期' }}</el-tag>
                  <div class="sa-faint" style="font-size:11px;margin-top:2px">
                    {{ row.impact?.dataSnapshot?.currentSemester || '—' }} · {{ row.impact?.evaluatedAt || '' }}
                  </div>
                </span>
                <el-tag v-else size="small" type="info">待试算</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="createdBy" label="创建人" width="100" />
            <el-table-column label="操作" width="320">
              <template #default="{row}">
                <el-button v-if="row.status==='draft'&&hasPerm('edit')" size="small" text type="primary" @click="openTrialScript(row)">试算脚本维护</el-button>
                <el-button v-if="row.status==='draft'&&hasPerm('edit')" size="small" text type="success" @click="changeAction(row,'evaluate')">影响试算</el-button>
                <el-button v-if="row.impact?.candidateStatus==='evaluated'" size="small" text @click="openCandidates(row)">候选明细</el-button>
                <el-button v-if="row.impact?.candidateStatus==='evaluated'" size="small" text @click="openAnalysis(row)">影响分析</el-button>
                <el-button v-if="row.status==='draft'&&hasPerm('edit')" size="small" text type="primary" @click="changeAction(row,'submit')">提交审核</el-button>
                <el-button v-if="row.status==='submitted'&&hasPerm('review')" size="small" text type="success" @click="changeAction(row,'approve')">通过</el-button>
                <el-button v-if="row.status==='submitted'&&hasPerm('review')" size="small" text type="danger" @click="changeAction(row,'reject')">拒绝</el-button>
                <el-button v-if="row.status==='approved'&&hasPerm('publish')" size="small" text type="primary" @click="changeAction(row,'publish')">发布配置</el-button>
                <el-button v-if="row.status==='published'&&hasPerm('activate')" size="small" text type="danger" @click="changeAction(row,'activate')">激活预警</el-button>
                <el-button v-if="(row.status==='published'||row.status==='activated')&&hasPerm('edit')" size="small" text type="warning" @click="changeAction(row,'rollback')">创建回滚单</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="sa-faint" style="font-size:11px;margin-top:12px;line-height:1.7">
            规则为引擎内置（基于教务系统真实成绩自动计算），变量与运算符固定、仅数值阈值可调。
            阈值或启用状态修改后<b>下次数据重算时生效</b>，预警结果在「预警查看」页面展示。
          </div>
        </div>

        <div v-if="false" class="sa-card" style="margin-top:14px;display:flex;justify-content:space-between;align-items:center">
          <div>
            <div class="sa-card-title">规则自发现</div>
            <div class="sa-faint" style="font-size:12px">切换到“规则自发现”Tab查看关联分析建议；采纳后回到本Tab完成试算、复核、发布与激活。</div>
          </div>
          <el-button type="primary" plain size="small" @click="$router.push('/admin/alert/discovery')">进入规则自发现</el-button>
        </div>

        <!-- 旧内嵌区块保留为兼容模板，不再渲染或发起请求。 -->
        <div v-if="false" class="sa-card" style="margin-top:14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <div class="sa-card-title" style="margin:0">
              规则自发现
              <span class="extra" v-if="discLastSemester">上次分析：{{ discLastSemester }} 学期 · {{ discTotalStudents.toLocaleString() }} 人</span>
            </div>
            <el-button size="small" type="primary" :loading="discovering" @click="runDiscovery">运行规则自发现</el-button>
          </div>
          <div class="sa-faint" style="font-size:11px;margin-bottom:8px">
            基于真实成绩、真实学籍异动和当前严重预警做历史关联分析。结果不是因果结论，采纳后仅创建变更草稿。
          </div>
          <el-alert v-if="discoveryEvidence.limitation" type="warning" :closable="false"
            :title="discoveryEvidence.limitation" show-icon style="margin-bottom:10px" />

          <!-- 待审核 -->
          <div v-if="discovered.pending.length" style="margin-bottom:12px">
            <div class="sa-card-title" style="font-size:13px">待审核建议（{{ discovered.pending.length }}）</div>
            <div v-for="dr in discovered.pending" :key="dr.id" class="disc-card">
              <div class="disc-header">
                <span class="disc-name">{{ dr.name }}</span>
                <el-tag :type="dr.level==='严重'?'danger':dr.level==='警告'?'warning':'info'" size="small">建议{{ dr.level }}</el-tag>
              </div>
              <div class="disc-cond">
                <span v-for="(c,ci) in dr.conditions" :key="c.key">
                  <span v-if="ci>0" style="color:#CBD5E1;margin:0 6px">且</span>
                  <span>{{ c.label }}</span>
                  <span style="color:#64748B;margin:0 4px">{{ c.op }}</span>
                  <b style="color:var(--sa-primary)">{{ c.value }}{{ c.unit }}</b>
                </span>
              </div>
              <!-- 详细解释 -->
              <div class="disc-explain" v-if="dr.detail">
                <div class="disc-explain-item">
                  在 <b>{{ dr.detail.total_samples?.toLocaleString() || '—' }}</b> 名有完整学业轨迹的学生中，
                  有 <b>{{ dr.sampleSize }}</b> 人命中此规则。
                </div>
                <div class="disc-explain-item">
                  命中学生中，
                  <b :style="{color: dr.detail.match_rate > 30 ? '#E11D48' : '#D97706'}">{{ dr.detail.match_rate }}%（{{ dr.detail.match_positive }}/{{ dr.detail.match_total }}）</b>
                  出现了退学、留级或多次严重预警等严重学业问题；
                  而全校平均的问题发生率为
                  <b>{{ dr.detail.overall_rate }}%（{{ dr.detail.overall_positive }}/{{ dr.detail.total_samples }}）</b>。
                </div>
                <div class="disc-explain-conclusion">
                  → 命中该规则的学生，出现严重学业问题的风险是全校平均水平的
                  <b :style="{color:dr.riskRatio>=5?'#E11D48':'#D97706',fontSize:'15px'}">{{ dr.riskRatio }} 倍</b>
                </div>
              </div>
              <div class="disc-actions">
                <el-button size="small" type="success" @click="reviewRule(dr.id, 'approve')">采纳并创建变更草稿</el-button>
                <el-button size="small" type="danger" plain @click="reviewRule(dr.id, 'reject')">拒绝</el-button>
              </div>
            </div>
          </div>

          <div v-if="discovered.approved.length" style="margin-bottom:12px">
            <div class="sa-card-title" style="font-size:13px">已采纳建议（{{ discovered.approved.length }}）</div>
            <div v-for="dr in discovered.approved" :key="dr.id" class="disc-card">
              <span class="disc-name">{{ dr.name }}</span>
              <span class="sa-faint" style="font-size:11px">
                已转入规则治理<span v-if="dr.detail?.governance_change_id"> · 变更单 #{{ dr.detail.governance_change_id }}</span>
              </span>
            </div>
          </div>

          <!-- 已拒绝折叠 -->
          <div v-if="discovered.rejected.length">
            <div class="disc-toggle" @click="showRejected=!showRejected">
              已拒绝（{{ discovered.rejected.length }}）<span style="margin-left:4px">{{ showRejected ? '▾' : '▸' }}</span>
            </div>
            <div v-if="showRejected">
              <div v-for="dr in discovered.rejected" :key="dr.id" class="disc-card rejected">
                <span class="disc-name">{{ dr.name }}</span>
                <span class="sa-faint" style="font-size:11px">置信度 {{ (dr.confidence*100).toFixed(0) }}% · 风险 x{{ dr.riskRatio }} · {{ dr.createdAt }}</span>
              </div>
            </div>
          </div>

          <div v-if="!discovered.pending.length && !discovered.rejected.length && !discovering" class="sa-faint" style="font-size:12px;padding:8px 0">
            暂无自发现规则。点击"运行规则自发现"开始分析。
          </div>
        </div>
      </el-tab-pane>

      <!-- 学期配置 -->
      <el-tab-pane v-if="!alertRules" label="学期配置" name="semester">
        <div class="sa-card">
          <div class="sa-card-title">当前学期信息</div>
          <el-empty :image-size="100">
            <template #description>
              <div style="font-size:13px;color:#64748B">暂无学期配置数据</div>
              <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
                学期起止 / 教学周 / 数据同步频率等配置需后端学期配置接口支持，当前未接入。
              </div>
            </template>
          </el-empty>
        </div>
      </el-tab-pane>

      <!-- 数据备份 -->
      <el-tab-pane v-if="!alertRules" label="数据备份" name="backup">
        <div class="sa-card">
          <div class="sa-card-title">备份策略</div>
          <el-empty :image-size="100">
            <template #description>
              <div style="font-size:13px;color:#64748B">暂无备份策略数据</div>
              <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
                备份频率 / 保留周期 / 完整性校验等信息需后端运维接口支持，当前未接入。
              </div>
            </template>
          </el-empty>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 规则阈值编辑对话框 -->
    <el-dialog v-model="ruleDialogVisible" title="编辑预警阈值" width="520px">
      <div v-if="editingRule" class="rule-edit">
        <div class="re-head">
          <span class="re-name">{{ editingRule.name }}</span>
          <el-tag :type="editingRule.level==='严重'?'danger':editingRule.level==='警告'?'warning':'info'" size="small">{{ editingRule.level }}</el-tag>
        </div>
        <el-form label-width="0" size="small">
          <div v-for="c in editForm.conditions" :key="c.key" class="cond-row">
            <span class="cond-row-var">{{ c.label }}</span>
            <el-tag size="small" type="info" effect="plain" class="cond-row-op">{{ c.op }}</el-tag>
            <el-input-number v-model="c.value" :min="c.min" :max="c.max" :step="c.step"
              :precision="Number.isInteger(c.step) ? 0 : 1" controls-position="right" style="width:130px" />
            <span class="cond-row-unit">{{ c.unit }}</span>
          </div>
          <el-input v-model="editForm.reason" type="textarea" :rows="3" maxlength="300"
            show-word-limit placeholder="请填写变更原因（至少5个字符）" />
        </el-form>
        <div class="sa-faint" style="font-size:11px;margin-top:4px;line-height:1.6">
          变量与运算符由引擎固定，仅可调整数值。保存后下次数据重算时生效。
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="ruleDialogVisible=false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="saveRule">创建变更单</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="scriptDialogVisible" title="试算脚本维护" width="min(760px, 92vw)"
      :close-on-click-modal="false" destroy-on-close>
      <div v-loading="scriptLoading" class="trial-script-editor">
        <div class="trial-script-meta">
          <span>变更单 #{{ scriptChangeId }}</span>
          <el-tag size="small" type="info">规则 {{ scriptRuleId }}</el-tag>
        </div>
        <el-form label-position="top">
          <el-form-item label="脚本类型" required>
            <el-radio-group v-model="scriptForm.scriptType">
              <el-radio-button value="sql">普通SQL</el-radio-button>
              <el-radio-button value="stored_procedure">存储过程</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="脚本内容" required>
            <el-input v-model="scriptForm.scriptContent" type="textarea" :rows="16"
              maxlength="50000" show-word-limit resize="vertical" :placeholder="scriptPlaceholder"
              class="trial-script-input" />
          </el-form-item>
        </el-form>
        <el-alert type="info" :closable="false" show-icon
          title="此处维护试算脚本配置，不会在保存时直接执行；脚本变更后需重新进行影响试算。" />
      </div>
      <template #footer>
        <el-button @click="scriptDialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="scriptSaving" :disabled="scriptLoading" @click="saveTrialScript">保存</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="candidateVisible" title="规则候选学生明细" width="900px">
      <el-table :data="candidateRows" size="small" v-loading="candidateLoading">
        <el-table-column prop="student_id" label="学号" width="130" />
        <el-table-column prop="student_name" label="姓名" width="90" />
        <el-table-column prop="college_name" label="学院" min-width="130" />
        <el-table-column prop="major_name" label="专业" min-width="120" />
        <el-table-column prop="trigger_detail" label="候选命中说明" min-width="220" show-overflow-tooltip />
      </el-table>
      <el-pagination style="margin-top:12px;justify-content:flex-end" background small
        layout="total, prev, pager, next" :total="candidateTotal" :page-size="20"
        :current-page="candidatePage" @current-change="loadCandidates" />
      <template #footer><el-button type="primary" plain @click="downloadCandidates">导出候选 CSV</el-button></template>
    </el-dialog>
    <el-dialog v-model="analysisVisible" title="规则变更影响分析" width="min(1120px, 94vw)">
      <div class="sa-card-title" style="font-size:13px">参数变更</div>
      <el-table :data="analysis.paramDiff || []" size="small" style="margin-bottom:16px">
        <el-table-column prop="key" label="参数" />
        <el-table-column prop="before" label="变更前" />
        <el-table-column prop="after" label="变更后" />
        <el-table-column label="是否变化"><template #default="{row}"><el-tag size="small" :type="row.changed?'warning':'info'">{{ row.changed?'已调整':'未调整' }}</el-tag></template></el-table-column>
      </el-table>
      <section class="distribution-section">
        <div class="distribution-head">
          <div>
            <div class="sa-card-title distribution-title">学院专业年级分布</div>
          </div>
          <div class="distribution-total">总影响 <strong>{{ analysisDistribution.total }}</strong> 人</div>
        </div>
        <el-table class="analysis-cross-table" :data="analysisDistribution.rows" border size="small"
          max-height="430" empty-text="暂无变更影响数据" :span-method="analysisSpanMethod"
          :row-class-name="analysisRowClassName">
          <el-table-column prop="collegeName" label="学院" width="170" fixed show-overflow-tooltip />
          <el-table-column prop="majorName" label="专业" width="170" fixed show-overflow-tooltip />
          <el-table-column v-for="(grade, gradeIndex) in analysisDistribution.grades" :key="grade"
            :label="grade" width="105" align="right" header-align="center">
            <template #default="{row}">{{ row.counts?.[gradeIndex] || 0 }}</template>
          </el-table-column>
          <el-table-column prop="total" label="小计" width="110" align="right" header-align="center" fixed="right" />
        </el-table>
      </section>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http, getToken } from '@/utils/http'

const props = withDefaults(defineProps<{alertRules?:boolean;embedded?:boolean}>(), {alertRules:false,embedded:false})
const alertRules = props.alertRules
const embedded = props.embedded

interface Condition { key: string; label: string; op: string; unit: string; value: number; min: number; max: number; step: number }
interface Rule { id: string; name: string; level: string; triggerType: string; conditions: Condition[]; params: string; editable: boolean; enabled: boolean }
interface RuleChange {
  changeId:number; ruleId:string; status:string; reason:string; impact:any;
  createdBy:string; isFresh?:boolean;
  trialScript?:{scriptType:string;maintained:boolean;updatedBy?:string;updatedAt?:string}
}

const activeTab = ref(alertRules ? 'rules' : 'semester')
const rules = reactive<Rule[]>([])
const rulesLoading = ref(false)
const ruleLoadError = ref('')
const rulePermissions = ref<string[]>([])
function hasPerm(permission:string) { return rulePermissions.value.includes(permission) }
const changes = reactive<RuleChange[]>([])
const candidateVisible = ref(false)
const candidateLoading = ref(false)
const candidateRows = ref<any[]>([])
const candidateTotal = ref(0)
const candidatePage = ref(1)
const candidateChangeId = ref(0)
const analysisVisible = ref(false)
const analysis = ref<any>({})
const analysisDistribution = computed(() => analysis.value?.organizationGradeDistribution || {
  grades: [], rows: [], total: 0,
})
const scriptDialogVisible = ref(false)
const scriptLoading = ref(false)
const scriptSaving = ref(false)
const scriptChangeId = ref(0)
const scriptRuleId = ref('')
const scriptForm = reactive({ scriptType: 'sql', scriptContent: '' })
const scriptPlaceholder = computed(() => scriptForm.scriptType === 'sql'
  ? '请输入用于规则影响试算的 SQL 脚本'
  : '请输入存储过程定义或调用脚本')

function analysisSpanMethod({ row, columnIndex }: {row:any;columnIndex:number}) {
  if (row.rowType === 'grandTotal') {
    if (columnIndex === 0) return [1, 2]
    if (columnIndex === 1) return [0, 0]
  }
  if (columnIndex === 0) {
    if (row.rowType === 'major' && row.collegeRowspan) return [row.collegeRowspan, 1]
    return [0, 0]
  }
  return [1, 1]
}

function analysisRowClassName({ row }: {row:any}) {
  return `analysis-${row.rowType || 'major'}`
}

function fmt(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return Number.isInteger(v) ? String(v) : String(v)
}

// ---- 阈值编辑 ----
const ruleDialogVisible = ref(false)
const saving = ref(false)
const editingRule = ref<Rule | null>(null)
const editForm = reactive<{ conditions: Condition[]; reason: string }>({ conditions: [], reason: '' })

function openRuleDialog(row: Rule) {
  if (!row.editable) return
  editingRule.value = row
  // 深拷贝条件，取消时不污染表格
  editForm.conditions = row.conditions.map(c => ({ ...c }))
  editForm.reason = ''
  ruleDialogVisible.value = true
}

async function saveRule() {
  if (!editingRule.value) return
  const values: Record<string, number> = {}
  editForm.conditions.forEach(c => { values[c.key] = c.value })
  if (editForm.reason.trim().length < 5) {
    ElMessage.warning('请填写至少5个字符的变更原因')
    return
  }
  saving.value = true
  try {
    await http.post(`/admin/settings/rules/${editingRule.value.id}/changes`,
      { values, reason: editForm.reason.trim() })
    ruleDialogVisible.value = false
    ElMessage.success('规则变更草稿已创建，生产规则未改变')
    await loadChanges()
  } finally {
    saving.value = false
  }
}

async function onRuleToggle(row: Rule) {
  const requested = row.enabled
  try {
    const { value } = await ElMessageBox.prompt(`请说明${requested ? '启用' : '停用'}规则“${row.name}”的原因`, '创建规则变更单',
      { inputValidator: (v: string) => v.trim().length >= 5 || '至少填写5个字符' })
    await http.post(`/admin/settings/rules/${row.id}/changes`, { enabled: requested, reason: value.trim() })
    row.enabled = !requested
    ElMessage.success('启停变更草稿已创建，生产状态暂未改变')
    await loadChanges()
  } catch {
    row.enabled = !requested
  }
}

function statusLabel(s:string) { return ({draft:'草稿',submitted:'待审核',approved:'已通过',rejected:'已拒绝',published:'配置已发布',activated:'预警已激活'} as any)[s] || s }
function statusType(s:string) { return s==='approved'||s==='published'||s==='activated'?'success':s==='rejected'?'danger':s==='submitted'?'warning':'info' }
async function openTrialScript(row:RuleChange) {
  scriptChangeId.value = row.changeId
  scriptRuleId.value = row.ruleId
  scriptForm.scriptType = row.trialScript?.scriptType || 'sql'
  scriptForm.scriptContent = ''
  scriptDialogVisible.value = true
  scriptLoading.value = true
  try {
    const data = await http.get<any>(`/admin/settings/rule-changes/${row.changeId}/trial-script`)
    scriptForm.scriptType = data.scriptType || 'sql'
    scriptForm.scriptContent = data.scriptContent || ''
  } catch (e:any) {
    scriptDialogVisible.value = false
    ElMessage.error(e?.message || '试算脚本加载失败')
  } finally {
    scriptLoading.value = false
  }
}
async function saveTrialScript() {
  if (!scriptForm.scriptContent.trim()) {
    ElMessage.warning('请输入试算脚本内容')
    return
  }
  scriptSaving.value = true
  try {
    await http.put(`/admin/settings/rule-changes/${scriptChangeId.value}/trial-script`, {
      script_type: scriptForm.scriptType,
      script_content: scriptForm.scriptContent.trim(),
    })
    scriptDialogVisible.value = false
    ElMessage.success('试算脚本已保存，请重新执行影响试算')
    await loadChanges()
  } catch (e:any) {
    ElMessage.error(e?.message || '试算脚本保存失败')
  } finally {
    scriptSaving.value = false
  }
}
function openCandidates(row:RuleChange) {
  candidateChangeId.value = row.changeId
  candidateVisible.value = true
  loadCandidates(1)
}
async function loadCandidates(page=1) {
  candidateLoading.value = true
  try {
    const d = await http.get<any>(`/admin/settings/rule-changes/${candidateChangeId.value}/candidates?page=${page}&page_size=20`)
    candidateRows.value = d.list || []
    candidateTotal.value = d.total || 0
    candidatePage.value = page
  } finally { candidateLoading.value = false }
}
async function openAnalysis(row:RuleChange) {
  analysis.value = await http.get<any>(`/admin/settings/rule-changes/${row.changeId}/analysis`)
  analysisVisible.value = true
}
async function downloadCandidates() {
  const res = await fetch(`/api/admin/settings/rule-changes/${candidateChangeId.value}/candidates.csv`,
    { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) { ElMessage.error('候选名单导出失败'); return }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `rule-change-${candidateChangeId.value}-candidates.csv`; a.click()
  URL.revokeObjectURL(url)
}
async function loadChanges() {
  try {
    const list = await http.get<RuleChange[]>('/admin/settings/rule-changes')
    changes.splice(0, changes.length, ...(list || []))
  } catch { changes.splice(0) }
}
async function changeAction(row:RuleChange, action:string) {
  try {
    if (action === 'activate') {
      await ElMessageBox.confirm(
        `将按候选清单更新当前预警：新增 ${row.impact?.newStudents || 0} 人、退出 ${row.impact?.exitedStudents || 0} 人。该操作会写入事件状态历史，是否继续？`,
        '确认激活预警', { type: 'warning', confirmButtonText: '确认激活' })
    }
    if (action === 'evaluate') await http.post(`/admin/settings/rule-changes/${row.changeId}/evaluate`)
    else if (action === 'submit') await http.post(`/admin/settings/rule-changes/${row.changeId}/submit`)
    else if (action === 'publish') await http.post(`/admin/settings/rule-changes/${row.changeId}/publish`)
    else if (action === 'activate') await http.post(`/admin/settings/rule-changes/${row.changeId}/activate`)
    else if (action === 'rollback') await http.post(`/admin/settings/rule-changes/${row.changeId}/rollback`)
    else await http.post(`/admin/settings/rule-changes/${row.changeId}/review`, { action })
    ElMessage.success('操作成功')
    await loadChanges()
    if (action === 'publish') {
      const d = await http.get<{rules:Rule[]}>('/admin/settings')
      rules.splice(0, rules.length, ...(d.rules || []))
    }
  } catch (e:any) { ElMessage.error(e?.message || '操作失败') }
}

// ── 规则自发现 ──
interface DiscoveredRule {
  id: number; semesterId: string; name: string; conditions: any[];
  level: string; confidence: number; riskRatio: number; sampleSize: number;
  detail: any; status: string; createdAt: string; approvedAt: string | null;
}
const discovered = reactive<{ pending: DiscoveredRule[]; approved: DiscoveredRule[]; rejected: DiscoveredRule[] }>({
  pending: [], approved: [], rejected: [],
})
const discLastSemester = ref('')
const discTotalStudents = ref(0)
const discovering = ref(false)
const showRejected = ref(false)
const discoveryEvidence = ref<any>({})

async function loadDiscovered() {
  try {
    const d = await http.get<any>('/admin/settings/rules/discovered')
    discovered.pending = d.pending || []
    discovered.approved = d.approved || []
    discovered.rejected = d.rejected || []
    discLastSemester.value = d.lastSemester || ''
    discTotalStudents.value = d.totalStudents || 0
    discoveryEvidence.value = d.evidence || {}
  } catch { /* 接口不可用时静默 */ }
}

async function runDiscovery() {
  discovering.value = true
  try {
    const d = await http.post<any>('/admin/settings/rules/discover')
    ElMessage.success(d.msg || `分析完成，发现 ${d.count} 条候选规则`)
    await loadDiscovered()
  } catch (e: any) {
    ElMessage.error(e?.message || '分析失败')
  } finally {
    discovering.value = false
  }
}

async function reviewRule(id: number, action: string) {
  try {
    const d = await http.put<any>(`/admin/settings/rules/discovered/${id}`, { action })
    ElMessage.success(d.msg || (action === 'approve' ? '已创建规则变更草稿' : '规则建议已拒绝'))
    await loadDiscovered()
    await loadChanges()
    // 同时刷新上方规则表
    const r = await http.get<{ rules: Rule[] }>('/admin/settings')
    rules.splice(0, rules.length, ...(r.rules || []))
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

onMounted(async () => {
  if (!alertRules) return
  rulesLoading.value = true
  ruleLoadError.value = ''
  try {
    const p = await http.get<any>('/admin/settings/rule-permissions/me')
    rulePermissions.value = p.permissions || []
    const d = await http.get<{ rules: Rule[] }>('/admin/settings')
    rules.splice(0, rules.length, ...(d.rules || []))
    await loadChanges()
  } catch (error:any) {
    rulePermissions.value = []
    ruleLoadError.value = error?.message || '请稍后重试'
  } finally {
    rulesLoading.value = false
  }
})
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.cond-line { font-size: 12px; color: #475569; }
.cond-var { color: #475569; }
.cond-op { margin: 0 4px; color: #94A3B8; font-weight: 600; }
.cond-val { color: var(--sa-primary); font-size: 13px; }
.cond-unit { color: #64748B; margin-left: 1px; }
.cond-join { margin: 0 8px; color: #CBD5E1; }
.rule-edit .re-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.rule-edit .re-name { font-size: 15px; font-weight: 700; color: #1E293B; }
.cond-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.cond-row-var { flex: 1; font-size: 13px; color: #475569; }
.cond-row-op { flex: 0 0 auto; }
.cond-row-unit { font-size: 12px; color: #64748B; min-width: 28px; }
.trial-script-editor { min-height: 430px; }
.trial-script-meta { display:flex; align-items:center; gap:10px; margin-bottom:16px; color:#475569; font-size:13px; }
.trial-script-input :deep(textarea) { font-family: Consolas, 'Courier New', monospace; line-height: 1.6; tab-size: 2; }
.distribution-section { margin-top: 4px; }
.distribution-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 10px; }
.distribution-title { margin-bottom: 4px; font-size: 13px; }
.distribution-total { flex: 0 0 auto; color: #475569; font-size: 12px; white-space: nowrap; }
.distribution-total strong { color: var(--sa-primary); font-size: 17px; font-variant-numeric: tabular-nums; }
.analysis-cross-table { width: 100%; }
.analysis-cross-table :deep(.cell) { font-variant-numeric: tabular-nums; }
.analysis-cross-table :deep(.analysis-collegeSubtotal td.el-table__cell) { background: #f8fafc !important; font-weight: 650; color: #334155; }
.analysis-cross-table :deep(.analysis-grandTotal td.el-table__cell) { background: #eef4ff !important; font-weight: 700; color: #1e3a8a; border-top-color: #bfdbfe; }
@media(max-width:760px){.distribution-head{align-items:flex-start;flex-direction:column;gap:8px}}
/* 规则自发现 */
.disc-card {
  border: 1px solid var(--sa-border-2); border-radius: 8px; padding: 14px 16px;
  margin-bottom: 10px; background: #fafbfc;
}
.disc-card.rejected { background: #f9fafb; opacity: 0.75; padding: 8px 14px; }
.disc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.disc-name { font-weight: 700; font-size: 14px; color: #1E293B; }
.disc-cond { font-size: 13px; color: #475569; margin-bottom: 10px; padding: 8px 10px; background: #f1f5f9; border-radius: 6px; }
.disc-explain { font-size: 12px; color: #64748B; line-height: 1.8; margin-bottom: 10px; }
.disc-explain-item { margin-bottom: 2px; }
.disc-explain-conclusion {
  margin-top: 8px; padding: 8px 12px; background: #fef2f2; border-left: 3px solid #E11D48;
  border-radius: 0 6px 6px 0; font-size: 13px; color: #475569;
}
.disc-actions { display: flex; gap: 8px; justify-content: flex-end; }
.disc-toggle { font-size: 12px; color: #64748B; cursor: pointer; padding: 6px 0; }
.disc-toggle:hover { color: var(--sa-primary); }
</style>
