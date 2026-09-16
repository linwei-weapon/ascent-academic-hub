<template><span class="expert-avatar" :class="appearance.tone" aria-hidden="true"><component :is="appearance.icon" /></span></template>
<script setup lang="ts">
import { computed } from 'vue'
import { Collection, Reading, Switch, Medal, Checked, User } from '@element-plus/icons-vue'
const props = defineProps<{ id: string }>()
const appearances = { program: { icon: Collection, tone: 'violet' }, course: { icon: Reading, tone: 'blue' }, transfer: { icon: Switch, tone: 'teal' }, recommendation: { icon: Medal, tone: 'gold' }, graduation: { icon: Checked, tone: 'rose' } }
const appearance = computed(() => appearances[props.id as keyof typeof appearances] || { icon: User, tone: 'violet' })
</script>
<style scoped>
.expert-avatar{display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:14px;background:#f0ebfa;color:#73569a;flex-shrink:0;border:1px solid #e8def5}.expert-avatar svg{width:25px;height:25px}.blue{background:#eaf1fc;color:#416aab;border-color:#dce7f8}.teal{background:#e9f5f1;color:#377e70;border-color:#d9ece5}.gold{background:#faf2e3;color:#997330;border-color:#efe4cd}.rose{background:#f7edf2;color:#a16383;border-color:#efdee8}
</style>
