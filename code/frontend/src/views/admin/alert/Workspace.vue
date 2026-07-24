<template>
  <div>
    <div class="workspace-head">
      <h2 class="sa-page-title">{{ pageTitle }}</h2>
      <p class="sa-page-sub">{{ pageSubtitle }}</p>
    </div>
    <BusinessPageContext source="学籍、成绩、历史预警与当前激活规则" />
    <el-tabs v-model="activeTab" class="alert-workspace" @tab-change="syncTab">
      <el-tab-pane label="预警监控" name="monitor" lazy><AlertMonitor embedded /></el-tab-pane>
      <el-tab-pane v-if="canGovern" label="预警规则" name="rules" lazy>
        <section class="rule-workspace">
          <div class="rule-workspace-head">
            <div>
              <h3>预警规则治理工作区</h3>
              <p>候选关联不会直接产生预警；必须依次完成采纳、影响试算、审核发布和激活。</p>
            </div>
            <el-segmented v-model="ruleView" :options="ruleViewOptions" size="small" />
          </div>
          <div class="governance-flow" aria-label="规则治理流程">
            <span>1 发现候选</span><i>→</i><span>2 采纳为草稿</span><i>→</i>
            <span>3 影响试算</span><i>→</i><span>4 审核发布</span><i>→</i><span>5 激活生效</span>
          </div>
          <RuleGovernance v-if="ruleView==='governance'" alert-rules embedded />
          <RuleDiscovery v-else embedded />
        </section>
      </el-tab-pane>
      <el-tab-pane label="低年级风险观察" name="early-risk" lazy>
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
const ruleView=ref<'governance'|'discovery'>('governance')
const ruleViewOptions=[
  {label:'生产规则与变更',value:'governance'},
  {label:'规则自发现候选',value:'discovery'},
]
const canGovern=computed(()=>{
  const role=authStore.user?.role || ''
  const actions=authStore.user?.permissionContext?.actionPermissions || []
  return ['dean','admin','quality_office','school_leader'].includes(role)
    || actions.includes('rule.discovery.manage')
})
const validTabs=computed(()=>new Set(canGovern.value?['monitor','rules','early-risk']:['monitor','early-risk']))
const activeTab=ref(validTabs.value.has(String(route.query.tab))?String(route.query.tab):'monitor')
const pageSubtitle=computed(()=>canGovern.value
  ? '查看当前预警学生、核查状态和历史观察，并在同一工作区治理预警规则。'
  : '查看当前授权范围内的预警学生、核查状态和低年级历史风险观察。')
watch(()=>route.query.tab,(value)=>{const tab=String(value||'monitor');if(validTabs.value.has(tab))activeTab.value=tab})
watch(canGovern,(allowed)=>{if(!allowed&&activeTab.value==='rules'){activeTab.value='monitor';syncTab('monitor')}})
function syncTab(tab:string|number){router.replace({path:'/admin/alert',query:tab==='monitor'?{}:{tab:String(tab)}})}
</script>

<style scoped>
.alert-workspace :deep(.el-tabs__header){margin-bottom:16px}
.workspace-head .sa-page-title{margin-bottom:2px}
.alert-workspace :deep(.el-tabs__item){font-weight:600}
.rule-workspace-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:10px}
.rule-workspace-head h3{margin:0;color:var(--sa-text);font-size:17px}
.rule-workspace-head p{margin:6px 0 0;color:var(--sa-muted);font-size:12px;line-height:1.6}
.governance-flow{display:flex;align-items:center;gap:8px;margin-bottom:14px;padding:9px 12px;border:1px solid #dbeafe;border-radius:8px;background:#f8fbff;color:#475569;font-size:11px}
.governance-flow span{font-weight:600}.governance-flow i{color:#94a3b8;font-style:normal}
.rule-workspace :deep(.sa-tabs>.el-tabs__header){display:none}
.embedded-topic :deep(.crumb),.embedded-topic :deep(.sa-page-title),.embedded-topic :deep(.sa-page-sub){display:none}
@media(max-width:760px){.rule-workspace-head{flex-direction:column}.governance-flow{align-items:flex-start;flex-direction:column}.governance-flow i{display:none}}
</style>
