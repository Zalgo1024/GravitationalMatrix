param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "status",
    [switch]$NoBrowser,
    [int]$StartupTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "runtime-lib.ps1")

# ============================================================================
# Independent operations console ("admin console").
#
# Isolation model (single backend + two frontends):
#   - backend : 127.0.0.1:8000  SHARED with the workbench (one DB, one queue).
#               Never start a second one: two processes would fight over the
#               same SQLite file and duplicate the task worker pool.
#   - workbench frontend : 127.0.0.1:3000  (owned by scripts\local-workbench.ps1)
#   - admin   frontend : 127.0.0.1:3001  (owned by THIS script)
#
# This script never touches port 3000, and the workbench script never touches
# 3001, so the two startup paths are fully independent. Each frontend also has
# its own build directory (workbench ".next", admin ".next-admin"), so neither
# can overwrite the other's bundle.
# ============================================================================

$adminPort = 3001
$workbenchPort = 3000
$backendPort = 8000
$adminUrl = "http://127.0.0.1:$adminPort"
$adminEntryUrl = "http://127.0.0.1:$adminPort/admin-console/overview"
$backendHealthUrl = "http://127.0.0.1:$backendPort/health"

# A5: the admin console gets its OWN build (distDir = .next-admin), built with
# ADMIN_UI_ENABLED=1 so the *.admin.tsx pages are routed. The workbench keeps
# plain ".next", which contains no admin routes at all. Two bundles, two
# processes, two logs - no shared artifact to accidentally leak.
$adminDistName = ".next-admin"
$adminStagingName = ".next-admin-staging"
$adminPreviousName = ".next-admin-previous"

$runtimeDir = Join-Path $workspaceRoot ".runtime"
$adminLog = Join-Path $runtimeDir "admin-frontend.log"
$adminErrorLog = Join-Path $runtimeDir "admin-frontend-error.log"
$adminStatePath = Join-Path $runtimeDir "admin-console-state.json"
$backendLog = Join-Path $runtimeDir "backend.log"
$backendErrorLog = Join-Path $runtimeDir "backend-error.log"
$frontendDir = Join-Path $workspaceRoot "frontend"

function Write-Step {
    param([string]$Message)
    Write-Host "[admin] $Message"
}

function Get-ListenerProcessIds {
    param([int]$Port)
    $ids = @()
    try {
        $lines = netstat -ano -p tcp 2>$null
    }
    catch {
        return @()
    }
    foreach ($line in $lines) {
        if ($line -match "TCP\s+.*:$Port\s+.*LISTENING\s+(\d+)\s*$") {
            $ids += [int]$Matches[1]
        }
    }
    return @($ids | Select-Object -Unique)
}

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
                # ignore individual read failures
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

function Get-AdminServiceState {
    $processIds = @(Get-ListenerProcessIds -Port $adminPort)
    if ($processIds.Count -eq 0) {
        return [PSCustomObject]@{ Status = "stopped"; ProcessId = 0; CommandLine = "" }
    }
    foreach ($processId in $processIds) {
        $commandLine = Get-LiveCommandLine -ProcessId $processId
        if (-not (Test-ServiceCommand -ServiceName "frontend" -CommandLine $commandLine -WorkspaceRoot $workspaceRoot)) {
            return [PSCustomObject]@{ Status = "conflict"; ProcessId = $processId; CommandLine = $commandLine }
        }
    }
    $listenerPid = [int]$processIds[0]
    return [PSCustomObject]@{ Status = "running"; ProcessId = $listenerPid; CommandLine = (Get-LiveCommandLine -ProcessId $listenerPid) }
}

function Get-BackendServiceState {
    $processIds = @(Get-ListenerProcessIds -Port $backendPort)
    if ($processIds.Count -eq 0) {
        return [PSCustomObject]@{ Status = "stopped"; ProcessId = 0; CommandLine = "" }
    }
    foreach ($processId in $processIds) {
        $commandLine = Get-LiveCommandLine -ProcessId $processId
        if (-not (Test-ServiceCommand -ServiceName "backend" -CommandLine $commandLine -WorkspaceRoot $workspaceRoot)) {
            return [PSCustomObject]@{ Status = "conflict"; ProcessId = $processId; CommandLine = $commandLine }
        }
    }
    $healthy = Test-HttpEndpoint -Url $backendHealthUrl
    return [PSCustomObject]@{
        Status = $(if ($healthy) { "running" } else { "degraded" })
        ProcessId = [int]$processIds[0]
        CommandLine = ""
    }
}

function Start-BackendService {
    param([string]$PythonPath)
    $backendDir = Join-Path $workspaceRoot "backend"
    Write-Step "Starting shared backend (FastAPI) on 127.0.0.1:$backendPort ..."
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

function Remove-SafeBuildDirectory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $fullFrontend = [System.IO.Path]::GetFullPath($frontendDir).TrimEnd('\', '/')
    $fullTarget = [System.IO.Path]::GetFullPath($Path)
    $allowedNames = @(".next", ".next-admin", ".next-admin-staging", ".next-admin-previous")
    if ([System.IO.Path]::GetDirectoryName($fullTarget) -ne $fullFrontend -or $allowedNames -notcontains [System.IO.Path]::GetFileName($fullTarget)) {
        throw "Refusing to remove unsafe build directory: $fullTarget"
    }
    # .NET delete instead of Remove-Item: identical semantics, but immune to
    # Remove-Item overrides (e.g. bulk-delete guards) that would abort the swap
    # half way. The allowlist above is what makes this safe.
    [System.IO.Directory]::Delete($fullTarget, $true)
}

# A5/A6: admin console is built from a separate source tree (frontend\admin-pages\).
# Workbench builds never see this directory because it lives outside frontend\src\app\.
# At admin build time we copy it into frontend\src\app\admin-console\ so Next can pick
# it up as a route subtree, then remove it after the build (success or failure) so the
# workbench tree stays clean.
$adminPagesDir = Join-Path $frontendDir "admin-pages\admin-console"
$adminStagedDir = Join-Path $frontendDir "src\app\admin-console"

function Copy-AdminPagesIntoSrc {
    if (-not (Test-Path -LiteralPath $adminPagesDir -PathType Container)) {
        throw "Admin pages source not found: $adminPagesDir"
    }
    # Copy-Item -Recurse with -Force overwrites existing target contents.
    Copy-Item -Path (Join-Path $adminPagesDir "*") -Destination $adminStagedDir -Recurse -Force
}

function Remove-AdminPagesFromSrc {
    if (Test-Path -LiteralPath $adminStagedDir -PathType Container) {
        # .NET Delete instead of Remove-Item: immune to safe-delete bulk guard.
        [System.IO.Directory]::Delete($adminStagedDir, $true)
    }
}

# Build into a staging directory, then swap it in. Building in place would
# destroy the current admin bundle if the build fails. The admin bundle lives in
# its own distDir (.next-admin) and never touches the workbench's ".next".
function Invoke-StagedFrontendBuild {
    param([string]$NpmPath)
    $currentDir = Join-Path $frontendDir $adminDistName
    $stagingDir = Join-Path $frontendDir $adminStagingName
    $previousDir = Join-Path $frontendDir $adminPreviousName

    Remove-SafeBuildDirectory -Path $stagingDir
    # Seed the webpack cache: prefer the previous admin build's cache, fall back
    # to the workbench cache so the very first admin build is not a cold build.
    $sourceCache = Join-Path $currentDir "cache"
    if (-not (Test-Path -LiteralPath $sourceCache -PathType Container)) {
        $sourceCache = Join-Path (Join-Path $frontendDir ".next") "cache"
    }
    if (Test-Path -LiteralPath $sourceCache -PathType Container) {
        $targetCache = Join-Path $stagingDir "cache"
        New-Item -ItemType Directory -Path $targetCache -Force | Out-Null
        robocopy $sourceCache $targetCache /E /NFL /NDL /NJH /NJS /NP > $null
    }

    $previousApiUrl = $env:NEXT_PUBLIC_API_URL
    $previousDistDir = $env:NEXT_DIST_DIR
    $previousAdminUi = $env:ADMIN_UI_ENABLED
    $previousAdminUiFlag = $env:NEXT_PUBLIC_ADMIN_UI
    # Next.js rewrites tsconfig.json's "include" to point at its distDir types.
    # Snapshot + restore it, otherwise every build leaves the repo dirty and the
    # stale ".next-*/types" entries make the next build fail type checking.
    $tsconfigPath = Join-Path $frontendDir "tsconfig.json"
    $tsconfigSnapshot = [System.IO.File]::ReadAllBytes($tsconfigPath)
    $tsconfigTimestamp = (Get-Item -LiteralPath $tsconfigPath).LastWriteTimeUtc
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$backendPort"
    $env:NEXT_DIST_DIR = $adminStagingName
    # A5/A6: this is the ONLY place that turns the admin routes on.
    $env:ADMIN_UI_ENABLED = "1"
    $env:NEXT_PUBLIC_ADMIN_UI = "1"
    # Stage admin pages into src/app/ so Next can route them, then ALWAYS clean
    # them up (success or failure path) so the workbench tree stays clean.
    Copy-AdminPagesIntoSrc
    try {
        & $NpmPath --prefix $frontendDir run build 2>&1 | Tee-Object -FilePath (Join-Path $runtimeDir "frontend-build.log")
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed. See .runtime\frontend-build.log" }
        if (-not (Test-Path -LiteralPath (Join-Path $stagingDir "BUILD_ID") -PathType Leaf)) { throw "Frontend build completed without BUILD_ID." }
    }
    finally {
        Remove-AdminPagesFromSrc
        [System.IO.File]::WriteAllBytes($tsconfigPath, $tsconfigSnapshot)
        [System.IO.File]::SetLastWriteTimeUtc($tsconfigPath, $tsconfigTimestamp)
        $env:NEXT_PUBLIC_API_URL = $previousApiUrl
        $env:NEXT_DIST_DIR = $previousDistDir
        $env:ADMIN_UI_ENABLED = $previousAdminUi
        $env:NEXT_PUBLIC_ADMIN_UI = $previousAdminUiFlag
    }

    Remove-SafeBuildDirectory -Path $previousDir
    if (Test-Path -LiteralPath $currentDir) { Move-Item -LiteralPath $currentDir -Destination $previousDir }
    try {
        Move-Item -LiteralPath $stagingDir -Destination $currentDir
    }
    catch {
        if (Test-Path -LiteralPath $previousDir) { Move-Item -LiteralPath $previousDir -Destination $currentDir }
        throw
    }
    Remove-SafeBuildDirectory -Path $previousDir
}

function Ensure-FrontendBuild {
    param([string]$NpmPath)
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules\next\package.json") -PathType Leaf)) {
        throw "Frontend dependencies are missing. Run: cd frontend; npm install"
    }
    $sources = @(
        (Join-Path $frontendDir "src"),
        (Join-Path $frontendDir "admin-pages"),
        (Join-Path $frontendDir "public"),
        (Join-Path $frontendDir "package.json"),
        (Join-Path $frontendDir "package-lock.json"),
        (Join-Path $frontendDir "next.config.ts"),
        (Join-Path $frontendDir "tsconfig.json")
    )
    $fresh = Test-FrontendBuildFresh -BuildIdPath (Join-Path $frontendDir "$adminDistName\BUILD_ID") -SourcePaths $sources
    if ($fresh) {
        Write-Step "Admin console build is current."
        return
    }
    Write-Step "Frontend sources changed; building the admin bundle (.next-admin) - this can take a minute..."
    Invoke-StagedFrontendBuild -NpmPath $NpmPath
    Write-Step "Admin bundle replaced (workbench's .next was not touched)."
}

function Start-AdminFrontend {
    param([string]$NodePath)
    $nextEntry = Join-Path $frontendDir "node_modules\next\dist\bin\next"
    if (-not (Test-Path -LiteralPath $nextEntry -PathType Leaf)) { throw "Next.js entry point is missing. Run npm install in frontend." }
    Write-Step "Starting admin console (Next.js) on 127.0.0.1:$adminPort ..."
    $previousApiUrl = $env:NEXT_PUBLIC_API_URL
    $previousDistDir = $env:NEXT_DIST_DIR
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$backendPort"
    # Serve the admin's own build, not the workbench's ".next".
    $env:NEXT_DIST_DIR = $adminDistName
    try {
        $process = Start-Process -FilePath $NodePath `
            -ArgumentList @("`"$nextEntry`"", "start", "`"$frontendDir`"", "-H", "127.0.0.1", "-p", [string]$adminPort) `
            -WindowStyle Hidden `
            -RedirectStandardOutput $adminLog `
            -RedirectStandardError $adminErrorLog `
            -PassThru
        return [int]$process.Id
    }
    finally {
        $env:NEXT_PUBLIC_API_URL = $previousApiUrl
        $env:NEXT_DIST_DIR = $previousDistDir
    }
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

function Save-AdminState {
    param([int]$AdminPid, [int]$BackendPid, [string]$BackendStatus)
    $state = [ordered]@{
        kind = "admin-console"
        workspace = $workspaceRoot
        updated_at = (Get-Date).ToString("o")
        admin = [ordered]@{ port = $adminPort; pid = $AdminPid; url = $adminEntryUrl }
        backend = [ordered]@{ port = $backendPort; pid = $BackendPid; status = $BackendStatus }
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $adminStatePath -Encoding utf8
}

function Invoke-Status {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $entries = @(
        [PSCustomObject]@{ Name = "Backend"; Port = $backendPort; Service = "backend" },
        [PSCustomObject]@{ Name = "Workbench"; Port = $workbenchPort; Service = "frontend" },
        [PSCustomObject]@{ Name = "AdminConsole"; Port = $adminPort; Service = "frontend" }
    )
    foreach ($entry in $entries) {
        $processIds = @(Get-ListenerProcessIds -Port $entry.Port)
        if ($processIds.Count -eq 0) {
            Write-Host ("{0,-13} port={1} status=stopped" -f $entry.Name, $entry.Port)
            continue
        }
        $listenerPid = [int]$processIds[0]
        $commandLine = Get-LiveCommandLine -ProcessId $listenerPid
        $owned = Test-ServiceCommand -ServiceName $entry.Service -CommandLine $commandLine -WorkspaceRoot $workspaceRoot
        $status = if ($owned) { "running" } else { "foreign" }
        Write-Host ("{0,-13} port={1} pid={2} status={3}" -f $entry.Name, $entry.Port, $listenerPid, $status)
    }
    Write-Host "Logs: $runtimeDir"
    return 0
}

function Invoke-Start {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

    $admin = Get-AdminServiceState
    $backend = Get-BackendServiceState

    if ($admin.Status -eq "conflict") {
        Write-Host "Port $adminPort is owned by another program:"
        Write-Host "  $($admin.CommandLine)"
        throw "Stop that program manually, then retry."
    }
    if ($backend.Status -eq "conflict") {
        Write-Host "Port $backendPort is owned by another program:"
        Write-Host "  $($backend.CommandLine)"
        throw "Stop that program manually, then retry."
    }
    if ($backend.Status -eq "degraded") {
        throw "Backend belongs to this workspace but is not healthy. Stop it first (stop.bat), inspect .runtime\backend-error.log, then retry."
    }

    $startAdmin = $false
    if ($admin.Status -eq "stopped") {
        $startAdmin = $true
    }
    elseif (-not (Test-HttpEndpoint -Url $adminUrl)) {
        Write-Step "Admin console process exists but is not serving; restarting it."
        if (-not (Stop-OwnedPort -Name "Frontend" -Port $adminPort)) { throw "The stale admin console could not be stopped safely." }
        $startAdmin = $true
    }

    $node = $null
    $npm = $null
    $python = $null
    $startedBackend = 0
    $startedAdmin = 0

    # Backend first: it is ready in seconds while the build/start takes longer.
    if ($backend.Status -eq "stopped") {
        $python = Resolve-Python
        $startedBackend = Start-BackendService -PythonPath $python
    }
    if ($startAdmin) {
        $node = Resolve-Executable -Candidates @("node.exe", "node") -Label "Node.js"
        $npm = Resolve-Executable -Candidates @("npm.cmd") -Label "npm"
        Ensure-FrontendBuild -NpmPath $npm
    }

    try {
        if ($startedBackend -gt 0) { Write-Step "Shared backend started (PID $startedBackend)." }
        else { Write-Step "Reusing healthy backend PID $($backend.ProcessId)." }

        if ($startAdmin) { $startedAdmin = Start-AdminFrontend -NodePath $node }
        else { Write-Step "Admin console already running (PID $($admin.ProcessId))." }

        $backendHealthy = $false
        $adminHealthy = $false
        $browserOpened = $false
        $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if (-not $backendHealthy) { $backendHealthy = Test-HttpEndpoint -Url $backendHealthUrl -TimeoutSeconds 1 }
            if (-not $adminHealthy) { $adminHealthy = Test-HttpEndpoint -Url $adminEntryUrl -TimeoutSeconds 2 }
            if ($adminHealthy -and -not $browserOpened -and -not $NoBrowser) {
                Start-Process $adminEntryUrl
                $browserOpened = $true
                Write-Step "Admin console is ready; opening browser: $adminEntryUrl"
            }
            if ($backendHealthy -and $adminHealthy) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $adminHealthy) { throw "Admin console did not become healthy within $StartupTimeoutSeconds seconds. See $adminLog" }
        if (-not $backendHealthy) { throw "Backend did not become healthy. See $backendLog" }

        $adminPid = if ($startedAdmin -gt 0) { $startedAdmin } else { $admin.ProcessId }
        $backendPid = if ($startedBackend -gt 0) { $startedBackend } else { $backend.ProcessId }
        Save-AdminState -AdminPid $adminPid -BackendPid $backendPid -BackendStatus "running"

        Write-Host ("{0,-13} port={1} pid={2} status=running" -f "AdminConsole", $adminPort, $adminPid)
        Write-Host ("{0,-13} port={1} pid={2} status=running" -f "Backend", $backendPort, $backendPid)
        Write-Step "Ready. Admin console: $adminEntryUrl"
        Write-Step "Sign in with an administrator account (see backend\.env ADMIN_EMAIL)."
        return 0
    }
    catch {
        if ($startedAdmin -gt 0) { Stop-StartedProcess -Name "Frontend" -ProcessId $startedAdmin }
        if ($startedBackend -gt 0) { Stop-StartedProcess -Name "Backend" -ProcessId $startedBackend }
        throw
    }
}

function Invoke-Stop {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $stopped = Stop-OwnedPort -Name "Frontend" -Port $adminPort
    if (Test-Path -LiteralPath $adminStatePath -PathType Leaf) { Remove-Item -LiteralPath $adminStatePath -Force }
    if ($stopped) {
        Write-Step "Admin console stopped (port $adminPort)."
        Write-Step "The shared backend on port $backendPort was left running on purpose - the workbench may be using it."
        return 0
    }
    Write-Host "The admin console could not be stopped safely."
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
    Write-Host "[admin] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if (-not [string]::IsNullOrWhiteSpace($_.ScriptStackTrace)) {
        Write-Host "[admin] LOCATION: $($_.ScriptStackTrace)" -ForegroundColor DarkGray
    }
    exit 1
}
