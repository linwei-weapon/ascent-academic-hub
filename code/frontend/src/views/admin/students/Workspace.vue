<template>
  <MyScope v-if="isRelationshipWorkspace" />
  <Analysis v-else />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { authStore } from '@/store/auth'
import Analysis from './Analysis.vue'
import MyScope from './MyScope.vue'

const RELATIONSHIP_ROLES = new Set(['counselor', 'class_adviser', 'mentor'])

/**
 * 学生成长与学业分析只有一个产品入口。
 * 页面表达按当前工作身份切换，数据范围仍由每个后端接口重新鉴权。
 */
const isRelationshipWorkspace = computed(() =>
  RELATIONSHIP_ROLES.has(
    authStore.user?.permissionContext?.activeRole || authStore.user?.role || '',
  ))
</script>
