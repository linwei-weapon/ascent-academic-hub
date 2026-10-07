# local：本地前后端与 SQLite

以下路径均相对于当前项目根目录。先读实际代码；本指南不把部署服务器的 MySQL 复制到本机。

## 1. 后端依赖与数据库

优先使用 `.venv/Scripts/python.exe`（Windows）或 `.venv/bin/python`（macOS/Linux），确认能够导入 `fastapi`、`uvicorn`、`pandas`、`httpx`。没有虚拟环境时创建 `.venv`，使用它安装 `code/backend/requirements.txt`；不要误用另一项目的 Python。

在 `code/` 用选定的 Python 读取 `backend.etl.config` 的 `DB_PATH`、`V2_DB_PATH`、`TS_DIR`。已有环境变量覆盖时沿用已确认的配置，不能把一个路径的库用于另一个项目。默认分析库为：

```text
code/backend/db/analytics.sqlite
code/backend/db/analytics_v2.sqlite
```

- 两库存在：检查只读连接可打开，继续启动；不自动初始化或迁移。
- 只存在部分库，或已有正式源数据却缺分析库：说明缺失项和路径，先确认需要恢复、正式 ETL 还是独立演示数据；不覆盖已有文件。
- 首次克隆且两库与源目录均为空：可以使用仓库自带 `scripts/bootstrap_demo_data.py` 创建脱敏演示数据，明确告诉用户数据为演示。生成与启动必须使用同一组路径环境变量。

首次演示初始化在 `code/` 执行以下脚本；逐条检查退出码，失败就停止。不要添加 `--force`。下面 `python` 均替换为已选定虚拟环境的解释器：

```text
python -X utf8 scripts/bootstrap_demo_data.py
python -X utf8 scripts/migrate_menu.py
python -X utf8 scripts/migrate_alert_rules.py
python -X utf8 scripts/migrate_permission_context.py
python -X utf8 scripts/migrate_staff_relationships.py
python -X utf8 scripts/migrate_etl_run.py
python -X utf8 scripts/migrate_system_management.py
python -X utf8 scripts/migrate_faculty_personnel_snapshot.py
python -X utf8 scripts/migrate_student_growth_indexes.py
python -X utf8 scripts/migrate_basic_reports.py
```

该列表对应现有 `code/scripts/init.sh` 的控制数据迁移；执行前核对脚本仍存在。不要执行历史 `migrate_decision_config_menu.py`，它会重新加入已废弃菜单。演示数据只覆盖其生成器声明的范围，不能假定专家研究等扩展模块已经有正式数据。

## 2. 启动

前端配置统一在 `code/frontend/vite.config.ts` 的 `frontendConfig.local` 中，默认代理本地 8000 后端；无需创建或复制 `.env` 文件。启动前核对配置中的实际端口和地址。

后端工作目录为 `code/`，使用选定的 Python：

```text
python -X utf8 -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

前端工作目录为 `code/frontend/`：

```text
npm run dev:local -- --host 127.0.0.1 --port 3006 --strictPort
```

用持久进程工具或隐藏后台方式启动，不要调用会弹出两个命令窗口的旧 `start.bat`。

Windows 后台示例：先把 `$projectRoot` 设置为已核实的当前仓库绝对路径；`$pythonExe` 设置为已核实的 Python 路径。`$runDir` 为仓库 `work/runtime/highedu-start/`，创建后执行：

```powershell
$backend = Start-Process -FilePath $pythonExe -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'backend.api.main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory (Join-Path $projectRoot 'code') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir 'local-backend.out.log') -RedirectStandardError (Join-Path $runDir 'local-backend.err.log') -PassThru
```

前端可直接使用当前 Node 执行 `code/frontend/node_modules/vite/bin/vite.js`，参数与上方 npm 命令一致（省略 `--open`），同样隐藏启动并记录日志。macOS/Linux 使用同一工作目录、解释器和参数，以 `nohup` 后台启动并记录 PID。

更换后端端口时，同步 `frontendConfig.local.apiTarget`；更换前端端口时，核对后端允许的本地来源。不要只改一端。

## 3. 验证与停止

1. 后端 `http://127.0.0.1:8000/api/health` 返回 JSON。
2. 前端 `http://127.0.0.1:3006/#/login` 加载成功，前端 `/api/health` 返回相同后端状态。
3. 新生成演示数据的账号以生成脚本或使用手册为准；已有数据库由用户用自己的账号登录。健康接口不证明全部业务数据、权限或模型配置可用。
4. 停止时先核对记录 PID 的当前进程仍属于该仓库，再停止本次启动的前后端；停止程序不会删除数据库。
