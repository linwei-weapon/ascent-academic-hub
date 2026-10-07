import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { ref, computed } from 'vue'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

const directory = new URL('../src/views/ai-decision/expert-resources/', import.meta.url)
let ast
for (const name of ['index.vue', 'ImportSkillDialog.vue', 'ResourceConfiguration.vue']) {
  const filename = new URL(name, directory)
  const { descriptor, errors } = parse(fs.readFileSync(filename, 'utf8'), { filename: filename.pathname })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: name })
  const template = compileTemplate({ source: descriptor.template.content, filename: filename.pathname, id: name, compilerOptions: { bindingMetadata: script.bindings } })
  assert.deepEqual(template.errors, [])
  if (name === 'index.vue') ast = ts.createSourceFile('resources.ts', descriptor.scriptSetup.content, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
}
console.log('PASS detail, create and package drawer SFCs compile')

const names = new Set(['closeDetail', 'closeCreate', 'confirmDiscard', 'mayLeave', 'startEdit', 'editBindings', 'bindSkill'])
const statements = ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.has(s.name?.text))
assert.equal(statements.length, names.size)
const js = ts.transpileModule(statements.map(s => s.getText(ast)).join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function harness() {
  const context = {
    selected: ref({ id: 'expert' }), navigation: ref([{ id: 'previous' }]), editing: ref(true),
    expanded: ref(true), section: ref('basic'), bindingSearch: ref('old'), viewVersion: ref('published'),
    content: ref({ skillIds: ['disabled'] }), catalog: ref({ skills: [{ id: 'live', enabled: true, published: {} }, { id: 'disabled', enabled: false, published: {} }, { id: 'unpublished', enabled: true }] }),
    busy: ref(false), loading: ref(false), dirty: ref(true), createDirty: ref(false), createVisible: ref(false),
    importVisible: ref(false), importDialog: ref(null), resourceRequest: 7,
    route: { path: '/admin/system/expert-management', query: {} },
    search: ref('课程'), category: ref('建设与改进'), status: ref('published'),
    approved: false, prompts: 0, replacements: [],
    ElMessageBox: { confirm: async () => { context.prompts++; if (!context.approved) throw new Error('cancel') } },
    router: { replace: async value => { context.replacements.push(value); if (context.approved) context.selected.value = null } },
  }
  vm.createContext(context)
  vm.runInContext(js, context)
  return context
}
const c = harness()
await c.closeDetail()
assert.equal(c.selected.value.id, 'expert')
assert.equal(c.navigation.value.length, 1)
assert.equal(c.expanded.value, true)
c.approved = true
await c.closeDetail()
assert.equal(c.selected.value, null)
assert.equal(c.navigation.value.length, 0)
assert.equal(c.expanded.value, false)
assert.equal(c.resourceRequest, 8)
console.log('PASS cancelled close retains draft; approved close clears detail and invalidates pending resource')

const url = harness()
url.route.query = { resourceId: 'expert', section: 'dependencies', backTo: '/admin/system/skill-management', backLabel: '技能', other: 'keep' }
await url.closeDetail()
assert.equal(url.selected.value.id, 'expert')
assert.deepEqual(JSON.parse(JSON.stringify(url.replacements[0].query)), { search: '课程', category: '建设与改进', status: 'published', other: 'keep' })
url.approved = true
await url.closeDetail()
assert.equal(url.selected.value, null)
console.log('PASS direct URL close preserves list filters and respects router refusal')

const blocked = harness()
blocked.busy.value = true
await blocked.closeDetail()
blocked.editBindings()
assert.equal(blocked.prompts, 0)
assert.equal(blocked.section.value, 'basic')
blocked.busy.value = false
blocked.editBindings()
assert.equal(blocked.editing.value, true)
assert.equal(blocked.viewVersion.value, 'draft')
assert.equal(blocked.section.value, 'dependencies')
assert.equal(blocked.bindingSearch.value, '')
console.log('PASS binding shortcut edits draft dependencies; busy operations cannot change work context')

const bindings = harness()
bindings.bindSkill('unpublished', true)
assert.deepEqual([...bindings.content.value.skillIds], ['disabled'])
bindings.bindSkill('disabled', false)
bindings.bindSkill('live', true)
assert.deepEqual([...bindings.content.value.skillIds], ['live'])
console.log('PASS unavailable old binding is removable; new binding requires enabled published skill')

const creation = harness()
creation.createVisible.value = true
creation.createDirty.value = true
await creation.closeCreate()
assert.equal(creation.createVisible.value, true)
creation.approved = true
await creation.closeCreate()
assert.equal(creation.createVisible.value, false)
creation.importVisible.value = true
creation.importDialog.value = { busy: true, mayLeave: async () => true }
assert.equal(await creation.mayLeave(), false)
creation.importDialog.value = { busy: false, mayLeave: async () => false }
assert.equal(await creation.mayLeave(), false)
console.log('PASS new form cancel protects entered values; uploading and cancelled package discard block navigation')

const derived = ast.statements.find(s => ts.isVariableStatement(s) && s.declarationList.declarations.some(d => d.name.getText(ast) === 'derivedTools'))
const deps = { computed, visibleSkills: ref([{ published: { content: { toolBindings: [{ serverId: 'live', toolName: 'published' }] } }, draft: { content: { toolBindings: [{ serverId: 'draft', toolName: 'unpublished' }] } } }]) }
vm.createContext(deps)
vm.runInContext(ts.transpileModule(`${derived.getText(ast)}\nglobalThis.result=derivedTools`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, deps)
assert.equal(deps.result.value[0].toolName, 'published')
console.log('PASS expert MCP preview uses skill published dependencies, never an unrelated skill draft')
