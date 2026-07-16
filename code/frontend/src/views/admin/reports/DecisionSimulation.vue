<template>
  <div class="decision-page">
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item>
      <el-breadcrumb-item>AI决策模拟</el-breadcrumb-item>
    </el-breadcrumb>

    <header class="page-head">
      <div>
        <h2 class="sa-page-title">AI决策模拟</h2>
        <p class="sa-page-sub">从管理问题出发，逐步查看基线、设置约束、比较方案并形成候选决策单；模拟不写入业务数据。</p>
      </div>
      <el-tag type="info" effect="plain">管理测算，不是审批结论</el-tag>
    </header>

    <section class="step-card sa-card">
      <StepTitle :number="1" title="选择本次要解决的管理问题" tip="一次只比较一个问题，避免把不同目标混成综合分数" />
      <div class="problem-grid">
        <button
          v-for="item in problemOptions"
          :key="item.type"
          class="problem-card"
          :class="{ active: params.problemType === item.type }"
          @click="chooseProblem(item.type)"
        >
          <span>{{ item.owner }}</span>
          <b>{{ item.title }}</b>
          <p>{{ item.question }}</p>
          <small>{{ item.output }}</small>
        </button>
      </div>
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
              <el-tag type="danger" effect="plain">当前管理问题</el-tag>
              <h3>{{ data.problem.question }}</h3>
              <p>{{ data.problem.why }}</p>
            </div>
            <div class="goal-box">
              <span>本次决策目标</span>
              <b>{{ data.problem.goal }}</b>
            </div>
          </div>
          <div class="baseline-grid">
            <div><span>候选课程</span><b>{{ metricValue('模拟课程') }}门</b><small>本次纳入比较的重点必修课程</small></div>
            <div><span>涉及学生</span><b>{{ metricValue('涉及学生') }}人</b><small>问题证据涉及的去重学生</small></div>
            <div><span>明确未通过</span><b>{{ metricValue('明确未通过') }}人次</b><small>已有失败证据，需要课程处理路径</small></div>
            <div><span>到期缺证据</span><b>{{ metricValue('到期缺证据') }}人次</b><small>先核验认定、替代或数据回写</small></div>
          </div>
          <el-alert type="info" :closable="false" show-icon title="口径边界" description="涉及学生为去重人数；课程缺口按人次汇总，同一学生涉及多门课程时会重复计算。" />
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
import { useRouter } from 'vue-router'
import { getGraduationCourseSupportSimulation } from '@/utils/ai'

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
const loading = ref(false)
const showEvidence = ref(false)
const selectedScenarioId = ref('')
const data = reactive<any>({})
const params = reactive({
  problemType: 'graduation' as ProblemType,
  addedClasses: 3,
  classCapacity: 30,
  availableTeachers: 3,
  priorityFocus: 'balanced' as 'balanced' | 'failed' | 'verification',
})

const problemOptions: Array<{ type: ProblemType; owner: string; title: string; question: string; output: string }> = [
  { type: 'graduation', owner: '教务处 / 二级学院', title: '毕业准备', question: '先核验还是先开班？', output: '输出学生课程处理和重修资源候选方案' },
  { type: 'course_support', owner: '教务处 / 开课学院', title: '课程支持', question: '有限资源优先投入哪些课程？', output: '输出课程支持优先序和资源要求' },
  { type: 'faculty_assurance', owner: '教务处 / 开课学院', title: '师资保障', question: '有限备份能力优先保障哪些课程？', output: '输出高影响课程团队保障候选方案' },
]

const trace = computed(() => data.traceability || {})
const usableClasses = computed(() => Math.min(params.addedClasses, params.availableTeachers))
const selectedScenario = computed(() => (data.scenarios || []).find((item: any) => item.id === selectedScenarioId.value))

function metricValue(label: string) {
  return (data.metrics || []).find((item: any) => item.label === label)?.value ?? '—'
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.join('；') : String(value || '—')
}

async function chooseProblem(type: ProblemType) {
  if (params.problemType === type && data.problem) return
  params.problemType = type
  if (type === 'course_support') params.priorityFocus = 'failed'
  else if (type === 'faculty_assurance') params.priorityFocus = 'balanced'
  else params.priorityFocus = 'balanced'
  await load()
}

async function load() {
  loading.value = true
  showEvidence.value = false
  try {
    const result = await getGraduationCourseSupportSimulation({ limit: 12, ...params })
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

onMounted(load)
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
@media (max-width:1100px) { .problem-grid,.baseline-grid,.constraint-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:760px) { .page-head,.baseline-hero,.sheet-head,.constraint-action { display:block; } .problem-grid,.baseline-grid,.constraint-grid,.sheet-grid { grid-template-columns:1fr; } .sheet-actions { justify-content:stretch; } }
</style>
