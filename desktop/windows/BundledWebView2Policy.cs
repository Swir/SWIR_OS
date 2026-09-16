using System.Diagnostics;
using System.Runtime.CompilerServices;

namespace Swir.Desktop.Host;

internal static class BundledWebView2Policy
{
    internal const string RuntimeDirectoryName = "WebView2FixedRuntime";
    internal const string BrowserExecutableName = "msedgewebview2.exe";
    internal const string ContractFixtureMarkerName = ".swir-ci-contract-fixture";
    internal const string AppContainerAclMarkerName = ".swir-appcontainer-acl-v1";

    [ModuleInitializer]
    internal static void ConfigureBundledRuntime()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        var browserExecutable = Path.Combine(runtimeRoot, BrowserExecutableName);
        var contractFixtureMarker = Path.Combine(runtimeRoot, ContractFixtureMarkerName);
        if (!Directory.Exists(runtimeRoot) || !File.Exists(browserExecutable))
            return;

        // Contract fixtures verify package topology only and must never be selected as a browser runtime.
        if (File.Exists(contractFixtureMarker))
            return;

        Environment.SetEnvironmentVariable(
            "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
            runtimeRoot,
            EnvironmentVariableTarget.Process);
    }

    internal static void EnsureRuntimeAccess()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        var browserExecutable = Path.Combine(runtimeRoot, BrowserExecutableName);
        if (!Directory.Exists(runtimeRoot) || !File.Exists(browserExecutable))
            return;
        if (File.Exists(Path.Combine(runtimeRoot, ContractFixtureMarkerName)))
            return;
        if (!RequiresWindows10AppContainerAcl())
            return;

        var marker = Path.Combine(runtimeRoot, AppContainerAclMarkerName);
        if (File.Exists(marker))
            return;

        GrantReadExecute(runtimeRoot, "*S-1-15-2-2"); // ALL RESTRICTED APPLICATION PACKAGES
        GrantReadExecute(runtimeRoot, "*S-1-15-2-1"); // ALL APPLICATION PACKAGES
        File.WriteAllText(marker, "swir.webview2.appcontainer-acl/1\n");
    }

    internal static bool RequiresWindows10AppContainerAcl()
    {
        if (!OperatingSystem.IsWindows())
            return false;
        var version = Environment.OSVersion.Version;
        return version.Major == 10 && version.Build > 0 && version.Build < 22000;
    }

    private static void GrantReadExecute(string runtimeRoot, string sid)
    {
        var systemRoot = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        var icacls = Path.Combine(systemRoot, "System32", "icacls.exe");
        if (!File.Exists(icacls))
            throw new InvalidOperationException("Windows ACL utility is unavailable; bundled WebView2 cannot be prepared safely on Windows 10.");

        var start = new ProcessStartInfo
        {
            FileName = icacls,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.ArgumentList.Add(runtimeRoot);
        start.ArgumentList.Add("/grant");
        start.ArgumentList.Add($"{sid}:(OI)(CI)(RX)");
        start.ArgumentList.Add("/T");
        start.ArgumentList.Add("/C");
        start.ArgumentList.Add("/Q");

        using var process = Process.Start(start)
            ?? throw new InvalidOperationException("Could not start Windows ACL preparation for bundled WebView2.");
        if (!process.WaitForExit(30_000))
        {
            try { process.Kill(entireProcessTree: true); } catch { }
            throw new InvalidOperationException("Timed out while preparing bundled WebView2 AppContainer permissions.");
        }
        var stderr = process.StandardError.ReadToEnd().Trim();
        if (process.ExitCode != 0)
            throw new InvalidOperationException($"Could not prepare bundled WebView2 AppContainer permissions (icacls {process.ExitCode}): {stderr}");
    }

    internal static object Describe()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        var fixture = File.Exists(Path.Combine(runtimeRoot, ContractFixtureMarkerName));
        return new
        {
            contract = "swir.desktop-bundled-webview2/0.2",
            relativePath = RuntimeDirectoryName,
            executable = BrowserExecutableName,
            available = File.Exists(Path.Combine(runtimeRoot, BrowserExecutableName)),
            contractFixture = fixture,
            appContainerAclRequired = RequiresWindows10AppContainerAcl(),
            appContainerAclPrepared = File.Exists(Path.Combine(runtimeRoot, AppContainerAclMarkerName)),
            configuredPath = Environment.GetEnvironmentVariable("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
        };
    }
}
