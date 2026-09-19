<template>
  <el-drawer
    :model-value="modelValue"
    class="faculty-kpi-drawer"
    size="calc(100vw * 2 / 3)"
    append-to-body
    :modal="false"
    modal-class="faculty-nonblocking-overlay"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="kpi-drawer-heading">
        <div>
          <h2>{{ data.metric?.label || metricLabel }}</h2>
          <p>{{ semester }}学期 · {{ data.college || '全校' }} · 指标下钻</p>
        </div>
        <el-tag :type="statusType" effect="plain">{{ statusLabel }}</el-tag>
      </div>
    </template>

    <div class="kpi-drawer-body">
      <div v-if="loading && !data.metric" class="kpi-drawer-loading">
        <el-skeleton :rows="10" animated />
        <p>正在汇总指标、组织分布与明细证据…</p>
      </div>
      <el-result
        v-else-if="error && !data.metric"
        icon="warning"
        title="指标下钻加载失败"
        :sub-title="error"
      >
        <template #extra><el-button type="primary" @click="load(true)">重新加载</el-button></template>
      </el-result>
      <template v-else-if="data.metric">
        <el-alert
          v-if="data.metric.status !== 'ready'"
          class="readiness-alert"
          type="warning"
          :closable="false"
          show-icon
          :title="data.metric.status === 'partial' ? '当前仅能提供部分指标证据' : '当前数据不足，暂不输出正式比例'"
          :description="data.metric.sub"
        />

        <section class="metric-overview">
          <KpiCard
            :label="data.metric.label"
            :value="data.metric.value"
            :sub="data.metric.sub"
            :hint="data.metric.hint"
            :tone="data.metric.tone"
          />
          <div class="metric-definition">
            <div><b>计算口径</b><p>{{ data.formula }}</p></div>
            <div><b>数据来源</b><p>{{ data.source_note }}</p></div>
            <div><b>适用边界</b><p>{{ data.boundary }}</p></div>
            <small>规则版本：{{ data.rule_version }}<template v-if="data.updated_at"> · 数据更新时间：{{ data.updated_at }}</template></small>
          </div>
        </section>

        <section v-if="data.breakdown?.length" class="breakdown-section">
          <div class="section-title">
            <div><h3>结构分布</h3><p>用于解释总体值，不用于学院或教师绩效排名。</p></div>
          </div>
          <div class="breakdown-grid">
            <div v-for="item in data.breakdown" :key="item.college_id || item.label || item.college_name" class="breakdown-item">
              <span>{{ item.college_name || item.label }}</span>
              <b v-if="item.staff_count !== undefined">{{ item.teaching_teacher_count }}/{{ item.staff_count }} 人</b>
              <b v-else-if="item.known_count !== undefined">{{ item.count }}/{{ item.known_count }} 人</b>
              <b v-else>{{ item.count }} 人</b>
              <small v-if="item.rate !== null && item.rate !== undefined">
                占比 {{ item.rate }}%<template v-if="item.coverage !== null && item.coverage !== undefined"> · 证据覆盖 {{ item.coverage }}%</template>
              </small>
            </div>
          </div>
        </section>

        <section v-if="data.evidence_gaps?.length" class="detail-section evidence-gap-section">
          <div class="section-title">
            <div><h3>数据治理清单</h3><p>这些实际授课教师因关键字段缺失未进入正式比例，请先补齐来源数据。</p></div>
          </div>
          <AppTable
            :columns="gapColumns"
            :data="data.evidence_gaps"
            :storage-key="`faculty:kpi:${metricKey}:gaps`"
            :config-version="1"
            :max-business-columns="6"
            :pagination="false"
            empty-text="当前没有待补齐记录"
          >
            <template #col-display_name="{ row }"><b>{{ row.display_name }}</b></template>
            <template #col-title="{ row }">{{ row.title || '待补齐' }}</template>
            <template #col-dept="{ row }">{{ row.dept || '待映射' }}</template>
            <template #col-actions="{ row }">
              <el-button link type="primary" @click.stop="emit('open-teacher', row)">教学经历</el-button>
            </template>
          </AppTable>
        </section>

        <section class="detail-section">
          <div class="detail-toolbar">
            <div>
              <h3>{{ detailTitle }}</h3>
              <p>{{ detailDescription }}</p>
            </div>
            <div class="detail-search">
              <el-input
                v-model="keyword"
                clearable
                placeholder="搜索教师、课程或学院"
                @keyup.enter="search"
                @clear="search"
              />
              <el-button type="primary" @click="search">查询</el-button>
            </div>
          </div>

          <AppTable
            :columns="columns"
            :data="data.items || []"
            :storage-key="`faculty:kpi:${metricKey}`"
            :config-version="1"
            :max-business-columns="8"
            :loading="loading"
            :pagination="true"
            :page="page"
            :page-size="pageSize"
            :total="data.total || 0"
            :page-sizes="[10, 20, 50, 100]"
            show-density
            show-column-settings
            :empty-text="emptyText"
            @page-change="changePage"
            @page-size-change="changePageSize"
          >
            <template #col-display_name="{ row }"><b>{{ row.display_name }}</b></template>
            <template #col-course_name="{ row }"><span class="course-name">{{ row.course_name }}</span></template>
            <template #col-title="{ row }">{{ row.title || '待补充' }}</template>
            <template #col-dept="{ row }">{{ row.dept || '待映射' }}</template>
            <template #col-title_completeness_rate="{ row }">{{ row.title_completeness_rate }}%</template>
            <template #col-actions="{ row }">
              <el-button v-if="row.course_id" link type="primary" @click.stop="emit('open-course', row)">课程证据</el-button>
              <el-button v-if="row.staff_id" link type="primary" @click.stop="emit('open-teacher', row)">教学经历</el-button>
            </template>
          </AppTable>
        </section>

        <el-alert
          v-if="error"
          class="inline-error"
          type="error"
          :closable="false"
          show-icon
          :title="`本次刷新失败，仍保留上次成功数据：${error}`"
        />
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import AppTable from '@/components/AppTable.vue'
import KpiCard from '@/components/KpiCard.vue'
import type { AppTableColumn } from '@/types/table'
import { getFacultyKpiDetails } from '@/api/teachingAnalysis/faculty'

const props = defineProps<{
  modelValue: boolean
  metricKey: string
  semester: string
  collegeId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'open-course': [row: any]
  'open-teacher': [row: any]
}>()

const metricNames: Record<string, string> = {
  teaching_staff_coverage: '授课教师总数/教职工总数',
  team_structure_exception: '团队结构异常课程数',
  continuous_single_teacher: '连续单点授课教师数',
  senior_title_teaching_rate: '高职称教师授课占比（教授、副教授）',
  young_teacher_teaching_rate: '青年教师授课占比（35岁以下）',
}

const metricLabel = computed(() => metricNames[props.metricKey] || '师资保障指标')
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const data = reactive<any>({})
let requestSerial = 0

const statusLabel = computed(() => ({
  ready: '数据就绪',
  partial: '部分就绪',
  insufficient: '证据不足',
  unavailable: '数据待接入',
} as Record<string, string>)[data.metric?.status] || '加载中')
const statusType = computed(() => data.metric?.status === 'ready' ? 'success' : 'warning')

const columns = computed<AppTableColumn[]>(() => {
  const action: AppTableColumn = { key: 'actions', label: '操作', width: 150, fixed: 'right', required: true, region: 'action' }
  if (props.metricKey === 'team_structure_exception') return [
    { key: 'course_name', label: '课程', minWidth: 180, fixed: 'left', required: true, region: 'identity' },
    { key: 'college_name', label: '责任学院', minWidth: 150, required: true, region: 'business' },
    { key: 'course_nature', label: '课程性质', minWidth: 100, region: 'business' },
    { key: 'lesson_count', label: '教学班', minWidth: 85, align: 'center', region: 'business' },
    { key: 'enrolled', label: '学生人次', minWidth: 95, align: 'center', region: 'business' },
    { key: 'teacher_count', label: '实际教师', minWidth: 90, align: 'center', region: 'business' },
    { key: 'senior_title_teachers', label: '教授/副教授', minWidth: 105, align: 'center', region: 'business' },
    { key: 'title_completeness_rate', label: '职称完整率', minWidth: 105, align: 'center', region: 'business' },
    { key: 'reason', label: '命中原因', minWidth: 240, tooltip: true, region: 'business' },
    action,
  ]
  if (props.metricKey === 'continuous_single_teacher') return [
    { key: 'display_name', label: '教师', minWidth: 110, fixed: 'left', required: true, region: 'identity' },
    { key: 'course_name', label: '连续单点课程', minWidth: 180, required: true, region: 'business' },
    { key: 'college_name', label: '责任学院', minWidth: 150, region: 'business' },
    { key: 'continuity_evidence_text', label: '最近3次开课教师证据', minWidth: 320, tooltip: true, region: 'business' },
    { key: 'lesson_count', label: '本期教学班', minWidth: 95, align: 'center', region: 'business' },
    { key: 'enrolled', label: '本期学生人次', minWidth: 105, align: 'center', region: 'business' },
    { key: 'title', label: '职称', minWidth: 100, region: 'business' },
    action,
  ]
  if (props.metricKey === 'young_teacher_teaching_rate') return [
    { key: 'display_name', label: '教师', minWidth: 110, fixed: 'left', required: true, region: 'identity' },
    { key: 'age_band', label: '年龄段', minWidth: 105, required: true, region: 'business' },
    { key: 'title', label: '职称', minWidth: 100, region: 'business' },
    { key: 'dept', label: '人事归属', minWidth: 150, region: 'business' },
    { key: 'course_count', label: '授课课程', minWidth: 95, align: 'center', region: 'business' },
    { key: 'lesson_count', label: '教学班', minWidth: 85, align: 'center', region: 'business' },
    { key: 'course_names', label: '课程证据', minWidth: 220, tooltip: true, region: 'business' },
    action,
  ]
  return [
    { key: 'display_name', label: '教师', minWidth: 110, fixed: 'left', required: true, region: 'identity' },
    { key: 'dept', label: '人事归属', minWidth: 150, required: true, region: 'business' },
    { key: 'title', label: '职称', minWidth: 100, region: 'business' },
    ...(props.metricKey === 'teaching_staff_coverage'
      ? [{ key: 'staff_category', label: '人员类别', minWidth: 105, region: 'business' as const }]
      : []),
    { key: 'course_count', label: '授课课程', minWidth: 95, align: 'center', region: 'business' },
    { key: 'lesson_count', label: '教学班', minWidth: 85, align: 'center', region: 'business' },
    { key: 'course_names', label: '课程证据', minWidth: 220, tooltip: true, region: 'business' },
    action,
  ]
})

const gapColumns: AppTableColumn[] = [
  { key: 'display_name', label: '教师', minWidth: 110, fixed: 'left', required: true, region: 'identity' },
  { key: 'dept', label: '归属单位', minWidth: 150, required: true, region: 'business' },
  { key: 'title', label: '职称', minWidth: 100, region: 'business' },
  { key: 'gap_reason', label: '待治理字段', minWidth: 190, required: true, region: 'business' },
  { key: 'course_names', label: '授课课程证据', minWidth: 220, tooltip: true, region: 'business' },
  { key: 'actions', label: '操作', width: 100, fixed: 'right', required: true, region: 'action' },
]

const detailTitle = computed(() => props.metricKey === 'team_structure_exception'
  ? '命中结构核查规则的课程'
  : props.metricKey === 'continuous_single_teacher'
    ? '连续单点教师—课程证据'
    : props.metricKey === 'young_teacher_teaching_rate'
      ? '35岁以下实际授课教师'
      : props.metricKey === 'senior_title_teaching_rate'
        ? '教授、副教授实际授课教师'
        : '实际授课教师')
const detailDescription = computed(() => props.metricKey.includes('teacher') || props.metricKey.includes('coverage') || props.metricKey.includes('rate')
  ? '仅展示当前授权范围内与本科教学有关的必要证据，不作个人绩效排名。'
  : '点击课程可继续查看实际授课团队、历史开课和规则证据。')
const emptyText = computed(() => data.metric?.status === 'ready'
  ? '当前条件下没有明细'
  : '真实数据尚未达到该指标的正式计算条件')

async function load(force = false) {
  if (!props.modelValue || !props.metricKey || !props.semester) return
  const serial = ++requestSerial
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({
      semester: props.semester,
      page: String(page.value),
      page_size: String(pageSize.value),
    })
    if (props.collegeId) query.set('college', props.collegeId)
    if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
    const result = await getFacultyKpiDetails<any>(props.metricKey, query)
    if (serial !== requestSerial) return
    Object.keys(data).forEach(key => delete data[key])
    Object.assign(data, result)
  } catch (requestError: any) {
    if (serial !== requestSerial) return
    error.value = requestError?.message || '请求失败'
    if (force) Object.keys(data).forEach(key => delete data[key])
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}
function changePage(value: number) {
  page.value = value
  void load()
}
function changePageSize(value: number) {
  pageSize.value = value
  page.value = 1
  void load()
}

watch(
  () => [props.modelValue, props.metricKey, props.semester, props.collegeId],
  ([visible], previous) => {
    if (!visible) return
    const contextChanged = !previous || previous.slice(1).some((value, index) => value !== [props.metricKey, props.semester, props.collegeId][index])
    if (contextChanged) {
      keyword.value = ''
      page.value = 1
      Object.keys(data).forEach(key => delete data[key])
    }
    void load()
  },
  { immediate: true },
)
</script>

<style scoped lang="scss">
.kpi-drawer-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  h2 { margin: 0; color: #0f172a; font-size: 20px; }
  p { margin: 5px 0 0; color: #64748b; font-size: 12px; }
}
.kpi-drawer-body { min-height: 560px; }
.kpi-drawer-loading {
  padding: 18px;
  p { color: #64748b; text-align: center; font-size: 12px; }
}
.readiness-alert { margin-bottom: 14px; }
.metric-overview {
  display: grid;
  grid-template-columns: minmax(230px,.55fr) minmax(0,1.45fr);
  gap: 14px;
  align-items: stretch;
  margin-bottom: 14px;
}
.metric-definition {
  display: grid;
  gap: 9px;
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
  div { display: grid; grid-template-columns: 70px minmax(0,1fr); gap: 10px; }
  b { color: #334155; font-size: 12px; }
  p { margin: 0; color: #64748b; font-size: 12px; line-height: 1.55; }
  small { color: #94a3b8; }
}
.breakdown-section,.detail-section {
  margin-top: 14px;
  padding: 15px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}
.section-title,.detail-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  h3 { margin: 0 0 5px; color: #0f172a; font-size: 16px; }
  p { margin: 0; color: #64748b; font-size: 12px; }
}
.breakdown-grid {
  display: grid;
  grid-template-columns: repeat(4,minmax(0,1fr));
  gap: 9px;
}
.breakdown-item {
  display: grid;
  gap: 4px;
  padding: 11px 12px;
  border-radius: 9px;
  background: #f8fafc;
  span { overflow: hidden; color: #64748b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
  b { color: #0f172a; font-size: 15px; }
  small { color: #4f46e5; }
}
.detail-search {
  display: grid;
  grid-template-columns: minmax(220px,320px) auto;
  gap: 8px;
}
.course-name { color: #4338ca; font-weight: 600; }
.inline-error { margin-top: 12px; }
@media (max-width:1100px) {
  .metric-overview { grid-template-columns: 1fr; }
  .breakdown-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .detail-toolbar { flex-direction: column; }
}
</style>
