// 教学管理分析路由：由 index.ts 统一注册，沿用原 URL、组件复用与兼容跳转。
import type { RouteRecordRaw } from 'vue-router'

export const teachingAnalysisRoutes: RouteRecordRaw[] = [
  // ====== 数据大屏（五级） ======
  // 教学数据总览
  { path: 'dashboard', component: () => import('@/views/teaching-analysis/dashboard/index.vue') },
  // 学院详情
  { path: 'college/:id', component: () => import('@/views/teaching-analysis/dashboard/Detail.vue') },
  // 专业详情
  { path: 'major/:id', component: () => import('@/views/teaching-analysis/dashboard/MajorDetail.vue') },
  // 课程详情
  { path: 'course/:id', component: () => import('@/views/teaching-analysis/dashboard/CourseDetail.vue') },
  // 课程学生清单
  { path: 'course/:id/students', component: () => import('@/views/teaching-analysis/students/List.vue'), meta: { courseProfile: true } },
  // 学生详情（多模块共享入口）
  { path: 'student/:id', component: () => import('@/views/teaching-analysis/students/Detail.vue') },

  // ====== 预警查看 ======
  // 学业预警工作区
  { path: 'alert', component: () => import('@/views/teaching-analysis/alert/Workspace.vue') },
  // 旧预警监控入口
  { path: 'alert/monitor', redirect: '/admin/alert?tab=monitor' },
  // 旧规则入口
  { path: 'alert/rules', redirect: '/admin/alert?tab=rules' },
  // 旧规则发现入口
  { path: 'alert/discovery', redirect: '/admin/alert?tab=rules' },

  // ====== 教学运行分析 ======
  // 教学运行：开课供给
  { path: 'operation/courses', component: () => import('@/views/teaching-analysis/operation/Index.vue') },
  // 教学运行：教室占用
  { path: 'operation/classroom', component: () => import('@/views/teaching-analysis/operation/Index.vue') },
  // 教学运行：调停课分析
  { path: 'operation/schedule-changes', component: () => import('@/views/teaching-analysis/operation/Index.vue') },
  // 教学运行：教师负荷
  { path: 'operation/teacher-load', component: () => import('@/views/teaching-analysis/operation/Index.vue') },
  // 教学运行：排课结构
  { path: 'operation/schedule-analysis', component: () => import('@/views/teaching-analysis/operation/Index.vue') },
  // 教学运行：课程结果
  { path: 'operation/course-quality', component: () => import('@/views/teaching-analysis/operation/Index.vue') },

  // ====== 培养质量分析 ======
  // 培养质量工作区
  { path: 'curriculum', component: () => import('@/views/teaching-analysis/curriculum/index.vue') },
  // 旧方案进度入口
  { path: 'curriculum/progress', redirect: '/admin/curriculum?tab=progress' },
  // 旧课程目标入口
  { path: 'curriculum/course-objectives/:id', redirect: '/admin/curriculum' },
  // 旧毕业要求入口
  { path: 'curriculum/graduate-requirements/:id', redirect: '/admin/curriculum' },

  // ====== 师资保障分析（旧团队/教师链接统一恢复为主页面抽屉） ======
  // 师资保障工作区
  { path: 'faculty', component: () => import('@/views/teaching-analysis/faculty/Index.vue') },
  // 旧课程团队链接
  { path: 'faculty/team', redirect: to => ({
    path: '/admin/faculty',
    query: {
      semester: to.query.semester,
      course: to.query.courseId,
      courseName: to.query.courseName,
    },
  }) },
  // 旧教师详情链接
  { path: 'faculty/:id', redirect: to => ({
    path: '/admin/faculty',
    query: {
      semester: to.query.semester,
      teacher: String(to.params.id),
    },
  }) },

  // ====== 学生成长与学业分析（同一路由按当前工作身份加载对应工作区） ======
  // 按工作身份显示学生分析
  { path: 'students/analysis', component: () => import('@/views/teaching-analysis/students/Workspace.vue') },
  // 旧「我的班级/学生」地址仅保留书签兼容，不再作为独立产品入口。
  // 旧负责学生入口
  { path: 'students/my', redirect: to => ({
    path: '/admin/students/analysis',
    query: to.query,
    hash: to.hash,
  }) },
  // 学生清单
  { path: 'students/list', component: () => import('@/views/teaching-analysis/students/List.vue') },

  // 历史事实专题入口
  // 旧低年级观察专题
  { path: 'reports/early-setback', redirect: '/admin/alert?tab=early-risk' },
  // 旧毕业准备专题
  { path: 'reports/graduation-readiness', redirect: '/admin/curriculum?tab=graduation-readiness' },
  // 旧课程质量专题
  { path: 'reports/course-quality', redirect: '/admin/operation/course-quality' },
  // 旧师资专题
  { path: 'reports/faculty-resource-risk', redirect: '/admin/faculty' },
  // 旧排课专题
  { path: 'reports/schedule-strategy', redirect: '/admin/operation/schedule-analysis' },
]
