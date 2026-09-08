param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "status",
    [switch]$NoBrowser,
    [int]$StartupTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-lib.ps1")

$frontendPort = 3000
$backendPort = 8000
$frontendUrl = "http://127.0.0.1:3000"
$backendUrl = "http://127.0.0.1:8000/health"
$runtimeDir = Join-Path $workspaceRoot ".runtime"
$statePath = Join-Path $runtimeDir "workbench-state.json"
$backendLog = Join-Path $runtimeDir "backend.log"
$backendErrorLog = Join-Path $runtimeDir "backend-error.log"
$frontendLog = Join-Path $runtimeDir "frontend.log"
$frontendErrorLog = Join-Path $runtimeDir "frontend-error.log"
$frontendDir = Join-Path $workspaceRoot "frontend"
$currentBuildDir = Join-Path $frontendDir ".next"
$stagingBuildDir = Join-Path $frontendDir ".next-staging"
$previousBuildDir = Join-Path $frontendDir ".next-previous"

function Write-Step {
    param([string]$Message)
    Write-Host "[workbench] $Message"
}

function Get-ListenerProcessIds {
    param([int]$Port)
    # 用 netstat 解析监听端口 → PID（Get-NetTCPConnection 在本机实测单次 2s+，太慢；
    # netstat 实测 <0.1s，同一信息）
    $ids = @()
    try {
        $lines = netstat -ano -p tcp 2>$null
    }
    catch {
        return @()
    }
    foreach ($line in $lines) {
        # 行格式: TCP    127.0.0.1:3000    0.0.0.0:0    LISTENING    45952
        # (IPv6: [::]:3000 同样含 ":3000")
        if ($line -match "TCP\s+.*:$Port\s+.*LISTENING\s+(\d+)\s*$") {
            $ids += [int]$Matches[1]
        }
    }
    return @($ids | Select-Object -Unique)
}

# 进程 CommandLine 批量缓存：Get-CimInstance Win32_Process 逐条查询慢（单条 ~0.35s），
# 首次调用时批量拉一次全量映射（~0.36s），后续命中缓存，显著加快多次状态探测。
$script:CommandLineCache = $null

function Get-LiveCommandLine {
    param([int]$ProcessId)
    if ($null -eq $script:CommandLineCache) {
        $script:CommandLineCache = @{}
        foreach ($proc in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            try {
                $script:CommandLineCache[[int]$proc.ProcessId] = [string]$proc.CommandLine
            }
            catch {
                # 忽略个别进程读取失败
            }
        }
    }
    $cached = $script:CommandLineCache[[int]$ProcessId]
    if ($null -eq $cached) { return "" }
    return [string]$cached
}

function Test-HttpEndpoint {
    param([string]$Url, [int]$TimeoutSeconds = 3)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Get-ServiceState {
    param([string]$Name, [int]$Port, [string]$HealthUrl)
    $processIds = @(Get-ListenerProcessIds -Port $Port)
    if ($processIds.Count -eq 0) {
        return [PSCustomObject]@{ Name = $Name; Port = $Port; Status = "stopped"; ProcessId = 0; CommandLine = ""; Healthy = $false }
    }

    foreach ($processId in $processIds) {
        $commandLine = Get-LiveCommandLine -ProcessId $processId
        $owned = Test-ServiceCommand -ServiceName $Name.ToLowerInvariant() -CommandLine $commandLine -WorkspaceRoot $workspaceRoot
        if (-not $owned) {
            return [PSCustomObject]@{ Name = $Name; Port = $Port; Status = "conflict"; ProcessId = $processId; CommandLine = $commandLine; Healthy = $false }
        }
    }

    $listenerPid = [int]$processIds[0]
    $healthy = Test-HttpEndpoint -Url $HealthUrl
    return [PSCustomObject]@{
        Name = $Name
        Port = $Port
        Status = $(if ($healthy) { "running" } else { "degraded" })
        ProcessId = $listenerPid
        CommandLine = Get-LiveCommandLine -ProcessId $listenerPid
        Healthy = $healthy
    }
}

function Show-ServiceState {
    param($Service)
    $pidLabel = if ($Service.ProcessId -gt 0) { [string]$Service.ProcessId } else { "-" }
    Write-Host ("{0,-9} port={1} pid={2} status={3}" -f $Service.Name, $Service.Port, $pidLabel, $Service.Status)
    if ($Service.Status -eq "conflict") {
        Write-Host "  foreign command: $($Service.CommandLine)"
    }
}

function Resolve-Executable {
    param([string[]]$Candidates, [string]$Label)
    foreach ($candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return (Resolve-Path -LiteralPath $candidate).Path }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) { return $command.Source }
    }
    throw "$Label was not found. Install it or add it to PATH."
}

function Resolve-Python {
    $venvPython = Join-Path $workspaceRoot "backend\.venv\Scripts\python.exe"
    $python = Resolve-Executable -Candidates @($venvPython, "python.exe", "python") -Label "Python"
    & $python -c "import uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Python cannot import uvicorn. Install backend dependencies before starting."
    }
    return $python
}

function Test-BuildFresh {
    $sources = @(
        (Join-Path $frontendDir "src"),
        (Join-Path $frontendDir "public"),
        (Join-Path $frontendDir "package.json"),
        (Join-Path $frontendDir "package-lock.json"),
        (Join-Path $frontendDir "next.config.ts"),
        (Join-Path $frontendDir "tsconfig.json"),
        (Join-Path $frontendDir ".env"),
        (Join-Path $frontendDir ".env.local"),
        (Join-Path $frontendDir ".env.production"),
        (Join-Path $frontendDir ".env.production.local")
    )
    return Test-FrontendBuildFresh -BuildIdPath (Join-Path $frontendDir ".next\BUILD_ID") -SourcePaths $sources
}

function Invoke-FrontendBuild {
    param([string]$NpmPath, [string]$DistDir = ".next", [switch]$Force)
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules\next\package.json") -PathType Leaf)) {
        throw "Frontend dependencies are missing. Run: cd frontend; npm install"
    }
    if (-not $Force -and $DistDir -eq ".next" -and (Test-BuildFresh)) {
        Write-Step "Frontend production build is current."
        return
    }

    Write-Step "Frontend sources changed; creating a production build..."
    $previousApiUrl = $env:NEXT_PUBLIC_API_URL
    $previousDistDir = $env:NEXT_DIST_DIR
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000"
    $env:NEXT_DIST_DIR = $DistDir
    $targetBuildDir = Join-Path $frontendDir $DistDir
    $tsconfigPath = Join-Path $frontendDir "tsconfig.json"
    $tsconfigSnapshot = [System.IO.File]::ReadAllBytes($tsconfigPath)
    $tsconfigTimestamp = (Get-Item -LiteralPath $tsconfigPath).LastWriteTimeUtc
    if ($DistDir -ne ".next") { Remove-SafeBuildDirectory -Path $targetBuildDir }
    # Staging 构建前，用上次生产构建的 webpack 缓存播种（robocopy 几秒），
    # 否则 staging 每次从零编译（冷构建 1-2 分钟 → 增量构建约十几秒）。
    if ($DistDir -ne ".next") {
        $sourceCache = Join-Path $frontendDir ".next\cache"
        if (Test-Path -LiteralPath $sourceCache -PathType Container) {
            $targetCache = Join-Path $targetBuildDir "cache"
            New-Item -ItemType Directory -Path $targetCache -Force | Out-Null
            robocopy $sourceCache $targetCache /E /NFL /NDL /NJH /NJS /NP > $null
            if ($LASTEXITCODE -ge 8) {
                Write-Step "Webpack cache seeding failed (robocopy exit $LASTEXITCODE); building cold instead."
            }
        }
    }
    try {
        & $NpmPath --prefix $frontendDir run build 2>&1 | Tee-Object -FilePath (Join-Path $runtimeDir "frontend-build.log")
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed. See .runtime\frontend-build.log" }
        if (-not (Test-Path -LiteralPath (Join-Path $targetBuildDir "BUILD_ID") -PathType Leaf)) { throw "Frontend build completed without BUILD_ID." }
    }
    finally {
        [System.IO.File]::WriteAllBytes($tsconfigPath, $tsconfigSnapshot)
        [System.IO.File]::SetLastWriteTimeUtc($tsconfigPath, $tsconfigTimestamp)
        $env:NEXT_PUBLIC_API_URL = $previousApiUrl
        $env:NEXT_DIST_DIR = $previousDistDir
    }
}

function Remove-SafeBuildDirectory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $fullFrontend = [System.IO.Path]::GetFullPath($frontendDir).TrimEnd('\', '/')
    $fullTarget = [System.IO.Path]::GetFullPath($Path)
    $allowedNames = @(".next", ".next-staging", ".next-previous")
    if ([System.IO.Path]::GetDirectoryName($fullTarget) -ne $fullFrontend -or $allowedNames -notcontains [System.IO.Path]::GetFileName($fullTarget)) {
        throw "Refusing to remove unsafe build directory: $fullTarget"
    }
    Remove-Item -LiteralPath $fullTarget -Recurse -Force
}

function Promote-FrontendBuild {
    Remove-SafeBuildDirectory -Path $previousBuildDir
    if (Test-Path -LiteralPath $currentBuildDir) { Move-Item -LiteralPath $currentBuildDir -Destination $previousBuildDir }
    try {
        Move-Item -LiteralPath $stagingBuildDir -Destination $currentBuildDir
    }
    catch {
        if (Test-Path -LiteralPath $previousBuildDir) { Move-Item -LiteralPath $previousBuildDir -Destination $currentBuildDir }
        throw
    }
}

function Restore-FrontendBuild {
    if (-not (Test-Path -LiteralPath $previousBuildDir)) { return $false }
    Remove-SafeBuildDirectory -Path $currentBuildDir
    Move-Item -LiteralPath $previousBuildDir -Destination $currentBuildDir
    return $true
}

function Start-BackendService {
    param([string]$PythonPath)
    $backendDir = Join-Path $workspaceRoot "backend"
    Write-Step "Starting FastAPI on 127.0.0.1:$backendPort..."
    $previousEngineDir = $env:ENGINE_DIR
    $env:ENGINE_DIR = $workspaceRoot
    try {
        $process = Start-Process -FilePath $PythonPath `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--app-dir", "`"$backendDir`"", "--host", "127.0.0.1", "--port", [string]$backendPort) `
            -WindowStyle Hidden `
            -RedirectStandardOutput $backendLog `
            -RedirectStandardError $backendErrorLog `
            -PassThru
        return [int]$process.Id
    }
    finally {
        $env:ENGINE_DIR = $previousEngineDir
    }
}

function Start-FrontendService {
    param([string]$NodePath)
    $nextEntry = Join-Path $workspaceRoot "frontend\node_modules\next\dist\bin\next"
    if (-not (Test-Path -LiteralPath $nextEntry -PathType Leaf)) { throw "Next.js entry point is missing. Run npm install in frontend." }
    Write-Step "Starting Next.js production server on 127.0.0.1:$frontendPort..."
    $previousApiUrl = $env:NEXT_PUBLIC_API_URL
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000"
    try {
        $process = Start-Process -FilePath $NodePath `
            -ArgumentList @("`"$nextEntry`"", "start", "`"$frontendDir`"", "-H", "127.0.0.1", "-p", [string]$frontendPort) `
            -WindowStyle Hidden `
            -RedirectStandardOutput $frontendLog `
            -RedirectStandardError $frontendErrorLog `
            -PassThru
        return [int]$process.Id
    }
    finally {
        $env:NEXT_PUBLIC_API_URL = $previousApiUrl
    }
}

function Wait-ForEndpoint {
    param([string]$Name, [string]$Url, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpEndpoint -Url $Url) { return $true }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "$Name did not become healthy within $TimeoutSeconds seconds."
    return $false
}

function Save-RuntimeState {
    param($Backend, $Frontend)
    $state = [ordered]@{
        workspace = $workspaceRoot
        updated_at = (Get-Date).ToString("o")
        backend = [ordered]@{ port = $Backend.Port; pid = $Backend.ProcessId; status = $Backend.Status }
        frontend = [ordered]@{ port = $Frontend.Port; pid = $Frontend.ProcessId; status = $Frontend.Status }
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
}

function Invoke-Status {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $backend = Get-ServiceState -Name "Backend" -Port $backendPort -HealthUrl $backendUrl
    $frontend = Get-ServiceState -Name "Frontend" -Port $frontendPort -HealthUrl $frontendUrl
    Show-ServiceState -Service $backend
    Show-ServiceState -Service $frontend
    Write-Host "Logs: $runtimeDir"
    if ($backend.Status -eq "running" -and $frontend.Status -eq "running") { return 0 }
    return 1
}

function Invoke-Start {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $backend = Get-ServiceState -Name "Backend" -Port $backendPort -HealthUrl $backendUrl
    $frontend = Get-ServiceState -Name "Frontend" -Port $frontendPort -HealthUrl $frontendUrl

    foreach ($service in @($backend, $frontend)) {
        if ($service.Status -eq "conflict") {
            Show-ServiceState -Service $service
            throw "Port $($service.Port) is owned by another program. Stop it manually, then retry."
        }
        if ($service.Status -eq "degraded") {
            Show-ServiceState -Service $service
            throw "$($service.Name) belongs to this workspace but is not healthy. Run stop.bat, inspect logs, then retry."
        }
    }

    $frontendAction = Get-FrontendAction -ServiceStatus $frontend.Status -BuildFresh (Test-BuildFresh)
    $node = $null
    $npm = $null
    $stagedUpgrade = $false
    if ($frontendAction -eq "restart") {
        Write-Step "Frontend build is stale; building a replacement before restart."
        $node = Resolve-Executable -Candidates @("node.exe", "node") -Label "Node.js"
        $npm = Resolve-Executable -Candidates @("npm.cmd") -Label "npm"
        Invoke-FrontendBuild -NpmPath $npm -DistDir ".next-staging" -Force
        if (-not (Stop-OwnedPort -Name "Frontend" -Port $frontendPort)) { throw "Stale frontend could not be stopped safely." }
        try {
            Promote-FrontendBuild
        }
        catch {
            Write-Step "Restarting previous frontend after build switch failure."
            $restoredFrontend = Start-FrontendService -NodePath $node
            if (-not (Wait-ForEndpoint -Name "Previous frontend" -Url $frontendUrl -TimeoutSeconds 30)) {
                Stop-StartedProcess -Name "Frontend" -ProcessId $restoredFrontend
            }
            throw
        }
        $stagedUpgrade = $true
        $frontend = Get-ServiceState -Name "Frontend" -Port $frontendPort -HealthUrl $frontendUrl
        $frontendAction = "start"
    }

    # 后端先行：后端 3-5 秒就能就绪，前端构建要 1-2 分钟——
    # 先把后端拉起来，构建期间 API 已可用，总启动时间 ≈ max(后端, 前端) 而不是两者之和。
    $python = $null
    $startedBackend = 0
    $startedFrontend = 0
    if ($backend.Status -eq "stopped") {
        $python = Resolve-Python
        $startedBackend = Start-BackendService -PythonPath $python
    }
    if ($frontendAction -eq "start") {
        if ($null -eq $node) { $node = Resolve-Executable -Candidates @("node.exe", "node") -Label "Node.js" }
        if ($null -eq $npm) { $npm = Resolve-Executable -Candidates @("npm.cmd") -Label "npm" }
        if (-not $stagedUpgrade) { Invoke-FrontendBuild -NpmPath $npm }
    }

    try {
        if ($startedBackend -gt 0) { Write-Step "Backend started first (PID $startedBackend); frontend build/start continues while API warms up." }
        else { Write-Step "Reusing healthy backend PID $($backend.ProcessId)." }
        if ($frontendAction -eq "start") { $startedFrontend = Start-FrontendService -NodePath $node } else { Write-Step "Reusing healthy frontend PID $($frontend.ProcessId)." }

        $backendHealthy = $false
        $frontendHealthy = $false
        $browserOpened = $false
        # 前后端并行健康等待（短超时轮询，互不阻塞）；
        # 前端一就绪就立即打开浏览器，不必等后端——用户看到页面的时间 ≈ 前端就绪时间。
        $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if (-not $backendHealthy) { $backendHealthy = Test-HttpEndpoint -Url $backendUrl -TimeoutSeconds 1 }
            if (-not $frontendHealthy) { $frontendHealthy = Test-HttpEndpoint -Url $frontendUrl -TimeoutSeconds 1 }
            if ($frontendHealthy -and -not $browserOpened -and -not $NoBrowser) {
                Start-Process $frontendUrl
                $browserOpened = $true
                Write-Step "Frontend is ready; opening browser: $frontendUrl"
            }
            if ($backendHealthy -and $frontendHealthy) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not ($backendHealthy -and $frontendHealthy)) {
            throw "Workbench startup failed. Inspect logs in $runtimeDir"
        }

        # 用循环内的健康结果构造最终状态（PID 以实际启动为准），
        # 不再重复探测端口/进程，省去两轮 Get-ServiceState 的耗时。
        $backendPid = if ($startedBackend -gt 0) { $startedBackend } else { $backend.ProcessId }
        $frontendPid = if ($startedFrontend -gt 0) { $startedFrontend } else { $frontend.ProcessId }
        $backendFinal = [PSCustomObject]@{
            Name = "Backend"; Port = $backendPort; Status = "running"
            ProcessId = $backendPid; CommandLine = ""; Healthy = $backendHealthy
        }
        $frontendFinal = [PSCustomObject]@{
            Name = "Frontend"; Port = $frontendPort; Status = "running"
            ProcessId = $frontendPid; CommandLine = ""; Healthy = $frontendHealthy
        }
        Save-RuntimeState -Backend $backendFinal -Frontend $frontendFinal
        Show-ServiceState -Service $backendFinal
        Show-ServiceState -Service $frontendFinal
        if ($stagedUpgrade) { Remove-SafeBuildDirectory -Path $previousBuildDir }
    }
    catch {
        if ($startedFrontend -gt 0) { Stop-StartedProcess -Name "Frontend" -ProcessId $startedFrontend }
        if ($startedBackend -gt 0) { Stop-StartedProcess -Name "Backend" -ProcessId $startedBackend }
        if ($stagedUpgrade -and (Restore-FrontendBuild)) {
            Write-Step "Restored the previous frontend build after startup failure."
            $restoredFrontend = Start-FrontendService -NodePath $node
            if (-not (Wait-ForEndpoint -Name "Restored frontend" -Url $frontendUrl -TimeoutSeconds 30)) {
                Stop-StartedProcess -Name "Frontend" -ProcessId $restoredFrontend
            }
        }
        throw
    }
    Write-Step "Workbench is ready: $frontendUrl"
    return 0
}

function Stop-StartedProcess {
    param([string]$Name, [int]$ProcessId)
    $commandLine = Get-LiveCommandLine -ProcessId $ProcessId
    if ([string]::IsNullOrWhiteSpace($commandLine)) { return }
    if (-not (Test-ServiceCommand -ServiceName $Name.ToLowerInvariant() -CommandLine $commandLine -WorkspaceRoot $workspaceRoot)) {
        Write-Host "Refusing to clean up unverified $Name PID $ProcessId."
        return
    }
    Write-Step "Cleaning up failed $Name PID $ProcessId..."
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-OwnedPort {
    param([string]$Name, [int]$Port)
    $processIds = @(Get-ListenerProcessIds -Port $Port)
    if ($processIds.Count -eq 0) {
        Write-Step "$Name is already stopped."
        return $true
    }

    foreach ($processId in $processIds) {
        $commandLine = Get-LiveCommandLine -ProcessId $processId
        if (-not (Test-ServiceCommand -ServiceName $Name.ToLowerInvariant() -CommandLine $commandLine -WorkspaceRoot $workspaceRoot)) {
            Write-Host "Refusing to stop foreign PID $processId on port $Port."
            Write-Host "  command: $commandLine"
            return $false
        }
    }

    foreach ($processId in $processIds) {
        Write-Step "Stopping $Name PID $processId..."
        Stop-Process -Id $processId -Force -ErrorAction Stop
    }
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-ListenerProcessIds -Port $Port).Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Invoke-Stop {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $frontendStopped = Stop-OwnedPort -Name "Frontend" -Port $frontendPort
    $backendStopped = Stop-OwnedPort -Name "Backend" -Port $backendPort
    if (Test-Path -LiteralPath $statePath -PathType Leaf) { Remove-Item -LiteralPath $statePath -Force }
    if ($frontendStopped -and $backendStopped) {
        Write-Step "Workbench stopped."
        return 0
    }
    Write-Host "One or more services could not be stopped safely."
    return 1
}

try {
    $exitCode = switch ($Action) {
        "start" { Invoke-Start }
        "stop" { Invoke-Stop }
        "status" { Invoke-Status }
    }
    exit $exitCode
}
catch {
    Write-Host "[workbench] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if (-not [string]::IsNullOrWhiteSpace($_.ScriptStackTrace)) {
        Write-Host "[workbench] LOCATION: $($_.ScriptStackTrace)" -ForegroundColor DarkGray
    }
    exit 1
}
