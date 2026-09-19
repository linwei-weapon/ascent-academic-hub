<!-- 师资保障分析：Index 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div class="faculty-page">
    <div class="head">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p v-if="pageSubtitle" class="sa-page-sub">{{ pageSubtitle }}</p>
      </div>
      <el-select v-model="semester" class="semester" placeholder="选择学期" @change="changeSemester">
        <el-option v-for="s in semesters" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
    </div>

    <el-skeleton v-if="pageLoading && !hasData" :rows="9" animated class="page-skeleton">
      <template #template>
        <div class="skeleton-kpis">
          <el-skeleton-item v-for="i in 5" :key="i" variant="rect" class="skeleton-kpi" />
        </div>
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
      <div class="management-kpi-row" :class="{ 'is-refreshing': refreshing }">
        <KpiCard
          v-for="item in data.kpis || []"
          :key="item.key"
          :label="item.label"
          :value="item.value"
          :sub="item.sub"
          :hint="item.hint"
          :tone="item.tone"
          interactive
          action-text="查看下钻"
          @drilldown="openKpiDrilldown(item.key)"
        />
      </div>

      <div v-if="isSchoolScope" class="overview-grid">
        <section class="sa-card college-card" v-loading="refreshing">
          <div class="section-head">
            <div>
              <h3>学院授课师资保障概览</h3>
            </div>
            <el-input v-model="collegeKeyword" clearable placeholder="搜索学院" class="college-search" />
          </div>
          <AppTable
            :columns="collegeColumns"
            :data="filteredColleges"
            storage-key="faculty:college-assurance"
            :max-business-columns="6"
            config-version="3"
            stripe

            row-class-name="college-row"
            @row-click="openCollegeQueue"
            @cell-mouse-enter="schedulePrefetch"
            @cell-mouse-leave="cancelPrefetch" :show-density="true" :show-column-settings="true" :pagination="false">
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
          </AppTable>
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
          <AppTable
            v-else
            v-loading="drawerLoading"
            :columns="courseQueueColumns"
            :data="queueRows"
            storage-key="faculty:course-review-queue"
            :max-business-columns="7"
            config-version="2"

            stripe

            empty-text="当前条件下没有课程"

            @row-click="row => openCourse(row)" :show-density="true" :show-column-settings="true" :pagination="true" :page="queuePage" :page-size="queuePageSize" :total="queueTotal" @page-change="queuePage = $event; loadQueue(true)" @page-size-change="changeQueuePageSize" :page-sizes="[10, 20, 50, 100]" :loading="drawerLoading">
            <template #col-course_name="{ row }">
              <span class="course-link">{{ row.course_name }}</span>
              <small class="course-code">{{ row.course_id }}</small>
            </template>
            <template #col-review_type="{ row }">
              <div class="review-type-list">
                <el-tag
                  v-for="type in courseReviewTypes(row)"
                  :key="type.key"
                  :type="reviewTagType(type.key)"
                  effect="plain"
                >
                  {{ type.label }}
                </el-tag>
              </div>
            </template>
            <template #col-attention_reasons="{ row }">
              <div class="reason-list">
                <span v-for="reason in courseAttentionReasons(row)" :key="reason">{{ reason }}</span>
              </div>
            </template>
            <template #col-actions="{ row }">
              <el-button link type="primary" @click.stop="openCourse(row)">详情</el-button>
            </template>
          </AppTable>
          <div v-if="queueTotal" class="queue-pagination">
            <span>共 {{ queueTotal }} 门课程</span>

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
              </div>
            </section>

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
                <div><h3>当前实际授课团队</h3></div>
              </div>
              <AppTable
                :columns="teamColumns"
                :data="courseDetail.members"
                storage-key="faculty:course-team"
                :max-business-columns="6"
                config-version="2"
                stripe :show-density="true" :show-column-settings="true" :pagination="false">
                <template #col-display_name="{ row }"><b>{{ row.display_name }}</b></template>
                <template #col-title="{ row }">{{ row.title || '待补充' }}</template>
                <template #col-organization_id="{ row }">{{ row.organization_id || '待映射' }}</template>
                <template #col-actions="{ row }">
                  <el-button link type="primary" @click="openTeacher(row)">教学经历</el-button>
                </template>
              </AppTable>
            </section>

            <el-collapse class="history-collapse">
              <el-collapse-item name="history">
                <template #title>
                  <span class="collapse-title">查看全部历史开课记录（{{ courseDetail.offerings.length }}个学期）</span>
                </template>
                <AppTable
                  :columns="offeringColumns"

                  storage-key="faculty:course-offerings"
                  :max-business-columns="6"
                  config-version="2"


                  stripe :show-density="true" :show-column-settings="true" :data="offeringPagination.rows" :pagination="true" :page="offeringPagination.page" :page-size="offeringPagination.pageSize" :total="offeringPagination.total" @page-change="offeringPagination.changePage" @page-size-change="offeringPagination.changePageSize"/>
              </el-collapse-item>
            </el-collapse>

          </template>
        </template>
      </div>
    </el-drawer>

    <el-drawer
      v-model="teacherDrawer.visible"
      :title="`${teacherDrawer.data.name || '教师'} · 教学经历`"
      size="760px"
      append-to-body
      :modal="false"
      modal-class="faculty-nonblocking-overlay"
      @closed="closeTeacherDrawer"
    >
      <div v-loading="teacherDrawer.loading" class="teacher-drawer">
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
          <el-descriptions-item label="部门" :span="2">{{ teacherDrawer.data.deptName || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="sa-kpi-row teacher-profile-kpis">
          <KpiCard v-for="k in teacherDrawer.data.kpis || []" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" tone="primary" />
        </div>
        <section class="drawer-section">
          <div class="section-head"><div><h3>本学期教学任务</h3></div></div>
          <AppTable
            :columns="teacherCurrentColumns"

            storage-key="faculty:teacher-current-courses"
            :max-business-columns="6"
            config-version="2"


            stripe

            empty-text="当前学期暂无教学任务" :show-density="true" :show-column-settings="true" :data="currentCoursesPagination.rows" :pagination="true" :page="currentCoursesPagination.page" :page-size="currentCoursesPagination.pageSize" :total="currentCoursesPagination.total" @page-change="currentCoursesPagination.changePage" @page-size-change="currentCoursesPagination.changePageSize"/>
        </section>
        <section class="drawer-section teacher-history">
          <div class="section-head"><div><h3>近年授课经历</h3></div></div>
          <AppTable
            :columns="teacherHistoryColumns"

            storage-key="faculty:teacher-history"
            :max-business-columns="6"
            config-version="2"


            stripe

            empty-text="暂无历史记录" :show-density="true" :show-column-settings="true" :data="historyPagination.rows" :pagination="true" :page="historyPagination.page" :page-size="historyPagination.pageSize" :total="historyPagination.total" @page-change="historyPagination.changePage" @page-size-change="historyPagination.changePageSize"/>
        </section>
      </div>
    </el-drawer>

    <FacultyKpiDrilldown
      :model-value="kpiDrawer.visible"
      :metric-key="kpiDrawer.metricKey"
      :semester="semester"
      :college-id="isSchoolScope ? undefined : data.college_id"
      @update:model-value="setKpiDrawerVisible"
      @open-course="openCourseFromKpi"
      @open-teacher="openTeacherFromKpi"
    />
  </div>
</template>

<script setup lang="ts">
import { useTablePagination } from '@/composables/useTablePagination'
import * as facultyApi from '@/api/teachingAnalysis/faculty'

import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getFilterMeta, type SemesterOpt } from '@/api/shared/filterMeta'
import KpiCard from '@/components/KpiCard.vue'
import AppTable from '@/components/AppTable.vue'
import FacultyKpiDrilldown from './FacultyKpiDrilldown.vue'
import type { AppTableColumn } from '@/types/table'
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
const collegeKeyword = ref('')
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
  kpis: [],
})
const kpiDrawer = reactive({ visible: false, metricKey: '' })
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
  ? ''
  : `聚焦${data.college || '本学院'}责任课程，明确先核实哪门课、为什么以及缺少什么证据。`)
// 由 CSS 随视口实时计算，窗口缩放时仍保持屏幕的 2/3 宽度。
const drawerWidth = 'calc(100vw * 2 / 3)'
const drawerTitle = computed(() => drawerMode.value === 'course'
  ? `${selectedCourse.value?.name || '课程'}详情`
  : `${selectedCollege.value?.name || (isSchoolScope.value ? '全校' : data.college || '本学院')} · 课程师资情况`)
const focusCourses = computed(() => {
  const rows = data.risk_courses || []
  return rows.filter((row: any) => isSchoolScope.value
    ? row.review_type === 'priority_review'
    : row.review_type !== 'general_observation'
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

const reviewTypeMeta = {
  priority_review: { label: '优先核查', tagType: 'danger' },
  continuous_single: { label: '连续单点', tagType: 'primary' },
  structure_review: { label: '结构核查', tagType: 'warning' },
  data_candidate: { label: '数据候选', tagType: 'info' },
  general_observation: { label: '一般观察', tagType: 'success' },
} as const
type ReviewTypeKey = keyof typeof reviewTypeMeta

const reviewTypeOptions = Object.entries(reviewTypeMeta).map(([value, meta]) => ({
  value,
  label: meta.label,
}))
const reviewTagType = (value: string) =>
  reviewTypeMeta[value as ReviewTypeKey]?.tagType || 'success'

const courseReviewTypes = (row: any) => {
  const types: ReviewTypeKey[] = []
  if (row.review_type === 'priority_review') {
    types.push('priority_review')
  }
  if (row.continuous_single_review) {
    types.push('continuous_single')
  }
  if (row.structure_review) {
    types.push('structure_review')
  }
  if (row.review_type === 'data_candidate') {
    types.push('data_candidate')
  }
  const matchedTypes = types.length ? types : ['general_observation' as const]
  return matchedTypes.map(key => ({ key, label: reviewTypeMeta[key].label }))
}

const courseAttentionReasons = (row: any): string[] =>
  row.attention_reasons?.length ? row.attention_reasons : ['一般观察']

const collegeColumns: AppTableColumn[] = [
  { key: 'college_name', label: '学院', minWidth: 180, fixed: 'left', required: true, region: 'identity' },
  { key: 'course_total', label: '课程总数', minWidth: 95, align: 'center', required: true, region: 'business' },
  { key: 'evaluable_courses', label: '可评估课程', minWidth: 105, align: 'center', required: true, region: 'business' },
  { key: 'priority_review_courses', label: '优先核查', minWidth: 100, align: 'center', required: true, region: 'business' },
  { key: 'continuous_single_courses', label: '连续单点', minWidth: 95, align: 'center', region: 'business' },
  { key: 'structure_review_courses', label: '结构核查', minWidth: 95, align: 'center', region: 'business' },
  { key: 'data_candidate_courses', label: '数据候选', minWidth: 95, align: 'center', region: 'business' },
  { key: 'review_rate', label: '优先核查率', minWidth: 105, align: 'center', region: 'business', defaultVisible: false },
  { key: 'lessons', label: '教学班', minWidth: 85, align: 'center', region: 'business', defaultVisible: false },
  { key: 'enrolled', label: '学生人次', minWidth: 95, align: 'center', region: 'business', defaultVisible: false },
  { key: 'actions', label: '操作', width: 95, fixed: 'right', required: true, region: 'action' },
]
// 抽屉内的数据列以较小 minWidth 作为相对权重随容器分配；标签、操作保留完整展示所需宽度。
const courseQueueColumns: AppTableColumn[] = [
  { key: 'course_name', label: '课程', minWidth: 19, fixed: 'left', required: true, region: 'identity' },
  { key: 'course_nature', label: '性质', minWidth: 8, region: 'business' },
  { key: 'review_type', label: '核查类型', minWidth: 18, required: true, region: 'business' },
  { key: 'lesson_count', label: '教学班', minWidth: 8, align: 'center', region: 'business' },
  { key: 'enrolled', label: '学生人次', minWidth: 9, align: 'center', required: true, region: 'business' },
  { key: 'teacher_count', label: '教师', minWidth: 7, align: 'center', region: 'business' },
  { key: 'attention_reasons', label: '核查原因', minWidth: 32, required: true, region: 'business' },
  { key: 'college_name', label: '责任学院', minWidth: 16, defaultVisible: false, region: 'business' },
  { key: 'continuity_observations', label: '历史观察次数', minWidth: 11, align: 'center', defaultVisible: false, region: 'business' },
  { key: 'title_completeness_rate', label: '职称证据率', minWidth: 11, align: 'center', defaultVisible: false, region: 'business', formatter: row => `${row.title_completeness_rate}%` },
  { key: 'actions', label: '操作', width: 95, fixed: 'right', required: true, region: 'action' },
]
const teamColumns: AppTableColumn[] = [
  { key: 'display_name', label: '教师', minWidth: 11, fixed: 'left', required: true, region: 'identity' },
  { key: 'team_role', label: '团队角色', minWidth: 10, required: true, region: 'business' },
  { key: 'lesson_count', label: '教学班', minWidth: 8, align: 'center', required: true, region: 'business' },
  { key: 'enrolled', label: '学生人次', minWidth: 10, align: 'center', required: true, region: 'business' },
  { key: 'lesson_share', label: '教学班占比', minWidth: 11, align: 'center', region: 'business', formatter: row => `${row.lesson_share}%` },
  { key: 'title', label: '职称', minWidth: 11, region: 'business' },
  { key: 'organization_id', label: '部门', minWidth: 16, region: 'business' },
  { key: 'staff_id', label: '教师代码', minWidth: 13, defaultVisible: false, region: 'business' },
  { key: 'actions', label: '操作', width: 95, fixed: 'right', required: true, region: 'action' },
]
const offeringColumns: AppTableColumn[] = [
  { key: 'semesterId', label: '学期', minWidth: 13, fixed: 'left', required: true, region: 'identity' },
  { key: 'lessonCount', label: '教学班', minWidth: 9, align: 'center', required: true, region: 'business' },
  { key: 'teacherCount', label: '教师', minWidth: 8, align: 'center', required: true, region: 'business' },
  { key: 'enrolled', label: '学生人次', minWidth: 10, align: 'center', region: 'business' },
  { key: 'capacity', label: '容量', minWidth: 9, align: 'center', region: 'business' },
  { key: 'avgClassSize', label: '平均班额', minWidth: 10, align: 'center', region: 'business' },
]
const teacherCurrentColumns: AppTableColumn[] = [
  { key: 'courseName', label: '课程', minWidth: 160, fixed: 'left', required: true, region: 'identity' },
  { key: 'teamRole', label: '角色', minWidth: 90, required: true, region: 'business' },
  { key: 'className', label: '教学班', minWidth: 160, region: 'business' },
  { key: 'students', label: '学生数', minWidth: 85, align: 'center', required: true, region: 'business' },
  { key: 'hours', label: '学时', minWidth: 75, align: 'center', region: 'business' },
  { key: 'courseDept', label: '课程责任学院', minWidth: 160, defaultVisible: false, region: 'business' },
]
const teacherHistoryColumns: AppTableColumn[] = [
  { key: 'semester', label: '学期', minWidth: 125, fixed: 'left', required: true, region: 'identity' },
  { key: 'courseName', label: '课程', minWidth: 170, required: true, region: 'business' },
  { key: 'teamRole', label: '角色', minWidth: 90, region: 'business' },
  { key: 'lessonCount', label: '教学班', minWidth: 85, align: 'center', region: 'business' },
  { key: 'students', label: '学生人次', minWidth: 100, align: 'center', region: 'business' },
  { key: 'hours', label: '学时', minWidth: 75, align: 'center', region: 'business' },
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
    const result = await facultyApi.getFacultyOverview<any>(semester.value)
    Object.assign(data, result)
  } catch (error: any) {
    pageError.value = error?.message || '请求失败'
  } finally {
    pageLoading.value = false
    refreshing.value = false
  }
}

const kpiKeys = new Set([
  'teaching_staff_coverage',
  'team_structure_exception',
  'continuous_single_teacher',
  'senior_title_teaching_rate',
  'young_teacher_teaching_rate',
])

function openKpiDrilldown(metricKey: string) {
  if (!kpiKeys.has(metricKey)) return
  kpiDrawer.metricKey = metricKey
  kpiDrawer.visible = true
  drawerVisible.value = false
  void syncUrl({
    drill: metricKey,
    college: undefined,
    course: undefined,
    teacher: undefined,
    teacherCourse: undefined,
    review: undefined,
  })
}

function setKpiDrawerVisible(visible: boolean) {
  kpiDrawer.visible = visible
  if (!visible) void syncUrl({ drill: undefined })
}

function openCourseFromKpi(row: any) {
  kpiDrawer.visible = false
  void openCourse(row, true)
}

function openTeacherFromKpi(row: any) {
  kpiDrawer.visible = false
  void openTeacher(row)
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
  return facultyApi.getFacultyCourses<any>(query)
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
  queueReviewType.value = ''
  courseDetail.value = null
  await syncUrl({ college: row.college_id, course: undefined, teacher: undefined, teacherCourse: undefined })
  await loadQueue()
}

async function openAllCourses() {
  selectedCollege.value = isSchoolScope.value
    ? null
    : { id: data.college_id, name: data.college }
  drawerMode.value = 'queue'
  drawerVisible.value = true
  queuePage.value = 1
  queueReviewType.value = ''
  courseDetail.value = null
  await syncUrl({ college: selectedCollege.value?.id, course: undefined, teacher: undefined, teacherCourse: undefined })
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

// 打开当前课程的既有详情入口，不改变课程标识和统计范围。
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
    teacherCourse: undefined,
    drill: undefined,
  })
  if (courseCache.has(key)) {
    courseDetail.value = courseCache.get(key)
    return
  }
  courseDetail.value = null
  drawerLoading.value = true
  try {
    const result = await facultyApi.getFacultyCourse<any>(row.course_id, semester.value)
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
  await syncUrl({ course: undefined, teacher: undefined, teacherCourse: undefined })
  if (!queueRows.value.length) await loadQueue()
}

function afterDrawerClosed() {
  drawerMode.value = 'queue'
  selectedCourse.value = null
  courseDetail.value = null
  selectedCollege.value = null
  drawerError.value = ''
  void syncUrl({ college: undefined, course: undefined, teacher: undefined, teacherCourse: undefined })
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
  const courseContextId = row.evidence_course_id || row.course_id || selectedCourse.value?.id || ''
  teacherDrawer.visible = true
  teacherDrawer.loading = true
  teacherDrawer.data = {
    name: row.display_name,
    kpis: [],
    currentCourses: [],
    teachingHistory: [],
  }
  await syncUrl({ teacher: teacherId, teacherCourse: courseContextId || undefined, drill: undefined })
  try {
    const query = new URLSearchParams({ semester: semester.value })
    if (courseContextId) query.set('course_id', courseContextId)
    teacherDrawer.data = await facultyApi.getFacultyTeacher(teacherId, query)
  } catch (error: any) {
    ElMessage.error(error?.message || '教师教学经历加载失败')
  } finally {
    teacherDrawer.loading = false
  }
}

function closeTeacherDrawer() {
  void syncUrl({ teacher: undefined, teacherCourse: undefined })
}

// 按原学期切换顺序清理并重新加载关联数据。
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
  const teacherCourseId = String(route.query.teacherCourse || '')
  const drill = String(route.query.drill || '')
  if (route.query.review) await syncUrl({ review: undefined })
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
    await openTeacher({
      staff_id: teacherId,
      display_name: teacherId,
      evidence_course_id: teacherCourseId || undefined,
    })
  }
  if (!collegeId && !courseId && !teacherId && kpiKeys.has(drill)) {
    kpiDrawer.metricKey = drill
    kpiDrawer.visible = true
  }
}

// 进入页面时执行原初始化流程，恢复路由条件与可用选项。
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
// 离开页面时清理原定时器或监听，保留组件的资源释放流程。
onBeforeUnmount(cancelPrefetch)

// 全量结果在页面分页；不改变查询、汇总和证据数据。
const offeringPagination = useTablePagination(() => courseDetail.value?.offerings || [], 10)

// 全量结果在页面分页；不改变查询、汇总和证据数据。
const currentCoursesPagination = useTablePagination(() => teacherDrawer.data.currentCourses || [], 10)

// 全量结果在页面分页；不改变查询、汇总和证据数据。
const historyPagination = useTablePagination(() => teacherDrawer.data.teachingHistory || [], 10)
</script>

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
}

.semester {
  width: 190px;
}

.page-skeleton {
  margin-top: 16px;
}

.skeleton-kpis {
  display: grid;
  grid-template-columns: repeat(5,minmax(0,1fr));
  gap: 12px;
}

.skeleton-kpi {
  height: 112px;
  border-radius: 14px;
}

.skeleton-table {
  height: 420px;
  margin-top: 14px;
  border-radius: 14px;
}

.management-kpi-row {
  display: grid;
  grid-template-columns: repeat(5,minmax(0,1fr));
  gap: 12px;
  margin: 14px 0;
  transition: opacity .2s;
  :deep(.sa-kpi) {
    height: 100%;
  }
  &.is-refreshing {
    opacity: .72;
  }
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  h3 {
    margin: 0 0 5px;
    color: #0f172a;
    font-size: 16px;
  }
  p {
    margin: 0;
    color: #64748b;
    font-size: 12px;
    line-height: 1.5;
  }
}


.overview-grid {
  display: grid;
  grid-template-columns: minmax(0,2.1fr) minmax(320px,.9fr);
  gap: 14px;
  align-items: start;
}

.college-search {
  width: 190px;
}

:deep(.college-row) {
  cursor: pointer;
}

:deep(.college-row:hover .college-link) {
  text-decoration: underline;
}

.college-link,.course-link {
  color: #4338ca;
  font-weight: 600;
}

.focus-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.focus-item {
  display: grid;
  grid-template-columns: minmax(0,1fr) auto;
  gap: 5px 10px;
  width: 100%;
  padding: 11px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  &:hover {
    border-color: #a5b4fc;
    background: #f8faff;
  }
}

.focus-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  b {
    overflow: hidden;
    color: #0f172a;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.focus-main small,.focus-reason {
  color: #64748b;
  font-size: 11px;
}

.focus-reason {
  grid-column: 1/3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.college-workbench {
  min-height: 320px;
}

.college-course-grid {
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  gap: 10px;
}

.college-course {
  display: grid;
  grid-template-columns: minmax(0,1fr) auto;
  gap: 7px 10px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  &:hover {
    border-color: #a5b4fc;
    background: #f8faff;
  }
  span {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 4px;
  }
  b {
    overflow: hidden;
    color: #0f172a;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  small, p {
    color: #64748b;
    font-size: 11px;
  }
  p {
    grid-column: 1/3;
    margin: 0;
    line-height: 1.6;
  }
  em {
    grid-column: 1/3;
    color: #4f46e5;
    font-size: 12px;
    font-style: normal;
  }
}

.inline-error {
  margin-top: 12px;
}

.drawer-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  h2 {
    margin: 0;
    color: #0f172a;
    font-size: 20px;
  }
}

.drawer-body {
  min-height: 560px;
}

.queue-toolbar {
  display: grid;
  grid-template-columns: 180px minmax(220px,360px) auto auto;
  gap: 10px;
  margin-bottom: 13px;
}

.drawer-skeleton {
  position: relative;
  padding: 18px;
  p {
    text-align: center;
    color: #64748b;
    font-size: 12px;
  }
}

.course-code {
  display: block;
  margin-top: 3px;
  color: #94a3b8;
}

.review-type-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.reason-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  line-height: 1.5;
}

.queue-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  color: #64748b;
  font-size: 12px;
}

.review-verdict {
  display: grid;
  grid-template-columns: minmax(0,1.5fr) minmax(280px,.7fr);
  gap: 18px;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid #fecdd3;
  border-left: 5px solid #e11d48;
  border-radius: 12px;
  background: #fff7f8;
  &.structure_review {
    border-color: #fde68a;
    border-left-color: #d97706;
    background: #fffbeb;
  }
  &.data_candidate {
    border-color: #cbd5e1;
    border-left-color: #64748b;
    background: #f8fafc;
  }
  h3 {
    margin: 9px 0 6px;
    color: #0f172a;
    font-size: 17px;
  }
  ul {
    margin: 0;
    padding-left: 20px;
    color: #475569;
    font-size: 13px;
    line-height: 1.7;
  }
}

.suggested-check {
  padding: 12px;
  border-radius: 9px;
  background: rgba(255,255,255,.75);
  b {
    color: #0f172a;
  }
  p {
    margin: 6px 0;
    color: #475569;
    font-size: 13px;
    line-height: 1.6;
  }
}

.drawer-kpis {
  margin: 14px 0;
}

.continuity-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 14px;
  padding: 13px 15px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: #f8fbff;
  h3 {
    margin: 0 0 5px;
    color: #0f172a;
    font-size: 15px;
  }
  p {
    margin: 0;
    color: #475569;
    font-size: 12px;
  }
}

.continuity-semesters {
  display: flex;
  gap: 8px;
  span {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 7px 9px;
    border-radius: 8px;
    background: #fff;
    color: #64748b;
    font-size: 10px;
  }
  b {
    color: #334155;
    font-size: 11px;
  }
}

.drawer-section {
  padding: 15px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}

.history-collapse {
  margin-top: 14px;
  padding: 0 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.collapse-title {
  color: #334155;
  font-weight: 600;
}

.teacher-quality-alert {
  margin-top: 10px;
}

.teacher-profile-summary {
  margin: 14px 0;
}

.teacher-profile-kpis {
  margin-bottom: 14px;
}

.teacher-history {
  margin-top: 14px;
}

@media (max-width:1350px) {
  .management-kpi-row {
    grid-template-columns: repeat(3,minmax(0,1fr));
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .college-course-grid {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }

}

@media (max-width:1050px) {
  .management-kpi-row {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }

  .skeleton-kpis {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }

  .college-course-grid {
    grid-template-columns: 1fr;
  }

  .review-verdict {
    grid-template-columns: 1fr;
  }

  .continuity-summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .queue-toolbar {
    grid-template-columns: 1fr 1fr;
  }

}
</style>

<style lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.faculty-nonblocking-overlay {
  pointer-events: none !important;
  .el-drawer {
    pointer-events: auto;
  }
}
</style>
