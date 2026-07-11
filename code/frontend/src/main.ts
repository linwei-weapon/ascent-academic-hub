import App from './App.vue'
import { createApp } from 'vue'
import { initStore } from './store'
import { initRouter } from './router'
import { applyStyleA } from './utils/theme'
import '@styles/core/tailwind.css'
import '@styles/index.scss'

// 注入 Style A 靛蓝主题（覆盖 ElementPlus 主色色阶，全局组件随之换肤）
applyStyleA()

const app = createApp(App)
initStore(app)
initRouter(app)
app.mount('#app')
