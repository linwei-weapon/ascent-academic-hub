<template>
  <!-- 明细清单页（新开浏览器标签页）：数据要素数字直达该数字代表的业务明细。
       与查证页分工：查证页回答"这个数字可信吗"，本页回答"这些人/这些事都是谁"。 -->
  <div class="detail-page">
    <header class="detail-top">
      <span class="brand">智能学业分析平台 · 明细清单</span>
      <span v-if="detail" class="meta">
        {{ detail.semester }} · 生成于 {{ detail.generated_at }}
      </span>
    </header>

    <main v-if="loading" class="state"><el-icon class="is-loading" :size="28"><Loading /></el-icon><p>正在载入明细…</p></main>

    <main v-else-if="error" class="state">
      <el-icon :size="28" color="#c45656"><CircleClose /></el-icon>
      <p class="err-title">{{ error }}</p>
      <p class="err-hint">信号可能已消除，或不在您当前工作身份的数据权限范围内。</p>
    </main>

    <main v-else-if="detail" class="body">
      <section class="card head-card">
        <div class="tags">
          <el-tag size="small" type="primary" effect="dark">{{ detail.fact }} {{ detail.fact_value }}</el-tag>
          <span class="from">来自专家：{{ detail.skill.skill_name }}</span>
        </div>
        <h1 class="title">{{ detail.title }}</h1>
        <p class="headline">{{ detail.headline }}</p>
      </section>

      <section class="card">
        <div class="table-head">
          <h2>明细清单（共 {{ detail.total }} 条）</h2>
          <el-button size="small" plain @click="goEvidence">
            查看信号查证页 ›
          </el-button>
        </div>
        <el-table :data="detail.rows" size="small" stripe max-height="640" class="rows">
          <el-table-column v-for="col in detail.columns" :key="col.key"
            :prop="col.key" :label="col.label" min-width="100" show-overflow-tooltip />
          <template #empty>该数据要素当前无明细记录</template>
        </el-table>
        <p v-if="detail.truncated" class="limit-note">
          仅展示前 {{ detail.rows.length }} 条（共 {{ detail.total }} 条）。完整清单请前往专题工作区核查。
        </p>
        <p v-if="detail.data_boundary" class="boundary">口径边界：{{ detail.data_boundary }}</p>
        <p class="note">本清单按您当前工作身份的数据权限生成，与信号判断同源；平台不执行任何办理操作。</p>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loading, CircleClose } from '@element-plus/icons-vue'
import { getSignalDetail } from '@/utils/decision'
import type { SignalDetail } from '@/types/decision'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const detail = ref<SignalDetail | null>(null)

function goEvidence() {
  router.push(`/admin/verify/signal/${encodeURIComponent(String(route.params.signalId || ''))}`)
}

onMounted(async () => {
  const signalId = String(route.params.signalId || '')
  const fact = String(route.query.fact || '')
  document.title = '明细清单'
  try {
    const res = await getSignalDetail(signalId, fact)
    detail.value = (res as any)?.data ?? res
    document.title = `明细清单 · ${detail.value?.title || fact}`
  } catch (e: any) {
    error.value = e?.msg || e?.message || '明细载入失败'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.detail-page { min-height: 100vh; background: #f3f5f9; }
.detail-top { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 12px 24px; background: #1f2d3d; color: #fff; }
.brand { font-size: 14px; font-weight: 600; }
.detail-top .meta { font-size: 12px; color: #b8c2cc; }
.state { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 120px 20px; color: #606266; }
.err-title { font-size: 15px; font-weight: 600; color: #303133; margin: 0; }
.err-hint { font-size: 13px; color: #909399; margin: 0; }
.body { max-width: 960px; margin: 0 auto; padding: 20px 20px 48px; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 16px 18px; }
.card h2 { margin: 0; font-size: 14px; color: #303133; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px; }
.from { font-size: 12px; color: #909399; margin-left: 4px; }
.title { margin: 0 0 6px; font-size: 17px; color: #1f2d3d; }
.headline { margin: 0; font-size: 13px; color: #606266; line-height: 1.6; }
.table-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.rows { width: 100%; }
.limit-note { margin: 10px 0 0; font-size: 12px; color: #b45309; background: #fdf6ec;
  border-radius: 6px; padding: 8px 10px; }
.boundary { margin: 10px 0 0; font-size: 12px; color: #b45309; background: #fdf6ec;
  border-radius: 6px; padding: 8px 10px; line-height: 1.6; }
.note { margin: 10px 0 0; font-size: 12px; color: #909399; }
</style>
