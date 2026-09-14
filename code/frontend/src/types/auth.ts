/** 现有认证接口 DTO，保留后端字段与可选性。 */
export interface AuthMenu {
  menu_id: string
  title: string
  path: string
  icon?: string | null
  sort_order?: number
  parent_id?: string | null
}

export interface AuthUser {
  username: string
  name: string
  role: string
  roleName: string
  activeIdentityId?: string
  identities?: Array<{
    identityId: string
    roleId: string
    roleName: string
    isDefault: boolean
    validFrom?: string | null
    validTo?: string | null
    source?: string | null
  }>
  permissionContext?: {
    userId: string
    username: string
    staffId?: string | null
    activeIdentityId: string
    activeRole: string
    activeRoleName: string
    authorized: boolean
    authorizationIssue?: string | null
    menuPermissions: string[]
    actionPermissions: string[]
    detailScope: Record<string, unknown>
    comparisonScope: Record<string, unknown>
    fieldPolicy: Record<string, unknown>
    scopeFingerprint: string
  }
  scope?: { collegeId?: string; collegeName?: string; majorId?: string; classIds?: string[] }
}

export type AuthProfile = AuthUser & { menus: AuthMenu[] }

export interface LoginResponse {
  token: string
  user: AuthProfile
}
