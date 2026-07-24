<template>
  <div class="faculty-page">
    <div class="head">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">{{ pageSubtitle }}</p>
      </div>
      <el-select v-model="semester" class="semester" placeholder="选择学期" @change="changeSemester">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>

    <BusinessPageContext
      :period="semester ? `统计学期：${semester}` : ''"
      source="教学任务、课程、教师职称与数据质量问题"
      :loading="pageLoading || refreshing"
    />

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="本页核查课程师资供给与团队连续性，不评价教师个人"
      :description="definition.boundary"
    />

    <el-skeleton v-if="pageLoading && !hasData" :rows="9" animated class="page-skeleton">
      <template #template>
        <div class="skeleton-kpis">
          <el-skeleton-item v-for="i in 5" :key="i" variant="rect" class="skeleton-kpi" />
        </div>
        <el-skeleton-item variant="rect" class="skeleton-summary" />
        <el-skeleton-item variant="rect" class="skeleton-table" />
      </template>
    </el-skeleton>

    <el-result
      v-else-if="pageError && !hasData"
      icon="warning"
      title="师资保障数据加载失败"
      :sub-title="pageError"
    >
      <template #extra><el-button type="primary" @click="loadOverview">重新加载</el-button></template>
    </el-result>

    <template v-else>
      <div class="kpi-filter-row" :class="{ 'is-refreshing': refreshing }">
        <button
          v-for="item in managementKpis"
          :key="item.key"
          type="button"
          class="kpi-filter"
          :class="{ active: activeReviewType === item.filter }"
          :aria-pressed="activeReviewType === item.filter"
          @click="toggleReviewFilter(item.filter)"
        >
          <KpiCard v-bind="item.card" />
        </button>
      </div>

      <div class="management-summary">
        <span class="summary-mark">本期管理要点</span>
        <span>{{ data.management_statement || '正在形成本期师资保障管理结论。' }}</span>
        <el-button v-if="activeReviewType" link type="primary" @click="clearReviewFilter">
          恢复全部课程
        </el-button>
      </div>

      <div v-if="activeReviewType" class="active-filter">
        <span>当前筛选：{{ reviewTypeLabel(activeReviewType) }}</span>
        <el-button link type="primary" @click="clearReviewFilter">清除筛选</el-button>
      </div>

      <section class="sa-card evidence-card">
        <div class="section-head">
          <div>
            <h3>本期证据就绪情况</h3>
            <p>未接入的证据不参与正式判断，避免把数据缺失误认为保障风险。</p>
          </div>
          <el-button link type="primary" @click="evidenceDrawer = true">查看口径边界</el-button>
        </div>
        <div class="evidence-strip">
          <button
            v-for="item in data.evidence_readiness"
            :key="item.key"
            type="button"
            class="evidence-item"
            @click="evidenceDrawer = true"
          >
            <span class="evidence-dot" :class="item.status" />
            <span><b>{{ item.label }}</b><small>{{ item.value }}</small></span>
          </button>
        </div>
        <div v-if="data.quality_gate?.excluded_lesson_count" class="quality-gate">
          已从正式指标排除
          <b>{{ data.quality_gate.excluded_lesson_count }}</b> 条异常教师任务，
          影响 <b>{{ data.quality_gate.affected_course_count }}</b> 门课程；
          相关课程仅进入数据核验，不形成正式保障结论。
        </div>
      </section>

      <div v-if="isSchoolScope" class="overview-grid">
        <section class="sa-card college-card" v-loading="refreshing">
          <div class="section-head">
            <div>
              <h3>学院师资保障概览</h3>
              <p>按课程责任学院汇总；点击学院进入本期课程核查队列。</p>
            </div>
            <el-input v-model="collegeKeyword" clearable placeholder="搜索学院" class="college-search" />
          </div>
          <DataTable
            :columns="collegeColumns"
            :data="filteredColleges"
            storage-key="faculty:college-assurance"
            :max-business-columns="6"
            config-version="2"
            stripe
            size="small"
            row-class-name="college-row"
            @row-click="openCollegeQueue"
            @cell-mouse-enter="schedulePrefetch"
            @cell-mouse-leave="cancelPrefetch"
          >
            <template #col-college_name="{ row }"><span class="college-link">{{ row.college_name }}</span></template>
            <template #col-priority_review_courses="{ row }">
              <el-tag :type="row.priority_review_courses ? 'danger' : 'success'" effect="plain">
                {{ row.priority_review_courses }}
              </el-tag>
            </template>
            <template #col-review_rate="{ row }">{{ row.review_rate }}%</template>
            <template #col-actions="{ row }">
              <el-button link type="primary" @click.stop="openCollegeQueue(row)">核查学院</el-button>
            </template>
          </DataTable>
        </section>

        <aside class="sa-card focus-card" v-loading="refreshing">
          <div class="section-head">
            <div>
              <h3>全校优先课程</h3>
              <p>只展示当前最需要分配管理注意力的课程。</p>
            </div>
            <el-button link type="primary" @click="openAllCourses">查看全部</el-button>
          </div>
          <div v-if="focusCourses.length" class="focus-list">
            <button
              v-for="course in focusCourses"
              :key="course.course_id"
              class="focus-item"
              type="button"
              @click="openCourse(course, true)"
            >
              <span class="focus-main">
                <b>{{ course.course_name }}</b>
                <small>{{ course.college_name }} · {{ course.course_nature }}</small>
              </span>
              <el-tag size="small" :type="reviewTagType(course.review_type)">
                {{ course.priority }}
              </el-tag>
              <span class="focus-reason">{{ course.attention_reasons?.[0] || '查看课程保障证据' }}</span>
            </button>
          </div>
          <el-empty v-else description="当前筛选下没有需优先核查的课程" />
        </aside>
      </div>

      <section v-else class="sa-card college-workbench" v-loading="refreshing">
        <div class="section-head">
          <div>
            <h3>{{ data.college || '本学院' }}师资保障工作区</h3>
            <p>当前仅展示本学院责任课程明细；其他学院只允许聚合比较，不开放课程团队下钻。</p>
          </div>
          <el-button type="primary" plain @click="openAllCourses">查看本院全部课程</el-button>
        </div>
        <div v-if="focusCourses.length" class="college-course-grid">
          <button
            v-for="course in focusCourses"
            :key="course.course_id"
            type="button"
            class="college-course"
            @click="openCourse(course, true)"
          >
            <span>
              <b>{{ course.course_name }}</b>
              <small>{{ course.course_nature }} · {{ course.lesson_count }}个班 · {{ course.enrolled }}人次</small>
            </span>
            <el-tag :type="reviewTagType(course.review_type)" effect="plain">{{ course.priority }}</el-tag>
            <p>{{ course.attention_reasons?.[0] }}</p>
            <em>查看证据 →</em>
          </button>
        </div>
        <el-empty v-else description="当前筛选下，本院没有需核查课程" />
      </section>

      <el-alert
        v-if="pageError"
        class="inline-error"
        type="error"
        :closable="false"
        show-icon
        :title="`本次刷新失败，页面仍保留上次成功数据：${pageError}`"
      >
        <template #default><el-button link type="danger" @click="loadOverview">重试</el-button></template>
      </el-alert>
    </template>

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
          <el-button v-if="drawerMode === 'course'" link type="primary" @click="backToQueue">
            ← 返回课程队列
          </el-button>
          <div>
            <h2>{{ drawerTitle }}</h2>
            <p>{{ drawerSubtitle }}</p>
          </div>
        </div>
      </template>

      <div class="drawer-body">
        <template v-if="drawerMode === 'queue'">
          <div class="queue-toolbar">
            <el-select v-model="queueReviewType" clearable placeholder="全部核查类型" @change="reloadQueue">
              <el-option v-for="item in reviewTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-input
              v-model="queueKeyword"
              clearable
              placeholder="搜索课程名称或代码"
              @keyup.enter="reloadQueue"
              @clear="reloadQueue"
            />
            <el-button type="primary" @click="reloadQueue">查询</el-button>
            <el-button v-if="queueReviewType || queueKeyword" @click="resetQueueFilter">恢复全部</el-button>
          </div>

          <div v-if="drawerLoading && !queueRows.length" class="drawer-skeleton">
            <el-skeleton :rows="8" animated />
            <p>正在汇总课程团队与跨学期开课证据…</p>
          </div>
          <el-result
            v-else-if="drawerError && !queueRows.length"
            icon="warning"
            title="课程队列加载失败"
            :sub-title="drawerError"
          >
            <template #extra><el-button type="primary" @click="loadQueue">重试</el-button></template>
          </el-result>
          <DataTable
            v-else
            v-loading="drawerLoading"
            :columns="courseQueueColumns"
            :data="queueRows"
            storage-key="faculty:course-review-queue"
            :max-business-columns="7"
            config-version="2"
            :page-size="queuePageSize"
            stripe
            size="small"
            empty-text="当前条件下没有课程"
            @update:page-size="changeQueuePageSize"
            @row-click="row => openCourse(row)"
          >
            <template #col-course_name="{ row }">
              <span class="course-link">{{ row.course_name }}</span>
              <small class="course-code">{{ row.course_id }}</small>
            </template>
            <template #col-review_type="{ row }">
              <el-tag :type="reviewTagType(row.review_type)" effect="plain">{{ row.priority }}</el-tag>
            </template>
            <template #col-attention_reasons="{ row }">
              <span class="reason-cell">{{ row.attention_reasons?.[0] || '一般观察' }}</span>
            </template>
            <template #col-actions="{ row }">
              <el-button link type="primary" @click.stop="openCourse(row)">查看证据</el-button>
            </template>
          </DataTable>
          <div v-if="queueTotal" class="queue-pagination">
            <span>共 {{ queueTotal }} 门课程</span>
            <el-pagination
              v-model:current-page="queuePage"
              v-model:page-size="queuePageSize"
              :total="queueTotal"
              :page-sizes="[10, 20, 50, 100]"
              layout="prev, pager, next"
              @current-change="loadQueue"
            />
          </div>
        </template>

        <template v-else-if="drawerMode === 'course'">
          <div v-if="drawerLoading && !courseDetail" class="drawer-skeleton">
            <el-skeleton :rows="10" animated />
            <p>正在核对触发规则、团队结构与历史开课连续性…</p>
          </div>
          <el-result
            v-else-if="drawerError && !courseDetail"
            icon="warning"
            title="课程证据加载失败"
            :sub-title="drawerError"
          >
            <template #extra><el-button type="primary" @click="reloadCurrentCourse">重试</el-button></template>
          </el-result>
          <template v-else-if="courseDetail">
            <section class="review-verdict" :class="courseDetail.review.type">
              <div>
                <el-tag :type="reviewTagType(courseDetail.review.type)" effect="dark">
                  {{ courseDetail.review.label }}
                </el-tag>
                <h3>为什么进入当前队列</h3>
                <ul>
                  <li v-for="reason in courseDetail.review.reasons" :key="reason">{{ reason }}</li>
                </ul>
              </div>
              <div class="suggested-check">
                <b>建议核实事项</b>
                <p>{{ courseDetail.review.suggested_check }}</p>
                <small>规则版本：{{ courseDetail.review.rule_version }}</small>
              </div>
            </section>

            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="结论适用边界"
              :description="courseDetail.boundary"
            />

            <div class="sa-kpi-row drawer-kpis">
              <KpiCard label="实际授课教师" :value="`${courseDetail.summary.teacher_count} 人`" sub="主讲与联合教师去重" hint="来自当前学期有效教学任务，已排除登记异常任务" tone="primary" />
              <KpiCard label="教学班" :value="`${courseDetail.summary.lesson_count} 个`" sub="当前有效教学任务" hint="被数据质量门禁排除的教学班不进入此数" tone="plain" />
              <KpiCard label="覆盖学生人次" :value="`${courseDetail.summary.enrolled} 人次`" sub="各教学班选课人次之和" hint="联合授课不拆分教师贡献比例" tone="amber" />
              <KpiCard label="职称证据" :value="`${courseDetail.summary.teacher_count - courseDetail.summary.unknown_title_count}/${courseDetail.summary.teacher_count} 人`" sub="仅用于课程团队结构核实" hint="职称缺失时不形成正式结构结论" tone="teal" />
              <KpiCard label="异常任务排除" :value="`${courseDetail.summary.excluded_lesson_count} 条`" sub="不进入正式指标" hint="命中已登记高/严重数据质量问题的教学任务" :tone="courseDetail.summary.excluded_lesson_count ? 'danger' : 'plain'" />
            </div>

            <section class="continuity-summary">
              <div>
                <h3>跨学期供给连续性</h3>
                <p>{{ courseDetail.continuity.summary }}</p>
              </div>
              <div class="continuity-semesters">
                <span v-for="item in courseDetail.continuity.recent" :key="item.semesterId">
                  <b>{{ item.semesterId }}</b>
                  {{ item.teacherCount }}名教师 / {{ item.lessonCount }}个班
                </span>
              </div>
            </section>

            <section class="drawer-section">
              <div class="section-head">
                <div><h3>当前实际授课团队</h3><p>教师经历仅为课程保障核查提供证据，不展示成绩评价。</p></div>
              </div>
              <DataTable
                :columns="teamColumns"
                :data="courseDetail.members"
                storage-key="faculty:course-team"
                :max-business-columns="6"
                config-version="2"
                stripe
                size="small"
              >
                <template #col-display_name="{ row }"><b>{{ row.display_name }}</b></template>
                <template #col-title="{ row }">{{ row.title || '待补充' }}</template>
                <template #col-organization_id="{ row }">{{ row.organization_id || '待映射' }}</template>
                <template #col-actions="{ row }">
                  <el-button link type="primary" @click="openTeacher(row)">教学经历</el-button>
                </template>
              </DataTable>
            </section>

            <el-collapse class="history-collapse">
              <el-collapse-item name="history">
                <template #title>
                  <span class="collapse-title">查看全部历史开课记录（{{ courseDetail.offerings.length }}个学期）</span>
                </template>
                <DataTable
                  :columns="offeringColumns"
                  :data="courseDetail.offerings"
                  storage-key="faculty:course-offerings"
                  :max-business-columns="6"
                  config-version="2"
                  pagination
                  :default-page-size="10"
                  stripe
                  size="small"
                />
              </el-collapse-item>
            </el-collapse>

            <section class="source-section">
              <b>数据来源</b>
              <span v-for="source in courseDetail.sources" :key="source.table">
                {{ source.name }}（{{ source.table }}，{{ source.time || '当前批次' }}）
              </span>
            </section>
          </template>
        </template>
      </div>
    </el-drawer>

    <el-drawer
      v-model="teacherDrawer.visible"
      :title="`${teacherDrawer.data.name || '教师'} · 教学经历证据`"
      size="760px"
      append-to-body
      :modal="false"
      modal-class="faculty-nonblocking-overlay"
      @closed="closeTeacherDrawer"
    >
      <div v-loading="teacherDrawer.loading" class="teacher-drawer">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="只呈现课程保障所需的教学经历"
          :description="teacherDrawer.data.boundary || '不展示平均成绩、通过率或模拟个人画像，不用于教师绩效评价。'"
        />
        <el-alert
          v-if="teacherDrawer.data.dataQuality"
          class="teacher-quality-alert"
          type="error"
          :closable="false"
          show-icon
          title="当前学期教学任务存在待核验数据问题"
          :description="teacherDrawer.data.dataQuality.detail"
        />
        <el-descriptions class="teacher-profile-summary" :column="2" border>
          <el-descriptions-item label="职工号">{{ teacherDrawer.data.code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="职称">{{ teacherDrawer.data.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="人事归属" :span="2">{{ teacherDrawer.data.deptName || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="sa-kpi-row teacher-profile-kpis">
          <KpiCard v-for="k in teacherDrawer.data.kpis || []" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" tone="primary" />
        </div>
        <section class="drawer-section">
          <div class="section-head"><div><h3>本学期教学任务</h3><p>联合授课不拆分贡献比例，所列学时不等同于人事核定工作量。</p></div></div>
          <DataTable
            :columns="teacherCurrentColumns"
            :data="teacherDrawer.data.currentCourses || []"
            storage-key="faculty:teacher-current-courses"
            :max-business-columns="6"
            config-version="2"
            pagination
            :default-page-size="10"
            stripe
            size="small"
            empty-text="当前学期暂无教学任务"
          />
        </section>
        <section class="drawer-section teacher-history">
          <div class="section-head"><div><h3>近年授课经历</h3><p>用于判断课程经验与实际供给范围，不作教学质量排名。</p></div></div>
          <DataTable
            :columns="teacherHistoryColumns"
            :data="teacherDrawer.data.teachingHistory || []"
            storage-key="faculty:teacher-history"
            :max-business-columns="6"
            config-version="2"
            pagination
            :default-page-size="10"
            stripe
            size="small"
            empty-text="暂无历史记录"
          />
        </section>
      </div>
    </el-drawer>

    <el-drawer v-model="evidenceDrawer" title="师资保障指标口径与证据边界" size="620px">
      <div class="evidence-detail">
        <el-alert type="warning" :closable="false" show-icon title="证据不足时不输出正式结论" :description="definition.boundary" />
        <section v-for="item in data.evidence_readiness" :key="item.key">
          <div><span class="evidence-dot" :class="item.status" /><b>{{ item.label }}</b><em>{{ item.value }}</em></div>
          <p>{{ item.note }}</p>
        </section>
        <section class="definition-list">
          <h3>五个顶层指标</h3>
          <p><b>可评估课程：</b>{{ definition.evaluable_courses }}</p>
          <p><b>优先核查课程：</b>{{ definition.priority_review_courses }}</p>
          <p><b>连续单点课程：</b>{{ definition.continuous_single_courses }}</p>
          <p><b>结构待核实课程：</b>{{ definition.structure_review_courses }}</p>
          <p><b>数据候选课程：</b>{{ definition.data_candidate_courses }}</p>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { http } from '@/utils/http'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import KpiCard from '@/components/KpiCard.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import { useBusinessPageTitle } from '@/utils/businessPage'

type DrawerMode = 'queue' | 'course'

const route = useRoute()
const router = useRouter()
const pageTitle = useBusinessPageTitle('/admin/faculty', '师资保障分析')
const semester = ref('')
const semesters = ref<SemesterOpt[]>([])
const pageLoading = ref(false)
const refreshing = ref(false)
const pageError = ref('')
const drawerLoading = ref(false)
const drawerError = ref('')
const drawerVisible = ref(false)
const drawerMode = ref<DrawerMode>('queue')
const evidenceDrawer = ref(false)
const collegeKeyword = ref('')
const activeReviewType = ref('')
const selectedCollege = ref<{ id: string; name: string } | null>(null)
const selectedCourse = ref<{ id: string; name: string } | null>(null)
const courseDetail = ref<any>(null)
const queueRows = ref<any[]>([])
const queueTotal = ref(0)
const queuePage = ref(1)
const queuePageSize = ref(20)
const queueReviewType = ref('')
const queueKeyword = ref('')
const data = reactive<any>({
  summary: {},
  colleges: [],
  risk_courses: [],
  evidence_readiness: [],
  quality_gate: {},
})
const definition = reactive<any>({})
const teacherDrawer = reactive<any>({
  visible: false,
  loading: false,
  data: { kpis: [], currentCourses: [], teachingHistory: [] },
})
const queueCache = new Map<string, any>()
const courseCache = new Map<string, any>()
let prefetchTimer: ReturnType<typeof setTimeout> | null = null

const hasData = computed(() => Object.keys(data.summary || {}).length > 0)
const isSchoolScope = computed(() => data.scope_mode !== 'college')
const pageSubtitle = computed(() => isSchoolScope.value
  ? '从全校识别真正需要学院核实的课程团队保障事项，再下钻查看证据。'
  : `聚焦${data.college || '本学院'}责任课程，明确先核实哪门课、为什么以及缺少什么证据。`)
const drawerWidth = computed(() => window.innerWidth >= 1600 ? '76%' : window.innerWidth >= 1200 ? '86%' : '96%')
const drawerTitle = computed(() => drawerMode.value === 'course'
  ? `${selectedCourse.value?.name || '课程'} · 师资保障证据`
  : `${selectedCollege.value?.name || (isSchoolScope.value ? '全校' : data.college || '本学院')} · 课程核查队列`)
const drawerSubtitle = computed(() => `${semester.value}学期 · 所有筛选和核查均在当前工作区完成`)
const focusCourses = computed(() => {
  const rows = data.risk_courses || []
  return (activeReviewType.value
    ? rows.filter((row: any) => activeReviewType.value === 'continuous_single'
      ? row.continuous_single
      : row.review_type === activeReviewType.value)
    : rows.filter((row: any) => isSchoolScope.value
      ? row.review_type === 'priority_review'
      : row.review_type !== 'general_observation')
  ).slice(0, isSchoolScope.value ? 8 : 12)
})
const filteredColleges = computed(() => {
  const keyword = collegeKeyword.value.trim()
  const rows = (data.colleges || []).map((row: any) => ({
    ...row,
    review_rate: row.evaluable_courses
      ? Math.round(row.priority_review_courses * 1000 / row.evaluable_courses) / 10
      : 0,
  }))
  return keyword ? rows.filter((row: any) => row.college_name.includes(keyword)) : rows
})

const reviewTypeOptions = [
  { value: 'priority_review', label: '优先核查' },
  { value: 'continuous_single', label: '连续单点' },
  { value: 'structure_review', label: '结构核查' },
  { value: 'data_candidate', label: '数据候选' },
  { value: 'general_observation', label: '一般观察' },
]
const reviewTypeLabel = (value: string) =>
  reviewTypeOptions.find(item => item.value === value)?.label || '全部课程'
const reviewTagType = (value: string) =>
  value === 'priority_review' ? 'danger'
    : value === 'structure_review' ? 'warning'
      : value === 'data_candidate' ? 'info' : 'success'
const fmt = (value: any, suffix = '') =>
  value === null || value === undefined ? '—' : `${value}${suffix}`

const managementKpis = computed(() => [
  {
    key: 'evaluable',
    filter: '',
    card: {
      label: '可评估课程',
      value: fmt(data.summary.evaluable_courses, ' 门'),
      sub: `本期共 ${data.summary.courses || 0} 门开课课程`,
      hint: definition.evaluable_courses || '',
      tone: 'primary' as const,
    },
  },
  {
    key: 'priority',
    filter: 'priority_review',
    card: {
      label: '优先核查课程',
      value: fmt(data.summary.priority_review_courses, ' 门'),
      sub: '点击筛选本期优先事项',
      hint: definition.priority_review_courses || '',
      tone: 'danger' as const,
    },
  },
  {
    key: 'continuous',
    filter: 'continuous_single',
    card: {
      label: '连续单点课程',
      value: fmt(data.summary.continuous_single_courses, ' 门'),
      sub: '最近3次实际开课证据',
      hint: definition.continuous_single_courses || '',
      tone: 'amber' as const,
    },
  },
  {
    key: 'structure',
    filter: 'structure_review',
    card: {
      label: '结构待核实课程',
      value: fmt(data.summary.structure_review_courses, ' 门'),
      sub: '职称证据达到判断门槛',
      hint: definition.structure_review_courses || '',
      tone: 'teal' as const,
    },
  },
  {
    key: 'data',
    filter: 'data_candidate',
    card: {
      label: '数据候选课程',
      value: fmt(data.summary.data_candidate_courses, ' 门'),
      sub: '先核实数据，不形成结论',
      hint: definition.data_candidate_courses || '',
      tone: 'plain' as const,
    },
  },
])

const collegeColumns: DataTableColumn[] = [
  { key: 'college_name', label: '学院', minWidth: 180, fixed: 'left', required: true, region: 'identity' },
  { key: 'evaluable_courses', label: '可评估课程', width: 105, align: 'right', required: true, region: 'business' },
  { key: 'priority_review_courses', label: '优先核查', width: 100, align: 'center', required: true, region: 'business' },
  { key: 'continuous_single_courses', label: '连续单点', width: 95, align: 'right', region: 'business' },
  { key: 'structure_review_courses', label: '结构核查', width: 95, align: 'right', region: 'business' },
  { key: 'data_candidate_courses', label: '数据候选', width: 95, align: 'right', region: 'business' },
  { key: 'review_rate', label: '优先核查率', width: 105, align: 'right', region: 'business', defaultVisible: false },
  { key: 'lessons', label: '教学班', width: 85, align: 'right', region: 'business', defaultVisible: false },
  { key: 'enrolled', label: '学生人次', width: 95, align: 'right', region: 'business', defaultVisible: false },
  { key: 'actions', label: '操作', width: 95, fixed: 'right', required: true, region: 'action' },
]
const courseQueueColumns: DataTableColumn[] = [
  { key: 'course_name', label: '课程', minWidth: 190, fixed: 'left', required: true, region: 'identity' },
  { key: 'course_nature', label: '性质', width: 80, region: 'business' },
  { key: 'review_type', label: '核查类型', width: 100, required: true, region: 'business' },
  { key: 'lesson_count', label: '教学班', width: 80, align: 'right', region: 'business' },
  { key: 'enrolled', label: '学生人次', width: 90, align: 'right', required: true, region: 'business' },
  { key: 'teacher_count', label: '教师', width: 70, align: 'right', region: 'business' },
  { key: 'attention_reasons', label: '首要核查原因', minWidth: 280, tooltip: true, required: true, region: 'business' },
  { key: 'college_name', label: '责任学院', minWidth: 160, defaultVisible: false, region: 'business' },
  { key: 'continuity_observations', label: '历史观察次数', width: 110, align: 'right', defaultVisible: false, region: 'business' },
  { key: 'title_completeness_rate', label: '职称证据率', width: 110, align: 'right', defaultVisible: false, region: 'business', formatter: row => `${row.title_completeness_rate}%` },
  { key: 'actions', label: '操作', width: 95, fixed: 'right', required: true, region: 'action' },
]
const teamColumns: DataTableColumn[] = [
  { key: 'display_name', label: '教师', minWidth: 110, fixed: 'left', required: true, region: 'identity' },
  { key: 'team_role', label: '团队角色', width: 95, required: true, region: 'business' },
  { key: 'lesson_count', label: '教学班', width: 80, align: 'right', required: true, region: 'business' },
  { key: 'enrolled', label: '学生人次', width: 95, align: 'right', required: true, region: 'business' },
  { key: 'lesson_share', label: '教学班占比', width: 105, align: 'right', region: 'business', formatter: row => `${row.lesson_share}%` },
  { key: 'title', label: '职称', width: 105, region: 'business' },
  { key: 'organization_id', label: '人事归属', minWidth: 160, region: 'business' },
  { key: 'staff_id', label: '教师代码', width: 125, defaultVisible: false, region: 'business' },
  { key: 'actions', label: '操作', width: 95, fixed: 'right', required: true, region: 'action' },
]
const offeringColumns: DataTableColumn[] = [
  { key: 'semesterId', label: '学期', width: 125, fixed: 'left', required: true, region: 'identity' },
  { key: 'lessonCount', label: '教学班', width: 85, align: 'right', required: true, region: 'business' },
  { key: 'teacherCount', label: '教师', width: 75, align: 'right', required: true, region: 'business' },
  { key: 'enrolled', label: '学生人次', width: 100, align: 'right', region: 'business' },
  { key: 'capacity', label: '容量', width: 85, align: 'right', region: 'business' },
  { key: 'avgClassSize', label: '平均班额', width: 95, align: 'right', region: 'business' },
]
const teacherCurrentColumns: DataTableColumn[] = [
  { key: 'courseName', label: '课程', minWidth: 160, fixed: 'left', required: true, region: 'identity' },
  { key: 'teamRole', label: '角色', width: 90, required: true, region: 'business' },
  { key: 'className', label: '教学班', minWidth: 160, region: 'business' },
  { key: 'students', label: '学生数', width: 85, align: 'right', required: true, region: 'business' },
  { key: 'hours', label: '学时', width: 75, align: 'right', region: 'business' },
  { key: 'courseDept', label: '课程责任学院', minWidth: 160, defaultVisible: false, region: 'business' },
]
const teacherHistoryColumns: DataTableColumn[] = [
  { key: 'semester', label: '学期', width: 125, fixed: 'left', required: true, region: 'identity' },
  { key: 'courseName', label: '课程', minWidth: 170, required: true, region: 'business' },
  { key: 'teamRole', label: '角色', width: 90, region: 'business' },
  { key: 'lessonCount', label: '教学班', width: 85, align: 'right', region: 'business' },
  { key: 'students', label: '学生人次', width: 100, align: 'right', region: 'business' },
  { key: 'hours', label: '学时', width: 75, align: 'right', region: 'business' },
  { key: 'courseDept', label: '课程责任学院', minWidth: 160, defaultVisible: false, region: 'business' },
]

function currentQuery(extra: Record<string, any> = {}) {
  const query: Record<string, any> = { ...route.query, semester: semester.value, ...extra }
  Object.keys(query).forEach(key => {
    if (query[key] === '' || query[key] === null || query[key] === undefined) delete query[key]
  })
  return query
}

async function syncUrl(extra: Record<string, any> = {}) {
  await router.replace({ path: '/admin/faculty', query: currentQuery(extra) })
}

async function loadOverview() {
  const firstLoad = !hasData.value
  pageLoading.value = firstLoad
  refreshing.value = !firstLoad
  pageError.value = ''
  try {
    const result = await http.get<any>(`/admin/faculty/management-overview?semester=${encodeURIComponent(semester.value)}`)
    Object.assign(data, result)
    Object.keys(definition).forEach(key => delete definition[key])
    Object.assign(definition, result.definition || {})
  } catch (error: any) {
    pageError.value = error?.message || '请求失败'
  } finally {
    pageLoading.value = false
    refreshing.value = false
  }
}

function toggleReviewFilter(filter: string) {
  if (!filter) {
    clearReviewFilter()
    return
  }
  activeReviewType.value = activeReviewType.value === filter ? '' : filter
  void syncUrl({ review: activeReviewType.value || undefined })
}
function clearReviewFilter() {
  activeReviewType.value = ''
  void syncUrl({ review: undefined })
}

function queueCacheKey(collegeId?: string) {
  return [
    semester.value,
    collegeId || '',
    queueReviewType.value,
    queueKeyword.value.trim(),
    queuePage.value,
    queuePageSize.value,
  ].join(':')
}

async function fetchQueueResult(collegeId = '') {
  const query = new URLSearchParams({
    semester: semester.value,
    page: String(queuePage.value),
    page_size: String(queuePageSize.value),
  })
  if (collegeId) query.set('college', collegeId)
  if (queueReviewType.value) query.set('review_type', queueReviewType.value)
  if (queueKeyword.value.trim()) query.set('keyword', queueKeyword.value.trim())
  return http.get<any>(`/admin/faculty/management-courses?${query}`)
}

async function loadQueue(force = false) {
  const collegeId = selectedCollege.value?.id || ''
  const cacheKey = queueCacheKey(collegeId)
  if (!force && queueCache.has(cacheKey)) {
    const cached = queueCache.get(cacheKey)
    queueRows.value = cached.items
    queueTotal.value = cached.total
    return
  }
  drawerLoading.value = true
  drawerError.value = ''
  try {
    const result = await fetchQueueResult(collegeId)
    queueRows.value = result.items || []
    queueTotal.value = result.total || 0
    queueCache.set(cacheKey, result)
  } catch (error: any) {
    drawerError.value = error?.message || '请求失败'
  } finally {
    drawerLoading.value = false
  }
}

async function openCollegeQueue(row: any) {
  selectedCollege.value = { id: row.college_id, name: row.college_name }
  drawerMode.value = 'queue'
  drawerVisible.value = true
  queuePage.value = 1
  queueReviewType.value = activeReviewType.value
  courseDetail.value = null
  await syncUrl({ college: row.college_id, course: undefined, teacher: undefined })
  await loadQueue()
}

async function openAllCourses() {
  selectedCollege.value = isSchoolScope.value
    ? null
    : { id: data.college_id, name: data.college }
  drawerMode.value = 'queue'
  drawerVisible.value = true
  queuePage.value = 1
  queueReviewType.value = activeReviewType.value
  courseDetail.value = null
  await syncUrl({ college: selectedCollege.value?.id, course: undefined, teacher: undefined })
  await loadQueue()
}

function schedulePrefetch(row: any) {
  cancelPrefetch()
  if (!row.college_id) return
  prefetchTimer = setTimeout(async () => {
    const cacheKey = queueCacheKey(row.college_id)
    if (queueCache.has(cacheKey)) return
    const result = await fetchQueueResult(row.college_id).catch(() => null)
    if (result) queueCache.set(cacheKey, result)
  }, 250)
}
function cancelPrefetch() {
  if (prefetchTimer) clearTimeout(prefetchTimer)
  prefetchTimer = null
}

async function openCourse(row: any, fromOverview = false) {
  selectedCourse.value = { id: row.course_id, name: row.course_name }
  if (fromOverview && row.college_id) {
    selectedCollege.value = { id: row.college_id, name: row.college_name }
  }
  drawerMode.value = 'course'
  drawerVisible.value = true
  drawerError.value = ''
  const key = `${semester.value}:${row.course_id}`
  await syncUrl({
    college: selectedCollege.value?.id,
    course: row.course_id,
    teacher: undefined,
  })
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
  } catch (error: any) {
    drawerError.value = error?.message || '请求失败'
  } finally {
    drawerLoading.value = false
  }
}

async function reloadCurrentCourse() {
  if (!selectedCourse.value) return
  courseCache.delete(`${semester.value}:${selectedCourse.value.id}`)
  await openCourse({
    course_id: selectedCourse.value.id,
    course_name: selectedCourse.value.name,
    college_id: selectedCollege.value?.id,
    college_name: selectedCollege.value?.name,
  })
}

async function backToQueue() {
  drawerMode.value = 'queue'
  courseDetail.value = null
  selectedCourse.value = null
  await syncUrl({ course: undefined, teacher: undefined })
  if (!queueRows.value.length) await loadQueue()
}

function afterDrawerClosed() {
  drawerMode.value = 'queue'
  selectedCourse.value = null
  courseDetail.value = null
  selectedCollege.value = null
  drawerError.value = ''
  void syncUrl({ college: undefined, course: undefined, teacher: undefined })
}

async function reloadQueue() {
  queuePage.value = 1
  queueCache.clear()
  await loadQueue(true)
}
async function resetQueueFilter() {
  queueReviewType.value = ''
  queueKeyword.value = ''
  await reloadQueue()
}
async function changeQueuePageSize(value: number) {
  queuePageSize.value = value
  queuePage.value = 1
  await loadQueue()
}

async function openTeacher(row: any) {
  const teacherId = row.staff_id
  teacherDrawer.visible = true
  teacherDrawer.loading = true
  teacherDrawer.data = {
    name: row.display_name,
    kpis: [],
    currentCourses: [],
    teachingHistory: [],
  }
  await syncUrl({ teacher: teacherId })
  try {
    const query = new URLSearchParams({ semester: semester.value })
    if (selectedCourse.value?.id) query.set('course_id', selectedCourse.value.id)
    teacherDrawer.data = await http.get(
      `/admin/faculty/management-teacher/${encodeURIComponent(teacherId)}?${query}`,
    )
  } catch (error: any) {
    ElMessage.error(error?.message || '教师教学经历加载失败')
  } finally {
    teacherDrawer.loading = false
  }
}

function closeTeacherDrawer() {
  void syncUrl({ teacher: undefined })
}

async function changeSemester() {
  queueCache.clear()
  courseCache.clear()
  await syncUrl({})
  await loadOverview()
  if (drawerVisible.value && selectedCourse.value) {
    await reloadCurrentCourse()
  } else if (drawerVisible.value) {
    await reloadQueue()
  }
}

async function restoreRouteContext() {
  const collegeId = String(route.query.college || '')
  const courseId = String(route.query.course || '')
  const teacherId = String(route.query.teacher || '')
  const review = String(route.query.review || '')
  if (reviewTypeOptions.some(item => item.value === review)) activeReviewType.value = review
  if (collegeId) {
    const college = (data.colleges || []).find((row: any) => row.college_id === collegeId)
    selectedCollege.value = {
      id: collegeId,
      name: college?.college_name || data.college || collegeId,
    }
  }
  if (courseId) {
    const course = (data.risk_courses || []).find((row: any) => row.course_id === courseId)
    await openCourse({
      course_id: courseId,
      course_name: course?.course_name || String(route.query.courseName || courseId),
      college_id: selectedCollege.value?.id,
      college_name: selectedCollege.value?.name,
    })
  } else if (collegeId) {
    drawerMode.value = 'queue'
    drawerVisible.value = true
    await loadQueue()
  }
  if (teacherId) {
    await openTeacher({ staff_id: teacherId, display_name: teacherId })
  }
}

onMounted(async () => {
  const meta = await getFilterMeta()
  semesters.value = (meta.semesters || []).slice().reverse()
  const querySemester = String(route.query.semester || '')
  semester.value = semesters.value.some(item => item.value === querySemester)
    ? querySemester
    : semesters.value[0]?.value || ''
  await loadOverview()
  if (hasData.value) await restoreRouteContext()
})
onBeforeUnmount(cancelPrefetch)
</script>

<style scoped>
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px}.semester{width:190px}.page-skeleton{margin-top:16px}.skeleton-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.skeleton-kpi{height:112px;border-radius:14px}.skeleton-summary{height:54px;margin:14px 0;border-radius:12px}.skeleton-table{height:420px;border-radius:14px}.kpi-filter-row{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:14px 0;transition:opacity .2s}.kpi-filter-row.is-refreshing{opacity:.72}.kpi-filter{padding:0;border:0;border-radius:14px;background:transparent;text-align:left;cursor:pointer}.kpi-filter :deep(.sa-kpi){height:100%;transition:border-color .2s,box-shadow .2s}.kpi-filter:hover :deep(.sa-kpi),.kpi-filter.active :deep(.sa-kpi){border-color:#818cf8;box-shadow:0 0 0 2px rgba(99,102,241,.1)}.kpi-filter.active :deep(.sa-kpi){background:#f8faff}.management-summary{display:flex;align-items:center;gap:12px;margin-bottom:12px;padding:13px 16px;border:1px solid #c7d2fe;border-radius:12px;background:#eef2ff;color:#475569;font-size:13px;line-height:1.6}.management-summary .el-button{margin-left:auto}.summary-mark{flex:none;padding:4px 9px;border-radius:999px;background:#4f46e5;color:#fff;font-size:12px}.active-filter{display:flex;align-items:center;gap:8px;width:max-content;margin:0 0 12px;padding:6px 10px;border-radius:999px;background:#f1f5f9;color:#475569;font-size:12px}.evidence-card{margin-bottom:14px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}.section-head h3{margin:0 0 5px;color:#0f172a;font-size:16px}.section-head p{margin:0;color:#64748b;font-size:12px;line-height:1.5}.evidence-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.evidence-item{display:flex;align-items:center;gap:9px;padding:10px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;text-align:left;cursor:pointer}.evidence-item:hover{border-color:#a5b4fc}.evidence-item span:last-child{display:flex;min-width:0;flex-direction:column;gap:3px}.evidence-item b{overflow:hidden;color:#334155;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.evidence-item small{color:#64748b}.evidence-dot{width:9px;height:9px;flex:none;border-radius:50%;background:#94a3b8}.evidence-dot.ready{background:#10b981}.evidence-dot.missing{background:#cbd5e1}.quality-gate{margin-top:10px;padding:8px 11px;border-radius:8px;background:#fff7ed;color:#9a3412;font-size:12px}.overview-grid{display:grid;grid-template-columns:minmax(0,2.1fr) minmax(320px,.9fr);gap:14px;align-items:start}.college-search{width:190px}:deep(.college-row){cursor:pointer}:deep(.college-row:hover .college-link){text-decoration:underline}.college-link,.course-link{color:#4338ca;font-weight:600}.focus-list{display:flex;flex-direction:column;gap:8px}.focus-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 10px;width:100%;padding:11px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;text-align:left;cursor:pointer}.focus-item:hover{border-color:#a5b4fc;background:#f8faff}.focus-main{display:flex;min-width:0;flex-direction:column;gap:3px}.focus-main b{overflow:hidden;color:#0f172a;text-overflow:ellipsis;white-space:nowrap}.focus-main small,.focus-reason{color:#64748b;font-size:11px}.focus-reason{grid-column:1/3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.college-workbench{min-height:320px}.college-course-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.college-course{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px 10px;padding:14px;border:1px solid #e2e8f0;border-radius:11px;background:#fff;text-align:left;cursor:pointer}.college-course:hover{border-color:#a5b4fc;background:#f8faff}.college-course span{display:flex;min-width:0;flex-direction:column;gap:4px}.college-course b{overflow:hidden;color:#0f172a;text-overflow:ellipsis;white-space:nowrap}.college-course small,.college-course p{color:#64748b;font-size:11px}.college-course p{grid-column:1/3;margin:0;line-height:1.6}.college-course em{grid-column:1/3;color:#4f46e5;font-size:12px;font-style:normal}.inline-error{margin-top:12px}.drawer-heading{display:flex;align-items:flex-start;gap:12px}.drawer-heading h2{margin:0;color:#0f172a;font-size:20px}.drawer-heading p{margin:5px 0 0;color:#64748b;font-size:12px}.drawer-body{min-height:560px}.queue-toolbar{display:grid;grid-template-columns:180px minmax(220px,360px) auto auto;gap:10px;margin-bottom:13px}.drawer-skeleton{position:relative;padding:18px}.drawer-skeleton p{text-align:center;color:#64748b;font-size:12px}.course-code{display:block;margin-top:3px;color:#94a3b8}.reason-cell{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.queue-pagination{display:flex;align-items:center;justify-content:space-between;margin-top:12px;color:#64748b;font-size:12px}.review-verdict{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,.7fr);gap:18px;margin-bottom:14px;padding:16px;border:1px solid #fecdd3;border-left:5px solid #e11d48;border-radius:12px;background:#fff7f8}.review-verdict.structure_review{border-color:#fde68a;border-left-color:#d97706;background:#fffbeb}.review-verdict.data_candidate{border-color:#cbd5e1;border-left-color:#64748b;background:#f8fafc}.review-verdict h3{margin:9px 0 6px;color:#0f172a;font-size:17px}.review-verdict ul{margin:0;padding-left:20px;color:#475569;font-size:13px;line-height:1.7}.suggested-check{padding:12px;border-radius:9px;background:rgba(255,255,255,.75)}.suggested-check b{color:#0f172a}.suggested-check p{margin:6px 0;color:#475569;font-size:13px;line-height:1.6}.suggested-check small{color:#94a3b8}.drawer-kpis{margin:14px 0}.continuity-summary{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:14px;padding:13px 15px;border:1px solid #dbeafe;border-radius:12px;background:#f8fbff}.continuity-summary h3{margin:0 0 5px;color:#0f172a;font-size:15px}.continuity-summary p{margin:0;color:#475569;font-size:12px}.continuity-semesters{display:flex;gap:8px}.continuity-semesters span{display:flex;flex-direction:column;gap:3px;padding:7px 9px;border-radius:8px;background:#fff;color:#64748b;font-size:10px}.continuity-semesters b{color:#334155;font-size:11px}.drawer-section{padding:15px;border:1px solid #e2e8f0;border-radius:12px;background:#fff}.history-collapse{margin-top:14px;padding:0 14px;border:1px solid #e2e8f0;border-radius:12px}.collapse-title{color:#334155;font-weight:600}.source-section{display:flex;flex-wrap:wrap;gap:8px 14px;margin-top:12px;padding:10px 13px;border-radius:9px;background:#f8fafc;color:#64748b;font-size:11px}.source-section b{color:#334155}.teacher-quality-alert{margin-top:10px}.teacher-profile-summary{margin:14px 0}.teacher-profile-kpis{margin-bottom:14px}.teacher-history{margin-top:14px}.evidence-detail>section{padding:14px 0;border-bottom:1px solid #eef2f7}.evidence-detail section div{display:flex;align-items:center;gap:8px}.evidence-detail section em{margin-left:auto;color:#64748b;font-style:normal}.evidence-detail section p{margin:7px 0 0;color:#64748b;font-size:12px;line-height:1.6}.definition-list h3{margin:0 0 10px;color:#0f172a;font-size:16px}.definition-list p b{color:#334155}@media(max-width:1350px){.overview-grid{grid-template-columns:1fr}.college-course-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-strip{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1050px){.kpi-filter-row{grid-template-columns:repeat(2,minmax(0,1fr))}.skeleton-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.college-course-grid{grid-template-columns:1fr}.review-verdict{grid-template-columns:1fr}.continuity-summary{align-items:flex-start;flex-direction:column}.queue-toolbar{grid-template-columns:1fr 1fr}.evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>

<style>
.faculty-nonblocking-overlay{pointer-events:none!important}.faculty-nonblocking-overlay .el-drawer{pointer-events:auto}
</style>
