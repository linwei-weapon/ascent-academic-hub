<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">学校管理</h2>
        <p class="sa-page-sub">合作学校协议与部署信息</p>
      </div>
    </div>

    <div class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110">
        <template #description>
          <div style="font-size:13px;color:#64748B">暂无合作学校数据</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            合作学校列表需后端学校管理接口支持，当前部署为单校模式，未接入多校管理数据。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
// 学校管理依赖多校管理接口，当前为单校部署、后端无对应数据源，按空态展示（不构造假数据）。
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
</style>
