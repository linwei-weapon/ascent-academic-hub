<!--
  Style A KPI 统计卡：白底 + 1px 描边 + 14 圆角 + 无阴影，数字用 Plus Jakarta + 等宽数字。
  tone 决定数值色：primary 靛蓝 / teal 青绿 / danger 玫红 / amber 琥珀 / plain 墨色。
  hint 存在时在标签后挂一个 ⓘ tooltip（指标口径说明）。
-->
<template>
  <div
    class="sa-kpi"
    :class="{ 'sa-kpi--interactive': canDrill, 'sa-kpi--disabled': interactive && !canDrill }"
    :role="canDrill ? 'button' : undefined"
    :tabindex="canDrill ? 0 : undefined"
    :aria-label="canDrill ? `${label}，${actionText || '查看明细'}` : undefined"
    :aria-disabled="interactive && !canDrill ? 'true' : undefined"
    @click="activate"
    @keydown.enter.prevent="activate"
    @keydown.space.prevent="activate"
  >
    <div class="sa-kpi__label">
      <span>{{ label }}</span>
      <el-tooltip v-if="hint" :content="hint" placement="top" effect="dark">
        <span class="sa-kpi__info" @click.stop>&#9432;</span>
      </el-tooltip>
    </div>
    <div class="sa-kpi__value tnum" :style="{ color: valueColor }">{{ display }}</div>
    <div v-if="sub" class="sa-kpi__sub">{{ sub }}</div>
    <div v-if="interactive" class="sa-kpi__action">
      {{ canDrill ? (actionText || '查看明细') : (disabledReason || '暂不可下钻') }}
      <span v-if="canDrill" aria-hidden="true">→</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: string | number
    sub?: string
    tone?: 'primary' | 'teal' | 'danger' | 'amber' | 'plain'
    hint?: string
    interactive?: boolean
    actionText?: string
    disabledReason?: string
  }>(),
  { tone: 'primary', interactive: false, actionText: '', disabledReason: '' }
)
const emit = defineEmits<{ (event: 'drilldown'): void }>()

const TONE: Record<string, string> = {
  primary: 'var(--sa-primary)',
  teal: 'var(--sa-teal)',
  danger: 'var(--sa-danger)',
  amber: 'var(--sa-amber)',
  plain: 'var(--sa-text)',
}
const valueColor = computed(() => TONE[props.tone || 'primary'])
const canDrill = computed(() => props.interactive && !props.disabledReason)

function activate() {
  if (canDrill.value) emit('drilldown')
}

// ---- 数值进场「跳动」：从 0 滚动到目标值，保留前后缀/千分位/小数位 ----
const display = ref('')
let raf = 0

function runCountUp(raw: string | number) {
  cancelAnimationFrame(raf)
  const str = String(raw ?? '')
  const m = str.match(/-?[\d,]*\.?\d+/)
  // 无数字（如 "—" / "暂无"）直接展示，不做动画
  if (!m) { display.value = str; return }
  const token = m[0]
  const prefix = str.slice(0, m.index)
  const suffix = str.slice((m.index ?? 0) + token.length)
  const hasComma = token.includes(',')
  const clean = token.replace(/,/g, '')
  const decimals = clean.includes('.') ? clean.split('.')[1].length : 0
  const target = parseFloat(clean)
  if (!isFinite(target)) { display.value = str; return }

  const fmt = (v: number) => {
    let s = decimals ? v.toFixed(decimals) : String(Math.round(v))
    if (hasComma) {
      const parts = s.split('.')
      parts[0] = Number(parts[0]).toLocaleString('en-US')
      s = parts.join('.')
    }
    return prefix + s + suffix
  }

  const dur = 850
  const t0 = performance.now()
  const tick = (now: number) => {
    const t = Math.min(1, (now - t0) / dur)
    const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic
    if (t < 1) {
      display.value = fmt(target * eased)
      raf = requestAnimationFrame(tick)
    } else {
      // 收尾用原始字符串，避免四舍五入与原值有偏差
      display.value = prefix + token + suffix
    }
  }
  raf = requestAnimationFrame(tick)
}

watch(() => props.value, v => runCountUp(v), { immediate: true })
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<style scoped>
.sa-kpi {
  background: #fff;
  border: 1px solid #eaedf2;
  border-radius: 14px;
  padding: 16px 18px;
  min-width: 0;
  transition: border-color 0.18s ease, transform 0.18s ease, background 0.18s ease;
}
.sa-kpi--interactive {
  cursor: pointer;
}
.sa-kpi--interactive:hover {
  border-color: color-mix(in srgb, var(--sa-primary) 42%, var(--sa-border));
  background: color-mix(in srgb, var(--sa-primary) 3%, #fff);
  transform: translateY(-1px);
}
.sa-kpi--interactive:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--sa-primary) 24%, transparent);
  outline-offset: 2px;
  border-color: var(--sa-primary);
}
.sa-kpi--disabled {
  cursor: not-allowed;
}
.sa-kpi__label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.2;
}
.sa-kpi__info {
  color: #94a3b8;
  cursor: help;
  font-size: 12px;
}
.sa-kpi__value {
  font-family: 'Plus Jakarta Sans', 'Noto Sans SC', sans-serif;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  margin-top: 8px;
  letter-spacing: -0.01em;
}
.sa-kpi__sub {
  font-size: 11px;
  color: #64748b;
  margin-top: 7px;
  line-height: 1.3;
}
.sa-kpi__action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: 9px;
  color: var(--sa-primary);
  font-size: 11px;
  font-weight: 600;
}
.sa-kpi--disabled .sa-kpi__action {
  color: var(--sa-faint);
}
@media (prefers-reduced-motion: reduce) {
  .sa-kpi { transition: none; }
}
</style>
