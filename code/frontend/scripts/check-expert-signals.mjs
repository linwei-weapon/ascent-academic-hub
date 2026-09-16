// Pure presentation contracts; no browser, credentials, API calls or real student data.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/utils/expertTeamSignals.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } })
const { teamSignals } = await import('data:text/javascript;base64,' + Buffer.from(compiled.outputText).toString('base64'))
const result = (expert, extra = {}) => ({ expert_id: expert, scenario: '', tables: [], ...extra })
const table = (id, rows = []) => ({ id, rows })
const values = r => teamSignals(r).map(c => c.value)

assert.deepEqual(values(result('program', { comparison: { focus_shared: 3, focus_union: 11, focus_similarity: 27.3 } })), [3, 11, 27.3])
assert.deepEqual(values(result('program', { comparison: { focus_shared: 0, focus_union: 0, focus_similarity: null } })), [0, 0, null])
assert.deepEqual(values(result('program', { scenario: 'sequence', comparison: { focus_shared: 99 }, tables: [table('schedule', [{}, {}])] })), [2])
assert.deepEqual(values(result('transfer', { comparison: { target_required: 61, potential_required: 39, additional_required: 22 } })), [61, 39, 22])
assert.deepEqual(values(result('course', { tables: [table('performance', [{ fails: 2 }, { fails: 0 }, { fails: 1 }])] })), [3, 2])
assert.deepEqual(values(result('course', { tables: [table('course_current', [{ students: 20, failed_students: 2, fail_rate: 10 }])] })), [20, 2, 10])
assert.deepEqual(values(result('course', { tables: [table('trend', [{}, {}])] })), [2])
assert.deepEqual(values(result('course')), [])
assert.deepEqual(values(result('graduation', { snapshot: { population: 113, counts: { explicit_gap: 3, candidate: 108, binding_issue: 2 } } })), [113, 3, 108, 2])
assert.deepEqual(values(result('graduation', { snapshot: { population: 5 } })), [5, null, null, null])
assert.deepEqual(values(result('recommendation')), [])
assert.equal(teamSignals(result('course', { tables: [table('course_current', [{ students: 0, failed_students: 0, fail_rate: null }])] }))[1].tableId, '')
assert.equal(teamSignals(result('course', { tables: [table('course_current', [{}]), table('class_distribution')] }))[1].tableId, 'class_distribution')
console.log('13 expert-signal presentation contracts PASS')
