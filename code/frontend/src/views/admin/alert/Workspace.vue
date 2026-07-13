<template>
  <div>
    <el-tabs v-model="activeTab" class="alert-workspace" @tab-change="syncTab">
      <el-tab-pane label="预警监控" name="monitor"><AlertMonitor /></el-tab-pane>
      <el-tab-pane v-if="canGovern" label="预警规则" name="rules"><RuleGovernance alert-rules embedded /></el-tab-pane>
      <el-tab-pane v-if="canGovern" label="规则自发现" name="discovery"><RuleDiscovery embedded /></el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authStore } from '@/store/auth'
import AlertMonitor from './index.vue'
import RuleDiscovery from './Discovery.vue'
import RuleGovernance from '../settings/index.vue'

const route=useRoute(),router=useRouter()
const canGovern=computed(()=>authStore.user?.role==='dean')
const valid=new Set(canGovern.value?['monitor','rules','discovery']:['monitor'])
const activeTab=ref(valid.has(String(route.query.tab))?String(route.query.tab):'monitor')
watch(()=>route.query.tab,(value)=>{const tab=String(value||'monitor');if(valid.has(tab))activeTab.value=tab})
function syncTab(tab:string|number){router.replace({path:'/admin/alert',query:tab==='monitor'?{}:{tab:String(tab)}})}
</script>

<style scoped>.alert-workspace :deep(.el-tabs__header){margin-bottom:16px}.alert-workspace :deep(.el-tabs__item){font-weight:600}</style>
