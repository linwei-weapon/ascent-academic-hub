// 基础报表路由：九张报表共用页面，保留原 URL 与授权菜单路径。
import type { RouteRecordRaw } from 'vue-router'

export const basicReportRoutes: RouteRecordRaw[] = [
  // 基础报表
  {
    path: 'basic-reports',
    redirect: '/admin/dashboard',
    children: [
      // 年级总体挂科情况
      { path: 'failure-overview', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 各专业补考前后挂科率比较
      { path: 'major-makeup-comparison', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 各专业整体与男女挂科率比较
      { path: 'major-gender-failure', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 各班级挂科门数具体情况
      { path: 'class-failure-count', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 各班级成绩分布
      { path: 'class-score-distribution', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 补考前后课程通过情况对比
      { path: 'course-makeup-comparison', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 各班大学英语四级通过情况
      { path: 'cet4-pass', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 重点关注学生名单
      { path: 'focus-students', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
      // 校级学业警示学生名单
      { path: 'academic-warning-roster', component: () => import('@/views/basic-reports/components/BasicReportPage.vue') },
    ],
  },
]
