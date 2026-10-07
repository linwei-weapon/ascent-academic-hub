param([int]$Port = 8011)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$codeRoot = Join-Path $repoRoot 'code'
$pythonPath = Join-Path $codeRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先安装专家资源服务依赖' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $Port 已占用；请核对服务归属。" }
$runtimePath = Join-Path $repoRoot 'work\runtime\highedu-start'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
Push-Location $codeRoot
try {
    & $pythonPath -m backend.expert_resources.migrate
    if ($LASTEXITCODE -ne 0) { throw '专家资源库初始化失败' }
} finally { Pop-Location }
$started = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.expert_resources.app:app','--host','127.0.0.1','--port',"$Port",'--no-access-log') -WorkingDirectory $codeRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'expert-resources.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'expert-resources.stderr.log')
@{pid=$started.Id;port=$Port;cwd=$codeRoot;startedAt=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'expert-resources.json') -Encoding UTF8
Write-Output "专家资源服务 PID=$($started.Id)，http://127.0.0.1:$Port/health；业务库只读，本地控制库已幂等初始化。"
