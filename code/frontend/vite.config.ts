import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'
import viteCompression from 'vite-plugin-compression'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import tailwindcss from '@tailwindcss/vite'

export default ({ mode }: { mode: string }) => {
  const root = process.cwd()
  const env = loadEnv(mode, root)
  const { VITE_VERSION, VITE_PORT, VITE_BASE_URL } = env

  console.log(`🚀 VERSION = ${VITE_VERSION}`)

  return defineConfig({
    define: { __APP_VERSION__: JSON.stringify(VITE_VERSION) },
    base: VITE_BASE_URL,
    server: {
      port: Number(VITE_PORT), host: true,
      // 使用显式 IPv4 回环地址，避免 Windows 上 localhost 优先解析为 ::1，
      // 而后端仅监听 127.0.0.1 时代理请求失败。
      proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
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
