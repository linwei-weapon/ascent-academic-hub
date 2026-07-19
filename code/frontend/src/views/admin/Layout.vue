<template>
  <el-container class="admin-layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">智能学业分析平台</div>
      <el-menu
        :key="menuRenderKey"
        :default-active="activeMenu"
        :default-openeds="openMenus"
        :unique-opened="true"
        @select="navigateMenu"
        class="sa-menu"
        background-color="transparent"
        text-color="#475569"
        active-text-color="#4F46E5"
      >
        <template v-for="m in menuTree" :key="m.menu_id">
          <!-- 有子菜单的父级 -->
          <el-sub-menu v-if="m.children && m.children.length" :index="m.menu_id">
            <template #title><span>{{ m.title }}</span></template>
            <el-menu-item v-for="c in m.children" :key="c.menu_id" :index="c.path">
              <span>{{ c.title }}</span>
            </el-menu-item>
          </el-sub-menu>
          <!-- 无子菜单的叶子节点 -->
          <el-menu-item v-else :index="m.path">
            <span>{{ m.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div class="topbar-right">
          <span class="user-name">{{ authStore.user?.name || authStore.user?.username }}</span>
          <el-select
            v-if="identityOptions.length > 1"
            class="identity-select"
            size="small"
            :model-value="authStore.user?.activeIdentityId"
            :loading="switchingIdentity"
            @change="onIdentityChange"
          >
            <el-option
              v-for="identity in identityOptions"
              :key="identity.identityId"
              :label="identity.roleName"
              :value="identity.identityId"
            />
          </el-select>
          <el-tag v-else size="small" effect="plain" type="primary">
            {{ authStore.user?.roleName }}
          </el-tag>
          <el-tooltip :content="scopeDescription" placement="bottom">
            <el-tag size="small" effect="plain" type="info">{{ scopeLabel }}</el-tag>
          </el-tooltip>
          <el-popconfirm title="确定退出登录？" @confirm="onLogout">
            <template #reference>
              <el-button size="small" text :icon="SwitchButton">登出</el-button>
            </template>
          </el-popconfirm>
        </div>
      </el-header>
      <el-main>
        <router-view :key="refreshKey" />
        <div class="data-source-footer">
          数据来源：教务系统 · 本系统仅做数据展示，不做数据干预
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { SwitchButton } from '@element-plus/icons-vue'
import {
  authStore, visibleMenus, logout, switchIdentity, type AuthMenu,
} from '@/store/auth'
import { menuKeyOfPath } from '@/utils/menu'

const route = useRoute()
const router = useRouter()

// 菜单树：按 parent_id 分组
interface MenuNode extends AuthMenu {
  children?: MenuNode[]
}
const menuTree = computed<MenuNode[]>(() => {
  const all = visibleMenus.value as AuthMenu[]
  return all
    .filter(m => !m.parent_id)
    .map(m => ({
      ...m,
      children: all
        .filter(c => c.parent_id === m.menu_id)
        .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)),
    }))
    .filter(m => m.children.length)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
})

const activeMenu = computed(() => {
  return menuKeyOfPath(route.path, String(route.query.returnTo || ''))
})
const activeParent = computed(() => (
  menuTree.value.find(parent => parent.children?.some(
    child => child.path === activeMenu.value,
  ))?.menu_id || ''
))
const openMenus = computed(() => activeParent.value ? [activeParent.value] : [])
const menuRenderKey = computed(() => (
  `${authStore.user?.username || 'guest'}:${authStore.user?.role || ''}:${activeParent.value}`
))
const refreshKey = ref(0)
const switchingIdentity = ref(false)
const identityOptions = computed(() => authStore.user?.identities || [])
const scopeLabel = computed(() => {
  const detail = authStore.user?.permissionContext?.detailScope as any
  const type = detail?.type
  if (type === 'all') return '全校数据'
  const ids = detail?.sourceScopeIds || []
  if (type === 'college') return authStore.user?.scope?.collegeName || '本学院'
  if (type === 'major') return '本专业'
  if (type === 'class') return `${ids.length}个行政班`
  if (type === 'staff_relation') return '所带学生'
  if (type === 'teacher') return '所授学生'
  return '范围待核验'
})
const scopeDescription = computed(() => {
  const permission = authStore.user?.permissionContext
  if (!permission?.authorized) return permission?.authorizationIssue || '当前身份没有有效范围'
  return `当前工作身份：${permission.activeRoleName}；明细范围：${scopeLabel.value}`
})

function onLogout() {
  logout()
}
async function onIdentityChange(identityId: string) {
  if (!identityId || identityId === authStore.user?.activeIdentityId) return
  switchingIdentity.value = true
  try {
    await switchIdentity(identityId)
    const home = authStore.menus.find(menu => menu.parent_id)?.path
    if (home) await router.replace(home)
    refreshKey.value += 1
  } finally {
    switchingIdentity.value = false
  }
}
function navigateMenu(path: string) {
  if (path && path !== route.path) void router.push(path)
}
</script>

<style scoped>
.admin-layout { height: 100vh; }

/* Style A：浅色边栏 + 细描边 */
.sidebar {
  background: #fff;
  border-right: 1px solid var(--sa-border);
  overflow-y: auto;
}
.logo {
  font-family: var(--sa-font-head);
  color: var(--sa-text);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  padding: 18px 18px 10px;
}
.view-badge {
  display: none;
}
.topbar {
  background: #fff;
  border-bottom: 1px solid var(--sa-border);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 24px;
  height: 52px;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--sa-text);
}
.identity-select { width: 150px; }
.el-main {
  background: var(--sa-bg);
}
.data-source-footer {
  margin-top: 24px; padding-top: 12px; border-top: 1px solid var(--sa-border);
  font-size: 10px; color: var(--sa-faint); text-align: center;
}

/* 菜单项做成 Style A 胶囊 */
.sa-menu { border-right: none; padding: 4px 0; }
.sa-menu :deep(.el-menu-item) {
  height: 42px;
  line-height: 42px;
  margin: 2px 10px;
  padding: 0 12px !important;
  border-radius: 8px;
  font-size: 13.5px;
}
.sa-menu :deep(.el-menu-item:hover) {
  background: #f1f5f9;
}
.sa-menu :deep(.el-menu-item.is-active) {
  background: #eef2ff;
  color: var(--sa-primary);
  font-weight: 600;
}
.sa-menu :deep(.el-sub-menu__title) {
  height: 44px;
  line-height: 44px;
  margin: 3px 8px;
  padding: 0 12px !important;
  border-radius: 8px;
  color: var(--sa-text);
  font-size: 13.5px;
  font-weight: 650;
}
.sa-menu :deep(.el-sub-menu__title:hover) {
  background: #f8fafc;
}
.sa-menu :deep(.el-sub-menu .el-menu-item) {
  margin-left: 18px;
  font-size: 13px;
}
</style>
