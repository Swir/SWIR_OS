using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Swir.Desktop.Host;

internal static class BundledRuntimeIntegritySelfTests
{
    public static int Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "swir-bundled-integrity-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var host = Path.Combine(root, "SWIR.Desktop.Host.exe");
            var webRoot = Path.Combine(root, "WebView2FixedRuntime");
            Directory.CreateDirectory(webRoot);
            var web = Path.Combine(webRoot, "msedgewebview2.exe");
            File.WriteAllBytes(host, "host-payload"u8.ToArray());
            File.WriteAllBytes(web, "webview2-payload"u8.ToArray());
            WriteManifest(root, host, web, prerequisiteDownloadsRequired: false);

            var verified = BundledRuntimeIntegrity.Verify(root, requireManifest: true);
            Assert(verified.ManifestPresent && verified.Verified && verified.Mode == "bundled-verified", "valid bundled runtime must verify");
            Assert(verified.EntryPointSha256 == Hash(host), "host SHA must be reported");
            Assert(verified.WebView2Sha256 == Hash(web), "WebView2 SHA must be reported");

            File.AppendAllText(web, "tamper");
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "size mismatch", "runtime size tampering must fail closed");
            File.WriteAllBytes(web, "webview2-payload"u8.ToArray());
            WriteManifest(root, host, web, prerequisiteDownloadsRequired: false);

            var sameSizeTamper = File.ReadAllBytes(web);
            sameSizeTamper[0] ^= 0x01;
            File.WriteAllBytes(web, sameSizeTamper);
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "SHA-256 mismatch", "same-size runtime tampering must fail closed on SHA-256");
            File.WriteAllBytes(web, "webview2-payload"u8.ToArray());
            WriteManifest(root, host, web, prerequisiteDownloadsRequired: false);

            var manifestPath = Path.Combine(root, BundledRuntimeIntegrity.ManifestFileName);
            var manifest = JsonNode.Parse(File.ReadAllText(manifestPath))?.AsObject()
                ?? throw new InvalidOperationException("manifest parse failed");
            manifest["integrity"]!["entryPoint"]!["path"] = "../outside.exe";
            File.WriteAllText(manifestPath, manifest.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "path", "path traversal must fail closed");

            WriteManifest(root, host, web, prerequisiteDownloadsRequired: true);
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "must not require user prerequisite downloads", "user prerequisite regression must fail closed");

            File.Delete(manifestPath);
            var dev = BundledRuntimeIntegrity.Verify(root, requireManifest: false);
            Assert(!dev.ManifestPresent && !dev.Verified && dev.Mode == "development-unverified", "developer build may run without release manifest");
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "missing desktop-host-build.json", "bundled release must require manifest");

            Console.WriteLine("SWIR bundled runtime integrity self-tests: OK — size, SHA-256, path containment and no-prerequisite policy verified.");
            return 0;
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void WriteManifest(string root, string host, string web, bool prerequisiteDownloadsRequired)
    {
        var payload = new
        {
            schema = "swir.desktop-host-build/0.1",
            releaseVersion = "0.5.7",
            channel = "preview",
            hostVersion = "0.5.7-preview",
            sourceCommit = new string('a', 40),
            entryPoint = "SWIR.Desktop.Host.exe",
            deployment = new
            {
                contract = "swir.desktop-bundled-runtime/0.1",
                mode = "self-contained-bundled",
                userPrerequisiteDownloadsRequired = prerequisiteDownloadsRequired
            },
            integrity = new
            {
                contract = BundledRuntimeIntegrity.IntegrityContract,
                algorithm = "SHA-256",
                entryPoint = Artifact("SWIR.Desktop.Host.exe", host),
                webView2Executable = Artifact("WebView2FixedRuntime/msedgewebview2.exe", web)
            }
        };
        File.WriteAllText(Path.Combine(root, BundledRuntimeIntegrity.ManifestFileName), JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    }

    private static object Artifact(string path, string file) => new
    {
        path,
        sha256 = Hash(file),
        size = new FileInfo(file).Length
    };

    private static string Hash(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("SELFTEST: " + message);
    }

    private static void AssertThrows(Action action, string messageFragment, string message)
    {
        try
        {
            action();
        }
        catch (Exception ex) when (ex.Message.Contains(messageFragment, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }
        throw new InvalidOperationException("SELFTEST: " + message);
    }
}
