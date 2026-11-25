param(
    [Parameter(Mandatory)][string] $PythonPath,
    [Parameter(Mandatory)][string] $LimiterPath,
    [Parameter(Mandatory)][string] $Store
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

function Invoke-Limiter {
    & $PythonPath -B $LimiterPath --store $Store @args 2>&1
}

$initial = Invoke-Limiter state
if ($LASTEXITCODE -ne 0) {
    [void][Windows.Forms.MessageBox]::Show(($initial -join ' '), 'Coding Usage Limiter')
    exit 2
}
$initial = $initial | ConvertFrom-Json

$form = New-Object Windows.Forms.Form
$form.Text = 'Coding Usage Limiter'
$form.StartPosition = 'CenterScreen'
$form.AutoScaleMode = 'Dpi'
$form.ClientSize = New-Object Drawing.Size(470, (196 + 62 * $initial.windows.Count))
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object Drawing.Font('Segoe UI', 10)

function Add-Control($Type, $Text, $X, $Y, $Width, $Height) {
    $control = New-Object "Windows.Forms.$Type"
    $control.Text = $Text
    $control.SetBounds($X, $Y, $Width, $Height)
    $form.Controls.Add($control)
    return $control
}

$title = Add-Control Label 'Coding Usage Limiter' 18 14 430 34
$title.Font = New-Object Drawing.Font('Segoe UI', 17, [Drawing.FontStyle]::Bold)
[void](Add-Control Label 'Stop coding at (%)' 20 61 152 28)
$cutoff = Add-Control TextBox ([string]$initial.cutoff) 172 58 108 28
$apply = Add-Control Button 'Apply cutoff' 342 55 108 32
$form.AcceptButton = $apply
[void](Add-Control Label 'Used (%)' 20 101 90 26)
[void](Add-Control Label 'Reset time (ISO 8601 or Unix seconds)' 112 101 330 26)
$rows = @{}
$row = 127
foreach ($entry in $initial.windows) {
    $usageLabel = Add-Control Label '' 20 $row 430 24
    $used = Add-Control TextBox '' 20 ($row + 24) 82 28
    $reset = Add-Control TextBox '' 112 ($row + 24) 219 28
    $save = Add-Control Button 'Save usage' 342 ($row + 21) 108 32
    $save.Tag = $entry.name
    $save.Add_Click({
        param($sender, $eventArgs)
        $name = $sender.Tag
        $fields = $rows[$name]
        $result = Invoke-Limiter record $name $fields.Used.Text $fields.Reset.Text
        $notice.Text = if ($LASTEXITCODE -eq 0) { 'Usage reading saved.' } else { $result -join ' ' }
        Update-Status
    })
    $rows[$entry.name] = @{ Used = $used; Reset = $reset; Label = $usageLabel }
    $row += 62
}
$status = Add-Control Label '' 20 ($row + 2) 430 30
$notice = Add-Control Label '' 20 ($row + 33) 430 32

function Update-Status {
    $json = Invoke-Limiter state
    if ($LASTEXITCODE -ne 0) {
        $status.Text = $json -join ' '
        return
    }
    $state = $json | ConvertFrom-Json
    foreach ($entry in $state.windows) {
        if (-not $rows.ContainsKey($entry.name)) { continue }
        $name = switch ($entry.name) {
            five_hour { 'Five-hour usage' }
            seven_day { 'Weekly usage' }
            default { $entry.name }
        }
        $used = if ($null -eq $entry.used) { 'no reading' } else { "$($entry.used)%" }
        if ($entry.stale -and $null -ne $entry.used) { $used += ' (refresh needed)' }
        $rows[$entry.name].Label.Text = "$name    $used"
    }
    $status.Text = if (-not $state.enabled) { 'Limiter disabled. Use /limiter in Claude Code to enable it.' }
        elseif ($state.reason) { $state.reason }
        else { "Coding allowed. Active cutoff $($state.cutoff)%." }
}

$apply.Add_Click({
    $result = Invoke-Limiter set-cutoff $cutoff.Text
    $notice.Text = if ($LASTEXITCODE -eq 0) { 'Cutoff applied to running sessions.' } else { $result -join ' ' }
    Update-Status
})
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 1000
$timer.Add_Tick({ Update-Status })
$form.Add_FormClosed({ $timer.Dispose() })
Update-Status
$timer.Start()
[void]$form.ShowDialog()
