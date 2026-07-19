<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">数据来源：教务系统教学任务与排课数据</p>
      </div>
      <el-select v-model="sharedSemester" style="width:190px" placeholder="选择统一统计学期">
        <el-option v-for="item in semesters" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
    </div>
    <BusinessPageContext
      source="教务系统教学任务、排课与教室实际占用数据"
      :period="sharedPeriod"
    />

    <el-tabs v-model="activeTab" @tab-click="onTabClick">
      <el-tab-pane label="课程总览" name="courses">
        <Courses v-if="loaded.courses" :key="`courses-${contentKey}`" />
      </el-tab-pane>
      <el-tab-pane label="教室利用率" name="classroom">
        <Classroom v-if="loaded.classroom" :key="`classroom-${contentKey}`" />
      </el-tab-pane>
      <el-tab-pane label="调课记录" name="schedule-changes">
        <ScheduleChanges v-if="loaded['schedule-changes']" :key="`schedule-changes-${contentKey}`" />
      </el-tab-pane>
      <el-tab-pane label="教师负荷" name="teacher-load">
        <TeacherLoad v-if="loaded['teacher-load']" :key="`teacher-load-${contentKey}`" />
      </el-tab-pane>
      <el-tab-pane label="课程排课分析" name="schedule-analysis">
        <ScheduleAnalysis v-if="loaded['schedule-analysis']" :key="`schedule-analysis-${contentKey}`" />
      </el-tab-pane>
      <el-tab-pane label="课程质量核查" name="course-quality">
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

const router = useRouter()
const route = useRoute()
const pageTitle = useBusinessPageTitle('/admin/operation/courses', '教学运行分析')
const sharedSemester = ref('')
const semesters = ref<SemesterOpt[]>([])
const contentKey = ref(0)
const sharedPeriod = computed(() => {
  const item = semesters.value.find(option => option.value === sharedSemester.value)
  return item ? `统一统计学期：${item.label}` : ''
})
provide('operationSemester', sharedSemester)
watch(sharedSemester, (value, oldValue) => {
  if (oldValue && value !== oldValue) contentKey.value += 1
  if (value && route.query.semester !== value) {
    router.replace({ path:route.path, query:{ ...route.query, semester:value } })
  }
})

const TAB_NAMES = ['courses', 'classroom', 'schedule-changes', 'teacher-load', 'schedule-analysis', 'course-quality'] as const
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
.embedded-topic :deep(.crumb),
.embedded-topic :deep(.sa-page-title),
.embedded-topic :deep(.sa-page-sub),
.embedded-topic :deep(.el-breadcrumb) {
  display: none;
}
</style>
