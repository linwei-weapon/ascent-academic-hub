<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">实践教学分析</h2>
        <p class="sa-page-sub">数据来源：实验任务表 + 实习基地表 + 毕业论文管理表 + 创新创业学分记录表</p>
      </div>
    </div>

    <div class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110">
        <template #description>
          <div style="font-size:13px;color:#64748B">暂无实践教学数据</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            该分析依赖「实验任务」「实习基地」「毕业论文」「创新创业学分」四类明细数据，<br />
            当前教务数据中尚未接入此模块，无法生成实验开出率 / 论文质量 / 基地利用 / 创新学分等统计。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
// 实践教学分析依赖 实验任务表/实习基地表/毕业论文管理表/创新创业学分记录表，当前后端无对应数据源，按空态展示（不构造假数据）。
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>
