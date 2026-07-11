<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/sync'}">数据同步</el-breadcrumb-item>
      <el-breadcrumb-item>数据浏览</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title">同步数据浏览</h2>
    <p class="sa-page-sub">按学校 / 数据类型浏览已同步明细</p>

    <div class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110">
        <template #description>
          <div style="font-size:13px;color:#64748B">暂无可浏览的同步数据</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            学生信息 / 课程成绩 / 培养方案 / 开课计划明细需后端同步接口支持，当前部署为单库直连模式，未接入同步明细数据。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
// 同步数据浏览依赖同步明细接口，当前为单库直连、后端无对应数据源，按空态展示（不构造假数据）。
</script>
