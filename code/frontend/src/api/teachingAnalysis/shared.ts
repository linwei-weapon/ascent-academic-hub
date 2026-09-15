// 原页面 URL 插值接受的值；不改变既有字符串拼接与参数序列化。
export type UrlValue = string | number | boolean | string[] | URLSearchParams | null | undefined

// 仅在参数非空时加问号，与预警查询和 CSV 导出的原规则一致。
export function withQuery(path: string, params: URLSearchParams): string {
  const suffix = params.toString()
  return `${path}${suffix ? `?${suffix}` : ''}`
}
