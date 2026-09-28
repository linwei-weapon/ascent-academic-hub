<!-- 专家团研究工作区：保留来源提交的业务与交互，归入 AI 管理决策模块。 -->
<template>
  <div class="team-workspace" aria-label="专家团工作区">
    <aside class="expert-side">
      <div class="side-heading"><h2>专家团</h2><p>选择专业视角，研究具体问题</p></div>
      <div class="side-switch" aria-label="导航内容">
        <button :class="{ active: navigation === 'experts' }" @click="navigation = 'experts'">专家目录</button>
        <button :class="{ active: navigation === 'history' }" @click="openHistory">最近讨论</button>
      </div>
      <template v-if="navigation === 'experts'">
        <section v-for="group in ['建设与改进', '培养与资格']" :key="group" class="expert-group">
          <p class="group-label">{{ group }}</p>
          <button v-for="item in experts.filter(e => e.group === group)" :key="item.id" class="expert-item"
            :class="{ selected: item.id === expertId }" :aria-current="item.id === expertId ? 'page' : undefined"
            :disabled="busy" @click="switchExpert(item.id)">
            <el-icon :size="19"><component :is="expertIcons[item.id]" /></el-icon>
            <span><b>{{ item.name }}</b><small>{{ item.purpose }}</small></span>
          </button>
        </section>
      </template>
      <section v-else class="history-list">
        <p class="group-label">当前工作身份的讨论 · 最近 50 条</p>
        <button v-for="item in history" :key="item.id" :disabled="busy" :class="{ selected: session?.id === item.id }" @click="loadHistory(item.id)">
          <b>{{ item.title }}</b><small>{{ expertName(item.expert_id) }} · {{ date(item.updated_at) }}</small>
        </button>
        <p v-if="!history.length" class="empty-history">还没有保存的讨论</p>
      </section>
      <button class="new-discussion" :disabled="busy" @click="newDiscussion"><el-icon><Plus /></el-icon> 发起新讨论</button>
      <p class="side-footer">原决策简报与专家分析继续保留</p>
    </aside>

    <main class="team-main" aria-live="polite">
      <div v-if="error" class="error-banner" role="alert">{{ error }} <button :disabled="busy" @click="retry">重试</button></div>
      <template v-if="expert">
        <header class="workspace-heading">
          <div><p class="eyebrow">{{ expert.group }} <span>· {{ scopeLabel }}</span></p><h1>{{ expert.name }}</h1></div>
          <div class="header-actions" v-if="session">
            <el-button :disabled="busy" @click="saveDiscussion">保存本次</el-button>
            <el-button :disabled="busy" @click="sourceOpen = true">查看依据</el-button>
            <el-button v-if="expertId === 'graduation' && result?.snapshot?.population" :disabled="busy || contextChanged" @click="saveStage">保存阶段记录</el-button>
          </div>
        </header>
        <p class="workspace-intro">{{ expert.question }}</p>
        <nav class="scenario-tabs" aria-label="管理场景">
          <button v-for="s in expert.scenarios" :key="s.id" :class="{ active: scenario === s.id }"
            :disabled="busy" :aria-pressed="scenario === s.id" @click="chooseScenario(s.id)">{{ s.name }}</button>
        </nav>
        <section class="context-form" aria-label="分析对象">
          <label><span>{{ expertId === 'transfer' ? '来源专业与方案' : '专业与培养方案' }}</span>
            <el-select v-model="planId" filterable placeholder="选择培养方案" :disabled="busy" aria-label="专业与培养方案" @change="changePlan">
              <el-option v-for="p in plans" :key="p.plan_id" :label="p.plan_name" :value="p.plan_id" />
            </el-select>
          </label>
          <label v-if="['program', 'transfer'].includes(expertId)"><span>比较对象</span>
            <el-select v-model="targetId" filterable clearable placeholder="自动寻找最接近的专业" :disabled="busy" aria-label="比较对象">
              <el-option label="自动寻找最接近的专业" value="" />
              <el-option v-for="p in comparablePlans" :key="p.plan_id" :label="p.plan_name" :value="p.plan_id" />
            </el-select>
          </label>
          <label v-if="expertId === 'course'"><span>成绩学期</span>
            <el-select v-model="semester" clearable placeholder="最近有成绩的学期" :disabled="busy" aria-label="成绩学期">
              <el-option v-for="term in semesters" :key="term" :label="term" :value="term" />
            </el-select>
          </label>
          <label v-if="expertId === 'program'"><span>比较口径</span>
            <el-select v-model="focus" :disabled="busy" aria-label="比较口径">
              <el-option v-for="(label, key) in focusLabels" :key="key" :label="label" :value="key" />
            </el-select>
          </label>
          <label v-if="expertId === 'course' && scenario !== 'priority'"><span>本次课程</span>
            <el-select v-model="selectedCourseId" filterable clearable :disabled="busy || !courseOptions.length" placeholder="分析后可选择具体课程" aria-label="本次课程">
              <el-option v-for="c in courseOptions" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </label>
          <label v-if="expertId === 'graduation' && scenario === 'changes'"><span>对照记录</span>
            <el-select v-model="baselineId" clearable :disabled="busy" placeholder="最近一次保存的阶段记录" aria-label="对照记录">
              <el-option v-for="b in baselineOptions" :key="b.id" :value="b.id" :label="date(b.created_at)" />
            </el-select>
          </label>
          <label v-if="expertId === 'transfer' && ['paths', 'recognition', 'capacity'].includes(scenario)"><span>学生修读对照（可选）</span>
            <el-select v-model="studentId" filterable remote clearable :remote-method="searchStudents" :loading="studentLoading"
              :disabled="busy" placeholder="不选时比较培养方案；输入姓名或学号" aria-label="学生修读对照" @visible-change="v => v && searchStudents('')">
              <el-option v-for="s in studentOptions" :key="s.student_id" :value="s.student_id" :label="`${s.display_name || '姓名未提供'} · ${s.student_id}`" />
            </el-select>
          </label>
          <el-button type="primary" :loading="busy" :disabled="!planId" @click="run()">{{ analyzeLabel }}</el-button>
        </section>
        <div v-if="contextChanged" class="context-notice" role="status">分析条件已调整，下方仍是上一次结果。请点击“{{ analyzeLabel }}”更新后再继续讨论。</div>
        <div v-if="recovery" class="context-notice" role="status">发现此浏览器尚未保存的内容，服务器已有新版本。
          <button class="text-button" @click="restoreRecovery">恢复到输入框</button><button class="text-button" @click="discardRecovery">丢弃本地内容</button>
        </div>
        <p v-if="!plans.length && !loading" class="empty-notice">当前权限范围没有可用培养方案，请先完成资料接入或范围映射。</p>

        <div v-if="busy" class="working" role="status"><el-icon class="is-loading"><Loading /></el-icon>正在读取当前范围资料，原结果仍保留。</div>
        <section v-if="!session && !busy" class="start-panel">
          <div class="start-icon"><el-icon :size="25"><component :is="expertIcons[expertId]" /></el-icon></div>
          <h2>{{ activeScenario?.description }}</h2>
          <p>先确认上方分析对象，再查看结果。每个比较数字都能查看明细与计算方法。</p>
          <div class="start-details"><span>明确分析范围</span><span>先看简短意见</span><span>点具体项目继续问</span></div>
          <p class="capability-note" v-if="expertId === 'recommendation'">年度推免规则尚未接入，本期先展示需要确认的条件，不生成资格名单。</p>
        </section>

        <div v-if="result" class="analysis-layout">
          <div class="analysis-reading">
          <p v-if="result.baseline" class="conversation-note">本次对照：{{ date(result.baseline.created_at) }} 保存的阶段记录 · {{ result.baseline.population }} 名学生</p>
          <p v-if="result.snapshot" class="conversation-note">进度规则：{{ result.snapshot.rule_version }} · 进度计算时间：{{ result.snapshot.source_times.map(date).join('、') || '未提供' }}。保存阶段记录不会形成资格认定。</p>
          <section class="opinion" :class="{ unavailable: result.status === 'blocked' }">
            <span class="opinion-label">{{ result.status === 'blocked' ? '当前条件' : '本次意见' }}</span>
            <h2>{{ result.headline }}</h2>
            <p>{{ result.title }} · {{ result.semester || selectedPlanLabel }} · {{ scenarioName(session!.expert_id, session!.request.scenario) }}<template v-if="result.student"> · {{ result.student.display_name || result.student.student_id }}</template></p>
            <div class="opinion-actions"><button class="text-button" @click="resultView = 'discussion'">继续讨论</button><button class="text-button" :disabled="contextChanged || busy" @click="openNote">整理讨论稿</button><button class="text-button" @click="sourceOpen = true">查看依据</button></div>
          </section>

          <section v-if="result.candidates.length" class="candidates" aria-label="可比较的专业">
            <div class="section-line"><h3>{{ expertId === 'transfer' ? '培养衔接比较对象' : '相近专业' }}</h3><span>最多 3 个 · 可手动替换</span></div>
            <div class="candidate-grid">
              <button v-for="(c, i) in result.candidates" :key="c.plan_id" :disabled="busy" @click="compareCandidate(c.plan_id)"
                :class="{ active: result.comparison?.target.plan_id === c.plan_id }">
                <small>比较对象 {{ i + 1 }}</small><b>{{ c.major_name }}</b>
                <span v-if="expertId === 'program'">{{ result.focus_label || '去除公共课程' }}重合 {{ c.focus_similarity ?? c.structural_similarity ?? '—' }}%</span>
                <span v-else>目标逐门必修同代码覆盖 {{ c.required_coverage ?? '—' }}%</span>
                <em>{{ expertId === 'transfer' ? '不等于可认定或可录取' : '不等于教学内容相似度' }}</em>
              </button>
            </div>
          </section>

          <details v-if="result.missing.length" class="missing-panel" :open="result.status === 'blocked'"><summary>还需明确的资料与事项 · {{ result.missing.length }} 项</summary>
            <ul><li v-for="item in result.missing" :key="item">{{ item }}</li></ul>
          </details>
          <nav class="result-nav" aria-label="结果阅读方式">
            <button :aria-pressed="resultView === 'overview'" :class="{ active: resultView === 'overview' }" @click="resultView = 'overview'">分析概览</button>
            <button :aria-pressed="resultView === 'details'" :class="{ active: resultView === 'details' }" @click="resultView = 'details'">数据明细</button>
            <button :aria-pressed="resultView === 'discussion'" :class="{ active: resultView === 'discussion' }" @click="resultView = 'discussion'">讨论记录 <small>{{ (session?.messages.length || 0) / 2 }}</small></button>
          </nav>

          <section v-for="t in displayTables" :id="'expert-team-table-' + t.id" :key="t.id" class="result-table">
            <div class="section-line"><h3>{{ t.title }} <small>共 {{ t.rows.length }} 项</small></h3>
              <button v-if="t.id === 'courses'" class="text-button" @click="courseFilter = courseFilter === 'all' ? 'shared' : 'all'">{{ courseFilter === 'all' ? '只看共同课程' : '查看全部课程' }}</button>
            </div>
            <div class="table-scroll"><table>
              <thead><tr><th v-for="c in t.columns" :key="c.key">{{ c.label }}</th><th class="action-col">查看</th></tr></thead>
              <tbody><tr v-for="entry in visibleRows(t)" :key="entry.index" :class="{ highlighted: selected?.tableId === t.id && selected?.index === entry.index }">
                <td v-for="c in t.columns" :key="c.key">{{ cell(entry.row[c.key]) }}</td>
                <td><button class="text-button" :aria-label="`查看${entry.row.name || entry.row.item || entry.row.label || '第' + (entry.index + 1) + '项'}说明`" @click="selectRow(t, entry.index)">说明</button></td>
              </tr></tbody>
            </table></div>
            <p v-if="!t.rows.length" class="empty-table">本次范围没有符合条件的记录，不代表所有相关要求均已满足。</p>
            <button v-if="filteredRows(t).length > (expanded[t.id] ? 100000 : 5)" class="expand-table" @click="expanded[t.id] = true">展开全部 {{ filteredRows(t).length }} 项</button>
            <button v-else-if="expanded[t.id] && t.rows.length > 5" class="expand-table" @click="expanded[t.id] = false">收起明细</button>
            <p v-if="t.note" class="table-note">{{ t.note }}</p>
          </section>

          <section v-if="selectedDetail" ref="selectionPanel" class="selection-detail">
            <div class="section-line"><h3>{{ selectedDetail.table.title }} · 所选项目</h3><button class="text-button" @click="selected = null">关闭</button></div>
            <p>{{ selectedDetail.text }}</p>
            <el-button plain type="primary" @click="askSelected">围绕这一项继续问</el-button>
            <el-button v-if="expertId === 'course' && selectedDetail.row.course_id" :disabled="busy" @click="viewCourseHistory(selectedDetail.row.course_id)">查看这门课的学期变化</el-button>
          </section>

          <div class="result-actions"><el-button :disabled="busy || contextChanged" @click="openNote">整理讨论稿</el-button>
            <button class="text-button" @click="sourceOpen = true">计算方法、来源与适用范围</button>
          </div>
          <section v-if="resultView === 'discussion' && session?.messages.length" class="discussion-flow" aria-label="讨论记录">
            <article v-for="(message, i) in session.messages" :key="i" :class="['message', message.role]">
              <small>{{ message.role === 'user' ? '我的问题' : message.basis || '分析说明' }}</small><p>{{ message.text }}</p>
            </article>
          </section>
          <section class="composer">
            <div class="section-line"><b>继续讨论</b><span v-if="selected">已选具体项目 <button class="text-button" @click="selected = null">取消选择</button></span></div>
            <textarea ref="composer" v-model="input" maxlength="2000" :disabled="busy || contextChanged" aria-label="继续讨论的问题"
              :placeholder="discussionPlaceholder" @keydown.ctrl.enter.prevent="send" />
            <div class="composer-actions"><div class="suggestions"><button v-for="q in result.suggestions" :key="q" :disabled="busy" @click="prefill(q)">{{ q }}</button></div>
              <el-button type="primary" :disabled="busy || contextChanged || !input.trim()" @click="send">发送</el-button></div>
            <small class="conversation-note">{{ conversationNote }}</small>
          </section>
          </div>
          <aside class="signal-rail" aria-label="本次分析重点数字">
            <details open class="signal-panel">
              <summary>{{ contextChanged || busy ? '上次分析数字' : '本次重点数字' }}<small>点击收起或展开</small></summary>
              <p class="signal-context">{{ result.title }}<span v-if="result.semester"> · {{ result.semester }}</span></p>
              <p v-if="contextChanged || busy" class="signal-warning">{{ busy ? '正在更新，暂显示上次结果。' : '条件已调整，需重新分析后更新数字。' }}</p>
              <div class="signal-cards">
                <button v-for="s in signals" :key="s.label" class="signal-card" :disabled="busy || contextChanged || !s.tableId"
                  :aria-label="`${s.label}：${s.value ?? '未提供'}${s.value === null ? '' : s.unit}；${s.tableId ? '查看相关明细' : s.note}`" @click="showSignalTable(s.tableId)">
                  <span>{{ s.label }}</span><strong>{{ s.value ?? '—' }}<small v-if="s.value !== null">{{ s.unit }}</small></strong><em>{{ s.note }}</em>
                  <small v-if="s.tableId" class="signal-link">查看相关明细 →</small>
                </button>
              </div>
              <p v-if="!signals.length" class="signal-empty">当前资料不足以形成可用数字，先明确所需规则与资料，不展示推测人数或排名。</p>
              <p class="signal-scope">{{ result.scope_label }} · 数字取自本次分析；未提供的值显示为“—”。</p>
              <button class="text-button" @click="sourceOpen = true">查看计算方法与来源</button>
            </details>
          </aside>
        </div>
      </template>
      <el-skeleton v-else-if="loading" :rows="8" animated />
    </main>

    <el-drawer v-model="sourceOpen" title="本次分析依据" :size="drawerWidth" destroy-on-close>
      <template v-if="result">
        <div class="source-meta"><b>{{ result.scope_label }}</b><p>分析版本：{{ result.version }}</p><p>资料导入：{{ date(result.data_time) }}</p><small>{{ result.data_time_note }}</small></div>
        <h3>计算方法</h3><ol class="source-list"><li v-for="m in result.methods" :key="m">{{ m }}</li></ol>
        <h3>数据来源</h3><div v-for="source in result.sources || []" :key="source.file" class="source-meta"><b>{{ source.file }}</b><p v-if="source.detail">{{ source.detail }}</p><small class="source-hash" v-if="source.hash">文件校验：{{ source.hash }}</small></div>
        <h3>适用范围</h3><ul class="source-list"><li v-for="l in result.limitations" :key="l">{{ l }}</li></ul>
        <section v-for="doc in result.documents" :key="doc.plan" class="source-document">
          <h3>{{ doc.plan }}</h3><p>{{ doc.file }}</p><small>{{ doc.basis }}</small>
          <el-alert v-for="issue in doc.issues" :key="issue" type="warning" :closable="false" :title="issue" show-icon />
          <details v-for="(part, i) in doc.sections" :key="i"><summary>{{ part.title }}</summary><p class="original-text">{{ part.text || '未提取到该章节内容' }}</p></details>
          <small v-if="doc.hash" class="source-hash">文件校验：{{ doc.hash }}</small>
        </section>
      </template>
    </el-drawer>
    <el-drawer v-model="noteOpen" title="讨论意见稿" :size="drawerWidth" destroy-on-close>
      <template v-if="result">
        <h2>{{ result.title }}</h2>
        <p class="conversation-note">以下提纲来自本次数据，可直接修改意见、保留不同看法或补充下一步安排。</p>
        <p class="conversation-note">已有稿件不会因调整条件自动改写；保存或下载前，请对照本次结果检查数字和范围。</p>
        <label class="note-label">讨论意见<textarea v-model="note" maxlength="12000" rows="18" placeholder="记录我的管理意见" /></label>
        <el-button type="primary" :disabled="busy" @click="saveDiscussion">保存讨论稿</el-button>
        <el-button :disabled="!note.trim() || busy" @click="downloadNote">下载文字稿</el-button>
        <p class="conversation-note">保存于当前工作身份的讨论记录，不向外发送，不形成审批或办理动作。</p>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Collection, Reading, Switch, Medal, Checked, Plus, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { authStore } from '@/store/auth'
import { teamSignals } from '@/utils/expertTeamSignals'
import { analyzeTeam, askTeam, getTeamCatalog, getTeamSession, listTeamSessions, saveTeamSession, reviseTeam, getTeamStudents, getTeamSnapshots, saveTeamSnapshot } from '@/api/aiDecision/expertTeam'
import type { TeamExpert, TeamPlan, TeamSession, TeamTable, TeamStudent, TeamRequest, TeamFocus } from '@/types/expertTeam'

const expertIcons: Record<string, any> = { program: Collection, course: Reading, transfer: Switch, recommendation: Medal, graduation: Checked }
const experts = ref<TeamExpert[]>([]), plans = ref<TeamPlan[]>([]), semesters = ref<string[]>([])
const expertId = ref('program'), scenario = ref('similarity'), planId = ref(''), targetId = ref(''), semester = ref('')
const focus = ref<TeamFocus>('non_common'), studentId = ref(''), studentOptions = ref<TeamStudent[]>([]), studentLoading = ref(false)
const focusLabels: Record<TeamFocus, string> = { non_common: '去除公共课程', foundation: '专业基础', main: '专业主干', practice: '专业实践', required: '逐门必修', all: '全部课程' }
const resultView = ref('overview')
const selectedCourseId = ref(''), baselineId = ref(''), baselineOptions = ref<{ id: string; created_at: string }[]>([])
let baselineSearch = 0
const navigation = ref('experts'), loading = ref(true), busy = ref(false), error = ref(''), input = ref(''), note = ref('')
const sourceOpen = ref(false), noteOpen = ref(false), conversationNote = ref('')
const session = ref<TeamSession | null>(null)
const history = ref<Pick<TeamSession, 'id' | 'expert_id' | 'title' | 'updated_at'>[]>([])
const selected = ref<{ tableId: string; index: number } | null>(null), courseFilter = ref('all')
const expanded = ref<Record<string, boolean>>({}), composer = ref<HTMLTextAreaElement>(), selectionPanel = ref<HTMLElement>()
type LocalDraft = { input: string; note: string; revision: number }
const caches = new Map<string, any>(), drafts = new Map<string, LocalDraft>()
const recovery = ref<LocalDraft | null>(null)
let disposed = false, generation = 0, identityEpoch = 0, studentSearch = 0
const isCurrent = (ticket: number) => !disposed && ticket === identityEpoch
const expert = computed(() => experts.value.find(e => e.id === expertId.value))
const discussionExamples: Record<string, string> = {
  program: '例如：只看专业主干课、比较第二个专业。',
  course: '例如：查看问题分析、比较建设做法、查看学期变化。',
  graduation: '例如：查看共同课程、查看资料问题、比较阶段记录。',
  transfer: '例如：比较第二个专业，或点选课程查看修读情况。',
  recommendation: '可询问需要补充的资料，或整理本次讨论意见。',
}
const discussionPlaceholder = computed(() => (discussionExamples[expertId.value] || '') + ' Ctrl + Enter 发送。')
function changePlan() { selectedCourseId.value = ''; baselineId.value = '' }
const activeScenario = computed(() => expert.value?.scenarios.find(s => s.id === scenario.value))
const result = computed(() => session.value?.result)
const signals = computed(() => result.value ? teamSignals(result.value) : [])
async function showSignalTable(id: string) {
  if (!id || busy.value || contextChanged.value) return
  resultView.value = 'details'; await nextTick()
  document.getElementById('expert-team-table-' + id)?.scrollIntoView({ block: 'start', behavior: 'auto' })
}
const courseOptions = computed(() => expertId.value === 'course' && session.value?.request.plan_id === planId.value ? result.value?.course_options || [] : [])
const scopeLabel = computed(() => authStore.user?.permissionContext?.detailScope?.type === 'all' ? '全校授权范围' : '本学院授权范围')
const selectedPlanLabel = computed(() => plans.value.find(p => p.plan_id === session.value?.request.plan_id)?.plan_name || '')
const comparablePlans = computed(() => {
  const source = plans.value.find(x => x.plan_id === planId.value)
  return plans.value.filter(p => p.plan_id !== planId.value && p.grade === source?.grade && p.training_type === source?.training_type && p.source === 'real')
})
const contextChanged = computed(() => {
  if (!session.value) return false
  const r = session.value.request
  return r.plan_id !== planId.value || r.scenario !== scenario.value || (r.target_plan_id || '') !== targetId.value ||
    (r.semester || '') !== semester.value || (r.focus || 'non_common') !== focus.value || (r.student_id || '') !== studentId.value ||
    (expertId.value === 'course' && (r.course_id || result.value?.course?.id || '') !== selectedCourseId.value) ||
    (expertId.value === 'graduation' && scenario.value === 'changes' && (r.baseline_id || '') !== baselineId.value)
})
const displayTables = computed(() => {
  const tables = result.value?.tables || []
  if (resultView.value === 'discussion') return []
  if (resultView.value === 'details') return tables
  if (['course', 'graduation'].includes(expertId.value)) return tables.slice(0, 2)
  const ids = result.value?.student ? ['student_transition', 'student_schedule'] : expertId.value === 'program' && scenario.value === 'features'
    ? ['positioning', 'named_courses', 'reading_requirements'] : ['layers', 'options', 'transition_summary', 'transition_schedule', 'readiness', 'performance']
  const selected = tables.filter(t => ids.includes(t.id))
  return selected.length ? selected : tables.slice(0, 2)
})
const analyzeLabel = computed(() => expertId.value === 'program' ? '开始比较' : expertId.value === 'transfer' ? '查看衔接' : expertId.value === 'recommendation' ? '查看条件' : '查看分析')
const drawerWidth = 'min(580px, 94vw)'
const selectedDetail = computed(() => {
  const t = result.value?.tables.find(t => t.id === selected.value?.tableId)
  const row = t?.rows[selected.value?.index ?? -1]
  return t && row ? { table: t, row, text: t.columns.map(c => `${c.label}：${cell(row[c.key])}`).join('；') } : null
})
const date = (v: string) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '未提供'
const cell = (v: any) => v === null || v === undefined || v === '' ? '—' : String(v)
const expertName = (id: string) => experts.value.find(x => x.id === id)?.name || id
const scenarioName = (id: string, sid: string) => experts.value.find(x => x.id === id)?.scenarios.find(s => s.id === sid)?.name || sid
function filteredRows(t: TeamTable) { return t.rows.map((row, index) => ({ row, index })).filter(e => t.id !== 'courses' || courseFilter.value !== 'shared' || e.row.side === '共同课程') }
function visibleRows(t: TeamTable) { return filteredRows(t).slice(0, expanded.value[t.id] ? undefined : 5) }
function draftPrefix() {
  const u = authStore.user
  return `expert-team-draft:${u?.username || ''}:${u?.activeIdentityId || ''}:${u?.permissionContext?.scopeFingerprint || ''}:`
}
function persistDraft() {
  if (!session.value || recovery.value) return
  const value = { input: input.value, note: note.value, revision: session.value.revision }
  drafts.set(session.value.id, value)
  try {
    const key = draftPrefix() + session.value.id
    if (input.value === session.value.draft && note.value === session.value.note) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, JSON.stringify(value))
  } catch { /* Restricted storage must not prevent analysis or explicit saving. */ }
}
function localDraft(value: TeamSession): LocalDraft | null {
  try {
    const raw = drafts.get(value.id) || JSON.parse(sessionStorage.getItem(draftPrefix() + value.id) || 'null')
    return raw && typeof raw.input === 'string' && raw.input.length <= 2000 && typeof raw.note === 'string' && raw.note.length <= 12000 && Number.isInteger(raw.revision) ? raw : null
  } catch { return null }
}
function restoreRecovery() {
  if (!recovery.value) return
  input.value = recovery.value.input; note.value = recovery.value.note; recovery.value = null; persistDraft()
}
function discardRecovery() { recovery.value = null; if (session.value) drafts.delete(session.value.id); persistDraft() }
function stash() {
  persistDraft()
  caches.set(expertId.value, { session: session.value, scenario: scenario.value, planId: planId.value, targetId: targetId.value, semester: semester.value, input: input.value, note: note.value, focus: focus.value, studentId: studentId.value, studentOptions: studentOptions.value, selectedCourseId: selectedCourseId.value, baselineId: baselineId.value })
}
function applySession(value: TeamSession) {
  const local = localDraft(value)
  session.value = value; expertId.value = value.expert_id; scenario.value = value.request.scenario; planId.value = value.request.plan_id
  targetId.value = value.request.target_plan_id || ''; semester.value = value.request.semester || ''
  focus.value = value.request.focus || 'non_common'; studentId.value = value.request.student_id || ''
  studentOptions.value = value.result.student ? [value.result.student] : []
  selectedCourseId.value = value.request.course_id || value.result.course?.id || ''; baselineId.value = value.request.baseline_id || ''
  input.value = local?.revision === value.revision ? local.input : value.draft
  note.value = local?.revision === value.revision ? local.note : value.note
  recovery.value = local && local.revision !== value.revision && (local.input !== value.draft || local.note !== value.note) ? local : null
  selected.value = null; expanded.value = {}; courseFilter.value = 'all'
  resultView.value = 'overview'
}
function switchExpert(id: string) {
  if (busy.value || id === expertId.value) return
  stash(); expertId.value = id; error.value = ''; selected.value = null; expanded.value = {}
  const c = caches.get(id)
  session.value = c?.session || null; scenario.value = c?.scenario || expert.value!.scenarios[0].id
  planId.value = c?.planId || planId.value || plans.value[0]?.plan_id || ''; targetId.value = c?.targetId || ''; semester.value = c?.semester || ''
  input.value = c?.input || ''; note.value = c?.note || ''; sourceOpen.value = false; noteOpen.value = false
  focus.value = c?.focus || 'non_common'; studentId.value = c?.studentId || ''; studentOptions.value = c?.studentOptions || []; recovery.value = null; resultView.value = 'overview'
  selectedCourseId.value = c?.selectedCourseId || ''; baselineId.value = c?.baselineId || ''
}
async function chooseScenario(id: string) {
  if (busy.value || scenario.value === id) return
  scenario.value = id
  if (!['paths', 'recognition', 'capacity'].includes(id)) studentId.value = ''
  if (planId.value) await run()
}
async function searchStudents(query: string) {
  if (!planId.value || expertId.value !== 'transfer') return
  const ticket = ++studentSearch, epoch = identityEpoch, plan = planId.value
  studentLoading.value = true
  try { const value = await getTeamStudents(plan, query); if (isCurrent(epoch) && ticket === studentSearch && plan === planId.value) studentOptions.value = value.items }
  catch (e: any) { if (isCurrent(epoch) && ticket === studentSearch) error.value = e.message }
  finally { if (isCurrent(epoch) && ticket === studentSearch) studentLoading.value = false }
}
async function refreshHistory() { const ticket = identityEpoch; const response = await listTeamSessions(); if (isCurrent(ticket)) history.value = response.items }
async function refreshBaselines() {
  const ticket = ++baselineSearch, epoch = identityEpoch, plan = planId.value
  baselineOptions.value = []
  if (expertId.value !== 'graduation' || !plan) return
  try { const value = await getTeamSnapshots(plan); if (isCurrent(epoch) && ticket === baselineSearch && expertId.value === 'graduation' && plan === planId.value) baselineOptions.value = value.items }
  catch (e: any) { if (isCurrent(epoch) && ticket === baselineSearch) error.value = e.message }
}
async function saveStage() {
  if (!session.value || busy.value || contextChanged.value) return
  const epoch = identityEpoch; busy.value = true; error.value = ''
  try {
    const saved = await saveTeamSnapshot(session.value.id, session.value.revision)
    if (!isCurrent(epoch)) return
    await refreshBaselines()
    if (!isCurrent(epoch)) return
    baselineId.value = saved.id
    ElMessage.success(`已保存阶段记录：${date(saved.created_at)}；相同数据不会重复保存`)
  } catch (e: any) { if (isCurrent(epoch)) error.value = e.message }
  finally { if (isCurrent(epoch)) busy.value = false }
}
async function viewCourseHistory(id: string) { if (!busy.value) { scenario.value = 'outcomes'; await run('', id) } }
async function openHistory() { const ticket = identityEpoch; navigation.value = 'history'; try { await refreshHistory() } catch (e: any) { if (isCurrent(ticket)) error.value = e.message } }
async function loadHistory(id: string) {
  if (busy.value) return; stash(); busy.value = true; error.value = ''
  const ticket = identityEpoch
  try { const value = await getTeamSession(id); if (isCurrent(ticket)) applySession(value) } catch (e: any) { if (isCurrent(ticket)) error.value = e.message }
  finally { if (isCurrent(ticket)) busy.value = false }
}
async function newDiscussion() {
  if (busy.value) return
  if (session.value && (input.value !== session.value.draft || note.value !== session.value.note)) {
    if (!await saveDiscussion()) return
  }
  stash(); session.value = null; input.value = ''; note.value = ''; selected.value = null; targetId.value = ''; error.value = ''; navigation.value = 'experts'
  studentId.value = ''; recovery.value = null
  selectedCourseId.value = ''; baselineId.value = ''
}
async function run(target?: string, courseId?: string) {
  if (busy.value || !planId.value) return
  if (recovery.value) { error.value = '请先选择恢复或丢弃本地未保存内容'; return }
  if (session.value && (input.value !== session.value.draft || note.value !== session.value.note)) { if (!await saveDiscussion()) return }
  stash(); busy.value = true; error.value = ''; const ticket = ++generation
  try {
    const request: TeamRequest = { expert_id: expertId.value, scenario: scenario.value, plan_id: planId.value,
      target_plan_id: target ?? targetId.value, semester: semester.value, course_id: expertId.value === 'course' ? courseId ?? selectedCourseId.value : '', focus: focus.value, student_id: studentId.value,
      baseline_id: expertId.value === 'graduation' ? baselineId.value : '' }
    const sameDiscussion = session.value?.expert_id === expertId.value && session.value?.request.plan_id === planId.value
    const value = sameDiscussion ? await reviseTeam(session.value!.id, { revision: session.value!.revision, analysis: request }) : await analyzeTeam(request)
    if (disposed || ticket !== generation) return
    drafts.delete(value.id); try { sessionStorage.removeItem(draftPrefix() + value.id) } catch { /* optional */ }
    applySession(value); await refreshHistory()
  } catch (e: any) { if (!disposed && ticket === generation) error.value = e.message }
  finally { if (!disposed && ticket === generation) busy.value = false }
}
async function compareCandidate(id: string) { await run(id) }
async function selectRow(t: TeamTable, index: number) { selected.value = { tableId: t.id, index }; await nextTick(); selectionPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
async function askSelected() {
  if (!selectedDetail.value) return
  const title = selectedDetail.value.row.name || selectedDetail.value.row.item || selectedDetail.value.row.label || '所选项目'
  input.value += `${input.value ? '\n' : ''}请说明“${title}”的具体情况。`
  await nextTick(); composer.value?.focus(); composer.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
async function prefill(q: string) { selected.value = null; input.value += `${input.value ? '\n' : ''}${q}`; await nextTick(); composer.value?.focus() }
async function send() {
  if (!session.value || busy.value || contextChanged.value || !input.value.trim() || recovery.value) return
  if (note.value !== session.value.note) { if (!await saveDiscussion()) return }
  busy.value = true; error.value = ''; const ticket = identityEpoch
  try {
    const value = await askTeam(session.value.id, { revision: session.value.revision, message: input.value.trim(), table_id: selected.value?.tableId, row_index: selected.value?.index })
    if (!isCurrent(ticket)) return
    drafts.delete(value.id); try { sessionStorage.removeItem(draftPrefix() + value.id) } catch { /* optional */ }
    applySession(value); input.value = ''; selected.value = null; resultView.value = 'discussion'
    await nextTick(); composer.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  } catch (e: any) { if (isCurrent(ticket)) error.value = e.message }
  finally { if (isCurrent(ticket)) busy.value = false }
}
async function saveDiscussion() {
  if (!session.value || busy.value || recovery.value) return false
  busy.value = true; error.value = ''; const ticket = identityEpoch
  try {
    const value = await saveTeamSession(session.value.id, { revision: session.value.revision, draft: input.value, note: note.value })
    if (!isCurrent(ticket)) return false
    session.value = value; drafts.delete(value.id); persistDraft(); ElMessage.success('已保存到当前工作身份的讨论记录'); return true
  } catch (e: any) { if (isCurrent(ticket)) error.value = e.message; return false }
  finally { if (isCurrent(ticket)) busy.value = false }
}
function openNote() { if (!note.value.trim()) note.value = result.value?.draft_text || result.value?.headline || ''; noteOpen.value = true }
async function downloadNote() {
  if (!session.value || busy.value) return
  const ticket = identityEpoch, id = session.value.id, content = note.value
  busy.value = true
  try {
    // Revalidate the current identity, student and every comparison object on
    // the server immediately before exporting an already displayed draft.
    const current = await getTeamSession(id)
    if (!isCurrent(ticket) || session.value?.id !== id) return
    if (current.revision !== session.value.revision) { error.value = '讨论已在其他窗口更新，请重新打开后再下载'; return }
    const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = '专家团讨论意见稿.txt'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e: any) { if (isCurrent(ticket)) error.value = e.message }
  finally { if (isCurrent(ticket)) busy.value = false }
}
async function initialize() {
  loading.value = true; error.value = ''; const ticket = identityEpoch
  try {
    const data = await getTeamCatalog(); if (!isCurrent(ticket)) return
    experts.value = data.experts; plans.value = data.plans; semesters.value = data.semesters; conversationNote.value = data.conversation_note
    planId.value = data.plans[0]?.plan_id || ''; await refreshHistory()
  } catch (e: any) { if (isCurrent(ticket)) error.value = e.message }
  finally { if (isCurrent(ticket)) loading.value = false }
}
function retry() { if (!experts.value.length) void initialize(); else void run() }
watch(planId, () => {
  if (targetId.value && !comparablePlans.value.some(p => p.plan_id === targetId.value)) targetId.value = ''
  if (session.value?.request.plan_id !== planId.value) { studentId.value = ''; studentOptions.value = []; studentSearch++; selectedCourseId.value = ''; baselineId.value = '' }
})
watch([expertId, planId], () => { void refreshBaselines() })
watch([input, note], persistDraft)
watch(resultView, () => { selected.value = null })
watch(() => [authStore.user?.activeIdentityId, authStore.user?.permissionContext?.scopeFingerprint], () => {
  generation++; identityEpoch++; caches.clear(); drafts.clear(); session.value = null; input.value = ''; note.value = ''; selected.value = null; history.value = []
  experts.value = []; plans.value = []; semesters.value = []; planId.value = ''; targetId.value = ''; sourceOpen.value = false; noteOpen.value = false; busy.value = false
  studentSearch++; studentId.value = ''; studentOptions.value = []; studentLoading.value = false; focus.value = 'non_common'; recovery.value = null
  baselineSearch++; baselineId.value = ''; baselineOptions.value = []; selectedCourseId.value = ''
  try { for (const key of Object.keys(sessionStorage)) if (key.startsWith('expert-team-draft:')) sessionStorage.removeItem(key) } catch { /* optional */ }
  void initialize()
})
onMounted(initialize)
onBeforeUnmount(() => { persistDraft(); disposed = true; generation++; caches.clear(); drafts.clear() })
</script>

<style lang="scss" scoped>
.analysis-layout{display:flex;flex-direction:column;gap:16px;min-width:0}.analysis-reading{min-width:0}.signal-rail{order:-1;min-width:0}.signal-panel{background:#fff;border:1px solid #e1e5ed;border-radius:9px;padding:14px}.signal-panel summary{cursor:pointer;font-size:14px;font-weight:550;color:#39445a}.signal-panel summary>small{font-size:11px;font-weight:400;color:#848b9b;margin-left:12px}.signal-context,.signal-scope,.signal-empty{font-size:12px;line-height:1.7;color:#737e91;margin:10px 0}.signal-scope{font-size:11px}.signal-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}.signal-card{display:flex;flex-direction:column;gap:6px;text-align:left;padding:11px;border:1px solid #e9e7f3;border-radius:7px;background:#fafaff;color:#39445a;min-width:0}.signal-card>span{font-size:12px;line-height:1.5}.signal-card strong{font-size:26px;font-weight:550;color:#4935a8}.signal-card strong small{font-size:12px;font-weight:400;margin-left:5px;color:#7b8496}.signal-card em{font-size:11px;line-height:1.6;font-style:normal;color:#7b8496}.signal-card:disabled{cursor:default;opacity:1}.signal-link{font-size:11px;color:#6350bd}.signal-warning{font-size:12px;line-height:1.7;color:#946521;background:#fff8e8;padding:8px;border-radius:5px}.signal-scope+.text-button{font-size:12px}
@media(min-width:1600px){.analysis-layout{display:grid;grid-template-columns:minmax(0,1fr) 220px;align-items:start;gap:18px}.signal-rail{order:0;position:sticky;top:18px}.signal-cards{grid-template-columns:1fr}.signal-panel summary>small{display:block;margin:6px 0 0}.signal-context{overflow-wrap:anywhere}}
.context-notice{display:flex;gap:12px;flex-wrap:wrap;padding:11px 14px;margin:12px 0;background:#fff8e8;color:#855e20;border:1px solid #ecddb7;border-radius:7px;font-size:13px;line-height:1.7}.opinion-actions{display:flex;gap:22px;margin-top:10px}.result-nav{display:flex;gap:8px;padding:4px;background:#eceef5;border-radius:8px;margin:18px 0}.result-nav button{border:0;background:none;color:#67738a;font-size:13px;padding:9px 15px;border-radius:6px}.result-nav button.active{background:#fff;color:#4935c0;box-shadow:0 1px 3px #1e293b12}.result-nav small{font-size:11px;color:#8a839b;margin-left:4px}.missing-panel summary{cursor:pointer;font-size:12px}.note-label textarea:focus-visible,.composer textarea:focus-visible{outline:2px solid #b4a8eb;outline-offset:3px}button:focus-visible{outline:2px solid #7968ca;outline-offset:3px}
.team-workspace{display:grid;grid-template-columns:228px minmax(0,1fr);gap:0;min-height:calc(100vh - 132px);border:1px solid #e1e5ec;border-radius:12px;background:#f6f7fb;color:#253044;overflow:hidden}
.expert-side{background:#fff;border-right:1px solid #e2e5ed;padding:20px 12px;display:flex;flex-direction:column;gap:12px}.side-heading{padding:0 8px}.side-heading h2{font-size:21px;margin:0;font-weight:600}.side-heading p{font-size:12px;color:#677388;margin:8px 0 0}
button{font:inherit;cursor:pointer}button:disabled{cursor:wait;opacity:.6}.side-switch{display:flex;background:#f2f3f8;padding:3px;border-radius:7px}.side-switch button{flex:1;border:0;background:none;border-radius:5px;padding:8px 3px;color:#536077;font-size:13px}.side-switch button.active{background:#fff;color:#3730a3;box-shadow:0 1px 3px #1e293b15}
.group-label{font-size:12px;color:#788194;margin:9px 10px}.expert-item{width:100%;display:flex;align-items:center;gap:12px;padding:14px 10px;border:1px solid transparent;border-left:3px solid transparent;border-radius:7px;text-align:left;background:transparent;color:#354156;margin-bottom:4px}.expert-item span{min-width:0}.expert-item b{display:block;font-size:14px;font-weight:500;line-height:1.55}.expert-item small{display:block;color:#758096;font-size:12px;line-height:1.55;margin-top:3px}.expert-item:hover{background:#f6f7fb}.expert-item.selected{color:#4338ca;background:#efefff;border-color:#e6e6fa;border-left-color:#5847df}.expert-item.selected small{color:#666198}
.new-discussion{display:flex;align-items:center;justify-content:center;gap:6px;margin-top:auto;padding:11px;border:1px solid #d8dce6;background:#fff;color:#414970;border-radius:7px;font-size:13px}.side-footer{font-size:11px;color:#778195;line-height:1.7;padding:0 6px;margin:0}.history-list{display:flex;flex-direction:column;gap:5px;max-height:650px;overflow:auto}.history-list button{background:none;border:0;border-radius:6px;padding:10px;text-align:left;color:#39445a}.history-list button.selected{background:#efefff}.history-list b{font-size:13px;font-weight:500;display:block;line-height:1.6}.history-list small{font-size:11px;color:#788194;display:block;margin-top:5px}.empty-history{font-size:12px;color:#768194;padding:10px}
.team-main{padding:24px 26px;min-width:0}.workspace-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.eyebrow{font-size:12px;color:#6a7285;margin:0 0 6px}.eyebrow span{color:#8a91a0}.workspace-heading h1{font-size:23px;font-weight:550;margin:0;line-height:1.5}.workspace-intro{font-size:13px;color:#69758a;margin:9px 0 18px;line-height:1.7}.header-actions{display:flex;gap:8px}.header-actions .el-button+.el-button{margin-left:0}.scenario-tabs{display:flex;gap:4px;border-bottom:1px solid #e1e5ee;margin-bottom:17px;flex-wrap:wrap}.scenario-tabs button{background:transparent;border:0;border-bottom:2px solid transparent;padding:10px 14px;font-size:13px;color:#657088}.scenario-tabs button.active{color:#4935c0;border-bottom-color:#6049dc;font-weight:550}
.context-form{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:18px}.context-form label{display:flex;flex:1 1 200px;min-width:160px;flex-direction:column;gap:6px;font-size:12px;color:#697386}.context-form .el-select{width:100%}.context-form>.el-button{height:32px}.working{display:flex;align-items:center;gap:8px;font-size:13px;color:#5d5593;background:#eeedf9;padding:12px;border-radius:7px;margin:12px 0}.error-banner{padding:12px;background:#fef2f2;border:1px solid #f4caca;color:#9f3535;border-radius:7px;margin-bottom:16px;font-size:13px}.error-banner button{border:0;background:none;color:#9f3535;text-decoration:underline;margin-left:12px}
.start-panel{padding:48px 24px;background:#fff;border:1px solid #e6e8ef;border-radius:9px;text-align:center;margin-top:25px}.start-icon{display:inline-flex;padding:13px;border-radius:12px;background:#eeedfd;color:#6553ce}.start-panel h2{font-size:20px;font-weight:500;margin:20px 0 10px}.start-panel p{font-size:13px;line-height:1.8;color:#778195}.start-details{display:flex;gap:28px;justify-content:center;font-size:12px;color:#5c6880;margin-top:30px;flex-wrap:wrap}.capability-note{background:#faf5e8;padding:10px;border-radius:7px}.empty-notice{font-size:13px;color:#a36a20}
.opinion{border-left:3px solid #6650dc;padding:3px 0 3px 14px;margin:20px 0}.opinion-label{font-size:12px;color:#7b8093}.opinion h2{display:inline;font-size:16px;font-weight:500;line-height:1.85;margin-left:10px}.opinion p{font-size:12px;color:#81899a;margin:7px 0}.opinion.unavailable{border-color:#c89232}.section-line{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.section-line h3{font-size:14px;font-weight:500;margin:0}.section-line>span,.section-line h3 small{color:#828b9c;font-size:11px;font-weight:400}.section-line h3 small{margin-left:8px}.candidates{margin:20px 0}.candidate-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-top:10px}.candidate-grid button{text-align:left;border:1px solid #e0e3ed;border-radius:8px;background:#fff;padding:12px;display:flex;flex-direction:column;gap:7px;color:#354258}.candidate-grid button.active{background:#f0effd;border-color:#b9b0e9}.candidate-grid small{font-size:11px;color:#81869b}.candidate-grid b{font-size:14px;font-weight:550}.candidate-grid span{font-size:12px;color:#5e5598}.candidate-grid em{font-size:11px;color:#85899c;font-style:normal}
.missing-panel{background:#fff9ef;border:1px solid #eee1c8;padding:14px 16px;border-radius:8px;margin-bottom:18px;font-size:13px;color:#835f25}.missing-panel ul{padding-left:20px;margin:8px 0 0;line-height:1.9}.result-table{margin:15px 0;background:#fff;border:1px solid #e1e5ed;border-radius:8px;overflow:hidden}.result-table>.section-line{padding:13px 15px}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px;text-align:left}th{font-weight:400;color:#7b8496;background:#f8f9fc;padding:10px 12px;white-space:nowrap}td{border-top:1px solid #eef0f5;padding:11px 12px;line-height:1.65;min-width:75px;max-width:260px;overflow-wrap:anywhere}tr.highlighted td{background:#f2f0ff}.action-col{width:45px}td:last-child{min-width:45px}.text-button{border:0;background:none;font-size:12px;color:#6350bd;padding:3px 0}.text-button:hover{text-decoration:underline}.table-note{padding:10px 15px;margin:0;font-size:11px;color:#848b9b;line-height:1.7;background:#fcfcfe;border-top:1px solid #eef0f6}.expand-table{width:100%;padding:10px;border:0;border-top:1px solid #eceef4;background:#fafbfe;font-size:12px;color:#77788d}.empty-table{font-size:12px;color:#818a9b;padding:15px}
.selection-detail{background:#f0effe;border:1px solid #dcd5f4;border-radius:8px;padding:15px;margin:14px 0}.selection-detail p{font-size:13px;line-height:1.85;color:#5f6082}.result-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:18px 0}.discussion-flow{display:flex;flex-direction:column;gap:12px;margin-top:20px}.message{background:#fff;border:1px solid #e7e9f1;padding:13px 16px;border-radius:8px;max-width:95%}.message.user{align-self:flex-end;background:#edebfb;border-color:#e1dbf5}.message small{font-size:11px;color:#8a839a}.message p{font-size:13px;white-space:pre-wrap;line-height:1.9;margin:6px 0 0}.composer{background:#fff;border:1px solid #d9dbe8;border-radius:9px;padding:14px;margin-top:18px}.composer .section-line b{font-size:12px;font-weight:400;color:#788094}.composer textarea{display:block;width:100%;box-sizing:border-box;border:0;resize:vertical;min-height:85px;max-height:240px;font:inherit;font-size:14px;line-height:1.8;color:#34415b;padding:12px 0;background:#fff}.composer textarea::placeholder{color:#9a9eaa}.composer-actions{display:flex;gap:10px;align-items:flex-end;justify-content:space-between}.suggestions{display:flex;flex-wrap:wrap;gap:6px}.suggestions button{border:0;background:#f5f4fa;border-radius:4px;padding:5px 7px;font-size:11px;color:#77708b}.conversation-note{display:block;font-size:11px;color:#8a91a0;line-height:1.7;margin-top:12px}
.source-meta{background:#f6f7fb;padding:15px;border-radius:8px;font-size:13px;line-height:1.7}.source-meta small{color:#7a8395}.source-list{font-size:13px;line-height:1.9;color:#667085;padding-left:20px}.source-document{border-top:1px solid #e5e7ed;padding-top:14px;margin-top:24px}.source-document>p{font-size:13px}.source-document>small{color:#81889a;font-size:11px}.source-document .el-alert{margin:12px 0}.source-document details{padding:12px 0;border-bottom:1px solid #edf0f5;font-size:13px}.source-document summary{cursor:pointer;color:#4d5b73}.original-text{white-space:pre-wrap;line-height:1.9;font-size:12px;color:#657088;overflow-wrap:anywhere}.source-hash{display:block;overflow-wrap:anywhere;margin-top:14px}.draft-headline{font-size:15px;line-height:1.9}.note-label{display:block;font-size:13px;color:#657088;margin:20px 0}.note-label textarea{box-sizing:border-box;width:100%;border:1px solid #dce0e9;border-radius:7px;padding:12px;margin-top:10px;font:inherit;line-height:1.8;resize:vertical}
@media(max-width:1350px){.team-workspace{grid-template-columns:205px minmax(0,1fr)}.team-main{padding:20px 18px}.candidate-grid{grid-template-columns:repeat(auto-fit,minmax(155px,1fr))}.expert-item{gap:9px;padding-left:7px}.expert-item small{font-size:11px}}
@media(max-width:1000px){.team-workspace{grid-template-columns:1fr}.expert-side{border-right:0;border-bottom:1px solid #e2e5ed}.expert-group{display:flex;flex-wrap:wrap;gap:6px}.expert-group .group-label{width:100%}.expert-item{width:auto;flex:1;min-width:180px}.side-footer{display:none}.new-discussion{margin-top:5px}.workspace-heading{align-items:flex-start}.header-actions{flex-wrap:wrap}.context-form label{flex-basis:230px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
@media(min-width:1001px){.team-workspace{overflow:clip}.expert-side{position:sticky;top:0;align-self:start;height:calc(100vh - 132px);box-sizing:border-box;overflow-y:auto}}
@media(max-width:1000px){.expert-side{padding:12px;gap:8px}.expert-item{padding:8px;min-width:155px;margin:0}.expert-item small{display:none}.side-heading{display:flex;align-items:center;gap:12px}.side-heading h2{font-size:18px}.side-heading p{margin:0}.expert-group .group-label{margin:2px 6px}.new-discussion{padding:8px}}
</style>
