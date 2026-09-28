---
name: highedu-start
description: 启动高教 ascent-academic-hub 项目。支持 local 本地前端、FastAPI 后端与 SQLite，以及 test 本地前端连接测试服务器后端与 MySQL。用于启动项目、切换开发连接方式或排查启动失败；不负责发布服务器或迁移远程数据。
---

# 高教项目启动

## 选择模式

| 用户意图 | 模式 | 启动内容 | 默认入口 |
| --- | --- | --- | --- |
| 本地开发、本地后端和数据库 | `local` | Vue + FastAPI + 本地 SQLite | `http://127.0.0.1:3006` |
| 连接测试环境、使用服务器数据 | `test` | 本地 Vue，代理远端 Java 后端及其 MySQL | `http://127.0.0.1:3007` |

用户可输入 `$highedu-start local` 或 `$highedu-start test`。从本轮上下文确定模式；没有明确选择时，先问使用本地还是测试环境，同时检查项目与依赖。

这里的模式是启动方式。`test` 不会在本地启动 MySQL；`local` 的 SQLite 是文件数据库，无需独立数据库服务。

## 共用流程

1. 定位当前协作者的项目根目录，确认存在 `code/frontend/package.json`、`code/backend/api/main.py`。技能放在仓库 `.agents/skills/highedu-start`；从该目录向上三级可定位仓库，不能写死某位开发者的盘符或目录。核对当前分支及项目 `AGENTS.md`，保留已有修改。
2. 检查 Node/npm、前端依赖和端口。Node 版本以项目所用 Vite 的 `engines` 为准；当前为 20.19 以上的 20.x 或 22.12 以上。依赖缺失时在 `code/frontend` 执行 `npm ci`；Windows PowerShell 使用 `npm.cmd`。
3. 只读取所选模式的指南：[local](references/local.md) 或 [test](references/test.md)。本地模式优先使用当前仓库 `.venv`，测试模式不需要 Python、SSH 私钥或数据库密码。
4. 启动前核对占用端口的进程、工作目录和启动参数。属于同一项目、模式且健康的服务可复用；归属不明时换空闲端口或说明占用，不批量结束 Node/Python。切换模式时先检查启动参数，不能仅凭页面相同判断模式。
5. 使用工具提供的持久进程会话，或操作系统后台启动方式。Windows 用 `Start-Process -WindowStyle Hidden`；macOS/Linux 可用 `nohup`。在 `work/runtime/highedu-start/` 记录日志、PID、项目目录和模式，便于后续核对及停止；不要保存账号密码、Token 或数据库内容。
6. 验证本地登录页和经前端代理的 `/api/health`。检查浏览器页面错误；可用空登录表单检查是否返回 JSON 参数校验错误，不能把这当成真实登录成功。需要真实账号时由用户自行登录，不索取或保存密码。
7. 回报模式、前端地址、实际后端地址、本地数据库路径（仅 local）、日志与停止方式，以及已验证和未验证的范围。不能仅凭端口监听就宣布可用。

## 数据与变更范围

- 日常启动复用已有本地库；不要自动运行 `init.bat`、`init.sh` 或正式 ETL，它们可能重建数据。新协作者首次启动的处理见 local 指南。
- `test` 使用共享环境真实数据。启动验证只读；不要附带修菜单、补角色授权、迁移数据库或重启远端服务。界面缺失或接口不兼容应定位到菜单、权限、后端版本，报告后再按用户任务处理。
- 公共配置统一在 `code/frontend/vite.config.ts` 的 `frontendConfig` 中维护；按模式使用 `local` 或 `test`。前端不加载 `.env` 文件，不在前端配置中保存数据库密码或密钥。
- 当前仓库后端为 Python/SQLite，测试服务器为另一份 Java/MySQL 实现。新前端功能需要测试后端已提供相应接口；不要直接把 Python 的 SQLite 迁移脚本用于 MySQL。
- 启动操作不包含 Git 提交、推送或线上发布。

## 团队使用

该技能与项目代码一起分发。协作者在仓库目录内打开支持仓库技能的 Codex，再使用 `$highedu-start local` 或 `$highedu-start test`。如果工具没有自动发现技能，可直接要求它读取此文件并执行；不必复制到个人技能目录。

人工启动与环境说明统一见[开发环境部署方案](../../../文档/5-部署方案/新增-5.1-开发环境部署方案.md)。
