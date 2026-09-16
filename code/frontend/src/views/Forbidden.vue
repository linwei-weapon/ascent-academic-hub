<template>
  <section class="forbidden-page">
    <div class="forbidden-card">
      <div class="status-code">403</div>
      <h2>当前工作身份无权访问此页面</h2>
      <p>
        系统已阻止本次访问，没有扩大您的菜单或数据范围。
        如需办理其他职责，请切换到已获授权的工作身份。
      </p>
      <div v-if="requestedPath" class="requested-path">
        请求路径：<code>{{ requestedPath }}</code>
      </div>
      <el-button type="primary" @click="goHome">返回当前身份首页</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authStore } from '@/store/auth'
import { homePathForUser } from '@/utils/menu'

const route = useRoute()
const router = useRouter()
const requestedPath = computed(() => String(route.query.from || ''))

function goHome() {
  void router.replace(homePathForUser(authStore.user, authStore.menus))
}
</script>

<style scoped>
.forbidden-page {
  min-height: calc(100vh - 128px);
  display: grid;
  place-items: center;
  padding: 24px;
}
.forbidden-card {
  width: min(560px, 100%);
  padding: 40px;
  text-align: center;
  background: #fff;
  border: 1px solid var(--sa-border);
  border-radius: 14px;
  box-shadow: 0 12px 36px rgb(15 23 42 / 6%);
}
.status-code {
  color: #c2410c;
  font-size: 54px;
  font-weight: 750;
  letter-spacing: 2px;
}
h2 {
  margin: 6px 0 12px;
  color: var(--sa-text);
  font-size: 22px;
}
p {
  margin: 0 auto 18px;
  color: var(--sa-muted);
  line-height: 1.8;
}
.requested-path {
  margin-bottom: 22px;
  padding: 9px 12px;
  color: #64748b;
  font-size: 12px;
  background: #f8fafc;
  border-radius: 8px;
  overflow-wrap: anywhere;
}
code {
  color: #334155;
}
</style>
