using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace Swir.Desktop.Host;

internal sealed class DesktopKonofixLauncher
{
    internal const string Schema = "swir.desktop-konofix-launch/0.1";
    internal const string ProductName = "Konofix Chat";
    internal const string ExpectedVersion = "0.5.1";
    private static readonly string[] ExecutableNames = { "konofix-chat.exe", "Konofix Chat.exe" };

    private readonly string[] _approvedRoots;
    private readonly Func<string?> _resolver;
    private readonly Func<string, bool> _versionVerifier;
    private readonly Func<ProcessStartInfo, int> _starter;
    private readonly Func<string, ExistingKonofixProcess?> _runningResolver;
    private readonly Func<IntPtr, bool> _foreground;

    internal DesktopKonofixLauncher(
        Func<string?>? resolver = null,
        Func<string, bool>? versionVerifier = null,
        Func<ProcessStartInfo, int>? starter = null,
        IEnumerable<string>? approvedRoots = null,
        Func<string, ExistingKonofixProcess?>? runningResolver = null,
        Func<IntPtr, bool>? foreground = null)
    {
        _approvedRoots = (approvedRoots ?? DefaultRoots())
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        _versionVerifier = versionVerifier ?? HasExpectedFileVersion;
        _resolver = resolver ?? ResolveInstalledExecutable;
        _starter = starter ?? StartProcess;
        _runningResolver = runningResolver ?? FindRunningQualifiedClient;
        _foreground = foreground ?? SetForegroundWindow;
    }

    internal object Describe()
    {
        var executable = TryResolveQualifiedExecutable();
        return new
        {
            schema = Schema,
            product = ProductName,
            expectedVersion = ExpectedVersion,
            installed = executable is not null,
            launchAvailable = executable is not null,
            provider = "windows-installed-client",
            shellExecution = false,
            automaticInstall = false,
            automaticExecution = false,
            legacyDataImport = false,
            systemEditionQualified = false
        };
    }

    internal KonofixLaunchResult Launch()
    {
        var executable = _resolver();
        if (string.IsNullOrWhiteSpace(executable))
            throw new DesktopKonofixException("KONOFIX_NOT_INSTALLED", "Konofix Chat 0.5.1 is not installed in an approved user or Program Files location.");

        executable = RequireQualifiedExecutable(executable);
        var existing = _runningResolver(executable);
        if (existing is not null)
        {
            var focused = existing.MainWindowHandle != IntPtr.Zero && _foreground(existing.MainWindowHandle);
            return new KonofixLaunchResult(Schema, ProductName, ExpectedVersion, false, existing.ProcessId, false, false, true, focused);
        }

        var start = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = Path.GetDirectoryName(executable) ?? throw new DesktopKonofixException("KONOFIX_INSTALL_INVALID", "Konofix install directory is unavailable."),
            UseShellExecute = false,
            CreateNoWindow = false
        };

        int pid;
        try { pid = _starter(start); }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception or FileNotFoundException)
        {
            throw new DesktopKonofixException("KONOFIX_LAUNCH_FAILED", "Windows could not start the qualified Konofix client.", ex);
        }
        if (pid <= 0)
            throw new DesktopKonofixException("KONOFIX_LAUNCH_FAILED", "Windows did not return a valid Konofix process id.");

        return new KonofixLaunchResult(Schema, ProductName, ExpectedVersion, true, pid, false, false, false, false);
    }

    private string? TryResolveQualifiedExecutable()
    {
        try
        {
            var value = _resolver();
            return string.IsNullOrWhiteSpace(value) ? null : RequireQualifiedExecutable(value);
        }
        catch (DesktopKonofixException) { return null; }
    }

    private string? ResolveInstalledExecutable()
    {
        foreach (var root in _approvedRoots)
        {
            foreach (var relative in new[]
            {
                Path.Combine("Konofix Chat", "konofix-chat.exe"),
                Path.Combine("Konofix Chat", "Konofix Chat.exe"),
                Path.Combine("Programs", "Konofix Chat", "konofix-chat.exe"),
                Path.Combine("Programs", "Konofix Chat", "Konofix Chat.exe")
            })
            {
                if (TryQualify(Path.Combine(root, relative), null, out var qualified)) return qualified;
            }
        }

        foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            try
            {
                using var baseKey = RegistryKey.OpenBaseKey(hive, view);
                using var uninstall = baseKey.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", writable: false);
                if (uninstall is null) continue;
                foreach (var subkeyName in uninstall.GetSubKeyNames())
                {
                    using var key = uninstall.OpenSubKey(subkeyName, writable: false);
                    if (!string.Equals(key?.GetValue("DisplayName") as string, ProductName, StringComparison.Ordinal)) continue;
                    var version = key?.GetValue("DisplayVersion") as string;
                    if (!VersionMatches(version)) continue;

                    if (key?.GetValue("InstallLocation") is string installLocation && !string.IsNullOrWhiteSpace(installLocation))
                        foreach (var name in ExecutableNames)
                            if (TryQualify(Path.Combine(installLocation.Trim(), name), version, out var qualified)) return qualified;

                    if (key?.GetValue("DisplayIcon") is string displayIcon)
                    {
                        var iconPath = ParseDisplayIconPath(displayIcon);
                        if (iconPath is not null && TryQualify(iconPath, version, out var qualified)) return qualified;
                    }
                }
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or System.Security.SecurityException or IOException) { }
        }
        return null;
    }

    private bool TryQualify(string candidate, string? declaredVersion, out string? qualified)
    {
        try
        {
            var full = RequireApprovedPath(candidate);
            if (!File.Exists(full) || (File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0)
            {
                qualified = null;
                return false;
            }
            if (!(VersionMatches(declaredVersion) || _versionVerifier(full)))
            {
                qualified = null;
                return false;
            }
            qualified = full;
            return true;
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or IOException or UnauthorizedAccessException)
        {
            qualified = null;
            return false;
        }
    }

    private string RequireQualifiedExecutable(string candidate)
    {
        var full = RequireApprovedPath(candidate);
        if (!File.Exists(full) || (File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0)
            throw new DesktopKonofixException("KONOFIX_INSTALL_INVALID", "Konofix executable is missing or uses a reparse point.");
        if (!_versionVerifier(full))
            throw new DesktopKonofixException("KONOFIX_VERSION_MISMATCH", $"Konofix executable is not the reviewed {ExpectedVersion} version.");
        return full;
    }

    private string RequireApprovedPath(string candidate)
    {
        if (string.IsNullOrWhiteSpace(candidate))
            throw new DesktopKonofixException("KONOFIX_INSTALL_INVALID", "Konofix executable path is empty.");

        var full = Path.GetFullPath(candidate);
        if (!Path.IsPathFullyQualified(full) || new Uri(full).IsUnc)
            throw new DesktopKonofixException("KONOFIX_INSTALL_INVALID", "Konofix executable must be a local absolute path.");
        if (!ExecutableNames.Contains(Path.GetFileName(full), StringComparer.OrdinalIgnoreCase))
            throw new DesktopKonofixException("KONOFIX_INSTALL_INVALID", "Unexpected Konofix executable name.");
        if (!_approvedRoots.Any(root => IsInside(root, full)))
            throw new DesktopKonofixException("KONOFIX_INSTALL_INVALID", "Konofix executable is outside approved install roots.");
        return full;
    }

    private static bool IsInside(string root, string candidate)
    {
        var prefix = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        return candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    private static IEnumerable<string> DefaultRoots()
    {
        yield return Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        yield return Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        yield return Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
    }

    private static bool HasExpectedFileVersion(string path)
    {
        try
        {
            var info = FileVersionInfo.GetVersionInfo(path);
            return VersionMatches(info.ProductVersion) || VersionMatches(info.FileVersion);
        }
        catch { return false; }
    }

    private static bool VersionMatches(string? value)
    {
        var normalized = (value ?? string.Empty).Trim();
        return string.Equals(normalized, ExpectedVersion, StringComparison.Ordinal)
            || normalized.StartsWith(ExpectedVersion + ".", StringComparison.Ordinal)
            || normalized.StartsWith(ExpectedVersion + "+", StringComparison.Ordinal);
    }

    private static string? ParseDisplayIconPath(string value)
    {
        var text = value.Trim();
        if (text.Length == 0) return null;
        if (text[0] == '"')
        {
            var end = text.IndexOf('"', 1);
            return end > 1 ? text[1..end] : null;
        }
        var comma = text.LastIndexOf(',');
        if (comma > 0 && int.TryParse(text[(comma + 1)..].Trim(), out _)) text = text[..comma];
        return text.Trim();
    }

    private static ExistingKonofixProcess? FindRunningQualifiedClient(string executable)
    {
        var expected = Path.GetFullPath(executable);
        var processName = Path.GetFileNameWithoutExtension(expected);
        foreach (var process in Process.GetProcessesByName(processName))
        {
            using (process)
            {
                try
                {
                    var runningPath = process.MainModule?.FileName;
                    if (string.IsNullOrWhiteSpace(runningPath)) continue;
                    if (!string.Equals(Path.GetFullPath(runningPath), expected, StringComparison.OrdinalIgnoreCase)) continue;
                    return new ExistingKonofixProcess(process.Id, process.MainWindowHandle);
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException)
                {
                    // Never trust process name alone when path inspection fails.
                }
            }
        }
        return null;
    }

    private static int StartProcess(ProcessStartInfo info)
    {
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Process.Start returned null.");
        return process.Id;
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(IntPtr hWnd);
}

internal sealed record ExistingKonofixProcess(int ProcessId, IntPtr MainWindowHandle);

internal sealed record KonofixLaunchResult(
    string Schema, string Product, string Version, bool Started, int ProcessId, bool ShellExecution, bool LegacyDataImported,
    bool AlreadyRunning, bool Focused);

internal sealed class DesktopKonofixException(string code, string message, Exception? innerException = null)
    : Exception(message, innerException)
{
    public string Code { get; } = code;
}
