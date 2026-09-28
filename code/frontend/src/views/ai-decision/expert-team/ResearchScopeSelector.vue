<!-- 专家团研究工作区：保留来源提交的业务与交互，归入 AI 管理决策模块。 -->
<template>
  <details :open="open" class="scope-settings" @toggle="$emit('update:open', ($event.target as HTMLDetailsElement).open)">
    <summary><span>{{ readonly ? '已保存的分析范围' : hasResearch ? '继续分析的范围' : '选择研究范围' }}</span><small>{{ summary }}</small><span class="scope-edit">{{ open ? '收起' : readonly ? '查看' : '调整' }}</span></summary>
    <div class="scope-content">
      <div class="scope-grid">
        <label>专业与培养方案<el-select v-model="scope.plan_id" :disabled="readonly" filterable clearable placeholder="选择专业及适用年级" aria-label="本次专业与培养方案" @change="$emit('plan-change')"><el-option v-for="plan in catalog?.plans || []" :key="plan.plan_id" :value="plan.plan_id" :label="researchPlanLabel(plan)" /></el-select></label>
        <label>比较专业（可选）<el-select v-model="scope.target_plan_id" :disabled="readonly" filterable clearable placeholder="留空时按实际课程推荐" no-data-text="暂无同年级、同培养类别的可比方案" aria-label="比较专业"><el-option v-for="plan in orderedPlans" :key="plan.plan_id" :value="plan.plan_id" :label="researchPlanLabel(plan)" /></el-select></label>
        <label>课程范围<el-select v-model="scope.focus" :disabled="readonly" aria-label="课程比较范围"><el-option v-for="(label, key) in focusLabels" :key="key" :value="key" :label="label" /></el-select></label>
        <label>成绩学期（适用时）<el-select v-model="scope.semester" :disabled="readonly" clearable aria-label="成绩学期" placeholder="按问题需要选择"><el-option v-for="semester in catalog?.semesters || []" :key="semester" :value="semester" :label="semester" /></el-select></label>
        <label v-if="courseOptions?.length">继续研究的课程<el-select v-model="scope.course_id" :disabled="readonly" clearable filterable aria-label="继续研究的课程"><el-option v-for="course in courseOptions" :key="course.id" :value="course.id" :label="course.name" /></el-select></label>
      </div>
      <section v-if="scope.plan_id && !readonly" class="recommended-plans" aria-label="按培养方案课程推荐比较专业" :aria-busy="loading">
        <b>按实际课程选择对照专业</b><span v-if="loading"> 正在比较课程安排…</span>
        <p v-if="error" role="alert">{{ error }} <button type="button" @click="loadRecommendations">重新获取</button></p>
        <template v-else-if="recommendation && !loading">
          <p>{{ recommendation.candidates.length ? '以下按已明确的非公共课程重合情况排列，名称不参与排序。点击可选为比较专业，尚不会开始分析。' : recommendation.empty_reason }}</p>
          <div class="recommendation-grid"><button v-for="plan in recommendation.candidates" :key="plan.plan_id" type="button" :aria-pressed="scope.target_plan_id === plan.plan_id" @click="scope.target_plan_id = plan.plan_id"><b>{{ plan.major_name }}</b><span>共同 {{ plan.shared }} 门 · 已纳入 {{ plan.source_count }} / {{ plan.target_count }} 门</span><small>已纳入课程重合 {{ plan.subset_overlap }}% · 并集 {{ plan.union }} 门</small><small>{{ plan.examples.slice(0, 2).map(c => c.name).join('、') }}</small><small>分类待明确 {{ plan.source_pending }} / {{ plan.target_pending }} 门，未计入</small><em>{{ scope.target_plan_id === plan.plan_id ? '已选择' : '选择此专业' }}</em></button></div>
          <p v-if="recommendation.candidates.length">这是所选课程范围的对照线索，不是完整专业相似度，也不代表课程可以互认。{{ scope.focus === 'all' ? '全部课程视图仍按非公共课程推荐对象，避免公共选修池影响选择。' : '' }}</p>
        </template>
      </section>
      <p>{{ scope.focus === 'all' ? '全部课程含公共课程及分类待明确课程，只作代码对照，不代表专业相似度。' : '仅按已明确的课程分类比较；分类资料不足的部分会单独说明。' }}<template v-if="hasResearch && !readonly"> 调整后从下一次发送起生效，历史分析保持原范围。</template></p>
    </div>
  </details>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { researchApi } from '@/api/aiDecision/expertResearch'
import { researchPlanLabel } from '@/utils/expertResearch'
import type { ComparatorRecommendation, ResearchCatalog, ResearchScope } from '@/types/expertResearch'
import type { TeamPlan } from '@/types/expertTeam'
const props = defineProps<{ open: boolean; scope: ResearchScope; catalog: ResearchCatalog | null; comparablePlans: TeamPlan[]; focusLabels: Record<string, string>; courseOptions?: { id: string; name: string }[]; hasResearch: boolean; readonly?: boolean }>()
defineEmits<{ 'update:open': [open: boolean]; 'plan-change': [] }>()
const recommendation = ref<ComparatorRecommendation | null>(null), loading = ref(false), error = ref('')
let generation = 0
async function loadRecommendations() {
  const attempt = ++generation; recommendation.value = null; error.value = ''; loading.value = false
  if (!props.open || props.readonly || !props.scope.plan_id) return
  loading.value = true
  try { const value = await researchApi.comparators(props.scope.plan_id, props.scope.focus); if (attempt === generation) recommendation.value = value }
  catch (e) { if (attempt === generation) error.value = e instanceof Error ? e.message : '推荐暂未读取成功，可手动选择专业。' }
  finally { if (attempt === generation) loading.value = false }
}
// Polling replaces the scope object even when these values are unchanged.
// Watch scalar sources so it cannot repeatedly cancel/restart recommendations.
watch([() => props.scope.plan_id, () => props.scope.focus, () => props.open, () => props.readonly], loadRecommendations, { immediate: true })
const orderedPlans = computed(() => {
  const ranked = recommendation.value?.candidates.map(p => p.plan_id) || []
  return [...props.comparablePlans].sort((a, b) => (ranked.includes(a.plan_id) ? ranked.indexOf(a.plan_id) : 100) - (ranked.includes(b.plan_id) ? ranked.indexOf(b.plan_id) : 100))
})
const summary = computed(() => {
  const plan = (id?: string) => researchPlanLabel(props.catalog?.plans.find(p => p.plan_id === id))
  if (!props.scope.plan_id) return '先明确专业及适用年级'
  const short = (id?: string) => { const p = props.catalog?.plans.find(p => p.plan_id === id); return p ? `${p.major_name} · ${p.grade}级` : plan(id) }
  return [short(props.scope.plan_id), props.scope.target_plan_id ? '对照 ' + short(props.scope.target_plan_id) : '按课程推荐对照专业', props.scope.semester || ''].filter(Boolean).join('　｜　')
})
</script>
<style lang="scss" scoped>
.scope-settings{flex:0 0 auto;margin:0 28px 8px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;color:#475569;font-size:14px;min-height:0}
summary{display:flex;align-items:center;gap:12px;cursor:pointer;padding:10px 14px;list-style:none;min-height:22px}summary::-webkit-details-marker{display:none}summary>span:first-child{font-weight:600;white-space:nowrap}summary small{font-size:13px;line-height:1.6;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;min-width:0;flex:1;color:#64748b}.scope-edit{font-size:13px;color:#4f46e5;flex-shrink:0}
.scope-content{padding:0 14px 10px;max-height:215px;overflow:auto}.scope-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:8px 0}.scope-grid label{display:flex;flex-direction:column;gap:6px;font-size:13px;color:#475569}.scope-grid :deep(.el-select__wrapper){font-size:14px;min-height:36px}.scope-content p{font-size:13px;line-height:1.7;color:#64748b;margin:8px 0 0}
summary:focus-visible{outline:2px solid #4f46e5;outline-offset:2px}
@media(min-width:1700px){.scope-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-height:700px){.scope-settings{margin-bottom:5px}summary{padding:6px 12px}.scope-content{max-height:115px}.scope-grid{gap:8px;padding-top:5px}.scope-content p{font-size:12px}}
@media(max-width:780px){.scope-settings{margin-left:16px;margin-right:16px}summary{gap:8px}summary small{font-size:12px}.scope-grid{grid-template-columns:1fr}}
.scope-settings[open]{max-height:45vh;overflow:auto}.scope-settings[open]>summary{position:sticky;top:0;background:#f8fafc;z-index:1}.scope-content{max-height:none;overflow:visible}.recommended-plans{border-top:1px solid #e2e8f0;padding:12px 0 4px}.recommended-plans>b{font-size:14px;color:#334155}.recommended-plans p{margin:7px 0;font-size:12px}.recommendation-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.recommendation-grid button{display:flex;flex-direction:column;align-items:flex-start;gap:6px;border:1px solid #dbe2ea;border-radius:7px;background:#fff;padding:12px;text-align:left;color:#475569;cursor:pointer;font:inherit}.recommendation-grid button[aria-pressed=true]{border-color:#4f46e5;background:#eef2ff}.recommendation-grid b{color:#1e293b;font-size:14px}.recommendation-grid span,.recommendation-grid small{font-size:12px;line-height:1.6}.recommendation-grid em{font-style:normal;font-size:12px;color:#4f46e5;margin-top:auto}.recommendation-grid button:focus-visible{outline:2px solid #4f46e5;outline-offset:2px}@media(max-width:1000px){.recommendation-grid{grid-template-columns:1fr}.recommendation-grid button{display:grid;grid-template-columns:1fr 1fr}.scope-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
