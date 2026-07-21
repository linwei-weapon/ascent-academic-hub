<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">决策配置</h2>
        <p class="sa-page-sub">AI管理决策的学校级配置：LLM 增强接入与各 Skill 阈值。阈值仅白名单内可调，全部变更走「草稿→发布→回滚」并留审计链。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- LLM 增强配置 -->
    <section class="sa-card">
      <div class="sa-card-title">
        LLM 增强配置
        <el-tag size="small" :type="llm.ready ? 'success' : 'info'" effect="plain" class="title-tag">
          {{ llm.ready ? '已就绪' : (llm.enabled ? '未配齐' : '未启用') }}
        </el-tag>
      </div>
      <el-alert type="info" :closable="false" show-icon class="llm-note"
        title="LLM 只做叙事：全部数字由 Skill 代码产出，模型输出经数字校验，失败自动回退规则版并如实标注。密钥仅存服务端，页面不回显。" />
      <el-form label-width="150px" class="llm-form">
        <el-form-item label="启用 LLM 增强">
          <el-switch v-model="llm.enabled" />
          <span class="form-hint">关闭时系统为完整规则版，不影响任何功能</span>
        </el-form-item>
        <el-form-item label="接口地址 base_url">
          <el-input v-model="llm.base_url" placeholder="OpenAI 兼容协议，如 https://dashscope.aliyuncs.com/compatible-mode/v1 或校内私有化网关" />
        </el-form-item>
        <el-form-item label="模型 model">
          <el-input v-model="llm.model" placeholder="如 qwen-plus / 私有化模型名" style="max-width: 360px" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="llmApiKey" type="password" show-password style="max-width: 360px"
            :placeholder="llm.has_api_key ? `已保存（尾号 ${llm.api_key_tail}），输入以更换；留空保持不变` : '未设置'" />
        </el-form-item>
        <el-form-item label="超时 / 重试">
          <el-input-number v-model="llm.timeout_seconds" :min="1" :max="120" />
          <span class="inline-unit">秒</span>
          <el-input-number v-model="llm.max_retries" :min="0" :max="1" />
          <span class="inline-unit">次（防线：重试不超过 1 次）</span>
        </el-form-item>
        <el-form-item label="能力开关">
          <el-checkbox v-model="llm.narrative_enabled">简报叙事增强</el-checkbox>
          <el-checkbox v-model="llm.chat_enabled">对话编排（决策追问）</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingLlm" @click="saveLlm">保存配置</el-button>
          <el-button :loading="testingLlm" @click="testLlm">测试连接</el-button>
          <span v-if="testResult" class="test-result" :class="{ ok: testResult.success }">
            {{ testResult.success ? `连接成功（${testResult.model}）` : `连接失败：${testResult.kind}${testResult.detail ? ' · ' + testResult.detail : ''}` }}
          </span>
        </el-form-item>
      </el-form>
    </section>

    <!-- Skill 阈值配置 -->
    <section class="sa-card">
      <div class="sa-card-title">
        Skill 阈值配置
        <span class="extra">默认值由产品给出；学校覆写只落在白名单范围，公式与数据来源不可改</span>
      </div>
      <el-tabs v-model="activeSkill">
        <el-tab-pane v-for="skill in skills" :key="skill.skill_id" :label="skill.name" :name="skill.skill_id">
          <p class="mq">{{ skill.management_question }}</p>
          <div class="ver-line">
            <span>生效版本</span>
            <el-tag size="small" :type="skill.config_version === 'product_default' ? 'info' : 'success'" effect="plain">
              {{ skill.config_version === 'product_default' ? '产品默认' : skill.config_version }}
            </el-tag>
            <el-tag v-if="latestDraft(skill)" size="small" type="warning" effect="plain">
              未发布草稿 {{ latestDraft(skill)?.version_no }}
            </el-tag>
            <el-button link type="primary" size="small" @click="openVersions(skill)">版本历史</el-button>
          </div>

          <el-form :label-width="230" class="skill-form">
            <el-form-item v-for="key in boundKeys(skill)" :key="key" :label="labelOf(key)">
              <template v-if="isNumericBound(skill, key)">
                <el-input-number v-model="forms[skill.skill_id][key]"
                  :min="skill.config_bounds[key].min" :max="skill.config_bounds[key].max"
                  :precision="skill.config_bounds[key].type === 'int' ? 0 : 2"
                  :step="skill.config_bounds[key].type === 'int' ? 1 : 0.05" />
              </template>
              <el-select v-else-if="skill.config_bounds[key].type === 'list'"
                v-model="forms[skill.skill_id][key]" multiple filterable allow-create
                default-first-option no-data-text="输入后回车添加" placeholder="字符串列表，逐项回车添加"
                style="width: 100%" />
              <el-input v-else v-model="forms[skill.skill_id][key]" style="max-width: 360px" />
              <div class="def-line">
                默认 {{ fmt(skill.default_config[key]) }} · 当前生效 {{ fmt(skill.active_config[key]) }}
                <template v-if="boundRange(skill, key)"> · 可调范围 {{ boundRange(skill, key) }}</template>
              </div>
            </el-form-item>

            <el-form-item label="变更原因">
              <el-input v-model="reasons[skill.skill_id]" maxlength="200" show-word-limit
                placeholder="说明为什么调整（必填，进入版本审计链）" style="max-width: 520px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="acting"
                :disabled="!isDirty(skill) || (reasons[skill.skill_id] || '').trim().length < 2"
                @click="saveDraft(skill)">保存草稿</el-button>
              <el-button type="success" :loading="acting" :disabled="!latestDraft(skill)"
                @click="publishLatest(skill)">发布草稿</el-button>
              <el-button :disabled="!isDirty(skill)" @click="resetForm(skill)">还原为生效值</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </section>

    <!-- 版本历史 -->
    <el-drawer v-model="verVisible" :title="`版本历史 · ${verSkill?.name || ''}`" size="620px">
      <el-table :data="verSkill?.versions || []" size="small">
        <el-table-column prop="version_no" label="版本" width="110" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="change_reason" label="变更原因" min-width="150" show-overflow-tooltip />
        <el-table-column label="创建/发布" width="170">
          <template #default="{ row }">
            <div class="ver-meta">{{ row.created_by }} · {{ shortTime(row.created_at) }}</div>
            <div v-if="row.published_at" class="ver-meta">发布 {{ row.published_by }} · {{ shortTime(row.published_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'draft'" link type="success" size="small"
              :loading="acting" @click="publishVersion(verSkill!, row)">发布</el-button>
            <el-button v-else link type="warning" size="small" :loading="acting"
              @click="rollbackVersion(verSkill!, row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!verSkill?.versions?.length" description="尚无学校配置版本（当前为产品默认）" :image-size="70" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { LlmConfigView, SkillConfigInfo, SkillConfigVersion, TagType } from '@/types/decision'
import {
  createSkillConfigDraft, getDecisionLlmConfig, getDecisionSkillConfigs,
  publishSkillConfig, rollbackSkillConfig, saveDecisionLlmConfig,
  testDecisionLlmConnection,
} from '@/utils/decision'

const loading = ref(false)
const acting = ref(false)
const skills = ref<SkillConfigInfo[]>([])
const activeSkill = ref('')
const forms = reactive<Record<string, Record<string, any>>>({})
const reasons = reactive<Record<string, string>>({})
const verVisible = ref(false)
const verSkill = ref<SkillConfigInfo | null>(null)

const llm = reactive<Omit<LlmConfigView, 'has_api_key' | 'api_key_tail' | 'ready'> & {
  has_api_key: boolean; api_key_tail: string; ready: boolean
}>({
  enabled: false, base_url: '', model: '', timeout_seconds: 20, max_retries: 1,
  narrative_enabled: true, chat_enabled: true, has_api_key: false, api_key_tail: '', ready: false,
})
const llmApiKey = ref('')
const savingLlm = ref(false)
const testingLlm = ref(false)
const testResult = ref<{ success: boolean; kind?: string; detail?: string; model?: string } | null>(null)

const FIELD_LABELS: Record<string, string> = {
  target_grade: '目标毕业届', near_grad_terms: '临近毕业学期',
  coordination_min_students: '校级协调最小人数', coordination_min_majors: '协调覆盖最小专业数',
  structural_gap_min_students: '结构性缺口最小人数', max_course_signals: '课程信号数量上限',
  persistent_multiplier: '持续偏高倍数', persistent_floor: '持续偏高下限(未通过率)',
  spike_multiplier: '突增倍数', spike_delta_pp: '突增百分点', min_sample: '最小样本量',
  high_impact_students: '高影响人数线', required_weight: '必修课权重', improve_delta_pp: '向好判定百分点',
  fail_per_required: '每门必修未通过得分', fail_cap: '未通过得分上限',
  gpa_drop_mild: '绩点下滑轻度阈值', gpa_drop_severe: '绩点下滑重度阈值',
  trend_mild: '趋势轻度得分', trend_severe: '趋势重度得分',
  stall_days: '滞留天数阈值', stall_score: '滞留得分', stale_days: '陈旧预警天数', top_n: '本周队列规模',
  high_enrolled: '大规模分界线(人)', mid_enrolled: '中规模分界线(人)', title_gap_ratio: '职称数据缺口比例',
}

function labelOf(key: string): string {
  const label = FIELD_LABELS[key]
  return label ? `${label}（${key}）` : key
}
function fmt(value: any): string {
  if (Array.isArray(value)) return value.join('、') || '—'
  return value === undefined || value === null ? '—' : String(value)
}
function boundKeys(skill: SkillConfigInfo): string[] {
  return Object.keys(skill.config_bounds || {})
}
function isNumericBound(skill: SkillConfigInfo, key: string): boolean {
  const t = skill.config_bounds[key]?.type
  return t === 'int' || t === 'float'
}
function boundRange(skill: SkillConfigInfo, key: string): string {
  const b = skill.config_bounds[key]
  if (!isNumericBound(skill, key)) return ''
  return `${b.min} ~ ${b.max}`
}
function latestDraft(skill: SkillConfigInfo): SkillConfigVersion | undefined {
  return (skill.versions || []).find(v => v.status === 'draft')
}
function isDirty(skill: SkillConfigInfo): boolean {
  const form = forms[skill.skill_id] || {}
  return boundKeys(skill).some(key =>
    JSON.stringify(form[key] ?? null) !== JSON.stringify(skill.active_config[key] ?? null))
}
function statusLabel(status: string): string {
  return { draft: '草稿', published: '生效中', retired: '已退役' }[status] || status
}
function statusTag(status: string): TagType {
  return ({ draft: 'warning', published: 'success', retired: 'info' } as Record<string, TagType>)[status] || 'info'
}
function shortTime(value?: string | null): string {
  return (value || '').replace('T', ' ').slice(5, 16)
}

async function load() {
  loading.value = true
  try {
    const [skillData, llmData] = await Promise.all([getDecisionSkillConfigs(), getDecisionLlmConfig()])
    skills.value = skillData.items
    if (!activeSkill.value || !skills.value.some(s => s.skill_id === activeSkill.value)) {
      activeSkill.value = skills.value[0]?.skill_id || ''
    }
    for (const skill of skills.value) resetForm(skill)
    Object.assign(llm, llmData)
    llmApiKey.value = ''
    testResult.value = null
  } finally {
    loading.value = false
  }
}

function resetForm(skill: SkillConfigInfo) {
  const form: Record<string, any> = {}
  for (const key of boundKeys(skill)) {
    const value = skill.active_config[key]
    form[key] = Array.isArray(value) ? [...value] : value
  }
  forms[skill.skill_id] = form
}

function overrideOf(skill: SkillConfigInfo): Record<string, any> {
  // 只提交与产品默认不同的键（保持覆写最小化，默认演进时自然跟随）
  const out: Record<string, any> = {}
  const form = forms[skill.skill_id] || {}
  for (const key of boundKeys(skill)) {
    if (JSON.stringify(form[key] ?? null) !== JSON.stringify(skill.default_config[key] ?? null)) {
      out[key] = form[key]
    }
  }
  return out
}

async function saveDraft(skill: SkillConfigInfo) {
  const reason = (reasons[skill.skill_id] || '').trim()
  acting.value = true
  try {
    await createSkillConfigDraft(skill.skill_id, overrideOf(skill), reason)
    ElMessage.success('草稿已保存，发布后生效')
    reasons[skill.skill_id] = ''
    await load()
  } finally {
    acting.value = false
  }
}

async function publishVersion(skill: SkillConfigInfo, row: SkillConfigVersion) {
  await ElMessageBox.confirm(
    `发布后 ${skill.name} 立即按版本 ${row.version_no} 运行，当前生效版本自动退役。确认发布？`,
    '发布配置', { confirmButtonText: '发布', cancelButtonText: '取消', type: 'warning' })
  acting.value = true
  try {
    await publishSkillConfig(skill.skill_id, row.config_id)
    ElMessage.success(`已发布 ${row.version_no}`)
    await load()
    verSkill.value = skills.value.find(s => s.skill_id === skill.skill_id) || null
  } finally {
    acting.value = false
  }
}

async function publishLatest(skill: SkillConfigInfo) {
  const draft = latestDraft(skill)
  if (!draft) return
  await publishVersion(skill, draft)
}

async function rollbackVersion(skill: SkillConfigInfo, row: SkillConfigVersion) {
  const { value } = await ElMessageBox.prompt(
    `将以 ${row.version_no} 的内容为蓝本生成新的发布版本（审计链保留）。请填写回滚原因：`,
    '回滚配置', { confirmButtonText: '回滚', cancelButtonText: '取消',
      inputPlaceholder: '必填', inputValidator: v => (v || '').trim().length >= 2 || '请填写原因' })
  acting.value = true
  try {
    await rollbackSkillConfig(skill.skill_id, row.config_id, (value || '').trim())
    ElMessage.success('已回滚并发布')
    await load()
    verSkill.value = skills.value.find(s => s.skill_id === skill.skill_id) || null
  } finally {
    acting.value = false
  }
}

function openVersions(skill: SkillConfigInfo) {
  verSkill.value = skill
  verVisible.value = true
}

async function saveLlm() {
  savingLlm.value = true
  try {
    const body: any = {
      enabled: llm.enabled, base_url: llm.base_url.trim(), model: llm.model.trim(),
      timeout_seconds: llm.timeout_seconds, max_retries: llm.max_retries,
      narrative_enabled: llm.narrative_enabled, chat_enabled: llm.chat_enabled,
    }
    if (llmApiKey.value) body.api_key = llmApiKey.value   // 未输入则保持原密钥
    const saved = await saveDecisionLlmConfig(body)
    Object.assign(llm, saved)
    llmApiKey.value = ''
    testResult.value = null
    ElMessage.success('LLM 配置已保存')
  } finally {
    savingLlm.value = false
  }
}

async function testLlm() {
  testingLlm.value = true
  testResult.value = null
  try {
    testResult.value = await testDecisionLlmConnection()
  } finally {
    testingLlm.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sa-head-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.title-tag { margin-left: 10px; }
.llm-note { margin-bottom: 14px; }
.llm-form :deep(.el-form-item) { margin-bottom: 14px; }
.form-hint { margin-left: 10px; color: #909399; font-size: 12px; }
.inline-unit { margin: 0 14px 0 6px; color: #909399; font-size: 12px; }
.test-result { margin-left: 12px; font-size: 12px; color: #c45656; }
.test-result.ok { color: #67c23a; }
.mq { margin: 2px 0 10px; color: #64748b; font-size: 13px; }
.ver-line { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; font-size: 12px; color: #909399; }
.skill-form { max-width: 860px; }
.def-line { width: 100%; color: #94a3b8; font-size: 11px; line-height: 1.6; }
.ver-meta { font-size: 11px; color: #909399; line-height: 1.6; }
</style>
