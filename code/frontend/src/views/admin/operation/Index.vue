<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">数据来源：教务系统教学任务与排课数据</p>
      </div>
      <div v-if="activeTab !== 'course-quality'" class="period-control">
        <span>统计学期</span>
        <el-select v-model="sharedSemester" style="width:190px" placeholder="选择统计学期">
          <el-option v-for="item in semesters" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
      <el-tag v-else type="info" effect="plain">课程结果使用独立多学期窗口</el-tag>
    </div>
    <BusinessPageContext
      source="教务系统教学任务、排课与教室实际占用数据"
      :period="sharedPeriod"
    />
    <div v-if="contextLoading" class="context-loading">
      <el-skeleton animated :rows="1" />
      <span>正在核对当前身份可见的数据域与统计周期…</span>
    </div>
    <el-alert v-else-if="contextError" type="error" :closable="false" show-icon
      title="教学运行数据范围核对失败" :description="contextError" class="context-alert">
      <template #default><el-button link type="primary" @click="loadDataContext">重新核对</el-button></template>
    </el-alert>
    <el-alert v-else-if="activeDomainContext" :type="activeDomainContext.available ? 'info' : 'warning'"
      :closable="false" show-icon class="context-alert"
      :title="activeDomainContext.available ? activeDomainTitle : '当前工作区暂无可用数据'"
      :description="activeDomainDescription" />

    <el-tabs v-model="activeTab" @tab-click="onTabClick">
      <el-tab-pane label="开课供给" name="courses">
        <Courses v-if="loaded.courses" />
      </el-tab-pane>
      <el-tab-pane label="排课结构" name="schedule-analysis">
        <ScheduleAnalysis v-if="loaded['schedule-analysis']" />
      </el-tab-pane>
      <el-tab-pane label="教室占用" name="classroom">
        <Classroom v-if="loaded.classroom" />
      </el-tab-pane>
      <el-tab-pane label="教师负荷" name="teacher-load">
        <TeacherLoad v-if="loaded['teacher-load']" />
      </el-tab-pane>
      <el-tab-pane label="调停课分析" name="schedule-changes">
        <ScheduleChanges v-if="loaded['schedule-changes']" />
      </el-tab-pane>
      <el-tab-pane label="课程结果" name="course-quality">
        <div v-if="loaded['course-quality']" class="embedded-topic"><CourseQuality /></div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, provide, ref, reactive, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Courses from './Courses.vue'
import Classroom from './Classroom.vue'
import ScheduleChanges from './ScheduleChanges.vue'
import TeacherLoad from './TeacherLoad.vue'
import ScheduleAnalysis from './ScheduleAnalysis.vue'
import CourseQuality from '../reports/CourseQuality.vue'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import { getFilterMeta, type SemesterOpt } from '@/utils/meta'
import { useBusinessPageTitle } from '@/utils/businessPage'
import { http } from '@/utils/http'

const router = useRouter()
const route = useRoute()
const pageTitle = useBusinessPageTitle('/admin/operation/courses', '教学运行分析')
const sharedSemester = ref('')
const semesters = ref<SemesterOpt[]>([])
const dataContext = ref<any>(null)
const contextLoading = ref(true)
const contextError = ref('')
const sharedPeriod = computed(() => {
  if (activeTab.value === 'course-quality') {
    const domain = dataContext.value?.domains?.courseResults
    return domain?.available
      ? `独立观察窗口：${domain.periodFrom} 至 ${domain.periodTo}`
      : '独立多学期观察窗口'
  }
  const item = semesters.value.find(option => option.value === sharedSemester.value)
  return item ? `页面统计学期：${item.label}` : ''
})
provide('operationSemester', sharedSemester)
provide('operationDataContext', dataContext)
watch(sharedSemester, (value) => {
  if (value && route.query.semester !== value) {
    router.replace({ path:route.path, query:{ ...route.query, semester:value } })
  }
})

const PATH_TO_TAB: Record<string, string> = {
  '/admin/operation/courses': 'courses',
  '/admin/operation/classroom': 'classroom',
  '/admin/operation/schedule-changes': 'schedule-changes',
  '/admin/operation/teacher-load': 'teacher-load',
  '/admin/operation/schedule-analysis': 'schedule-analysis',
  '/admin/operation/course-quality': 'course-quality',
}

const activeTab = ref(PATH_TO_TAB[route.path] || 'courses')
const TAB_DOMAIN: Record<string, string> = {
  courses: 'courseSupply',
  classroom: 'classroomOccupancy',
  'schedule-changes': 'scheduleChanges',
  'teacher-load': 'teacherLoad',
  'schedule-analysis': 'scheduleStructure',
  'course-quality': 'courseResults',
}
const activeDomainContext = computed(() =>
  dataContext.value?.domains?.[TAB_DOMAIN[activeTab.value]] || null)
const activeDomainTitle = computed(() => {
  const item = activeDomainContext.value
  if (!item) return ''
  if (item.timeControl === 'independent_period_window') {
    return `当前结果观察窗口：${item.periodFrom || '—'} 至 ${item.periodTo || '—'}`
  }
  return `当前数据覆盖：${item.periodFrom || '—'} 至 ${item.periodTo || '—'}`
})
const activeDomainDescription = computed(() => {
  const item = activeDomainContext.value
  if (!item?.available) return '当前身份在该数据域没有已接入记录；这不等同于业务指标为0。'
  const count = item.periodCount ? `，共${item.periodCount}个学期` : ''
  return `来源：${item.source}；范围口径：${item.scopeBasis}${count}；证据级别：${item.evidenceLevel}。`
})
const loaded = reactive<Record<string, boolean>>({
  courses: activeTab.value === 'courses',
  classroom: activeTab.value === 'classroom',
  'schedule-changes': activeTab.value === 'schedule-changes',
  'teacher-load': activeTab.value === 'teacher-load',
  'schedule-analysis': activeTab.value === 'schedule-analysis',
  'course-quality': activeTab.value === 'course-quality',
})

function onTabClick(tab: any) {
  const name = tab.paneName as string
  loaded[name] = true
  const path = `/admin/operation/${name}`
  if (route.path !== path) {
    router.replace({ path, query:route.query })
  }
}

watch(() => route.path, (path) => {
  const tab = PATH_TO_TAB[path]
  if (tab && tab !== activeTab.value) {
    activeTab.value = tab
    loaded[tab] = true
  }
})

async function loadDataContext() {
  contextLoading.value = true
  contextError.value = ''
  try {
    dataContext.value = await http.get<any>('/admin/operation/data-context')
  } catch (error:any) {
    dataContext.value = null
    contextError.value = error?.message || '无法确认当前身份的数据范围，请稍后重试。'
  } finally {
    contextLoading.value = false
  }
}

loadDataContext()
getFilterMeta().then(meta => {
  semesters.value = meta.semesters.slice().reverse()
  const requested = String(route.query.semester || '')
  sharedSemester.value = semesters.value.some(item => item.value === requested)
    ? requested : (meta.current || semesters.value[0]?.value || '')
})
</script>

<style scoped>
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}
.period-control {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 13px;
}
.embedded-topic :deep(.crumb),
.embedded-topic :deep(.sa-page-title),
.embedded-topic :deep(.sa-page-sub),
.embedded-topic :deep(.el-breadcrumb) {
  display: none;
}
.context-alert {
  margin: 10px 0 12px;
}
.context-loading {
  position: relative;
  margin: 10px 0 12px;
  padding: 12px 14px;
  border: 1px solid var(--sa-border);
  border-radius: 8px;
  background: #fff;
}
.context-loading :deep(.el-skeleton__item) {
  height: 18px;
}
.context-loading span {
  position: absolute;
  left: 18px;
  top: 12px;
  font-size: 12px;
  color: #64748b;
}
</style>
