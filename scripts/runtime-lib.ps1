Set-StrictMode -Version Latest

function Test-WorkspaceCommand {
    [CmdletBinding()]
    param(
        [AllowEmptyString()][string]$CommandLine,
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $normalizedRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot).TrimEnd('\', '/')
    $searchFrom = 0
    while ($searchFrom -lt $CommandLine.Length) {
        $matchAt = $CommandLine.IndexOf($normalizedRoot, $searchFrom, [System.StringComparison]::OrdinalIgnoreCase)
        if ($matchAt -lt 0) { return $false }
        $afterMatch = $matchAt + $normalizedRoot.Length
        if ($afterMatch -ge $CommandLine.Length) { return $true }
        $nextCharacter = $CommandLine[$afterMatch]
        if ($nextCharacter -eq '\' -or $nextCharacter -eq '/' -or $nextCharacter -eq '"' -or $nextCharacter -eq "'") {
            return $true
        }
        $searchFrom = $afterMatch
    }
    return $false
}

function Get-PortDecision {
    [CmdletBinding()]
    param(
        [int]$ListenerPid,
        [AllowEmptyString()][string]$CommandLine,
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot
    )

    if ($ListenerPid -le 0) { return "free" }
    if (Test-WorkspaceCommand -CommandLine $CommandLine -WorkspaceRoot $WorkspaceRoot) { return "reuse" }
    return "conflict"
}

function Test-ServiceCommand {
    [CmdletBinding()]
    param(
        [ValidateSet("backend", "frontend")][string]$ServiceName,
        [AllowEmptyString()][string]$CommandLine,
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot
    )

    if ($ServiceName -eq "frontend") {
        $nextEntry = [regex]::Escape((Join-Path $WorkspaceRoot "frontend\node_modules\next\dist\bin\next"))
        $frontendDir = [regex]::Escape((Join-Path $WorkspaceRoot "frontend"))
        $nodeExecutable = '(?:"[^"]*node(?:\.exe)?"|[^\s"]*node(?:\.exe)?)'
        $projectArgument = '(?:\s+["'']?' + $frontendDir + '["'']?)?'
        $optionsOrEnd = '(?=\s+-|\s*$)'
        # 兼容相对路径入口（旧版脚本与手动调试常用），正反斜杠都认。
        # node + next start + 本项目固定端口 3000 的组合足以确认归属，
        # 避免「判成外来程序不敢杀 → 下次 start 报端口冲突」的死锁。
        $nextEntryRelative = 'node_modules[\\/]+next[\\/]+dist[\\/]+bin[\\/]+next'
        $nextPattern = '^\s*' + $nodeExecutable + '\s+["'']?(?:' + $nextEntry + '|' + $nextEntryRelative + ')["'']?\s+start' + $projectArgument + $optionsOrEnd
        return [regex]::IsMatch($CommandLine, $nextPattern, 'IgnoreCase')
    }

    $isUvicorn = [regex]::IsMatch($CommandLine, '(?:^|\s)-m\s+uvicorn(?:\s|$)', 'IgnoreCase')
    $isApplication = [regex]::IsMatch($CommandLine, '(?:^|\s)app\.main:app(?:\s|$)', 'IgnoreCase')
    $backendDir = [regex]::Escape((Join-Path $WorkspaceRoot "backend"))
    $appDirPattern = '(?:^|\s)--app-dir(?:\s+|=)["'']?' + $backendDir + '["'']?(?=\s|$)'
    $hasExactAppDir = [regex]::IsMatch($CommandLine, $appDirPattern, 'IgnoreCase')
    # 兼容历史形态：--app-dir . （相对路径，旧版脚本与手动调试常用）。
    # uvicorn + app.main:app + 8000 固定端口的组合已足以确认归属，避免
    # 「判成外来程序不敢杀 → 下次 start 报端口冲突」的死锁。
    $hasRelativeAppDir = [regex]::IsMatch($CommandLine, '(?:^|\s)--app-dir(?:\s+|=)["'']?\.["'']?(?=\s|$)', 'IgnoreCase')
    return $isUvicorn -and $isApplication -and ($hasExactAppDir -or $hasRelativeAppDir)
}

function Test-FrontendBuildFresh {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$BuildIdPath,
        [Parameter(Mandatory = $true)][string[]]$SourcePaths
    )

    if (-not (Test-Path -LiteralPath $BuildIdPath -PathType Leaf)) { return $false }
    $buildTime = (Get-Item -LiteralPath $BuildIdPath).LastWriteTimeUtc

    foreach ($sourcePath in $SourcePaths) {
        if (-not (Test-Path -LiteralPath $sourcePath)) { continue }
        $sourceItem = Get-Item -LiteralPath $sourcePath
        if (-not $sourceItem.PSIsContainer) {
            if ($sourceItem.LastWriteTimeUtc -gt $buildTime) { return $false }
            continue
        }

        $newerFile = Get-ChildItem -LiteralPath $sourcePath -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTimeUtc -gt $buildTime } |
            Select-Object -First 1
        if ($null -ne $newerFile) { return $false }
    }

    return $true
}

function Get-FrontendAction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ServiceStatus,
        [Parameter(Mandatory = $true)][bool]$BuildFresh
    )

    if ($ServiceStatus -eq "stopped") { return "start" }
    if ($ServiceStatus -eq "running" -and $BuildFresh) { return "reuse" }
    if ($ServiceStatus -eq "running") { return "restart" }
    throw "Unsupported frontend service status: $ServiceStatus"
}
