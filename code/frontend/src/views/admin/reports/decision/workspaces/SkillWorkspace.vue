<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports/decision">AI管理决策</el-breadcrumb-item>
      <el-breadcrumb-item to="/admin/reports/decision">决策简报</el-breadcrumb-item>
      <el-breadcrumb-item>{{ result?.skill_name || '专题工作区' }}</el-breadcrumb-item>
    </el-breadcrumb>

    <el-alert v-if="loading" class="loading-alert" type="info" :closable="false" show-icon
      title="正在运行 Skill" description="正在按当前权限范围实时计算本专题信号。" />

    <template v-if="result">
      <div class="ws-head">
        <div>
          <h2 class="sa-page-title">{{ result.skill_name }}</h2>
          <p class="sa-page-sub">{{ result.management_question }}</p>
        </div>
        <div class="ws-meta">
          <el-tag size="small" :type="result.data_readiness?.ready ? 'success' : 'danger'" effect="plain">
            {{ result.data_readiness?.ready ? '数据就绪' : '数据缺失' }}
          </el-tag>
          <el-tag size="small" type="info" effect="plain">配置 {{ result.config_version }}</el-tag>
          <el-tag size="small" type="info" effect="plain">运行 {{ (result.run_at || '').slice(0, 16).replace('T', ' ') }}</el-tag>
          <el-button size="small" :loading="loading" @click="load">重新运行</el-button>
        </div>
      </div>

      <el-alert v-if="!result.data_readiness?.ready" type="error" :closable="false" show-icon
        title="本专题依赖的数据表未就绪，以下为降级输出"
        :description="missingText" class="loading-alert" />

      <component :is="workspaceComp" :result="result" @evidence="openEvidence" />

      <el-collapse v-if="result.exclusions?.length || result.data_boundary" class="boundary">
        <el-collapse-item name="boundary" title="口径边界与显式排除项（建立信任的关键：告诉你检查过什么但判定正常）">
          <p v-if="result.data_boundary" class="boundary-text">{{ result.data_boundary }}</p>
          <ul v-if="result.exclusions?.length">
            <li v-for="(ex, i) in result.exclusions" :key="i"><b>{{ ex.what }}</b> — {{ ex.why }}</li>
          </ul>
        </el-collapse-item>
      </el-collapse>
    </template>

    <el-skeleton v-else-if="loading" animated :rows="8" />

    <EvidenceCard v-model:visible="evidenceVisible" :signal="evidenceSignal" @ask="onAsk" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { DecisionSignal, SkillSection } from '@/types/decision'
import { runDecisionSkill } from '@/utils/decision'
import EvidenceCard from '../components/cards/EvidenceCard.vue'
import GraduationGapWorkspace from './GraduationGapWorkspace.vue'
import CourseQualityWorkspace from './CourseQualityWorkspace.vue'
import AlertPriorityWorkspace from './AlertPriorityWorkspace.vue'
import FacultyStructureWorkspace from './FacultyStructureWorkspace.vue'

const WORKSPACES: Record<string, any> = {
  'graduation-gap': GraduationGapWorkspace,
  'course-quality': CourseQualityWorkspace,
  'alert-priority': AlertPriorityWorkspace,
  'faculty-structure': FacultyStructureWorkspace,
}

const route = useRoute()
const router = useRouter()
const skillId = computed(() => String(route.params.skillId || ''))
const result = ref<(SkillSection & { run_at?: string }) | null>(null)
const loading = ref(false)
const evidenceVisible = ref(false)
const evidenceSignal = ref<DecisionSignal | null>(null)

const workspaceComp = computed(() => WORKSPACES[skillId.value])
const missingText = computed(() =>
  (result.value?.data_readiness?.items || [])
    .filter((it: any) => it.required && !it.available)
    .map((it: any) => `缺失：${it.table}（${it.purpose || '必需表'}）`).join('；') || '依赖数据未就绪')

async function load() {
  if (!workspaceComp.value) {
    router.replace('/admin/reports/decision')
    return
  }
  loading.value = true
  try {
    result.value = await runDecisionSkill(skillId.value)
  } finally {
    loading.value = false
  }
}

function openEvidence(signal: DecisionSignal) {
  evidenceSignal.value = signal
  evidenceVisible.value = true
}

function onAsk() {
  evidenceVisible.value = false
}

watch(skillId, () => { result.value = null; load() })
onMounted(load)
</script>

<style scoped>
.loading-alert { margin: 12px 0; }
.ws-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.ws-meta { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; padding-top: 12px; }
.boundary { margin-top: 4px; }
.boundary-text { margin: 0 0 8px; color: #606266; font-size: 12px; line-height: 1.6; }
.boundary ul { margin: 0; padding-left: 18px; color: #606266; font-size: 12px; line-height: 1.8; }
@media (max-width: 1100px) { .ws-head { display: block; } }
</style>
