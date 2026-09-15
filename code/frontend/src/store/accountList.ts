/** 账号到数据权限的单次返回现场；仅存查询状态，不持久化账号数据，也不写页面 URL。 */
export interface AccountListFilters {
  keyword: string
  accountSource: string
  roleId: string
  authStatus: string
  permissionStatus: string
  status: string
}

export interface AccountListReturnState {
  page: number
  pageSize: number
  filters: AccountListFilters
  draft: AccountListFilters
  activeCard: string
}

let pendingReturn: { contextKey: string; state: AccountListReturnState } | null = null

/** 只在主动进入数据权限时保存，普通列表离开或刷新不产生持久化分页。 */
export function rememberAccountListReturn(contextKey: string, state: AccountListReturnState): void {
  pendingReturn = {
    contextKey,
    state: { ...state, filters: { ...state.filters }, draft: { ...state.draft } },
  }
}

/** 返回时消费一次；用户或工作身份不同则丢弃，不串用其他身份的筛选现场。 */
export function takeAccountListReturn(contextKey: string): AccountListReturnState | null {
  const saved = pendingReturn
  pendingReturn = null
  return saved?.contextKey === contextKey ? saved.state : null
}
