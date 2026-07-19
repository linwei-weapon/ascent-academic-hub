<template>
  <div class="decision-page">
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item>
      <el-breadcrumb-item>决策研判</el-breadcrumb-item>
    </el-breadcrumb>

    <header class="page-head">
      <div>
        <h2 class="sa-page-title">决策研判</h2>
        <p class="sa-page-sub">无需学习“Skill”操作：从学校预设的管理问题出发，由管理专家组织事实、约束、方案和证据；临时研判不写入业务数据。</p>
      </div>
      <el-tag type="info" effect="plain">管理测算，不是审批结论</el-tag>
    </header>

    <section class="step-card sa-card">
      <StepTitle :number="1" title="选择本次要解决的管理问题" tip="每个问题由一个版本化管理专家负责，学校可调整白名单阈值和默认参数" />
      <div class="problem-grid">
        <button
          v-for="item in problemOptions"
          :key="item.expertId"
          class="problem-card"
          :class="{ active: selectedExpertId === item.expertId }"
          @click="chooseExpert(item)"
        >
          <span>{{ (item.owners || []).join(' / ') }} · {{ item.version?.version }}</span>
          <b>{{ item.name }}</b>
          <p>{{ item.managementQuestion }}</p>
          <small>{{ item.description }}</small>
        </button>
      </div>
      <div v-if="expertRuntime.expertId" class="expert-context">
        <div><span>当前专家</span><b>{{ expertRuntime.expertName }} · {{ expertRuntime.expertVersion }}</b></div>
        <div><span>分析范围</span><b>{{ scopeLabel }}</b></div>
        <div><span>数据条件</span><b :class="{ ready: expertRuntime.dataReadiness?.ready }">{{ expertRuntime.dataReadiness?.ready ? '所需数据已接入' : '存在必需数据缺口' }}</b></div>
        <div><span>会话边界</span><b>临时条件不改变正式口径</b></div>
      </div>
    </section>

    <section v-if="expertRuntime.expertId" class="dialogue-card sa-card">
      <div class="dialogue-head">
        <div>
          <b>和管理专家继续讨论</b>
          <p>可用自然语言调整本次临时条件；系统会先复述理解，再局部重算，不改变正式口径和数据权限。</p>
        </div>
        <div class="dialogue-actions">
          <el-button size="small" :disabled="interpreting" @click="askExpert('恢复正式口径')">恢复正式口径</el-button>
          <el-button v-if="canManageSchemes" size="small" type="primary" plain @click="saveScheme">保存为学校方案草稿</el-button>
        </div>
      </div>
      <div class="understood-scope">
        <span>我理解的范围：{{ scopeLabel }}</span>
        <span>学期：{{ sessionSemester || data.semester || '当前数据学期' }}</span>
        <span>专家：{{ expertRuntime.expertName }} · {{ expertRuntime.expertVersion }}</span>
        <span>临时条件：{{ temporaryConditionText }}</span>
      </div>
      <div class="question-chips">
        <button v-for="question in expertRuntime.recommendedQuestions || []" :key="question" @click="askExpert(question)">
          {{ question }}
        </button>
      </div>
      <div class="conversation">
        <article v-for="(message,index) in messages" :key="index" :class="message.role">
          <span>{{ message.role === 'user' ? '你' : expertRuntime.expertName }}</span>
          <p>{{ message.text }}</p>
          <small v-if="message.detail">{{ message.detail }}</small>
        </article>
      </div>
      <div class="composer">
        <el-input v-model="chatInput" type="textarea" :rows="2" maxlength="500"
          placeholder="例如：如果可协调5名教师，每班40人，优先处理明确未通过学生"
          @keydown.ctrl.enter.prevent="submitMessage" />
        <el-button type="primary" :loading="interpreting" :disabled="!chatInput.trim()" @click="submitMessage">
          发送并重新研判
        </el-button>
      </div>
      <p class="composer-tip">Ctrl + Enter 发送。对话只能缩小或调整当前授权范围内的临时条件，不能切换到其他学院或全校。</p>
    </section>

    <el-alert
      v-if="loading"
      class="loading-alert"
      type="info"
      :closable="false"
      show-icon
      title="正在汇总当前问题的事实基线"
      description="系统正在读取培养方案课程完成证据、开课供给、课程团队和替代关系，并按当前管理目标比较候选方案。"
    />

    <el-skeleton :loading="loading" animated :rows="8">
      <template v-if="data.problem">
        <section class="step-card sa-card">
          <StepTitle :number="2" title="先确认当前基线和为什么现在要决策" tip="基线不准确时，不应继续调参数" />
          <div class="baseline-hero">
            <div>
              <el-tag type="danger" effect="plain">{{ data.expert?.name || '当前管理问题' }} · {{ data.expert?.version || '—' }}</el-tag>
              <h3>{{ data.problem.question }}</h3>
              <p>{{ data.problem.why }}</p>
            </div>
            <div class="goal-box">
              <span>本次决策目标</span>
              <b>{{ data.problem.goal }}</b>
            </div>
          </div>
          <div class="baseline-grid">
            <div v-for="item in (data.metrics || []).slice(0,4)" :key="item.label">
              <span>{{ item.label }}</span><b>{{ item.value }}{{ item.unit }}</b><small>{{ item.hint }}</small>
            </div>
          </div>
          <el-alert type="info" :closable="false" show-icon title="口径边界" :description="data.expert?.boundaries?.join('；') || trace.boundary" />
        </section>

        <section class="step-card sa-card">
          <StepTitle :number="3" title="设置本场景真实可用的约束" tip="只填能够被学校确认的资源，不把理想值当成可用资源" />
          <div class="constraint-grid">
            <label v-if="params.problemType !== 'faculty_assurance'">
              <span>最多可新增班级</span>
              <el-input-number v-model="params.addedClasses" :min="0" :max="20" />
              <small>用于测算重修/补修班，不代表已经批准</small>
            </label>
            <label v-if="params.problemType !== 'faculty_assurance'">
              <span>单班计划容量</span>
              <el-input-number v-model="params.classCapacity" :min="15" :max="120" :step="5" />
              <small>应按学校常用班额填写</small>
            </label>
            <label>
              <span>{{ params.problemType === 'faculty_assurance' ? '可协调备份教师' : '可协调教师' }}</span>
              <el-input-number v-model="params.availableTeachers" :min="0" :max="20" />
              <small>只填写当前确有协调可能的教师数量</small>
            </label>
            <label v-if="params.problemType === 'graduation'">
              <span>本轮优先目标</span>
              <el-select v-model="params.priorityFocus">
                <el-option label="先核验再分流" value="balanced" />
                <el-option label="优先处理明确未通过" value="failed" />
                <el-option label="优先核验缺证据" value="verification" />
              </el-select>
              <small>影响方案排序，不改变原始数据</small>
            </label>
            <label v-if="params.problemType === 'course_support'">
              <span>本轮优先支持课程</span>
              <el-input-number v-model="params.supportCourseLimit" :min="1" :max="20" />
              <small>限制本轮候选课程数量，避免资源平均摊薄</small>
            </label>
            <label v-if="params.problemType === 'course_support'">
              <span>显著波动阈值</span>
              <el-input-number v-model="params.significantChangePp" :min="3" :max="30" :step="1" />
              <small>单位为百分点，用于解释最高与最低未通过率之差</small>
            </label>
            <label v-if="params.problemType === 'faculty_assurance'">
              <span>高影响覆盖阈值</span>
              <el-input-number v-model="params.minimumStudents" :min="50" :max="1000" :step="50" />
              <small>单教师课程达到该学生覆盖规模时进入重点核查</small>
            </label>
          </div>
          <div class="constraint-action">
            <span v-if="params.problemType !== 'faculty_assurance'">当前最多形成 {{ usableClasses }} 个新增班，计划容量 {{ usableClasses * params.classCapacity }} 人次。</span>
            <span v-else>当前最多为 {{ params.availableTeachers }} 门高影响课程安排一名备份教师。</span>
            <el-button type="primary" :loading="loading" @click="load">按当前约束重新测算</el-button>
          </div>
        </section>

        <section class="step-card sa-card">
          <StepTitle :number="4" title="用同一组管理结果比较候选方案" tip="不展示不可解释的综合分数，先看覆盖、剩余问题、资源和不确定性" />
          <div class="recommendation-line">
            <div>
              <span>系统建议优先作为候选</span>
              <b>{{ data.recommendation?.bestScenarioTitle }}</b>
              <p>{{ data.recommendation?.reason }}</p>
            </div>
            <el-tag type="warning" effect="plain">建议不等于自动采用</el-tag>
          </div>
          <el-table :data="data.scenarios || []" stripe class="comparison-table">
            <el-table-column label="候选方案" min-width="210">
              <template #default="{ row }">
                <div class="scenario-name">
                  <el-tag v-if="row.recommended" type="danger" size="small">系统建议</el-tag>
                  <b>{{ row.title }}</b>
                  <small>{{ row.bestFor }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="预计影响" width="105" align="right">
              <template #default="{ row }"><b class="impact-number">{{ row.estimatedStudents }}</b> 人次</template>
            </el-table-column>
            <el-table-column label="剩余问题" min-width="150">
              <template #default="{ row }"><b>{{ row.remainingGap }}</b><small class="block">{{ row.remainingLabel }}</small></template>
            </el-table-column>
            <el-table-column label="资源成本" min-width="190">
              <template #default="{ row }"><b>{{ row.costLevel }}成本 · {{ row.implementationDifficulty }}难度</b><small class="block">{{ row.resourceUse }}</small></template>
            </el-table-column>
            <el-table-column label="不确定性" min-width="190">
              <template #default="{ row }"><span>{{ row.uncertainty }}</span></template>
            </el-table-column>
            <el-table-column label="选择" width="110" fixed="right">
              <template #default="{ row }">
                <el-button :type="selectedScenarioId === row.id ? 'primary' : 'default'" size="small" @click="selectedScenarioId = row.id">
                  {{ selectedScenarioId === row.id ? '已选候选' : '选为候选' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="selectedScenario" class="step-card decision-sheet sa-card">
          <StepTitle :number="5" title="形成候选决策单，再进入专题核查证据" tip="这里只形成管理讨论稿，不直接生成开班、认定或教师安排" />
          <div class="sheet-head">
            <div>
              <span>候选方案</span>
              <h3>{{ selectedScenario.title }}</h3>
              <p>{{ selectedScenario.logic }}</p>
            </div>
            <div class="sheet-result"><b>{{ selectedScenario.estimatedStudents }}</b><span>预计影响人次</span></div>
          </div>
          <div class="sheet-grid">
            <div><span>采用条件</span><b>{{ selectedScenario.decisionCondition }}</b></div>
            <div><span>资源要求</span><b>{{ selectedScenario.resourceUse }}</b></div>
            <div><span>仍余问题</span><b>{{ selectedScenario.remainingGap }}人次 · {{ selectedScenario.remainingLabel }}</b></div>
            <div><span>不建议采用的情况</span><b>{{ selectedScenario.notRecommendedWhen }}</b></div>
          </div>
          <div class="checklist">
            <b>形成正式安排前必须核查</b>
            <ol><li v-for="item in data.decisionChecklist || []" :key="item">{{ item }}</li></ol>
          </div>
          <div class="sheet-actions">
            <el-button @click="showEvidence = !showEvidence">{{ showEvidence ? '收起课程证据' : '查看本次课程证据' }}</el-button>
            <el-button type="primary" @click="enterEvidence">{{ data.problem.routeLabel }}</el-button>
          </div>
          <el-table v-if="showEvidence" :data="(data.courses || []).slice(0, 10)" stripe class="evidence-table">
            <el-table-column prop="courseName" label="课程" min-width="190" />
            <el-table-column prop="failedStudents" label="明确未通过" width="105" align="right" />
            <el-table-column prop="verificationStudents" label="待核验证据" width="105" align="right" />
            <el-table-column label="供给/团队" width="140"><template #default="{ row }">{{ row.lessonCount }}班 / {{ row.teacherCount }}教师</template></el-table-column>
            <el-table-column label="需要核查" min-width="230"><template #default="{ row }">{{ (row.bottlenecks || []).join('；') }}</template></el-table-column>
          </el-table>
        </section>

        <section class="trace-card sa-card">
          <el-collapse>
            <el-collapse-item name="trace" title="查看数据来源、计算口径与模拟边界">
              <el-descriptions :column="1" border>
                <el-descriptions-item label="技术来源">{{ listText(trace.dataSources) }}</el-descriptions-item>
                <el-descriptions-item label="计算逻辑">{{ trace.calculationLogic }}</el-descriptions-item>
                <el-descriptions-item label="命中规则">{{ listText(trace.rules) }}</el-descriptions-item>
                <el-descriptions-item label="公式/口径">{{ trace.formula }}</el-descriptions-item>
                <el-descriptions-item label="使用边界">{{ trace.boundary }}</el-descriptions-item>
              </el-descriptions>
            </el-collapse-item>
          </el-collapse>
        </section>
      </template>
    </el-skeleton>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getAIExpertCatalog, getAIExpertRuntime, getGraduationCourseSupportSimulation,
  interpretAIExpertMessage, saveAIAnalysisScheme,
} from '@/utils/ai'
import { authStore } from '@/store/auth'

type ProblemType = 'graduation' | 'course_support' | 'faculty_assurance'

const StepTitle = defineComponent({
  props: { number: { type: Number, required: true }, title: { type: String, required: true }, tip: { type: String, required: true } },
  setup(props) {
    return () => h('div', { class: 'step-title' }, [
      h('span', { class: 'step-number' }, String(props.number)),
      h('div', [h('b', props.title), h('small', props.tip)]),
    ])
  },
})

const router = useRouter()
const route = useRoute()
const sessionSemester = String(route.query.semester || '')
const loading = ref(false)
const showEvidence = ref(false)
const selectedScenarioId = ref('')
const selectedExpertId = ref('')
const chatInput = ref('')
const interpreting = ref(false)
const messages = ref<Array<{ role: 'assistant' | 'user'; text: string; detail?: string }>>([])
const data = reactive<any>({})
const expertCatalog = reactive<any>({ experts: [] })
const expertRuntime = reactive<any>({})
const params = reactive({
  problemType: 'graduation' as ProblemType,
  addedClasses: 3,
  classCapacity: 30,
  availableTeachers: 3,
  priorityFocus: 'balanced' as 'balanced' | 'failed' | 'verification',
  supportCourseLimit: 5,
  significantChangePp: 8,
  minimumStudents: 300,
})

const problemOptions = computed<any[]>(() => expertCatalog.experts || [])
const scenarioByExpert: Record<string, ProblemType> = {
  'graduation-readiness': 'graduation',
  'high-impact-course-support': 'course_support',
  'course-team-continuity': 'faculty_assurance',
}
const focusLabels: Record<string, string> = {
  balanced: '先核验再分流',
  failed: '明确未通过优先',
  verification: '待核验证据优先',
}
const parameterLabels: Record<string, string> = {
  addedClasses: '新增班数',
  classCapacity: '单班容量',
  availableTeachers: '可协调教师',
  priorityFocus: '研判侧重',
  supportCourseLimit: '优先支持课程',
  significantChangePp: '显著波动阈值',
  minimumStudents: '高影响覆盖阈值',
}

const trace = computed(() => data.traceability || {})
const usableClasses = computed(() => Math.min(params.addedClasses, params.availableTeachers))
const selectedScenario = computed(() => (data.scenarios || []).find((item: any) => item.id === selectedScenarioId.value))
const scopeLabel = computed(() => {
  const scope = expertRuntime.scope || expertCatalog.scope || {}
  if (scope.scopeType === 'all') return `${scope.roleName || '当前角色'} · 全校`
  if (scope.scopeType === 'college') return `${scope.roleName || '当前角色'} · 本学院`
  return `${scope.roleName || '当前角色'} · 当前授权范围`
})
const canManageSchemes = computed(() => (
  authStore.user?.permissionContext?.actionPermissions || []
).includes('system.manage'))
const temporaryConditionText = computed(() => {
  if (params.problemType === 'graduation') {
    return `新增班≤${params.addedClasses}，单班${params.classCapacity}人，可协调教师${params.availableTeachers}人，侧重${focusLabels[params.priorityFocus] || params.priorityFocus}`
  }
  if (params.problemType === 'course_support') {
    return `优先支持${params.supportCourseLimit}门，显著波动${params.significantChangePp}个百分点，可协调教师${params.availableTeachers}人`
  }
  return `高影响覆盖≥${params.minimumStudents}人次，可协调备份教师${params.availableTeachers}人`
})

function listText(value: unknown) {
  return Array.isArray(value) ? value.join('；') : String(value || '—')
}

function parameterChangeText(key: string, value: unknown) {
  const label = parameterLabels[key] || key
  if (key === 'priorityFocus') return `${label}：${focusLabels[String(value)] || value}`
  const unit = key === 'classCapacity' || key === 'minimumStudents'
    ? '人'
    : key === 'availableTeachers' ? '名'
      : key === 'addedClasses' ? '个'
        : key === 'supportCourseLimit' ? '门'
          : key === 'significantChangePp' ? '个百分点' : ''
  return `${label}：${value}${unit}`
}

async function chooseExpert(item: any) {
  const type = scenarioByExpert[item.expertId] || item.simulatorScenario || 'graduation'
  if (selectedExpertId.value === item.expertId && data.problem) return
  selectedExpertId.value = item.expertId
  params.problemType = type
  if (type === 'course_support') params.priorityFocus = 'failed'
  else if (type === 'faculty_assurance') params.priorityFocus = 'balanced'
  else params.priorityFocus = 'balanced'
  await loadExpertRuntime(item.expertId, true)
  resetConversation(item.managementQuestion)
  await load()
}

async function loadExpertRuntime(expertId: string, applyDefaults = false) {
  const result = await getAIExpertRuntime(expertId, sessionSemester || undefined)
  Object.keys(expertRuntime).forEach((key) => delete expertRuntime[key])
  Object.assign(expertRuntime, result)
  if (!applyDefaults) return
  const runtimeParams = result.parameters || {}
  if (runtimeParams.addedClasses) params.addedClasses = runtimeParams.addedClasses.value
  if (runtimeParams.classCapacity) params.classCapacity = runtimeParams.classCapacity.value
  if (runtimeParams.availableTeachers) params.availableTeachers = runtimeParams.availableTeachers.value
  if (runtimeParams.priorityFocus) params.priorityFocus = runtimeParams.priorityFocus.value
  if (runtimeParams.supportCourseLimit) params.supportCourseLimit = runtimeParams.supportCourseLimit.value
  if (runtimeParams.significantChangePp) params.significantChangePp = runtimeParams.significantChangePp.value
  if (runtimeParams.minimumStudents) params.minimumStudents = runtimeParams.minimumStudents.value
}

async function loadExperts() {
  const result = await getAIExpertCatalog()
  Object.assign(expertCatalog, result)
  const requested = String(route.query.expert || '')
  const first = problemOptions.value.find((item) => item.expertId === requested) || problemOptions.value[0]
  if (!first) return
  selectedExpertId.value = first.expertId
  params.problemType = scenarioByExpert[first.expertId] || first.simulatorScenario || 'graduation'
  await loadExpertRuntime(first.expertId, true)
  resetConversation(String(route.query.question || first.managementQuestion || ''))
}

function resetConversation(question: string) {
  messages.value = [{
    role: 'assistant',
    text: question || '请选择上方推荐问题，或直接说明本次可用资源和关注重点。',
    detail: '我会在当前工作身份和数据范围内解释条件，不会修改学校正式指标。',
  }]
}

async function askExpert(question: string) {
  chatInput.value = question
  await submitMessage()
}

async function submitMessage() {
  const message = chatInput.value.trim()
  if (!message || interpreting.value) return
  messages.value.push({ role: 'user', text: message })
  chatInput.value = ''
  interpreting.value = true
  try {
    const result = await interpretAIExpertMessage(selectedExpertId.value, {
      message,
      scopeFingerprint: expertRuntime.scope?.scopeFingerprint || expertCatalog.scope?.scopeFingerprint || '',
      currentParameters: { ...params },
      semester: sessionSemester || undefined,
    })
    for (const [key, value] of Object.entries(result.parameterChanges || {})) {
      if (key in params) (params as any)[key] = value
    }
    const changed = Object.entries(result.parameterChanges || {})
      .map(([key, value]) => parameterChangeText(key, value)).join('；')
    const groundedResponse = !result.understood && !result.scopeRequest?.blocked && data.summary
      ? `基于当前已加载的专家结果：${data.summary}${data.recommendation?.reason ? ` ${data.recommendation.reason}` : ''}`
      : result.response
    messages.value.push({
      role: 'assistant',
      text: groundedResponse,
      detail: result.scopeRequest?.blocked
        ? `权限边界：${result.scopeRequest.message}`
        : changed ? `已理解的临时条件：${changed}` : '未改变当前临时条件。',
    })
    if (result.recalculate) await load()
  } catch (error: any) {
    messages.value.push({ role: 'assistant', text: error?.message || '本次条件解释失败，请重新表述。' })
  } finally {
    interpreting.value = false
  }
}

async function saveScheme() {
  try {
    const result = await ElMessageBox.prompt(
      '保存的是学校分析方案草稿，不会立即发布，也不会保存越权数据范围。',
      '保存学校分析方案',
      { inputPlaceholder: `例如：${expertRuntime.expertName}常用方案`, inputValue: `${expertRuntime.expertName}常用方案` },
    )
    const parameterKeys = Object.keys(expertRuntime.parameters || {})
    const schemeParameters = Object.fromEntries(
      parameterKeys.map((key) => [key, (params as any)[key]]),
    )
    await saveAIAnalysisScheme(selectedExpertId.value, {
      name: result.value,
      parameters: schemeParameters,
      changeReason: '由决策研判工作区保存，待管理员发布',
    })
    ElMessage.success('已保存为草稿；发布后才会成为学校正式分析方案')
  } catch {
    // 用户取消保存时不产生草稿，也不提示错误。
  }
}

async function load() {
  loading.value = true
  showEvidence.value = false
  try {
    const result = await getGraduationCourseSupportSimulation({
      limit: 12,
      ...params,
      expertId: selectedExpertId.value,
      semester: sessionSemester || undefined,
    })
    Object.keys(data).forEach((key) => delete data[key])
    Object.assign(data, result)
    selectedScenarioId.value = result.recommendation?.bestScenarioId || result.scenarios?.[0]?.id || ''
  } finally {
    loading.value = false
  }
}

function enterEvidence() {
  if (data.problem?.route) router.push(data.problem.route)
}

onMounted(async () => {
  loading.value = true
  try {
    await loadExperts()
    await load()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.decision-page { padding-bottom: 18px; }
.page-head { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
.step-card { margin-top:14px; }
.step-title { display:flex; gap:10px; align-items:flex-start; margin-bottom:14px; }
.step-number { display:grid; place-items:center; width:28px; height:28px; flex:0 0 28px; border-radius:50%; background:#4f46e5; color:#fff; font-weight:700; }
.step-title b { display:block; color:#172554; font-size:16px; }
.step-title small { display:block; margin-top:4px; color:#64748b; font-size:12px; }
.problem-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.problem-card { padding:16px; border:1px solid #dbe3ef; border-radius:12px; background:#fff; text-align:left; cursor:pointer; transition:.18s ease; }
.problem-card:hover { border-color:#818cf8; transform:translateY(-1px); }
.problem-card.active { border:2px solid #4f46e5; background:#eef2ff; box-shadow:0 8px 20px rgba(79,70,229,.1); }
.problem-card span,.problem-card small { display:block; color:#64748b; font-size:11px; }
.problem-card b { display:block; margin:7px 0 5px; color:#1e293b; font-size:17px; }
.problem-card p { margin:0 0 10px; color:#334155; font-size:13px; }
.problem-card small { color:#4f46e5; }
.expert-context { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:12px; padding:12px; border-radius:10px; background:#f8fafc; border:1px solid #e2e8f0; }
.expert-context span { display:block; color:#64748b; font-size:11px; }
.expert-context b { display:block; margin-top:4px; color:#334155; font-size:12px; line-height:1.5; }
.expert-context b.ready { color:#047857; }
.dialogue-card { margin-top:14px; border:1px solid #c7d2fe; background:linear-gradient(180deg,#fff 0%,#f8faff 100%); }
.dialogue-head { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
.dialogue-head b { color:#1e1b4b; font-size:16px; }
.dialogue-head p { margin:5px 0 0; color:#64748b; font-size:12px; }
.dialogue-actions { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.understood-scope { display:flex; flex-wrap:wrap; gap:8px 16px; margin:12px 0; padding:10px 12px; border-radius:9px; background:#eef2ff; color:#4338ca; font-size:11px; }
.question-chips { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
.question-chips button { border:1px solid #c7d2fe; border-radius:999px; background:#fff; color:#4338ca; padding:6px 10px; cursor:pointer; font-size:11px; }
.question-chips button:hover { background:#eef2ff; }
.conversation { display:grid; gap:9px; max-height:280px; overflow:auto; padding:10px; border:1px solid #e2e8f0; border-radius:10px; background:#fff; }
.conversation article { max-width:85%; padding:9px 12px; border-radius:10px; background:#f1f5f9; }
.conversation article.user { justify-self:end; background:#4f46e5; color:#fff; }
.conversation article span { display:block; margin-bottom:4px; color:#64748b; font-size:10px; }
.conversation article.user span { color:#c7d2fe; }
.conversation article p { margin:0; font-size:12px; line-height:1.65; }
.conversation article small { display:block; margin-top:5px; color:#64748b; font-size:10px; line-height:1.5; }
.conversation article.user small { color:#e0e7ff; }
.composer { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:end; margin-top:10px; }
.composer-tip { margin:6px 0 0; color:#94a3b8; font-size:10px; }
.loading-alert { margin:14px 0; }
.baseline-hero { display:grid; grid-template-columns:1.35fr 1fr; gap:14px; margin-bottom:12px; }
.baseline-hero > div { padding:16px; border-radius:12px; background:#f8fafc; border:1px solid #e2e8f0; }
.baseline-hero h3 { margin:8px 0; color:#172554; font-size:19px; }
.baseline-hero p { margin:0; color:#475569; line-height:1.7; font-size:13px; }
.goal-box span { display:block; color:#d97706; font-size:12px; font-weight:700; }
.goal-box b { display:block; margin-top:8px; color:#334155; line-height:1.75; font-size:14px; }
.baseline-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:12px; }
.baseline-grid > div { padding:13px; border:1px solid #e2e8f0; border-radius:10px; }
.baseline-grid span,.baseline-grid small { display:block; color:#64748b; font-size:11px; }
.baseline-grid b { display:block; margin:5px 0; color:#e11d48; font-size:22px; }
.constraint-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.constraint-grid label { display:grid; gap:6px; color:#475569; font-size:12px; }
.constraint-grid small { color:#94a3b8; line-height:1.45; }
.constraint-grid :deep(.el-input-number),.constraint-grid :deep(.el-select) { width:100%; }
.constraint-action { display:flex; justify-content:space-between; gap:12px; align-items:center; margin-top:14px; padding-top:12px; border-top:1px dashed #dbe3ef; color:#64748b; font-size:12px; }
.recommendation-line { display:flex; justify-content:space-between; gap:16px; padding:14px; margin-bottom:12px; background:#fffbeb; border:1px solid #fde68a; border-radius:10px; }
.recommendation-line span { color:#a16207; font-size:11px; }
.recommendation-line b { display:block; margin:5px 0; color:#78350f; }
.recommendation-line p { margin:0; color:#92400e; font-size:12px; line-height:1.6; }
.scenario-name { display:grid; gap:5px; }
.scenario-name small,.block { display:block; margin-top:4px; color:#64748b; font-size:11px; line-height:1.45; }
.impact-number { color:#e11d48; font-size:19px; }
.decision-sheet { border:1px solid #c7d2fe; background:linear-gradient(180deg,#fff 0%,#f8faff 100%); }
.sheet-head { display:flex; justify-content:space-between; gap:16px; padding:15px; background:#eef2ff; border-radius:11px; }
.sheet-head span { color:#4f46e5; font-size:11px; font-weight:700; }
.sheet-head h3 { margin:5px 0; color:#1e1b4b; }
.sheet-head p { margin:0; color:#475569; font-size:12px; line-height:1.6; }
.sheet-result { min-width:120px; text-align:center; align-self:center; }
.sheet-result b { display:block; color:#e11d48; font-size:30px; }
.sheet-result span { color:#64748b; }
.sheet-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin:12px 0; }
.sheet-grid > div { padding:12px; background:#fff; border:1px solid #e2e8f0; border-radius:9px; }
.sheet-grid span { display:block; color:#64748b; font-size:11px; }
.sheet-grid b { display:block; margin-top:5px; color:#334155; font-size:12px; line-height:1.6; }
.checklist { padding:12px 14px; background:#fff; border-left:4px solid #4f46e5; }
.checklist b { color:#1e293b; }
.checklist ol { margin:8px 0 0; padding-left:20px; color:#475569; font-size:12px; line-height:1.8; }
.sheet-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:12px; }
.evidence-table { margin-top:12px; }
.trace-card { margin-top:14px; }
.trace-card :deep(.el-collapse-item__header) { color:#4f46e5; font-weight:600; }
@media (max-width:1100px) { .problem-grid,.baseline-grid,.constraint-grid,.expert-context { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:760px) { .page-head,.baseline-hero,.sheet-head,.constraint-action,.dialogue-head { display:block; } .problem-grid,.baseline-grid,.constraint-grid,.sheet-grid,.expert-context,.composer { grid-template-columns:1fr; } .sheet-actions { justify-content:stretch; } }
</style>
