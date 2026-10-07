import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'
import viteCompression from 'vite-plugin-compression'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import tailwindcss from '@tailwindcss/vite'

// 原型默认使用测试服务器；dev:local 才显式使用本地开发后端。
const frontendConfig = {
  version: '3.0.2',
  base: '/',
  local: { port: 3006, apiTarget: 'http://127.0.0.1:8000' },
  test: { port: 3007, apiTarget: 'http://114.215.189.215' },
  metricVerification: { apiTarget: 'http://127.0.0.1:8010' },
  expertResources: { apiTarget: 'http://127.0.0.1:8011' },
}

export default ({ mode }: { mode: string }) => {
  const remoteTest = mode === 'test'
  const { port, apiTarget } = remoteTest ? frontendConfig.test : frontendConfig.local
  const apiOrigin = new URL(apiTarget).origin

  console.log(`🚀 VERSION = ${frontendConfig.version}`)
  console.log(`[API proxy] /api -> ${apiTarget}`)

  return defineConfig({
    envDir: false,
    define: { __APP_VERSION__: JSON.stringify(frontendConfig.version) },
    base: frontendConfig.base,
    server: {
      port, host: remoteTest ? '127.0.0.1' : true,
      strictPort: remoteTest,
      // 使用显式 IPv4 回环地址，避免 Windows 上 localhost 优先解析为 ::1，
      // 而后端仅监听 127.0.0.1 时代理请求失败。
      proxy: {
        ...(remoteTest ? {
          '/api/admin/expert-resources': {
            target: frontendConfig.expertResources.apiTarget,
            changeOrigin: true,
          },
          '/api/admin/metric-verification': {
            target: frontendConfig.metricVerification.apiTarget,
            changeOrigin: true,
          },
        } : {}),
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          configure(proxy) {
            proxy.on('proxyReq', (proxyReq, req) => {
              // Spring checks Origin on POST requests. Translate only requests
              // originating from this local frontend, preserving authentication.
              if (remoteTest && req.headers.origin === `http://${req.headers.host}`) {
                proxyReq.setHeader('Origin', apiOrigin)
              }
            })
          },
        },
      },
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@styles': resolvePath('src/assets/styles')
      }
    },
    build: {
      target: 'es2015', outDir: 'dist', chunkSizeWarningLimit: 2000,
      minify: 'terser',
      terserOptions: { compress: { drop_console: true, drop_debugger: true } },
    },
    plugins: [
      vue(),
      tailwindcss(),
      AutoImport({
        imports: ['vue', 'vue-router', 'pinia', '@vueuse/core'],
        dts: 'src/types/import/auto-imports.d.ts',
        // 当前未接入 ESLint，不生成未使用的全局变量配置文件。
        eslintrc: { enabled: false }
      }),
      // 仅自动引入本项目组件；Element Plus 已在 main.ts 全局注册。
      Components({ dts: 'src/types/import/components.d.ts' }),
      viteCompression({ verbose: false, disable: false, algorithm: 'gzip', ext: '.gz', threshold: 10240, deleteOriginFile: false }),
    ],
    optimizeDeps: {
      include: ['echarts/core','echarts/charts','echarts/components','echarts/renderers','element-plus']
    },
    css: {
      preprocessorOptions: { scss: { additionalData: `` } },
      postcss: { plugins: [{ postcssPlugin:'internal:charset-removal', AtRule:{ charset:(atRule:any)=>{ if(atRule.name==='charset') atRule.remove() } } }] }
    }
  })
}

function resolvePath(paths: string) { return path.resolve(__dirname, paths) }
