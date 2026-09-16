import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { authStore } from '@/store/auth'
import { researchApi, ResearchApiError, newRequestId, isRunning, comparableResearchPlans, clearAcceptedText, appendWithoutOverwrite, type Research, type ResearchCatalog, type ResearchSummary, type ResearchScope, type ResearchMaterial, type ResearchSources, type ResearchResult, type ResearchQuestion, type ResearchExpert, type SavedText, type SaveTextBody } from '@/utils/expertResearch'
import type { TeamSession } from '@/utils/expertTeam'
import { mergeResearchSnapshot } from './researchSnapshot'

type FieldName = 'draft' | 'opinion'
interface EditableText { text: string; base: SavedText; state: 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'; conflict: SavedText | null; pending: SaveTextBody | null; inFlight: boolean; error: string }
export interface ReferenceExcerpt { title: string; text: string; resultId: string }
interface LocalResearch {
  draft: EditableText; opinion: EditableText; scope: ResearchScope; scopeBase: ResearchScope; directed: string; panel: 'sources' | 'opinion' | null
  sources: ResearchSources | null; sourceResult: ResearchResult | null; sourceError: string; sourceLoading: boolean; excerpt: ReferenceExcerpt | null
  scroll: number; sending: boolean; pendingSubmit: { message: string; scope: ResearchScope; client_request_id: string; expert_id?: string; expected_context_epoch?: number } | null; error: string; notice: string; unread: boolean
}
const emptyText = (): EditableText => ({ text: '', base: { text: '', revision: 0 }, state: 'saved', conflict: null, pending: null, inFlight: false, error: '' })
const emptyLocal = (): LocalResearch => ({ draft: emptyText(), opinion: emptyText(), scope: { plan_id: '', focus: 'non_common' }, scopeBase: { plan_id: '', focus: 'non_common' }, directed: '', panel: null, sources: null, sourceResult: null, sourceError: '', sourceLoading: false, excerpt: null, scroll: 0, sending: false, pendingSubmit: null, error: '', notice: '', unread: false })
const sameScope = (left: ResearchScope, right: ResearchScope) => [...new Set([...Object.keys(left), ...Object.keys(right)])].every(key => (left[key as keyof ResearchScope] ?? '') === (right[key as keyof ResearchScope] ?? ''))

export function useResearchWorkspace() {
  const catalog = ref<ResearchCatalog | null>(null), summaries = ref<ResearchSummary[]>([]), cursor = ref(''), activeId = ref('new')
  const records = reactive<Record<string, Research>>({}), locals = reactive<Record<string, LocalResearch>>({ new: emptyLocal() })
  const loading = ref(true), loadingResearch = ref(false), loadingList = ref(false), bootstrapError = ref(''), query = ref(''), archived = ref(false)
  const sidebarOpen = ref(true), expertOpen = ref(false), participantBusy = ref(false), materialOpen = ref(false), materialBusy = ref(false), material = ref<ResearchMaterial | null>(null), includeOpinion = ref(false)
  const legacyOpen = ref(false), legacyItems = ref<{ id: string; title: string; expert_id: string; updated_at: string }[]>([]), legacyRecord = ref<TeamSession | null>(null), legacyBusy = ref(false), legacyPrepareError = ref(''), versions = ref<SavedText[]>([]), olderBusy = ref(false)
  const expandedHistory = new Set<string>()
  const rejectedMaterialResults = new Map<string, string>()
  let epoch = 0, disposed = false, selectionTicket = 0, listTicket = 0, pollBusy = false, pollTimer: ReturnType<typeof setInterval> | undefined
  const saveTimers = new Map<string, ReturnType<typeof setTimeout>>()
  const current = computed(() => records[activeId.value] || null), local = computed(() => locals[activeId.value] || locals.new)
  const busy = computed(() => isRunning(current.value?.active_run) || local.value.sending)
  const result = computed(() => current.value?.current_result?.status === 'reference' ? null : current.value?.current_result || null)
  const identityLabel = computed(() => authStore.user?.roleName || '当前工作身份')
  const valid = (ticket: number) => !disposed && ticket === epoch
  const ensure = (id: string) => locals[id] || (locals[id] = emptyLocal())

  function mergeText(target: EditableText, saved?: SavedText) {
    if (!saved || saved.revision < target.base.revision) return
    if (target.text === target.base.text || target.text === saved.text) {
      target.text = saved.text; target.base = { ...saved }; target.conflict = null; target.error = ''; target.state = 'saved'
    } else if (saved.revision !== target.base.revision && saved.text !== target.base.text) {
      if (target.pending?.text === saved.text) { target.base = { ...saved }; target.state = 'dirty' }
      else { target.conflict = { ...saved }; target.state = 'conflict' }
    } else if (saved.revision > target.base.revision) target.base = { ...saved }
  }
  function mergeResearch(value: Research) {
    const rejectedResult = rejectedMaterialResults.get(value.id)
    if (rejectedResult && value.current_result?.id === rejectedResult) value = { ...value, current_result: null }
    else if (value.current_result) rejectedMaterialResults.delete(value.id)
    const old = records[value.id]
    if (old) value = mergeResearchSnapshot(old, value, expandedHistory.has(value.id))
    const wasKnown = !!locals[value.id], state = ensure(value.id)
    mergeText(state.draft, value.draft); mergeText(state.opinion, value.opinion)
    // Follow server-resolved scope only while no unsent scope edits are being prepared.
    if (!wasKnown || (!old && !state.scope.plan_id) || sameScope(state.scope, state.scopeBase)) state.scope = { ...value.scope }
    state.scopeBase = { ...value.scope }
    if (old?.current_result?.id !== value.current_result?.id && value.current_result) state.unread = !!old
    records[value.id] = value
    if (!value.active_run && state.notice === '问题已收到。可以继续编辑下一轮问题或切换研究。') state.notice = ''
    const at = summaries.value.findIndex(s => s.id === value.id)
    if (at >= 0) summaries.value[at] = { ...summaries.value[at], id: value.id, title: value.title, updated_at: value.updated_at, status: value.status, metadata_revision: value.metadata_revision }
  }
  function showError(error: unknown, id = activeId.value) {
    const message = error instanceof Error ? error.message : '操作未完成，请稍后重试。'
    if (error instanceof ResearchApiError && [401, 403].includes(error.status)) {
      epoch++; saveTimers.forEach(clearTimeout); saveTimers.clear(); rejectedMaterialResults.clear(); Object.keys(records).forEach(key => delete records[key]); Object.keys(locals).forEach(key => delete locals[key]); locals.new = emptyLocal()
      activeId.value = 'new'; summaries.value = []; catalog.value = null; materialOpen.value = false; legacyOpen.value = false; expertOpen.value = false; material.value = null; legacyRecord.value = null; legacyItems.value = []; versions.value = []; loadingResearch.value = false; loading.value = false; pollBusy = false; bootstrapError.value = message
      return
    }
    ensure(id).error = message
  }
  async function refreshList(append = false) {
    const ticket = epoch, serial = ++listTicket; loadingList.value = true
    try { const data = await researchApi.list(query.value, archived.value, append ? cursor.value : ''); if (!valid(ticket) || serial !== listTicket) return; summaries.value = append ? [...summaries.value, ...data.items.filter(item => !summaries.value.some(old => old.id === item.id))] : data.items; cursor.value = data.next_cursor || '' }
    catch (error) { if (valid(ticket)) showError(error) } finally { if (valid(ticket) && serial === listTicket) loadingList.value = false }
  }
  function scheduleSave(id: string, field: FieldName) {
    const key = `${id}:${field}`, timer = saveTimers.get(key)
    if (timer) clearTimeout(timer)
    saveTimers.set(key, setTimeout(() => { saveTimers.delete(key); void saveField(id, field) }, 700))
  }
  function updateText(field: FieldName, text: string) {
    const id = activeId.value, value = ensure(id)[field]
    value.text = text; if (!value.conflict) value.state = text === value.base.text ? 'saved' : 'dirty'
    if (!loading.value && (id !== 'new' || field === 'draft')) scheduleSave(id, field)
  }
  async function saveField(id: string, field: FieldName): Promise<boolean> {
    const state = ensure(id)[field], ticket = epoch
    if (id === 'new' && field === 'opinion') return false
    if (state.inFlight || state.conflict) return false
    if (state.text === state.base.text && !state.pending) return true
    if (state.text.length > (field === 'draft' ? 4000 : 24000)) { state.state = 'error'; state.error = field === 'draft' ? '问题超过4000字，文字已保留，请分次研究。' : '意见超过24000字，文字已保留，请缩减后再保存。'; return false }
    state.inFlight = true; state.state = 'saving'; state.error = ''
    const body = state.pending || { text: state.text, revision: state.base.revision, client_request_id: newRequestId() }; state.pending = body
    try {
      const saved = await researchApi.saveText(id, field, body)
      if (!valid(ticket)) return false
      // An older acknowledgement must not erase a newer GET version or a conflict already shown.
      if (saved.revision < Math.max(state.base.revision, state.conflict?.revision || 0, records[id]?.[field].revision || 0)) {
        state.pending = null
        state.state = state.conflict ? 'conflict' : state.text === state.base.text ? 'saved' : 'dirty'
        return state.state === 'saved'
      }
      state.base = { ...saved }; state.pending = null; state.conflict = null; state.state = state.text === saved.text ? 'saved' : 'dirty'
      if (records[id]) records[id][field] = { ...saved }
      return state.state === 'saved'
    } catch (error) {
      if (!valid(ticket)) return false
      if (error instanceof ResearchApiError && error.status === 409) {
        try { const remote = await researchApi.text(id, field); if (!valid(ticket)) return false; state.conflict = remote; state.pending = null; state.state = 'conflict' }
        catch { if (valid(ticket)) { state.state = 'error'; state.error = '未能读取另一版本，请保留文字后重试。' } }
      } else { state.state = 'error'; state.error = error instanceof Error ? error.message : '暂未保存，请重试。'; if (error instanceof ResearchApiError && [401, 403].includes(error.status)) showError(error, id) }
      return false
    } finally { if (valid(ticket)) { state.inFlight = false; if (state.state === 'dirty') scheduleSave(id, field) } }
  }
  async function resolveConflict(field: FieldName, useRemote: boolean) {
    const state = local.value[field]; if (!state.conflict) return
    const remote = { ...state.conflict }; if (useRemote) state.text = remote.text
    state.base = remote; state.conflict = null; state.pending = null; state.state = state.text === remote.text ? 'saved' : 'dirty'
    if (!useRemote) await saveField(activeId.value, field)
  }
  async function flush(id = activeId.value) { await Promise.all([saveField(id, 'draft'), ...(id === 'new' ? [] : [saveField(id, 'opinion')])]) }
  async function openResearch(id: string) {
    void flush(); const ticket = epoch, selection = ++selectionTicket
    activeId.value = id; ensure(id); loadingResearch.value = id !== 'new'; materialOpen.value = false; versions.value = []
    if (id === 'new') return
    try { const value = await researchApi.get(id); if (!valid(ticket)) return; mergeResearch(value); if (selection === selectionTicket) { ensure(id).unread = false; await nextTick() } }
    catch (error) { if (valid(ticket)) showError(error, id) } finally { if (valid(ticket) && selection === selectionTicket) loadingResearch.value = false }
  }
  async function openSearchResult(item: ResearchSummary): Promise<string | null> {
    const ticket = epoch, matched = query.value.trim() ? item.matched_turn_id : undefined
    await openResearch(item.id)
    if (!valid(ticket) || activeId.value !== item.id || !matched) return null
    if (!current.value?.turns.some(turn => turn.id === matched) && item.match_seq != null) await loadEarlier(item.match_seq + 1)
    if (!valid(ticket) || activeId.value !== item.id) return null
    if (current.value?.turns.some(turn => turn.id === matched)) return matched
    ensure(item.id).notice = '已打开研究，但暂未读到匹配的讨论位置，可重试搜索或加载更早讨论。'
    return null
  }
  async function startNewResearch(clearDraft = false) {
    await openResearch('new')
    query.value = ''; archived.value = false
    const state = ensure('new')
    state.panel = null
    if (state.sending || state.pendingSubmit) {
      state.notice = '上一条新研究问题的提交结果尚未确认，文字已保留。请等待结果或重试原问题，避免重复建立研究。'
      return 'pending' as const
    }
    if (state.draft.conflict) {
      state.error = '草稿在其他窗口有更新，请先比较两个版本，再开始新研究。'
      return 'conflict' as const
    }
    if (state.draft.text.trim() && !clearDraft) {
      state.notice = '已打开尚未发送的研究草稿，原有文字和范围保留。'
      return 'draft' as const
    }
    if (clearDraft) updateText('draft', '')
    state.scope = { plan_id: '', focus: 'non_common' }; state.scopeBase = { ...state.scope }; state.directed = ''
    state.error = ''; state.scroll = 0; state.unread = false
    state.notice = '已开始一项新研究。请选择专业与培养方案，写下问题后发送；此前讨论仍保留在研究列表中。'
    return 'ready' as const
  }
  async function submit(scopeOverride?: ResearchScope) {
    const id = activeId.value, state = ensure(id), record = records[id], ticket = epoch
    if (state.sending || isRunning(record?.active_run) || record?.status === 'archived') return
    if (state.draft.conflict) { state.error = '问题草稿在其他窗口更新，请先比较版本。'; return }
    const scope = { ...(scopeOverride || state.scope) }, text = state.draft.text
    if (!text.trim()) { state.error = '请先写下要研究的问题。'; return }
    if (!scope.plan_id) { state.error = '请先明确本次使用的专业与培养方案，不能把历史方案自动当作本届。'; return }
    if (text.length > 4000) { state.error = '本次问题较长，请保留文字后分次研究，每次不超过4000字。'; return }
    state.sending = true; state.error = ''
    if (!state.pendingSubmit) state.pendingSubmit = { message: text, scope, client_request_id: newRequestId(), ...(state.directed ? { expert_id: state.directed } : {}), ...(record ? { expected_context_epoch: record.context_epoch } : {}) }
    const body = state.pendingSubmit
    try {
      const value = record ? await researchApi.turn(id, { ...body, kind: 'analysis', expected_context_epoch: body.expected_context_epoch! }) : await researchApi.create(body)
      if (!valid(ticket)) return
      const preparedScope = { ...state.scope }
      mergeResearch(value)
      const accepted = clearAcceptedText(state.draft.text, body.message)
      state.draft.text = accepted; state.pendingSubmit = null; state.directed = ''; state.notice = '问题已收到。可以继续编辑下一轮问题或切换研究。'
      const destination = ensure(value.id)
      if (id === 'new') { destination.scope = sameScope(preparedScope, body.scope) ? { ...value.scope } : preparedScope; destination.scopeBase = { ...value.scope }; destination.draft.text = accepted; destination.draft.state = accepted === destination.draft.base.text ? 'saved' : 'dirty'; if (activeId.value === id) activeId.value = value.id; scheduleSave('new', 'draft') }
      else destination.draft.text = accepted
      destination.draft.state = accepted === destination.draft.base.text ? 'saved' : 'dirty'; scheduleSave(value.id, 'draft')
      void refreshList()
    } catch (error) {
      if (!valid(ticket)) return
      if (error instanceof ResearchApiError && error.status >= 400 && error.status < 500) state.pendingSubmit = null
      showError(error, id)
    } finally { if (valid(ticket)) state.sending = false }
  }
  async function cancel() {
    const record = current.value; if (!record?.active_run) return
    const ticket = epoch, id = record.id; ensure(id).notice = '停止请求正在提交，等待服务端确认。'
    try { const value = await researchApi.cancel(id, record.active_run.id); if (valid(ticket)) mergeResearch(value) } catch (error) { if (valid(ticket)) showError(error, id) }
  }
  async function participant(id: string, action: 'add' | 'exclude') {
    const record = current.value; if (!record) return
    const ticket = epoch; participantBusy.value = true
    try { const value = await researchApi.participant(record.id, record.participants_revision, id, action); if (!valid(ticket)) return; mergeResearch(value); ensure(record.id).notice = action === 'add' ? '已加入本研究；没有启动新分析。' : record.active_run?.status === 'running' ? '本轮已开始，该专家后续不再自动参与；本轮贡献保留。' : '后续不再自动选择该专家，明确重新加入可恢复。' }
    catch (error) { if (valid(ticket)) showError(error, record.id) } finally { if (valid(ticket)) participantBusy.value = false }
  }
  function prefill(text: string) {
    updateText('draft', appendWithoutOverwrite(local.value.draft.text, text))
    if (text.trim() === '查看全部课程') {
      local.value.scope.focus = 'all'
      local.value.notice = '已将下一轮范围设为全部课程，包含公共课程和分类未明确的课程；仅作课程代码对照，不作为专业相似度结论。点击发送后开始。'
    }
  }
  function direct(expert: ResearchExpert) { local.value.directed = expert.id; if (!local.value.draft.text.trim()) prefill(expert.question || `请从${expert.name}的角度分析这个问题。`); local.value.notice = current.value ? '已准备本次补充安排，点击发送后执行；原有问题文字未覆盖。' : '已选择本次分析专家，请确认范围和问题后发送。'; expertOpen.value = false }
  async function compare(planId: string) { if (busy.value) return; prefill('请比较这个专业，说明共同与不同的培养安排及当前可判断的范围。'); await submit({ ...local.value.scope, target_plan_id: planId }) }
  // Further operations are below; all requests retain their originating identity and research.
  async function rename(title: string) {
    const record = current.value; if (!record || !title.trim() || title.trim() === record.title) return
    const ticket = epoch
    try { const value = await researchApi.metadata(record.id, { revision: record.metadata_revision, title: title.trim() }); if (valid(ticket)) mergeResearch(value) }
    catch (error) { if (valid(ticket)) showError(error, record.id) }
  }
  async function archive() {
    const record = current.value; if (!record) return
    if (isRunning(record.active_run)) { local.value.error = '本轮仍在分析，请先点击停止，服务端确认后再归档。'; return }
    await flush(record.id)
    if (['error', 'conflict', 'saving', 'dirty'].some(status => [local.value.draft.state, local.value.opinion.state].includes(status as EditableText['state']))) { local.value.error = '还有暂未保存的文字，请先保存或处理版本差异后再归档。'; return }
    const ticket = epoch
    try { const value = await researchApi.metadata(record.id, { revision: record.metadata_revision, status: record.status === 'archived' ? 'active' : 'archived' }); if (valid(ticket)) { mergeResearch(value); local.value.notice = value.status === 'archived' ? '已归档，所有讨论和意见保留，可以恢复。' : '已恢复，可以继续研究。'; void refreshList() } }
    catch (error) { if (valid(ticket)) showError(error, record.id) }
  }
  async function openSources(value: ResearchResult) {
    const id = activeId.value, state = ensure(id), ticket = epoch
    if (id === 'new') return
    state.panel = 'sources'; state.sourceResult = value; state.sourceLoading = true; state.sourceError = ''
    try { const data = await researchApi.sources(id, value.id); if (valid(ticket) && state.sourceResult?.id === value.id) state.sources = data }
    catch (error) { if (valid(ticket) && state.sourceResult?.id === value.id) { state.sources = null; state.sourceError = error instanceof Error ? error.message : '资料暂未读取。'; if (error instanceof ResearchApiError && [401, 403].includes(error.status)) showError(error, id) } }
    finally { if (valid(ticket) && state.sourceResult?.id === value.id) state.sourceLoading = false }
  }
  function pinExcerpt(title: string, text: string) {
    if (!local.value.sourceResult) return
    local.value.excerpt = { title, text, resultId: local.value.sourceResult.id }; local.value.panel = 'opinion'
  }
  async function loadOpinionVersions() {
    const record = current.value, ticket = epoch; if (!record) return
    try { const data = await researchApi.opinionVersions(record.id); if (valid(ticket) && activeId.value === record.id) versions.value = data.items }
    catch (error) { if (valid(ticket)) showError(error, record.id) }
  }
  async function addQuestion(text: string, kind: 'data' | 'choice' = 'data') {
    const record = current.value, ticket = epoch; if (!record || !text.trim()) return
    try { await researchApi.question(record.id, text.trim(), kind); if (!valid(ticket)) return; const value = await researchApi.get(record.id); if (valid(ticket)) mergeResearch(value) }
    catch (error) { if (valid(ticket)) showError(error, record.id) }
  }
  async function changeQuestion(question: ResearchQuestion) {
    const record = current.value, ticket = epoch; if (!record) return
    try { await researchApi.updateQuestion(record.id, question, question.status === 'deferred' || question.status === 'resolved' ? 'open' : 'deferred'); if (!valid(ticket)) return; const value = await researchApi.get(record.id); if (valid(ticket)) mergeResearch(value) }
    catch (error) { if (valid(ticket)) showError(error, record.id) }
  }
  function beginMaterialPreparation() { includeOpinion.value = false }
  watch(() => [activeId.value, current.value?.context_epoch, current.value?.current_result?.id, local.value?.opinion.text], () => { includeOpinion.value = false }, { flush: 'sync' })
  async function prepareMaterial() {
    const record = current.value, ticket = epoch; if (!record?.current_result || record.current_result.status === 'reference') return
    if (record.current_result.method_unavailable) { local.value.error = '本轮使用的方法已停用，不能整理新材料；历史资料和已有材料仍可查看。'; return }
    const includeConfirmed = includeOpinion.value, confirmedText = local.value.opinion.text, confirmedResult = record.current_result.id
    if (includeConfirmed && (local.value.opinion.state !== 'saved' || local.value.opinion.inFlight)) {
      const saved = await saveField(record.id, 'opinion')
      if (!valid(ticket)) return
      if (!saved) { local.value.error = '请先保存个人意见并处理版本差异，再整理含意见的讨论稿。'; local.value.panel = 'opinion'; return }
    }
    if (activeId.value !== record.id || current.value?.current_result?.id !== confirmedResult || (includeConfirmed && local.value.opinion.text !== confirmedText)) { ensure(record.id).error = '分析范围或意见已更新，请重新打开整理材料并确认。'; includeOpinion.value = false; return }
    if (current.value.current_result.method_unavailable) { ensure(record.id).error = '本轮使用的方法已停用，请仅查看历史资料和已有材料。'; return }
    materialBusy.value = true; materialOpen.value = true; material.value = null
    try {
      const value = await researchApi.makeMaterial(record.id, { result_id: record.current_result.id, opinion_revision: ensure(record.id).opinion.base.revision, include_opinion: includeConfirmed && !!ensure(record.id).opinion.base.text.trim(), question_revisions: record.questions.map(q => ({ id: q.id, revision: q.revision })) })
      if (!valid(ticket) || activeId.value !== record.id) return
      material.value = value; const refreshed = await researchApi.get(record.id); if (valid(ticket)) mergeResearch(refreshed)
    } catch (error) {
      if (!valid(ticket)) return
      materialOpen.value = false; material.value = null
      if (error instanceof ResearchApiError && error.status === 409) {
        includeOpinion.value = false
        if (error.message.includes('result_conflict')) rejectedMaterialResults.set(record.id, confirmedResult)
        if (records[record.id]?.current_result?.id === confirmedResult) records[record.id].current_result = null
        ensure(record.id).error = '研究内容的版本已变化，正在重新读取。不会自动更换结果生成材料。'
        try {
          const refreshed = await researchApi.get(record.id)
          if (!valid(ticket)) return
          mergeResearch(refreshed)
          ensure(record.id).error = records[record.id]?.current_result ? '已重新读取当前研究。请重新确认分析范围和个人意见，再整理材料；本次没有自动换用新结果。' : '暂未取得一致的当前结果，旧指针已停止使用。请稍后重新打开研究，再确认范围和意见后整理；历史讨论与意见仍保留。'
        } catch (refreshError) {
          if (!valid(ticket)) return
          if (refreshError instanceof ResearchApiError && [401, 403].includes(refreshError.status)) showError(refreshError, record.id)
          else ensure(record.id).error = '研究版本已变化，但最新内容暂未读取。请稍后重新打开研究，再确认范围和意见后整理；历史讨论与意见仍保留。'
        }
      } else showError(error, record.id)
    }
    finally { if (valid(ticket)) materialBusy.value = false }
  }
  async function viewMaterial(id: string) {
    const ticket = epoch, researchId = activeId.value; materialOpen.value = true; materialBusy.value = true; material.value = null
    try { const value = await researchApi.material(id); if (valid(ticket) && activeId.value === researchId) material.value = value }
    catch (error) { if (valid(ticket)) { materialOpen.value = false; showError(error, researchId) } } finally { if (valid(ticket)) materialBusy.value = false }
  }
  async function openLegacy(id?: string) {
    const ticket = epoch; legacyOpen.value = true; legacyBusy.value = true; legacyPrepareError.value = ''
    try { if (id) { const value = await researchApi.legacyItem(id); if (valid(ticket)) legacyRecord.value = value } else { legacyRecord.value = null; const value = await researchApi.legacy(); if (valid(ticket)) legacyItems.value = value.items } }
    catch (error) { if (valid(ticket)) { legacyOpen.value = false; showError(error) } } finally { if (valid(ticket)) legacyBusy.value = false }
  }
  async function prepareLegacyResearch() {
    const legacy = legacyRecord.value, ticket = epoch
    legacyPrepareError.value = ''
    if (!legacy) return
    if (legacy.request?.student_id) { legacyPrepareError.value = '这份档案包含个体学生范围，当前只能只读查看，不能改成群体研究。'; showError(new Error(legacyPrepareError.value)); return }
    const scope = legacy.request, plans = catalog.value?.plans || []
    if (!scope?.plan_id || !plans.some(plan => plan.plan_id === scope.plan_id)) { legacyPrepareError.value = '原培养方案在当前授权目录中不可用，请新建研究后重新选择范围。'; showError(new Error(legacyPrepareError.value)); return }
    const targetAvailable = comparableResearchPlans(plans, scope.plan_id).some(plan => plan.plan_id === scope.target_plan_id)
    await openResearch('new')
    if (!valid(ticket) || activeId.value !== 'new') return
    local.value.scope = { plan_id: scope.plan_id, focus: scope.focus || 'all', ...(targetAvailable ? { target_plan_id: scope.target_plan_id } : {}), ...(scope.semester ? { semester: scope.semester } : {}), ...(scope.course_id ? { course_id: scope.course_id } : {}), ...(scope.scenario ? { scenario: scope.scenario } : {}), ...(scope.expert_id ? { expert_id: scope.expert_id } : {}) }
    const expert = catalog.value?.experts.find(item => item.id === scope.expert_id && item.enabled)
    local.value.directed = expert?.id || ''
    prefill([...legacy.messages].reverse().find(message => message.role === 'user')?.text || legacy.title)
    local.value.notice = '已准备原问题与当前可用范围，已有草稿仍保留。发送后重新读取当前资料；旧档案与原个人意见不会改动。' + (scope.target_plan_id && !targetAvailable ? '原比较方案目前不可用，已留空，请明确比较对象。' : '')
    legacyOpen.value = false
  }
  async function poll() {
    if (pollBusy || loading.value || disposed) return
    pollBusy = true; const ticket = epoch
    const ids = [...new Set([...(activeId.value === 'new' ? [] : [activeId.value]), ...Object.values(records).filter(r => isRunning(r.active_run)).map(r => r.id)])]
    try { await Promise.all(ids.map(async id => { try { const value = await researchApi.get(id); if (valid(ticket)) mergeResearch(value) } catch (error) { if (valid(ticket)) showError(error, id) } })) }
    finally { if (valid(ticket)) pollBusy = false }
  }
  async function loadEarlier(before?: number) {
    const record = current.value, ticket = epoch; if (!record || (!before && !record.next_before) || olderBusy.value) return
    const sequential = before == null || before === record.next_before, historyCursor = record.next_before
    olderBusy.value = true
    try { const value = await researchApi.get(record.id, before ?? record.next_before!); if (!valid(ticket)) return; expandedHistory.add(record.id); record.next_before = sequential ? value.next_before : historyCursor; mergeResearch(value) }
    catch (error) { if (valid(ticket)) showError(error, record.id) } finally { if (valid(ticket)) olderBusy.value = false }
  }
  async function initialize() {
    const ticket = epoch; loading.value = true; bootstrapError.value = ''
    try {
      const [value, draft] = await Promise.all([researchApi.catalog(), researchApi.text('new', 'draft')])
      if (!valid(ticket)) return
      catalog.value = value; mergeText(ensure('new').draft, draft); await refreshList()
    } catch (error) { if (valid(ticket)) bootstrapError.value = error instanceof Error ? error.message : '研究工作区暂未加载，请重试。' }
    finally { if (valid(ticket)) loading.value = false }
  }
  function beforeLeave(event: BeforeUnloadEvent) {
    if (Object.values(locals).some(item => [item.draft, item.opinion].some(text => text.text !== text.base.text || text.inFlight))) { event.preventDefault(); event.returnValue = '' }
  }
  let searchTimer: ReturnType<typeof setTimeout> | undefined
  watch(query, () => { if (searchTimer) clearTimeout(searchTimer); searchTimer = setTimeout(() => void refreshList(), 350) })
  watch(archived, () => void refreshList())
  watch(() => [authStore.user?.username, authStore.user?.activeIdentityId, authStore.user?.permissionContext?.scopeFingerprint].join('|'), () => {
    epoch++; selectionTicket++; listTicket++; saveTimers.forEach(clearTimeout); saveTimers.clear(); Object.keys(records).forEach(id => delete records[id]); Object.keys(locals).forEach(id => delete locals[id]); locals.new = emptyLocal()
    activeId.value = 'new'; catalog.value = null; summaries.value = []; material.value = null; materialOpen.value = false; legacyOpen.value = false; legacyRecord.value = null; legacyItems.value = []; expertOpen.value = false; participantBusy.value = false; pollBusy = false; versions.value = []; loadingResearch.value = false; expandedHistory.clear(); rejectedMaterialResults.clear(); olderBusy.value = false
    void initialize()
  })
  onMounted(() => { void initialize(); pollTimer = setInterval(() => void poll(), 3500); window.addEventListener('beforeunload', beforeLeave) })
  onBeforeUnmount(() => { void flush(); disposed = true; epoch++; if (pollTimer) clearInterval(pollTimer); if (searchTimer) clearTimeout(searchTimer); saveTimers.forEach(clearTimeout); window.removeEventListener('beforeunload', beforeLeave) })
  return { catalog, summaries, cursor, activeId, records, locals, current, local, result, busy, loading, loadingResearch, loadingList, bootstrapError, query, archived, sidebarOpen, expertOpen, participantBusy, materialOpen, materialBusy, material, includeOpinion, legacyOpen, legacyItems, legacyRecord, legacyBusy, legacyPrepareError, versions, identityLabel, olderBusy, loadEarlier,
    initialize, refreshList, openResearch, startNewResearch, openSearchResult, updateText, saveField, resolveConflict, flush, submit, cancel, participant, prefill, direct, compare, rename, archive, openSources, pinExcerpt, loadOpinionVersions, addQuestion, changeQuestion, beginMaterialPreparation, prepareMaterial, viewMaterial, openLegacy, prepareLegacyResearch, showError }
}
