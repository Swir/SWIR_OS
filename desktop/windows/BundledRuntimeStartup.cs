using System.Runtime.CompilerServices;

namespace Swir.Desktop.Host;

internal static class BundledRuntimeStartup
{
    [ModuleInitializer]
    internal static void VerifyBundledRuntimeBeforeHostStart()
    {
#if SWIR_BUNDLED_RELEASE
        _ = BundledRuntimeIntegrity.Verify(AppContext.BaseDirectory, requireManifest: true);
#else
        var manifest = Path.Combine(AppContext.BaseDirectory, BundledRuntimeIntegrity.ManifestFileName);
        if (File.Exists(manifest))
            _ = BundledRuntimeIntegrity.Verify(AppContext.BaseDirectory, requireManifest: false);
#endif
        BundledWebView2Policy.EnsureRuntimeAccess();
    }
}
