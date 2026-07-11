/**
 * Style A「靛蓝清爽」主题注入。
 *
 * 全局视觉只有一个真相源：ElementPlus 主色变量 `--el-color-primary` 及其色阶。
 * 项目里 `--main-color → --theme-color` 都指向它，因此覆盖这一组变量即可让
 * el-button / el-tag / el-menu / el-switch / el-progress / el-pagination / el-select
 * 等所有 ElementPlus 组件，以及 nprogress 进度条统一切换为靛蓝。
 *
 * 用 documentElement 内联变量写入：内联样式优先级高于任何样式表 :root，
 * 不受 ElementPlus 运行时注入顺序影响，确定性覆盖。
 */

type RGB = [number, number, number]
const WHITE: RGB = [255, 255, 255]
const BLACK: RGB = [0, 0, 0]

function hexToRgb(hex: string): RGB {
  const h = hex.replace('#', '')
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
}
function rgbToHex([r, g, b]: RGB): string {
  const f = (n: number) => Math.round(n).toString(16).padStart(2, '0')
  return `#${f(r)}${f(g)}${f(b)}`
}
function mix(base: RGB, other: RGB, w: number): RGB {
  return [base[0] * (1 - w) + other[0] * w, base[1] * (1 - w) + other[1] * w, base[2] * (1 - w) + other[2] * w]
}

/** 生成 ElementPlus 单色完整色阶（base + light-3/5/7/8/9 + dark-2） */
function rampVars(name: string, baseHex: string): Record<string, string> {
  const base = hexToRgb(baseHex)
  const out: Record<string, string> = { [`--el-color-${name}`]: baseHex }
  for (const lv of [3, 5, 7, 8, 9]) out[`--el-color-${name}-light-${lv}`] = rgbToHex(mix(base, WHITE, lv / 10))
  out[`--el-color-${name}-dark-2`] = rgbToHex(mix(base, BLACK, 0.2))
  return out
}

/** Style A 色板（与 _style-preview.html A 套一致） */
export const STYLE_A = {
  primary: '#4F46E5', // 靛蓝 主强调
  teal: '#0D9488', // 青绿 数据正向
  amber: '#D97706', // 琥珀 关注
  danger: '#E11D48', // 玫红 风险
  text: '#1E293B', // slate-800 正文/标题
  muted: '#64748B', // slate-500 次要
  faint: '#94A3B8', // slate-400 极弱
  border: '#EAEDF2', // 卡片描边
  appBg: '#F8FAFC', // 页面底
  headFont: "'Plus Jakarta Sans','Noto Sans SC',system-ui,sans-serif",
} as const

export function applyStyleA(): void {
  const root = document.documentElement
  const vars: Record<string, string> = {
    ...rampVars('primary', STYLE_A.primary),
    ...rampVars('success', STYLE_A.teal), // success → 青绿（数据正向）
    ...rampVars('warning', STYLE_A.amber),
    ...rampVars('danger', STYLE_A.danger),
    ...rampVars('error', STYLE_A.danger),
    ...rampVars('info', STYLE_A.muted),
    '--custom-radius': '10px', // 卡片 14 / 控件 ~5px 的基准
  }
  for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v)
}
