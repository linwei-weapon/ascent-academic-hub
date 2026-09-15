<!-- 基础报表通用表格：复用 AppTable，整表展示以保留相邻合并和原有显示偏好。 -->
<template>
  <AppTable
    :key="definition.reportId"
    :columns="definition.columns"
    :data="result?.rows || []"
    :storage-key="`basic-report:${definition.reportId}`"
    :span-method="spanMethod"
    :row-class-name="rowClassName"
    :max-business-columns="12"
    :pagination="false"
    :show-density="true"
    :show-column-settings="true"
    :config-version="['RPT-01', 'RPT-02', 'RPT-03', 'RPT-06'].includes(definition.reportId) ? 3 : 2"
    empty-text=""
  >
    <template #col-courseEvidence="{ row }">
      <span class="multiline-cell">{{ row.courseEvidence || '—' }}</span>
    </template>
    <template #empty>
      <div class="blank-table-body">{{ result ? '当前授权范围和筛选条件下无数据' : '' }}</div>
    </template>
    <template v-for="(_, name) in $slots" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps || {}" />
    </template>
  </AppTable>
</template>

<script setup lang="ts">
import AppTable from '@/components/AppTable.vue'
import type { BasicReportTableProps } from '@/types/basicReports'

defineProps<BasicReportTableProps>()
</script>

<style scoped lang="scss">
.blank-table-body {
  min-height: 48px;
}

.multiline-cell {
  white-space: pre-line;
  line-height: 1.65;
}
</style>
