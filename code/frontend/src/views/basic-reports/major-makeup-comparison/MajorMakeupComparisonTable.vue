<!-- 各专业补考前后挂科率比较：承接本报表特有单元格与表头，查询仍由公共页面负责。 -->
<template>
  <BasicReportTable v-bind="$props">
<template #header-failedBeforeRate>
          <span class="formula-header">挂科率（补考前）<el-tooltip content="挂科率（补考前）= 已挂人数 ÷ 专业人数" placement="top"><el-icon class="formula-help-icon" tabindex="0" aria-label="查看补考前挂科率计算公式"><QuestionFilled /></el-icon></el-tooltip></span>
        </template>
<template #header-failedAfterRate>
          <span class="formula-header">挂科率（补考后）<el-tooltip content="挂科率（补考后）= 在挂人数 ÷ 专业人数" placement="top"><el-icon class="formula-help-icon" tabindex="0" aria-label="查看补考后挂科率计算公式"><QuestionFilled /></el-icon></el-tooltip></span>
        </template>
<template #header-passRate>
          <span class="formula-header">通过率<el-tooltip content="通过率 =（专业人数－在挂人数）÷ 专业人数" placement="top"><el-icon class="formula-help-icon" tabindex="0" aria-label="查看通过率计算公式"><QuestionFilled /></el-icon></el-tooltip></span>
        </template>
  </BasicReportTable>
</template>

<script setup lang="ts">
import BasicReportTable from '../components/BasicReportTable.vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import type { BasicReportTableProps } from '@/types/basicReports'

defineProps<BasicReportTableProps>()


</script>

<style scoped lang="scss">
.formula-header {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.formula-help-icon {
  color: var(--el-color-primary);
  cursor: help;
  font-size: 14px;


  &:focus-visible {
    outline: 2px solid var(--el-color-primary-light-5);
    outline-offset: 2px;
    border-radius: 50%;
  }

}
</style>
