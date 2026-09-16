<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">数据同步监控</h2>
        <p class="sa-page-sub">每校四类数据独立同步 · 自动重试 · 同步日志可追溯</p>
      </div>
    </div>

    <div class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110">
        <template #description>
          <div style="font-size:13px;color:#64748B">暂无数据同步记录</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            同步状态、行数、校验失败与同步日志需后端数据同步接口支持，当前部署为单库直连模式，未接入同步调度数据。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
// 数据同步监控依赖同步调度接口，当前为单库直连、后端无对应数据源，按空态展示（不构造假数据）。
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>
