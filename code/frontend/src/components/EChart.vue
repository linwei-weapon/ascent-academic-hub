<!--
  通用 ECharts 包装组件（Style A）。
  · 只注册项目实际用到的图表/组件，全部落在 vite optimizeDeps 已预打包的
    echarts/core|charts|components|renderers 范围内，避免 dev 期 504 重优化。
  · props.option 传完整 ECharts option；深度 watch 后 setOption(true) 全量刷新。
  · ResizeObserver 自适应父容器宽度；卸载时 dispose 释放。
-->
<template>
  <div ref="el" class="sa-echart" :style="{ height: typeof height === 'number' ? height + 'px' : height }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, RadarChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, DatasetComponent,
  TitleComponent, MarkLineComponent, VisualMapComponent, GraphicComponent, PolarComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, RadarChart,
  GridComponent, TooltipComponent, LegendComponent, DatasetComponent,
  TitleComponent, MarkLineComponent, VisualMapComponent, GraphicComponent, PolarComponent,
  CanvasRenderer,
])

const props = withDefaults(defineProps<{ option: any; height?: number | string }>(), { height: 280 })

const el = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const opt = props.option ?? {}
  // 进场动画默认：元素依次跳入（柱/点/扇区按序展开）。option 自带的动画字段优先级更高。
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    animationDelay: (idx: number) => idx * 40,
    ...opt,
  }, true)
}

onMounted(async () => {
  await nextTick()
  render()
  ro = new ResizeObserver(() => chart?.resize())
  if (el.value) ro.observe(el.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})

defineExpose({ resize: () => chart?.resize() })
</script>

<style scoped>
.sa-echart {
  width: 100%;
}
</style>
