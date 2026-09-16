<!-- 每个展开的行政班独立持有页码；业务列、姓名点击及格式仍由 MyScope 提供。 -->
<template>
  <AppTable
    v-bind="$attrs"
    :columns="columns" :data="pagination.rows"
    storage-key="students:my-class-students"
    :show-density="true" :show-column-settings="true"
    :page="pagination.page" :page-size="pagination.pageSize" :total="pagination.total"
    @page-change="pagination.changePage" @page-size-change="pagination.changePageSize"
  >
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </AppTable>
</template>

<script setup lang="ts">
import AppTable from '@/components/AppTable.vue'
import { useTablePagination } from '@/composables/useTablePagination'
import type { AppTableColumn, TableRow } from '@/types/table'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ columns: AppTableColumn[]; data: TableRow[] }>()
const pagination = useTablePagination(() => props.data, 10)
</script>
