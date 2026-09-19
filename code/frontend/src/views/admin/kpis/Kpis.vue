<!-- 指标与口径管理：系统管理模块，沿用既有接口、治理操作与权限边界。 -->
<template>
  <div class="metric-page">
    <div class="page-head">
      <div>
        <h2 class="sa-page-title">指标与口径管理</h2>
        <p class="sa-page-sub">统一查看正式指标定义、学校待确认口径、实现证据和页面引用；指标公式不在页面中任意编辑。</p>
      </div>
      <el-button :loading="exporting" @click="exportCatalog">导出指标确认清单</el-button>
    </div>

    <div class="catalog-context">
      <span><b>目录版本</b>{{ summary.catalogVersion || '—' }}</span>
      <span><b>已绑定页面</b>{{ summary.boundPages || 0 }} 个</span>
      <span><b>治理边界</b>指标定义、页面展示、分析阈值分开管理</span>
    </div>

    <template v-if="initialLoading">
      <el-alert title="正在整理指标目录、页面引用和实现证据，预计需要数秒…" type="info" :closable="false" show-icon />
      <div class="sa-card loading-card"><el-skeleton :rows="9" animated /></div>
    </template>
    <template v-else>
      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
        <template #default><el-button size="small" @click="reloadAll">重新加载</el-button></template>
      </el-alert>

      <div class="metric-kpis">
        <button v-for="card in cards" :key="card.key" type="button"
          class="metric-kpi" :class="{active:activeCard===card.key}" @click="applyCard(card.key)">
          <span>{{ card.label }} <el-tooltip :content="card.help"><i>?</i></el-tooltip></span>
          <b>{{ card.value }}</b>
          <small>{{ card.action }}</small>
        </button>
      </div>

      <el-tabs v-model="activeTab" class="metric-tabs" @tab-change="onTabChange">
        <el-tab-pane label="指标目录" name="catalog">
          <el-alert
            class="catalog-hint"
            title="候选指标表示尚待学校确认，不等于功能缺失。"
            type="info"
            :closable="false"
            show-icon
          />

          <div v-if="listLoading && rows.length" class="updating-bar">正在按新条件更新指标目录，当前结果暂时保留…</div>
          <div class="sa-card table-card catalog-table" v-loading="listLoading && !!rows.length"
            element-loading-text="正在更新指标目录…">
            <AppTable
              show-density
              show-column-settings
              :columns="columns"
              :data="rows"
              storage-key="system:metric-catalog"
              :max-business-columns="7"
              :config-version="1"
              :page-size="pageSize"
              stripe
              empty-text="当前条件下没有指标"
              @page-size-change="changePageSize"
              @row-click="openDetail"
              row-class-name="metric-row"
              :page="page"
              :total="total"
              :loading="listLoading"
              @page-change="changePage"
            >
              <template #toolbar>
                <div class="filters sa-button-row">
                  <el-select size="small" v-model="filters.domain" clearable placeholder="全部业务域" @change="search">
                    <el-option v-for="item in summary.domains || []" :key="item.label"
                      :label="`${item.label}（${item.count}）`" :value="item.label" />
                  </el-select>
                  <el-select size="small" v-model="filters.definitionStatus" clearable placeholder="全部定义状态" @change="search">
                    <el-option label="已发布" value="published" />
                    <el-option label="待学校确认" value="pending_confirmation" />
                    <el-option label="范围背景" value="context" />
                    <el-option label="已停用" value="deprecated" />
                  </el-select>
                  <el-select size="small" v-model="filters.implementationStatus" clearable placeholder="全部实现状态" @change="search">
                    <el-option label="已实现并验证" value="verified" />
                    <el-option label="待建立实现证据" value="unverified" />
                    <el-option label="定义与实现不一致" value="mismatch" />
                    <el-option label="已退出页面" value="retired" />
                  </el-select>
                  <el-input size="small" v-model="filters.keyword" clearable placeholder="搜索指标名称、编号、公式或技术标识"
                    @keyup.enter="search" @clear="search" />
                  <el-button size="small" type="primary" @click="search">查询</el-button>
                  <el-button size="small" @click="resetFilters">重置</el-button>
                </div>
              </template>
              <template #col-identity="{row}">
                <div class="metric-identity"><b>{{ row.name }}</b><span>{{ row.metric_id }}</span></div>
              </template>
              <template #col-definition_status_label="{row}">
                <el-tag size="small" effect="plain" :type="definitionTag(row.definition_status)">
                  {{ row.definition_status_label }}
                </el-tag>
              </template>
              <template #col-implementation_status_label="{row}">
                <el-tag size="small" effect="plain" :type="implementationTag(row.implementation_status)">
                  {{ row.implementation_status_label }}
                </el-tag>
              </template>
              <template #col-page_count="{row}">
                <span v-if="row.page_count">{{ row.page_count }} 个页面</span>
                <span v-else class="sa-faint">尚未绑定</span>
              </template>
              <template #col-action><el-button link type="primary">核查口径</el-button></template>
            </AppTable>
          </div>
        </el-tab-pane>

        <el-tab-pane label="页面引用与一致性" name="pages">
          <el-alert title="只有建立了“指标定义—计算实现—使用页面”显式绑定的指标，才计为已验证；能显示数字不等于口径已经登记。" type="info" :closable="false" show-icon />
          <div class="sa-card table-card page-table" v-loading="pagesLoading">
            <AppTable
              show-density
              show-column-settings
              :columns="pageColumns"
              :data="pageTable.rows"
              storage-key="system:metric-page-bindings"
              :max-business-columns="5"
              :config-version="1"
              stripe
              empty-text="尚无已登记的页面引用"
              :page="pageTable.page"
              :page-size="pageTable.pageSize"
              :total="pageTable.total"
              :loading="pagesLoading"
              @page-change="pageTable.changePage"
              @page-size-change="pageTable.changePageSize"
            >
              <template #col-page_path="{row}"><code>{{ row.page_path }}</code></template>
              <template #col-status="{row}">
                <el-tag size="small" effect="plain" :type="row.issue_count ? 'danger' : 'success'">
                  {{ row.issue_count ? `${row.issue_count} 项待核查` : '版本一致' }}
                </el-tag>
              </template>
            </AppTable>
          </div>
        </el-tab-pane>

        <el-tab-pane label="版本与治理规则" name="governance">
          <div class="governance-grid">
            <section class="sa-card">
              <h3>正式指标定义</h3>
              <p>管理指标必须先登记统计对象、分子分母、排除条件、来源、粒度和版本，再进入业务页面。</p>
              <ul><li>不在前端执行自然语言公式或任意SQL。</li><li>正式口径变化通过代码、迁移和测试发布新版本。</li><li>旧版本保留页面引用与审计证据。</li></ul>
            </section>
            <section class="sa-card">
              <h3>页面展示配置</h3>
              <p>页面别名、显隐和顺序属于页面级配置，不再伪装成指标定义。</p>
              <ul><li>同一指标可被多个页面引用。</li><li>页面必须声明采用的定义版本。</li><li>展示配置可以独立记录历史和安全回滚。</li></ul>
            </section>
            <section class="sa-card">
              <h3>分析阈值</h3>
              <p>关注阈值、优先级和适用角色因学校管理办法而异，统一由“分析方案管理”承载。</p>
              <ul><li>学生数、教师数等背景量不强制设置风险阈值。</li><li>阈值不改变指标的分子和分母。</li><li>发布前需要学校确认适用范围和版本。</li></ul>
            </section>
          </div>
          <div class="sa-card migration-note">
            <h3>当前目录迁移说明</h3>
            <p>客户确认文档中的指标已进入统一候选目录；当前代码中有明确计算与页面绑定证据的指标标记为“已实现并验证”。原“应届毕业率、学位授予率”因只有合成结果，已退出正式页面，仅保留历史兼容记录。</p>
            <el-button type="primary" plain @click="applyCard('pending')">核查待学校确认指标</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-drawer v-model="detailVisible" size="720px" :title="detailTitle" destroy-on-close>
      <template v-if="detailLoading">
        <el-skeleton :rows="10" animated />
      </template>
      <template v-else-if="detail.definition">
        <div class="drawer-status">
          <el-tag effect="plain" :type="definitionTag(detail.definition.definition_status)">
            {{ detail.definition.definition_status_label }}
          </el-tag>
          <el-tag effect="plain" :type="implementationTag(detail.definition.implementation_status)">
            {{ detail.definition.implementation_status_label }}
          </el-tag>
          <span>版本 {{ detail.definition.version }}</span>
        </div>
        <el-tabs>
          <el-tab-pane label="管理解释">
            <section class="definition-block"><span>回答的管理问题</span><p>{{ detail.definition.management_value || '待补充' }}</p></section>
            <section class="definition-block"><span>不应如何解读 / 待确认边界</span><p>{{ detail.definition.boundary || '暂无额外边界' }}</p></section>
            <section class="definition-block"><span>目录来源</span><p>{{ detail.definition.definition_source }}</p></section>
          </el-tab-pane>
          <el-tab-pane label="统计口径">
            <section class="definition-block important"><span>计算逻辑</span><p>{{ detail.definition.formula }}</p></section>
            <div class="detail-grid">
              <div><span>指标编号</span><b>{{ detail.definition.metric_id }}</b></div>
              <div><span>技术标识</span><b>{{ detail.definition.technical_kpi_id || '尚未绑定' }}</b></div>
              <div><span>数据来源</span><b>{{ detail.definition.data_source || '待实施核验' }}</b></div>
              <div><span>统计粒度</span><b>{{ detail.definition.grain || '待实施核验' }}</b></div>
              <div><span>更新周期</span><b>{{ detail.definition.update_cycle || '待实施核验' }}</b></div>
              <div><span>指标性质</span><b>{{ sourceKindLabel(detail.definition.source_kind) }}</b></div>
            </div>
          </el-tab-pane>
          <el-tab-pane :label="`实现与页面（${detail.bindings?.length || 0}）`">
            <el-alert v-if="!detail.bindings?.length" title="尚未建立页面实现绑定；这表示实现证据待核验，不直接认定功能缺失。" type="warning" :closable="false" show-icon />
            <div v-for="binding in detail.bindings || []" :key="binding.binding_id" class="binding-item">
              <div><b>{{ binding.display_name }}</b><code>{{ binding.page_path }}</code></div>
              <el-tag size="small" type="success" effect="plain">定义 {{ binding.definition_version }} / 实现 {{ binding.implementation_version }}</el-tag>
              <p>{{ binding.evidence_note }}</p>
              <el-button size="small" @click="goPage(binding.page_path)">查看使用页面</el-button>
            </div>
          </el-tab-pane>
          <el-tab-pane label="变更记录">
            <el-alert :title="detail.governance?.changeRule" type="info" :closable="false" show-icon />
            <AppTable
              :columns="displayHistoryColumns"
              storage-key="system:metric-display-history"
              :pagination="false"
              :data="detail.displayHistory || []"
              class="metric-history-table"
            >
              <template #empty><el-empty description="暂无展示配置变更记录" :image-size="70" /></template>
            </AppTable>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { useTablePagination } from '@/composables/useTablePagination'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as kpisApi from '@/api/admin/kpis'

const router = useRouter()
const activeTab = ref('catalog')
const activeCard = ref('')
const initialLoading = ref(true)
const listLoading = ref(false)
const pagesLoading = ref(false)
const loadError = ref('')
const exporting = ref(false)
const summary = reactive<any>({ domains: [] })
const rows = ref<any[]>([])
const pageRows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filters = reactive({ domain: '', definitionStatus: '', implementationStatus: '', keyword: '' })
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = reactive<any>({ definition: null, bindings: [], displayHistory: [], governance: null })

// 展示服务端提供的指标治理汇总，并关联既有筛选项。
const cards = computed(() => [
  {key:'all',label:'统一指标目录',value:summary.total || 0,help:'客户确认指标、范围背景量和历史兼容指标的统一目录。',action:'查看全部指标'},
  {key:'verified',label:'已实现并验证',value:summary.verified || 0,help:'已建立正式定义、计算实现和页面引用证据的指标。',action:'核查已发布口径'},
  {key:'pending',label:'待学校确认',value:summary.pendingConfirmation || 0,help:'已经形成建议口径，仍需学校确认边界和采用方式。',action:'形成学校确认清单'},
  {key:'inconsistent',label:'实现不一致',value:summary.inconsistent || 0,help:'正式发布指标中，定义版本与实现证据不一致的项目。',action:'优先处理差异'},
  {key:'retired',label:'已停用或迁移',value:summary.retired || 0,help:'不再进入正式页面，但保留历史版本和迁移证据。',action:'查看退出原因'},
])

const columns:AppTableColumn[] = [
  {key:'identity',label:'指标',required:true,region:'identity',fixed:'left',minWidth:210},
  {key:'domain',label:'业务域',minWidth:150},
  {key:'definition_status_label',label:'定义状态',minWidth:125},
  {key:'implementation_status_label',label:'实现状态',minWidth:145},
  {key:'formula',label:'计算逻辑摘要',minWidth:280,tooltip:true},
  {key:'management_value',label:'管理价值',minWidth:240,tooltip:true,defaultVisible:false},
  {key:'boundary',label:'边界与待确认',minWidth:240,tooltip:true,defaultVisible:false},
  {key:'data_source',label:'数据来源',minWidth:180,tooltip:true},
  {key:'grain',label:'统计粒度',minWidth:140,defaultVisible:false},
  {key:'page_count',label:'页面引用',minWidth:120},
  {key:'version',label:'版本',minWidth:85},
  {key:'technical_kpi_id',label:'技术标识',minWidth:170,tooltip:true,defaultVisible:false},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:110},
]
const pageColumns:AppTableColumn[] = [
  {key:'page_path',label:'使用页面',required:true,region:'identity',fixed:'left',minWidth:260},
  {key:'metric_count',label:'已绑定指标',minWidth:130},
  {key:'consistent_count',label:'版本一致',minWidth:120},
  {key:'issue_count',label:'待核查',minWidth:110},
  {key:'updated_at',label:'最近核验',minWidth:165},
  {key:'status',label:'核查结果',required:true,region:'action',fixed:'right',width:140},
]

// 根据已加载的指标定义显示名称和编号。
const detailTitle = computed(() => detail.definition
  ? `指标口径 · ${detail.definition.name}（${detail.definition.metric_id}）`
  : '指标口径')

// 用当前已应用筛选和分页生成请求参数，保留原字段名。
function queryString() {
  const p = new URLSearchParams({page:String(page.value),page_size:String(pageSize.value)})
  if (filters.domain) p.set('domain', filters.domain)
  if (filters.definitionStatus) p.set('definition_status', filters.definitionStatus)
  if (filters.implementationStatus) p.set('implementation_status', filters.implementationStatus)
  if (filters.keyword.trim()) p.set('keyword', filters.keyword.trim())
  return p.toString()
}
// 读取指标目录汇总，保持后端治理状态口径。
async function loadSummary() {
  const data:any = await kpisApi.getMetricSummary()
  Object.assign(summary, data || {})
}
// 按现有筛选和分页读取指标目录及总数。
async function loadList() {
  listLoading.value = true
  try {
    const data:any = await kpisApi.listMetrics(queryString())
    rows.value = data?.items || []
    total.value = data?.total || 0
  } finally { listLoading.value = false }
}
// 按需读取指标与页面实现的绑定列表。
async function loadPages() {
  pagesLoading.value = true
  try { pageRows.value = await kpisApi.listMetricPages() || [] }
  finally { pagesLoading.value = false }
}
// 加载指标汇总和列表，失败时保留统一重试入口。
async function reloadAll() {
  initialLoading.value = true
  loadError.value = ''
  try { await Promise.all([loadSummary(), loadList()]) }
  catch (error:any) { loadError.value = error?.message || '指标目录加载失败，请稍后重试。' }
  finally { initialLoading.value = false }
}
// 应用当前指标筛选并从第一页重新读取。
function search() { activeCard.value = ''; page.value = 1; loadList() }
// 恢复本页面既有筛选默认值后重新查询。
function resetFilters() {
  Object.assign(filters, {domain:'',definitionStatus:'',implementationStatus:'',keyword:''})
  activeCard.value = ''
  page.value = 1
  loadList()
}
// 将治理卡片映射到既有定义和实现状态条件。
function applyCard(key:string) {
  activeCard.value = key
  activeTab.value = 'catalog'
  Object.assign(filters, {domain:'',definitionStatus:'',implementationStatus:'',keyword:''})
  if (key === 'verified') filters.implementationStatus = 'verified'
  if (key === 'pending') filters.definitionStatus = 'pending_confirmation'
  if (key === 'inconsistent') filters.implementationStatus = 'mismatch'
  if (key === 'retired') filters.definitionStatus = 'deprecated'
  page.value = 1
  loadList()
}
// 公共分页事件只触发一次查询，沿用当前指标筛选。
function changePage(value: number) {
  if (value === page.value || listLoading.value) return
  page.value = value
  loadList()
}

// 切换指标页长后重置页码并重新读取。
function changePageSize(value:number) {
  if (value === pageSize.value) return
  pageSize.value = value
  page.value = 1
  loadList()
}
// 按当前标签页按需加载数据，保留既有加载时机。
function onTabChange(name:any) { if (name === 'pages' && !pageRows.value.length) loadPages() }
// 清理上一指标详情后加载定义、绑定及展示变更记录。
async function openDetail(row:any) {
  detailVisible.value = true
  detailLoading.value = true
  Object.assign(detail, {definition:null,bindings:[],displayHistory:[],governance:null})
  try { Object.assign(detail, await kpisApi.getMetric(row.metric_id)) }
  finally { detailLoading.value = false }
}
// 关闭指标详情并跳转到其绑定的既有页面。
function goPage(path:string) { detailVisible.value = false; router.push(path) }
// 按定义状态展示标签，不修改指标发布状态。
function definitionTag(status:string):any {
  return ({published:'success',pending_confirmation:'warning',context:'info',deprecated:'info'} as any)[status] || 'info'
}
// 按实现证据状态展示标签，不代替后端核验。
function implementationTag(status:string):any {
  return ({verified:'success',unverified:'warning',mismatch:'danger',retired:'info'} as any)[status] || 'info'
}
// 按既有指标性质映射显示来源类别。
function sourceKindLabel(kind:string) {
  return ({formal:'正式管理指标',context:'分析范围背景',legacy:'历史兼容',definition:'候选定义'} as any)[kind] || kind
}
// 使用当前筛选导出既有 CSV，保留身份请求头及文件名。
async function exportCatalog() {
  exporting.value = true
  try {
    const p = new URLSearchParams()
    if (filters.domain) p.set('domain', filters.domain)
    if (filters.definitionStatus) p.set('definition_status', filters.definitionStatus)
    if (filters.implementationStatus) p.set('implementation_status', filters.implementationStatus)
    if (filters.keyword.trim()) p.set('keyword', filters.keyword.trim())
    const response = await kpisApi.exportMetricCatalog(p)
    if (!response.ok) throw new Error('导出失败')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '指标口径确认清单.csv'
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('指标确认清单已导出')
  } catch (error:any) { ElMessage.error(error?.message || '导出失败') }
  finally { exporting.value = false }
}

// 进入页面时沿用原初始化与路由参数恢复流程。
onMounted(reloadAll)
// 列定义只负责展示；单元格内容和业务操作沿用原页面。
const displayHistoryColumns: AppTableColumn[] = [
  { key: "changed_at", label: "时间", minWidth: 160 },
  { key: "changed_by", label: "操作人", minWidth: 100 },
  { key: "change_reason", label: "展示配置变更原因", minWidth: 220 },
]

// 各标签页与抽屉独立持有分页状态，保留全量接口和原业务筛选。
const pageTable = useTablePagination(() => pageRows.value)
</script>

<style scoped lang="scss">
// 页面区域、状态修饰与后代元素按相邻规则分组，保留原级联和弹窗作用域。
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.catalog-context {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 24px;
  margin: 12px 0;
  padding: 11px 14px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
  color: var(--sa-muted);
  font-size: 12px;

  span {
    display: flex;
    gap: 7px;
  }

  b {
    color: #334155;
  }
}

.loading-card {
  margin-top: 12px;
}

.metric-kpis {
  display: grid;
  grid-template-columns: repeat(5,minmax(0,1fr));
  gap: 12px;
  margin: 14px 0;
}

.metric-kpi {
  padding: 14px;
  border: 1px solid var(--sa-border-2);
  border-radius: 12px;
  background: #fff;
  text-align: left;
  cursor: pointer;

  &:hover, &.active {
    border-color: #818cf8;
    box-shadow: 0 0 0 2px rgba(99,102,241,.08);
  }

  span, small {
    display: block;
    color: var(--sa-muted);
  }

  span {
    font-size: 12px;
  }

  i {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 15px;
    height: 15px;
    border: 1px solid #cbd5e1;
    border-radius: 50%;
    font-size: 10px;
    font-style: normal;
  }

  b {
    display: block;
    margin: 7px 0;
    color: #0f172a;
    font-size: 25px;
  }

  small {
    font-size: 11px;
  }
}

.metric-tabs {
  margin-top: 8px;
}

.catalog-hint {
  margin-bottom: 12px;
}

.catalog-table {
  :deep(.app-table__toolbar) {
    flex-wrap: wrap;
  }

  :deep(.app-table__extra) {
    flex: 0 1 auto;
  }

  :deep(.app-table__tools) {
    margin-left: auto;
  }
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sa-button-gap);
  align-items: center;

  .el-input, .el-select {
    flex: 0 0 auto;
    max-width: 100%;
    min-width: 0;
  }

  .el-select {
    width: 140px;
  }

  .el-select:nth-child(3) {
    width: 160px;
  }

  .el-input {
    width: 260px;
  }

  .el-button + .el-button {
    margin-left: 0;
  }
}

.updating-bar {
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--sa-track);
  color: #4338ca;
  font-size: 12px;
}

.table-card {
  padding: 14px;
}

.metric-identity {
  display: flex;
  flex-direction: column;
  gap: 3px;

  // 名称与编号共用原详情入口，以主题链接色标识可点击内容。
  b, span {
    color: var(--sa-primary);
  }

  span {
    font-size: 11px;
  }

  &:hover {
    b, span {
      text-decoration: underline;
    }
  }
}

:deep(.metric-row) {
  cursor: pointer;
}

:deep(.metric-row:hover td.el-table__cell) {
  background: #f5f7ff !important;
}

.page-table {
  margin-top: 12px;
}

.page-table code,.binding-item code {
  color: #475569;
  font-family: ui-monospace,SFMono-Regular,Consolas,monospace;
}

.governance-grid {
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  gap: 14px;

  section {
    padding: 18px;
  }
}

.governance-grid h3,.migration-note h3 {
  margin: 0 0 9px;
  color: #0f172a;
  font-size: 16px;
}

.governance-grid p,.migration-note p {
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.governance-grid {

  ul {
    margin: 10px 0 0;
    padding-left: 19px;
    color: var(--sa-muted);
    font-size: 12px;
    line-height: 1.8;
  }
}

.migration-note {
  margin-top: 14px;
  padding: 18px;
}

.drawer-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;

  &>span {
    margin-left: auto;
    color: var(--sa-muted);
    font-size: 12px;
  }
}

.definition-block {
  margin-bottom: 12px;
  padding: 14px;
  border: 1px solid var(--sa-border-2);
  border-radius: 10px;
  background: var(--sa-bg);

  &.important {
    border-color: #c7d2fe;
    background: #f8faff;
  }
}

.definition-block span,.detail-grid span {
  display: block;
  color: var(--sa-muted);
  font-size: 11px;
}

.definition-block {

  p {
    margin: 7px 0 0;
    color: #334155;
    line-height: 1.75;
  }
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;

  &>div {
    padding: 12px;
    border: 1px solid var(--sa-border-2);
    border-radius: 9px;
  }

  b {
    display: block;
    margin-top: 5px;
    color: var(--sa-text);
    font-size: 13px;
  }
}

.binding-item {
  margin-bottom: 10px;
  padding: 13px;
  border: 1px solid var(--sa-border-2);
  border-radius: 10px;

  &>div {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &>.el-tag {
    margin-top: 8px;
  }

  p {
    color: var(--sa-muted);
    font-size: 12px;
    line-height: 1.6;
  }
}

@media (max-width:1250px) {
  .metric-kpis {
    grid-template-columns: repeat(3,minmax(0,1fr));
  }

  .governance-grid {
    grid-template-columns: 1fr;
  }

}

@media (max-width:850px) {
  .metric-kpis,.detail-grid {
    grid-template-columns: 1fr;
  }

  .page-head {
    align-items: stretch;
    flex-direction: column;
  }

}

// 静态控件尺寸与局部布局由 class 管理，动态样式保留在原数据绑定中。
.metric-history-table {
  margin-top: 12px;
}
</style>
