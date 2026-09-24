param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$TimeoutSeconds = 20,
    [string]$ClientProcessName = 'konofix-chat-swir-ci-a'
)

$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw 'Native file-picker automation is restricted to a disposable Windows GitHub Actions runner.'
}
if ($ClientProcessName -notmatch '^konofix-chat-swir-ci-[ab]$') {
    throw 'Unexpected Konofix CI client process name.'
}

$resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw 'The transfer fixture must be a regular file.'
}
$fullPath = [IO.Path]::GetFullPath($resolved)
$tempRoot = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\') + '\'
if (-not $fullPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to select a file outside RUNNER_TEMP: $fullPath"
}

$clientProcesses = @(Get-Process -Name $ClientProcessName -ErrorAction SilentlyContinue)
if ($clientProcesses.Count -ne 1) {
    throw "Expected exactly one running $ClientProcessName process; found $($clientProcesses.Count)."
}
$clientPid = [int]$clientProcesses[0].Id

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$root = [System.Windows.Automation.AutomationElement]::RootElement
$trueCondition = [System.Windows.Automation.Condition]::TrueCondition
$editIdCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
    '1148'
)
$buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button
)
$editCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Edit
)

function Find-KonofixFileDialog {
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $trueCondition)
    $fallback = $null
    foreach ($window in $windows) {
        try {
            if ([int]$window.Current.ProcessId -ne $clientPid) { continue }
            $className = [string]$window.Current.ClassName
            $name = [string]$window.Current.Name
            if ($className -eq '#32770') { return $window }
            if ($name -eq 'Wyślij plik przez Konofix Chat' -or $name -match '^(Open|Otwórz|Choose|Wybierz|Select)') {
                $fallback = $window
            }
        } catch {}
    }
    return $fallback
}

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
while ([DateTime]::UtcNow -lt $deadline) {
    $dialog = Find-KonofixFileDialog
    if ($null -eq $dialog) {
        Start-Sleep -Milliseconds 150
        continue
    }

    Write-Host "Konofix file dialog found for PID ${clientPid}: class='$($dialog.Current.ClassName)' name='$($dialog.Current.Name)'"

    $candidates = @()
    $preferred = $dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editIdCondition)
    if ($null -ne $preferred) { $candidates += $preferred }
    $edits = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
    foreach ($candidate in $edits) { $candidates += $candidate }

    $edit = $null
    $valuePattern = $null
    foreach ($candidate in $candidates) {
        try {
            if (-not $candidate.Current.IsEnabled) { continue }
            $candidatePattern = $null
            if ($candidate.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$candidatePattern)) {
                $edit = $candidate
                $valuePattern = $candidatePattern
                break
            }
        } catch {}
    }
    if ($null -eq $edit -or $null -eq $valuePattern) {
        throw 'Konofix file dialog exposed no editable filename control with ValuePattern.'
    }

    $valuePattern.SetValue($fullPath)

    $buttons = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
    $open = $null
    foreach ($button in $buttons) {
        $name = ($button.Current.Name -replace '&', '').Trim()
        if ($name -match '^(Open|Otwórz|Choose|Wybierz|Select|OK)$') {
            $open = $button
            break
        }
    }
    if ($null -eq $open) {
        throw 'Konofix file dialog exposed no recognized Open/Select button.'
    }

    Write-Host "Submitting disposable Konofix transfer fixture: $([IO.Path]::GetFileName($fullPath))"
    $invoke = $open.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $invoke.Invoke()
    # Do not wait for the native dialog to disappear through UI Automation: on
    # hosted runners that COM query can block while the rfd dialog is tearing
    # down. The Node E2E is authoritative and immediately requires a genuine
    # incoming `file-offer` from the second published client, so returning here
    # cannot turn an unsuccessful selection into a pass.
    Write-Host 'Native picker submit invoked; downstream peer assertion owns success.'
    exit 0
}

$snapshot = @()
$top = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $trueCondition)
foreach ($window in $top) {
    try {
        if ([int]$window.Current.ProcessId -eq $clientPid) {
            $snapshot += "name='$($window.Current.Name)' class='$($window.Current.ClassName)'"
        }
    } catch {}
}
throw "Timed out waiting for the Konofix file dialog for PID $clientPid. Client windows: $($snapshot -join '; ')"
