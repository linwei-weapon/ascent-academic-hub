# 07 · 数据初始化与 ETL

> 回答两个问题：**① 数据库里要初始化哪些数据？② 用什么脚本初始化？**

---

## 1. 一句话结论

- 分析库 `analytics.sqlite` **未随包附带**，需用 ETL 从 9 学期源库**重建一次**。
- 初始化数据（账号/角色/菜单/预警规则）是**代码定义的**（`seed.py`），ETL 跑到第⑧步时写入，
  **不是 SQL dump**。
- 初始化脚本：`code/scripts/init.bat`（Windows）/ `init.sh`（macOS/Linux），一键完成。

---

## 2. 要初始化哪些数据

分析库的数据分两类：

### A. 业务数据（从源库 ETL 派生）
33 张表中的 `dim_*` / `fact_*` / `agg_*`，全部由 ETL 从 `datasource/构造数据/` 的 9 学期源库
抽取、清洗、派生、聚合而来。无需手工准备，跑 ETL 即生成。

### B. 系统初始化数据（seed.py 代码定义）
`sys_*` 6 张表的内容是**写死在 `code/backend/etl/seed.py` 里的常量**，ETL 第⑧步写入：

**① 账号 sys_user（11 个）**
- 10 个角色账号：用户名 = 角色 key，密码统一 `Demo@2026`。
- 1 个管理员：`admin` / `admin123`（role=dean）。
- 密码哈希：`pbkdf2_sha256$100000$<盐hex>$<dk hex>`（stdlib hashlib，10 万次迭代 + 16 字节随机盐）。

**② 角色 sys_role（10 个）**
school_leader / dean / dept_operation / dept_research / dept_practice / quality_office /
college_dean / college_secretary / counselor / dept_director，各带 data_scope_type（all/college/major/class）。

**③ 菜单 sys_menu（11 项）**+ **角色菜单 sys_role_menu**
数据大屏 / 预警查看 / 教学运行分析 / 培养质量分析 / 师资结构分析 / 学生学业分析 / 报表中心 /
账号管理 / 菜单管理 / 角色管理 / 系统设置。系统管理三页 + 系统设置仅 dean 可见。

**④ 预警规则 sys_alert_rule（5 条）**
R1 GPA持续下降 / R2 挂科累积 / R3 学分缺口过大 / R4 核心课挂科 / R6 退学风险，全部阈值触发，
params 存引擎实际消费的阈值（见 `01-需求说明.md` §4.1）。

**⑤ 角色数据范围 sys_role_scope**
给院级/系/辅导员角色绑定真实学院/专业/班级 id（演示用，接口暂未按此过滤）。

> 改这些初始值：编辑 `seed.py`，并同步幂等迁移脚本更新已运行的库（见 §5）。

---

## 3. 初始化脚本

| 脚本 | 平台 | 作用 |
|---|---|---|
| `code/scripts/init.bat` | Windows（双击） | 跑 ETL 重建 + 跑菜单/规则迁移 |
| `code/scripts/init.sh` | macOS/Linux/Git-Bash | 同上 |
| `code/scripts/start.bat` / `start.sh` | — | 启动前后端 |
| `code/scripts/e2e_check.py` | — | 端到端数据核对 |
| `code/scripts/migrate_menu.py` | — | 幂等：只更新 sys_menu/sys_role_menu |
| `code/scripts/migrate_alert_rules.py` | — | 幂等：只更新 sys_alert_rule |

`init` 脚本内部等价于：
```bash
cd code
PYTHONIOENCODING=utf-8 python -X utf8 -m backend.etl.run_etl   # 重建 33 表（含 seed 初始化数据）
PYTHONIOENCODING=utf-8 python -X utf8 scripts/migrate_menu.py        # 幂等对齐菜单
PYTHONIOENCODING=utf-8 python -X utf8 scripts/migrate_alert_rules.py # 幂等对齐规则
```

> `run_etl` 本身已经通过 seed 写入了菜单与规则；两个 migrate 脚本是为「不重跑全量 ETL、
> 只热更元数据」的场景准备的幂等工具，init 里一并执行以保证与最新约定一致。

---

## 4. ETL 流程（run_etl.py 9 步）

输入：`datasource/构造数据/*.db`（9 学期）+ `datasource/培养方案docx/*.docx`（2 份）
输出：`code/backend/db/analytics.sqlite`

```
① extract_ts   读 9 个学期源库，并表为成绩源 g / 教学任务源 t / extras（当前在校 ids 等）
② transform    构建 7 维表 + fact_grade（64万行）+ fact_lesson，贯通 9 学期
③ parse_plan   解析 2 份培养方案 docx → fact_plan_meta / fact_plan_course（按专业名对齐 major_id）
④ alert_engine 对当前在校学生快照按 5 规则派生 fact_alert（往届天然排除）
⑤ aggregate    预聚合 6 张 agg_*（按学期）
⑥ synth_business 合成业务表（毕业/考纪/出勤/师资画像/学分要求，固定种子）
⑦ build_real_business 用真实源覆盖异动/校外考试/调停课（标 real）
⑧ seed         写 sys_*（账号/角色/菜单/规则/范围）← 初始化数据在此
⑨ load + validate 入库 + 数据校验报告（行数/挂科率/孤儿外键/GPA/预警分布）
```

校验通过标准：孤儿外键全 0、真实挂科率落在 3-8%。结束打印 `✓ 通过`。

---

## 5. 修改初始化数据后如何生效

| 改什么 | 改哪 | 让运行库生效 |
|---|---|---|
| 账号/角色/范围 | `seed.py` | 重跑 `init`（全量 ETL） |
| 菜单 | `seed.py` 的 MENUS/ROLE_MENU + `migrate_menu.py` | 跑 `migrate_menu.py`（幂等，不必重 ETL） |
| 预警规则阈值 | `seed.py` 的 ALERT_RULES + `migrate_alert_rules.py` | 跑 `migrate_alert_rules.py`；**预警结果重算需重跑 ETL** |

> 原则：`seed.py` 是「重建时的真相源」，migrate 脚本是「不重建时的热更工具」，两者保持一致，
> 避免重跑 init 后改动被回退。

---

## 6. 重建 / 换源数据

- ETL 幂等（schema 先 DROP 再 CREATE），可安全重复跑 `init`。
- 换源数据：替换 `datasource/构造数据/` 下 9 个库（或设环境变量 `TS_DIR` 指向别处），
  替换 `datasource/培养方案docx/`（或设 `DATA_DIR`），重跑 `init`。
- 路径解析见 `code/backend/etl/config.py`：默认相对交接包结构
  （`PKG_ROOT/datasource/构造数据` 与 `/培养方案docx`），可被 `TS_DIR`/`DATA_DIR` 环境变量覆盖。

---

## 7. 数据库初始数据快照（核对用）

跑完 init 后，关键计数应接近：

| 项 | 值 |
|---|---|
| 表数量 | 33 |
| dim_student | 12,670 |
| dim_teacher | 437 |
| fact_grade | ~640,000 |
| fact_alert | ~5,027 |
| dim_semester | 9（当前=2025-2026-2） |
| sys_user | 11 |
| sys_role | 10 |
| sys_menu | 11 |
| sys_alert_rule | 5 |
| 真实挂科率 | 3-8%（约 6%） |
