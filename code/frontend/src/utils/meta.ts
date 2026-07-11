/**
 * 维度筛选元数据：拉取 /api/admin/meta/filters（学期/年级/校区/学院/课程性质/职称/预警枚举），
 * 进程内缓存一次。各分析页下拉从此动态加载，避免硬编码、随 ETL 自动更新。
 */
export interface SemesterOpt { value: string; label: string; current: boolean }
export interface MajorOpt { value: string; label: string; college: string }
export interface ClassOpt { value: string; label: string; major: string; grade: string }
export interface FilterMeta {
  current: string
  semesters: SemesterOpt[]
  grades: string[]
  campuses: string[]
  colleges: { value: string; label: string }[]
  courseNature: string[]
  titles: string[]
  majors: MajorOpt[]
  classes: ClassOpt[]
  categories: string[]
  roomTypes: string[]
  buildings: string[]
  years: string[]
  attritionKinds: string[]
  sizeBuckets: string[]
  alert: { level: string[]; type: string[]; status: string[] }
  retake: string[]
}

let _cache: FilterMeta | null = null
let _inflight: Promise<FilterMeta> | null = null

export async function getFilterMeta(): Promise<FilterMeta> {
  if (_cache) return _cache
  if (_inflight) return _inflight
  const token = localStorage.getItem('bi_token') || ''
  _inflight = fetch('/api/admin/meta/filters', {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  })
    .then(r => r.json())
    .then(d => {
      _cache = d.data as FilterMeta
      _inflight = null
      return _cache
    })
    .catch(e => {
      _inflight = null
      throw e
    })
  return _inflight
}
