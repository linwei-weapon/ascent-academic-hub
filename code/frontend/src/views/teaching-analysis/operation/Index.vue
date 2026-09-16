<!-- 教学运行分析：Index 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
      </div>
      <div v-if="activeTab !== 'course-quality'" class="period-control">
        <span>统计学期</span>
        <el-select v-model="sharedSemester" style="width:190px" placeholder="选择统计学期">
          <el-option v-for="item in semesters" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
    </div>
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
import * as operationApi from '@/api/teachingAnalysis/operation'

import { provide, ref, reactive, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Courses from './Courses.vue'
import Classroom from './Classroom.vue'
import ScheduleChanges from './ScheduleChanges.vue'
import TeacherLoad from './TeacherLoad.vue'
import ScheduleAnalysis from './ScheduleAnalysis.vue'
import CourseQuality from './CourseQuality.vue'
import { getFilterMeta, type SemesterOpt } from '@/api/shared/filterMeta'
import { useBusinessPageTitle } from '@/utils/businessPage'


const router = useRouter()
const route = useRoute()
const pageTitle = useBusinessPageTitle('/admin/operation/courses', '教学运行分析')
const sharedSemester = ref('')
const semesters = ref<SemesterOpt[]>([])
const dataContext = ref<any>(null)
provide('operationSemester', sharedSemester)
provide('operationDataContext', dataContext)
// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
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
const loaded = reactive<Record<string, boolean>>({
  courses: activeTab.value === 'courses',
  classroom: activeTab.value === 'classroom',
  'schedule-changes': activeTab.value === 'schedule-changes',
  'teacher-load': activeTab.value === 'teacher-load',
  'schedule-analysis': activeTab.value === 'schedule-analysis',
  'course-quality': activeTab.value === 'course-quality',
})

// 记录已加载的专题并同步原路由，切换时保留共享学期。
function onTabClick(tab: any) {
  const name = tab.paneName as string
  loaded[name] = true
  const path = `/admin/operation/${name}`
  if (route.path !== path) {
    router.replace({ path, query:route.query })
  }
}

// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
watch(() => route.path, (path) => {
  const tab = PATH_TO_TAB[path]
  if (tab && tab !== activeTab.value) {
    activeTab.value = tab
    loaded[tab] = true
  }
})

async function loadDataContext() {
  try {
    dataContext.value = await operationApi.getOperationContext<any>()
  } catch {
    dataContext.value = null
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

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
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

.embedded-topic {
  :deep(.crumb), :deep(.sa-page-title), :deep(.sa-page-sub), :deep(.el-breadcrumb) {
    display: none;
  }
}
</style>
