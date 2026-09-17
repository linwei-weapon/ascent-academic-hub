import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import * as vue from 'vue'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = relative => fs.readFileSync(path.join(base, relative), 'utf8')
let passed = 0
async function test(name, callback) { await callback(); passed++; process.stdout.write(`PASS ${name}\n`) }
function loadTs(relative, mocks = {}, extra = {}) {
  const code = ts.transpileModule(read(relative), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(`(function(require,module,exports){${code}\n})`, { console, setTimeout, clearTimeout, setInterval, clearInterval, URL, Blob, crypto: globalThis.crypto, ...extra })(name => name in mocks ? mocks[name] : require(name), module, module.exports)
  return module.exports
}

const researchClient = loadTs('src/api/aiDecision/expertResearch.ts', { '@/utils/http': { getToken: () => 'token', getActiveIdentity: () => 'identity' } }, { fetch: async () => { throw new Error('Unexpected request') } })
const utils = loadTs('src/utils/expertResearch.ts', { '@/api/aiDecision/expertResearch': researchClient })
await test('Chinese research dates are Shanghai-local and never raw ISO', () => {
  const value = utils.researchDate('2026-09-16T00:00:00+00:00')
  assert.ok(value.includes('2026') && value.includes('08:00') && !value.includes('T00'))
  assert.equal(utils.researchDate(), '时间未提供')
})
await test('Business result presents critical issues and scope receipt before tables', () => {
  const code = read('src/views/ai-decision/expert-team/ResearchResult.vue')
  assert.ok(code.indexOf('critical-issues') < code.indexOf('result-table'))
  assert.ok(code.includes('result.request_receipt') && code.includes('point.source'))
  assert.ok(code.includes('selected_shared'))
})
await test('Frozen memo body precedes collapsible detail appendix', () => {
  const code = read('src/views/ai-decision/expert-team/MaterialPreview.vue')
  assert.ok(code.indexOf('discussion_memo.sections') < code.indexOf('memo-appendix'))
  assert.ok(code.includes('v-else class="paper"'))
})
await test('Long research titles are clamped without truncating original turn messages', () => {
  const code = read('src/views/ai-decision/expert-team/index.vue')
  assert.ok(code.includes('.research-header h1,.current-scope{display:-webkit-box;-webkit-line-clamp:2'))
  assert.ok(code.includes('{{ turn.message }}'))
})
await test('Archived materials have a stable discussion label without a missing API title', () => {
  const code = read('src/views/ai-decision/expert-team/index.vue')
  assert.ok(code.includes('讨论稿 {{ current.materials.length - index }}'))
  assert.ok(code.includes('researchDate(item.created_at)'))
})
await test('Ctrl+Enter sends, plain Enter and IME never send', () => {
  const event = { key: 'Enter', ctrlKey: true, isComposing: false, keyCode: 13 }
  assert.equal(utils.shouldSendKey(event, false), true)
  assert.equal(utils.shouldSendKey({ ...event, ctrlKey: false }, false), false)
  assert.equal(utils.shouldSendKey({ ...event, isComposing: true }, false), false)
  assert.equal(utils.shouldSendKey({ ...event, keyCode: 229 }, false), false)
  assert.equal(utils.shouldSendKey(event, true), false)
})
await test('Acknowledgement does not erase text typed after submit', () => {
  assert.equal(utils.clearAcceptedText('原问题', '原问题'), '')
  assert.equal(utils.clearAcceptedText('已经开始写下一轮', '原问题'), '已经开始写下一轮')
  assert.equal(utils.appendWithoutOverwrite('原有文字', '补充问题'), '原有文字\n补充问题')
})
await test('Running and terminal states remain distinct', () => {
  for (const status of ['queued', 'running', 'cancel_requested']) assert.equal(utils.isRunning({ id: 'r', status }), true)
  for (const status of ['completed', 'failed', 'cancelled', 'timed_out']) assert.equal(utils.isRunning({ id: 'r', status }), false)
  assert.equal(utils.runLabel('cancel_requested'), '正在停止')
})
await test('Plan labels always identify the explicit cohort without duplication', () => {
  assert.equal(utils.researchPlanLabel({ plan_name: '航海技术培养方案', grade: 2022 }), '航海技术培养方案 · 2022级')
  assert.equal(utils.researchPlanLabel({ plan_name: '2022级航海技术培养方案', grade: 2022 }), '2022级航海技术培养方案')
  assert.equal(utils.researchPlanLabel(undefined), '')
})
await test('Manual comparison excludes missing, different-type and different-cohort plans', () => {
  const plans = [{ plan_id: 'source', grade: 2022, training_type: '普通本科' }, { plan_id: 'same', grade: 2022, training_type: '普通本科' }, { plan_id: 'preparatory', grade: 2022, training_type: '预科' }, { plan_id: 'unknown', grade: 2022 }, { plan_id: 'different-year', grade: 2023, training_type: '普通本科' }]
  assert.deepEqual(Array.from(utils.comparableResearchPlans(plans, 'source'), plan => plan.plan_id), ['same'])
  assert.equal(utils.comparableResearchPlans(plans, 'unknown').length, 0)
})

const text = (value = '', revision = 0) => ({ text: value, revision, saved_at: '2026-09-16T09:00:00' })
const record = (id, extra = {}) => ({ id, title: `研究${id}`, status: 'active', updated_at: '2026-09-16T09:00:00', metadata_revision: 1, context_epoch: 1, scope: { plan_id: 'plan-2022', focus: 'non_common' }, participants_revision: 1, participants: [], draft: text(), opinion: text(), turns: [], active_run: null, current_result: null, questions: [], materials: [], ...extra })
const clone = value => JSON.parse(JSON.stringify(value))
const store = { A: record('A'), B: record('B') }
let newDraft = text(), saveConflict = false, pendingCreate, pendingTurn, holdTurn = false, saveCalls = [], getCalls = [], turnCalls = [], materialCalls = []
const earlierPages = new Map()
const api = {
  catalog: async () => ({ version: 'v3', mode: 'structured', notice: '已接入范围', role_view: 'director', experts: [], plans: [], semesters: [] }),
  list: async () => ({ items: Object.values(store).map(clone) }),
  get: async (id, before) => { getCalls.push({ id, before }); return clone(earlierPages.get(`${id}:${before}`) || store[id]) },
  text: async (id, field) => clone(id === 'new' ? newDraft : store[id][field]),
  saveText: async (id, field, body) => { saveCalls.push({ id, field, ...body }); if (saveConflict) throw new utils.ResearchApiError('其他窗口已更新', 409); const value = text(body.text, body.revision + 1); if (id === 'new') newDraft = value; else store[id][field] = value; return clone(value) },
  create: body => new Promise(resolve => { pendingCreate = () => { store.C = record('C', { active_run: { id: 'run-C', status: 'queued' }, turns: [{ id: 'turn-C', message: body.message, created_at: '2026-09-16T09:00:00', run: { id: 'run-C', status: 'queued' } }] }); resolve(clone(store.C)) } }),
  turn: async (id, body) => { turnCalls.push({ id, ...clone(body) }); const seq = Math.max(0, ...store[id].turns.map(turn => turn.seq || 0)) + 1; store[id].scope = clone(body.scope); store[id].active_run = { id: `run-${id}-${seq}`, status: 'queued' }; store[id].turns.push({ id: `turn-${id}-${seq}`, seq, message: body.message, created_at: '2026-09-16T09:00:00', run: clone(store[id].active_run) }); const snapshot = clone(store[id]); if (holdTurn) return new Promise(resolve => { pendingTurn = () => resolve(snapshot) }); return snapshot },
  cancel: async id => { store[id].active_run = { id: `run-${id}`, status: 'cancel_requested' }; return clone(store[id]) },
  makeMaterial: async (id, body) => { materialCalls.push({ id, ...clone(body) }); return { id: 'material-test', research_id: id, title: '讨论材料', result_id: body.result_id, opinion_revision: body.opinion_revision, snapshot: { result: clone(store[id].current_result), opinion: body.include_opinion ? clone(store[id].opinion) : text(), questions: [] }, stale: false } },
}
const authStore = vue.reactive({ user: { username: 'leader', activeIdentityId: 'identity', roleName: '教务处处长', permissionContext: { scopeFingerprint: 'all' } } })
const timerCallbacks = new Map(); let nextTimer = 1
const fakeVue = { ...vue, onMounted: () => {}, onBeforeUnmount: () => {} }
const snapshots = loadTs('src/views/ai-decision/expert-team/researchSnapshot.ts')
const readingBehavior = loadTs('src/views/ai-decision/expert-team/researchReading.ts')
const layout = loadTs('src/views/ai-decision/expert-team/researchLayout.ts')
await test('Short workspace height uses its actual top at 125 percent zoom and keeps send space reserved', () => {
  assert.equal(layout.availableResearchHeight(576, 54.4), 505)
  assert.equal(layout.availableResearchHeight(620, 86), 518)
  assert.equal(layout.availableResearchHeight(576, 600), 0)
  const code = read('src/views/ai-decision/expert-team/index.vue')
  assert.match(code, /--available-workspace-height': availableWorkspaceHeight/)
  assert.match(code, /\.reading-scroll\{flex:1 1 150px;min-height:100px/)
  assert.match(code, /\.research-composer\{flex:0 1 auto;min-height:158px;max-height:224px/)
  assert.match(code, /\.composer-bottom\{flex:0 0 auto;min-height:34px\}/)
  assert.match(code, /removeEventListener\('resize', measureWorkspace\)/)
})
await test('Result arrival follows the first or waiting-at-end discussion within its reader only', () => {
  const previous = { researchId: 'A', turnId: 'turn-1', resultId: '' }, arrived = { ...previous, resultId: 'result-1' }
  assert.equal(readingBehavior.shouldFollowResult(previous, arrived, { loading: false, firstRound: true, wasAtEnd: false, userInteracted: false }), true)
  assert.equal(readingBehavior.shouldFollowResult(previous, arrived, { loading: false, firstRound: false, wasAtEnd: true, userInteracted: true }), true)
  const target = { getBoundingClientRect: () => ({ top: 520 }) }, reader = { scrollTop: 80, contains: node => node === target, getBoundingClientRect: () => ({ top: 200 }) }
  assert.equal(readingBehavior.positionConclusion(reader, target), true); assert.equal(reader.scrollTop, 390)
  assert.doesNotMatch(read('src/views/ai-decision/expert-team/researchReading.ts'), /scrollIntoView|window\.scroll/)
})
await test('Result arrival does not move a user reading history or reopening an existing research', () => {
  const previous = { researchId: 'A', turnId: 'turn-2', resultId: '' }, arrived = { ...previous, resultId: 'result-2' }
  const state = { loading: false, firstRound: false, wasAtEnd: false, userInteracted: true }
  assert.equal(readingBehavior.shouldFollowResult(previous, arrived, state), false)
  assert.equal(readingBehavior.shouldFollowResult(previous, arrived, { ...state, firstRound: true }), false)
  assert.equal(readingBehavior.shouldFollowResult(previous, { ...arrived, researchId: 'B' }, { ...state, wasAtEnd: true }), false)
  assert.equal(readingBehavior.shouldFollowResult(arrived, arrived, { ...state, wasAtEnd: true }), false)
})
const controller = loadTs('src/views/ai-decision/expert-team/useResearchWorkspace.ts', { vue: fakeVue, '@/store/auth': { authStore }, '@/utils/expertResearch': utils, '@/api/aiDecision/expertResearch': { ...researchClient, researchApi: api }, './researchSnapshot': snapshots }, { setTimeout: callback => { const id = nextTimer++; timerCallbacks.set(id, callback); return id }, clearTimeout: id => timerCallbacks.delete(id), window: { addEventListener() {}, removeEventListener() {} } })
const scope = vue.effectScope()
const workspace = scope.run(() => controller.useResearchWorkspace())
await workspace.initialize()
await test('New research starts from known non-public courses rather than the public elective pool', () => {
  assert.equal(workspace.local.value.scope.focus, 'non_common'); assert.equal(workspace.local.value.scope.plan_id, '')
})
await test('Opening a saved research restores explicit plan scope', async () => {
  await workspace.openResearch('A'); assert.equal(workspace.local.value.scope.plan_id, 'plan-2022')
})
await test('Draft and opinion use independent revision requests', async () => {
  workspace.updateText('draft', '下轮问题'); await workspace.saveField('A', 'draft')
  workspace.updateText('opinion', '领导自己的意见'); await workspace.saveField('A', 'opinion')
  const draft = saveCalls.find(call => call.field === 'draft' && call.id === 'A'), opinion = saveCalls.find(call => call.field === 'opinion')
  assert.equal(draft.revision, 0); assert.equal(opinion.revision, 0); assert.notEqual(draft.client_request_id, opinion.client_request_id)
  assert.equal(workspace.local.value.opinion.text, '领导自己的意见')
})
await test('409 keeps local and remote versions, then explicit save resolves', async () => {
  workspace.updateText('opinion', '我的新想法'); store.A.opinion = text('另一窗口的意见', 4); saveConflict = true
  await workspace.saveField('A', 'opinion')
  assert.equal(workspace.local.value.opinion.text, '我的新想法'); assert.equal(workspace.local.value.opinion.conflict.text, '另一窗口的意见')
  saveConflict = false; await workspace.resolveConflict('opinion', false)
  assert.equal(store.A.opinion.text, '我的新想法'); assert.equal(store.A.opinion.revision, 5)
})
await test('Unclear plan does not create a request', async () => {
  await workspace.openResearch('new'); workspace.updateText('draft', '研究本届问题'); await workspace.submit()
  assert.match(workspace.local.value.error, /培养方案/); assert.equal(pendingCreate, undefined)
})
await test('Late new-research response cannot steal focus or erase new typing', async () => {
  workspace.local.value.scope.plan_id = 'plan-2022'; workspace.updateText('draft', '原问题')
  const submitted = workspace.submit(); workspace.updateText('draft', '下一条尚未发送的问题'); await workspace.openResearch('B'); pendingCreate(); await submitted
  assert.equal(workspace.activeId.value, 'B'); assert.equal(workspace.locals.C.draft.text, '下一条尚未发送的问题'); assert.equal(workspace.records.C.active_run.status, 'queued')
})
await test('Stop shows server adjudication, not fake local completion', async () => {
  await workspace.openResearch('C'); await workspace.cancel(); assert.equal(workspace.current.value.active_run.status, 'cancel_requested'); assert.equal(workspace.busy.value, true)
})
await test('Overlong input is preserved and not submitted', async () => {
  await workspace.openResearch('B'); const long = '文'.repeat(4001); workspace.updateText('draft', long); await workspace.submit(); assert.equal(workspace.local.value.draft.text.length, 4001); assert.match(workspace.local.value.error, /4000/)
})
await test('All-course action prepares explicit scope and retains text until user sends', async () => {
  await workspace.openResearch('A'); workspace.updateText('draft', '我已有的补充'); const previousCalls = turnCalls.length
  workspace.prefill('查看全部课程')
  assert.equal(workspace.local.value.scope.focus, 'all'); assert.equal(workspace.local.value.draft.text, '我已有的补充\n查看全部课程')
  assert.equal(turnCalls.length, previousCalls); assert.match(workspace.local.value.notice, /不作为专业相似度/)
  await workspace.submit(); assert.equal(turnCalls.at(-1).scope.focus, 'all')
  store.A.active_run = null
})
await test('Search opens the matched historical page and preserves the match metadata', async () => {
  const latest = { id: 'latest-A', seq: 21, message: '最近的问题', created_at: '2026-09-16T10:00:00', run: { id: 'last', status: 'completed' } }
  const earlier = { id: 'earlier-A', seq: 2, message: '专业共同课程问题', created_at: '2026-09-16T09:00:00', run: { id: 'old', status: 'completed' } }
  store.A.turns = [latest]; store.A.next_before = 20
  earlierPages.set('A:3', record('A', { turns: [earlier], next_before: null, draft: store.A.draft, opinion: store.A.opinion }))
  workspace.query.value = '共同课程'
  const item = { ...store.A, matched_turn_id: 'earlier-A', match_seq: 2, snippet: '专业共同课程问题' }
  workspace.summaries.value = [item]
  assert.equal(await workspace.openSearchResult(item), 'earlier-A')
  assert.ok(getCalls.some(call => call.id === 'A' && call.before === 3)); assert.ok(workspace.current.value.turns.some(turn => turn.id === 'latest-A'))
  assert.equal(workspace.current.value.next_before, 20, 'Jumping to a match must not skip the intervening unread history')
  assert.equal(workspace.summaries.value[0].match_seq, 2); assert.equal(workspace.summaries.value[0].snippet, item.snippet)
  workspace.query.value = ''
})
await test('Completed reference turn leaves the valid current analysis unchanged', async () => {
  const previous = { id: 'valid-A', status: 'completed', headline: '原有有效判断' }
  store.A.current_result = previous
  store.A.turns.push({ id: 'reference-A', message: '解释计算口径', created_at: '2026-09-16T11:00:00', run: { id: 'reference-run', status: 'completed' }, result: { id: 'reference-result', status: 'reference', headline: '已有分析说明' } })
  await workspace.openResearch('A')
  assert.equal(workspace.result.value.id, 'valid-A'); assert.equal(workspace.current.value.turns.find(turn => turn.id === 'reference-A').result.status, 'reference')
  store.A.current_result = { id: 'invalid-reference-pointer', status: 'reference' }; await workspace.openResearch('A')
  assert.equal(workspace.result.value.id, 'valid-A')
})
const completedTurn = (seq, status = 'completed') => ({ id: `snapshot-turn-${seq}`, seq, message: `第${seq}轮`, created_at: `2026-09-16T10:0${seq}:00`, run: { id: `snapshot-run-${seq}`, status, created_at: `2026-09-16T10:0${seq}:00`, lease_generation: status === 'completed' ? 2 : 1 }, ...(status === 'completed' ? { result: { id: `snapshot-result-${seq}`, status: 'completed', created_at: `2026-09-16T10:0${seq}:30`, headline: `第${seq}轮判断` } } : {}) })
await test('Same-context stale GET cannot regress result, terminal run or independent revisions', async () => {
  const first = completedTurn(1), second = completedTurn(2)
  const stale = record('R', { turns: [first, completedTurn(2, 'queued')], current_result: first.result, active_run: completedTurn(2, 'queued').run, metadata_revision: 1, participants_revision: 1, opinion: text('旧意见', 1) })
  const fresh = record('R', { turns: [first, second], current_result: second.result, active_run: null, title: '新名称', metadata_revision: 3, participants_revision: 3, opinion: text('新意见', 3) })
  const originalGet = api.get; let resolveStale
  api.get = async id => id === 'R' ? new Promise(resolve => { resolveStale = () => resolve(clone(stale)) }) : originalGet(id)
  const pending = workspace.openResearch('R'); api.get = originalGet; store.R = fresh; await workspace.openResearch('R'); resolveStale(); await pending
  assert.equal(workspace.result.value.id, second.result.id); assert.equal(workspace.current.value.active_run, null); assert.equal(workspace.current.value.turns.at(-1).run.status, 'completed')
  assert.equal(workspace.current.value.title, '新名称'); assert.equal(workspace.current.value.metadata_revision, 3); assert.equal(workspace.current.value.opinion.revision, 3); assert.equal(workspace.local.value.opinion.text, '新意见')
})
await test('Late queued submission response cannot replace its completed publication', async () => {
  const first = completedTurn(1); store.T = record('T', { turns: [first], current_result: first.result }); await workspace.openResearch('T')
  workspace.updateText('draft', '继续第二轮'); holdTurn = true; const pending = workspace.submit()
  const turn = store.T.turns.at(-1); turn.run.status = 'completed'; turn.run.lease_generation = 2; turn.result = { id: 'published-second', status: 'completed', created_at: '2026-09-16T11:00:00', headline: '第二轮有效结论' }; store.T.current_result = turn.result; store.T.active_run = null; store.T.updated_at = '2026-09-16T11:00:00'
  await workspace.openResearch('T'); pendingTurn(); await pending; holdTurn = false
  assert.equal(workspace.result.value.id, 'published-second'); assert.equal(workspace.current.value.active_run, null); assert.equal(workspace.current.value.turns.at(-1).run.status, 'completed')
})
await test('Older history pages add turns without replacing the current live state', () => {
  const last = completedTurn(8), old = completedTurn(1), running = completedTurn(9, 'running')
  const current = record('P', { turns: [last, running], current_result: last.result, active_run: running.run, next_before: 8, opinion: text('最新意见', 5), metadata_revision: 4, questions: [{ id: 'q', revision: 3, text: '新事项', status: 'deferred' }], materials: [{ id: 'material-1' }] })
  const page = record('P', { turns: [old], current_result: old.result, next_before: null, opinion: text('旧意见', 1), questions: [{ id: 'q', revision: 1, text: '旧事项', status: 'open' }] })
  const merged = snapshots.mergeResearchSnapshot(current, page, true)
  assert.equal(merged.turns.length, 3); assert.equal(merged.current_result.id, last.result.id); assert.equal(merged.active_run.id, running.run.id); assert.equal(merged.next_before, 8)
  assert.equal(merged.opinion.revision, 5); assert.equal(merged.questions[0].revision, 3); assert.equal(merged.materials.length, 1)
})
await test('A genuine retry run can progress beyond a previous terminal attempt', () => {
  const first = completedTurn(1); first.run.status = 'failed'; delete first.result
  const retried = clone(first); retried.run = { id: 'retry', status: 'queued', retry_of: first.run.id, created_at: '2026-09-16T12:00:00' }
  const merged = snapshots.mergeResearchSnapshot(record('retry', { turns: [first] }), record('retry', { turns: [retried], active_run: retried.run }))
  assert.equal(merged.turns[0].run.id, 'retry'); assert.equal(merged.active_run.id, 'retry')
})
await test('Material opinion inclusion resets every opening and after scope or opinion changes', async () => {
  store.M = record('M', { opinion: text('针对A范围的个人意见', 1), current_result: { id: 'scope-a', status: 'completed' } }); await workspace.openResearch('M')
  workspace.beginMaterialPreparation(); assert.equal(workspace.includeOpinion.value, false); workspace.includeOpinion.value = true; workspace.beginMaterialPreparation(); assert.equal(workspace.includeOpinion.value, false)
  workspace.includeOpinion.value = true; store.M.context_epoch = 2; store.M.scope = { plan_id: 'scope-b', focus: 'all' }; store.M.current_result = { id: 'scope-b', status: 'completed' }; await workspace.openResearch('M')
  assert.equal(workspace.includeOpinion.value, false); assert.equal(workspace.local.value.opinion.text, '针对A范围的个人意见')
  await workspace.prepareMaterial(); assert.equal(materialCalls.at(-1).include_opinion, false)
  workspace.beginMaterialPreparation(); workspace.includeOpinion.value = true; await workspace.prepareMaterial(); assert.equal(materialCalls.at(-1).include_opinion, true)
  workspace.includeOpinion.value = true; workspace.updateText('opinion', '修改后的意见'); assert.equal(workspace.includeOpinion.value, false)
})
await test('Late save acknowledgement preserves a newer remote revision and visible conflict', async () => {
  store.S = record('S', { opinion: text('原意见', 1) }); await workspace.openResearch('S'); workspace.updateText('opinion', '我的保存内容')
  const originalSave = api.saveText; let resolveSave
  api.saveText = async () => new Promise(resolve => { resolveSave = () => resolve(text('我的保存内容', 2)) })
  const saving = workspace.saveField('S', 'opinion')
  store.S.opinion = text('其他窗口已保存的新版本', 3); await workspace.openResearch('S')
  resolveSave(); await saving; api.saveText = originalSave
  assert.equal(workspace.current.value.opinion.revision, 3); assert.equal(workspace.local.value.opinion.conflict.revision, 3); assert.equal(workspace.local.value.opinion.state, 'conflict'); assert.equal(workspace.local.value.opinion.text, '我的保存内容')
})
await test('Retired methods disable new material actions without removing historical access', async () => {
  store.F = record('F', { current_result: { id: 'retired', status: 'completed', method_unavailable: true }, materials: [{ id: 'old-material', title: '原讨论材料' }] }); await workspace.openResearch('F')
  const callsBefore = materialCalls.length; await workspace.prepareMaterial()
  assert.equal(materialCalls.length, callsBefore); assert.match(workspace.local.value.error, /方法已停用/); assert.equal(workspace.current.value.materials[0].id, 'old-material')
  const code = read('src/views/ai-decision/expert-team/index.vue')
  assert.match(code, /:disabled="!!result\.method_unavailable"/); assert.match(code, /:disabled="!!result\?\.method_unavailable"/); assert.match(code, /查看已有材料/)
})
await test('Material 409 refreshes the current result and requires fresh confirmation without retrying', async () => {
  store.CF = record('CF', { current_result: { id: 'before-conflict', status: 'completed' }, opinion: text('保留个人意见', 1) }); await workspace.openResearch('CF')
  const makeBefore = api.makeMaterial; let attempts = 0
  api.makeMaterial = async () => { attempts++; store.CF.current_result = { id: 'after-conflict', status: 'completed' }; throw new utils.ResearchApiError('result_conflict：当前结果已变化', 409) }
  workspace.includeOpinion.value = true; await workspace.prepareMaterial(); api.makeMaterial = makeBefore
  assert.equal(attempts, 1); assert.equal(workspace.result.value.id, 'after-conflict'); assert.equal(workspace.includeOpinion.value, false); assert.equal(workspace.materialOpen.value, false); assert.equal(workspace.material.value, null)
  assert.match(workspace.local.value.error, /重新确认分析范围和个人意见/); assert.equal(workspace.local.value.opinion.text, '保留个人意见')
})
await test('A repeated mixed snapshot cannot restore the result pointer rejected by material 409', async () => {
  store.MX = record('MX', { current_result: { id: 'mixed-old', status: 'completed' }, turns: [completedTurn(2)] }); await workspace.openResearch('MX')
  const makeBefore = api.makeMaterial; api.makeMaterial = async () => { throw new utils.ResearchApiError('result_conflict：当前结果已变化', 409) }
  await workspace.prepareMaterial(); api.makeMaterial = makeBefore
  assert.equal(workspace.result.value, null); assert.match(workspace.local.value.error, /旧指针已停止使用/); assert.equal(workspace.current.value.turns.length, 1)
  store.MX.current_result = completedTurn(2).result; await workspace.openResearch('MX'); assert.equal(workspace.result.value.id, completedTurn(2).result.id)
})
await test('Published automatic target and focus carry into an ordinary follow-up', async () => {
  store.D = record('D'); await workspace.openResearch('D')
  store.D.scope = { plan_id: 'plan-2022', target_plan_id: 'closest-2022', focus: 'all' }; store.D.context_epoch = 2
  store.D.current_result = { id: 'automatic-target', status: 'completed', headline: '自动选择可比专业后的有效判断' }
  await workspace.openResearch('D'); workspace.updateText('draft', '解释计算口径'); await workspace.submit()
  assert.equal(turnCalls.at(-1).scope.target_plan_id, 'closest-2022'); assert.equal(turnCalls.at(-1).scope.focus, 'all'); assert.equal(turnCalls.at(-1).expected_context_epoch, 2)
  assert.equal(workspace.result.value.id, 'automatic-target')
  store.D.active_run = null
})
await test('Scope prepared after sending survives both acknowledgement and publication', async () => {
  await workspace.openResearch('D'); workspace.updateText('draft', '继续分析当前两专业'); holdTurn = true
  const submitted = workspace.submit()
  workspace.local.value.scope.focus = 'practice'; workspace.local.value.scope.target_plan_id = 'my-next-target'
  pendingTurn(); await submitted; holdTurn = false
  assert.equal(workspace.local.value.scope.focus, 'practice'); assert.equal(workspace.local.value.scope.target_plan_id, 'my-next-target')
  store.D.scope = { ...store.D.scope, focus: 'main', target_plan_id: 'server-current-target' }; store.D.context_epoch = 3; store.D.active_run = null
  await workspace.openResearch('D')
  assert.equal(workspace.local.value.scope.focus, 'practice'); assert.equal(workspace.local.value.scope.target_plan_id, 'my-next-target'); assert.equal(workspace.local.value.scopeBase.target_plan_id, 'server-current-target')
})
await test('Legacy research prepares a fresh draft without sending or copying personal opinion', async () => {
  workspace.catalog.value.plans = [{ plan_id: 'plan-2022', grade: 2022, training_type: '普通本科' }, { plan_id: 'target-2022', grade: 2022, training_type: '普通本科' }]
  workspace.catalog.value.experts = [{ id: 'program', enabled: true }]
  await workspace.openResearch('new'); workspace.updateText('draft', '已经在写的新研究'); const opinionBefore = workspace.local.value.opinion.text, previousCalls = turnCalls.length
  workspace.legacyRecord.value = { id: 'old', title: '原研究', request: { plan_id: 'plan-2022', target_plan_id: 'target-2022', focus: 'all', expert_id: 'program', scenario: 'similarity' }, messages: [{ role: 'user', text: '原来两个专业的共同课程有哪些？' }], note: '原个人意见，不要复制', result: { tables: [], documents: [] } }
  const legacyBefore = JSON.stringify(workspace.legacyRecord.value)
  await workspace.prepareLegacyResearch()
  assert.equal(workspace.activeId.value, 'new'); assert.equal(workspace.local.value.draft.text, '已经在写的新研究\n原来两个专业的共同课程有哪些？'); assert.equal(workspace.local.value.scope.target_plan_id, 'target-2022'); assert.equal(workspace.local.value.directed, 'program')
  assert.equal(workspace.local.value.opinion.text, opinionBefore); assert.equal(turnCalls.length, previousCalls); assert.equal(JSON.stringify(workspace.legacyRecord.value), legacyBefore); assert.match(workspace.local.value.notice, /重新读取当前资料/)
})
await test('Individual-student legacy records cannot silently become group research', async () => {
  workspace.legacyRecord.value.request.student_id = 'individual-record'; const original = workspace.local.value.draft.text
  await workspace.prepareLegacyResearch(); assert.equal(workspace.local.value.draft.text, original); assert.match(workspace.local.value.error, /个体学生范围/)
})
await test('Identity change removes old research and opinion cache', async () => {
  authStore.user.activeIdentityId = 'other-identity'; await vue.nextTick(); await Promise.resolve(); assert.equal(workspace.activeId.value, 'new'); assert.equal(workspace.records.A, undefined); assert.equal(workspace.locals.A, undefined)
})
await test('New research preserves an unsent draft until explicitly cleared', async () => {
  await workspace.openResearch('new'); workspace.updateText('draft', '尚未发送的管理问题')
  workspace.local.value.scope = { plan_id: 'old-plan', target_plan_id: 'old-target', focus: 'main' }
  assert.equal(await workspace.startNewResearch(), 'draft')
  assert.equal(workspace.local.value.draft.text, '尚未发送的管理问题')
  assert.equal(workspace.local.value.scope.plan_id, 'old-plan')
  assert.equal(await workspace.startNewResearch(true), 'ready')
  assert.equal(workspace.local.value.draft.text, '')
  assert.equal(workspace.local.value.scope.plan_id, '')
  assert.equal(workspace.local.value.scope.target_plan_id, undefined)
  assert.match(workspace.local.value.notice, /已开始一项新研究/)
})
await test('New research does not abandon an uncertain submit or conflicting draft', async () => {
  workspace.local.value.pendingSubmit = { message: '提交中', scope: { plan_id: 'p' }, client_request_id: 'pending' }
  assert.equal(await workspace.startNewResearch(true), 'pending')
  assert.equal(workspace.local.value.pendingSubmit.client_request_id, 'pending')
  workspace.local.value.pendingSubmit = null
  workspace.local.value.draft.conflict = text('其他窗口', 88)
  assert.equal(await workspace.startNewResearch(true), 'conflict')
  assert.equal(workspace.local.value.draft.conflict.text, '其他窗口')
  workspace.local.value.draft.conflict = null
})
await test('Expert cards keep details accessible and separate prepare from execute', () => {
  const code = read('src/views/ai-decision/expert-team/ExpertPicker.vue')
  assert.match(code, /class="expert-card"/); assert.match(code, /<ExpertAvatar/)
  assert.match(code, /:aria-label="expert.name \+ '，查看详情'"/)
  assert.match(code, /scenario.release === 'deferred'/)
  assert.match(code, /选择后返回讨论区，可修改问题并发送/)
  assert.match(code, /选择这位专家/)
  assert.doesNotMatch(code, /researchApi|submit\(/)
  assert.match(code, /:disabled="readonly"/)
  assert.match(read('src/views/ai-decision/expert-team/index.vue'), /@click="newResearchDialog"/)
})
scope.stop()
await test('Leadership scope is above reading and uses unambiguous cohort labels', () => {
  const page = read('src/views/ai-decision/expert-team/index.vue')
  assert.ok(page.indexOf('<ResearchScopeSelector') < page.indexOf('ref="reading"'))
  const selector = read('src/views/ai-decision/expert-team/ResearchScopeSelector.vue')
  assert.match(selector, /researchPlanLabel\(plan\)/)
  assert.match(selector, /历史分析保持原范围/)
  assert.match(selector, /:disabled="readonly"/)
})
await test('Leadership page keeps archived reading and normal-state copy clean', () => {
  const page = read('src/views/ai-decision/expert-team/index.vue')
  assert.doesNotMatch(page.split('<script')[0], /capability-notice|class="research-progress" open/)
  assert.match(page, /class="archive-status"/)
  assert.match(page, /v-if="current\?\.status !== 'archived'" class="send-tools"/)
  assert.doesNotMatch(read('src/views/ai-decision/expert-team/MaterialPreview.vue'), /历史模板材料|研究编号：|材料版本：|重新校验当前权限/)
})
await test('Medium-screen notes free reading space without rewriting sidebar preference', () => {
  const page = read('src/views/ai-decision/expert-team/index.vue')
  assert.match(page, /const sidebarVisible = computed/)
  assert.match(page, /v-show="sidebarVisible"/)
  assert.match(page, /sidebarVisible.value \? 232 : 0/)
  assert.match(read('src/views/ai-decision/expert-team/ResearchSidePanel.vue'), /@keydown.esc.stop="\$emit\('close'\)"/)
  const layout = read('src/layouts/AppLayout.vue')
  assert.match(layout, /'expert-main': route.path === '\/admin\/reports\/expert-team'/)
  assert.match(layout, /\.el-main.expert-main[^}]*overflow:hidden/)
})
await test('New workspace stores no business draft in browser persistent storage', () => {
  const code = read('src/views/ai-decision/expert-team/useResearchWorkspace.ts')
  assert.doesNotMatch(code, /(?:localStorage|sessionStorage)\.setItem/)
})
await test('Sidebar persistence is layout-only and closing a panel restores the opener', () => {
  const code = read('src/views/ai-decision/expert-team/index.vue')
  assert.match(code, /sidebarPreferenceKey = 'expert-research-sidebar-open'/)
  assert.match(code, /setItem\(sidebarPreferenceKey, value \? '1' : '0'\)/)
  assert.match(code, /origin\.focus\(\{ preventScroll: true \}\)/)
  assert.match(code, /target\.focus\(\{ preventScroll: true \}\)/)
})
await test('Legacy view includes preserved result tables and original documents without writing controls', () => {
  const code = read('src/views/ai-decision/expert-team/index.vue')
  assert.match(code, /:result="legacyResult"[^\n]*readonly hide-sources/)
  assert.match(code, /legacyResult\?\.documents/); assert.match(code, /legacyResult\?\.methods/)
  assert.doesNotMatch(code, /v-model="sceneKey"|<LegacyWorkspace/)
})
await test('Reading area takes priority and the composer expands explicitly', () => {
  const code = read('src/views/ai-decision/expert-team/index.vue')
  const welcome = code.match(/<section v-if="!current" class="welcome">([\s\S]*?)<\/section>/)[1]
  assert.doesNotMatch(welcome, /<h2|welcome-eyebrow/); assert.match(welcome, /question-examples/)
  const styles = read('src/views/ai-decision/expert-team/leadership.scss')
  assert.match(styles, /is-expanded>textarea/); assert.match(code, /composerExpanded = !composerExpanded/)
})
await test('Recommendations have request generation guards and never replace a manual selection', () => {
  const selector = read('src/views/ai-decision/expert-team/ResearchScopeSelector.vue')
  assert.match(selector, /attempt === generation/)
  assert.match(selector, /watch\(\[\(\) => props.scope.plan_id/)
  assert.match(selector, /researchApi\.comparators/)
  assert.match(selector, /source_pending/)
  assert.doesNotMatch(selector, /scope\.target_plan_id = (?:value|recommendation)/)
})
await test('New results use a non-overlapping reading locator and separate data view', () => {
  const page = read('src/views/ai-decision/expert-team/index.vue')
  assert.match(page, /class="reading-location"/)
  assert.doesNotMatch(page.split('<script')[0], /class="new-content"/)
  assert.match(read('src/views/ai-decision/expert-team/ResearchResult.vue'), /v-show="view === 'data'"/)
})
await test('Research progress uses the supplied management summary while retaining numeric result content', () => {
  assert.match(read('src/views/ai-decision/expert-team/index.vue'), /result\.decision_summary \|\| result\.headline/)
  assert.match(read('src/views/ai-decision/expert-team/ResearchResult.vue'), /result\.headline \|\| result\.title/)
})
for (const name of ['index.vue', 'ResearchScopeSelector.vue', 'ResearchResult.vue', 'ResearchSidePanel.vue', 'ExpertPicker.vue', 'ExpertAvatar.vue', 'MaterialPreview.vue']) {
  await test(`Vue component parses and template compiles: ${name}`, () => {
    const filename = path.join(base, 'src/views/ai-decision/expert-team', name), source = fs.readFileSync(filename, 'utf8')
    const parsed = parse(source, { filename }); assert.deepEqual(parsed.errors, [])
    const script = compileScript(parsed.descriptor, { id: name })
    const template = compileTemplate({ id: name, filename, source: parsed.descriptor.template.content, compilerOptions: { bindingMetadata: script.bindings } })
    assert.deepEqual(template.errors, [])
  })
}
process.stdout.write(`\n${passed} expert research checks passed.\n`)
