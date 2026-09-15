<!-- 公共分页：页面持有页码、页长和服务端总数，组件只发送用户操作事件。 -->
<template>
  <div v-if="total > 0" class="app-pagination" aria-label="表格分页">
    <div class="app-pagination__controls">
      <el-config-provider :locale="zhCn">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="pageSizes"
          :total="total"
          :disabled="disabled"
          :pager-count="5"
          size="default"
          layout="total, sizes, prev, pager, next, jumper"
          @update:current-page="changePage"
          @update:page-size="changePageSize"
        />
      </el-config-provider>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { DEFAULT_TABLE_PAGE_SIZE, TABLE_PAGE_SIZES } from '@/types/table'

const props = withDefaults(defineProps<{
  page?: number
  pageSize?: number
  total: number
  pageSizes?: number[]
  disabled?: boolean
}>(), {
  page: 1,
  pageSize: DEFAULT_TABLE_PAGE_SIZE,
  pageSizes: () => [...TABLE_PAGE_SIZES],
  disabled: false,
})

const emit = defineEmits<{
  'page-change': [page: number]
  'page-size-change': [pageSize: number]
}>()

let changingPageSize = false

/** 页长更新时 Element Plus 可能同时修正页码；由页面统一回第一页，避免重复查询。 */
function changePageSize(value: number): void {
  if (props.disabled || value === props.pageSize || !props.pageSizes.includes(value)) return
  changingPageSize = true
  emit('page-size-change', value)
  void nextTick(() => { changingPageSize = false })
}

/** 只转发有效的用户翻页；父组件回写相同页码不会再次发起查询。 */
function changePage(value: number): void {
  if (props.disabled || changingPageSize || value === props.page) return
  if (!Number.isSafeInteger(value) || value < 1) return
  emit('page-change', value)
}
</script>

<style scoped lang="scss">
.app-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-top: 16px;
  margin-top: 16px;
  border-top: 1px solid var(--sa-border);

  &__controls {
    min-width: 0;
    overflow-x: auto;

    // 页码输入内部高度跟随分页按钮（桌面 32px、窄屏 28px），避免被全局输入框高度撑出纵向滚动条。
    :deep(.el-pagination__editor.el-input) {
      --el-input-height: var(--el-pagination-button-height);
    }
  }

  @media (max-width: 768px) {
    &__controls {
      width: 100%;
    }
  }
}
</style>
