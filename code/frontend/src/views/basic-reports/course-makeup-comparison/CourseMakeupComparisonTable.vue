<!-- 课程补考对比：通过 AppTable 的列插槽保留两层表头、课程合并及原比例显示。 -->
<template>
  <AppTable
    :columns="definition.columns"
    :data="result?.rows || []"
    :storage-key="`basic-report:${definition.reportId}`"
    :pagination="false"
    :span-method="spanMethod"
    :row-class-name="rowClassName"
    border
    empty-text=""
  >
    <!-- 原页面没有显示工具或分页；固定分组列只负责展示后端返回的完整结果。 -->
    <template #columns>
      <el-table-column prop="course" label="科目" min-width="190" fixed="left" align="center">
        <template #default="{ row }"><span class="multiline-cell">{{ row.course }}</span></template>
      </el-table-column>
      <el-table-column prop="majorName" label="专业" min-width="160" fixed="left" align="center" />
      <el-table-column prop="majorStudentCount" label="专业人数" min-width="100" align="center" />
      <el-table-column label="补考前数据" align="center">
        <el-table-column prop="failedBeforeStudents" label="挂科人数" min-width="100" align="center" />
        <el-table-column prop="failedBeforeRate" label="专业挂科率" min-width="120" align="center">
          <template #default="{ row }">{{ formatRate(row.failedBeforeRate) }}</template>
        </el-table-column>
        <el-table-column prop="failedBeforeCourseTotal" label="挂科总人数" min-width="110" align="center" />
        <el-table-column prop="failedBeforeCourseRate" label="总挂科率" min-width="110" align="center">
          <template #default="{ row }">{{ formatRate(row.failedBeforeCourseRate) }}</template>
        </el-table-column>
      </el-table-column>
      <el-table-column label="补考后数据" align="center">
        <el-table-column prop="failedAfterStudents" label="挂科人数" min-width="100" align="center" />
        <el-table-column prop="failedAfterRate" label="专业挂科率" min-width="120" align="center">
          <template #default="{ row }">{{ formatRate(row.failedAfterRate) }}</template>
        </el-table-column>
        <el-table-column prop="failedAfterCourseTotal" label="挂科总人数" min-width="110" align="center" />
        <el-table-column prop="failedAfterCourseRate" label="总挂科率" min-width="110" align="center">
          <template #default="{ row }">{{ formatRate(row.failedAfterCourseRate) }}</template>
        </el-table-column>
      </el-table-column>
      <el-table-column prop="makeupPassedStudents" label="补考通过人数" min-width="120" align="center" />
    </template>
    <template #empty><div class="blank-table-body">{{ result ? '当前授权范围和筛选条件下无数据' : '' }}</div></template>
  </AppTable>
</template>

<script setup lang="ts">
import AppTable from '@/components/AppTable.vue'
import type { BasicReportTableProps } from '@/types/basicReports'

defineProps<BasicReportTableProps>()

// 按原精度显示接口比例，空值保留破折号。
function formatRate(value: number | null | undefined) { return value == null ? '—' : `${(value * 100).toFixed(2)}%` }
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
