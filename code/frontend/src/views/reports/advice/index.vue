<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports/decision">AI管理决策</el-breadcrumb-item>
      <el-breadcrumb-item>专家问策</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="page-head">
      <div>
        <h2 class="sa-page-title">专家问策</h2>
        <p class="sa-page-sub">选择一位专家，开始对话 —— 每位专家只回答本领域问题，建议必附依据。</p>
      </div>
      <el-tag v-if="semester" size="small" type="info" effect="plain" class="semester-tag">
        数据学期 {{ semester }}
      </el-tag>
    </div>

    <div v-if="experts.length" class="expert-grid">
      <div v-for="ex in experts" :key="ex.skill_id" class="sa-card expert-card">
        <div class="card-head">
          <span class="expert-icon">{{ ex.icon || '策' }}</span>
          <div class="head-text">
            <b class="expert-title">{{ ex.title || ex.name }}</b>
            <span class="expert-name">{{ ex.name }}</span>
          </div>
          <el-badge v-if="ex.signal_count" :value="ex.signal_count" type="warning" class="sig-badge" />
          <el-button type="primary" link class="enter-btn" @click="enter(ex)">
            进入问策<el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>

        <p class="mgmt-q">{{ ex.management_question }}</p>

        <div class="top-signal">
          <template v-if="ex.top_signal">
            <el-tag size="small" :type="SEVERITY_META[ex.top_signal.severity]?.tag || 'info'" effect="dark">
              {{ SEVERITY_META[ex.top_signal.severity]?.label || ex.top_signal.severity }}
            </el-tag>
            <span class="signal-line">今日最关键：{{ ex.top_signal.headline }}</span>
          </template>
          <template v-else>
            <el-tag size="small" type="success" effect="plain">正常</el-tag>
            <span class="signal-line muted">今日无异常信号</span>
          </template>
        </div>
      </div>
    </div>

    <el-skeleton v-else-if="loading" animated :rows="6" />
    <el-empty v-else description="专家库加载失败或暂无可用专家" />

    <div class="sa-card boundary-bar">
      只读、不办业务：对话不产生任何办理动作；每位专家只回答本领域问题，越界问题会被拒答并指路到对应专家；
      所有数字来自确定性代码，AI 不创造指标。
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import type { AdviceExpert } from '@/types/decision'
import { SEVERITY_META } from '@/types/decision'
import { getAdviceExperts } from '@/utils/decision'

const router = useRouter()
const experts = ref<AdviceExpert[]>([])
const loading = ref(false)
const semester = ref('')

function enter(ex: AdviceExpert) {
  router.push(`/admin/reports/advice/${encodeURIComponent(ex.skill_id)}`)
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await getAdviceExperts()
    experts.value = data.items || []
    // 学期字段不在专家接口中，沿用卡片内口径，不在此页编造
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.semester-tag { margin-top: 14px; }
.expert-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 14px 0; }
.expert-card { display: flex; flex-direction: column; gap: 10px; }
.card-head { display: flex; align-items: center; gap: 10px; }
.expert-icon { width: 38px; height: 38px; border-radius: 10px; background: #4f46e5; color: #fff;
  font-size: 18px; display: grid; place-items: center; flex-shrink: 0; }
.head-text { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.expert-title { font-size: 15px; color: #0f172a; }
.expert-name { font-size: 12px; color: #909399; }
.sig-badge { flex-shrink: 0; }
.enter-btn { flex-shrink: 0; font-size: 13px; }
.mgmt-q { margin: 0; font-size: 13px; color: #475569; line-height: 1.7; }
.top-signal { display: flex; align-items: center; gap: 8px; margin-top: auto;
  border-top: 1px dashed #ebeef5; padding-top: 10px; }
.signal-line { font-size: 12px; color: #334155; line-height: 1.5;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.signal-line.muted { color: #909399; }
.boundary-bar { font-size: 12px; color: #909399; line-height: 1.8; }
@media (max-width: 1100px) {
  .expert-grid { grid-template-columns: 1fr; }
}
</style>
