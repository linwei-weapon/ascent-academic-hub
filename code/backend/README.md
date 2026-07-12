# 平台管理端 · 后端 API（阶段3）

FastAPI + SQLite 分析库（`backend/db/analytics.sqlite`，分析查询只读、治理接口受控写入）。统一响应包络 `{code,msg,data}`，
前端读 `d.data`，接口形状对齐 `平台管理端-0618/vite.config.ts` 的 mock，可零改动切换。

## 启动

```bash
# 依赖：fastapi uvicorn pydantic python-jose[cryptography] python-multipart
PYTHONIOENCODING=utf-8 python -X utf8 -m uvicorn backend.api.main:app --reload --port 8000
```

健康检查：`GET http://localhost:8000/api/health` → `{"code":0,"msg":"ok","data":{"status":"up"}}`

## 演示账号

开发演示账号统一密码 `Demo@2026`。常用：`dean`、`college_dean`、`counselor`、`admin`。
所有 `/api/admin/*` 业务接口均要求 Bearer Token；核心数据接口按角色的数据范围过滤，RBAC 与安全审计接口仅 `dean` 可访问。
生产环境不得沿用演示账号和默认 JWT 密钥。

## 接口清单

| 方法 | 路径 | 说明 | 数据源 |
|---|---|---|---|
| POST | /api/auth/login | 登录，返回 token + user(menus) | sys_user/role/menu |
| GET | /api/auth/me | 当前用户 | — |
| POST | /api/auth/logout | 登出并撤销当前 JWT jti | sys_revoked_token |
| GET | /api/admin/dashboard | 大屏总览 | dim_* + agg_* |
| GET | /api/admin/college/{id} | 学院详情 | fact_grade + agg_* |
| GET | /api/admin/major/{id} | 专业详情 | fact_grade |
| GET | /api/admin/course/{id} | 课程详情 | fact_grade |
| GET | /api/admin/alerts | 预警总览/列表 | fact_alert |
| GET | /api/admin/student/{sid} | 学生明细 | fact_grade + fact_alert |
| GET | /api/admin/curriculum/plan/{major} | 培养方案 | fact_plan_meta/course |
| GET | /api/admin/reports?type= | 报表中心 | 见下 |
| GET | /api/admin/reports/custom?metrics=&dimension=&semester= | 自定义报表 | 真实学生/成绩/预警受控聚合 |
| POST | /api/admin/settings/rules/discover | 运行规则自发现 | 真实数据历史关联候选，不直接生效 |
| GET/PUT | /api/admin/settings/rules/discovered | 查询/采纳规则建议 | 采纳仅创建规则治理草稿 |
| GET/PUT | /api/admin/settings/kpi-config | 注册 KPI 显示与排序治理 | sys_kpi_config |
| GET | /api/admin/rbac/security-audit | 安全审计（管理员） | sys_security_audit |

**培养方案**：真实方案仅 2 个专业（M017 安全工程 / M031 海洋油气工程，2022级）。
前端选择器传占位 id（pe2007 等），后端别名映射 `me_safety→M017`、`pe_ocean→M031`，
未命中回退首个真实方案。

**报表 type**：`score/passrank/alert/attrition/exam` 由真实同步数据计算；
`discipline/graduate/attend` 为规则模拟事实，`credit` 混合真实培养要求与模拟毕业事实。
接口响应会返回 evidence 明细，前端明确展示证据等级；所有学生级报表接入角色数据范围。

**自定义报表**：当前开放 K001 在籍学生数、K002 预警学生数、K003 GPA 均值、
K004 挂科率，支持学院/专业/年级维度与学期筛选。缺少可靠来源的指标不生成替代值。

**规则自发现**：`association-v2` 仅使用真实成绩、真实学籍异动和当前严重预警做历史关联分析。
所有候选特征必须由通用规则引擎可执行；未知特征按失败关闭处理。采纳建议只创建禁用规则占位和
规则变更草稿，之后必须完成影响试算、独立复核、发布配置和受控激活。

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

先起后端（8000）再起前端（3006）。CORS 默认只允许本地 3006/3007 来源，可通过逗号分隔的
`BI_CORS_ORIGINS` 配置部署白名单。生产环境设置 `BI_APP_ENV=production` 时必须同时配置独立
`BI_JWT_SECRET`，否则后端拒绝启动。

安全基线：新密码使用 PBKDF2-SHA256 310,000 次迭代；JWT 校验 issuer/audience 并携带 jti；
登录按“用户名×客户端”执行 15 分钟 8 次失败限流；登录、登出与 RBAC/KPI 敏感变更进入只读审计页面。
