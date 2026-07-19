<template>
  <div class="login-wrap">
    <!-- 左侧品牌展示区 -->
    <div class="login-hero">
      <div class="hero-bg-a"></div>
      <div class="hero-bg-b"></div>
      <div class="hero-inner">
        <div class="hero-logo">
          <span class="logo-mark">智</span>
          <span class="logo-text">智能学业分析平台</span>
        </div>
        <h1 class="hero-title">数据驱动的<br />高校学业洞察</h1>
        <p class="hero-desc">
          汇聚教务全量成绩、学籍与培养方案数据，<br />
          为校、院两级提供实时学业监测、预警与多维分析。
        </p>
        <ul class="hero-points">
          <li><i></i>学业预警 · 高危学生实时识别</li>
          <li><i></i>培养质量 · 多维下钻与趋势对比</li>
          <li><i></i>师资与教学运行全景看板</li>
        </ul>
      </div>
    </div>

    <!-- 右侧登录表单区 -->
    <div class="login-main">
      <div class="login-card">
        <div class="brand">智能学业分析平台</div>
        <div class="subtitle">高校教务学业数据分析平台</div>

        <el-form class="login-form" @submit.prevent="onSubmit">
          <el-form-item>
            <el-input
              v-model="form.username"
              size="large"
              placeholder="用户名"
              :prefix-icon="User"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="密码"
              :prefix-icon="Lock"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="onSubmit"
          >登 录</el-button>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { authStore, login } from '@/store/auth'
import { homePathForUser } from '@/utils/menu'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function onSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await login(form.username.trim(), form.password)
    ElMessage.success('登录成功')
    const redirect = (router.currentRoute.value.query.redirect as string)
      || homePathForUser(authStore.user, authStore.menus)
    router.replace(redirect)
  } catch {
    // 错误提示已在 http 层统一弹出
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  background: #f7f8fb;
}

/* ---------- 左侧品牌区 ---------- */
.login-hero {
  position: relative;
  flex: 1 1 56%;
  overflow: hidden;
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 45%, #3730a3 100%);
  color: #fff;
  display: flex;
  align-items: center;
}
.hero-bg-a,
.hero-bg-b {
  position: absolute;
  border-radius: 50%;
  filter: blur(8px);
  opacity: 0.5;
  pointer-events: none;
}
.hero-bg-a {
  width: 520px;
  height: 520px;
  top: -180px;
  right: -120px;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.55), transparent 70%);
}
.hero-bg-b {
  width: 460px;
  height: 460px;
  bottom: -160px;
  left: -100px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.45), transparent 70%);
}
.hero-inner {
  position: relative;
  z-index: 1;
  padding: 0 8% 0 9%;
  max-width: 620px;
}
.hero-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 48px;
}
.logo-mark {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 800;
}
.logo-text {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.hero-title {
  font-size: 40px;
  font-weight: 800;
  line-height: 1.25;
  margin: 0 0 20px;
  letter-spacing: -0.01em;
}
.hero-desc {
  font-size: 15px;
  line-height: 1.9;
  color: rgba(255, 255, 255, 0.82);
  margin: 0 0 36px;
}
.hero-points {
  list-style: none;
  padding: 0;
  margin: 0;
}
.hero-points li {
  display: flex;
  align-items: center;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.9);
  margin-bottom: 14px;
}
.hero-points li i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #a5b4fc;
  margin-right: 12px;
  box-shadow: 0 0 0 4px rgba(165, 180, 252, 0.25);
}

/* ---------- 右侧表单区 ---------- */
.login-main {
  position: relative;
  flex: 1 1 44%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  /* 淡灰点阵纹理 + 柔和高光，避免大面积留白 */
  background:
    radial-gradient(circle at center, #d3dae7 1.3px, transparent 1.6px) 0 0 / 20px 20px,
    linear-gradient(135deg, #f6f8fc 0%, #eef1f7 100%);
}
.login-main::before {
  content: '';
  position: absolute;
  inset: 0;
  /* 仅在卡片正后方柔化点阵，使表单区域更聚焦 */
  background: radial-gradient(48% 42% at 50% 50%, rgba(244,246,250,0.92) 0%, transparent 72%);
  pointer-events: none;
}
.login-main > * {
  position: relative;
  z-index: 1;
}
.login-card {
  width: 360px;
  max-width: 100%;
  background: #fff;
  border: 1px solid #e8eaf0;
  border-radius: 16px;
  padding: 40px 34px 34px;
  box-shadow: 0 16px 48px rgba(15, 23, 42, 0.08);
  animation: rise 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes rise {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
.brand {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  letter-spacing: -0.01em;
}
.subtitle {
  font-size: 12px;
  color: #94a3b8;
  margin: 8px 0 28px;
}
.login-form :deep(.el-input__wrapper) {
  border-radius: 10px;
}
.login-btn {
  width: 100%;
  margin-top: 6px;
  border-radius: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

/* ---------- 窄屏：隐藏品牌区 ---------- */
@media (max-width: 880px) {
  .login-hero { display: none; }
  .login-main { flex: 1 1 100%; }
}
</style>
