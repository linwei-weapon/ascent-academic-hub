# 智能学业分析平台 · 交接包

> 高校教务**学业数据分析 BI 平台**（只读看板，不干预业务数据）。
> 本交接包**自包含**：含全部代码、数据源、文档与一键脚本，接收方可独立重建并演示。

---

## 一、这是什么

面向高校校、院两级的学业数据分析系统。汇聚 9 个学期的教务成绩、学籍、培养方案数据，
提供学业预警、培养质量、师资结构、教学运行、报表中心等多维只读看板。
**只做数据展示与分析，不回写教务业务库。**

- 前端：Vue 3 + Vite 7 + TypeScript + Element Plus + ECharts + Pinia（管理端，hash 路由）
- 后端：Python 3.13 + FastAPI + Uvicorn，raw sqlite3 只读查询，统一 `{code,msg,data}` 包络
- 数据：9 学期源 SQLite 库 → ETL → 星型分析库 `analytics.sqlite`（33 表）

---

## 二、目录结构

```
智能学业分析平台-交接/
├── README.md                  ← 本文件（总入口）
├── docs/                      ← 全套交接文档
│   ├── 01-需求说明.md
│   ├── 02-技术方案.md
│   ├── 03-部署手册.md          ← 先看这个跑起来
│   ├── 04-使用手册.md
│   ├── 05-二次开发指南.md
│   ├── 06-数据库表结构.md
│   ├── 07-数据初始化与ETL.md
│   └── 既有文档/               ← 研发过程产出（规划/技术方案/数据字典/血缘等）
├── code/
│   ├── backend/               ← FastAPI 后端 + ETL（Python）
│   │   ├── api/               ← 路由（12 个 router）
│   │   ├── etl/               ← ETL 全链路 + schema.sql + seed.py
│   │   ├── db/                ← 分析库输出目录（初始空，init 后生成 analytics.sqlite）
│   │   └── requirements.txt
│   ├── frontend/              ← Vue 3 管理端
│   └── scripts/               ← init / start / e2e / 迁移脚本
├── datasource/
│   ├── 构造数据/              ← 9 学期源 SQLite 库（ETL 主输入，~177MB）
│   └── 培养方案docx/          ← 2 份真实培养方案（ETL 步骤③解析）
└── 演示截图/                  ← 各页面演示截图
```

> **注意**：分析库 `analytics.sqlite` **未随包附带**，需接收方运行一次 ETL 重建（见下）。
> 这样保证交接的是「可复现的数据管线」，而非一个黑盒库文件。

---

## 三、五分钟跑起来

详细步骤见 `docs/03-部署手册.md`。最短路径：

```bash
# 1) 后端依赖
cd code/backend && pip install -r requirements.txt && cd ..

# 2) 一键初始化分析库（跑 ETL，约 1-3 分钟）
#    Windows: 双击 scripts\init.bat
#    macOS/Linux:
bash scripts/init.sh

# 3) 前端依赖
cd frontend && pnpm install && cd ..

# 4) 一键启动前后端
#    Windows: 双击 scripts\start.bat
#    macOS/Linux:
bash scripts/start.sh
```

- 前端：http://localhost:3006/   后端：http://localhost:8000/api/health
- 登录：**admin / admin123**（其余 10 个角色账号见 `docs/04-使用手册.md`）

---

## 四、文档导航

| 想了解 | 看这份 |
|---|---|
| 系统做什么、给谁用、有哪些页面 | `docs/01-需求说明.md` |
| 架构、技术选型、四层数据管线 | `docs/02-技术方案.md` |
| 怎么装、怎么跑、常见报错 | `docs/03-部署手册.md` |
| 登录、各页面怎么用、账号角色 | `docs/04-使用手册.md` |
| 改代码、加页面、加接口、改数据 | `docs/05-二次开发指南.md` |
| 33 张表的字段含义 | `docs/06-数据库表结构.md` |
| 初始化数据有哪些、ETL 怎么跑 | `docs/07-数据初始化与ETL.md` |

---

## 五、铁律（交接方务必知晓）

1. **只读系统**：所有接口对分析库只读，绝不回写教务源库。
2. **数据真实性**：能真算的真算；真实学业源缺失的业务域（毕业去向/考勤/考纪等）由 ETL
   合成真表（固定随机种子可复现，标 `source='sim'`，**前端不暴露**），绝不在 API 层硬编码假数。
3. **真实培养方案仅 2 份**：安全工程、海洋油气工程（均 2022 级），其余专业按铁律不造方案，
   前端诚实空态。
4. **终端编码**：跑 Python 须 `PYTHONIOENCODING=utf-8 python -X utf8`（否则中文 GBK 乱码）。
5. 改后端代码需重启 uvicorn（脚本未开 `--reload`）。
