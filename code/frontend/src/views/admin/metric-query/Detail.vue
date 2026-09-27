<template>
  <div class="metric-detail-page">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="backToList">← 返回指标查询</el-button>
        <h2 class="sa-page-title">指标详情</h2>
        <p class="sa-page-sub">集中核查指标口径、上下游引用关系、使用位置和适用规则。</p>
      </div>
      <el-tag v-if="detail.metric.id" effect="plain">{{ detail.metric.id }}</el-tag>
    </div>

    <el-alert
      v-if="loadError"
      :title="loadError"
      type="error"
      :closable="false"
      show-icon
    >
      <template #default><el-button size="small" @click="loadDetail">重新加载</el-button></template>
    </el-alert>

    <template v-if="loading">
      <div class="sa-card loading-card"><el-skeleton :rows="12" animated /></div>
    </template>
    <template v-else-if="!loadError">
      <section class="sa-card section-card basic-card">
        <div class="section-head">
          <div><h3>指标基本信息</h3><p>指标定义及其当前关系数量。</p></div>
        </div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="指标名称">{{ detail.metric.name }}</el-descriptions-item>
          <el-descriptions-item label="标签分类">
            <div v-if="detail.metric.tags.length" class="tag-list">
              <el-tag v-for="tag in detail.metric.tags" :key="tag.id || tag.label" size="small" effect="plain">
                {{ tag.label }}
              </el-tag>
            </div>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="指标详细说明" :span="2">
            <div class="definition-content">{{ detail.metric.description }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="计算公式" :span="2">
            <div class="formula definition-content">{{ detail.metric.formula }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="使用模块/功能点" :span="2">
            <el-tooltip :content="detail.metric.usageText" placement="top" :disabled="detail.metric.usageText === '—'">
              <span class="overflow-text">{{ detail.metric.usageText }}</span>
            </el-tooltip>
          </el-descriptions-item>
          <el-descriptions-item label="引用指标数">{{ countText(detail.metric.referencedMetricCount) }}</el-descriptions-item>
          <el-descriptions-item label="被引用指标数">{{ countText(detail.metric.dependentMetricCount) }}</el-descriptions-item>
          <el-descriptions-item label="被使用模块功能点数">{{ countText(detail.metric.usagePointCount) }}</el-descriptions-item>
        </el-descriptions>
      </section>

      <section class="sa-card section-card">
        <div class="section-head">
          <div><h3>被引用指标清单</h3><p>直接使用当前指标作为计算输入的下游指标。</p></div>
          <span>{{ detail.dependents.length }} 项</span>
        </div>
        <AppTable
          :columns="relationColumns"
          :data="detail.dependents"
          storage-key="system:metric-query:dependents"
          :pagination="false"
          empty-text="暂无被引用指标"
        >
          <template #col-tags="{ row }"><MetricTags :tags="row.tags" /></template>
          <template #col-usageText="{ row }"><UsageTooltip :text="row.usageText" /></template>
          <template #col-referencedMetricCount="{ row }">{{ countText(row.referencedMetricCount) }}</template>
          <template #col-dependentMetricCount="{ row }">{{ countText(row.dependentMetricCount) }}</template>
          <template #col-usagePointCount="{ row }">{{ countText(row.usagePointCount) }}</template>
          <template #col-action="{ row }"><el-button link type="primary" @click="openMetric(row.id)">详细</el-button></template>
        </AppTable>
      </section>

      <section class="sa-card section-card">
        <div class="section-head">
          <div><h3>引用指标清单</h3><p>当前指标计算时直接引用的上游指标。</p></div>
          <span>{{ detail.dependencies.length }} 项</span>
        </div>
        <AppTable
          :columns="relationColumns"
          :data="detail.dependencies"
          storage-key="system:metric-query:dependencies"
          :pagination="false"
          empty-text="暂无引用指标"
        >
          <template #col-tags="{ row }"><MetricTags :tags="row.tags" /></template>
          <template #col-usageText="{ row }"><UsageTooltip :text="row.usageText" /></template>
          <template #col-referencedMetricCount="{ row }">{{ countText(row.referencedMetricCount) }}</template>
          <template #col-dependentMetricCount="{ row }">{{ countText(row.dependentMetricCount) }}</template>
          <template #col-usagePointCount="{ row }">{{ countText(row.usagePointCount) }}</template>
          <template #col-action="{ row }"><el-button link type="primary" @click="openMetric(row.id)">详细</el-button></template>
        </AppTable>
      </section>

      <section class="sa-card section-card">
        <div class="section-head">
          <div><h3>指标使用模块/功能点清单</h3><p>定位指标在页面、卡片、图表或列表中的实际使用位置。</p></div>
          <span>{{ detail.usages.length }} 项</span>
        </div>
        <AppTable
          :columns="usageColumns"
          :data="detail.usages"
          storage-key="system:metric-query:usages"
          :pagination="false"
          empty-text="暂无已登记的使用模块/功能点"
        />
      </section>

      <section class="sa-card section-card">
        <div class="section-head">
          <div><h3>核验问题</h3><p>代码、文档、页面显示或数据边界之间尚待统一的事项。</p></div>
          <span>{{ detail.issues.length }} 项</span>
        </div>
        <AppTable
          :columns="issueColumns"
          :data="detail.issues"
          storage-key="system:metric-query:issues"
          :pagination="false"
          empty-text="暂无已登记核验问题"
        />
      </section>

      <section class="sa-card section-card">
        <div class="section-head">
          <div><h3>规则信息</h3><p>展示与该指标关联的计算、触发或预警规则；本页面只读。</p></div>
          <span>{{ detail.rules.length }} 项</span>
        </div>
        <AppTable
          :columns="ruleColumns"
          :data="detail.rules"
          storage-key="system:metric-query:rules"
          :pagination="false"
          empty-text="暂无已登记规则"
        />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, ref, watch, type PropType } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElTag, ElTooltip } from 'element-plus'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import * as kpisApi from '@/api/admin/kpis'
import {
  countText,
  normalizeMetricDetail,
  type MetricDetailModel,
  type SelectNode,
} from './model'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const metricId = computed(() => String(route.params.id || ''))
const detail = ref<MetricDetailModel>(normalizeMetricDetail({ metric: { id: metricId.value } }))

const MetricTags = defineComponent({
  props: { tags: { type: Array as PropType<SelectNode[]>, default: () => [] } },
  setup(props) {
    return () => props.tags.length
      ? h('div', { class: 'tag-list' }, props.tags.map(tag => h(ElTag, { key: tag.id || tag.label, size: 'small', effect: 'plain' }, () => tag.label)))
      : h('span', { class: 'sa-faint' }, '—')
  },
})

const UsageTooltip = defineComponent({
  props: { text: { type: String, default: '—' } },
  setup(props) {
    return () => h(ElTooltip, { content: props.text, placement: 'top', disabled: props.text === '—' }, {
      default: () => h('span', { class: 'overflow-text' }, props.text),
    })
  },
})

const relationColumns: AppTableColumn[] = [
  { key: 'name', label: '指标名称', required: true, region: 'identity', fixed: 'left', minWidth: 180 },
  { key: 'description', label: '指标详细说明', minWidth: 240, align: 'left', tooltip: true },
  { key: 'formula', label: '计算公式', minWidth: 240, align: 'left', tooltip: true },
  { key: 'tags', label: '标签分类', minWidth: 170, align: 'left' },
  { key: 'usageText', label: '使用模块/功能点', minWidth: 240, align: 'left' },
  { key: 'referencedMetricCount', label: '引用指标数', minWidth: 120 },
  { key: 'dependentMetricCount', label: '被引用指标数', minWidth: 130 },
  { key: 'usagePointCount', label: '被使用模块功能点数', minWidth: 170 },
  { key: 'action', label: '操作', required: true, region: 'action', fixed: 'right', width: 90 },
]

const usageColumns: AppTableColumn[] = [
  { key: 'level1', label: '一级模块', required: true, region: 'identity', fixed: 'left', minWidth: 160, tooltip: true },
  { key: 'level2', label: '二级模块', minWidth: 180, tooltip: true },
  { key: 'level3', label: '三级模块', minWidth: 180, tooltip: true },
  { key: 'functionPoint', label: '功能点', minWidth: 220, tooltip: true },
  { key: 'description', label: '功能点说明', minWidth: 300, align: 'left', tooltip: true },
]

const ruleColumns: AppTableColumn[] = [
  { key: 'name', label: '规则名称', required: true, region: 'identity', fixed: 'left', minWidth: 180 },
  { key: 'type', label: '规则类型', minWidth: 120 },
  { key: 'condition', label: '触发/计算条件', minWidth: 280, align: 'left', tooltip: true },
  { key: 'warningLevel', label: '预警级别', minWidth: 120 },
  { key: 'version', label: '版本', minWidth: 100 },
  { key: 'status', label: '状态', minWidth: 100 },
  { key: 'description', label: '规则说明', minWidth: 260, align: 'left', tooltip: true },
]

const issueColumns: AppTableColumn[] = [
  { key: 'type', label: '问题类型', required: true, region: 'identity', fixed: 'left', minWidth: 190 },
  { key: 'severity', label: '级别', minWidth: 100 },
  { key: 'status', label: '状态', minWidth: 100 },
  { key: 'description', label: '问题说明', minWidth: 360, align: 'left', tooltip: true },
  { key: 'sourceRef', label: '核验来源', minWidth: 300, align: 'left', tooltip: true },
]

async function loadDetail(): Promise<void> {
  if (!metricId.value) return
  loading.value = true
  loadError.value = ''
  try {
    const definition = await kpisApi.getMetric(metricId.value)
    let impact: unknown
    try {
      impact = await kpisApi.getMetricImpact(metricId.value)
    } catch { /* 兼容尚未实现影响分析接口的旧服务 */ }
    detail.value = normalizeMetricDetail(definition, impact)
  } catch (error: any) {
    loadError.value = error?.message || '指标详情加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function backToList(): void {
  router.push('/admin/system/metric-query')
}

function openMetric(id: string): void {
  if (id) router.push(`/admin/system/metric-query/${encodeURIComponent(id)}`)
}

watch(metricId, loadDetail, { immediate: true })
</script>

<style scoped lang="scss">
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;

  .el-button {
    margin-bottom: 6px;
    padding-left: 0;
  }
}

.loading-card,
.section-card {
  padding: 16px;
}

.section-card {
  margin-bottom: 14px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;

  h3 {
    margin: 0;
    color: var(--sa-text);
    font-size: 16px;
  }

  p,
  > span {
    color: var(--sa-muted);
    font-size: 12px;
  }

  p {
    margin: 5px 0 0;
  }
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.formula {
  color: #334155;
  line-height: 1.7;
}

.definition-content {
  line-height: 1.8;
  overflow-wrap: anywhere;
  white-space: pre-line;
}

.overflow-text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-descriptions__label) {
  width: 150px;
  color: var(--sa-muted);
}

@media (max-width: 720px) {
  .page-head {
    flex-direction: column;
  }

  :deep(.el-descriptions__body .el-descriptions__table) {
    display: block;
    overflow-x: auto;
  }

}
</style>
