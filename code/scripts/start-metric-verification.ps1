param([int]$Port = 8010)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$codeRoot = Join-Path $repoRoot 'code'
$pythonPath = Join-Path $codeRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先为 code/backend/.venv 安装 requirements-metric-verification.txt' }
if (-not (Test-Path -LiteralPath (Join-Path $codeRoot 'backend\.env.metric-verification'))) { throw '请从 .env.metric-verification.example 建立本地配置。' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $Port 已占用，请核对现有服务；本脚本不会停止其他进程。" }
$runtimePath = Join-Path $repoRoot 'work\runtime\highedu-start'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$started = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.metric_verification.app:app','--host','127.0.0.1','--port',"$Port",'--no-access-log') -WorkingDirectory $codeRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'metric-verification.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'metric-verification.stderr.log')
@{ pid = $started.Id; port = $Port; cwd = $codeRoot; startedAt = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'metric-verification.json') -Encoding UTF8
Write-Output "指标核验服务 PID=$($started.Id)，http://127.0.0.1:$Port/health；未执行数据库迁移。"
