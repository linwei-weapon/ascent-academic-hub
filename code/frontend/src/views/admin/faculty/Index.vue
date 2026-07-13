<template>
  <div>
    <div class="head">
      <div>
        <h2 class="sa-page-title">本科教学师资保障分析</h2>
        <p class="sa-page-sub">从真实教学任务识别课程团队单点承担、任务集中和教授本科教学参与核查对象。</p>
      </div>
      <div class="filters">
        <el-select v-model="semester" placeholder="选择学期" @change="load">
          <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="college" clearable filterable placeholder="全部学院" @change="onCollegeChange">
          <el-option v-for="x in colleges" :key="x.id" :label="x.name" :value="x.id" />
        </el-select>
      </div>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="本页用于师资供给与课程团队核查，不用于教师个人评价"
      :description="definition.boundary"
    />

    <div v-if="data.college" class="scope-banner">
      <div>
        <span class="scope-label">当前核查范围</span>
        <b>{{ data.college }}</b>
        <span>以下指标、风险课程和主讲任务均已按该学院筛选</span>
      </div>
      <el-button type="primary" plain @click="clearCollege">返回全校范围</el-button>
    </div>

    <div class="sa-kpi-row kpi-summary">
      <KpiCard
        v-for="k in kpis"
        :key="k.label"
        :label="k.label"
        :value="k.value"
        :sub="k.note"
        :hint="k.help"
        :tone="k.tone"
      />
    </div>

    <section class="sa-card workspace" v-loading="loading">
      <el-tabs v-model="activeView" class="view-tabs">
        <el-tab-pane name="college">
          <template #label><span>学院保障概览 <em>{{ data.colleges.length }}</em></span></template>
          <div class="section-head">
            <div>
              <h3>学院本科教学师资保障概览</h3>
              <p>先比较单点课程数量，再进入学院查看具体课程，不在概览表中重复解释管理用途。</p>
            </div>
          </div>
          <el-table :data="data.colleges" stripe size="small">
            <el-table-column prop="college_name" label="学院" min-width="180" />
            <el-table-column prop="courses" label="开课课程" width="100" />
            <el-table-column prop="lessons" label="教学班" width="90" />
            <el-table-column prop="enrolled" label="选课人次" width="105" />
            <el-table-column prop="single_teacher_courses" label="单一教师课程" width="120" />
            <el-table-column prop="high_impact_courses" width="140">
              <template #header><KpiLabel label="高影响单点课程" formula="当前学期仅1名实际授课教师，且累计选课人次不少于100的课程；100人为原型核查阈值。" /></template>
              <template #default="{ row }">
                <el-tag :type="row.high_impact_courses ? 'danger' : 'success'">{{ row.high_impact_courses }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="inspectCollege(row)">查看风险课程</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane name="risk">
          <template #label><span>风险课程核查 <em>{{ data.risk_courses.length }}</em></span></template>
          <div class="section-head">
            <div>
              <h3>需要核查的课程团队</h3>
              <p>核查理由来自当期教师覆盖、教学规模和职称证据，不代表教师能力或教学质量。</p>
            </div>
            <el-button v-if="data.college" link type="primary" @click="activeView = 'college'">查看学院概览</el-button>
          </div>
          <el-table :data="data.risk_courses" stripe>
            <el-table-column prop="course_name" label="课程" min-width="190" show-overflow-tooltip />
            <el-table-column prop="college_name" label="开课学院" min-width="145" />
            <el-table-column prop="course_nature" label="课程性质" width="105" />
            <el-table-column prop="lesson_count" label="教学班" width="75" />
            <el-table-column prop="enrolled" label="选课人次" width="90" />
            <el-table-column prop="teacher_count" label="实际教师" width="85" />
            <el-table-column label="职称证据" width="95">
              <template #default="{ row }">{{ row.known_title_teachers }} / {{ row.teacher_count }}</template>
            </el-table-column>
            <el-table-column label="优先级" width="80">
              <template #default="{ row }"><el-tag :type="row.priority === '高' ? 'danger' : 'warning'">{{ row.priority }}</el-tag></template>
            </el-table-column>
            <el-table-column label="核查理由" min-width="280">
              <template #default="{ row }">{{ row.attention_reasons.join('；') }}</template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }"><el-button link type="primary" @click="goTeam(row)">团队证据</el-button></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane name="teacher">
          <template #label><span>主讲任务核查 <em>{{ data.teachers.length }}</em></span></template>
          <div class="section-head">
            <div>
              <h3>主讲教学任务集中教师</h3>
              <p>按主讲教师字段统计教学班和选课人次；联合授课缺少分工比例，当前不拆分工作量。</p>
            </div>
          </div>
          <el-table :data="data.teachers" size="small" stripe>
            <el-table-column prop="teacher_name" label="教师" width="110" />
            <el-table-column prop="college_name" label="学院" min-width="160" />
            <el-table-column prop="title" label="职称" width="110"><template #default="{ row }">{{ row.title || '待补充' }}</template></el-table-column>
            <el-table-column prop="course_count" label="课程数" width="85" />
            <el-table-column prop="lesson_count" label="教学班数" width="90" />
            <el-table-column prop="enrolled" label="覆盖选课人次" width="120" />
            <el-table-column label="核查边界" min-width="320">
              <template #default>核对是否为正常团队分工、合班记录或任务集中，不能据此直接认定超负荷。</template>
            </el-table-column>
            <el-table-column label="操作" width="95" fixed="right">
              <template #default="{ row }"><el-button link type="primary" @click="goTeacher(row)">教学档案</el-button></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </section>

    <section class="sa-card explain">
      <div class="sa-card-title">指标口径与管理动作</div>
      <p><b>单一教师覆盖课程：</b>{{ definition.single_teacher_courses }} 管理动作是核查是否需要协同备课和接续教师。</p>
      <p><b>高影响单点课程：</b>{{ definition.high_impact_courses }} 管理动作是结合下一学期开课规模优先安排资源。</p>
      <p><b>教授本科教学参与率：</b>{{ definition.professor_participation }}</p>
      <p><b>职称证据完整率：</b>{{ definition.title_completeness }} 完整率不足时不形成职称梯队结论。</p>
      <p><b>任务集中度：</b>{{ definition.load_share }}</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { http } from '@/utils/http'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import { COLLEGE_MAP } from '@/constants/colleges'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'

const router = useRouter()
const semester = ref('')
const college = ref('')
const activeView = ref('college')
const semesters = ref<SemesterOpt[]>([])
const loading = ref(false)
const colleges = Object.entries(COLLEGE_MAP).map(([id, name]) => ({ id, name }))
const data = reactive<any>({ summary: {}, colleges: [], risk_courses: [], teachers: [], college: '' })
const definition = reactive<any>({})

const fmt = (value: any, suffix = '') => value === null || value === undefined ? '—' : value + suffix
const kpis = computed(() => [
  { label: '本科教学活跃教师', value: fmt(data.summary.active_teachers, ' 人'), note: `覆盖 ${data.summary.courses || 0} 门课程`, help: definition.active_teachers || '', tone: 'primary' as const },
  { label: '单一教师覆盖课程', value: fmt(data.summary.single_teacher_courses, ' 门'), note: '当前学期仅1名实际授课教师', help: definition.single_teacher_courses || '', tone: 'amber' as const },
  { label: '高影响单点课程', value: fmt(data.summary.high_impact_courses, ' 门'), note: '单一教师且选课人次≥100', help: definition.high_impact_courses || '', tone: 'danger' as const },
  { label: '教授本科教学参与率', value: fmt(data.summary.professor_participation_rate, '%'), note: `${data.summary.professor_active || 0} / ${data.summary.professor_total || 0} 人`, help: definition.professor_participation || '', tone: 'teal' as const },
  { label: '职称证据完整率', value: fmt(data.summary.title_completeness_rate, '%'), note: '决定能否分析职称梯队', help: definition.title_completeness || '', tone: 'teal' as const },
  { label: '前10%主讲教师任务占比', value: fmt(data.summary.top10_load_share, '%'), note: '按主讲字段覆盖选课人次计算', help: definition.load_share || '', tone: 'plain' as const },
])

async function load() {
  loading.value = true
  try {
    const query = new URLSearchParams()
    if (semester.value) query.set('semester', semester.value)
    if (college.value) query.set('college', college.value)
    const result = await http.get<any>('/admin/faculty/management-overview?' + query)
    Object.assign(data, result)
    Object.assign(definition, result.definition)
  } finally {
    loading.value = false
  }
}

async function onCollegeChange() {
  await load()
  if (college.value) activeView.value = 'risk'
}

async function inspectCollege(row: any) {
  const match = colleges.find(item => item.name === row.college_name)
  if (!match) return
  college.value = match.id
  activeView.value = 'risk'
  await load()
}

async function clearCollege() {
  college.value = ''
  activeView.value = 'college'
  await load()
}

function goTeam(row: any) {
  router.push({ path: '/admin/faculty/team', query: { courseId: row.course_id, courseName: row.course_name } })
}

function goTeacher(row: any) {
  router.push('/admin/faculty/' + row.teacher_id)
}

onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = (meta.semesters || []).slice().reverse()
  semester.value = semesters.value[0]?.value || ''
  await load()
})
</script>

<style scoped>
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px}.filters{display:flex;gap:10px}.filters .el-select{width:180px}.scope-banner{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:14px 0 0;padding:11px 14px;border:1px solid #c7d2fe;border-radius:10px;background:#eef2ff;color:#475569}.scope-banner>div{display:flex;align-items:center;gap:10px}.scope-label{padding:3px 8px;border-radius:999px;background:#4f46e5;color:#fff;font-size:12px}.kpi-summary{margin-top:14px}.workspace{margin-bottom:14px;min-height:420px}.view-tabs :deep(.el-tabs__header){margin-bottom:18px}.view-tabs :deep(.el-tabs__item){height:42px;padding:0 22px;font-size:14px}.view-tabs em{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;background:#eef2ff;color:#4f46e5;font-size:11px;font-style:normal}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-head h3{margin:0 0 5px;font-size:16px;color:#0f172a}.section-head p{margin:0;color:#64748b;font-size:12px}.explain p{font-size:13px;line-height:1.8;color:#475569}
</style>
