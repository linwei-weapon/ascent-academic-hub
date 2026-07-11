<template>
  <span style="display:inline-flex;align-items:center;gap:2px">
    <span>{{ label }}</span>
    <el-tooltip v-if="formula" :content="formula" placement="top" effect="dark">
      <span style="cursor:help;color:#94A3B8;font-size:12px;font-weight:400">ⓘ</span>
    </el-tooltip>
  </span>
</template>
<script setup lang="ts">
defineProps<{ label: string; formula?: string }>();
</script>
