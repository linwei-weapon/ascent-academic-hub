<!-- 专家团研究工作区：保留来源提交的业务与交互，归入 AI 管理决策模块。 -->
<template>
  <div ref="workspace" class="research-workspace" :style="{ '--available-workspace-height': availableWorkspaceHeight + 'px' }" :class="{ 'side-hidden': !sidebarVisible, 'panel-overlay': panelOverlay, 'narrow': workspaceWidth < 880 }" aria-label="专家团研究工作区">
    <aside v-show="sidebarVisible" class="research-sidebar" aria-label="研究导航">
      <div class="sidebar-heading"><div><small>专家团</small><h2>我的研究</h2></div><button class="icon-button" aria-label="收起研究栏" @click="sidebarOpen = false"><el-icon><Fold /></el-icon></button></div>
      <button class="new-research" :disabled="loading" @click="newResearchDialog"><el-icon><Plus /></el-icon> 新建研究</button>
      <input v-model="query" class="research-search" placeholder="查找研究或讨论内容" aria-label="搜索授权研究与讨论" />
      <div class="list-switch"><button :class="{ selected: !archived }" @click="archived = false">近期研究</button><button :class="{ selected: archived }" @click="archived = true">已归档</button></div>
      <div class="research-list" :aria-busy="loadingList">
        <button v-for="item in summaries" :key="item.id" :class="{ selected: activeId === item.id }" :aria-current="activeId === item.id ? 'page' : undefined" @click="openSearchResult(item)"><b>{{ item.title }}</b><span v-if="query && item.snippet" class="search-snippet">{{ item.snippet }}</span><small><span v-if="records[item.id]?.active_run && isRunning(records[item.id].active_run)" class="running-dot">{{ runLabel(records[item.id].active_run!.status) }} · </span>{{ date(item.updated_at) }}<span v-if="locals[item.id]?.unread"> · 有新内容</span></small></button>
        <p v-if="!summaries.length && !loadingList" class="quiet sidebar-empty">{{ query ? '没有找到相关研究。' : archived ? '尚无归档研究。' : '从一个具体问题开始，研究会保存在这里。' }}</p>
        <button v-if="cursor" class="more" :disabled="loadingList" @click="refreshList(true)">查看更多研究</button>
      </div>
      <details class="participants" open><summary>本次专家 <span>{{ activeParticipants.length }}</span></summary><p v-if="!activeParticipants.length" class="quiet">发送问题后，由有资料支持的相关专家参与。</p><button v-for="participant in activeParticipants" :key="participant.expert_id" @click="expertOpen = true"><ExpertAvatar :id="participant.expert_id" class="participant-avatar" /><span><b>{{ expertName(participant.expert_id) }}</b><small>{{ result?.actual_experts?.includes(participant.expert_id) ? '最近一轮已参与' : '已加入，本轮未参与' }}</small></span></button><button class="add-expert" @click="expertOpen = true">＋ 添加专家</button><small v-if="excludedCount" class="quiet">{{ excludedCount }}位已停止自动参与，可在添加窗口重新加入。</small></details>
      <button class="legacy-entry" @click="openLegacy()">查看以往讨论档案</button>
    </aside>

    <main class="research-main">
      <header class="research-header">
        <div class="heading-left"><button class="icon-button menu-toggle" aria-label="展开或收起研究栏" :aria-expanded="sidebarVisible" @click="toggleSidebar"><el-icon><Fold v-if="sidebarVisible" /><Expand v-else /></el-icon></button><div><p class="identity">{{ catalog?.role_view === 'dean' ? '本院教学研究' : '全校教学研究' }}<span v-if="current?.status === 'archived'"> · 已归档</span></p><h1 :title="current?.title">{{ workspaceTitle }}</h1></div></div>
        <div class="header-tools"><button v-if="!sidebarVisible" class="text-button" :disabled="loading" @click="newResearchDialog">新建研究</button><button class="expert-entry" @click="expertOpen = true"><el-icon><Plus /></el-icon>{{ activeParticipants.length ? '参与专家 · ' + activeParticipants.length : '选择专家' }}</button><button class="text-button help-entry" @click="helpOpen = true">使用说明</button><el-dropdown v-if="current" trigger="click"><button class="text-button" aria-label="研究操作">更多</button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="renameDialog">修改研究名称</el-dropdown-item><el-dropdown-item v-if="current.status !== 'archived'" @click="newQuestionDialog">添加待明确事项</el-dropdown-item><el-dropdown-item @click="archiveDialog">{{ current.status === 'archived' ? '恢复研究' : '归档研究' }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>
      <ResearchScopeSelector v-model:open="scopeOpen" :scope="local.scope" :catalog="catalog" :comparable-plans="comparablePlans" :focus-labels="focusLabels" :course-options="result?.course_options" :has-research="!!current" :readonly="current?.status === 'archived'" @plan-change="planChanged" />
      <div v-if="bootstrapError" class="error-banner" role="alert">{{ bootstrapError }} <button class="text-button" @click="initialize">重新加载</button></div>
      <div v-if="local.error" class="error-banner" role="alert">{{ local.error }} <button class="text-button" @click="local.error = ''">收起</button></div>
      <div v-if="local.notice" class="notice-banner" role="status">{{ local.notice }} <button class="text-button" @click="local.notice = ''">知道了</button></div>

      <nav v-if="result" class="reading-location" aria-label="讨论阅读定位"><span>{{ current?.turns.filter(t => t.result).length }}轮讨论 · {{ local.unread ? '有新的分析' : '分析与个人意见分别保存' }}</span><button class="text-button" @click="scrollLatest">{{ local.unread ? '查看最新分析' : '回到最新分析开头' }}<el-icon><ArrowUp /></el-icon></button></nav>
      <div ref="reading" class="reading-scroll" @scroll="rememberScroll" @wheel="markReadingInteraction" @touchmove="markReadingInteraction" @pointerdown="markReadingPointer" @keydown="markReadingKey">
        <el-skeleton v-if="loading || loadingResearch" :rows="7" animated />
        <template v-else>
          <section v-if="!current" class="welcome"><p class="welcome-intro">{{ catalog?.role_view === 'dean' ? '从本院的一个具体问题开始，也可以在下方直接提问。' : '选择一个常见问题作为起点，也可以在下方直接提问。' }}</p><div class="question-examples"><button v-for="example in examples" :key="example.text" @click="useExample(example)"><span>{{ example.title }}</span><b>{{ example.text }}</b><small>准备这个问题 →</small></button></div></section>
          <details v-if="result" class="research-progress"><summary>研究摘要 <span>{{ current?.turns.filter(t => t.result).length }}轮分析<template v-if="openQuestions.length"> · {{ openQuestions.length }}项待明确</template></span></summary><p><b>目前看法</b>{{ result.decision_summary || result.headline }}</p><p v-if="openQuestions.length"><b>尚需明确</b>{{ openQuestions.length }}项 <button class="text-button" @click="showQuestions = true">查看</button></p><p v-if="current && current.turns.filter(t => t.result).length > 1"><button class="text-button" @click="scrollLatest">查看最近一轮</button><span>此前分析与个人意见分别保留。</span></p></details>
          <button v-if="current?.next_before" class="load-history" :disabled="olderBusy" @click="loadEarlier">加载更早讨论</button>
          <section v-if="current" class="conversation" aria-label="连续研究讨论">
            <article v-for="turn in current.turns" :key="turn.id" :id="'research-turn-' + turn.id" class="turn" tabindex="-1">
              <div class="user-question"><small>我的问题 · {{ date(turn.created_at) }}</small><p>{{ turn.message }}</p></div>
              <div v-if="!turn.result" class="run-state" :class="{ failed: ['failed','timed_out'].includes(turn.run.status) }" role="status"><span class="status-dot" :class="{ working: isRunning(turn.run) }" />{{ runLabel(turn.run.status) }}<p v-if="turn.run.error">{{ turn.run.error }}</p><button v-if="!isRunning(turn.run) && !busy" class="text-button" @click="prefill(turn.message)">将问题放回输入区</button></div>
              <template v-else><p v-if="['partial','partial_success'].includes(turn.run.status)" class="notice-banner">本轮只完成了部分分析，以下仅展示已确认的内容。</p><p v-if="turn.result.method_unavailable" class="error-banner">本轮使用的方法版本已停用，不应继续依此形成新结论。</p><ResearchResult :result="turn.result" :experts="catalog?.experts || []" :busy="busy" :readonly="current.status === 'archived' || !!turn.result.method_unavailable" @sources="openSources" @compare="compare" @question="addQuestion($event)" @adopt="previewAdopt" @prefill="prepareQuestion" /></template>
            </article>
            <p v-if="!current.turns.length" class="quiet">尚无可读取的讨论轮次。</p>
          </section>
          <section v-if="current?.questions.length" class="questions-inline"><button class="text-button" @click="showQuestions = !showQuestions">{{ showQuestions ? '收起' : '查看' }}待明确事项 · {{ current.questions.length }}项</button><div v-if="showQuestions"><article v-for="question in current.questions" :key="question.id"><div><span class="question-kind">{{ question.kind === 'data' ? '资料与规则' : '管理取舍' }}</span><small>{{ questionLabel(question.status) }}</small></div><p>{{ question.text }}</p><button class="text-button" @click="changeQuestion(question)">{{ question.status === 'open' ? '暂缓' : '重新打开' }}</button></article><p class="quiet">资料需经原有业务渠道确认。这里不能把“已提交”手动改成“已明确”。</p></div></section>
        </template>
      </div>

      <footer class="research-composer" :class="{ 'is-archived': current?.status === 'archived', 'is-expanded': composerExpanded }">
        <p v-if="current?.status === 'archived'" class="archive-status">已归档，可继续查看资料和已保存意见。<button class="text-button" @click="archive">恢复研究，继续讨论</button></p>
        <template v-else>
        <div v-if="local.directed" class="directed">本次请 {{ expertName(local.directed) }} {{ current ? '补充' : '分析' }} <button class="text-button" @click="local.directed = ''">取消本次指定</button></div>
        <div v-if="busy" class="composer-busy" role="status">{{ current?.active_run ? runLabel(current.active_run.status) : '正在提交问题' }}。可以编辑下一轮文字或切换研究。<button v-if="current?.active_run" class="text-button" @click="cancel">停止本轮</button></div>
        <div class="input-heading"><label for="research-question">{{ current ? '继续讨论' : '提出研究问题' }}</label><span><button class="text-button" @click="helpOpen = true">使用说明</button><button class="text-button" :aria-expanded="composerExpanded" @click="composerExpanded = !composerExpanded">{{ composerExpanded ? '收起输入' : '展开输入' }}</button></span></div>
        <textarea id="research-question" ref="composer" :value="local.draft.text" rows="2" :disabled="loading || !!bootstrapError" :placeholder="current ? '继续提问，或补充实际情况…' : '例如：哪些专业的课程安排接近，是否值得共同建设？'" aria-label="研究问题" @input="updateText('draft', ($event.target as HTMLTextAreaElement).value)" @blur="saveField(activeId, 'draft')" @compositionstart="composing = true" @compositionend="composing = false" @keydown="onComposerKey" />
        <div v-if="local.draft.state === 'conflict'" class="warning-inline">问题草稿已在其他窗口更新，当前文字保留。<button class="text-button" @click="draftConflictOpen = true">比较两个版本</button></div>
        <div v-if="local.draft.state === 'error'" class="warning-inline">{{ local.draft.error }}<button class="text-button" @click="saveField(activeId, 'draft')">重试保存</button></div>
        </template>
        <p v-if="result?.method_unavailable" class="warning-inline" role="status">本轮使用的方法已停用，不能整理新材料；历史资料和已有材料仍可查看。</p>
        <div class="composer-bottom"><div class="composer-tools"><button v-if="result" class="text-button" @click="openSources(result)">查看资料</button><button v-if="current" class="text-button" @click="switchPanel('opinion')">我的意见</button><button v-if="result" class="text-button" :disabled="!!result.method_unavailable" :title="result.method_unavailable ? '本轮使用的方法已停用，不能整理新材料' : undefined" @click="materialOptionsOpen = true">整理讨论材料</button><button v-if="result?.method_unavailable && current?.materials.length" class="text-button" @click="materialOptionsOpen = true">查看已有材料</button></div><div v-if="current?.status !== 'archived'" class="send-tools"><small>{{ local.draft.state === 'saved' ? '草稿已保存' : local.draft.state === 'saving' ? '草稿保存中' : '有未保存修改' }} · Ctrl+Enter发送</small><el-button type="primary" :loading="local.sending" :disabled="busy || loading || !local.draft.text.trim()" @click="submit()">发送</el-button></div></div>
      </footer>
    </main>

    <ResearchSidePanel :key="activeId" :panel="local.panel" :sources="local.sources" :source-target="sourceTarget" :source-result="local.sourceResult" :source-loading="local.sourceLoading" :source-error="local.sourceError" :text="local.opinion.text" :save-state="local.opinion.state" :saved-at="local.opinion.base.saved_at" :save-error="local.opinion.error" :conflict="local.opinion.conflict" :excerpt="local.excerpt" :versions="versions" @panel="switchPanel" @close="closePanel" @pin="pinExcerpt" @unpin="local.excerpt = null" @full-source="sourceById" @update:text="updateText('opinion', $event)" @save="saveField(activeId, 'opinion')" @resolve="confirmResolution('opinion', $event)" @versions="loadOpinionVersions" @restore="previewRestore" />
    <ExpertPicker v-model:open="expertOpen" :experts="catalog?.experts || []" :participants="current?.participants || []" :research-id="current?.id" :saving="participantBusy" :readonly="current?.status === 'archived'" @participate="participant" @direct="chooseExpert" />
    <MaterialPreview v-model:open="materialOpen" :material="material" :busy="materialBusy" @error="showError" />
    <el-dialog v-model="helpOpen" title="如何使用专家团" width="min(560px, 94vw)" append-to-body><div class="usage-guide"><h3>围绕一个管理问题持续研究</h3><p>先选择专业、适用年级和需要比较的范围，再写下问题。可以选择专家，也可以直接提问。</p><h3>把分析、依据与个人意见分开</h3><p>分析中的“查看资料”可以打开本轮来源。“我的意见”由你自己编辑，新分析不会替换已有文字。</p><h3>需要时整理讨论材料</h3><p>材料保留形成时的分析和范围，个人意见经你确认后选入；后续讨论不会改写已保存材料。</p><h3>适用范围</h3><p>{{ catalog?.notice }}</p></div><template #footer><el-button type="primary" @click="helpOpen = false">开始研究</el-button></template></el-dialog>
    <el-dialog v-model="materialOptionsOpen" :title="result?.method_unavailable ? '查看已有讨论材料' : '整理本次讨论材料'" width="min(680px, 94vw)" append-to-body>
      <p v-if="result?.method_unavailable" class="warning-inline" role="status">本轮使用的方法已停用。这里可以打开以前保存的材料，不能据此生成新材料。</p>
      <p class="dialog-copy">采用以下有效分析的范围，不采用输入区尚未发送的新条件。材料不会自动随以后的讨论变化。</p>
      <div class="material-scope"><b>{{ planName(current?.scope.plan_id) }}<template v-if="current?.scope.target_plan_id"> 与 {{ planName(current.scope.target_plan_id) }}</template></b><p>{{ result?.scope_label }} · {{ focusLabels[current?.scope.focus || 'all'] }}</p><p>{{ result?.headline }}</p></div>
      <template v-if="local.opinion.text.trim()"><h3 class="material-opinion-title">现有个人意见 · 全文</h3><p class="dialog-copy">这些意见可能形成于先前的范围或结论之下。请逐段确认仍适用于本次材料；不勾选时不会加入，原意见也不会删除。</p><textarea :value="local.opinion.text" class="dialog-text" readonly rows="6" aria-label="本次待确认的个人意见全文" /><el-checkbox v-model="includeOpinion" class="material-confirmation">已确认这些意见适用于本次范围，加入材料</el-checkbox></template>
      <p v-else class="quiet">没有个人意见时，仅整理研究情况，不编造领导意见。</p>
      <div v-if="current?.materials.length" class="old-materials"><h3>以前整理的材料</h3><button v-for="(item, index) in current.materials" :key="item.id" class="text-button" @click="materialOptionsOpen = false; viewMaterial(item.id)">讨论稿 {{ current.materials.length - index }} · {{ researchDate(item.created_at) }}</button></div>
      <template #footer><el-button @click="materialOptionsOpen = false">返回</el-button><el-button type="primary" :disabled="!!result?.method_unavailable" @click="materialOptionsOpen = false; prepareMaterial()">生成内容预览</el-button></template>
    </el-dialog>
    <el-dialog v-model="adoptOpen" :title="adoptMode === 'append' ? '将这段内容纳入我的意见' : '恢复为新的意见版本'" width="min(650px,94vw)" append-to-body><p class="dialog-copy">{{ adoptMode === 'append' ? '内容将追加到现有意见末尾，不替换原有文字。可以先修改。' : '确认后替换当前编辑文字并保存为新版本，原已保存版本仍保留。' }}</p><textarea v-model="adoptText" class="dialog-text" rows="8" aria-label="待采纳的意见内容" /><template #footer><el-button @click="adoptOpen = false">暂不采纳</el-button><el-button type="primary" @click="acceptAdopt">{{ adoptMode === 'append' ? '确认追加' : '确认恢复为新版本' }}</el-button></template></el-dialog>
    <el-dialog v-model="draftConflictOpen" title="比较问题草稿" width="min(650px,94vw)" append-to-body><p class="dialog-copy">当前输入文字仍保留在主页面。下方是另一窗口保存的版本。</p><textarea class="dialog-text" :value="local.draft.conflict?.text || ''" readonly rows="8" aria-label="另一窗口保存的问题" /><template #footer><el-button @click="confirmResolution('draft', true)">采用另一份内容</el-button><el-button type="primary" @click="confirmResolution('draft', false)">保存我的文字为新版本</el-button></template></el-dialog>
    <el-dialog v-model="legacyOpen" title="旧讨论档案 · 只读" width="min(900px,96vw)" append-to-body>
      <p class="dialog-copy">仅展示原来确实保存的结果和文字；未留存的历史依据不会补造。这里不修改旧讨论。</p>
      <p v-if="legacyBusy">正在读取档案……</p>
      <template v-else-if="legacyRecord">
        <button class="text-button" @click="openLegacy()">返回旧讨论列表</button><h2>{{ legacyRecord.title }}</h2>
        <el-button :disabled="!!legacyRecord.request?.student_id" @click="prepareLegacyResearch">以此为基础新建研究</el-button>
        <p v-if="legacyPrepareError" class="warning-inline" role="alert">{{ legacyPrepareError }}</p>
        <p class="quiet">{{ legacyRecord.request?.student_id ? '这份档案含个体学生范围，当前仅供只读查看，不转换为群体研究。' : '仅准备原问题与可用范围。发送后重新读取当前资料，不修改旧档案，也不自动复制个人意见。' }}</p>
        <ResearchResult v-if="legacyResult" :result="legacyResult" :experts="catalog?.experts || []" readonly hide-sources />
        <details v-if="legacyResult?.methods?.length"><summary>原已保存的计算方法</summary><p v-for="(method,i) in legacyResult.methods" :key="i" class="legacy-text">{{ method }}</p></details>
        <details v-for="(document,i) in legacyResult?.documents || []" :key="i"><summary>{{ document.plan }} · 原已保存资料</summary><p class="legacy-text">{{ document.file }}<br>{{ document.basis }}</p><p v-for="issue in document.issues || []" :key="issue" class="quiet">{{ issue }}</p><section v-for="(part,j) in document.sections || []" :key="j"><h3>{{ part.title }}</h3><p class="legacy-text">{{ part.text || '这部分原文未留存。' }}</p></section></details>
        <details v-if="legacyResult?.sources?.length"><summary>原已保存的来源记录</summary><p v-for="source in legacyResult.sources" :key="source.file" class="legacy-text">{{ source.file }}<br>{{ source.detail }}</p></details>
        <details v-for="(message,i) in legacyRecord.messages" :key="i" :open="i > legacyRecord.messages.length - 5"><summary>{{ message.role === 'user' ? '我的问题' : '原分析说明' }}</summary><p class="legacy-text">{{ message.text }}</p></details>
        <h3 v-if="legacyRecord.note">原已保存意见</h3><p class="legacy-text">{{ legacyRecord.note }}</p>
      </template>
      <div v-else class="legacy-list"><button v-for="item in legacyItems" :key="item.id" @click="openLegacy(item.id)"><b>{{ item.title }}</b><small>{{ date(item.updated_at) }}</small></button><p v-if="!legacyItems.length" class="quiet">当前身份没有可读取的旧讨论。</p></div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Fold, Expand, Plus, ArrowUp } from '@element-plus/icons-vue'
import { appendWithoutOverwrite, comparableResearchPlans, isRunning, researchDate, researchPlanLabel, runLabel, shouldSendKey } from '@/utils/expertResearch'
import type { ResearchResult as ResearchResultData, ResearchSummary } from '@/types/expertResearch'
import { useResearchWorkspace } from './useResearchWorkspace'
import { positionConclusion, shouldFollowResult } from './researchReading'
import { availableResearchHeight } from './researchLayout'
import ResearchResult from './ResearchResult.vue'
import ResearchSidePanel from './ResearchSidePanel.vue'
import ExpertPicker from './ExpertPicker.vue'
import ExpertAvatar from './ExpertAvatar.vue'
import type { ResearchExpert } from '@/types/expertResearch'
import MaterialPreview from './MaterialPreview.vue'
import ResearchScopeSelector from './ResearchScopeSelector.vue'

const ws = useResearchWorkspace()
const { catalog, summaries, cursor, activeId, records, locals, current, local, result, busy, loading, loadingResearch, loadingList, bootstrapError, query, archived, sidebarOpen, expertOpen, participantBusy, materialOpen, materialBusy, material, includeOpinion, legacyOpen, legacyItems, legacyRecord, legacyBusy, legacyPrepareError, versions, identityLabel, olderBusy,
  initialize, refreshList, openResearch, updateText, saveField, resolveConflict, submit, cancel, participant, prefill, direct, compare, rename, archive, openSources: requestSources, pinExcerpt, loadOpinionVersions, addQuestion, changeQuestion, prepareMaterial, viewMaterial, openLegacy, prepareLegacyResearch, showError } = ws
const workspace = ref<HTMLElement>(), reading = ref<HTMLElement>(), composer = ref<HTMLTextAreaElement>(), workspaceWidth = ref(1280), composing = ref(false)
const availableWorkspaceHeight = ref(450)
const helpOpen = ref(false)
const composerExpanded = ref(false)
const workspaceTitle = computed(() => {
  if (!current.value) return '今天想研究哪项工作？'
  const first = current.value.turns[0]?.message || ''
  const automatic = first.slice(0, 28) + (first.length > 28 ? '…' : '')
  if (current.value.title !== automatic) return current.value.title
  return ({ program: '专业培养方案研究', course: '课程质量与建设研究', transfer: '转专业培养衔接研究', graduation: '毕业准备情况研究', recommendation: '推免工作准备研究' } as Record<string, string>)[result.value?.expert_id || ''] || '教学管理问题研究'
})
const scopeOpen = ref(false), showQuestions = ref(false), materialOptionsOpen = ref(false), adoptOpen = ref(false), adoptText = ref(''), adoptMode = ref<'append' | 'restore'>('append'), draftConflictOpen = ref(false)
// On medium screens give reading + notes priority, without changing the saved
// navigation preference. Closing the panel restores the original sidebar.
const sidebarVisible = computed(() => sidebarOpen.value && !(local.value.panel && workspaceWidth.value >= 960 && workspaceWidth.value < 1240))
const panelOverlay = computed(() => workspaceWidth.value - (sidebarVisible.value ? 232 : 0) - 360 < 600)
function toggleSidebar() { if (!sidebarVisible.value && local.value.panel) { closePanel(); sidebarOpen.value = true } else sidebarOpen.value = !sidebarOpen.value }
const activeParticipants = computed(() => current.value?.participants.filter(p => p.status === 'active') || [])
const excludedCount = computed(() => current.value?.participants.filter(p => p.status === 'excluded').length || 0)
const openQuestions = computed(() => current.value?.questions.filter(q => q.status === 'open') || [])
const focusLabels = { all: '全部课程代码（含公共课程）', non_common: '已明确的非公共课程', foundation: '专业基础', main: '专业主干', foundation_main: '专业基础与专业主干', practice: '专业实践', required: '逐门必修' }
const sourceTarget = ref('documents')
const planName = (id?: string) => researchPlanLabel(catalog.value?.plans.find(plan => plan.plan_id === id))
const expertName = (id: string) => catalog.value?.experts.find(expert => expert.id === id)?.name || '历史专家'
const date = (value: string) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '时间未提供'
const questionLabel = (status: string) => (({ open: '待明确', deferred: '暂缓', resolved: '已明确' } as Record<string, string>)[status] || '状态待确认')
const comparablePlans = computed(() => comparableResearchPlans(catalog.value?.plans || [], local.value.scope.plan_id))
const legacyResult = computed<ResearchResultData | null>(() => legacyRecord.value?.result ? { ...legacyRecord.value.result, id: `legacy-${legacyRecord.value.id}` } : null)
const examples = computed(() => catalog.value?.role_view === 'dean' ? [
  { title: '本院专业培养', text: '本院两个专业共用哪些课程，培养差异体现在哪里？', expert: 'program' },
  { title: '关键课程', text: '本院哪些课程值得先了解，还需要哪些教学资料？', expert: 'course' },
  { title: '毕业准备', text: '本院毕业准备中，哪些是课程缺口，哪些是记录问题？', expert: 'graduation' },
] : [
  { title: '专业建设', text: '两个专业共用哪些课程，各自的培养重点有什么不同？', expert: 'program' },
  { title: '教学与课程', text: '哪些课程有值得关注的群体表现，还需了解哪些情况？', expert: 'course' },
  { title: '共同保障问题', text: '所选年级毕业准备中，有哪些共性堵点和资料问题？', expert: 'graduation' },
])
async function newResearchDialog() {
  let state = await ws.startNewResearch()
  if (workspaceWidth.value < 880) sidebarOpen.value = false
  if (state === 'draft') {
    const original = local.value, text = original.draft.text
    try {
      await ElMessageBox.confirm('你还有一份尚未发送的研究草稿。继续编辑可保留原文字；清空后将重新选择范围并起草问题。已经发送的讨论不受影响。', '如何处理未发送的草稿？', { confirmButtonText: '清空并重新起草', cancelButtonText: '继续这份草稿', type: 'warning', distinguishCancelAndClose: true })
      if (local.value !== original || activeId.value !== 'new' || original.draft.text !== text) return
      state = await ws.startNewResearch(true)
    } catch { /* Closing or cancelling keeps the original draft. */ }
  }
  if (activeId.value !== 'new') return
  if (state === 'conflict') draftConflictOpen.value = true
  if (state === 'ready') scopeOpen.value = true
  await nextTick(); composer.value?.focus({ preventScroll: true })
}
async function chooseExpert(expert: ResearchExpert) {
  if (!expert.enabled || current.value?.status === 'archived') return
  direct(expert)
  if (workspaceWidth.value < 880) sidebarOpen.value = false
  if (!local.value.scope.plan_id) scopeOpen.value = true
  await nextTick(); composer.value?.focus({ preventScroll: true })
}
function useExample(example: { text: string; expert: string }) {
  prefill(example.text); scopeOpen.value = true; void nextTick(() => composer.value?.focus())
}
function planChanged() { if (!comparablePlans.value.some(plan => plan.plan_id === local.value.scope.target_plan_id)) local.value.scope.target_plan_id = ''; local.value.scope.course_id = ''; local.value.scope.student_id = ''; local.value.scope.baseline_id = '' }
function onComposerKey(event: KeyboardEvent) { if (shouldSendKey(event, composing.value)) { event.preventDefault(); void submit() } }
const readingInteractions = new Set<string>()
let readingInteractionVersion = 0
function markReadingInteraction() { readingInteractions.add(activeId.value); readingInteractionVersion++ }
function markReadingPointer(event: PointerEvent) { if (event.target === reading.value) markReadingInteraction() }
function markReadingKey(event: KeyboardEvent) { if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) markReadingInteraction() }
function rememberScroll() {
  if (!reading.value) return
  local.value.scroll = reading.value.scrollTop
  const conclusion = latestConclusion(), bounds = reading.value.getBoundingClientRect()
  if (conclusion) { const box = conclusion.getBoundingClientRect(); if (box.top >= bounds.top - 16 && box.top < bounds.bottom - 48) local.value.unread = false }
}
function latestConclusion() { const turn = current.value?.turns.at(-1); return turn?.result ? document.getElementById(`research-turn-${turn.id}`)?.querySelector<HTMLElement>('.research-result') || null : null }
async function scrollLatest() { await nextTick(); const conclusion = latestConclusion(); if (reading.value) { if (conclusion) positionConclusion(reading.value, conclusion); else reading.value.scrollTop = reading.value.scrollHeight; local.value.scroll = reading.value.scrollTop } local.value.unread = false }
async function loadEarlier() { const node = reading.value, height = node?.scrollHeight || 0, top = node?.scrollTop || 0; await ws.loadEarlier(); await nextTick(); if (node) node.scrollTop = top + node.scrollHeight - height }
async function openSearchResult(item: ResearchSummary) {
  const turnId = await ws.openSearchResult(item)
  await nextTick()
  if (!turnId || activeId.value !== item.id || !reading.value) return
  const target = document.getElementById(`research-turn-${turnId}`)
  if (!target || !reading.value.contains(target)) return
  reading.value.scrollTop += target.getBoundingClientRect().top - reading.value.getBoundingClientRect().top - 12
  local.value.scroll = reading.value.scrollTop
  target.focus({ preventScroll: true })
}
async function prepareQuestion(text: string) { prefill(text); await nextTick(); composer.value?.focus() }
let panelReturnFocus: HTMLElement | null = null
function rememberPanelOrigin() { if (!local.value.panel) panelReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null }
async function openSources(value: ResearchResultData, target = 'documents') { rememberPanelOrigin(); sourceTarget.value = target; await requestSources(value) }
function switchPanel(panel: 'sources' | 'opinion') { rememberPanelOrigin(); if (panel === 'sources' && !local.value.sources && result.value) void openSources(result.value); else local.value.panel = panel }
function closePanel() { const id = activeId.value, origin = panelReturnFocus; void saveField(id, 'opinion'); local.value.panel = null; panelReturnFocus = null; void nextTick(() => { if (id !== activeId.value) return; if (origin?.isConnected) origin.focus({ preventScroll: true }); else composer.value?.focus({ preventScroll: true }) }) }
function sourceById(id: string) { const value = current.value?.turns.find(turn => turn.result?.id === id)?.result || (result.value?.id === id ? result.value : null); if (value) void openSources(value); else local.value.sourceError = '当前读取的历史中尚无这轮资料，请先加载相应讨论。' }
function previewAdopt(text: string) { adoptMode.value = 'append'; adoptText.value = text; adoptOpen.value = true }
function previewRestore(text: string) { adoptMode.value = 'restore'; adoptText.value = text; adoptOpen.value = true }
async function acceptAdopt() { updateText('opinion', adoptMode.value === 'append' ? appendWithoutOverwrite(local.value.opinion.text, adoptText.value) : adoptText.value); adoptOpen.value = false; local.value.panel = 'opinion'; await saveField(activeId.value, 'opinion') }
async function confirmResolution(field: 'draft' | 'opinion', useRemote: boolean) {
  if (useRemote) { try { await ElMessageBox.confirm('采用另一份内容会替换当前编辑文字。请确认已经保留需要的部分。', '确认采用', { confirmButtonText: '确认采用', cancelButtonText: '返回比较', type: 'warning' }) } catch { return } }
  await resolveConflict(field, useRemote); if (field === 'draft') draftConflictOpen.value = false
}
async function renameDialog() { if (!current.value) return; try { const value = await ElMessageBox.prompt('名称只用于查找研究，不改变已保存范围和计算。', '修改研究名称', { inputValue: current.value.title, inputValidator: value => !!value?.trim() && value.length <= 160 || '请输入1—160字的研究名称。', confirmButtonText: '保存名称', cancelButtonText: '取消' }); await rename(value.value) } catch { /* User cancelled. */ } }
async function archiveDialog() {
  if (!current.value) return
  if (isRunning(current.value.active_run)) { try { await ElMessageBox.confirm('当前分析仍在进行。先提交停止请求，确认已停止后再归档。', '先停止本轮分析', { confirmButtonText: '提交停止请求', cancelButtonText: '返回研究' }); await cancel() } catch { /* User cancelled. */ } return }
  await archive()
}
async function newQuestionDialog() { try { const value = await ElMessageBox.prompt('写清还缺少什么，以及影响哪个判断。不会自动发给其他人。', '新增待明确事项', { inputType: 'textarea', inputValidator: value => !!value?.trim() && value.length <= 2000 || '请填写1—2000字的具体事项。', confirmButtonText: '保存待明确', cancelButtonText: '取消' }); await addQuestion(value.value); showQuestions.value = true } catch { /* User cancelled. */ } }
let observer: ResizeObserver | undefined
function measureWorkspace() {
  if (!workspace.value) return
  const bounds = workspace.value.getBoundingClientRect()
  workspaceWidth.value = bounds.width
  availableWorkspaceHeight.value = availableResearchHeight(window.innerHeight, bounds.top)
}
watch(activeId, async () => { panelReturnFocus = null; await nextTick(); scopeOpen.value = false; if (reading.value) reading.value.scrollTop = local.value.scroll; materialOptionsOpen.value = false; draftConflictOpen.value = false; adoptOpen.value = false; showQuestions.value = false; if (workspaceWidth.value < 880) sidebarOpen.value = false })
watch(() => local.value.error, text => { if (text.includes('请先明确本次使用')) scopeOpen.value = true })
watch(materialOptionsOpen, open => { if (open) ws.beginMaterialPreparation() }, { flush: 'sync' })
watch(workspaceWidth, (width, previous) => { if (width < 880 && previous >= 880) sidebarOpen.value = false })
watch(loadingResearch, async value => { if (!value) { await nextTick(); if (reading.value) reading.value.scrollTop = local.value.scroll } })
watch(() => current.value?.turns.length, async (_count, previous) => { if (!reading.value || !previous || loadingResearch.value || current.value?.turns.at(-1)?.result) return; const id = activeId.value, nearBottom = reading.value.scrollHeight - reading.value.scrollTop - reading.value.clientHeight < 64; if (nearBottom) { await nextTick(); if (reading.value && activeId.value === id) { reading.value.scrollTop = reading.value.scrollHeight; local.value.scroll = reading.value.scrollTop } } })
watch(() => { const turn = current.value?.turns.at(-1); return { researchId: activeId.value, turnId: turn?.id || '', resultId: turn?.result?.id || '' } }, async (next, previous) => {
  if (!reading.value || !previous || next.researchId !== previous.researchId || !next.resultId || (next.turnId === previous.turnId && next.resultId === previous.resultId) || loadingResearch.value) return
  const follow = shouldFollowResult(previous, next, { loading: loadingResearch.value, firstRound: current.value?.turns.length === 1, wasAtEnd: reading.value.scrollHeight - reading.value.scrollTop - reading.value.clientHeight < 64, userInteracted: readingInteractions.has(next.researchId) })
  if (!follow) { local.value.unread = true; return }
  const interaction = readingInteractionVersion
  await nextTick()
  if (activeId.value !== next.researchId || interaction !== readingInteractionVersion || !reading.value) return
  const conclusion = latestConclusion()
  if (conclusion && positionConclusion(reading.value, conclusion)) { local.value.scroll = reading.value.scrollTop; local.value.unread = false }
}, { flush: 'pre' })
const sidebarPreferenceKey = 'expert-research-sidebar-open'
watch(sidebarOpen, value => { try { window.localStorage.setItem(sidebarPreferenceKey, value ? '1' : '0') } catch { /* Layout preference is optional; never persist business content. */ } })
onMounted(() => { try { sidebarOpen.value = window.localStorage.getItem(sidebarPreferenceKey) !== '0' } catch { /* Default to the expanded navigation. */ } observer = new ResizeObserver(measureWorkspace); if (workspace.value) observer.observe(workspace.value); measureWorkspace(); window.addEventListener('resize', measureWorkspace) })
onBeforeUnmount(() => { observer?.disconnect(); window.removeEventListener('resize', measureWorkspace) })
</script>

<style lang="scss" scoped>
.search-snippet{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:11px;line-height:1.7;color:#8c8597;margin-top:5px}.turn:focus-visible{outline:2px solid #9a84c5;outline-offset:5px;border-radius:5px}
.research-workspace{--accent:#6f56a5;--ink:#2c3142;--muted:#7e8596;display:flex;position:relative;height:calc(100vh - 126px);min-height:600px;background:#fff;border:1px solid #e4e6ed;border-radius:12px;overflow:hidden;color:var(--ink);font-family:inherit}.research-workspace button,.research-workspace input,.research-workspace textarea{font-family:inherit}.research-workspace button{cursor:pointer}.research-workspace button:disabled{cursor:not-allowed;opacity:.55}.research-workspace button:focus-visible,.research-workspace summary:focus-visible,.research-workspace input:focus-visible,.research-workspace textarea:focus-visible{outline:2px solid #9a84c5;outline-offset:3px}.research-sidebar{width:232px;min-width:232px;display:flex;flex-direction:column;background:#f8f9fc;border-right:1px solid #e7e8ef;padding:22px 14px 14px;box-sizing:border-box;min-height:0}.sidebar-heading{display:flex;justify-content:space-between;align-items:center;padding:0 8px 18px}.sidebar-heading small{font-size:11px;letter-spacing:1px;color:#9993a7}.sidebar-heading h2{font-size:20px;font-weight:600;margin:5px 0 0}.icon-button{width:30px;height:32px;border:0;background:none;color:#81768f;font-size:25px;border-radius:5px}.icon-button:hover{background:#eeebf5}.new-research{border:1px solid #d8cee8;border-radius:7px;background:#fff;color:#6c5598;padding:10px;font-size:14px;font-weight:500}.research-search{width:100%;box-sizing:border-box;margin:16px 0 10px;padding:10px 11px;font-size:12px;border:1px solid #e6e6ee;border-radius:6px;background:#fff;color:#484b5d}.research-search::placeholder{color:#9296a3}.list-switch{display:flex;gap:18px;padding:0 6px 10px}.list-switch button{border:0;background:none;padding:5px 0;color:#9296a4;font-size:12px}.list-switch button.selected{color:#655086;font-weight:550}.research-list{overflow:auto;flex:1;min-height:80px}.research-list>button{display:block;width:100%;text-align:left;border:0;border-left:3px solid transparent;border-radius:6px;background:none;color:#555d70;padding:11px 10px;margin-bottom:4px}.research-list>button.selected{background:#eeebf7;border-left-color:#8465b7;color:#564477}.research-list>button:hover{background:#f0eef6}.research-list b{font-size:13px;line-height:1.7;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.research-list small{font-size:10px;color:#9192a0;display:block;margin-top:5px;line-height:1.6}.running-dot{color:#786395}.quiet{font-size:12px;line-height:1.85;color:#858a99}.sidebar-empty{padding:8px 9px}.research-list .more{text-align:center;font-size:12px;color:#74608e}.participants{border-top:1px solid #e4e5ed;margin-top:18px;padding-top:15px;max-height:34%;overflow:auto}.participants>summary{font-size:12px;color:#7c7889;padding:0 8px 9px;cursor:pointer}.participants>summary span{margin-left:7px;color:#b0a6be}.participants>.quiet{padding:0 8px}.participants>button{display:flex;align-items:center;gap:10px;padding:9px 8px;width:100%;border:0;background:none;text-align:left}.expert-mark{display:flex;align-items:center;justify-content:center;width:29px;height:29px;border-radius:7px;background:#efebf6;color:#8a70a8;font-size:13px}.participants b{display:block;font-size:12px;font-weight:500;color:#53566c}.participants small{display:block;font-size:10px;line-height:1.6;color:#9895a2;margin-top:2px}.participants .add-expert{font-size:12px;color:#7b6499;margin-top:4px}.legacy-entry{margin-top:17px;padding:10px 4px;border:0;border-top:1px solid #e5e6ef;background:none;color:#85808e;font-size:11px;text-align:left}.side-footnote{font-size:10px;color:#a4a5ae;margin:2px 4px;line-height:1.7}.research-main{display:flex;flex:1;min-width:0;flex-direction:column;background:#fff;position:relative;min-height:0}.research-header{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:24px 30px 12px}.heading-left{display:flex;gap:12px;align-items:flex-start;min-width:0}.menu-toggle{font-size:17px;margin:3px 0 0;width:24px;flex-shrink:0}.identity{font-size:11px;color:#9694a1;letter-spacing:.2px;margin:0 0 7px}.research-header h1{font-size:21px;line-height:1.6;font-weight:600;margin:0;color:#323244;overflow-wrap:anywhere}.current-scope{font-size:11px;line-height:1.7;color:#8c8b99;margin:6px 0 0}.header-tools{display:flex;align-items:center;gap:15px;padding-top:15px;flex-shrink:0}.text-button{border:0;background:none;padding:3px 0;color:#77628f;font-size:12px;line-height:1.7}.text-button:hover{text-decoration:underline}.capability-notice{font-size:11px;line-height:1.8;color:#918c99;margin:0 31px 10px;max-height:44px;overflow:auto}.error-banner,.notice-banner{padding:9px 14px;font-size:12px;line-height:1.85;margin:0 26px 10px;border-radius:6px}.error-banner{background:#fff1ed;color:#9c604c;border:1px solid #efdbd2}.notice-banner{background:#f7f4fc;color:#7f7191;border:1px solid #e8e1f0}.error-banner .text-button,.notice-banner .text-button{margin-left:10px}.reading-scroll{overflow:auto;flex:1;min-height:90px;padding:12px max(28px,calc((100% - 820px)/2)) 22px;scrollbar-gutter:stable}.welcome{padding:24px 2px 14px;max-width:800px}.welcome-eyebrow{font-size:12px;color:#9a86b6}.welcome h2{font-size:25px;line-height:1.7;font-weight:550;margin:12px 0 15px;max-width:690px}.welcome>p:not(.quiet){font-size:14px;line-height:1.9;color:#858997;max-width:650px}.question-examples{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:25px 0 17px}.question-examples button{text-align:left;padding:16px 15px;border:1px solid #e7e4ec;border-radius:9px;background:#fcfbfd;display:flex;flex-direction:column;gap:10px}.question-examples span{font-size:11px;color:#a096ad}.question-examples b{font-size:13px;line-height:1.85;font-weight:500;color:#686477}.question-examples small{font-size:11px;color:#9d8caf;margin-top:auto}.question-examples button:hover{border-color:#c6b9da;background:#f7f4fc}.research-progress{padding:13px 16px;border:1px solid #e8e5ef;background:#fbfafe;border-radius:8px;margin:3px 0 25px}.research-progress summary{font-size:12px;color:#76628b;cursor:pointer;font-weight:550}.research-progress summary span{margin-left:10px;font-size:10px;color:#a09aa9;font-weight:400}.research-progress p{font-size:12px;color:#7c778a;line-height:1.85;margin:9px 0 0;display:flex;gap:10px;flex-wrap:wrap}.research-progress p b{font-weight:500;color:#655b76;flex-shrink:0}.research-progress p:first-of-type{display:block}.research-progress p:first-of-type b{margin-right:10px}.research-progress p span{font-size:11px;color:#aaa4b0}.turn{margin-bottom:28px}.user-question{margin:8px 0 23px;padding:13px 16px;background:#f7f6fa;border-radius:8px;border:1px solid #eeecf2}.user-question small{font-size:10px;color:#a09aa8}.user-question p{font-size:15px;line-height:1.9;margin:7px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}.run-state{font-size:13px;color:#8e7ca1;padding:18px 4px;line-height:1.8}.run-state p{font-size:12px;color:#968b95}.run-state.failed{color:#aa735f}.status-dot{display:inline-block;width:7px;height:7px;background:#b9aacb;border-radius:50%;margin-right:9px}.status-dot.working{animation:pulse 1.5s infinite}.questions-inline{border-top:1px solid #eae7ef;padding-top:15px;margin:18px 0}.questions-inline article{padding:13px 0;border-bottom:1px solid #efedf3;font-size:13px;line-height:1.8}.questions-inline article>div{display:flex;gap:15px;color:#92849f;font-size:11px}.questions-inline article p{margin:8px 0;color:#625b6e}.load-history{display:block;width:100%;border:0;background:#f8f7fb;padding:10px;color:#877394;font-size:12px;margin-bottom:16px;border-radius:6px}.new-content{text-align:center;height:0;z-index:2;position:relative;bottom:35px}.new-content button{background:#f2edf9;color:#7c6598;border:1px solid #ddcfea;border-radius:14px;font-size:11px;padding:6px 13px;box-shadow:0 2px 8px #37304a0d}.research-composer{border-top:1px solid #e7e6ed;padding:12px 28px 15px;background:#fff;flex-shrink:0}.scope-settings{margin-bottom:9px;font-size:12px;color:#7a7088}.scope-settings>summary{cursor:pointer;padding:3px 0}.scope-settings>summary small{font-size:11px;color:#a39aaa;margin-left:12px}.scope-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px 12px;padding:13px 0 3px;max-height:180px;overflow:auto}.scope-grid label{font-size:11px;color:#8a8095;display:flex;flex-direction:column;gap:6px}.scope-grid :deep(.el-select__wrapper){font-size:12px}.research-composer>textarea{display:block;width:100%;box-sizing:border-box;border:1px solid #dcd7e7;border-radius:9px;min-height:116px;max-height:220px;resize:vertical;padding:13px 15px;font-size:15px;line-height:1.85;color:#4c455b;background:#fefeff}.research-composer>textarea::placeholder{color:#aaa4b5}.composer-bottom{display:flex;justify-content:space-between;gap:13px;align-items:center;margin-top:10px}.composer-tools{display:flex;flex-wrap:wrap;gap:16px}.composer-tools .text-button{font-size:11px}.send-tools{display:flex;align-items:center;gap:12px;flex-shrink:0}.send-tools>small{font-size:10px;color:#aaa5b1}.send-tools :deep(.el-button--primary){background:#78609e;border-color:#78609e;padding:9px 24px;height:34px}.directed,.composer-busy,.warning-inline{font-size:11px;line-height:1.8;margin:8px 0;color:#907ba4;background:#faf7ff;padding:6px 10px;border-radius:5px}.directed .text-button,.composer-busy .text-button,.warning-inline .text-button{margin-left:12px}.warning-inline{color:#ac8554;background:#fff9ed}.research-workspace.panel-overlay:deep(.auxiliary-panel){position:absolute;right:0;top:0;bottom:0;box-shadow:-14px 0 38px #30254018;width:min(390px,95%);min-width:0}.narrow .research-sidebar{position:absolute;left:0;top:0;bottom:0;z-index:30;box-shadow:15px 0 30px #3025401c;width:232px}.dialog-copy{font-size:13px;line-height:1.9;color:#7f788b}.dialog-text{width:100%;box-sizing:border-box;padding:13px;border:1px solid #dcd8e6;border-radius:7px;font:inherit;font-size:14px;line-height:1.85;color:#51495f;resize:vertical}.old-materials{border-top:1px solid #e7e2eb;margin-top:22px;padding-top:13px}.old-materials h3{font-size:13px;color:#7c6e88}.old-materials button{display:block;text-align:left;padding:8px 0}.legacy-list{max-height:55vh;overflow:auto}.legacy-list button{display:flex;flex-direction:column;gap:7px;text-align:left;background:#faf9fc;border:1px solid #e8e4ee;border-radius:6px;width:100%;margin:8px 0;padding:13px}.legacy-list b{font-weight:500;font-size:13px}.legacy-list small{font-size:11px;color:#9a93a1}.legacy-text{white-space:pre-wrap;line-height:1.9;font-size:14px;overflow-wrap:anywhere}@keyframes pulse{50%{opacity:.3}}@media(max-width:1200px){.research-header{padding:18px 22px 10px}.reading-scroll{padding:12px 24px 20px}.research-composer{padding:10px 22px 13px}.welcome h2{font-size:22px}.question-examples{gap:8px}.question-examples button{padding:13px}.scope-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.send-tools>small{display:none}}@media(max-width:780px){.research-workspace{min-height:590px}.research-header h1{font-size:18px}.header-tools{padding-top:6px}.research-header{gap:8px}.question-examples{grid-template-columns:1fr}.question-examples button{display:block}.question-examples b{display:block;margin:6px 0}.question-examples small{display:none}.scope-grid{grid-template-columns:1fr 1fr}.composer-bottom{align-items:flex-end}.composer-tools{gap:9px}.composer-tools .text-button{font-size:10px}.research-composer>textarea{font-size:14px}.welcome{padding-top:10px}.welcome h2{font-size:20px}.research-workspace.panel-overlay:deep(.auxiliary-panel){width:95%}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important}}
/* Keep first-use choices visible without shrinking the discussion composer. */
.welcome{padding:2px 0 6px}.welcome .welcome-intro{font-size:13px;line-height:1.7;color:#655e73;margin:0 0 10px;max-width:none}.welcome .question-examples{margin:0;gap:10px}.welcome .question-examples button{padding:11px 12px;gap:6px}.welcome .question-examples span{font-size:12px;color:#6f617f}.welcome .question-examples b{font-size:13px;line-height:1.65;color:#514b60}.welcome .question-examples small{font-size:12px;color:#78628f;margin-top:auto}.research-workspace .quiet{color:#6d6779}.research-sidebar small,.sidebar-heading small,.research-sidebar .legacy-entry,.side-footnote,.identity,.current-scope,.capability-notice,.research-progress summary span,.research-progress p span,.scope-settings>summary small,.scope-grid label,.composer-tools .text-button,.send-tools>small,.directed,.composer-busy,.warning-inline,.search-snippet{font-size:12px}.research-sidebar small,.side-footnote,.current-scope,.capability-notice,.research-progress summary span,.research-progress p span,.scope-settings>summary small,.scope-grid label,.send-tools>small,.search-snippet{color:#6f687a}.identity,.list-switch button,.research-sidebar .legacy-entry{color:#6c617b}.research-sidebar .participants b{font-size:13px}.capability-notice{max-height:48px}.research-list small{line-height:1.55}.user-question small{font-size:12px;color:#756d80}
.welcome>p.welcome-intro{font-size:13px;line-height:1.7;color:#655e73;margin:0 0 10px;max-width:none}.research-search::placeholder{color:#746c80}.research-composer>textarea::placeholder{color:#746b80}.participants>summary,.participants>summary span{font-size:12px;color:#6f687a}.research-progress p{color:#685f76}
.material-scope{padding:12px 14px;background:#f7f5fb;border:1px solid #e6e0ef;border-radius:7px;font-size:13px;line-height:1.8;color:#554a65}.material-scope p{margin:6px 0 0}.material-opinion-title{font-size:14px;color:#554a65;margin:20px 0 8px}.material-confirmation{margin-top:12px;max-width:100%;height:auto}.material-confirmation:deep(.el-checkbox__label){white-space:normal;line-height:1.7}
.research-header h1,.current-scope{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.heading-left>div{min-width:0}.research-header{flex-shrink:0}.header-tools{flex-wrap:wrap;justify-content:flex-end;max-width:180px}
.research-workspace{height:calc(100dvh - 126px);min-height:0}.research-sidebar{z-index:30}.scope-settings{min-height:0}.research-composer{min-height:0}
@media(max-height:640px){.research-header{padding:12px 22px 8px}.capability-notice{margin-bottom:6px;max-height:44px}.research-composer{display:flex;flex-direction:column;max-height:64%;padding:8px 22px 10px;overflow:hidden}.scope-settings{flex:0 1 auto;overflow:auto;max-height:100px;margin-bottom:6px}.research-composer>textarea{flex-shrink:0;min-height:116px;max-height:140px}.composer-bottom{flex-shrink:0;margin-top:7px}.research-composer>.warning-inline,.research-composer>.directed,.research-composer>.composer-busy{flex:0 1 auto;min-height:0;max-height:42px;overflow:auto;margin:4px 0}.reading-scroll{min-height:35px;padding-top:6px;padding-bottom:12px}.scope-grid{max-height:110px}}
@media(max-height:620px){.research-header{padding:8px 22px 6px}.research-header h1{font-size:18px;line-height:1.45}.identity{margin-bottom:3px}.header-tools{padding-top:4px}.capability-notice{max-height:36px;margin-bottom:4px}.research-composer>textarea{height:80px;min-height:80px;max-height:80px;resize:none;overflow:auto}.scope-settings{margin-bottom:4px}.reading-scroll{min-height:150px}}
@media(max-height:620px){.capability-notice{flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-height:none;line-height:1.8}}
/* Short screens use their real remaining height, not the desktop header allowance.
   Keep the send row inside the workspace; optional context scrolls independently. */
@media(max-height:640px){
  .research-workspace{height:var(--available-workspace-height,calc(100dvh - 72px));box-sizing:border-box}
  .research-header{flex:0 1 auto;min-height:56px;max-height:96px;overflow:auto;box-sizing:border-box}
  .research-main>.error-banner,.research-main>.notice-banner{flex:0 0 auto;max-height:36px;box-sizing:border-box;overflow:auto;padding:4px 10px;margin-bottom:4px}
  .capability-notice{flex:0 0 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-height:none;line-height:1.8;margin-bottom:4px}
  .reading-scroll{flex:1 1 150px;min-height:100px;box-sizing:border-box}
  .research-composer{flex:0 1 auto;min-height:158px;max-height:224px;box-sizing:border-box}
  .research-composer>textarea{height:80px;min-height:80px;max-height:80px;resize:none;overflow:auto}
  .composer-bottom{flex:0 0 auto;min-height:34px}
  .composer-tools{min-width:0;max-height:56px;overflow:auto}
}
.participants .participant-avatar{width:34px;height:34px;border-radius:10px}.participants .participant-avatar:deep(svg){width:19px;height:19px}.participants>button:not(.add-expert){border:1px solid #e7e0ee;background:#fff;border-radius:9px;padding:10px 9px;margin-top:9px;gap:9px}.participants>button:not(.add-expert):hover{border-color:#b7a4cb;background:#fdfbff}
@media(min-height:641px) and (max-height:800px){.research-header{padding-top:14px;padding-bottom:8px}.research-composer>textarea{height:96px;min-height:96px;max-height:128px}.reading-scroll{min-height:160px}}
</style>
<style lang="scss" scoped src="./leadership.scss"></style>
