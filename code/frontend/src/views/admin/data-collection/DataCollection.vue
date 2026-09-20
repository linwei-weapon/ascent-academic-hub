<!-- 数据采集监控：系统管理模块，沿用既有接口、治理操作与权限边界。 -->
<template>
  <div class="collection-page">
    <div class="page-head">
      <div>
        <h2 class="sa-page-title">数据采集监控</h2>
        <p class="sa-page-sub">判断分析数据是否已接入、是否及时更新、哪些问题影响业务页面；源数据仍在学校业务系统核查修订。</p>
      </div>
      <div class="head-actions sa-button-row">
        <el-button :loading="exporting" @click="exportChecklist">导出接入核验清单</el-button>
        <el-button v-if="overview.canTrigger" type="primary" plain @click="operationVisible=true">运维操作</el-button>
        <el-button :loading="refreshing" @click="reloadAll">刷新状态</el-button>
      </div>
    </div>

    <div class="context-strip">
      <span><b>目录版本</b>{{ overview.catalogVersion || '—' }}</span>
      <span><b>最近接入</b>{{ formatDateTime(overview.lastIngestedAt) }}</span>
      <span><b>治理边界</b>只监控接入与运行证据，不维护教务主数据</span>
    </div>

    <template v-if="initialLoading">
      <el-alert title="正在核对数据源、最近批次、运行记录和下游影响，预计需要数秒…" type="info" :closable="false" show-icon />
      <div class="sa-card loading-card"><el-skeleton :rows="10" animated /></div>
    </template>
    <template v-else>
      <el-alert v-if="pageError" :title="pageError" type="error" :closable="false" show-icon>
        <template #default><el-button size="small" @click="reloadAll">重新加载</el-button></template>
      </el-alert>

      <div class="status-cards">
        <button v-for="card in cards" :key="card.key" type="button" class="status-card"
          :class="{active:activeCard===card.key, danger:card.tone==='danger', warning:card.tone==='warning'}"
          @click="applyCard(card.key)">
          <span>{{ card.label }} <el-tooltip :content="card.help"><i>?</i></el-tooltip></span>
          <b>{{ card.value }}</b>
          <small>{{ card.action }}</small>
        </button>
      </div>

      <section class="sa-card priority-panel">
        <div class="section-title">
          <div><h3>优先处理事项</h3><p>这里只呈现会影响数据可信度或业务页面使用的事项，不把“已接入”误报为失败。</p></div>
          <el-button v-if="activeCard" link type="primary" @click="clearCard">清除卡片筛选</el-button>
        </div>
        <div v-if="overview.priorities?.length" class="priority-list">
          <button v-for="issue in overview.priorities" :key="issue.issueKey" type="button"
            class="priority-item" @click="openSource(issue.sourceCode)">
            <span class="severity-dot" :class="issue.severity"></span>
            <span class="priority-main"><b>{{ issue.title }}</b><small>{{ issue.reason }}</small></span>
            <span class="priority-impact"><small>影响</small>{{ issue.impact }}</span>
            <span class="priority-action">查看证据 →</span>
          </button>
        </div>
        <el-empty v-else description="当前没有需要优先核查的接入事项" :image-size="70" />
      </section>

      <el-tabs v-model="activeTab" class="collection-tabs" @tab-change="onTabChange">
        <el-tab-pane label="数据源接入态势" name="sources">
          <div class="sa-card table-card" v-loading="sourceLoading && !!sources.length" element-loading-text="正在更新数据源状态…">
            <AppTable
              show-density
              show-column-settings
              :columns="sourceColumns"
              :data="sources"
              storage-key="system:data-sources"
              :max-business-columns="7"
              :config-version="1"
              :page-size="sourcePageSize"
              stripe
              empty-text="当前条件下没有数据源"
              @page-size-change="changeSourcePageSize"
              @row-click="row=>openSource(row.sourceCode)"
              row-class-name="clickable-row"
              :page="sourcePage"
              :total="sourceTotal"
              :loading="sourceLoading"
              @page-change="loadSources"
            >
              <!-- 筛选与提示复用工具栏左侧区域，右侧保留表格显示设置。 -->
              <template #toolbar>
                <div class="filters sa-button-row">
                  <el-select size="small" v-model="draftFilters.domain" clearable placeholder="全部数据域">
                    <el-option v-for="item in overview.domains || []" :key="item.label"
                      :label="`${item.label}（${item.count}）`" :value="domainCode(item.label)" />
                  </el-select>
                  <el-select size="small" v-model="draftFilters.status" clearable placeholder="全部状态">
                    <el-option label="已接入" value="connected" />
                    <el-option label="尚未接入" value="missing" />
                    <el-option label="超过更新周期" value="overdue" />
                    <el-option label="最近处理失败" value="failed" />
                    <el-option label="正在更新" value="running" />
                    <el-option label="有待核验项" value="attention" />
                  </el-select>
                  <el-input size="small" v-model="draftFilters.keyword" clearable
                    placeholder="搜索数据源、来源系统或影响模块" @keyup.enter="applyFilters" />
                  <el-button size="small" type="primary" @click="applyFilters">应用筛选</el-button>
                  <el-button size="small" @click="resetFilters">重置</el-button>
                  <span v-if="filterDirty" class="filter-dirty">筛选条件尚未应用</span>
                </div>
                <div v-if="sourceLoading && sources.length" class="updating-bar">正在按新条件更新，当前结果暂时保留…</div>
              </template>
              <template #col-source="{row}">
                <div class="source-identity"><b>{{ row.sourceName }}</b><span>{{ row.sourceSystem }}</span></div>
              </template>
              <template #col-access="{row}">
                <el-tag size="small" effect="plain" :type="accessTag(row.accessStatus)">{{ row.accessStatusLabel }}</el-tag>
              </template>
              <template #col-validation="{row}">
                <el-tag size="small" effect="plain" :type="validationTag(row.validationStatus)">{{ row.validationStatusLabel }}</el-tag>
                <small v-if="row.attentionCount" class="attention-count">{{ row.attentionCount }}项</small>
              </template>
              <template #col-lastIngestedAt="{row}">{{ formatDateTime(row.lastIngestedAt) }}</template>
              <template #col-sourceRows="{row}">{{ formatNumber(row.sourceRows) }}</template>
              <template #col-downstream="{row}">{{ (row.downstreamModules || []).join('、') }}</template>
              <template #col-action><el-button link type="primary">核查</el-button></template>
            </AppTable>
            <div class="pager">
              <span>接入状态与质量校验状态分开呈现。</span>

            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="运行与异常" name="runs">
          <div class="sa-card table-card" v-loading="runLoading">
            <el-alert class="table-note run-note" title="运行记录用于核查某次处理读了哪些批次、生成了多少结果以及哪些校验需要关注；不会在主表直接展示原始JSON。" type="info" :closable="false" show-icon />
            <AppTable
              show-density
              show-column-settings
              :columns="runColumns"
              :data="runs"
              storage-key="system:etl-runs"
              :max-business-columns="7"
              :config-version="1"
              :page-size="runPageSize"
              stripe
              empty-text="尚无运行记录"
              @page-size-change="changeRunPageSize"
              @row-click="row=>openRun(row.run_id)"
              row-class-name="clickable-row"
              :page="runPage"
              :total="runTotal"
              :loading="runLoading"
              @page-change="loadRuns"
            >
              <template #toolbar>
                <div class="run-filters">
                  <el-select size="small" v-model="runFilters.task" clearable placeholder="全部任务" @change="loadRuns(1)">
                    <el-option v-for="task in overview.tasks || []" :key="task.task" :label="task.name" :value="task.task" />
                  </el-select>
                  <el-select size="small" v-model="runFilters.status" clearable placeholder="全部状态" @change="loadRuns(1)">
                    <el-option label="成功" value="success" />
                    <el-option label="失败" value="failed" />
                    <el-option label="执行中" value="running" />
                  </el-select>
                </div>
              </template>
              <template #col-task="{row}">
                <div class="source-identity"><b>{{ row.taskName }}</b><span>运行 #{{ row.run_id }}</span></div>
              </template>
              <template #col-sources="{row}">{{ row.sourceNames?.length ? row.sourceNames.join('、') : '尚未建立批次关联' }}</template>
              <template #col-status="{row}"><el-tag size="small" effect="plain" :type="runTag(row.status)">{{ runStatusLabel(row.status) }}</el-tag></template>
              <template #col-started_at="{row}">{{ formatDateTime(row.started_at) }}</template>
              <template #col-duration_ms="{row}">{{ formatDuration(row.duration_ms) }}</template>
              <template #col-rows_written="{row}">{{ formatNumber(row.rows_written) }}</template>
              <template #col-action><el-button link type="primary">详情</el-button></template>
            </AppTable>
            <div class="pager">
              <span>失败原因和技术证据在详情中查看。</span>

            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="交付接入清单" name="checklist">
          <div class="sa-card table-card" v-loading="checklistLoading">
            <AppTable
              show-density
              show-column-settings
              :columns="checklistColumns"
              :data="checklistTable.rows"
              storage-key="system:data-source-checklist"
              :max-business-columns="6"
              :config-version="1"
              stripe
              :page="checklistTable.page"
              :page-size="checklistTable.pageSize"
              :total="checklistTable.total"
              :loading="checklistLoading"
              @page-change="checklistTable.changePage"
              @page-size-change="checklistTable.changePageSize"
            >
              <template #toolbar>
                <el-alert class="table-note" title="该清单用于学校接口准备和实施核验，不在本页配置字段映射或修改学校主数据。" type="info" :closable="false" show-icon />
              </template>
              <template #col-source="{row}"><div class="source-identity"><b>{{ row.sourceName }}</b><span>{{ row.domainName }}</span></div></template>
              <template #col-status="{row}"><el-tag size="small" effect="plain" :type="accessTag(row.accessStatus)">{{ row.accessStatusLabel }}</el-tag></template>
              <template #col-downstream="{row}">{{ (row.downstreamModules || []).join('、') }}</template>
              <template #col-action="{row}"><el-button link type="primary" @click.stop="openSource(row.sourceCode)">证据</el-button></template>
            </AppTable>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-drawer v-model="sourceDrawerVisible" size="760px" :title="sourceDrawerTitle" destroy-on-close>
      <el-skeleton v-if="sourceDetailLoading" :rows="11" animated />
      <template v-else-if="sourceDetail.source">
        <div class="drawer-tags">
          <el-tag effect="plain" :type="accessTag(sourceDetail.source.accessStatus)">{{ sourceDetail.source.accessStatusLabel }}</el-tag>
          <el-tag effect="plain" :type="validationTag(sourceDetail.source.validationStatus)">{{ sourceDetail.source.validationStatusLabel }}</el-tag>
          <span>最近接入 {{ formatDateTime(sourceDetail.source.lastIngestedAt) }}</span>
        </div>
        <el-tabs>
          <el-tab-pane label="当前状态">
            <div class="detail-metrics">
              <div><span>源文件行数</span><b>{{ formatNumber(sourceDetail.source.sourceRows) }}</b></div>
              <div><span>写入关系/事实数</span><b>{{ formatNumber(sourceDetail.source.loadedRows) }}</b></div>
              <div><span>待核验记录</span><b :class="{warn:sourceDetail.source.attentionCount}">{{ sourceDetail.source.attentionCount || 0 }}</b></div>
              <div><span>更新边界</span><b>{{ sourceDetail.source.updateCycle }}</b></div>
            </div>
            <section class="definition-block"><span>管理用途</span><p>{{ sourceDetail.source.managementUse }}</p></section>
            <section class="definition-block"><span>下游影响</span><p>{{ sourceDetail.source.downstreamModules.join('、') }}</p></section>
            <section class="definition-block"><span>计数边界</span><p>{{ sourceDetail.governance?.countBoundary }}</p></section>
          </el-tab-pane>
          <el-tab-pane :label="`最近批次（${sourceDetail.batches?.length || 0}）`">
            <AppTable
              show-density
              show-column-settings
              :columns="batchColumns"
              :data="batchTable.rows"
              :storage-key="`system:source-batches:${sourceDetail.source.sourceCode}`"
              :max-business-columns="6"
              :config-version="1"
              stripe
              :page="batchTable.page"
              :page-size="batchTable.pageSize"
              :total="batchTable.total"
              :loading="sourceDetailLoading"
              @page-change="batchTable.changePage"
              @page-size-change="batchTable.changePageSize"
            >
              <template #col-ingested_at="{row}">{{ formatDateTime(row.ingested_at) }}</template>
              <template #col-row_count="{row}">{{ formatNumber(row.row_count) }}</template>
              <template #col-accepted_count="{row}">{{ formatNumber(row.accepted_count) }}</template>
              <template #col-qualityLabel="{row}"><el-tag size="small" effect="plain" :type="row.quality_status==='warning'?'warning':'success'">{{ row.qualityLabel }}</el-tag></template>
            </AppTable>
          </el-tab-pane>
          <el-tab-pane label="校验与映射">
            <el-alert v-if="!sourceDetail.mappings?.length && !sourceDetail.roomQuality"
              title="当前没有待核验的代码映射或源记录校验事项。" type="success" :closable="false" show-icon />
            <div v-if="sourceDetail.roomQuality" class="quality-grid">
              <div><span>已观测教室</span><b>{{ formatNumber(sourceDetail.roomQuality.observed_rooms) }}</b></div>
              <div><span>楼宇待匹配记录</span><b>{{ formatNumber(sourceDetail.roomQuality.pending_building_rows) }}</b></div>
              <div><span>时空重叠记录</span><b>{{ formatNumber(sourceDetail.roomQuality.overlap_rows) }}</b></div>
              <div><span>已脱敏活动记录</span><b>{{ formatNumber(sourceDetail.roomQuality.pii_redacted_rows) }}</b></div>
            </div>
            <div v-for="item in sourceDetail.mappings || []" :key="`${item.domain}:${item.source_code}`" class="evidence-item">
              <b>{{ item.source_code }}</b><span>{{ item.note }}</span><el-tag size="small" type="warning" effect="plain">待源系统核查</el-tag>
            </div>
            <el-alert class="boundary-note" :title="sourceDetail.governance?.correctionBoundary" type="info" :closable="false" show-icon />
          </el-tab-pane>
          <el-tab-pane :label="`关联运行（${sourceDetail.runs?.length || 0}）`">
            <AppTable
              show-density
              show-column-settings
              :columns="sourceRunColumns"
              :data="sourceRunTable.rows"
              :storage-key="`system:source-runs:${sourceDetail.source.sourceCode}`"
              :max-business-columns="5"
              :config-version="1"
              stripe
              @row-click="row=>openRun(row.run_id)"
              row-class-name="clickable-row"
              :page="sourceRunTable.page"
              :page-size="sourceRunTable.pageSize"
              :total="sourceRunTable.total"
              :loading="sourceDetailLoading"
              @page-change="sourceRunTable.changePage"
              @page-size-change="sourceRunTable.changePageSize"
            >
              <template #col-taskName="{row}">{{ row.taskName }}</template>
              <template #col-status="{row}"><el-tag size="small" effect="plain" :type="runTag(row.status)">{{ runStatusLabel(row.status) }}</el-tag></template>
              <template #col-started_at="{row}">{{ formatDateTime(row.started_at) }}</template>
              <template #col-duration_ms="{row}">{{ formatDuration(row.duration_ms) }}</template>
              <template #col-action><el-button link type="primary">详情</el-button></template>
            </AppTable>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>

    <el-drawer v-model="runDrawerVisible" size="760px" :title="runDrawerTitle" destroy-on-close>
      <el-skeleton v-if="runDetailLoading" :rows="11" animated />
      <template v-else-if="runDetail.run">
        <div class="drawer-tags">
          <el-tag effect="plain" :type="runTag(runDetail.run.status)">{{ runStatusLabel(runDetail.run.status) }}</el-tag>
          <span>开始 {{ formatDateTime(runDetail.run.started_at) }}</span>
          <span>耗时 {{ formatDuration(runDetail.run.duration_ms) }}</span>
        </div>
        <el-alert v-if="runDetail.run.errorSummary" :title="runDetail.run.errorSummary" type="error" :closable="false" show-icon />
        <el-tabs>
          <el-tab-pane label="运行结论">
            <div class="check-grid">
              <div v-for="item in runDetail.checks || []" :key="item.key" :class="{warn:item.status==='warning'}">
                <span>{{ item.label }}</span><b>{{ displayValue(item.value) }}</b>
              </div>
            </div>
            <el-empty v-if="!runDetail.checks?.length" description="本次运行没有结构化校验明细" :image-size="70" />
          </el-tab-pane>
          <el-tab-pane :label="`输入批次（${runDetail.batches?.length || 0}）`">
            <AppTable
              show-density
              show-column-settings
              :columns="runBatchColumns"
              :data="runBatchTable.rows"
              :storage-key="`system:run-batches:${runDetail.run.run_id}`"
              :max-business-columns="5"
              :config-version="1"
              stripe
              :page="runBatchTable.page"
              :page-size="runBatchTable.pageSize"
              :total="runBatchTable.total"
              :loading="runDetailLoading"
              @page-change="runBatchTable.changePage"
              @page-size-change="runBatchTable.changePageSize"
            >
              <template #col-ingested_at="{row}">{{ formatDateTime(row.ingested_at) }}</template>
              <template #col-row_count="{row}">{{ formatNumber(row.row_count) }}</template>
              <template #col-accepted_count="{row}">{{ formatNumber(row.accepted_count) }}</template>
            </AppTable>
          </el-tab-pane>
          <el-tab-pane label="技术证据">
            <el-alert :title="runDetail.boundary" type="info" :closable="false" show-icon />
            <pre class="technical-pre">{{ JSON.stringify(runDetail.technicalEvidence, null, 2) }}</pre>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>

    <el-drawer v-model="operationVisible" size="560px" title="受控运维操作" destroy-on-close>
      <el-alert title="正式调度仍由学校数据交换平台执行；这里只允许授权人员重跑白名单任务，不接受任意脚本或参数。" type="warning" :closable="false" show-icon />
      <div class="task-list">
        <label v-for="task in overview.tasks || []" :key="task.task" :class="{selected:selectedTask===task.task}">
          <input v-model="selectedTask" type="radio" :value="task.task" />
          <span><b>{{ task.name }}</b><small>{{ task.description }}</small><em v-if="task.needsSourceFiles">依赖已部署的数据源文件</em></span>
        </label>
      </div>
      <el-alert v-if="triggerResult" :title="triggerResult.title" :description="triggerResult.description"
        :type="triggerResult.type" :closable="false" show-icon />
      <template #footer>
        <el-button @click="operationVisible=false">关闭</el-button>
        <el-button type="primary" :disabled="!selectedTask" :loading="triggering" @click="triggerTask">确认重跑</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { formatDateTime } from '@/utils/dateTime'
import { useTablePagination } from '@/composables/useTablePagination'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as dataCollectionApi from '@/api/admin/dataCollection'

const initialLoading = ref(true)
const refreshing = ref(false)
const pageError = ref('')
const exporting = ref(false)
const activeTab = ref('sources')
const activeCard = ref('')
const overview = reactive<any>({ priorities: [], domains: [], tasks: [] })

const sources = ref<any[]>([])
const sourceLoading = ref(false)
const sourceTotal = ref(0)
const sourcePage = ref(1)
const sourcePageSize = ref(20)
const draftFilters = reactive({ domain: '', status: '', keyword: '' })
const appliedFilters = reactive({ domain: '', status: '', keyword: '' })
// 比较草稿与已应用条件，提示筛选尚未用于当前结果。
const filterDirty = computed(() => JSON.stringify(draftFilters) !== JSON.stringify(appliedFilters))

const runs = ref<any[]>([])
const runLoading = ref(false)
const runLoaded = ref(false)
const runTotal = ref(0)
const runPage = ref(1)
const runPageSize = ref(20)
const runFilters = reactive({ task: '', status: '' })

const checklistRows = ref<any[]>([])
const checklistLoading = ref(false)
const checklistLoaded = ref(false)

const sourceDrawerVisible = ref(false)
const sourceDetailLoading = ref(false)
const sourceDetail = reactive<any>({ source: null, batches: [], mappings: [], runs: [] })
const runDrawerVisible = ref(false)
const runDetailLoading = ref(false)
const runDetail = reactive<any>({ run: null, batches: [], checks: [] })

const operationVisible = ref(false)
const selectedTask = ref('')
const triggering = ref(false)
const triggerResult = ref<any>(null)
let pollTimer: number | undefined
let pollCount = 0

// 根据采集总览生成状态卡片，统计口径保持由后端提供。
const cards = computed(() => [
  {key:'missing', label:'数据源接入', value:`${overview.connectedSources || 0}/${overview.expectedSources || 0}`,
    help:'已形成可用批次的数据源数÷接入目录中应接入的数据源数。', action:'核查尚未接入数据', tone:'normal'},
  {key:'overdue', label:'超过更新周期', value:overview.overdueSources || 0,
    help:'距最近成功接入时间超过目录约定更新边界的数据源数。', action:'核查数据时效', tone:overview.overdueSources?'warning':'normal'},
  {key:'unstable', label:'失败或执行中', value:overview.failedOrRunningTasks || 0,
    help:'最近一次处理失败或仍处于执行中的数据源数。', action:'核查运行状态', tone:overview.failedOrRunningTasks?'danger':'normal'},
  {key:'attention', label:'待核验记录', value:overview.attentionItems || 0,
    help:'代码映射、空间匹配、结构校验等需要反馈源系统核查的记录数。', action:'查看问题证据', tone:overview.attentionItems?'warning':'normal'},
])

const sourceColumns:AppTableColumn[] = [
  {key:'source',label:'数据源',required:true,region:'identity',fixed:'left',minWidth:220},
  {key:'domainName',label:'数据域',minWidth:145},
  {key:'access',label:'接入状态',minWidth:125},
  {key:'validation',label:'校验状态',minWidth:145},
  {key:'lastIngestedAt',label:'最近接入',minWidth:165},
  {key:'sourceRows',label:'源行数',minWidth:110},
  {key:'updateCycle',label:'更新周期',minWidth:150,defaultVisible:false},
  {key:'sourceFile',label:'最近文件/接口',minWidth:180,tooltip:true,defaultVisible:false},
  {key:'downstream',label:'影响模块',minWidth:240,tooltip:true},
  {key:'managementUse',label:'管理用途',minWidth:240,tooltip:true,defaultVisible:false},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:90},
]
const runColumns:AppTableColumn[] = [
  {key:'task',label:'任务',required:true,region:'identity',fixed:'left',minWidth:220},
  {key:'sources',label:'输入数据源',minWidth:240,tooltip:true},
  {key:'status',label:'状态',minWidth:100},
  {key:'started_at',label:'开始时间',minWidth:165},
  {key:'duration_ms',label:'耗时',minWidth:105},
  {key:'rows_written',label:'生成记录',minWidth:110},
  {key:'triggered_by',label:'触发方式/人员',minWidth:130},
  {key:'errorSummary',label:'失败摘要',minWidth:220,tooltip:true,defaultVisible:false},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:90},
]
const checklistColumns:AppTableColumn[] = [
  {key:'source',label:'数据源',required:true,region:'identity',fixed:'left',minWidth:220},
  {key:'sourceSystem',label:'来源系统',minWidth:170},
  {key:'deliveryMode',label:'交付方式',minWidth:120},
  {key:'requiredFields',label:'关键字段',minWidth:300,tooltip:true},
  {key:'updateCycle',label:'建议更新周期',minWidth:170},
  {key:'downstream',label:'影响模块',minWidth:240,tooltip:true},
  {key:'status',label:'当前状态',minWidth:125},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:90},
]
const batchColumns:AppTableColumn[] = [
  {key:'source_file',label:'文件/接口',required:true,region:'identity',minWidth:190,tooltip:true},
  {key:'ingested_at',label:'接入时间',minWidth:165},
  {key:'row_count',label:'源行数',minWidth:100},
  {key:'accepted_count',label:'写入记录',minWidth:105},
  {key:'qualityLabel',label:'基础校验',minWidth:140},
]
const sourceRunColumns:AppTableColumn[] = [
  {key:'taskName',label:'运行任务',required:true,region:'identity',minWidth:220},
  {key:'status',label:'状态',minWidth:100},
  {key:'started_at',label:'开始时间',minWidth:165},
  {key:'duration_ms',label:'耗时',minWidth:100},
  {key:'rows_written',label:'生成记录',minWidth:110},
  {key:'action',label:'操作',required:true,region:'action',fixed:'right',width:80},
]
const runBatchColumns:AppTableColumn[] = [
  {key:'source_name',label:'数据源',required:true,region:'identity',minWidth:180},
  {key:'source_file',label:'文件/接口',minWidth:180,tooltip:true},
  {key:'ingested_at',label:'接入时间',minWidth:165},
  {key:'row_count',label:'源行数',minWidth:100},
  {key:'accepted_count',label:'写入记录',minWidth:105},
]

// 从当前数据源详情生成抽屉标题。
const sourceDrawerTitle = computed(() => sourceDetail.source ? `数据源核查 · ${sourceDetail.source.sourceName}` : '数据源核查')
// 使用当前运行记录标识生成详情标题。
const runDrawerTitle = computed(() => runDetail.run ? `运行详情 · ${runDetail.run.taskName} #${runDetail.run.run_id}` : '运行详情')

// 将页面业务域选项映射为已有接口使用的编码。
function domainCode(label:string) {
  return ({'基础主数据':'master','学籍与培养方案':'student','成绩与课程结果':'achievement','教学任务与师资':'teaching','教室占用':'resource'} as any)[label] || label
}
// 按既有显示规则格式化数量，不重算接口统计。
function formatNumber(value:any) { return value == null ? '—' : Number(value).toLocaleString('zh-CN') }
// 将任务耗时转为既有展示单位，保留空值处理。
function formatDuration(ms:any) {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  const sec = ms/1000
  return sec < 60 ? `${sec.toFixed(1)}秒` : `${Math.floor(sec/60)}分${Math.round(sec%60)}秒`
}
// 按既有展示约定格式化详情值，不改变数据内容。
function displayValue(value:any) {
  if (Array.isArray(value)) return value.length ? value.join('、') : '0'
  if (value && typeof value==='object') return JSON.stringify(value)
  return value == null || value==='' ? '—' : String(value)
}
// 将后端接入状态映射为页面标签样式。
function accessTag(status:string) { return status==='failed'?'danger':status==='overdue'?'warning':status==='running'?'warning':status==='missing'?'info':'success' }
// 将校验状态映射为现有提示样式。
function validationTag(status:string) { return status==='failed'?'danger':status==='warning'?'warning':status==='passed'?'success':'info' }
// 按后端任务状态选择标签样式。
function runTag(status:string) { return status==='failed'?'danger':status==='running'?'warning':'success' }
// 保留现有运行状态的中文展示映射。
function runStatusLabel(status:string) { return ({success:'成功',failed:'失败',running:'执行中'} as any)[status] || status }

// 读取采集状态总览与当前学校上下文。
async function loadOverview() {
  const data = await dataCollectionApi.getCollectionOverview()
  Object.assign(overview, data)
}
// 将数据源筛选及目标分页编码为现有请求字段。
function sourceQuery(page=sourcePage.value, pageSize=sourcePageSize.value) {
  const qs = new URLSearchParams({page:String(page),page_size:String(pageSize)})
  if (appliedFilters.domain) qs.set('domain',appliedFilters.domain)
  if (appliedFilters.status) qs.set('status',appliedFilters.status)
  if (appliedFilters.keyword) qs.set('keyword',appliedFilters.keyword)
  return qs.toString()
}
// 按已应用条件加载数据源列表，保留原分页和加载状态。
async function loadSources(page=1) {
  sourcePage.value=page
  sourceLoading.value=true
  try {
    const data=await dataCollectionApi.listCollectionSources(sourceQuery(page))
    sources.value=data.sources || []; sourceTotal.value=data.total || 0
  } finally { sourceLoading.value=false }
}
// 读取任务运行记录并同步服务端总数。
async function loadRuns(page=1) {
  runPage.value=page; runLoading.value=true
  try {
    const qs=new URLSearchParams({page:String(page),page_size:String(runPageSize.value)})
    if (runFilters.task) qs.set('task',runFilters.task)
    if (runFilters.status) qs.set('status',runFilters.status)
    const data=await dataCollectionApi.listCollectionRuns(qs)
    runs.value=data.runs || []; runTotal.value=data.total || 0; runLoaded.value=true
  } finally { runLoading.value=false }
}
// 按原接口范围读取确认清单，不扩大数据读取边界。
async function loadChecklist() {
  checklistLoading.value=true
  try {
    const data=await dataCollectionApi.getCollectionChecklist()
    checklistRows.value=data.sources || []; checklistLoaded.value=true
  } finally { checklistLoading.value=false }
}
// 并行更新页面需要的采集视图，并保留整体错误反馈。
async function reloadAll() {
  refreshing.value=true; pageError.value=''
  try {
    const jobs:any[]=[loadOverview(),loadSources(sourcePage.value)]
    if (runLoaded.value) jobs.push(loadRuns(runPage.value))
    if (checklistLoaded.value) jobs.push(loadChecklist())
    await Promise.all(jobs)
  } catch (err:any) { pageError.value=err?.message || '数据采集状态加载失败' }
  finally { refreshing.value=false; initialLoading.value=false }
}
// 将草稿筛选应用到结果查询，并沿用原分页重置规则。
function applyFilters() {
  Object.assign(appliedFilters,draftFilters); activeCard.value=''
  loadSources(1)
}
// 恢复本页面既有筛选默认值后重新查询。
function resetFilters() {
  Object.assign(draftFilters,{domain:'',status:'',keyword:''})
  Object.assign(appliedFilters,draftFilters); activeCard.value=''
  loadSources(1)
}
// 把状态卡片应用到既有筛选及标签页。
function applyCard(key:string) {
  activeTab.value='sources'; activeCard.value=activeCard.value===key?'':key
  Object.assign(draftFilters,{domain:'',status:activeCard.value || '',keyword:''})
  Object.assign(appliedFilters,draftFilters)
  loadSources(1)
}
// 清除状态卡片条件并恢复原查询流程。
function clearCard() { activeCard.value=''; draftFilters.status=''; appliedFilters.status=''; loadSources(1) }
// 调整数据源页长后按既有规则重新加载列表。
function changeSourcePageSize(value:number) { sourcePageSize.value=value; loadSources(1) }
// 调整运行记录页长后按既有规则重新加载列表。
function changeRunPageSize(value:number) { runPageSize.value=value; loadRuns(1) }
// 按当前标签页按需加载数据，保留既有加载时机。
function onTabChange(name:any) {
  if (name==='runs' && !runLoaded.value) loadRuns(1)
  if (name==='checklist' && !checklistLoaded.value) loadChecklist()
}
// 根据源编码加载详情及相关证据。
async function openSource(code:string) {
  sourceDrawerVisible.value=true; sourceDetailLoading.value=true
  Object.assign(sourceDetail,{source:null,batches:[],mappings:[],runs:[]})
  try { Object.assign(sourceDetail,await dataCollectionApi.getCollectionSource(code)) }
  catch (err:any) { ElMessage.error(err?.message || '数据源证据加载失败') }
  finally { sourceDetailLoading.value=false }
}
// 按运行编号加载任务详情，保留原抽屉状态。
async function openRun(id:number) {
  runDrawerVisible.value=true; runDetailLoading.value=true
  Object.assign(runDetail,{run:null,batches:[],checks:[]})
  try { Object.assign(runDetail,await dataCollectionApi.getCollectionRun(id)) }
  catch (err:any) { ElMessage.error(err?.message || '运行详情加载失败') }
  finally { runDetailLoading.value=false }
}
// 沿用现有清单内容与导出格式，不修改源数据。
async function exportChecklist() {
  exporting.value=true
  try {
    const response=await dataCollectionApi.exportCollectionChecklist()
    if(!response.ok) throw new Error('导出失败')
    const blob=await response.blob(); const url=URL.createObjectURL(blob)
    const link=document.createElement('a'); link.href=url; link.download='数据接入核验清单.csv'; link.click()
    URL.revokeObjectURL(url)
  } catch(err:any) { ElMessage.error(err?.message || '导出失败') }
  finally { exporting.value=false }
}
// 经原确认流程提交所选任务，受理后沿用后台轮询。
async function triggerTask() {
  if(!selectedTask.value) return
  const task=overview.tasks.find((item:any)=>item.task===selectedTask.value)
  try {
    await ElMessageBox.confirm(`确认重跑“${task?.name || selectedTask.value}”？任务受理后可离开本页。`,
      '受控运维操作',{type:'warning',confirmButtonText:'确认重跑',cancelButtonText:'取消'})
  } catch { return }
  triggering.value=true; triggerResult.value=null
  try {
    const data=await dataCollectionApi.triggerCollectionTask({task:selectedTask.value})
    triggerResult.value={
      type:data.status==='failed'?'error':data.status==='success'?'success':'info',
      title:data.status==='success'?'任务执行完成':data.status==='failed'?'任务执行失败':'任务已受理，正在后台执行',
      description:data.runId?`运行编号 #${data.runId}，可在“运行与异常”查看证据。`:'运行记录正在建立，请稍后刷新。',
    }
    if(data.status==='running') schedulePoll(data.runId)
    else await reloadAll()
  } catch(err:any) { triggerResult.value={type:'error',title:'任务未能受理',description:err?.message || '请稍后重试'} }
  finally { triggering.value=false }
}
// 按原次数和间隔跟踪后台任务，失败时保留现有重试行为。
function schedulePoll(runId:number|undefined) {
  if(pollTimer) window.clearTimeout(pollTimer)
  pollCount+=1
  if(pollCount>60) return
  pollTimer=window.setTimeout(async()=>{
    try {
      if(runId) {
        const detail:any=await dataCollectionApi.pollCollectionRun(runId)
        if(detail.run?.status!=='running') {
          triggerResult.value={type:detail.run?.status==='success'?'success':'error',
            title:detail.run?.status==='success'?'后台任务执行完成':'后台任务执行失败',
            description:`运行编号 #${runId}，请在“运行与异常”查看完整证据。`}
          await reloadAll(); return
        }
      } else await loadRuns(1)
    } catch { /* 轮询失败不打断用户操作，下一轮继续 */ }
    schedulePoll(runId)
  },2000)
}

// 离开页面时清理任务轮询，避免已卸载页面继续请求。
onBeforeUnmount(()=>{ if(pollTimer) window.clearTimeout(pollTimer) })
// 进入采集工作区时加载原有总览与列表。
reloadAll()
// 各标签页与抽屉独立持有分页状态，保留全量接口和原业务筛选。
const checklistTable = useTablePagination(() => checklistRows.value)
const batchTable = useTablePagination(() => sourceDetail.batches || [])
const sourceRunTable = useTablePagination(() => sourceDetail.runs || [])
const runBatchTable = useTablePagination(() => runDetail.batches || [])
</script>

<style scoped lang="scss">
// 页面区域、状态修饰与后代元素按相邻规则分组，保留原级联和弹窗作用域。
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 14px;
}

.head-actions {
  display: flex;
  gap: var(--sa-button-gap);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.context-strip {
  display: flex;
  gap: 28px;
  padding: 10px 14px;
  margin-bottom: 14px;
  border: 1px solid var(--sa-border);
  border-radius: 10px;
  background: var(--sa-bg);
  color: var(--sa-muted);
  font-size: 12px;

  b {
    margin-right: 7px;
    color: #334155;
  }
}

.loading-card {
  margin-top: 12px;
  padding: 20px;
}

.status-cards {
  display: grid;
  grid-template-columns: repeat(4,minmax(0,1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.status-card {
  appearance: none;
  text-align: left;
  padding: 16px;
  background: #fff;
  border: 1px solid var(--sa-border);
  border-radius: 12px;
  cursor: pointer;
  transition: .18s;

  &:hover, &.active {
    border-color: #6366f1;
    box-shadow: 0 5px 18px rgba(79,70,229,.08);
  }

  &.active {
    background: #f5f3ff;
  }

  &>span {
    display: block;
    color: var(--sa-muted);
    font-size: 13px;
  }

  i {
    display: inline-grid;
    place-items: center;
    width: 16px;
    height: 16px;
    border: 1px solid #cbd5e1;
    border-radius: 50%;
    font-style: normal;
    font-size: 10px;
  }

  b {
    display: block;
    margin: 8px 0 6px;
    font-size: 27px;
    color: #312e81;
  }

  &.warning b {
    color: var(--sa-amber);
  }

  &.danger b {
    color: #dc2626;
  }

  small {
    color: var(--sa-faint);
  }
}

.priority-panel {
  padding: 16px;
  margin-bottom: 14px;
}

.section-title {
  display: flex;
  justify-content: space-between;
  gap: 14px;

  h3 {
    margin: 0 0 4px;
    font-size: 16px;
  }

  p {
    margin: 0 0 12px;
    color: var(--sa-muted);
    font-size: 12px;
  }
}

.priority-list {
  display: grid;
  gap: 8px;
}

.priority-item {
  display: grid;
  grid-template-columns: 12px minmax(240px,1.2fr) minmax(220px,1fr) 105px;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 11px 12px;
  border: 1px solid var(--sa-border-2);
  border-radius: 9px;
  background: #fff;
  text-align: left;
  cursor: pointer;

  &:hover {
    background: var(--sa-bg);
    border-color: #c7d2fe;
  }
}

.severity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f59e0b;

  &.high {
    background: #ef4444;
  }
}

.priority-main {

  b, small {
    display: block;
  }

  small {
    margin-top: 3px;
    color: var(--sa-muted);
  }
}

.priority-impact {
  color: #475569;
  font-size: 12px;

  small {
    display: block;
    color: var(--sa-faint);
  }
}

.priority-action {
  color: var(--sa-primary);
  font-size: 12px;
  text-align: right;
}

.collection-tabs {
  margin-top: 2px;
}

.filters,.run-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sa-button-gap);

  .el-select,.el-input {
    max-width: 100%;
  }

  .el-button + .el-button {
    margin-left: 0;
  }
}

.filters {

  .el-select {
    width: 190px;
  }

  .el-input {
    width: 300px;
  }
}

.run-filters {

  .el-select {
    width: 190px;
  }
}

.run-note {
  margin-bottom: 12px;
}

.table-note {
  padding: 6px 10px;
}

.filter-dirty {
  color: var(--sa-amber);
  font-size: 12px;
}

.updating-bar {
  margin-top: 8px;
  padding: 7px 12px;
  background: var(--sa-track);
  color: var(--sa-primary);
  font-size: 12px;
  border-radius: 8px 8px 0 0;
}

.table-card {
  padding: 14px;

  // 保留右侧设置的完整宽度；空间不足时，左侧筛选在卡片内自然换行。
  :deep(.app-table__tools) {
    flex-shrink: 0;
  }

  @media (max-width:800px) {
    :deep(.app-table__toolbar) {
      flex-wrap: wrap;
    }

    :deep(.app-table__extra) {
      flex-basis: 100%;
    }

    :deep(.app-table__tools) {
      margin-left: auto;
    }
  }
}

.pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  color: var(--sa-muted);
  font-size: 12px;
}

.source-identity {

  b, span {
    display: block;
  }

  span {
    margin-top: 3px;
    color: var(--sa-faint);
    font-size: 11px;
  }
}

.attention-count {
  margin-left: 5px;
  color: var(--sa-amber);
}

.clickable-row {
  cursor: pointer;
}

.drawer-tags {
  display: flex;
  align-items: center;
  gap: 9px;
  padding-bottom: 12px;
  color: var(--sa-muted);
  font-size: 12px;
}

.detail-metrics,.quality-grid,.check-grid {
  display: grid;
  grid-template-columns: repeat(2,minmax(0,1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.detail-metrics>div,.quality-grid>div,.check-grid>div {
  padding: 13px;
  border: 1px solid var(--sa-border-2);
  border-radius: 9px;
  background: var(--sa-bg);
}

.detail-metrics span,.quality-grid span,.check-grid span {
  display: block;
  color: var(--sa-muted);
  font-size: 12px;
}

.detail-metrics b,.quality-grid b,.check-grid b {
  display: block;
  margin-top: 6px;
  color: var(--sa-text);
  font-size: 17px;
}

.detail-metrics b.warn,.check-grid>div.warn b {
  color: var(--sa-amber);
}

.definition-block {
  padding: 13px 14px;
  margin-bottom: 10px;
  border: 1px solid var(--sa-border-2);
  border-radius: 9px;

  span {
    color: var(--sa-muted);
    font-size: 12px;
  }

  p {
    margin: 6px 0 0;
    line-height: 1.7;
    color: #334155;
  }
}

.evidence-item {
  display: grid;
  grid-template-columns: 1fr 2fr auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--sa-border-2);

  span {
    color: var(--sa-muted);
  }
}

.boundary-note {
  margin-top: 14px;
}

.technical-pre {
  max-height: 520px;
  overflow: auto;
  margin-top: 12px;
  padding: 14px;
  border-radius: 9px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.task-list {
  display: grid;
  gap: 10px;
  margin: 16px 0;

  label {
    display: flex;
    gap: 10px;
    padding: 13px;
    border: 1px solid var(--sa-border-2);
    border-radius: 9px;
    cursor: pointer;
  }

  label.selected {
    border-color: #6366f1;
    background: #f5f3ff;
  }

  input {
    margin-top: 4px;
  }

  b, small, em {
    display: block;
  }

  small {
    margin-top: 4px;
    color: var(--sa-muted);
    line-height: 1.55;
  }

  em {
    margin-top: 5px;
    color: var(--sa-amber);
    font-size: 11px;
    font-style: normal;
  }
}

@media (max-width:1200px) {
  .status-cards {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }

  .priority-item {
    grid-template-columns: 12px 1fr 100px;
  }

  .priority-impact {
    display: none;
  }

}

@media (max-width:800px) {
  .page-head {
    display: block;
  }

  .head-actions {
    justify-content: flex-start;
    margin-top: 10px;
  }

  .context-strip {
    display: grid;
    gap: 7px;
  }

  .status-cards {
    grid-template-columns: 1fr;
  }

  .filters,.run-filters {
    align-items: stretch;
    flex-direction: column;
  }

  .filters .el-select,.filters .el-input,.run-filters .el-select {
    width: 100%;
  }

  .priority-item {
    grid-template-columns: 12px 1fr;
  }

  .priority-action {
    display: none;
  }

}
</style>
