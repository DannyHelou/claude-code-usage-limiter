$ErrorActionPreference = 'Stop'
$start = '# >>> Coding Usage Limiter >>>'
$end = '# <<< Coding Usage Limiter <<<'
$pattern = '(?m)^' + [regex]::Escape($start) + '\r?\n(?s:.*?)^' + [regex]::Escape($end) + '(?:\r?\n|$)'
$encoding = [Text.UTF8Encoding]::new($false, $true)
$content = ''
if ([IO.File]::Exists($ProfilePath)) {
    $reader = [IO.StreamReader]::new($ProfilePath, $encoding, $true)
    try {
        $content = $reader.ReadToEnd()
        $encoding = $reader.CurrentEncoding
    } finally {
        $reader.Dispose()
    }
}
$blocks = [regex]::Matches($content, $pattern)
$markerCount = @($content -split '\r?\n' | Where-Object { $_ -ceq $start -or $_ -ceq $end }).Count
if ($blocks.Count -gt 1 -or $markerCount -ne (2 * $blocks.Count)) {
    throw "The limiter markers in $ProfilePath need manual repair."
}
$block = if ($blocks.Count) { $blocks[0] }
$remaining = if ($block) { $content.Remove($block.Index, $block.Length) } else { $content }

function Write-LimiterProfile([string] $Text) {
    if ($Text -ceq $content) { return }
    New-Item -ItemType Directory (Split-Path -Parent $ProfilePath) -Force | Out-Null
    $temporary = "$ProfilePath.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, $Text, $encoding)
        if ([IO.File]::Exists($ProfilePath)) {
            # File.Replace requires a real backup path on Windows PowerShell.
            [IO.File]::Replace($temporary, $ProfilePath, "$temporary.backup")
        } else {
            [IO.File]::Move($temporary, $ProfilePath)
        }
    } finally {
        [IO.File]::Delete($temporary)
        [IO.File]::Delete("$temporary.backup")
    }
}

function Quote-LimiterArgument([string] $Value) {
    "'" + $Value.Replace("'", "''") + "'"
}
