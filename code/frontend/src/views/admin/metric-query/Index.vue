<template>
  <div class="metric-query-page">
    <div class="page-head">
      <div>
        <h2 class="sa-page-title">指标查询</h2>
        <p class="sa-page-sub">按模块、标签或名称检索统一指标目录，查看计算口径、引用关系和实际使用位置。</p>
      </div>
      <div class="result-count">共 {{ total }} 个指标</div>
    </div>

    <div class="sa-card filters">
      <el-tree-select
        v-model="filters.moduleId"
        :data="moduleOptions"
        :props="treeProps"
        node-key="id"
        value-key="id"
        check-strictly
        clearable
        filterable
        placeholder="全部模块"
        @change="search"
      />
      <el-select
        v-model="filters.tagIds"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        filterable
        placeholder="全部标签分类"
        @change="search"
      >
        <el-option
          v-for="item in tagOptions"
          :key="item.id"
          :label="optionLabel(item)"
          :value="item.id"
        />
      </el-select>
      <el-input
        v-model="filters.name"
        clearable
        placeholder="输入指标名称"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <el-alert
      v-if="loadError"
      class="load-error"
      :title="loadError"
      type="error"
      :closable="false"
      show-icon
    >
      <template #default><el-button size="small" @click="loadList">重新加载</el-button></template>
    </el-alert>
    <div v-if="loading && rows.length" class="updating-bar">正在更新查询结果，当前结果暂时保留…</div>

    <div class="sa-card table-card">
      <AppTable
        show-density
        show-column-settings
        :columns="columns"
        :data="rows"
        storage-key="system:metric-query"
        :config-version="1"
        :max-business-columns="7"
        :page="page"
        :page-size="pageSize"
        :total="total"
        :loading="loading"
        stripe
        empty-text="当前条件下没有指标"
        @page-change="changePage"
        @page-size-change="changePageSize"
      >
        <template #col-name="{ row }">
          <div class="metric-name"><b>{{ row.name }}</b><span>{{ row.id || '—' }}</span></div>
        </template>
        <template #col-tags="{ row }">
          <div v-if="row.tags.length" class="tag-list">
            <el-tag v-for="tag in row.tags" :key="tag.id || tag.label" size="small" effect="plain">
              {{ tag.label }}
            </el-tag>
          </div>
          <span v-else class="sa-faint">—</span>
        </template>
        <template #col-usageText="{ row }">
          <el-tooltip :content="row.usageText" placement="top" :disabled="row.usageText === '—'">
            <span class="overflow-text">{{ row.usageText }}</span>
          </el-tooltip>
        </template>
        <template #col-referencedMetricCount="{ row }">{{ countText(row.referencedMetricCount) }}</template>
        <template #col-dependentMetricCount="{ row }">{{ countText(row.dependentMetricCount) }}</template>
        <template #col-usagePointCount="{ row }">{{ countText(row.usagePointCount) }}</template>
        <template #col-action="{ row }">
          <el-button link type="primary" @click.stop="openDetail(row.id)">详细</el-button>
        </template>
      </AppTable>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import * as kpisApi from '@/api/admin/kpis'
import {
  countText,
  normalizeMetricList,
  type MetricRow,
  type SelectNode,
} from './model'

const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const rows = ref<MetricRow[]>([])
const moduleOptions = ref<SelectNode[]>([])
const tagOptions = ref<SelectNode[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filters = reactive({ moduleId: '', tagIds: [] as string[], name: '' })
const treeProps = { value: 'id', label: 'label', children: 'children' }

const columns: AppTableColumn[] = [
  { key: 'name', label: '指标名称', required: true, region: 'identity', fixed: 'left', minWidth: 190 },
  { key: 'description', label: '指标详细说明', minWidth: 260, align: 'left', tooltip: true },
  { key: 'formula', label: '计算公式', minWidth: 260, align: 'left', tooltip: true },
  { key: 'tags', label: '标签分类', minWidth: 180, align: 'left' },
  { key: 'usageText', label: '使用模块/功能点', minWidth: 260, align: 'left' },
  { key: 'referencedMetricCount', label: '引用指标数', minWidth: 120 },
  { key: 'dependentMetricCount', label: '被引用指标数', minWidth: 130 },
  { key: 'usagePointCount', label: '被使用模块功能点数', minWidth: 170 },
  { key: 'action', label: '操作', required: true, region: 'action', fixed: 'right', width: 90 },
]

function optionLabel(item: SelectNode): string {
  return item.count === undefined ? item.label : `${item.label}（${item.count}）`
}

function queryString(): string {
  const query = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
  if (filters.moduleId) query.set('module_id', filters.moduleId)
  if (filters.tagIds.length) query.set('tag_ids', filters.tagIds.join(','))
  if (filters.name.trim()) query.set('name', filters.name.trim())
  return query.toString()
}

async function loadFallbackModules(): Promise<void> {
  if (moduleOptions.value.length) return
  try {
    const summary: any = await kpisApi.getMetricSummary()
    moduleOptions.value = (summary?.domains || []).map((item: any) => ({
      id: String(item.label || item.name || item.id || ''),
      label: String(item.label || item.name || item.id || '—'),
      count: Number.isFinite(Number(item.count)) ? Number(item.count) : undefined,
    })).filter((item: SelectNode) => item.id)
  } catch { /* 旧服务没有筛选聚合时仍可按名称查询 */ }
}

async function loadList(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const model = normalizeMetricList(await kpisApi.listMetrics(queryString()))
    rows.value = model.items
    total.value = model.total
    if (model.modules.length) moduleOptions.value = model.modules
    if (model.tags.length) tagOptions.value = model.tags
    await loadFallbackModules()
  } catch (error: any) {
    loadError.value = error?.message || '指标查询失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  loadList()
}

function resetFilters(): void {
  filters.moduleId = ''
  filters.tagIds = []
  filters.name = ''
  page.value = 1
  loadList()
}

function changePage(value: number): void {
  if (value === page.value || loading.value) return
  page.value = value
  loadList()
}

function changePageSize(value: number): void {
  if (value === pageSize.value || loading.value) return
  pageSize.value = value
  page.value = 1
  loadList()
}

function openDetail(metricId: string): void {
  if (!metricId) return
  router.push(`/admin/system/metric-query/${encodeURIComponent(metricId)}`)
}

onMounted(loadList)
</script>

<style scoped lang="scss">
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.result-count {
  padding-top: 8px;
  color: var(--sa-muted);
  font-size: 13px;
}

.filters {
  display: grid;
  grid-template-columns: minmax(190px, .8fr) minmax(220px, 1fr) minmax(240px, 1.25fr) auto auto;
  gap: 10px;
  margin: 14px 0 12px;
  padding: 14px;
}

.load-error,
.updating-bar {
  margin-bottom: 12px;
}

.updating-bar {
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--sa-track);
  color: var(--sa-primary);
  font-size: 12px;
}

.table-card {
  min-width: 0;
  padding: 14px;
}

.metric-name {
  display: flex;
  flex-direction: column;
  gap: 3px;

  b {
    color: var(--sa-text);
  }

  span {
    color: var(--sa-muted);
    font-size: 11px;
  }
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.overflow-text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .page-head {
    flex-direction: column;
  }

  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
