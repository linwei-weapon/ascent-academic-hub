# test：本地前端连接测试服务器

## 配置与启动

工作目录为当前项目的 `code/frontend/`。测试服务器地址和端口从 `vite.config.ts` 的 `frontendConfig.test` 读取，不在技能中另维护一份地址。默认本地端口 3007。

```text
npm ci
npm run dev:test
```

依赖已安装且锁文件未变化时跳过 `npm ci`。原型默认 `npm run dev` 与 `dev:test` 均执行 `vite --mode test`；Vite 将 `/api` 代理到 `frontendConfig.test.apiTarget`，数据库由远端后端访问。不要以本地开发后端或示例数据替代测试服务器业务数据。

- 该模式只需要 Node/npm 和测试环境的应用账号；不安装或启动本地 Python、MySQL，不需要 SSH 或数据库密码。
- 使用持久进程工具或隐藏后台启动。Windows 可用当前 Node 执行 `node_modules/vite/bin/vite.js --mode test`，工作目录仍为 `code/frontend/`，通过 `Start-Process -WindowStyle Hidden` 记录日志与 PID；macOS/Linux 用相同参数后台启动。
- 确认启动日志中的实际代理目标和端口与 `frontendConfig.test` 一致；遇到意外目标先核对当前工作目录和启动进程，不能静默改为本地后端。
- 端口冲突且未确认归属时使用 `npm run dev:test -- --port 3008`，返回实际地址；不停止其他项目。
- 如需更改后端地址，修改 `frontendConfig.test.apiTarget` 后重启。前端不加载 `.env` 文件。

## 验证与边界

1. 打开本地 `/#/login`，检查页面和资源是否加载成功。
2. 请求本地 `/api/health`，确认经代理收到远程 JSON 状态。
3. 必要时从本地页面发送空登录表单，确认 POST 返回 JSON 参数校验错误，而不是跨域错误或 HTML；不尝试猜账号密码。
4. 用户使用测试环境应用账号自行登录。数据修改作用于共享测试库；启动检查不执行写业务数据的操作。
5. 菜单由远端授权数据决定。某个本地新页面没有菜单、返回 404 或字段不同，应检查远端版本与权限，不能为“启动成功”擅自修改远程菜单或数据库。
6. 停止本次本地前端进程即可，不停止测试服务器。

## 指标核验原型（已授权时单独启动）

系统管理中的“指标核验”由本仓库独立原型服务提供。`test` 模式仅将 `/api/admin/metric-verification` 转到 `frontendConfig.metricVerification.apiTarget`；其余接口继续使用现有测试环境。该服务复核测试环境的登录和当前身份，直接读取配置的测试库。

需要此模块时，按[指标核验模块说明](../../../../文档/4-需求文档/4.9-系统管理/指标核验模块说明.md)安装依赖并建立服务端配置；运行 `code/scripts/start-metric-verification.ps1` 隐藏启动8010服务。脚本记录PID和日志，不自动迁移、不重置数据库。源库连接仅执行只读查询。服务或身份校验不可用时，不添加此模块入口。

## 专家资源与专家团（已授权时单独启动）

若通过工具启动的进程在会话结束后退出，可使用`code/scripts/start-prototype-services.py`统一启动现有3007、8010、8011服务。Windows应从独立进程启动该脚本，例如通过`Win32_Process.Create`；脚本以隐藏进程运行，仅复用现有配置与控制库，记录PID和日志，并检测HTTP就绪。已占用端口保留并提示核对，不结束其他进程。该方式不设置开机自启，重启电脑后仍需启动。

专家资源服务使用8011端口。`test`模式仅把`/api/admin/expert-resources`代理到本机，其余接口继续使用测试服务器。安装`code/backend/requirements-expert-resources.txt`后运行`code/scripts/start-expert-resources.ps1`。脚本幂等初始化本地资源控制库并记录PID/日志，不修改学校业务库。

业务连接复用`.env.metric-verification`配置；专家、Skill、MCP定义、发布版本与研究结果保存在`code/backend/db/expert_resources.sqlite`。不能把此SQLite称为学校业务数据副本。管理入口沿用`system.manage`，研究沿用测试环境现有`ai.analyze`及有效的全校/学院范围，服务器逐次复核当前登录身份。详细方法、缺项和部署说明见[数据与运行技术规格](../../../../文档/4-需求文档/4.7-AI管理决策/expert-design-v3-20260916/04-数据与运行技术规格.md#12-专家资源管理原型实现)。
