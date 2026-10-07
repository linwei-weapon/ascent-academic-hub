<template>
  <main class="verification-page">
    <header class="page-heading">
      <div><h2 class="sa-page-title">指标核验</h2><p class="sa-page-sub">按业务指标查看需求口径、三层数据与 SQL，对照真实结果并记录判断。</p></div>
      <div class="revision-actions"><el-select :model-value="moduleId" :disabled="!!selectedEntry || loading || importOpen" aria-label="选择指标业务模块" style="width:170px" @change="changeModule"><el-option label="教学数据总览" value="teaching-overview" /><el-option label="AI简报" value="ai-briefing" /></el-select><el-tag v-if="catalog" effect="plain">{{ catalog.capabilities.environment || '环境待确认' }}</el-tag><el-button size="small" :loading="loading" :disabled="!!selectedEntry || importOpen" :title="selectedEntry ? '返回指标清单后刷新，保留正在填写的核验内容' : '读取当前生效的指标映射'" @click="loadCatalog">刷新指标映射</el-button><el-button v-if="mappingManage" size="small" :disabled="!!selectedEntry || loading || importOpen" @click="importOpen = true">导入映射包</el-button></div>
    </header>
    <p v-if="catalog?.mappingRevisionId" class="mapping-version">当前映射：{{ mappingRevision?.package.packageId || catalog.mappingRevisionId }}<span v-if="mappingRevision"> · {{ mappingRevision.package.metrics.length }} 个业务指标</span> · SQL 与核验记录使用此版本。{{ selectedEntry ? '返回清单后可刷新版本。' : '' }}</p>
    <el-alert v-if="mappingError" :title="mappingError" type="warning" :closable="false" show-icon />
    <el-alert v-if="accessError" :title="accessError" type="warning" :closable="false" show-icon />
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon><template #default><el-button size="small" @click="loadCatalog">重新加载</el-button></template></el-alert>
    <section v-show="!selectedEntry" v-loading="loading" class="sa-card indicator-list" aria-label="业务指标清单">
      <div class="list-heading"><div><h3>{{ catalog?.module.name || moduleName }}</h3><p class="muted">按页面找指标，同一口径在不同场景复用。</p></div><span class="muted">{{ filteredEntries.length }} 个指标场景</span></div>
      <form class="filters" @submit.prevent="applyFilters">
        <label><span>业务页面</span><el-select v-model="draft.page" aria-label="业务页面" @change="draft.group = ''"><el-option label="全部页面" value="" /><el-option v-for="page in catalog?.indicatorSystem?.pages || []" :key="page.id" :label="page.name" :value="page.id" /></el-select></label>
        <label><span>指标分类</span><el-select v-model="draft.group" clearable aria-label="指标分类" placeholder="全部分类"><el-option v-for="group in groups" :key="group" :label="group" :value="group" /></el-select></label>
        <label class="search-field"><span>指标名称</span><el-input v-model="draft.search" clearable aria-label="搜索指标名称" placeholder="搜索业务名称或页面别名" /></label>
        <div class="filter-actions"><el-button type="primary" native-type="submit">查询</el-button><el-button @click="resetFilters">重置</el-button></div>
      </form>
      <el-alert v-if="recentError" :title="recentError" type="info" :closable="false" />
      <el-alert v-if="catalog && !catalog.indicatorSystem" title="指标体系尚未返回，暂不能展示业务指标入口。" description="请确认核验服务已更新；原需求登记仍保留，不将全文条款替代为指标清单。" type="warning" :closable="false" />
      <section v-for="section in groupedEntries" :key="section.name" class="indicator-group">
        <h4>{{ section.name }}</h4>
        <div class="indicator-grid">
          <article v-for="entry in section.entries" :key="entry.id" class="indicator-card">
            <div class="card-heading"><button :id="entryButtonId(entry.id)" type="button" class="indicator-link" @click="openEntry(entry)">{{ entry.name }}</button><el-tag size="small" :type="entry.status === 'pending' ? 'warning' : 'info'" effect="plain">{{ definitionStatus(entry.status) }}</el-tag></div>
            <p class="scene-name">{{ pageName(entry.pageId) }}</p><p class="meaning">{{ entry.meaning }}</p>
            <p v-if="entry.pendingIssues.length" class="pending-note">待明确：{{ entry.pendingIssues[0] }}{{ entry.pendingIssues.length > 1 ? `（另有 ${entry.pendingIssues.length - 1} 项）` : '' }}</p>
            <div class="recent-status" v-if="recentByEntry.get(entry.id)"><el-tag size="small" :type="recentByEntry.get(entry.id)?.current === false ? 'info' : judgmentType(recentByEntry.get(entry.id)!.judgment)">{{ recentByEntry.get(entry.id)?.current === true ? '最近：' : '历史：' }}{{ recentByEntry.get(entry.id)?.judgment }}</el-tag><span>{{ formatTime(recentByEntry.get(entry.id)!.createdAt) }}</span><small>{{ recentByEntry.get(entry.id)?.current === false ? '定义已变化，需重新核对' : '仅适用该记录的范围与时点' }}</small></div>
            <p v-else class="muted recent-status">{{ catalog?.capabilities.records ? '近期记录中尚无本场景核验' : '核验记录存储未就绪' }}</p>
            <el-button class="entry-action" type="primary" plain @click="openEntry(entry)">查看口径、三层 SQL 与结果</el-button>
          </article>
        </div>
      </section>
      <el-empty v-if="catalog?.indicatorSystem && !loading && !filteredEntries.length" :description="moduleId === 'ai-briefing' && !catalog.mappingRevisionId ? 'AI简报指标尚未登记生效。完成受保护的映射发布后刷新。' : '没有符合条件的指标，请调整页面、分类或名称。'" :image-size="70" />
      <p v-if="!loading && !catalog && mappingManage" class="muted">尚未取得当前生效清单。可从“导入映射包”查看实际版本并保存完整映射；数据库或基线有问题时，服务会拒绝保存与生效。</p>
      <p v-if="catalog?.capabilities.records" class="muted list-footnote">最近状态来自当前身份的最近 100 条记录，未显示不代表从未核验。历史“符合”不自动适用于本次范围。</p>
    </section>
    <template v-if="selectedEntry && catalog">
      <RequirementWorkspace v-if="selectedMetric && selectedRequirement" :key="`${moduleId}:${selectedEntry.id}:${catalog.mappingRevisionId || 'legacy'}`" :module-id="moduleId" :entry="selectedEntry" :metric="selectedMetric" :metrics="catalog.metrics" :requirement="selectedRequirement" :capabilities="catalog.capabilities" :source-document="catalog.module.sourceDocument" :page-name="pageName(selectedEntry.pageId)" :mapping-revision-id="catalog.mappingRevisionId" :mapping="mappingRevision?.package" @collapse="closeEntry" @saved="rememberRecord" />
      <el-alert v-else title="该指标场景的定义或需求关联尚未完整返回。" type="warning" :closable="false"><template #default><el-button @click="closeEntry">返回指标清单</el-button></template></el-alert>
    </template>
    <el-alert v-if="!loading && route.query.scene && !selectedEntry && catalog" title="此指标场景已变更或不存在，请从当前清单重新选择。" type="warning" :closable="false" />
    <details v-if="catalog?.capabilities.limitations.length" class="environment-notes"><summary>当前环境与核验边界</summary><ul><li v-for="item in catalog.capabilities.limitations" :key="item">{{ item }}</li></ul></details>
    <MappingPackageImport v-if="importOpen" :key="moduleId" :module-id="moduleId" :can-manage="mappingManage" @close="importOpen = false" @changed="loadCatalog" />
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getRecentVerificationRecords, getVerificationCatalog, getMappingRevision, getVerificationAccess } from '@/api/admin/metricVerification'
import type { VerificationCatalog, VerificationIndicatorEntry, VerificationJudgment, VerificationRecord, MappingRevision, VerificationModuleId } from '@/types/metricVerification'
import RequirementWorkspace from './RequirementWorkspace.vue'
import MappingPackageImport from './MappingPackageImport.vue'
import { definitionStatus } from './labels'
const route = useRoute()
const router = useRouter()
const moduleId = computed<VerificationModuleId>(() => route.query.moduleId === 'ai-briefing' ? 'ai-briefing' : 'teaching-overview')
const moduleName = computed(() => moduleId.value === 'ai-briefing' ? 'AI简报' : '教学数据总览')
const catalog = ref<VerificationCatalog>()
const loading = ref(false)
const loadError = ref('')
const recentError = ref('')
const mappingRevision = ref<MappingRevision>()
const mappingError = ref('')
const importOpen = ref(false)
const mappingManage = ref(false)
const accessError = ref('')
const recentRecords = ref<VerificationRecord[]>([])
const draft = reactive({ page: typeof route.query.page === 'string' ? route.query.page : 'home', group: typeof route.query.group === 'string' ? route.query.group : '', search: typeof route.query.search === 'string' ? route.query.search : '' })
const filters = reactive({ ...draft })
let alive = true
let loadGeneration = 0
const entries = computed(() => catalog.value?.indicatorSystem?.entries || [])
const selectedEntry = computed(() => entries.value.find(entry => entry.id === route.query.scene))
const selectedMetric = computed(() => catalog.value?.metrics.find(metric => metric.id === selectedEntry.value?.metricId))
const selectedRequirement = computed(() => catalog.value?.requirements.find(requirement => requirement.id === selectedEntry.value?.requirementId))
const groups = computed(() => [...new Set(entries.value.filter(entry => !draft.page || entry.pageId === draft.page).map(entry => entry.group))])
const filteredEntries = computed(() => {
  const search = filters.search.trim().toLocaleLowerCase()
  return entries.value.filter(entry => (!filters.page || entry.pageId === filters.page) && (!filters.group || entry.group === filters.group)
    && (!search || [entry.name, ...entry.aliases, pageName(entry.pageId)].join(' ').toLocaleLowerCase().includes(search)))
})
const groupedEntries = computed(() => [...new Set(filteredEntries.value.map(entry => entry.group))].map(name => ({ name, entries: filteredEntries.value.filter(entry => entry.group === name) })))
const recentByEntry = computed(() => {
  const result = new Map<string, VerificationRecord>()
  for (const record of [...recentRecords.value].sort((a, b) => b.createdAt.localeCompare(a.createdAt))) {
    const entry = entries.value.find(item => item.id === record.scenarioId && item.metricId === record.metricId)
    if (entry && !result.has(entry.id)) result.set(entry.id, record)
  }
  return result
})
function pageName(id: string) { return catalog.value?.indicatorSystem?.pages.find(page => page.id === id)?.name || '页面待定位' }
function entryButtonId(id: string) { return `indicator-entry-${id}` }
function judgmentType(value: VerificationJudgment): 'success' | 'danger' | 'warning' { return value === '符合' ? 'success' : value === '有差异' ? 'danger' : 'warning' }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) }
function filterQuery() { return { ...route.query, moduleId: moduleId.value, page: filters.page, group: filters.group || undefined, search: filters.search || undefined } }
async function changeModule(value: VerificationModuleId) {
  if (selectedEntry.value || importOpen.value || value === moduleId.value) return
  Object.assign(draft, { page: 'home', group: '', search: '' }); Object.assign(filters, draft)
  catalog.value = undefined; mappingRevision.value = undefined; recentRecords.value = []
  await router.replace({ path: route.path, query: { moduleId: value, page: 'home' } })
}
function applyFilters() { Object.assign(filters, draft); void router.replace({ path: route.path, query: { ...filterQuery(), scene: undefined } }) }
function resetFilters() { Object.assign(draft, { page: 'home', group: '', search: '' }); applyFilters() }
async function openEntry(entry: VerificationIndicatorEntry) {
  await router.push({ path: route.path, query: { ...filterQuery(), scene: entry.id } })
  await nextTick()
  document.getElementById('indicator-detail-heading')?.scrollIntoView({ block: 'start' })
  document.getElementById('indicator-detail-heading')?.focus({ preventScroll: true })
}
async function closeEntry() {
  const id = selectedEntry.value?.id
  await router.push({ path: route.path, query: { ...filterQuery(), scene: undefined } })
  await nextTick()
  if (id) { document.getElementById(entryButtonId(id))?.focus({ preventScroll: true }); document.getElementById(entryButtonId(id))?.scrollIntoView({ block: 'nearest' }) }
}
function rememberRecord(record: VerificationRecord) { recentRecords.value = [record, ...recentRecords.value.filter(item => item.id !== record.id)].slice(0, 100) }
async function loadCatalog() {
  const generation = ++loadGeneration
  const selectedModule = moduleId.value
  loading.value = true; loadError.value = ''; recentError.value = ''; mappingError.value = ''; accessError.value = ''; mappingManage.value = false
  try {
    const [access, response] = await Promise.allSettled([getVerificationAccess(selectedModule), getVerificationCatalog(selectedModule)])
    if (!alive || generation !== loadGeneration) return
    if (access.status === 'fulfilled') mappingManage.value = access.value.authorized === true && access.value.mappingManage === true
    else accessError.value = `映射维护权限暂未确认：${access.reason instanceof Error ? access.reason.message : '读取失败'}`
    if (response.status === 'rejected') throw response.reason
    const result = response.value
    catalog.value = result
    mappingRevision.value = undefined
    if (result.mappingRevisionId) {
      try { const revision = await getMappingRevision(result.mappingRevisionId, selectedModule); if (alive && generation === loadGeneration) mappingRevision.value = revision }
      catch (error) { if (alive && generation === loadGeneration) mappingError.value = `映射依据暂未取得：${error instanceof Error ? error.message : '读取失败'}。SQL 仍绑定当前读取版本。` }
    }
    if (result.capabilities.records) {
      try { const response = await getRecentVerificationRecords(result.mappingRevisionId, selectedModule); if (alive && generation === loadGeneration) recentRecords.value = response.items }
      catch (error) { if (alive && generation === loadGeneration) recentError.value = `最近核验状态暂未取得：${error instanceof Error ? error.message : '读取失败'}` }
    }
  } catch (error) { if (alive && generation === loadGeneration) loadError.value = error instanceof Error ? error.message : '读取业务指标失败' }
  finally { if (alive && generation === loadGeneration) loading.value = false }
}
watch(moduleId, () => { importOpen.value = false; mappingManage.value = false; catalog.value = undefined; mappingRevision.value = undefined; recentRecords.value = []; void loadCatalog() })
onMounted(loadCatalog)
onBeforeUnmount(() => { alive = false; ++loadGeneration })
</script>

<style scoped>
.verification-page { min-width:0; }
.revision-actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }.mapping-version { font-size:12px; color:var(--el-text-color-secondary); overflow-wrap:anywhere; margin:0 0 16px; }
.page-heading,.list-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:18px; }
.indicator-list { padding:20px; } h3,h4 { margin:0; } h3 { font-size:17px; } h4 { font-size:15px; margin-bottom:12px; }
.muted,.scene-name { color:var(--el-text-color-secondary); font-size:12px; } .list-heading p { margin:7px 0 0; }
.filters { display:flex; align-items:end; flex-wrap:wrap; gap:12px; margin-bottom:22px; }
.filters label { display:flex; flex-direction:column; gap:6px; width:180px; min-width:0; font-size:12px; }
.filters .search-field { flex:1 1 220px; } .filter-actions { display:flex; } .indicator-group { margin:24px 0; }
.indicator-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(310px,100%),1fr)); gap:14px; }
.indicator-card { border:1px solid var(--el-border-color-light); border-radius:6px; padding:16px; display:flex; flex-direction:column; min-width:0; }
.card-heading { display:flex; align-items:start; justify-content:space-between; gap:10px; } .card-heading .el-tag { flex-shrink:0; }
.indicator-link { color:var(--el-color-primary); font:inherit; font-size:15px; font-weight:600; border:0; background:transparent; padding:0; text-align:left; line-height:1.55; cursor:pointer; scroll-margin-top:90px; }
.indicator-link:focus-visible { outline:2px solid var(--el-color-primary); outline-offset:4px; }
.meaning { font-size:13px; line-height:1.7; margin:2px 0 12px; overflow-wrap:anywhere; }
.scene-name { margin:5px 0 9px; } .pending-note { font-size:12px; line-height:1.6; color:var(--el-color-warning-dark-2); margin:0 0 12px; }
.recent-status { display:flex; flex-wrap:wrap; align-items:center; gap:5px 8px; margin:auto 0 12px; padding-top:8px; font-size:11px; color:var(--el-text-color-secondary); }
.recent-status small { flex-basis:100%; font-size:11px; } .entry-action { align-self:flex-start; max-width:100%; white-space:normal; height:auto; min-height:32px; line-height:1.5; }
.list-footnote { line-height:1.6; } .environment-notes { margin:16px 4px; color:var(--el-text-color-secondary); font-size:13px; } summary { cursor:pointer; } li { margin:5px 0; }
@media(max-width:760px) { .page-heading,.list-heading { flex-direction:column; gap:8px; } .indicator-list { padding:12px; } .filters label { flex:1 1 150px; } }
</style>
