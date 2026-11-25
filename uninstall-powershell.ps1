param(
    [string] $ProfilePath = $PROFILE.CurrentUserAllHosts,
    [string] $InstallRoot = (Join-Path $env:LOCALAPPDATA 'ClaudeCodeUsageLimiter')
)
$ProfilePath = [IO.Path]::GetFullPath($ProfilePath)
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
. (Join-Path $PSScriptRoot 'powershell-install-common.ps1')
if ($block) { Write-LimiterProfile $remaining }

$otherProfiles = 'WindowsPowerShell', 'PowerShell' | ForEach-Object {
    Join-Path ([Environment]::GetFolderPath('MyDocuments')) "$_\profile.ps1"
} | Where-Object { $_ -ne $ProfilePath -and [IO.File]::Exists($_) }
$stillUsed = $false
foreach ($other in $otherProfiles) {
    $otherContent = [IO.File]::ReadAllText($other)
    if ($otherContent.Contains($start) -and $otherContent.Contains($InstallRoot)) { $stillUsed = $true }
}

$versions = Join-Path $InstallRoot 'versions'
if (-not $stillUsed -and [IO.Directory]::Exists($versions)) {
    $rootItem = Get-Item -LiteralPath $InstallRoot
    $versionsItem = Get-Item -LiteralPath $versions
    if (($versionsItem.Attributes -bor $rootItem.Attributes) -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Refusing to remove runtimes from a linked directory.'
    }
    $prefix = [IO.Path]::GetFullPath($versions).TrimEnd('\') + '\'
    foreach ($entry in Get-ChildItem -LiteralPath $versions -Directory) {
        if ($entry.Name -notmatch '^\d+\.\d+\.\d+(?:-[a-z0-9.]+)?$' -or
            -not $entry.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
            ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
        $stamp = Join-Path $entry.FullName '.limiter-runtime'
        if ([IO.File]::Exists($stamp) -and (Get-Content -LiteralPath $stamp -Raw).Trim() -eq $entry.Name) {
            Remove-Item -LiteralPath $entry.FullName -Recurse -Force
        }
    }
}
Write-Output "Registration removed. Saved data remains in $(Join-Path $InstallRoot 'data')."
Write-Output 'Open a new PowerShell terminal to use the original claude command.'
