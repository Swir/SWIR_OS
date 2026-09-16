using System.Runtime.CompilerServices;

namespace Swir.Desktop.Host;

internal static class BundledWebView2Policy
{
    internal const string RuntimeDirectoryName = "WebView2FixedRuntime";
    internal const string BrowserExecutableName = "msedgewebview2.exe";

    [ModuleInitializer]
    internal static void ConfigureBundledRuntime()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        var browserExecutable = Path.Combine(runtimeRoot, BrowserExecutableName);
        if (!Directory.Exists(runtimeRoot) || !File.Exists(browserExecutable))
            return;

        Environment.SetEnvironmentVariable(
            "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
            runtimeRoot,
            EnvironmentVariableTarget.Process);
    }

    internal static object Describe()
    {
        var runtimeRoot = Path.Combine(AppContext.BaseDirectory, RuntimeDirectoryName);
        return new
        {
            contract = "swir.desktop-bundled-webview2/0.1",
            relativePath = RuntimeDirectoryName,
            executable = BrowserExecutableName,
            available = File.Exists(Path.Combine(runtimeRoot, BrowserExecutableName)),
            configuredPath = Environment.GetEnvironmentVariable("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
        };
    }
}
