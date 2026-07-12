import { http } from '@/utils/http'

let teachingSemesterPromise: Promise<string> | null = null

/** 返回已接入真实教学任务的最新学期；没有数据时返回空字符串。 */
export function getV2TeachingSemester(): Promise<string> {
  if (!teachingSemesterPromise) {
    teachingSemesterPromise = http.get<any>('/v2/meta/teaching-semesters')
      .then(data => data?.current || '')
      .catch(() => '')
  }
  return teachingSemesterPromise
}
