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
$clientPid = [uint32]$clientProcesses[0].Id

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class SwirKonofixDialogNative {
    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hwnd, StringBuilder className, int maxCount);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")]
    private static extern IntPtr GetDlgItem(IntPtr hwnd, int id);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, IntPtr wParam,
        string lParam, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, IntPtr wParam,
        IntPtr lParam, uint flags, uint timeout, out IntPtr result);

    private const uint WM_SETTEXT = 0x000C;
    private const uint BM_CLICK = 0x00F5;
    private const uint SMTO_ABORTIFHUNG = 0x0002;

    public static IntPtr FindDialog(uint processId, out string description) {
        IntPtr found = IntPtr.Zero;
        string snapshot = "";
        EnumWindows((hwnd, _) => {
            uint pid;
            GetWindowThreadProcessId(hwnd, out pid);
            if (pid != processId) return true;
            var cls = new StringBuilder(128);
            var title = new StringBuilder(512);
            GetClassName(hwnd, cls, cls.Capacity);
            GetWindowText(hwnd, title, title.Capacity);
            if (snapshot.Length > 0) snapshot += "; ";
            snapshot += "class='" + cls + "' title='" + title + "'";
            if (cls.ToString() == "#32770") {
                found = hwnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        description = snapshot;
        return found;
    }

    public static string SubmitFile(IntPtr dialog, string path) {
        if (dialog == IntPtr.Zero) throw new InvalidOperationException("Dialog handle is zero.");
        // Windows Common Item Dialog exposes File name as cmb13 (1148). WM_SETTEXT
        // is handled by the editable combo and avoids UI Automation COM stalls on
        // hosted runners. The real Konofix `file-offer` on peer B remains the
        // authoritative proof that the published client accepted this selection.
        IntPtr fileName = GetDlgItem(dialog, 1148);
        if (fileName == IntPtr.Zero) {
            // Older common-dialog layouts expose the edit directly as edt1 (1152).
            fileName = GetDlgItem(dialog, 1152);
        }
        if (fileName == IntPtr.Zero) throw new InvalidOperationException("No standard filename control (1148/1152) found.");
        IntPtr ignored;
        if (SendMessageTimeout(fileName, WM_SETTEXT, IntPtr.Zero, path, SMTO_ABORTIFHUNG, 2000, out ignored) == IntPtr.Zero)
            throw new InvalidOperationException("Filename control rejected or timed out on WM_SETTEXT.");

        IntPtr open = GetDlgItem(dialog, 1); // IDOK
        if (open == IntPtr.Zero) throw new InvalidOperationException("No standard Open/OK control (IDOK=1) found.");
        if (SendMessageTimeout(open, BM_CLICK, IntPtr.Zero, IntPtr.Zero, SMTO_ABORTIFHUNG, 2000, out ignored) == IntPtr.Zero)
            throw new InvalidOperationException("Open/OK control rejected or timed out on BM_CLICK.");
        return "submitted";
    }
}
'@

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$lastSnapshot = ''
while ([DateTime]::UtcNow -lt $deadline) {
    $snapshot = ''
    $dialog = [SwirKonofixDialogNative]::FindDialog($clientPid, [ref]$snapshot)
    $lastSnapshot = $snapshot
    if ($dialog -eq [IntPtr]::Zero) {
        Start-Sleep -Milliseconds 150
        continue
    }

    Write-Host "Konofix file dialog found for PID ${clientPid}: $snapshot"
    $result = [SwirKonofixDialogNative]::SubmitFile($dialog, $fullPath)
    if ($result -ne 'submitted') { throw 'Native picker submit returned an unexpected result.' }
    Write-Host "Submitted disposable Konofix transfer fixture: $([IO.Path]::GetFileName($fullPath))"
    exit 0
}

throw "Timed out waiting for the Konofix file dialog for PID $clientPid. Client windows: $lastSnapshot"
