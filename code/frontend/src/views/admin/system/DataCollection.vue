<template>
  <div class="dc-page">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">数据采集监控</h2>
        <p class="sa-page-sub">查看采集批次台账与ETL运行历史，手动触发白名单采集任务；平台只消费学校数据，不维护教务主数据。</p>
      </div>
      <el-button :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="boundary-alert"
      :title="overview.boundary || '原型期不内置调度器，采集由学校数据交换平台触发。'" />

    <!-- ① 概览卡 -->
    <div class="overview-grid" v-loading="loading">
      <article class="ov-card">
        <span class="ov-label">上次采集时间</span>
        <b>{{ overview.lastCollectedAt || '—' }}</b>
        <small>批次台账 data_batch 最新采集/接入时间</small>
      </article>
      <article class="ov-card">
        <span class="ov-label">采集批次总数</span>
        <b>{{ overview.batchTotal ?? '—' }}</b>
        <small>质检未通过 {{ overview.batchQualityPending ?? 0 }} 批</small>
      </article>
      <article class="ov-card">
        <span class="ov-label">最近运行</span>
        <b v-if="overview.lastRun">
          <el-tag size="small" :type="statusTagType(overview.lastRun.status)">{{ statusLabel(overview.lastRun.status) }}</el-tag>
          {{ taskName(overview.lastRun.task) }}
        </b>
        <b v-else>—</b>
        <small>{{ overview.lastRun ? (overview.lastRun.finished_at || overview.lastRun.started_at) : '暂无运行记录' }}</small>
      </article>
      <article class="ov-card">
        <span class="ov-label">待处理数据质量问题</span>
        <b :class="{warn: (overview.openQualityIssues||0) > 0}">{{ overview.openQualityIssues ?? '—' }}</b>
        <small>教学运行分析数据质量核查 open 状态（只读引用）</small>
      </article>
    </div>

    <!-- ② 手动触发 + 采集频率 -->
    <div class="action-grid">
      <article class="panel">
        <h3>手动触发采集任务</h3>
        <p class="panel-sub">仅可触发白名单任务；触发需要 etl.trigger 动作权限，并记录安全审计。同任务执行中时不可重复触发。</p>
        <div class="trigger-row">
          <el-select v-model="selectedTask" placeholder="选择采集任务" style="flex:1">
            <el-option v-for="t in overview.tasks || []" :key="t.task" :value="t.task"
              :label="`${t.name}（${t.task}）`">
              <div>{{ t.name }} <span class="task-id">{{ t.task }}</span></div>
              <div class="task-desc">{{ t.description }}<template v-if="t.needsSourceFiles"> · 依赖数据源文件</template></div>
            </el-option>
          </el-select>
          <el-button type="primary" :loading="triggering" :disabled="!selectedTask" @click="trigger">触发采集</el-button>
        </div>
        <el-alert v-if="triggerResult" :type="triggerResult.status === 'success' ? 'success' : (triggerResult.status === 'failed' ? 'error' : 'warning')"
          :closable="false" show-icon class="trigger-result"
          :title="triggerResult.msg"
          :description="triggerResult.detail" />
      </article>
      <article class="panel">
        <h3>采集频率配置</h3>
        <p class="panel-sub">配置值来自系统参数（学期与数据），本页只读展示；编辑请前往「系统参数」。</p>
        <div v-for="key in ['data.refresh_mode','data.refresh_cron']" :key="key" class="freq-row">
          <template v-if="overview.frequency && overview.frequency[key]">
            <b>{{ overview.frequency[key].name }}</b>
            <span class="freq-value">{{ overview.frequency[key].value }}</span>
            <small>{{ overview.frequency[key].description }}</small>
          </template>
          <template v-else>
            <b>{{ key }}</b><span class="freq-value">未配置</span>
          </template>
        </div>
        <el-alert type="warning" :closable="false" show-icon title="原型期系统不内置调度器；定时采集由学校数据交换平台按计划触发。" />
      </article>
    </div>

    <!-- ③ 批次台账 -->
    <article class="panel">
      <h3>采集批次台账</h3>
      <p class="panel-sub">V2 贴源层 data_batch：每个源文件的哈希、行数与质检状态，可关联最近一次ETL运行。</p>
      <el-table :data="batches" v-loading="loadingBatches" size="small" stripe>
        <el-table-column prop="source_code" label="数据源" width="130" />
        <el-table-column prop="source_file" label="源文件" min-width="220" show-overflow-tooltip />
        <el-table-column prop="row_count" label="源行数" width="90" align="right" />
        <el-table-column prop="accepted_count" label="接受" width="80" align="right" />
        <el-table-column prop="rejected_count" label="拒绝" width="80" align="right" />
        <el-table-column label="质检状态" width="100">
          <template #default="{row}">
            <el-tag size="small" :type="qualityTagType(row.quality_status)">{{ row.quality_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近运行" width="100">
          <template #default="{row}">
            <el-tag v-if="row.last_run_status" size="small" :type="statusTagType(row.last_run_status)">{{ statusLabel(row.last_run_status) }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="collected_at" label="采集时间" width="170" show-overflow-tooltip />
        <el-table-column prop="ingested_at" label="接入时间" width="170" show-overflow-tooltip />
      </el-table>
    </article>

    <!-- ④ 运行历史 -->
    <article class="panel">
      <h3>ETL 运行历史</h3>
      <p class="panel-sub">etl_run：每次跑批的成败、耗时、行数与校验结果（checks_json）。</p>
      <div class="runs-filter">
        <el-select v-model="runFilter.task" placeholder="全部任务" clearable style="width:260px" @change="loadRuns(1)">
          <el-option v-for="t in overview.tasks || []" :key="t.task" :value="t.task" :label="`${t.name}（${t.task}）`" />
          <el-option value="run_etl_full" label="完整ETL管线（run_etl_full）" />
        </el-select>
        <el-select v-model="runFilter.status" placeholder="全部状态" clearable style="width:140px" @change="loadRuns(1)">
          <el-option value="success" label="成功" />
          <el-option value="failed" label="失败" />
          <el-option value="running" label="执行中" />
        </el-select>
      </div>
      <el-table :data="runs" v-loading="loadingRuns" size="small" stripe>
        <el-table-column type="expand">
          <template #default="{row}">
            <pre class="checks-pre">{{ prettyChecks(row.checks_json) }}</pre>
          </template>
        </el-table-column>
        <el-table-column prop="run_id" label="ID" width="70" />
        <el-table-column label="任务" min-width="200">
          <template #default="{row}">{{ taskName(row.task) }} <span class="task-id">{{ row.task }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" width="200" show-overflow-tooltip />
        <el-table-column label="耗时" width="100" align="right">
          <template #default="{row}">{{ row.duration_ms == null ? '—' : formatDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column prop="rows_written" label="写入行数" width="90" align="right">
          <template #default="{row}">{{ row.rows_written ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="triggered_by" label="触发人" width="110" show-overflow-tooltip />
        <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip>
          <template #default="{row}">{{ row.error || '—' }}</template>
        </el-table-column>
      </el-table>
      <el-pagination class="runs-pager" layout="total, prev, pager, next" :total="runsTotal"
        :page-size="runFilter.pageSize" :current-page="runFilter.page"
        @current-change="loadRuns" />
    </article>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from '@/utils/http'

const loading = ref(false)
const loadingBatches = ref(false)
const loadingRuns = ref(false)
const triggering = ref(false)
const overview = reactive<any>({ tasks: [], frequency: {} })
const batches = ref<any[]>([])
const runs = ref<any[]>([])
const runsTotal = ref(0)
const selectedTask = ref('')
const triggerResult = ref<any>(null)
const runFilter = reactive({ task: '', status: '', page: 1, pageSize: 20 })

const taskNames = reactive<Record<string, string>>({ run_etl_full: '完整ETL管线' })
function taskName(task: string) { return taskNames[task] || task }
function statusLabel(s: string) { return ({ success: '成功', failed: '失败', running: '执行中' } as any)[s] || s }
function statusTagType(s: string) { return s === 'success' ? 'success' : (s === 'failed' ? 'danger' : 'warning') }
function qualityTagType(s: string) { return (s === 'passed' || s === 'ok') ? 'success' : (s === 'pending' ? 'info' : 'warning') }
function formatDuration(ms: number) {
  if (ms < 1000) return `${ms} ms`
  const sec = ms / 1000
  return sec < 60 ? `${sec.toFixed(1)} 秒` : `${Math.floor(sec / 60)} 分 ${Math.round(sec % 60)} 秒`
}
function prettyChecks(raw: string) {
  if (!raw) return '（无校验明细）'
  try { return JSON.stringify(JSON.parse(raw), null, 2) } catch { return raw }
}

async function loadOverview() {
  const data = await http.get('/admin/system/data-collection/overview')
  Object.assign(overview, data)
  for (const t of data.tasks || []) taskNames[t.task] = t.name
}
async function loadBatches() {
  loadingBatches.value = true
  try {
    const data = await http.get('/admin/system/data-collection/batches')
    batches.value = data.batches || []
  } finally { loadingBatches.value = false }
}
async function loadRuns(page = 1) {
  runFilter.page = page
  loadingRuns.value = true
  try {
    const qs = new URLSearchParams({ page: String(runFilter.page), pageSize: String(runFilter.pageSize) })
    if (runFilter.task) qs.set('task', runFilter.task)
    if (runFilter.status) qs.set('status', runFilter.status)
    const data = await http.get(`/admin/system/data-collection/runs?${qs.toString()}`)
    runs.value = data.runs || []
    runsTotal.value = data.total || 0
  } finally { loadingRuns.value = false }
}
async function loadAll() {
  loading.value = true
  try { await Promise.all([loadOverview(), loadBatches(), loadRuns(runFilter.page)]) }
  finally { loading.value = false }
}
async function trigger() {
  if (!selectedTask.value) return
  const name = taskName(selectedTask.value)
  try {
    await ElMessageBox.confirm(
      `即将同步执行「${name}」。执行期间页面会等待结果（最长 2 分钟），确认触发？`,
      '手动触发采集任务', { confirmButtonText: '确认触发', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  triggering.value = true
  triggerResult.value = null
  try {
    const data = await http.post('/admin/system/data-collection/trigger', { task: selectedTask.value })
    triggerResult.value = {
      status: data.status,
      msg: data.status === 'success'
        ? `执行完成：写入 ${data.rowsWritten ?? '—'} 行，耗时 ${data.durationMs != null ? formatDuration(data.durationMs) : '—'}（run_id=${data.runId}）`
        : data.status === 'running'
          ? `任务已受理仍在执行中（run_id=${data.runId ?? '—'}），请稍后刷新运行历史`
          : `执行失败（run_id=${data.runId ?? '—'}）`,
      detail: data.error || '',
    }
    await Promise.all([loadOverview(), loadRuns(1)])
  } catch (err: any) {
    ElMessage.error(err?.message || '触发失败')
  } finally { triggering.value = false }
}
onMounted(loadAll)
</script>

<style scoped>
.sa-head-row{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}
.boundary-alert{margin-bottom:12px}
.overview-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}
.ov-card{padding:16px;background:#fff;border:1px solid var(--sa-border);border-radius:12px}
.ov-label{display:block;color:#94a3b8;font-size:12px;margin-bottom:8px}
.ov-card b{display:block;font-size:18px;color:#1e293b}
.ov-card b.warn{color:#d97706}
.ov-card small{display:block;margin-top:8px;color:#94a3b8;line-height:1.5}
.action-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:14px}
.panel{padding:16px;background:#fff;border:1px solid var(--sa-border);border-radius:12px;margin-bottom:14px}
.action-grid .panel{margin-bottom:0}
.panel h3{margin:0 0 6px;font-size:15px;color:#1e293b}
.panel-sub{margin:0 0 12px;color:#94a3b8;font-size:12px;line-height:1.6}
.trigger-row{display:flex;gap:10px;margin-bottom:10px}
.trigger-result{margin-top:6px}
.task-id{color:#94a3b8;font-size:11px}
.task-desc{color:#94a3b8;font-size:11px}
.freq-row{margin-bottom:12px}
.freq-row b{display:block;color:#1e293b;font-size:13px}
.freq-value{display:inline-block;margin:4px 0;color:#4f46e5;font-weight:600}
.freq-row small{display:block;color:#94a3b8;line-height:1.5}
.runs-filter{display:flex;gap:10px;margin-bottom:10px}
.runs-pager{margin-top:10px;justify-content:flex-end}
.checks-pre{margin:0;padding:8px 12px;background:#f8fafc;border-radius:8px;font-size:11px;line-height:1.6;max-height:320px;overflow:auto;white-space:pre-wrap;word-break:break-all}
@media(max-width:1100px){.overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.action-grid{grid-template-columns:1fr}}
</style>
