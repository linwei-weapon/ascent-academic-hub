# 发布操作

以下使用 PowerShell 本地命令及 Linux 远端命令。替换示例版本为本次实际值；自动执行时检查每条命令退出码，失败不继续。macOS/Linux 使用 `npm`，Windows 使用 `npm.cmd`。

## 1. 登录与基线

```powershell
ssh edu_developer@114.215.189.215
```

在远端终端执行：

```bash
sudo -n /usr/local/sbin/highedu-publish status
curl -fsS http://127.0.0.1/api/health
test -w /home/edu_developer/uploads && echo "上传目录可写"
```

记录 `Current` 指向的完整版本目录名及 `MainPID`；健康接口应返回 `code: 0`、`data.status: up`。这些指定 sudo 命令无需再次输入密码；权限错误时报告实际输出，不改用管理员账号绕过。SSH 主机密钥首次连接应核对可信指纹；密钥变化不能直接删除记录跳过校验。

## 2. 准备产物

版本号用时间、组件和 Git 短提交组成，例如 `20261008-153000-web-a1b2c3d`，最多 40 位，仅字母、数字、下划线和连字符，首位为字母或数字。这个长度也保证加上服务器 `shared-frontend-` 前缀后可用于回滚命令。每次使用新版本，不覆盖旧包。

### 前端

按[代码来源](source.md)获取前端仓库指定提交，在识别出的前端模块中（当前前端仓库为 `code/frontend`），按锁文件安装依赖：有 `package-lock.json` 时 `npm.cmd ci`；其他锁文件使用项目指定工具，不顺手改锁文件。执行：

```powershell
npm.cmd run build
```

确认本次生成 `dist/index.html`，生产 API 使用同源 `/api`，没有依赖 Vite 开发代理。将压缩包生成在仓库 `work/runtime/highedu_deploy/<版本号>/`，命令形如：

```powershell
tar -czf "<产物目录>/frontend.tar.gz" -C dist .
tar -tzf "<产物目录>/frontend.tar.gz"
Get-FileHash -Algorithm SHA256 "<产物目录>/frontend.tar.gz"
Get-FileHash -Algorithm SHA256 dist/index.html
```

使用实际绝对产物路径替换 `<产物目录>` 并提前创建目录。包内必须直接包含 `index.html`，不能多包一层 `dist/`；不含符号链接或特殊文件，文件数小于 10000，包体和解压总量不超过 512 MiB。

### Java 后端

按[代码来源](source.md)获取 Java 仓库指定提交，在确认的 Maven 模块或聚合根目录构建；不要求协作者拥有原作者电脑上的目录。核对 Java 17 兼容性以及构建/测试配置。优先用项目 Maven Wrapper，否则用 Maven，标准构建为：

```text
mvn clean verify
```

先确认测试不会连接共享库执行写入；需要测试配置时使用项目已有隔离配置。检查实际可执行 Spring Boot JAR（含启动清单及应用 classes），排除 `.original`、sources、javadoc 包，不能靠多个 JAR 中的“第一个”判断。检查打包资源不含真实密码或密钥，将选定产物复制为本次产物目录内的 `edu-backend.jar` 并计算 SHA-256。已有 JAR 则核对来源、版本、运行时兼容性，不声称由本次源码构建。

## 3. 上传和发布

以下示例为前端，先在**本地终端**执行，密码由用户交互输入：

```powershell
ssh edu_developer@114.215.189.215 "mkdir /home/edu_developer/uploads/20261008-153000-web-a1b2c3d"
scp "<产物目录>/frontend.tar.gz" edu_developer@114.215.189.215:/home/edu_developer/uploads/20261008-153000-web-a1b2c3d/frontend.tar.gz
ssh edu_developer@114.215.189.215
```

也可通过 SFTP 上传至相同位置。目录已存在时先核对归属，使用新版本号，不覆盖未知文件。

再在**远端终端**执行并核对 SHA-256 与本地一致：

```bash
sha256sum /home/edu_developer/uploads/20261008-153000-web-a1b2c3d/frontend.tar.gz
sudo -n /usr/local/sbin/highedu-publish status
sudo -n /usr/local/sbin/highedu-publish frontend 20261008-153000-web-a1b2c3d
```

后端使用独立版本号，把上传文件换为 `edu-backend.jar`，发布操作换为 `backend`。后端发布会重启 `highedu-api.service`；前端发布保留当前 JAR，不主动重启后端。无需手动 reload Nginx。

## 4. 验证及回滚

```bash
sudo -n /usr/local/sbin/highedu-publish status
curl -fsS http://127.0.0.1/api/health
sudo -n /usr/bin/journalctl -u highedu-api.service -n 200 --no-pager
```

公网验证 `http://114.215.189.215/` 和 `/api/health`；将下载的首页计算 SHA-256，与本次 `dist/index.html` 对比，并检查它引用的资源。后端核对 `/opt/highedu/current/backend/edu-backend.jar` 的散列及启动日志；日志回报前隐去可能包含的凭据。

成功输出应有 `Published`、`Previous`、`Rollback`。发布失败先读状态和日志；前端页面/API 不兼容、权限菜单缺失需明确定位，不自动改数据库。

用户要求回滚时，使用已记录且经核对的**完整版本目录名**，不要只填上传版本号：

```bash
sudo -n /usr/local/sbin/highedu-publish rollback <完整版本目录名>
```

执行后重新验证首页、健康接口和业务。保留发布前基线；前后端分步发布的最终 `Previous` 是中间版本，不一定是整次发布前的版本。回滚不能撤销数据库变更。
