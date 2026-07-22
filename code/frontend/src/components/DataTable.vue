<!--
  DataTable 标准表格控件（M6）
  ==========================
  包装 el-table，提供声明式列配置 + 工具栏（列显示/隐藏、列顺序、行密度、每页行数），
  按「用户 × 页面」把偏好持久化到 localStorage，键格式：
      bi_table_pref:{用户名}:{storageKey}
  读写均做防御：JSON 解析失败 / 键缺失 / 列定义变更时回退默认，不影响表格使用。

  使用方式：
    <DataTable
      :columns="cols" :data="rows" storage-key="students:list" size="small"
      @row-click="goStudent" row-class-name="row-clickable">
      <template #col-name="{ row }">…自定义单元格…</template>
      <template #header-gpa>…自定义表头…</template>
    </DataTable>

  - 列定义在页面侧声明（key/label/width/minWidth/align/fixed/sortable/defaultVisible/tooltip/formatter），
    组件不内置任何业务列；自定义渲染通过 `col-{key}` / `header-{key}` 插槽透传。
  - 其余 el-table 常用能力（stripe、row-click、sort-change、row-class-name、empty-text、v-loading 等）
    通过 $attrs / 指令原样透传。
  - 行密度：紧凑=small、默认=沿用页面传入的 size（未传则为 default）、宽松=large。
  - 每页行数：
    · 内置分页：pagination + default-page-size，组件切片并渲染分页条，data 变化自动回到第 1 页；
    · 外部分页：页面自带 el-pagination 时用 v-model:page-size 联动，组件负责持久化与恢复，
      恢复值与当前不一致时 emit update:pageSize，由页面自行重载数据。
-->
<script lang="ts">
/** DataTable 列定义；组件不内置业务列，全部在使用方页面声明。 */
export interface DataTableColumn {
  /** 列唯一标识，同时是插槽名后缀（col-{key} / header-{key}）与偏好存储键 */
  key: string
  /** 表头文案；列设置面板中展示 */
  label: string
  /** 数据字段名，缺省取 key */
  prop?: string
  width?: number | string
  minWidth?: number | string
  align?: 'left' | 'center' | 'right'
  fixed?: boolean | 'left' | 'right'
  sortable?: boolean | 'custom'
  /** false 时默认隐藏（用户可在列设置中打开） */
  defaultVisible?: boolean
  /** show-overflow-tooltip */
  tooltip?: boolean
  formatter?: (row: any, column: any, cellValue: any, index: number) => any
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref, useAttrs, watch } from 'vue'
import { ArrowDown, ArrowUp, Setting } from '@element-plus/icons-vue'
import { authStore } from '@/store/auth'

type Density = 'compact' | 'default' | 'loose'
interface TablePref { order?: string[]; hidden?: string[]; density?: Density; pageSize?: number }

const props = withDefaults(defineProps<{
  columns: DataTableColumn[]
  data?: any[]
  /** 页面级标识，偏好键 bi_table_pref:{用户名}:{storageKey} 的最后一段 */
  storageKey: string
  /** 内置分页：组件切片并渲染分页条 */
  pagination?: boolean
  pageSizes?: number[]
  defaultPageSize?: number
  /** 外部分页模式：页面传 v-model:page-size 联动自带分页 */
  pageSize?: number
}>(), {
  data: () => [],
  pagination: false,
  pageSizes: () => [10, 20, 50, 100],
  defaultPageSize: 10,
  pageSize: undefined,
})

const emit = defineEmits<{ (e: 'update:pageSize', value: number): void }>()

defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

// ── 列 / 密度 / 行数状态（默认值先就位，再被偏好覆盖）──
const colOrder = ref<string[]>(props.columns.map(c => c.key))
const colHidden = ref<string[]>(props.columns.filter(c => c.defaultVisible === false).map(c => c.key))
const density = ref<Density>('default')
const pageSizeInner = ref<number>(props.defaultPageSize)
const currentPage = ref(1)

function prefStorageKey(): string {
  return `bi_table_pref:${authStore.user?.username || 'anonymous'}:${props.storageKey}`
}
function readPref(): TablePref | null {
  try {
    const raw = localStorage.getItem(prefStorageKey())
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as TablePref : null
  } catch {
    return null // JSON 解析失败回退默认
  }
}

// 恢复偏好：无效键、已删除列、非法值全部防御性忽略
const savedPref = readPref()
if (savedPref) {
  if (Array.isArray(savedPref.order)) {
    const known = new Set(props.columns.map(c => c.key))
    const kept = savedPref.order.filter(k => known.has(k))
    const added = props.columns.map(c => c.key).filter(k => !kept.includes(k))
    if (kept.length) colOrder.value = [...kept, ...added]
  }
  if (Array.isArray(savedPref.hidden)) {
    const known = new Set(props.columns.map(c => c.key))
    colHidden.value = savedPref.hidden.filter(k => known.has(k))
  }
  if (savedPref.density === 'compact' || savedPref.density === 'default' || savedPref.density === 'loose') {
    density.value = savedPref.density
  }
  if (typeof savedPref.pageSize === 'number' && savedPref.pageSize > 0) {
    pageSizeInner.value = savedPref.pageSize
  }
}

function savePref(): void {
  try {
    localStorage.setItem(prefStorageKey(), JSON.stringify({
      order: colOrder.value,
      hidden: colHidden.value,
      density: density.value,
      pageSize: pageSizeInner.value,
    }))
  } catch { /* 存储失败（如隐私模式）不影响表格使用 */ }
}

// ── 列渲染 ──
const colMap = computed(() => new Map(props.columns.map(c => [c.key, c])))
const orderedColumns = computed(() =>
  colOrder.value.map(k => colMap.value.get(k)).filter(Boolean) as DataTableColumn[])
const visibleColumns = computed(() =>
  orderedColumns.value.filter(c => !colHidden.value.includes(c.key)))

// ── 行密度：默认档沿用页面自身 size，保持迁移前视觉一致 ──
const tableSize = computed(() => {
  if (density.value === 'compact') return 'small'
  if (density.value === 'loose') return 'large'
  const s = attrs.size as string | undefined
  return s === 'small' || s === 'large' ? s : 'default'
})

// ── 每页行数 ──
const isExternalPageSize = computed(() => props.pageSize !== undefined)
const showPageSize = computed(() => props.pagination || isExternalPageSize.value)
const pageSizeValue = computed(() => isExternalPageSize.value ? (props.pageSize as number) : pageSizeInner.value)

function onPageSizeChange(value: number): void {
  pageSizeInner.value = value
  currentPage.value = 1
  savePref()
  if (isExternalPageSize.value) emit('update:pageSize', value)
}

onMounted(() => {
  // 外部分页：偏好中的每页行数与页面当前值不一致时回写，由页面自行重载
  if (isExternalPageSize.value && pageSizeInner.value !== props.pageSize) {
    emit('update:pageSize', pageSizeInner.value)
  }
})

// ── 内置分页 ──
const pagedData = computed(() => {
  if (!props.pagination) return props.data
  const start = (currentPage.value - 1) * pageSizeInner.value
  return props.data.slice(start, start + pageSizeInner.value)
})
watch(() => props.data, () => { currentPage.value = 1 })

// ── 列设置面板 ──
function toggleCol(key: string, visible: boolean): void {
  if (visible) colHidden.value = colHidden.value.filter(k => k !== key)
  else if (!colHidden.value.includes(key)) colHidden.value = [...colHidden.value, key]
  savePref()
}
function moveCol(index: number, dir: -1 | 1): void {
  const target = index + dir
  if (target < 0 || target >= colOrder.value.length) return
  const arr = [...colOrder.value]
  const [item] = arr.splice(index, 1)
  arr.splice(target, 0, item)
  colOrder.value = arr
  savePref()
}
function onDensityChange(value: string | number | boolean | undefined): void {
  density.value = value as Density
  savePref()
}
function resetPref(): void {
  colOrder.value = props.columns.map(c => c.key)
  colHidden.value = props.columns.filter(c => c.defaultVisible === false).map(c => c.key)
  density.value = 'default'
  pageSizeInner.value = props.defaultPageSize
  currentPage.value = 1
  try { localStorage.removeItem(prefStorageKey()) } catch { /* ignore */ }
  if (isExternalPageSize.value) emit('update:pageSize', props.defaultPageSize)
}
</script>

<template>
  <div class="data-table">
    <div class="data-table__toolbar">
      <span class="data-table__toolbar-extra"><slot name="toolbar" /></span>
      <div class="data-table__tools">
        <el-select
          v-if="showPageSize"
          :model-value="pageSizeValue"
          size="small"
          class="data-table__page-size"
          aria-label="每页行数"
          @change="onPageSizeChange"
        >
          <el-option v-for="s in pageSizes" :key="s" :label="`${s} 条/页`" :value="s" />
        </el-select>
        <el-radio-group
          :model-value="density"
          size="small"
          aria-label="行密度"
          @change="onDensityChange"
        >
          <el-radio-button value="compact">紧凑</el-radio-button>
          <el-radio-button value="default">默认</el-radio-button>
          <el-radio-button value="loose">宽松</el-radio-button>
        </el-radio-group>
        <el-popover placement="bottom-end" trigger="click" :width="300">
          <template #reference>
            <el-button size="small" :icon="Setting">列设置</el-button>
          </template>
          <div class="data-table__col-panel">
            <div class="data-table__col-head">
              <span>列显示与顺序</span>
              <el-button link type="primary" size="small" @click="resetPref">恢复默认</el-button>
            </div>
            <div v-for="(c, i) in orderedColumns" :key="c.key" class="data-table__col-row">
              <el-checkbox
                :model-value="!colHidden.includes(c.key)"
                size="small"
                @change="(v: string | number | boolean) => toggleCol(c.key, !!v)"
              >{{ c.label || c.key }}</el-checkbox>
              <span class="data-table__col-moves">
                <el-button link size="small" :icon="ArrowUp" :disabled="i === 0" aria-label="上移" @click="moveCol(i, -1)" />
                <el-button link size="small" :icon="ArrowDown" :disabled="i === orderedColumns.length - 1" aria-label="下移" @click="moveCol(i, 1)" />
              </span>
            </div>
          </div>
        </el-popover>
      </div>
    </div>

    <el-table v-bind="$attrs" :data="pagedData" :size="tableSize">
      <el-table-column
        v-for="col in visibleColumns"
        :key="col.key"
        :prop="col.prop ?? col.key"
        :label="col.label"
        :width="col.width"
        :min-width="col.minWidth"
        :align="col.align"
        :fixed="col.fixed"
        :sortable="col.sortable"
        :formatter="col.formatter"
        :show-overflow-tooltip="col.tooltip"
      >
        <template v-if="$slots['col-' + col.key]" #default="scope">
          <slot :name="'col-' + col.key" v-bind="scope" />
        </template>
        <template v-if="$slots['header-' + col.key]" #header="scope">
          <slot :name="'header-' + col.key" v-bind="scope" />
        </template>
      </el-table-column>
      <template v-if="$slots.empty" #empty><slot name="empty" /></template>
    </el-table>

    <div v-if="pagination" class="data-table__pager">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSizeInner"
        :total="props.data.length"
        layout="total, prev, pager, next"
        small
      />
    </div>
  </div>
</template>

<style scoped>
.data-table__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.data-table__toolbar-extra { flex: 1; min-width: 0; }
.data-table__tools { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.data-table__page-size { width: 104px; }
.data-table__col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--sa-muted, #64748b);
}
.data-table__col-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1px 0;
}
.data-table__col-moves { display: inline-flex; }
.data-table__pager { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
