<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">教学运行分析</h2>
        <p class="sa-page-sub">数据来源：教务系统教学任务与排课数据</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" @tab-click="onTabClick">
      <el-tab-pane label="课程总览" name="courses">
        <Courses v-if="loaded.courses" />
      </el-tab-pane>
      <el-tab-pane label="教室利用率" name="classroom">
        <Classroom v-if="loaded.classroom" />
      </el-tab-pane>
      <el-tab-pane label="调课记录" name="schedule-changes">
        <ScheduleChanges v-if="loaded['schedule-changes']" />
      </el-tab-pane>
      <el-tab-pane label="教师负荷" name="teacher-load">
        <TeacherLoad v-if="loaded['teacher-load']" />
      </el-tab-pane>
      <el-tab-pane label="课程排课分析" name="schedule-analysis">
        <ScheduleAnalysis v-if="loaded['schedule-analysis']" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Courses from './Courses.vue'
import Classroom from './Classroom.vue'
import ScheduleChanges from './ScheduleChanges.vue'
import TeacherLoad from './TeacherLoad.vue'
import ScheduleAnalysis from './ScheduleAnalysis.vue'

const router = useRouter()
const route = useRoute()

const TAB_NAMES = ['courses', 'classroom', 'schedule-changes', 'teacher-load', 'schedule-analysis'] as const
const PATH_TO_TAB: Record<string, string> = {
  '/admin/operation/courses': 'courses',
  '/admin/operation/classroom': 'classroom',
  '/admin/operation/schedule-changes': 'schedule-changes',
  '/admin/operation/teacher-load': 'teacher-load',
  '/admin/operation/schedule-analysis': 'schedule-analysis',
}

const activeTab = ref(PATH_TO_TAB[route.path] || 'courses')
const loaded = reactive<Record<string, boolean>>({
  courses: activeTab.value === 'courses',
  classroom: activeTab.value === 'classroom',
  'schedule-changes': activeTab.value === 'schedule-changes',
  'teacher-load': activeTab.value === 'teacher-load',
  'schedule-analysis': activeTab.value === 'schedule-analysis',
})

function onTabClick(tab: any) {
  const name = tab.paneName as string
  loaded[name] = true
  const path = `/admin/operation/${name}`
  if (route.path !== path) {
    router.replace(path)
  }
}

watch(() => route.path, (path) => {
  const tab = PATH_TO_TAB[path]
  if (tab && tab !== activeTab.value) {
    activeTab.value = tab
    loaded[tab] = true
  }
})
</script>

<style scoped>
.sa-head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}
</style>
