$ErrorActionPreference = 'Stop'
$root = Join-Path ([IO.Path]::GetTempPath()) ('limiter smoke ' + [guid]::NewGuid().ToString('N'))
$profilePath = Join-Path $root 'profile.ps1'
$installRoot = Join-Path $root 'installed'
$legacy = Join-Path $root 'old checkout'
$legacyStore = Join-Path $legacy '.usage-limiter'
$python = (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source
$install = Join-Path $PSScriptRoot 'install-powershell.ps1'
$uninstall = Join-Path $PSScriptRoot 'uninstall-powershell.ps1'
$source = Join-Path $PSScriptRoot 'limiter.py'
$unchanged = "# Existing profile line`r`n"
New-Item -ItemType Directory -Path $legacy -Force | Out-Null
try {
    & $python -B $source --store $legacyStore configure 78 | Out-Null
    if ($LASTEXITCODE) { throw 'Could not seed the test database.' }
    $legacyDatabase = Join-Path $legacyStore 'usage.db'
    & $python -c "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('UPDATE config SET enabled=0'); db.commit()" $legacyDatabase
    if ($LASTEXITCODE) { throw 'Could not seed enabled state.' }
    $reset = [DateTimeOffset]::UtcNow.AddHours(1).ToUnixTimeSeconds()
    & $python -B $source --store $legacyStore record five_hour 32 $reset
    if ($LASTEXITCODE) { throw 'Could not seed usage.' }
    $legacyBlock = @"
# >>> Coding Usage Limiter >>>
function claude {
    & '$python' -B '$legacy\limiter.py' launch -- @args
}
# <<< Coding Usage Limiter <<<
"@
    [IO.File]::WriteAllText($profilePath, $unchanged + $legacyBlock + "`r`n", [Text.Encoding]::Unicode)
    & $install -ProfilePath $profilePath -InstallRoot $installRoot
    $installed = [IO.File]::ReadAllText($profilePath)
    & $install -ProfilePath $profilePath -InstallRoot $installRoot
    if ([IO.File]::ReadAllText($profilePath) -cne $installed) { throw 'Repeat install changed the profile.' }
    $version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim()
    $launcher = Join-Path $installRoot "versions\$version\limiter.py"
    $store = Join-Path $installRoot 'data'
    $state = & $python -B $launcher --store $store state | ConvertFrom-Json
    if ($LASTEXITCODE -or $state.cutoff -ne 78 -or $state.enabled -or $state.windows[0].used -ne 32) {
        throw 'Upgrade did not preserve cutoff, enabled state and usage data.'
    }
    . $profilePath
    if ((Get-Command claude).CommandType -ne 'Function') { throw 'Profile did not register the command.' }
    & $uninstall -ProfilePath $profilePath -InstallRoot $installRoot
    & $uninstall -ProfilePath $profilePath -InstallRoot $installRoot
    if ([IO.File]::ReadAllText($profilePath) -cne $unchanged) { throw 'Uninstall altered unrelated profile content.' }
    if ([IO.File]::Exists($launcher) -or -not [IO.File]::Exists((Join-Path $store 'usage.db'))) {
        throw 'Uninstall did not remove the runtime and preserve settings.'
    }
    & $install -ProfilePath $profilePath -InstallRoot $installRoot
    & $uninstall -ProfilePath $profilePath -InstallRoot $installRoot
    if ([IO.File]::ReadAllText($profilePath) -cne $unchanged) { throw 'Fresh install and uninstall changed the profile.' }
    $nested = "# >>> Coding Usage Limiter >>>`r`n" + $unchanged + $legacyBlock + "`r`n"
    [IO.File]::WriteAllText($profilePath, $nested)
    foreach ($operation in $install, $uninstall) {
        $blocked = $false
        try {
            & $operation -ProfilePath $profilePath -InstallRoot $installRoot
        } catch {
            if ($_.Exception.Message -notmatch 'markers.*manual repair') { throw }
            $blocked = $true
        }
        if (-not $blocked -or [IO.File]::ReadAllText($profilePath) -cne $nested) {
            throw 'An installer operation accepted or rewrote malformed markers.'
        }
    }
    Write-Output 'PowerShell installer smoke tests passed.'
} finally {
    if ([IO.Path]::GetFullPath($root).StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
