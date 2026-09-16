/** 全量列表的页面分页状态：供列表和详情子表复用，AppTable 只接收当前页。 */
import { computed, reactive, ref, watch } from 'vue'
import { DEFAULT_TABLE_PAGE_SIZE, TABLE_PAGE_SIZES, type TableRow } from '@/types/table'

export function useTablePagination(source: () => TableRow[], initialPageSize: number = DEFAULT_TABLE_PAGE_SIZE) {
  const page = ref(1)
  // 旧页面可显式保留初始页长；其他接入继续使用统一的 20 条。
  const pageSize = ref<number>(TABLE_PAGE_SIZES.some(size => size === initialPageSize) ? initialPageSize : DEFAULT_TABLE_PAGE_SIZE)
  const total = computed(() => source().length)
  const lastPage = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const rows = computed(() => source().slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

  // 沿用旧内部分页的重置规则：切换数据源、筛选或重新加载完整集合后从第一页展示。
  watch(source, () => { page.value = 1 })
  watch(lastPage, value => { page.value = Math.min(page.value, value) })

  function changePage(value: number): void {
    if (Number.isSafeInteger(value)) page.value = Math.min(lastPage.value, Math.max(1, value))
  }

  function changePageSize(value: number): void {
    if (!TABLE_PAGE_SIZES.some(size => size === value) || value === pageSize.value) return
    pageSize.value = value
    page.value = 1
  }

  return reactive({ page, pageSize, total, rows, changePage, changePageSize })
}
