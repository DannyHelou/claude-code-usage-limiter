param(
    [string] $ProfilePath = $PROFILE.CurrentUserAllHosts,
    [string] $InstallRoot = (Join-Path $env:LOCALAPPDATA 'ClaudeCodeUsageLimiter')
)
$ProfilePath = [IO.Path]::GetFullPath($ProfilePath)
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
. (Join-Path $PSScriptRoot 'powershell-install-common.ps1')

if ($remaining -match '(?im)^\s*(?:function\s+(?:global:|script:)?claude\b|(?:set-alias|new-alias|sal|nal)\s+(?:-name\s+)?claude\b)') {
    throw 'The profile already defines claude outside the limiter block.'
}
$command = Get-Command claude -ErrorAction SilentlyContinue
if ($ProfilePath -eq $PROFILE.CurrentUserAllHosts -and $command -and $command.CommandType -in 'Alias','Function' -and
    ($command.CommandType -eq 'Alias' -or -not $block -or -not $block.Value.Contains($command.Definition.Trim()))) {
    throw 'The current PowerShell session already defines claude outside the limiter block.'
}
$python = (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source
& $python -c 'import sys; sys.exit(sys.version_info < (3, 10))'
if ($LASTEXITCODE) { throw 'Python 3.10 or later is required.' }
$version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(?:-[a-z0-9.]+)?$') { throw 'Invalid release version.' }
$versions = Join-Path $InstallRoot 'versions'
$runtime = Join-Path $versions $version
$data = Join-Path $InstallRoot 'data'
$database = Join-Path $data 'usage.db'
$files = 'limiter.py', 'limiter_demo.py', 'limiter_windows.py', 'limiter_window.ps1', 'claude-integration', 'VERSION', 'LICENSE'
Write-Output "PowerShell profile: $ProfilePath"
Write-Output "Installed files: $runtime"
New-Item -ItemType Directory -Path $versions, $data -Force | Out-Null
if (-not [IO.Directory]::Exists($runtime)) {
    $stage = Join-Path $versions ('.install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $stage -Recurse
    }
    [IO.File]::WriteAllText((Join-Path $stage '.limiter-runtime'), $version)
    [IO.Directory]::Move($stage, $runtime)
}
if ($block -and -not [IO.File]::Exists($database)) {
    $legacy = [regex]::Match($block.Value, "-B '((?:''|[^'])+)' launch --")
    if ($legacy.Success) {
        $oldLauncher = $legacy.Groups[1].Value.Replace("''", "'")
        $oldDatabase = Join-Path (Split-Path -Parent $oldLauncher) '.usage-limiter\usage.db'
        if ([IO.File]::Exists($oldDatabase)) {
            $temporaryDb = "$database.$([guid]::NewGuid().ToString('N')).tmp"
            try {
                & $python -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); target=sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()' $oldDatabase $temporaryDb
                if ($LASTEXITCODE) { throw 'Could not migrate the previous limiter database.' }
                [IO.File]::Move($temporaryDb, $database)
            } finally {
                [IO.File]::Delete($temporaryDb)
            }
        }
    }
}
$launcher = Quote-LimiterArgument (Join-Path $runtime 'limiter.py')
$quotedPython = Quote-LimiterArgument $python
$store = Quote-LimiterArgument $data
$registration = @"
$start
function claude {
    `$limiterStore = if (`$env:CODING_LIMITER_HOME) { `$env:CODING_LIMITER_HOME } else { $store }
    & $quotedPython -B $launcher --store `$limiterStore launch -- @args
}
$end
"@
$newline = if ($content.Contains("`n") -and -not $content.Contains("`r`n")) { "`n" } else { "`r`n" }
$registration = ($registration -replace '\r?\n', $newline) + $newline
if ($block) {
    $updated = $remaining.Insert($block.Index, $registration)
} else {
    $separator = if ($remaining -and -not $remaining.EndsWith("`n")) { $newline } else { '' }
    $updated = $remaining + $separator + $registration
}
Write-LimiterProfile $updated
Write-Output 'Open a new PowerShell terminal and run claude.'
