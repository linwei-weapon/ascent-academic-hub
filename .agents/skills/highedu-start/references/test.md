# test：本地前端连接测试服务器

## 配置与启动

工作目录为当前项目的 `code/frontend/`。测试服务器地址和端口从 `vite.config.ts` 的 `frontendConfig.test` 读取，不在技能中另维护一份地址。默认本地端口 3007。

```text
npm ci
npm run dev:test
```

依赖已安装且锁文件未变化时跳过 `npm ci`。`dev:test` 执行 `vite --mode test`；Vite 将 `/api` 代理到 `frontendConfig.test.apiTarget`，数据库由远端后端访问。

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
