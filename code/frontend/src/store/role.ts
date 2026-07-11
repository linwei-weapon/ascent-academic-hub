import { reactive, computed } from 'vue'

/** 角色枚举 */
export type RoleType =
  | 'school_leader'      // 校领导
  | 'dean'               // 教务处处长
  | 'dept_operation'     // 教务处·运行科
  | 'dept_research'      // 教务处·教研科
  | 'dept_practice'      // 教务处·实践科
  | 'quality_office'     // 质量办/评估中心
  | 'college_dean'       // 二级学院·院长
  | 'college_secretary'  // 二级学院·教学秘书
  | 'counselor'          // 辅导员
  | 'dept_director'      // 系主任/教研室主任
  | 'teacher'            // 任课教师 [V1.1新增]

/** 角色中文名映射 */
export const ROLE_LABELS: Record<RoleType, string> = {
  school_leader:      '校领导',
  dean:               '教务处处长',
  dept_operation:     '教务处·运行科',
  dept_research:      '教务处·教研科',
  dept_practice:      '教务处·实践科',
  quality_office:     '质量办/评估中心',
  college_dean:       '二级学院·院长',
  college_secretary:  '二级学院·教学秘书',
  counselor:          '辅导员',
  dept_director:      '系主任',
  teacher:            '任课教师',
}

/** 角色分组（用于快捷切换） */
export const ROLE_GROUPS = {
  school: ['school_leader', 'dean', 'dept_operation', 'dept_research', 'dept_practice', 'quality_office'] as RoleType[],
  college: ['college_dean', 'college_secretary', 'counselor', 'dept_director'] as RoleType[],
}

/** 是否校级视角 */
export function isSchoolRole(r: RoleType): boolean { return ROLE_GROUPS.school.includes(r) }
/** 是否院级视角 */
export function isCollegeRole(r: RoleType): boolean { return ROLE_GROUPS.college.includes(r) }

interface RoleState {
  role: RoleType
  collegeId: string
  collegeName: string
  /** 辅导员专用：分管的年级/班级ID列表 */
  managedClassIds: string[]
  /** 系主任专用：所属专业ID */
  majorId: string
}

export const roleStore = reactive<RoleState>({
  role: 'dean',
  collegeId: 'C05',
  collegeName: '地球科学学院',
  managedClassIds: [],
  majorId: '',
})

/** 切换角色 */
export function switchRole(r: RoleType) {
  roleStore.role = r
}

/** 设置学院 */
export function setCollege(id: string, name: string) {
  roleStore.collegeId = id
  roleStore.collegeName = name
}

/** 设置辅导员分管班级 */
export function setManagedClasses(ids: string[]) {
  roleStore.managedClassIds = ids
}

/** 设置系主任所属专业 */
export function setMajorId(id: string) {
  roleStore.majorId = id
}
