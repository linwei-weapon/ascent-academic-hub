import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { reactive, ref, computed, isReactive } from 'vue'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const filename = new URL('../src/views/ai-decision/conversation/index.vue', import.meta.url)
const source = fs.readFileSync(filename, 'utf8')
const { descriptor } = parse(source, { filename: filename.pathname })
const script = compileScript(descriptor, { id: 'conversation-check' })
const template = compileTemplate({ source: descriptor.template.content, filename: filename.pathname, id: 'conversation-check', compilerOptions: { bindingMetadata: script.bindings } })
assert.deepEqual(template.errors, [])
const ast = ts.createSourceFile('conversation.ts', descriptor.scriptSetup.content, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = new Set(['openConversation', 'applyExecution', 'poll'])
const functions = ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.has(s.name?.text)).map(s => s.getText(ast)).join('\n')
assert.equal(ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.has(s.name?.text)).length, 3)
const js = ts.transpileModule(functions, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText

function harness() {
  const research = { id: 'history', turns: [{ id: 'turn', executionId: 'execution', expert: { id: 'course' } }] }
  const slots = reactive({ new: { draft: {} } }), currentKey = ref('new')
  const pending = [], timers = new Map()
  const context = {
    epoch: 1, slots, currentKey, historyOpen: ref(false), loadError: ref(''),
    tasks: ref([{ expertId: 'course', taskId: 'C-PERFORMANCE', available: true }]),
    makeSlot: () => ({ research: null, draft: {}, selected: -1, execution: null, pending: null, running: false, submitting: false, uncertain: false, error: '', notice: '' }),
    api: { research: async () => research, execution: () => new Promise(resolve => pending.push(resolve)) },
    loadCourses: async () => {}, loadHistory: async () => {}, timers,
    finalStates: new Set(['completed', 'partial', 'blocked', 'failed', 'cancelled', 'needs_input']),
    executionId: e => e?.id || '', explanationStateLabel: () => '事实模式', stateLabel: s => s,
    setTimeout: callback => callback, clearTimeout: () => {},
  }
  vm.createContext(context)
  vm.runInContext(js, context)
  const running = computed(() => slots[currentKey.value].running || false)
  return { context, slots, running, pending }
}
async function settle() { for (let i = 0; i < 5; i++) await Promise.resolve() }

const terminal = harness()
await terminal.context.openConversation('history')
assert.equal(terminal.running.value, true)
assert.equal(isReactive(terminal.slots.history), true)
terminal.pending.shift()({ id: 'execution', state: 'partial', revision: 2, workerFinished: true, researchId: 'history' })
await settle()
assert.equal(terminal.running.value, false, '历史执行已结束，发送按钮必须响应状态更新')
assert.equal(terminal.slots.history.research.turns.length, 1)
console.log('PASS historical terminal response unlocks reactive composer')

const explaining = harness()
await explaining.context.openConversation('history')
assert.equal(explaining.running.value, true)
explaining.pending.shift()({ id: 'execution', state: 'partial', revision: 2, workerFinished: false, researchId: 'history' })
await settle()
assert.equal(explaining.running.value, true, '事实已保存而工作尚未退出，不能提前解锁')
await explaining.context.applyExecution(explaining.slots.history, { id: 'execution', state: 'partial', revision: 3, workerFinished: true, researchId: 'history' }, 1)
assert.equal(explaining.running.value, false)
console.log('PASS facts saved keep occupied until actual worker exit')

const oldIdentity = harness()
await oldIdentity.context.openConversation('history')
assert.equal(oldIdentity.running.value, true)
oldIdentity.context.epoch = 2
oldIdentity.pending.shift()({ id: 'execution', state: 'partial', revision: 2, workerFinished: true, researchId: 'history' })
await settle()
assert.equal(oldIdentity.slots.history.execution, null, '旧身份响应不能写回当前状态')
console.log('PASS late response from old identity is ignored')
console.log('PASS conversation SFC compiles')

const presetSource = fs.readFileSync(new URL('../src/views/ai-decision/expert-resources/PresetTasks.vue', import.meta.url), 'utf8')
const presetDescriptor = parse(presetSource).descriptor
const presetAst = ts.createSourceFile('presets.ts', presetDescriptor.scriptSetup.content, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const loadRecords = presetAst.statements.find(s => ts.isFunctionDeclaration(s) && s.name?.text === 'loadRecords')
const presetJs = ts.transpileModule(loadRecords.getText(presetAst), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function presetHarness({ failOnce = false, workerFinished = true } = {}) {
  let refreshes = 0
  const latest = { executionId: 'finished', state: 'partial', workerFinished }
  const context = {
    epoch: 1, recordRequest: 0, recordTimer: null, refreshedExecution: '', props: { expertId: 'course' },
    recordPreset: ref({ id: 'C-BRIEF-01', latestExecution: { state: 'queued' } }), recordPage: ref(1),
    recordsLoading: ref(false), recordsError: ref(''), executions: ref([]), recordTotal: ref(0), recordsOpen: ref(true), items: ref([]),
    clearTimeout: () => {}, setTimeout: callback => callback,
    api: {
      presetExecutions: async () => ({ items: [latest], total: 1 }),
      presets: async () => { refreshes++; if (failOnce && refreshes === 1) throw new Error('temporary refresh failure'); return { items: [{ id: 'C-BRIEF-01', trialValid: true, latestExecution: latest }] } },
    },
  }
  vm.createContext(context)
  vm.runInContext(presetJs, context)
  return { context, latest, refreshes: () => refreshes }
}
const finished = presetHarness()
await finished.context.loadRecords()
assert.equal(finished.context.recordPreset.value.latestExecution.state, 'partial')
assert.equal(finished.context.refreshedExecution, 'finished')
await finished.context.loadRecords()
assert.equal(finished.refreshes(), 1)
console.log('PASS terminal record refreshes preset once using executionId')

const retryRefresh = presetHarness({ failOnce: true })
await retryRefresh.context.loadRecords()
assert.ok(retryRefresh.context.recordsError.value)
assert.equal(retryRefresh.context.refreshedExecution, '')
await retryRefresh.context.loadRecords()
assert.equal(retryRefresh.refreshes(), 2)
assert.equal(retryRefresh.context.recordPreset.value.trialValid, true)
assert.equal(retryRefresh.context.recordsError.value, '')
console.log('PASS failed preset refresh can retry without stale terminal cache')

const occupied = presetHarness({ workerFinished: false })
await occupied.context.loadRecords()
assert.equal(occupied.refreshes(), 0)
assert.ok(occupied.context.recordTimer)
occupied.latest.workerFinished = true
await occupied.context.loadRecords()
assert.equal(occupied.refreshes(), 1)
console.log('PASS record polling waits for actual worker finish')

for (const relative of ['briefing/index.vue', 'processing/index.vue', 'expert-resources/PresetTasks.vue', 'expert-resources/index.vue', 'expert-resources/RunResult.vue']) {
  const filename = new URL('../src/views/ai-decision/' + relative, import.meta.url)
  const d = parse(fs.readFileSync(filename, 'utf8'), { filename: filename.pathname }).descriptor
  const s = compileScript(d, { id: relative })
  assert.deepEqual(compileTemplate({ source: d.template.content, filename: filename.pathname, id: relative, compilerOptions: { bindingMetadata: s.bindings } }).errors, [])
}
console.log('PASS five adjacent management and result SFCs compile')

// Temporary identity/network failures must preserve drafts and invalid-source
// notices. Retrying resources never resubmits a conversation request.
const loadFunction = ast.statements.find(s => ts.isFunctionDeclaration(s) && s.name?.text === 'load')
assert.ok(loadFunction)
const loadJs = ts.transpileModule(loadFunction.getText(ast), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
let failResources = true, catalogRequests = 0, optionRequests = 0
const resourceContext = {
  epoch: 1, resourcesLoading: ref(false), resourcesError: ref(''),
  loadError: ref('来源已失效'), catalog: ref({ experts: [] }), tasks: ref([]), models: ref([]),
  slots: reactive({ new: { draft: { question: '保留这条未发送问题' } } }),
  api: {
    catalog: async () => { catalogRequests++; if (failResources) throw new Error('身份校验暂时中断'); return { experts: [{ id: 'course' }] } },
    tasks: async () => ({ items: [{ taskId: 'C-PERFORMANCE', expertId: 'course', available: true }] }),
    models: async () => ({ items: [] }),
  },
  loadOptions: async () => { optionRequests++ },
}
vm.createContext(resourceContext)
vm.runInContext(loadJs, resourceContext)
const firstResourceLoad = resourceContext.load()
await resourceContext.load()
await firstResourceLoad
assert.equal(catalogRequests, 1)
assert.equal(resourceContext.resourcesError.value, '身份校验暂时中断')
assert.equal(optionRequests, 0)
assert.equal(resourceContext.resourcesLoading.value, false)
failResources = false
await resourceContext.load()
assert.equal(resourceContext.resourcesError.value, '')
assert.equal(resourceContext.catalog.value.experts[0].id, 'course')
assert.equal(resourceContext.slots.new.draft.question, '保留这条未发送问题')
assert.equal(resourceContext.loadError.value, '来源已失效')
assert.equal(optionRequests, 1)
console.log('PASS resource retry preserves draft and source notice without duplicate submission')

let finishOldCatalog
resourceContext.api.catalog = () => new Promise(resolve => { finishOldCatalog = resolve })
const oldIdentityLoad = resourceContext.load()
resourceContext.epoch++
resourceContext.resourcesLoading.value = false
resourceContext.catalog.value = { experts: [{ id: 'new-identity' }] }
finishOldCatalog({ experts: [{ id: 'old-identity' }] })
await oldIdentityLoad
assert.equal(resourceContext.catalog.value.experts[0].id, 'new-identity')
assert.equal(optionRequests, 1)
console.log('PASS delayed resources from previous identity cannot replace current catalog')
