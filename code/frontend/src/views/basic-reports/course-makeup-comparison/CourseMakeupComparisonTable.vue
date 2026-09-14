<!-- 补考前后课程通过情况对比：保持原分组表头、课程合并及比例显示。 -->
<template>
<el-table :data="result?.rows || []" border :span-method="spanMethod" :row-class-name="rowClassName" empty-text="">
        <el-table-column prop="course" label="科目" min-width="190" fixed="left"><template #default="{ row }"><span class="multiline-cell">{{ row.course }}</span></template></el-table-column>
        <el-table-column prop="majorName" label="专业" min-width="160" fixed="left" />
        <el-table-column prop="majorStudentCount" label="专业人数" min-width="100" align="center" />
        <el-table-column label="补考前数据" align="center">
          <el-table-column prop="failedBeforeStudents" label="挂科人数" min-width="100" align="center" />
          <el-table-column prop="failedBeforeRate" label="专业挂科率" min-width="120" align="center"><template #default="{ row }">{{ formatRate(row.failedBeforeRate) }}</template></el-table-column>
          <el-table-column prop="failedBeforeCourseTotal" label="挂科总人数" min-width="110" align="center" />
          <el-table-column prop="failedBeforeCourseRate" label="总挂科率" min-width="110" align="center"><template #default="{ row }">{{ formatRate(row.failedBeforeCourseRate) }}</template></el-table-column>
        </el-table-column>
        <el-table-column label="补考后数据" align="center">
          <el-table-column prop="failedAfterStudents" label="挂科人数" min-width="100" align="center" />
          <el-table-column prop="failedAfterRate" label="专业挂科率" min-width="120" align="center"><template #default="{ row }">{{ formatRate(row.failedAfterRate) }}</template></el-table-column>
          <el-table-column prop="failedAfterCourseTotal" label="挂科总人数" min-width="110" align="center" />
          <el-table-column prop="failedAfterCourseRate" label="总挂科率" min-width="110" align="center"><template #default="{ row }">{{ formatRate(row.failedAfterCourseRate) }}</template></el-table-column>
        </el-table-column>
        <el-table-column prop="makeupPassedStudents" label="补考通过人数" min-width="120" align="center" />
        <template #empty><div class="blank-table-body">{{ result ? '当前授权范围和筛选条件下无数据' : '' }}</div></template>
      </el-table>
</template>

<script setup lang="ts">
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
