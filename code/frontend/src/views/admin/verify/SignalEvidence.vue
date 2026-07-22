<template>
  <!-- 查证窗口（R2）：新开浏览器窗口中的只读证据页，无侧边导航。
       数据全部来自后端证据包接口；越权或信号不存在时显示明确空态。 -->
  <div class="verify-page">
    <header class="verify-top">
      <span class="brand">智能学业分析平台 · 信号查证</span>
      <span v-if="pack" class="meta">
        {{ pack.semester }} · 生成于 {{ pack.generated_at }} · {{ methodLabel }}
      </span>
    </header>

    <main v-if="loading" class="state"><el-icon class="is-loading" :size="28"><Loading /></el-icon><p>正在载入证据…</p></main>

    <main v-else-if="error" class="state">
      <el-icon :size="28" color="#c45656"><CircleClose /></el-icon>
      <p class="err-title">{{ error }}</p>
      <p class="err-hint">信号可能已消除，或不在您当前工作身份的数据权限范围内。</p>
    </main>

    <main v-else-if="pack" class="body">
      <!-- 判断区 -->
      <section class="card judgement" :class="`sev-${sig.severity}`">
        <div class="tags">
          <el-tag size="small" :type="severityMeta(sig).tag" effect="dark">{{ severityMeta(sig).label }}</el-tag>
          <el-tag size="small" :type="changeMeta(sig).tag" effect="plain">{{ changeMeta(sig).label }}</el-tag>
          <el-tag v-if="sig.hotspot" size="small" type="danger" effect="plain">跨专题热点</el-tag>
          <span class="from">来自专家：{{ pack.skill.skill_name }}（{{ pack.skill.management_question }}）</span>
        </div>
        <h1 class="headline">{{ sig.headline }}</h1>
        <p class="consequence">暂不处理：{{ sig.consequence }}</p>
      </section>

      <!-- 关键数字 -->
      <section class="card">
        <h2>关键数字</h2>
        <div class="facts">
          <div v-for="[k, v] in allFacts" :key="k" class="fact">
            <em>{{ k }}</em><b>{{ v }}</b>
          </div>
        </div>
        <p v-if="!allFacts.length" class="empty">该信号无结构化数字，判断依据见下方证据明细。</p>
      </section>

      <!-- 证据明细 -->
      <section class="card">
        <h2>证据明细</h2>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="管理对象">{{ entityLabel }}</el-descriptions-item>
          <el-descriptions-item label="数据表"><code>{{ sig.evidence.table || '—' }}</code></el-descriptions-item>
          <el-descriptions-item label="筛选条件"><code>{{ sig.evidence.condition || '—' }}</code></el-descriptions-item>
          <el-descriptions-item label="数据时效">{{ pack.data_freshness || sig.evidence.freshness || '—' }}</el-descriptions-item>
          <el-descriptions-item label="置信度">{{ confidenceLabel(sig) }}</el-descriptions-item>
          <el-descriptions-item label="配置版本">{{ pack.skill.config_version || '—' }}</el-descriptions-item>
        </el-descriptions>
        <p class="boundary">口径边界：{{ sig.data_boundary || pack.skill.data_boundary || '—' }}</p>
        <div v-if="pack.skill.exclusions?.length" class="exclusions">
          <p class="ex-title">显式排除项（本结论不覆盖）：</p>
          <p v-for="(ex, i) in pack.skill.exclusions" :key="i" class="ex-item">· {{ ex.what }} —— {{ ex.why }}</p>
        </div>
      </section>

      <!-- 建议动作（只读参考，不产生任何办理动作） -->
      <section class="card">
        <h2>建议动作（供人工参考）</h2>
        <div class="action-box">
          <div><span>建议责任</span><b>{{ sig.action.owner || '—' }}</b></div>
          <div><span>建议时限</span><b class="when">{{ sig.action.when || '—' }}</b></div>
          <p>{{ sig.action.what }}</p>
          <small v-if="sig.action.rationale">{{ sig.action.rationale }}</small>
        </div>
        <p class="note">本平台只输出决策建议与核查依据，不执行任何办理操作；处置请走学校既有管理流程。</p>
      </section>

      <!-- 深度核查入口：最后一跳才进分析页 -->
      <section v-if="sig.evidence.verify_route" class="card deep">
        <h2>需要更多数据？</h2>
        <el-button type="primary" plain @click="goDeep">前往专题深度核查（进入分析页面）</el-button>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loading, CircleClose } from '@element-plus/icons-vue'
import { getSignalEvidence } from '@/utils/decision'
import type { SignalEvidencePack } from '@/types/decision'
import { SEVERITY_META, CHANGE_META } from '@/types/decision'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const pack = ref<SignalEvidencePack | null>(null)

const sig = computed(() => pack.value!.signal)
const allFacts = computed(() => Object.entries(pack.value?.signal.facts || {}))
const methodLabel = computed(() =>
  pack.value?.generation_method === 'llm_enhanced' ? 'LLM增强生成' : '规则模板生成')
const entityLabel = computed(() => {
  const e = pack.value?.signal.entity
  return e ? `${e.name}（${e.type} · ${e.id}）` : '—'
})

function severityMeta(s: SignalEvidencePack['signal']) {
  return SEVERITY_META[s.severity] || SEVERITY_META.low
}
function changeMeta(s: SignalEvidencePack['signal']) {
  return CHANGE_META[s.change] || CHANGE_META.ongoing
}
function confidenceLabel(s: SignalEvidencePack['signal']): string {
  return ({ high: '高', medium: '中', limited: '有限' } as Record<string, string>)[s.confidence] || s.confidence
}

function goDeep() {
  const routePath = pack.value?.signal.evidence.verify_route
  if (routePath) router.push(routePath)
}

onMounted(async () => {
  const signalId = String(route.params.signalId || '')
  document.title = '信号查证'
  try {
    const res = await getSignalEvidence(signalId)
    pack.value = (res as any)?.data ?? res
    document.title = `信号查证 · ${pack.value?.signal.entity?.name || signalId}`
  } catch (e: any) {
    error.value = e?.msg || e?.message || '证据载入失败'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.verify-page { min-height: 100vh; background: #f3f5f9; }
.verify-top { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 12px 24px; background: #1f2d3d; color: #fff; }
.brand { font-size: 14px; font-weight: 600; }
.verify-top .meta { font-size: 12px; color: #b8c2cc; }
.state { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 120px 20px; color: #606266; }
.err-title { font-size: 15px; font-weight: 600; color: #303133; margin: 0; }
.err-hint { font-size: 13px; color: #909399; margin: 0; }
.body { max-width: 880px; margin: 0 auto; padding: 20px 20px 48px; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 16px 18px; }
.card h2 { margin: 0 0 12px; font-size: 14px; color: #303133; }
.judgement { border-left: 4px solid #909399; }
.judgement.sev-critical { border-left-color: #c45656; }
.judgement.sev-high { border-left-color: #e6a23c; }
.judgement.sev-medium { border-left-color: #b88230; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 10px; }
.from { font-size: 12px; color: #909399; margin-left: 4px; }
.headline { margin: 0 0 8px; font-size: 17px; line-height: 1.6; color: #1f2d3d; }
.consequence { margin: 0; font-size: 13px; color: #9f1239; line-height: 1.6; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; }
.fact { background: #f5f7fa; border-radius: 6px; padding: 6px 12px; font-size: 13px; }
.fact em { font-style: normal; color: #909399; margin-right: 8px; }
.fact b { color: #4f46e5; }
.empty { margin: 0; font-size: 12px; color: #909399; }
code { background: #f5f7fa; border-radius: 4px; padding: 1px 6px; font-size: 12px; color: #475569; }
.boundary { margin: 12px 0 0; font-size: 12px; color: #b45309; background: #fdf6ec;
  border-radius: 6px; padding: 8px 10px; line-height: 1.6; }
.exclusions { margin-top: 10px; }
.ex-title { margin: 0 0 4px; font-size: 12px; font-weight: 600; color: #606266; }
.ex-item { margin: 2px 0; font-size: 12px; color: #909399; line-height: 1.6; }
.action-box { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px;
  background: #eef2ff; border-radius: 8px; padding: 10px 12px; }
.action-box span { display: block; color: #94a3b8; font-size: 11px; }
.action-box b { font-size: 13px; color: #3730a3; }
.action-box b.when { color: #b45309; }
.action-box p, .action-box small { grid-column: 1 / -1; margin: 2px 0 0; font-size: 13px;
  color: #334155; line-height: 1.6; }
.action-box small { color: #64748b; }
.note { margin: 10px 0 0; font-size: 12px; color: #909399; }
.deep { text-align: center; }
</style>
