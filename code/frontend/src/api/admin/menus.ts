// 菜单管理接口：只封装原有请求，不解释或修正后台业务数据。
import { http } from '@/utils/http'

// 读取完整菜单目录，供页面组装树和父级选项。
export function listMenus<T = any>(): Promise<T> {
  return http.get<T>('/admin/rbac/menus')
}

// 提交菜单编辑字段，保留原路径及父级字段约定。
export function updateMenu<T = any>(menuId: string | number, body: unknown): Promise<T> {
  return http.put<T>(`/admin/rbac/menus/${encodeURIComponent(menuId)}`, body)
}

// 提交新菜单字段，菜单保存不直接授予角色权限。
export function createMenu<T = any>(body: unknown): Promise<T> {
  return http.post<T>('/admin/rbac/menus', body)
}

// 删除用户已确认的菜单，关联关系由原接口校验。
export function deleteMenu<T = any>(menuId: string | number): Promise<T> {
  return http.del<T>(`/admin/rbac/menus/${encodeURIComponent(menuId)}`)
}
