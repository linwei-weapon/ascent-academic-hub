<template>
  <div v-loading="pageLoading" element-loading-text="正在计算师资任务与课程团队指标，请稍候…" element-loading-background="rgba(248,250,252,.82)">
    <div class="head">
      <div>
        <h2 class="sa-page-title">本科教学师资保障分析</h2>
        <p class="sa-page-sub">从全校发现师资保障重点，再在抽屉中连续核查学院和课程团队，核查过程不离开当前页面。</p>
      </div>
      <el-select v-model="semester" class="semester" placeholder="选择学期" @change="changeSemester">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="本页用于师资供给与课程团队核查，不用于教师个人评价"
      :description="definition.boundary"
    />

    <div class="sa-kpi-row kpi-summary">
      <KpiCard v-for="item in schoolKpis" :key="item.label" v-bind="item" />
    </div>

    <div class="management-summary">
      <div class="summary-mark">本学期核查重点</div>
      <div>
        全校共有 <b>{{ data.summary.high_impact_courses || 0 }}</b> 门高集中承担课程，涉及
        <b>{{ affectedCollegeCount }}</b> 个学院；建议先核实教学任务拆分和工作量是否准确，再判断是否需要调整师资安排。
      </div>
    </div>

    <div class="overview-grid">
      <section class="sa-card college-card">
        <div class="section-head">
          <div>
            <h3>学院师资保障概览</h3>
            <p>点击学院整行打开核查抽屉；关闭抽屉后保留当前学期、列表位置和全校指标。</p>
          </div>
          <el-input v-model="collegeKeyword" clearable placeholder="搜索学院" class="college-search" />
        </div>
        <el-table
          :data="filteredColleges"
          stripe
          size="small"
          row-class-name="college-row"
          @row-click="openCollege"
          @cell-mouse-enter="schedulePrefetch"
          @cell-mouse-leave="cancelPrefetch"
        >
          <el-table-column prop="college_name" label="学院" min-width="175">
            <template #default="{ row }"><span class="college-link">{{ row.college_name }}</span></template>
          </el-table-column>
          <el-table-column prop="courses" label="开课课程" width="90" align="right" />
          <el-table-column prop="lessons" label="教学班" width="80" align="right" />
          <el-table-column prop="enrolled" label="选课人次" width="95" align="right" />
          <el-table-column prop="single_teacher_courses" label="单点课程" width="90" align="right" />
          <el-table-column prop="high_impact_courses" width="125" align="center">
            <template #header><KpiLabel label="高集中承担" :formula="definition.high_impact_courses" /></template>
            <template #default="{ row }"><el-tag :type="row.high_impact_courses ? 'danger' : 'success'">{{ row.high_impact_courses }}</el-tag></template>
          </el-table-column>
          <el-table-column label="保障状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.high_impact_courses ? 'danger' : row.single_teacher_courses ? 'warning' : 'success'" effect="plain">
                {{ row.high_impact_courses ? '优先核验' : '常规观察' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }"><el-button link type="primary" @click.stop="openCollege(row)">核查</el-button></template>
          </el-table-column>
        </el-table>
      </section>

      <aside class="sa-card focus-card">
        <div class="sa-card-title">全校重点课程 <span class="extra">按影响范围优先</span></div>
        <div v-if="schoolFocusCourses.length" class="focus-list">
          <button v-for="course in schoolFocusCourses" :key="course.course_id" class="focus-item" @click="openCourseFromSchool(course)">
            <span class="focus-name">{{ course.course_name }}</span>
            <span class="focus-college">{{ course.college_name }}</span>
            <span class="focus-reason">{{ course.teacher_count }}名教师 · {{ course.enrolled }}选课人次 · {{ course.lesson_count }}个教学班</span>
            <el-tag size="small" type="danger">{{ course.priority }}优先级</el-tag>
          </button>
        </div>
        <el-empty v-else description="当前没有重点核查课程" />
        <div class="focus-note">
          <b>如何使用</b>
          <p>先从左侧选择学院完成责任范围核查；也可直接点击重点课程，在同一抽屉中查看团队证据。</p>
        </div>
      </aside>
    </div>

    <section class="sa-card explain">
      <div class="sa-card-title">指标口径与管理边界</div>
      <p><b>高影响单点课程：</b>{{ definition.high_impact_courses }}</p>
      <p><b>教授本科教学参与率：</b>{{ definition.professor_participation }}</p>
      <p><b>主讲任务集中度：</b>{{ definition.load_share }}</p>
      <p><b>职称证据完整率：</b>{{ definition.title_completeness }} 当前完整率为 {{ data.summary.title_completeness_rate ?? '—' }}%。</p>
    </section>

    <el-drawer
      v-model="drawerVisible"
      class="faculty-drawer"
      :size="drawerWidth"
      :destroy-on-close="false"
      :close-on-click-modal="false"
      :modal="false"
      modal-class="faculty-nonblocking-overlay"
      @closed="afterDrawerClosed"
    >
      <template #header>
        <div class="drawer-heading">
          <el-button v-if="drawerMode === 'course' && selectedCollege" link type="primary" @click="backToCollege">← 返回学院核查</el-button>
          <div>
            <h2>{{ drawerTitle }}</h2>
            <p>{{ drawerSubtitle }}</p>
          </div>
        </div>
      </template>

      <div v-loading="drawerLoading" class="drawer-body">
        <template v-if="drawerMode === 'college' && collegeDetail">
          <el-alert type="info" :closable="false" show-icon title="核查说明" description="以下内容仅替换抽屉区域；全校概览保持在后台，关闭抽屉不会重新请求全校数据。" />
          <div class="sa-kpi-row drawer-kpis">
            <KpiCard v-for="item in collegeKpis" :key="item.label" v-bind="item" />
          </div>

          <div class="drawer-grid">
            <section class="drawer-section risk-section">
              <div class="section-head">
                <div><h3>需要核查的课程团队</h3><p>核查原因来自当期授课覆盖、教学规模和职称证据，不代表教师能力。</p></div>
              </div>
              <el-table :data="collegeDetail.risk_courses" stripe max-height="520">
                <el-table-column prop="course_name" label="课程" min-width="180" show-overflow-tooltip />
                <el-table-column prop="course_nature" label="课程性质" width="100" />
                <el-table-column prop="lesson_count" label="教学班" width="72" align="right" />
                <el-table-column prop="enrolled" label="选课人次" width="88" align="right" />
                <el-table-column prop="teacher_count" label="教师" width="65" align="right" />
                <el-table-column label="核查理由" min-width="240"><template #default="{ row }">{{ row.attention_reasons.join('；') }}</template></el-table-column>
                <el-table-column label="操作" width="92" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openCourse(row)">团队证据</el-button></template></el-table-column>
              </el-table>
            </section>

            <aside class="drawer-section teacher-section">
              <div class="section-head"><div><h3>主讲任务集中 TOP5</h3><p>仅用于核对任务分工，不认定超负荷。</p></div></div>
              <div v-for="teacher in collegeTopTeachers" :key="teacher.teacher_id" class="teacher-item">
                <div><b>{{ teacher.teacher_name }}</b><span>{{ teacher.title || '职称待补充' }}</span></div>
                <p>{{ teacher.course_count }}门课程 · {{ teacher.lesson_count }}个教学班</p>
                <strong>{{ teacher.enrolled }}人次</strong>
                <el-button link type="primary" @click="goTeacher(teacher)">教学档案</el-button>
              </div>
              <el-collapse v-if="collegeDetail.teachers.length > 5" class="more-teachers">
                <el-collapse-item :title="`查看其余 ${collegeDetail.teachers.length - 5} 名主讲教师`" name="more">
                  <div v-for="teacher in collegeDetail.teachers.slice(5)" :key="teacher.teacher_id" class="teacher-compact">
                    <span>{{ teacher.teacher_name }}</span><span>{{ teacher.lesson_count }}班 / {{ teacher.enrolled }}人次</span>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </aside>
          </div>
        </template>

        <template v-else-if="drawerMode === 'course' && courseDetail">
          <el-alert type="warning" :closable="false" show-icon title="课程团队证据边界" :description="courseDetail.boundary" />
          <div class="sa-kpi-row drawer-kpis">
            <KpiCard label="实际授课教师" :value="`${courseDetail.summary.teacher_count} 人`" hint="当前学期教学任务主教师与联合教师去重人数" tone="primary" />
            <KpiCard label="教学班" :value="`${courseDetail.summary.lesson_count} 个`" hint="当前学期该课程教学班数" tone="plain" />
            <KpiCard label="覆盖选课人次" :value="`${courseDetail.summary.enrolled} 人次`" hint="当前学期各教学班选课人次之和" tone="amber" />
            <KpiCard label="教授/副教授" :value="`${courseDetail.summary.professor_count} / ${courseDetail.summary.associate_professor_count} 人`" hint="按教师主数据规范化职称统计" tone="teal" />
            <KpiCard label="职称待补充" :value="`${courseDetail.summary.unknown_title_count} 人`" hint="团队成员中职称字段为空的人数" :tone="courseDetail.summary.unknown_title_count ? 'danger' : 'teal'" />
          </div>
          <div class="course-grid">
            <section class="drawer-section">
              <div class="section-head"><div><h3>实际授课团队成员</h3><p>来源于当前学期真实教学任务。</p></div></div>
              <el-table :data="courseDetail.members" stripe>
                <el-table-column prop="display_name" label="教师" min-width="110" />
                <el-table-column prop="staff_id" label="教师代码" width="125" />
                <el-table-column prop="title" label="职称" width="110"><template #default="{ row }">{{ row.title || '待补充' }}</template></el-table-column>
                <el-table-column prop="organization_id" label="所属组织" min-width="150" />
                <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="goTeacherFromMember(row)">教学档案</el-button></template></el-table-column>
              </el-table>
            </section>
            <section class="drawer-section">
              <div class="section-head"><div><h3>历史开课供给证据</h3><p>只证明已接入学期曾开设，不代表未来开课计划。</p></div></div>
              <el-table :data="courseDetail.offerings" stripe max-height="360">
                <el-table-column prop="semesterId" label="学期" width="120" />
                <el-table-column prop="lessonCount" label="教学班" width="75" align="right" />
                <el-table-column prop="teacherCount" label="教师" width="65" align="right" />
                <el-table-column prop="capacity" label="容量" width="75" align="right" />
                <el-table-column prop="enrolled" label="选课人次" width="90" align="right" />
                <el-table-column prop="avgClassSize" label="平均班额" width="85" align="right" />
              </el-table>
            </section>
          </div>
        </template>
      </div>
    </el-drawer>
    <el-drawer v-model="teacherDrawer.visible" :title="`${teacherDrawer.data.name || '教师'} · 本科教学档案`" size="720px" append-to-body :modal="false" modal-class="faculty-nonblocking-overlay">
      <div v-loading="teacherDrawer.loading">
        <el-alert type="info" :closable="false" show-icon title="档案仅在当前师资核查中展开" description="关闭后继续查看原学院或课程团队，不跳转到其他业务模块。" />
        <el-descriptions class="teacher-profile-summary" :column="2" border>
          <el-descriptions-item label="职工号">{{ teacherDrawer.data.code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="职称">{{ teacherDrawer.data.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="所属单位" :span="2">{{ teacherDrawer.data.deptName || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="sa-kpi-row teacher-profile-kpis"><KpiCard v-for="k in teacherProfileKpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" tone="primary" /></div>
        <section class="drawer-section">
          <div class="section-head"><div><h3>本学期教学班</h3><p>用于核对当期任务覆盖，不评价教师教学质量。</p></div></div>
          <el-table :data="teacherDrawer.data.currentCourses || []" size="small" max-height="300" empty-text="当前学期暂无教学班">
            <el-table-column prop="courseName" label="课程" min-width="150"/><el-table-column prop="className" label="教学班" min-width="150"/>
            <el-table-column prop="students" label="学生数" width="80" align="right"/><el-table-column prop="hours" label="学时" width="70" align="right"/>
          </el-table>
        </section>
        <section class="drawer-section teacher-history">
          <div class="section-head"><div><h3>近年授课证据</h3><p>用于判断课程经验和可替补范围。</p></div></div>
          <el-table :data="teacherDrawer.data.teachingHistory || []" size="small" max-height="300" empty-text="暂无历史记录">
            <el-table-column prop="semester" label="学期" width="120"/><el-table-column prop="courseName" label="课程" min-width="160"/>
            <el-table-column prop="students" label="修读人数" width="90" align="right"/><el-table-column prop="passRate" label="通过率" width="80" align="right"/>
          </el-table>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { http } from '@/utils/http'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import { COLLEGE_MAP } from '@/constants/colleges'
import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'

const semester = ref('')
const semesters = ref<SemesterOpt[]>([])
const pageLoading = ref(false)
const drawerLoading = ref(false)
const drawerVisible = ref(false)
const drawerMode = ref<'college' | 'course'>('college')
const collegeKeyword = ref('')
const selectedCollege = ref<{ id: string; name: string } | null>(null)
const selectedCourse = ref<{ id: string; name: string } | null>(null)
const collegeDetail = ref<any>(null)
const courseDetail = ref<any>(null)
const teacherDrawer = reactive<any>({visible:false,loading:false,data:{kpis:[],currentCourses:[],teachingHistory:[]}})
const data = reactive<any>({ summary: {}, colleges: [], risk_courses: [], teachers: [] })
const definition = reactive<any>({})
const collegeCache = new Map<string, any>()
const courseCache = new Map<string, any>()
let prefetchTimer: ReturnType<typeof setTimeout> | null = null

const collegeOptions = Object.entries(COLLEGE_MAP).map(([id, name]) => ({ id, name }))
const collegeIdByName = new Map(collegeOptions.map(item => [item.name, item.id]))
const fmt = (value: any, suffix = '') => value === null || value === undefined ? '—' : value + suffix
const affectedCollegeCount = computed(() => data.colleges.filter((item: any) => item.high_impact_courses > 0).length)
const schoolFocusCourses = computed(() => data.risk_courses.slice(0, 5))
const filteredColleges = computed(() => {
  const keyword = collegeKeyword.value.trim()
  return keyword ? data.colleges.filter((item: any) => item.college_name.includes(keyword)) : data.colleges
})
const drawerWidth = computed(() => window.innerWidth >= 1600 ? '74%' : window.innerWidth >= 1200 ? '82%' : '94%')
const drawerTitle = computed(() => drawerMode.value === 'course' ? `${selectedCourse.value?.name || '课程'} · 团队保障证据` : `${selectedCollege.value?.name || '学院'} · 师资保障核查`)
const drawerSubtitle = computed(() => drawerMode.value === 'course' ? `${semester.value}学期 · 在当前抽屉内返回学院核查，不重新加载学院数据` : `${semester.value}学期 · 关闭抽屉即可回到原全校概览`)
const collegeTopTeachers = computed(() => (collegeDetail.value?.teachers || []).slice(0, 5))
const teacherProfileKpis = computed(() => (teacherDrawer.data.kpis || []).filter((x:any) =>
  ['本学期授课门数','教学班记录','本学期总学时','近期平均成绩'].includes(x.label)))

const schoolKpis = computed(() => [
  { label: '本科教学活跃教师', value: fmt(data.summary.active_teachers, ' 人'), sub: `覆盖 ${data.summary.courses || 0} 门课程`, hint: definition.active_teachers || '', tone: 'primary' as const },
  { label: '单一教师覆盖课程', value: fmt(data.summary.single_teacher_courses, ' 门'), sub: '当前学期仅1名实际授课教师', hint: definition.single_teacher_courses || '', tone: 'amber' as const },
  { label: '高集中承担课程', value: fmt(data.summary.high_impact_courses, ' 门'), sub: `涉及 ${affectedCollegeCount.value} 个学院`, hint: definition.high_impact_courses || '', tone: 'danger' as const },
  { label: '教授本科教学参与率', value: fmt(data.summary.professor_participation_rate, '%'), sub: `${data.summary.professor_active || 0} / ${data.summary.professor_total || 0} 人`, hint: definition.professor_participation || '', tone: 'teal' as const },
  { label: '前10%主讲教师任务占比', value: fmt(data.summary.top10_load_share, '%'), sub: '按主讲字段覆盖选课人次计算', hint: definition.load_share || '', tone: 'plain' as const },
])

const collegeKpis = computed(() => {
  const summary = collegeDetail.value?.summary || {}
  return [
    { label: '实际授课教师', value: fmt(summary.active_teachers, ' 人'), sub: `覆盖 ${summary.courses || 0} 门课程`, hint: definition.active_teachers || '', tone: 'primary' as const },
    { label: '单点承担课程', value: fmt(summary.single_teacher_courses, ' 门'), sub: '当前学期仅1名实际授课教师', hint: definition.single_teacher_courses || '', tone: 'amber' as const },
    { label: '高集中承担课程', value: fmt(summary.high_impact_courses, ' 门'), sub: '人均班数与人次同时进入高集中区间', hint: definition.high_impact_courses || '', tone: 'danger' as const },
    { label: '教授参与率', value: fmt(summary.professor_participation_rate, '%'), sub: `${summary.professor_active || 0} / ${summary.professor_total || 0} 人`, hint: definition.professor_participation || '', tone: 'teal' as const },
    { label: '前10%主讲任务占比', value: fmt(summary.top10_load_share, '%'), sub: '仅表示任务集中程度', hint: definition.load_share || '', tone: 'plain' as const },
  ]
})

async function loadSchool() {
  pageLoading.value = true
  try {
    const result = await http.get<any>(`/admin/faculty/management-overview?semester=${encodeURIComponent(semester.value)}`)
    Object.assign(data, result)
    Object.assign(definition, result.definition)
  } finally {
    pageLoading.value = false
  }
}

async function fetchCollege(id: string) {
  const key = `${semester.value}:${id}`
  if (collegeCache.has(key)) return collegeCache.get(key)
  const query = new URLSearchParams({ semester: semester.value, college: id })
  const result = await http.get<any>('/admin/faculty/management-overview?' + query)
  collegeCache.set(key, result)
  return result
}

async function openCollege(row: any) {
  const id = row.college_id || collegeIdByName.get(row.college_name)
  if (!id) return
  selectedCollege.value = { id, name: row.college_name }
  selectedCourse.value = null
  courseDetail.value = null
  drawerMode.value = 'college'
  drawerVisible.value = true
  const cached = collegeCache.get(`${semester.value}:${id}`)
  if (cached) {
    collegeDetail.value = cached
    return
  }
  collegeDetail.value = null
  drawerLoading.value = true
  try { collegeDetail.value = await fetchCollege(id) } finally { drawerLoading.value = false }
}

function schedulePrefetch(row: any) {
  cancelPrefetch()
  const id = row.college_id || collegeIdByName.get(row.college_name)
  if (!id || collegeCache.has(`${semester.value}:${id}`)) return
  prefetchTimer = setTimeout(() => { void fetchCollege(id).catch(() => undefined) }, 250)
}

function cancelPrefetch() {
  if (prefetchTimer) clearTimeout(prefetchTimer)
  prefetchTimer = null
}

async function openCourse(row: any) {
  selectedCourse.value = { id: row.course_id, name: row.course_name }
  drawerMode.value = 'course'
  const key = `${semester.value}:${row.course_id}`
  if (courseCache.has(key)) {
    courseDetail.value = courseCache.get(key)
    return
  }
  courseDetail.value = null
  drawerLoading.value = true
  try {
    const result = await http.get<any>(`/admin/faculty/management-course/${encodeURIComponent(row.course_id)}?semester=${encodeURIComponent(semester.value)}`)
    courseCache.set(key, result)
    courseDetail.value = result
  } finally { drawerLoading.value = false }
}

async function openCourseFromSchool(row: any) {
  const id = data.colleges.find((item: any) => item.college_name === row.college_name)?.college_id || collegeIdByName.get(row.college_name)
  selectedCollege.value = id ? { id, name: row.college_name } : null
  drawerVisible.value = true
  if (id) {
    const cached = collegeCache.get(`${semester.value}:${id}`)
    if (cached) collegeDetail.value = cached
    else void fetchCollege(id).then(result => { collegeDetail.value = result }).catch(() => undefined)
  }
  await openCourse(row)
}

function backToCollege() {
  drawerMode.value = 'college'
  selectedCourse.value = null
  courseDetail.value = null
}

function afterDrawerClosed() {
  drawerMode.value = 'college'
  selectedCourse.value = null
  courseDetail.value = null
  drawerLoading.value = false
}

async function openTeacherProfile(teacherId: string, name = '') {
  teacherDrawer.visible=true; teacherDrawer.loading=true
  teacherDrawer.data={name,kpis:[],currentCourses:[],teachingHistory:[]}
  try { teacherDrawer.data=await http.get(`/admin/faculty/${encodeURIComponent(teacherId)}?semester=${encodeURIComponent(semester.value)}`) }
  finally { teacherDrawer.loading=false }
}
function goTeacher(row: any) { void openTeacherProfile(row.teacher_id, row.teacher_name) }
function goTeacherFromMember(row: any) { void openTeacherProfile(row.staff_id, row.display_name) }

async function changeSemester() {
  drawerVisible.value = false
  collegeCache.clear()
  courseCache.clear()
  await loadSchool()
}

onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = (meta.semesters || []).slice().reverse()
  semester.value = semesters.value[0]?.value || ''
  await loadSchool()
})
onBeforeUnmount(cancelPrefetch)
</script>

<style scoped>
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px}.semester{width:190px}.kpi-summary{margin-top:14px}.management-summary{display:flex;align-items:center;gap:14px;margin-bottom:14px;padding:12px 16px;border:1px solid #c7d2fe;border-radius:12px;background:#eef2ff;color:#475569;font-size:13px;line-height:1.6}.management-summary b{color:#312e81;font-size:15px}.summary-mark{flex:none;padding:4px 9px;border-radius:999px;background:#4f46e5;color:#fff;font-size:12px}.overview-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(300px,.82fr);gap:14px;align-items:start;margin-bottom:14px}.college-card,.focus-card{min-width:0}.section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}.section-head h3{margin:0 0 5px;font-size:16px;color:#0f172a}.section-head p{margin:0;color:#64748b;font-size:12px;line-height:1.5}.college-search{width:190px}:deep(.college-row){cursor:pointer}:deep(.college-row:hover .college-link){text-decoration:underline}.college-link{color:#4338ca;font-weight:600}.focus-list{display:flex;flex-direction:column;gap:8px}.focus-item{position:relative;display:grid;grid-template-columns:1fr auto;gap:4px 8px;width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;text-align:left;cursor:pointer}.focus-item:hover{border-color:#a5b4fc;background:#f8faff}.focus-name{overflow:hidden;color:#0f172a;font-weight:600;text-overflow:ellipsis;white-space:nowrap}.focus-college,.focus-reason{color:#64748b;font-size:11px}.focus-item .el-tag{grid-column:2;grid-row:1/3;align-self:center}.focus-note{margin-top:14px;padding:12px;border-radius:10px;background:#f8fafc;color:#475569;font-size:12px}.focus-note p{margin:5px 0 0;line-height:1.6}.explain p{margin:5px 0;color:#475569;font-size:13px;line-height:1.7}.drawer-heading{display:flex;align-items:flex-start;gap:12px}.drawer-heading h2{margin:0;color:#0f172a;font-size:20px}.drawer-heading p{margin:5px 0 0;color:#64748b;font-size:12px}.drawer-body{min-height:520px}.drawer-kpis{margin:14px 0}.drawer-grid{display:grid;grid-template-columns:minmax(0,2.3fr) minmax(260px,.8fr);gap:14px;align-items:start}.drawer-section{padding:15px;border:1px solid #e2e8f0;border-radius:12px;background:#fff}.teacher-item{position:relative;padding:11px 0;border-bottom:1px solid #eef2f7}.teacher-item:last-child{border-bottom:0}.teacher-item div{display:flex;justify-content:space-between;gap:8px}.teacher-item span,.teacher-item p{color:#64748b;font-size:11px}.teacher-item p{margin:5px 0}.teacher-item strong{color:#0f172a}.teacher-item .el-button{float:right}.more-teachers{margin-top:8px}.teacher-compact{display:flex;justify-content:space-between;padding:6px 0;color:#475569;font-size:12px}.course-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start}.teacher-profile-summary{margin:14px 0}.teacher-profile-kpis{margin-bottom:14px}.teacher-history{margin-top:14px}@media(max-width:1250px){.overview-grid{grid-template-columns:1fr}.drawer-grid,.course-grid{grid-template-columns:1fr}}
</style>
<style>
.faculty-nonblocking-overlay { pointer-events:none !important; }
.faculty-nonblocking-overlay .el-drawer { pointer-events:auto; }
</style>
