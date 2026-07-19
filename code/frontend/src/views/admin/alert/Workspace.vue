<template>
  <div>
    <div class="workspace-head">
      <h2 class="sa-page-title">{{ pageTitle }}</h2>
      <p class="sa-page-sub">统一查看学校预警结果、历史变化，并在同一工作区治理预警规则与候选规则。</p>
    </div>
    <BusinessPageContext source="学籍、成绩、历史预警与当前激活规则" />
    <el-tabs v-model="activeTab" class="alert-workspace" @tab-change="syncTab">
      <el-tab-pane label="预警监控" name="monitor"><AlertMonitor embedded /></el-tab-pane>
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
      <el-tab-pane label="低年级风险观察" name="early-risk">
        <div class="embedded-topic"><EarlySetback /></div>
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
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import EarlySetback from '../reports/EarlySetback.vue'
import { useBusinessPageTitle } from '@/utils/businessPage'

const route=useRoute(),router=useRouter()
const pageTitle=useBusinessPageTitle('/admin/alert','学业预警监控')
const canGovern=computed(()=>['dean','admin'].includes(authStore.user?.role || ''))
const valid=new Set(canGovern.value?['monitor','rules','early-risk']:['monitor','early-risk'])
const activeTab=ref(valid.has(String(route.query.tab))?String(route.query.tab):'monitor')
watch(()=>route.query.tab,(value)=>{const tab=String(value||'monitor');if(valid.has(tab))activeTab.value=tab})
function syncTab(tab:string|number){router.replace({path:'/admin/alert',query:tab==='monitor'?{}:{tab:String(tab)}})}
</script>

<style scoped>
.alert-workspace :deep(.el-tabs__header){margin-bottom:16px}
.workspace-head .sa-page-title{margin-bottom:2px}
.alert-workspace :deep(.el-tabs__item){font-weight:600}
.discovery-section{margin-top:22px;padding-top:22px;border-top:1px solid var(--sa-border)}
.section-heading{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
.section-heading h3{margin:0;color:var(--sa-text);font-size:17px}
.section-heading p{margin:6px 0 0;color:var(--sa-muted);font-size:12px;line-height:1.6}
.embedded-topic :deep(.crumb),.embedded-topic :deep(.sa-page-title),.embedded-topic :deep(.sa-page-sub){display:none}
</style>
