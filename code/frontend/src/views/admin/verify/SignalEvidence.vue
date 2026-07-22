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

      <!-- 关键数字：人数类数字可直达明细清单，聚合/判定值仅展示 -->
      <section class="card">
        <h2>关键数字</h2>
        <div class="facts">
          <div v-for="[k, v] in allFacts" :key="k" class="fact" :class="{ drillable: isDrillable(k) }">
            <em>{{ k }}</em><b>{{ v }}</b>
            <button v-if="isDrillable(k)" type="button" class="drill-btn"
              :title="`查看「${k}」明细清单`" @click="goDetail(k)">明细 ›</button>
          </div>
        </div>
        <p v-if="drillableFacts.length" class="drill-hint">带「明细」的数字可直达该数字代表的业务清单。</p>
        <p v-if="!allFacts.length" class="empty">该信号无结构化数字，判断依据见下方证据明细。</p>
      </section>

      <!-- 这个结论是怎么得出的：管理者视角的业务口径，技术细节零出现 -->
      <section class="card">
        <h2>这个结论是怎么得出的</h2>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="统计对象">{{ sig.entity?.name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="数据来源">{{ sourceLabel }}</el-descriptions-item>
          <el-descriptions-item label="数据时效">{{ pack.data_freshness || sig.evidence.freshness || '—' }}</el-descriptions-item>
          <el-descriptions-item label="结论可靠性">{{ reliabilityLabel }}</el-descriptions-item>
          <el-descriptions-item label="统计口径">{{ caliberLabel }}</el-descriptions-item>
        </el-descriptions>
        <p class="boundary">口径边界：{{ sig.data_boundary || pack.skill.data_boundary || '—' }}</p>
        <div v-if="pack.skill.exclusions?.length" class="exclusions">
          <p class="ex-title">显式排除项（本结论不覆盖）：</p>
          <p v-for="(ex, i) in pack.skill.exclusions" :key="i" class="ex-item">· {{ ex.what }} —— {{ ex.why }}</p>
        </div>
      </section>

      <!-- 技术口径：仅系统管理员可见（数据核验是他的工作内容，对其他角色是噪音） -->
      <section v-if="isTechViewer" class="card">
        <h2>技术口径（数据管理员）</h2>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="数据表"><code>{{ sig.evidence.table || '—' }}</code></el-descriptions-item>
          <el-descriptions-item label="筛选条件"><code>{{ sig.evidence.condition || '—' }}</code></el-descriptions-item>
          <el-descriptions-item label="对象标识"><code>{{ entityTechLabel }}</code></el-descriptions-item>
          <el-descriptions-item label="配置版本"><code>{{ pack.skill.config_version || '—' }}</code></el-descriptions-item>
          <el-descriptions-item label="生成方式">{{ methodLabel }}</el-descriptions-item>
        </el-descriptions>
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
import { authStore } from '@/store/auth'
import type { SignalEvidencePack } from '@/types/decision'
import { SEVERITY_META, CHANGE_META } from '@/types/decision'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const pack = ref<SignalEvidencePack | null>(null)

/** 技术口径区仅对系统管理员可见 */
const isTechViewer = computed(() =>
  authStore.user?.permissionContext?.activeRole === 'admin')

/** 数据表 → 业务名映射（管理者不看表名；组合表按 + / × 拆分逐个翻译） */
const TABLE_LABELS: Record<string, string> = {
  student_plan_course_status: '学生必修完成记录',
  teaching_lesson: '历史教学任务',
  fact_alert: '学业预警记录',
  alert_event: '预警认领状态',
  fact_grade: '课程成绩记录',
  dim_student: '学生基本信息',
  dim_course: '课程基本信息',
  dim_staff: '教师基本信息',
  agg_course_offering: '教学任务快照',
  agg_course_team: '教学团队快照',
  student_course_substitution: '课程替代认定记录',
  grade_attempt: '成绩修读记录',
}
const sourceLabel = computed(() => {
  const raw = pack.value?.signal.evidence?.table || ''
  if (!raw) return '—'
  const parts = raw.split(/\+|×/).map(s => s.trim()).filter(Boolean)
  const labels = parts.map(p => TABLE_LABELS[p] || p)
  const sep = raw.includes('×') ? ' × ' : ' + '
  return labels.join(sep)
})

/** 置信度的人话翻译：管理者关心的是"这结论有多硬" */
const reliabilityLabel = computed(() => {
  const c = pack.value?.signal.confidence
  return ({
    high: '高 —— 基于明确业务记录，非推断',
    medium: '中 —— 基于推断或样本有限',
    limited: '有限 —— 数据缺口较大，仅作线索',
  } as Record<string, string>)[c || ''] || c || '—'
})

/** 规则版本的人话翻译：管理者关心"口径是不是我们学校自己定的" */
const caliberLabel = computed(() => {
  const v = pack.value?.skill.config_version
  if (!v || v === 'product_default') return '标准口径（未做学校定制）'
  return `学校定制口径（${v}）`
})

const entityTechLabel = computed(() => {
  const e = pack.value?.signal.entity
  return e ? `${e.type} · ${e.id}` : '—'
})

const sig = computed(() => pack.value!.signal)
const allFacts = computed(() => Object.entries(pack.value?.signal.facts || {}))
const drillableFacts = computed(() => pack.value?.signal.drillable_facts || [])
function isDrillable(label: string): boolean {
  return drillableFacts.value.includes(label)
}
function goDetail(label: string) {
  router.push({
    path: `/admin/verify/signal/${encodeURIComponent(String(route.params.signalId || ''))}/detail`,
    query: { fact: label },
  })
}
const methodLabel = computed(() =>
  pack.value?.generation_method === 'llm_enhanced' ? 'LLM增强生成' : '规则模板生成')

function severityMeta(s: SignalEvidencePack['signal']) {
  return SEVERITY_META[s.severity] || SEVERITY_META.low
}
function changeMeta(s: SignalEvidencePack['signal']) {
  return CHANGE_META[s.change] || CHANGE_META.ongoing
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
.fact.drillable { border: 1px solid #c7d2fe; background: #eef2ff; }
.drill-btn { margin-left: 8px; border: none; background: none; color: #4f46e5;
  font-size: 12px; cursor: pointer; padding: 0; text-decoration: underline; }
.drill-btn:hover { color: #3730a3; }
.drill-hint { margin: 8px 0 0; font-size: 12px; color: #909399; }
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
