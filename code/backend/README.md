# 平台管理端 · 后端 API（阶段3）

FastAPI + 只读 SQLite（`backend/db/analytics.sqlite`）。统一响应包络 `{code,msg,data}`，
前端读 `d.data`，接口形状对齐 `平台管理端-0618/vite.config.ts` 的 mock，可零改动切换。

## 启动

```bash
# 依赖：fastapi uvicorn pydantic python-jose[cryptography] python-multipart
PYTHONIOENCODING=utf-8 python -X utf8 -m uvicorn backend.api.main:app --reload --port 8000
```

健康检查：`GET http://localhost:8000/api/health` → `{"code":0,"msg":"ok","data":{"status":"up"}}`

## 演示账号

统一密码 `Demo@2026`。常用：`dean`(教务处处长,9菜单)、`college_dean`(8)、`counselor`(辅导员,1)、`admin`。
鉴权仅做**菜单权限**（`sys_role_menu`），无数据/功能权限。`/api/admin/*` 业务接口当前不校验 token
（与 mock 一致，前端零改动）；`/api/auth/me`、`/api/auth/logout` 需 `Authorization: Bearer <token>`。

## 接口清单

| 方法 | 路径 | 说明 | 数据源 |
|---|---|---|---|
| POST | /api/auth/login | 登录，返回 token + user(menus) | sys_user/role/menu |
| GET | /api/auth/me | 当前用户 | — |
| POST | /api/auth/logout | 登出（无状态占位） | — |
| GET | /api/admin/dashboard | 大屏总览 | dim_* + agg_* |
| GET | /api/admin/college/{id} | 学院详情 | fact_grade + agg_* |
| GET | /api/admin/major/{id} | 专业详情 | fact_grade |
| GET | /api/admin/course/{id} | 课程详情 | fact_grade |
| GET | /api/admin/alerts | 预警总览/列表 | fact_alert |
| GET | /api/admin/student/{sid} | 学生明细 | fact_grade + fact_alert |
| GET | /api/admin/curriculum/plan/{major} | 培养方案 | fact_plan_meta/course |
| GET | /api/admin/reports?type= | 报表中心 | 见下 |
| GET | /api/admin/reports/custom?metrics=&dimension=&semester= | 自定义报表 | 真实学生/成绩/预警受控聚合 |

**培养方案**：真实方案仅 2 个专业（M017 安全工程 / M031 海洋油气工程，2022级）。
前端选择器传占位 id（pe2007 等），后端别名映射 `me_safety→M017`、`pe_ocean→M031`，
未命中回退首个真实方案。

**报表 type**：`score/passrank/alert/attrition/exam` 由真实同步数据计算；
`discipline/graduate/attend` 为规则模拟事实，`credit` 混合真实培养要求与模拟毕业事实。
接口响应会返回 evidence 明细，前端明确展示证据等级；所有学生级报表接入角色数据范围。

**自定义报表**：当前开放 K001 在籍学生数、K002 预警学生数、K003 GPA 均值、
K004 挂科率，支持学院/专业/年级维度与学期筛选。缺少可靠来源的指标不生成替代值。

## 前后端联调（切换 mock → 真实后端）

编辑 `平台管理端-0618/vite.config.ts`：

1. 注释 `plugins` 中的 `mockPlugin()`。
2. `server` 增加代理：

```ts
server: {
  port: Number(VITE_PORT), host: true,
  proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
}
```

先起后端（8000）再起前端（3006）。CORS 演示环境已放开（`allow_origins=["*"]`）。
