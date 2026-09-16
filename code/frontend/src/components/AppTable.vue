<!-- 公共表格：统一列设置、三档密度与分页展示；页面拥有查询和分页状态。 -->
<template>
  <div class="app-table" :class="`app-table--${density}`" :aria-busy="loading">
    <div v-if="showDensity || showColumnSettings || $slots.toolbar" class="app-table__toolbar">
      <div class="app-table__extra"><slot name="toolbar" /></div>
      <div v-if="showDensity || showColumnSettings" class="app-table__tools">
        <el-radio-group v-if="showDensity" :model-value="density" size="small" aria-label="行密度" @change="changeDensity">
          <el-radio-button value="compact">紧凑</el-radio-button>
          <el-radio-button value="default">默认</el-radio-button>
          <el-radio-button value="loose">宽松</el-radio-button>
        </el-radio-group>
        <el-popover v-if="showColumnSettings" placement="bottom-end" trigger="click" :width="320">
          <template #reference>
            <el-button size="small" :icon="Setting">列设置</el-button>
          </template>
          <div class="app-table__columns">
            <div class="app-table__columns-heading">
              <span>业务列 {{ visibleBusinessCount }} / 最多 {{ businessLimit }}</span>
              <el-button link type="primary" size="small" @click="resetDisplay">恢复默认</el-button>
            </div>
            <div
              v-for="column in orderedColumns"
              :key="column.key"
              class="app-table__column"
              :class="{ 'is-fixed': columnRegion(column) !== 'business' }"
              :draggable="columnRegion(column) === 'business'"
              @dragstart="startDrag(column, $event)"
              @dragend="draggingKey = ''"
              @dragover.prevent
              @drop="dropColumn(column)"
            >
              <el-icon v-if="columnRegion(column) === 'business'" class="app-table__drag"><Rank /></el-icon>
              <span v-else class="app-table__region">{{ columnRegion(column) === 'identity' ? '识别' : '操作' }}</span>
              <el-checkbox
                :model-value="!hiddenColumns.includes(column.key)"
                :disabled="column.required"
                size="small"
                @change="toggleColumn(column, Boolean($event))"
              >
                {{ column.label }}<span v-if="column.required" class="app-table__required">（必选）</span>
              </el-checkbox>
              <span v-if="columnRegion(column) === 'business'" class="app-table__moves">
                <el-button
                  link size="small" :icon="ArrowUp"
                  :disabled="businessColumns[0]?.key === column.key"
                  :aria-label="`上移${column.label}`" @click="moveColumn(column.key, -1)"
                />
                <el-button
                  link size="small" :icon="ArrowDown"
                  :disabled="businessColumns[businessColumns.length - 1]?.key === column.key"
                  :aria-label="`下移${column.label}`" @click="moveColumn(column.key, 1)"
                />
              </span>
            </div>
          </div>
        </el-popover>
      </div>
    </div>

    <div v-loading="loading" class="app-table__body">
      <!-- fit 随可见列与容器尺寸重新分配空间；普通列用 minWidth，固定宽度列用 width。 -->
      <el-table v-bind="$attrs" :data="data" :size="tableSize" :fit="true" @row-click="forwardRowClick">
        <!-- 分组表头由页面通过 columns 插槽提供，仍使用本组件的表格容器与样式。 -->
        <slot name="columns">
          <el-table-column
            v-for="column in visibleColumns" :key="column.key"
            :prop="column.prop ?? column.key" :label="column.label"
            :width="column.width" :min-width="column.minWidth"
            :align="column.align ?? 'center'" header-align="center" :fixed="column.fixed"
            :sortable="column.sortable" :formatter="column.formatter"
            :show-overflow-tooltip="column.tooltip"
          >
            <template v-if="$slots[`col-${column.key}`]" #default="scope">
              <slot :name="`col-${column.key}`" v-bind="scope" />
            </template>
            <template v-if="$slots[`header-${column.key}`]" #header="scope">
              <slot :name="`header-${column.key}`" v-bind="scope" />
            </template>
          </el-table-column>
        </slot>
        <template v-if="$slots.empty" #empty><slot name="empty" /></template>
      </el-table>
    </div>

    <AppPagination
      v-if="pagination" :page="page" :page-size="pageSize" :total="total"
      :page-sizes="pageSizes" :disabled="loading"
      @page-change="emit('page-change', $event)"
      @page-size-change="emit('page-size-change', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Rank, Setting } from '@element-plus/icons-vue'
import { ElMessage, type TableColumnCtx } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import {
  DEFAULT_TABLE_PAGE_SIZE, TABLE_PAGE_SIZES, TABLE_DENSITY_SIZES, isTableDensity,
  type AppTableColumn, type TableColumnRegion, type TableDensity, type TablePreferences, type TableRow,
} from '@/types/table'
import { readTablePreferences, tablePreferenceKey, writeTablePreferences } from '@/utils/tablePreferences'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  columns: AppTableColumn[]
  data?: TableRow[]
  storageKey: string
  configVersion?: string | number
  maxBusinessColumns?: number
  /** 页面按原有需求显式开启工具，不因替换组件而增加交互。 */
  showDensity?: boolean
  showColumnSettings?: boolean
  /** 隐藏密度切换时固定使用此档，不读取旧的密度偏好。 */
  defaultDensity?: TableDensity
  loading?: boolean
  pagination?: boolean
  page?: number
  pageSize?: number
  pageSizes?: number[]
  total?: number
}>(), {
  data: () => [],
  configVersion: 1,
  maxBusinessColumns: 10,
  showDensity: false,
  showColumnSettings: false,
  defaultDensity: 'default',
  loading: false,
  pagination: true,
  page: 1,
  pageSize: DEFAULT_TABLE_PAGE_SIZE,
  pageSizes: () => [...TABLE_PAGE_SIZES],
  total: 0,
})

const emit = defineEmits<{
  'page-change': [page: number]
  'page-size-change': [pageSize: number]
  'row-click': [row: TableRow, column: TableColumnCtx<TableRow> | null, event: Event]
}>()

const density = ref<TableDensity>('default')
const columnOrder = ref<string[]>([])
const hiddenColumns = ref<string[]>([])
const draggingKey = ref('')
const preferenceKey = computed(() => tablePreferenceKey(props.storageKey, props.configVersion))
const columnMap = computed(() => new Map(props.columns.map(column => [column.key, column])))

/** 显式区域优先；未声明时兼容原固定列语义。 */
function columnRegion(column: AppTableColumn): TableColumnRegion {
  if (column.region) return column.region
  if (column.fixed === 'left') return 'identity'
  if (column.fixed === 'right') return 'action'
  return 'business'
}

/** 保留用户的区内顺序，识别列始终靠左、操作列始终靠右。 */
const orderedColumns = computed(() => {
  const columns = columnOrder.value.map(key => columnMap.value.get(key))
    .filter((column): column is AppTableColumn => Boolean(column))
  return (['identity', 'business', 'action'] as const)
    .flatMap(region => columns.filter(column => columnRegion(column) === region))
})
const businessColumns = computed(() => orderedColumns.value.filter(column => columnRegion(column) === 'business'))
const visibleColumns = computed(() => orderedColumns.value.filter(column => !hiddenColumns.value.includes(column.key)))
const visibleBusinessCount = computed(() => businessColumns.value.filter(column => !hiddenColumns.value.includes(column.key)).length)
const businessLimit = computed(() => Math.max(props.maxBusinessColumns, businessColumns.value.filter(column => column.required).length))

/** 三档固定映射，不让页面传入的 size 使默认档与紧凑档重合。 */
const tableSize = computed(() => TABLE_DENSITY_SIZES[density.value])

/** 必选列和可见业务列上限以当前列定义为准，不信任过期或手工修改的偏好。 */
function enforceColumnRules(): void {
  hiddenColumns.value = hiddenColumns.value.filter(key => {
    const column = columnMap.value.get(key)
    return column && !column.required
  })
  // 未提供列设置入口时只按页面声明展示，避免显示上限隐藏用户无法恢复的列。
  if (!props.showColumnSettings) return
  let remaining = businessLimit.value - businessColumns.value.filter(column => column.required).length
  for (const column of businessColumns.value) {
    if (column.required || hiddenColumns.value.includes(column.key)) continue
    if (remaining > 0) remaining -= 1
    else hiddenColumns.value.push(column.key)
  }
}

/** 恢复只更新展示状态，不 emit 页码或页长，不触发页面请求。 */
function restoreDisplay(saved: TablePreferences): void {
  const keys = props.columns.map(column => column.key)
  const known = new Set(keys)
  const retained = (props.showColumnSettings ? saved.order ?? [] : []).filter(key => known.has(key))
  columnOrder.value = [...retained, ...keys.filter(key => !retained.includes(key))]
  const defaultHidden = props.columns.filter(column => column.defaultVisible === false).map(column => column.key)
  hiddenColumns.value = props.showColumnSettings ? saved.hidden ?? defaultHidden : defaultHidden
  density.value = props.showDensity ? saved.density ?? props.defaultDensity : props.defaultDensity
  draggingKey.value = ''
  enforceColumnRules()
}

// 关闭的功能忽略对应旧偏好，保留原记录；重新开启后仍可恢复。
watch(
  [preferenceKey, () => props.columns, () => props.showDensity, () => props.showColumnSettings, () => props.defaultDensity],
  () => restoreDisplay(readTablePreferences(preferenceKey.value)),
  { immediate: true },
)

/** 只保存显示设置；旧页长字段原样保留，新的页面分页完全由父页面管理。 */
function saveDisplay(): void {
  if (!props.showDensity && !props.showColumnSettings) return
  const saved = readTablePreferences(preferenceKey.value)
  if (props.showColumnSettings) {
    saved.order = [...columnOrder.value]
    saved.hidden = [...hiddenColumns.value]
  }
  if (props.showDensity) saved.density = density.value
  writeTablePreferences(preferenceKey.value, saved)
}

function changeDensity(value: unknown): void {
  if (!isTableDensity(value) || value === density.value) return
  density.value = value
  saveDisplay()
}

/** 显示偏好复位不改变当前查询、页码或页长。 */
function resetDisplay(): void {
  restoreDisplay({})
  saveDisplay()
}

function toggleColumn(column: AppTableColumn, visible: boolean): void {
  if (column.required && !visible) return
  if (visible && hiddenColumns.value.includes(column.key)) {
    if (columnRegion(column) === 'business' && visibleBusinessCount.value >= businessLimit.value) {
      ElMessage.warning(`为保证可读性，当前最多显示 ${businessLimit.value} 个业务列`)
      return
    }
    hiddenColumns.value = hiddenColumns.value.filter(key => key !== column.key)
  } else if (!visible && !hiddenColumns.value.includes(column.key)) {
    hiddenColumns.value.push(column.key)
  }
  saveDisplay()
}

/** 按钮与拖拽共用同一排序入口，只允许调整业务列之间的位置。 */
function reorderColumn(source: string, target: string): void {
  const keys = businessColumns.value.map(column => column.key)
  if (source === target || !keys.includes(source) || !keys.includes(target)) return
  const order = [...columnOrder.value]
  const from = order.indexOf(source)
  const to = order.indexOf(target)
  order.splice(from, 1)
  order.splice(to, 0, source)
  columnOrder.value = order
  saveDisplay()
}

function moveColumn(key: string, offset: -1 | 1): void {
  const index = businessColumns.value.findIndex(column => column.key === key)
  const target = businessColumns.value[index + offset]
  if (target) reorderColumn(key, target.key)
}

function startDrag(column: AppTableColumn, event: DragEvent): void {
  if (columnRegion(column) !== 'business') return
  draggingKey.value = column.key
  event.dataTransfer?.setData('text/plain', column.key)
}

function dropColumn(column: AppTableColumn): void {
  reorderColumn(draggingKey.value, column.key)
  draggingKey.value = ''
}

function forwardRowClick(row: TableRow, column: TableColumnCtx<TableRow> | null, event: Event): void {
  emit('row-click', row, column, event)
}
</script>

<style scoped lang="scss">
.app-table {
  min-width: 0;

  &__toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }

  &__extra {
    flex: 1;
    min-width: 0;
  }

  &__tools {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }

  &__body {
    min-width: 0;

    // 表头（含左右固定列）共用主题浅色背景，三档密度只调整原有行距。
    :deep(.el-table) {
      --el-table-header-bg-color: var(--sa-track);
    }

    // Element Plus 的分组表头另有背景规则；两层表头仍使用同一主题色。
    :deep(.el-table thead.is-group th.el-table__cell) {
      background-color: var(--el-table-header-bg-color);
    }
  }

  // 列设置弹层虽渲染到 body，仍通过本组件的作用域类限定样式。
  &__columns {
    color: var(--sa-muted);
    font-size: var(--el-font-size-extra-small);

    &-heading {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
  }

  &__column {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 4px 0;
    border-bottom: 1px solid var(--sa-border);

    &:not(.is-fixed) {
      cursor: grab;

      &:active {
        cursor: grabbing;
      }
    }

    :deep(.el-checkbox) {
      flex: 1;
      min-width: 0;
    }
  }

  &__drag, &__required {
    color: var(--sa-faint);
  }

  &__region {
    padding: 2px 4px;
    border-radius: var(--el-border-radius-small);
    background: var(--sa-bg);
    color: var(--sa-muted);
  }

  &__moves {
    display: inline-flex;
    margin-left: auto;
  }

  @media (max-width: 768px) {
    &__toolbar {
      flex-wrap: wrap;
    }

    &__tools {
      margin-left: auto;
    }
  }
}
</style>
