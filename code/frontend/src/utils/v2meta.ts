import { getActiveIdentity, http } from '@/utils/http'

let teachingSemesterPromise: Promise<string> | null = null
let teachingSemesterIdentity = ''

/** 返回已接入真实教学任务的最新学期；没有数据时返回空字符串。 */
export function getV2TeachingSemester(): Promise<string> {
  const identity = getActiveIdentity()
  if (identity !== teachingSemesterIdentity) {
    teachingSemesterIdentity = identity
    teachingSemesterPromise = null
  }
  if (!teachingSemesterPromise) {
    teachingSemesterPromise = http.get<any>('/v2/meta/teaching-semesters')
      .then(data => data?.current || '')
      .catch(() => {
        teachingSemesterPromise = null
        return ''
      })
  }
  return teachingSemesterPromise
}
