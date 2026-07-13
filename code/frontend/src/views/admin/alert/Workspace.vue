<template>
  <div>
    <el-tabs v-model="activeTab" class="alert-workspace" @tab-change="syncTab">
      <el-tab-pane label="预警监控" name="monitor"><AlertMonitor /></el-tab-pane>
      <el-tab-pane v-if="canGovern" label="预警规则" name="rules">
        <RuleGovernance alert-rules embedded />
        <div class="discovery-section">
          <div class="section-heading">
            <div>
              <h3>规则自发现</h3>
              <p>基于历史预警与学业结果识别候选关联，采纳后仍需进入上方规则变更流程试算、复核和发布。</p>
            </div>
          </div>
          <RuleDiscovery embedded />
        </div>
      </el-tab-pane>
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
const valid=new Set(canGovern.value?['monitor','rules']:['monitor'])
const activeTab=ref(valid.has(String(route.query.tab))?String(route.query.tab):'monitor')
watch(()=>route.query.tab,(value)=>{const tab=String(value||'monitor');if(valid.has(tab))activeTab.value=tab})
function syncTab(tab:string|number){router.replace({path:'/admin/alert',query:tab==='monitor'?{}:{tab:String(tab)}})}
</script>

<style scoped>
.alert-workspace :deep(.el-tabs__header){margin-bottom:16px}
.alert-workspace :deep(.el-tabs__item){font-weight:600}
.discovery-section{margin-top:22px;padding-top:22px;border-top:1px solid var(--sa-border)}
.section-heading{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
.section-heading h3{margin:0;color:var(--sa-text);font-size:17px}
.section-heading p{margin:6px 0 0;color:var(--sa-muted);font-size:12px;line-height:1.6}
</style>
