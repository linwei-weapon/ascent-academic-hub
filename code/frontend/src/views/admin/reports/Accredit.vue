<template>
  <div>
    <el-breadcrumb separator="›" style="margin-bottom:12px">
      <el-breadcrumb-item :to="{path:'/admin/reports'}">报表中心</el-breadcrumb-item>
      <el-breadcrumb-item>认证评估报表</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title">认证评估报表</h2>
    <p class="sa-page-sub">支撑本科教育教学审核评估 + 工程教育专业认证 + 高基报表 · 数据自动从教务系统汇总</p>

    <div class="sa-card" style="margin-top:14px">
      <el-empty :image-size="110">
        <template #description>
          <div style="font-size:13px;color:#64748B">暂无认证评估数据</div>
          <div style="font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.7">
            审核评估指标体系达成度、工程教育认证通用标准、高基报表均依赖<br />
            「评估指标—课程支撑—达成度评价」专项数据，当前教务数据中尚未接入此明细，无法自动汇总生成。
          </div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
// 认证评估报表（审核评估/工程教育认证/高基报表）依赖评估指标体系与达成度评价数据，当前后端无对应数据源，按空态展示（不构造假数据）。
</script>
