param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw 'Native file-picker automation is restricted to a disposable Windows GitHub Actions runner.'
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

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$root = [System.Windows.Automation.AutomationElement]::RootElement
$title = 'Wyślij plik przez Konofix Chat'
$titleCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    $title
)
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

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
while ([DateTime]::UtcNow -lt $deadline) {
    $dialog = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $titleCondition)
    if ($null -eq $dialog) {
        Start-Sleep -Milliseconds 150
        continue
    }

    $edit = $dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editIdCondition)
    if ($null -eq $edit) {
        $edits = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
        foreach ($candidate in $edits) {
            try {
                if ($candidate.Current.IsEnabled) {
                    $null = $candidate.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                    $edit = $candidate
                    break
                }
            } catch {}
        }
    }
    if ($null -eq $edit) { throw 'Konofix file dialog exposed no editable filename control.' }

    $valuePattern = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
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
    $invoke = $open.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $invoke.Invoke()

    $closeDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $closeDeadline) {
        Start-Sleep -Milliseconds 100
        if ($null -eq $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $titleCondition)) {
            Write-Host "Selected disposable Konofix transfer fixture: $([IO.Path]::GetFileName($fullPath))"
            exit 0
        }
    }
    throw 'Konofix file dialog did not close after selection.'
}
throw "Timed out waiting for Konofix file dialog '$title'."
