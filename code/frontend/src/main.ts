// Element Plus 全量样式先加载，项目主题与页面样式随后覆盖。
import 'element-plus/dist/index.css'
import App from './App.vue'
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import { initStore } from './store'
import { initRouter } from './router'
import { applyStyleA } from './utils/theme'
import '@styles/core/tailwind.css'
import '@styles/index.scss'

// 注入 Style A 靛蓝主题（覆盖 ElementPlus 主色色阶，全局组件随之换肤）
applyStyleA()

const app = createApp(App)
// 统一注册 Element Plus 组件、指令和服务；业务组件沿用页面引用方式。
app.use(ElementPlus)
initStore(app)
initRouter(app)
app.mount('#app')
