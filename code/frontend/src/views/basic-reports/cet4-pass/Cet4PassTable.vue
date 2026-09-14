<!-- 各班大学英语四级通过情况：承接本报表特有单元格与表头，查询仍由公共页面负责。 -->
<template>
  <BasicReportTable v-bind="$props">
    <template #col-cet4PassRateRank="{ row }">
      <span v-if="row.cet4PassRateRank" :class="rankClass(row.cet4PassRateRank)">{{ row.cet4PassRateRank }}</span>
      <span v-else>—</span>
    </template>
  </BasicReportTable>
</template>

<script setup lang="ts">
import BasicReportTable from '../components/BasicReportTable.vue'

import type { BasicReportTableProps } from '@/types/basicReports'

defineProps<BasicReportTableProps>()

// 按原前三名映射排名样式，不改变接口排名或排序。
function rankClass(rank: number) {
  return rank <= 3 ? ['cet4-rank', 'rank-' + rank] : 'cet4-rank-text'
}
</script>

<style scoped lang="scss">
.cet4-rank {
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #fff;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 1px 3px rgb(15 23 42 / 18%);


  &.rank-1 {
    background: #c9a227;
  }


  &.rank-2 {
    background: #b87333;
  }


  &.rank-3 {
    background: #9ca3af;
  }

}

.cet4-rank-text {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
