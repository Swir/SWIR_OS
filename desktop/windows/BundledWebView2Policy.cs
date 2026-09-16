using System.Runtime.CompilerServices;

namespace Swir.Desktop.Host;

internal static class BundledWebView2Policy
{
    internal const string RuntimeDirectoryName = "WebView2FixedRuntime";
    internal const string BrowserExecutableName = "msedgewebview2.exe";
    internal const string ContractFixtureMarkerName = ".swir-ci-contract-fixture";

    [ModuleInitializer]
    internal static void ConfigureBundledRuntime()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        var browserExecutable = Path.Combine(runtimeRoot, BrowserExecutableName);
        var contractFixtureMarker = Path.Combine(runtimeRoot, ContractFixtureMarkerName);
        if (!Directory.Exists(runtimeRoot) || !File.Exists(browserExecutable))
            return;

        // A contract fixture verifies packaging topology only. It is deliberately never selected as a browser
        // runtime, allowing release E2E to exercise the real host health handshake through the runner's
        // installed Evergreen runtime. Production Fixed Version payloads never contain this marker.
        if (File.Exists(contractFixtureMarker))
            return;

        Environment.SetEnvironmentVariable(
            "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
            runtimeRoot,
            EnvironmentVariableTarget.Process);
    }

    internal static object Describe()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        var fixture = File.Exists(Path.Combine(runtimeRoot, ContractFixtureMarkerName));
        return new
        {
            contract = "swir.desktop-bundled-webview2/0.1",
            relativePath = RuntimeDirectoryName,
            executable = BrowserExecutableName,
            available = File.Exists(Path.Combine(runtimeRoot, BrowserExecutableName)),
            contractFixture = fixture,
            configuredPath = Environment.GetEnvironmentVariable("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
        };
    }
}
