<!-- 年级总体挂科情况：承接本报表特有单元格与表头，查询仍由公共页面负责。 -->
<template>
  <BasicReportTable v-bind="$props">
    <template #col-category="{ row }">
      <span class="multiline-cell">{{ row.category }}</span>
    </template>
  </BasicReportTable>
</template>

<script setup lang="ts">
import BasicReportTable from '../components/BasicReportTable.vue'

import type { BasicReportTableProps } from '@/types/basicReports'

defineProps<BasicReportTableProps>()


</script>

<style scoped lang="scss">
.multiline-cell {
  white-space: pre-line;
  line-height: 1.65;
}
</style>
