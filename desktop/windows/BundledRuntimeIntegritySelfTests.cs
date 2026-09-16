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
            var provenance = Path.Combine(webRoot, ".swir-webview2-provenance.json");
            File.WriteAllBytes(host, "host-payload"u8.ToArray());
            File.WriteAllBytes(web, "webview2-payload"u8.ToArray());
            WriteFixtureProvenance(provenance, web);
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false);

            var verified = BundledRuntimeIntegrity.Verify(root, requireManifest: true);
            Assert(verified.ManifestPresent && verified.Verified && verified.Mode == "bundled-verified", "valid bundled runtime must verify");
            Assert(verified.EntryPointSha256 == Hash(host), "host SHA must be reported");
            Assert(verified.WebView2Sha256 == Hash(web), "WebView2 SHA must be reported");
            Assert(verified.WebView2ProvenanceSha256 == Hash(provenance), "WebView2 provenance SHA must be reported");

            File.AppendAllText(web, "tamper");
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "size mismatch", "runtime size tampering must fail closed");
            File.WriteAllBytes(web, "webview2-payload"u8.ToArray());
            WriteFixtureProvenance(provenance, web);
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false);

            var sameSizeTamper = File.ReadAllBytes(web);
            sameSizeTamper[0] ^= 0x01;
            File.WriteAllBytes(web, sameSizeTamper);
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "SHA-256 mismatch", "same-size runtime tampering must fail closed on SHA-256");
            File.WriteAllBytes(web, "webview2-payload"u8.ToArray());
            WriteFixtureProvenance(provenance, web);
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false);

            File.AppendAllText(provenance, " ");
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "provenance size mismatch", "provenance byte tampering must fail closed");
            WriteFixtureProvenance(provenance, web);
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false);

            var provenanceNode = JsonNode.Parse(File.ReadAllText(provenance))?.AsObject()
                ?? throw new InvalidOperationException("provenance parse failed");
            provenanceNode["executable"]!["sha256"] = new string('b', 64);
            File.WriteAllText(provenance, provenanceNode.ToJsonString());
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false, rewriteProvenance: false);
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "does not match bundled WebView2 integrity", "semantically forged provenance must fail even when outer provenance hash is updated");
            WriteFixtureProvenance(provenance, web);
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false);

            var manifestPath = Path.Combine(root, BundledRuntimeIntegrity.ManifestFileName);
            var manifest = JsonNode.Parse(File.ReadAllText(manifestPath))?.AsObject()
                ?? throw new InvalidOperationException("manifest parse failed");
            manifest["integrity"]!["entryPoint"]!["path"] = "../outside.exe";
            File.WriteAllText(manifestPath, manifest.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "path", "path traversal must fail closed");

            WriteFixtureProvenance(provenance, web);
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: true);
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "must not require user prerequisite downloads", "user prerequisite regression must fail closed");

            WriteFixtureProvenance(provenance, web);
            var badDownload = JsonNode.Parse(File.ReadAllText(provenance))?.AsObject()
                ?? throw new InvalidOperationException("provenance parse failed");
            badDownload["userDownloadRequired"] = true;
            File.WriteAllText(provenance, badDownload.ToJsonString());
            WriteManifest(root, host, web, provenance, prerequisiteDownloadsRequired: false, rewriteProvenance: false);
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "must not require a user download", "provenance cannot reintroduce user prerequisites");

            File.Delete(manifestPath);
            var dev = BundledRuntimeIntegrity.Verify(root, requireManifest: false);
            Assert(!dev.ManifestPresent && !dev.Verified && dev.Mode == "development-unverified", "developer build may run without release manifest");
            AssertThrows(() => BundledRuntimeIntegrity.Verify(root, true), "missing desktop-host-build.json", "bundled release must require manifest");

            Console.WriteLine("SWIR bundled runtime integrity self-tests: OK — host, WebView2, provenance, SHA-256, containment and no-prerequisite policy verified.");
            return 0;
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void WriteFixtureProvenance(string provenance, string web)
    {
        var payload = new
        {
            schema = BundledRuntimeIntegrity.WebView2ProvenanceContract,
            sourcePolicy = "ci-contract-fixture",
            sourceUrl = "fixture://windows-system32/where.exe",
            archiveSha256 = new string('0', 64),
            version = "fixture-or-unknown",
            architecture = "x64",
            executable = new
            {
                path = "msedgewebview2.exe",
                sha256 = Hash(web),
                authenticode = "fixture",
                signerSubject = "CI contract fixture only",
                signerThumbprint = ""
            },
            userDownloadRequired = false,
            contractFixture = true
        };
        File.WriteAllText(provenance, JsonSerializer.Serialize(payload));
    }

    private static void WriteManifest(string root, string host, string web, string provenance, bool prerequisiteDownloadsRequired, bool rewriteProvenance = true)
    {
        if (rewriteProvenance) WriteFixtureProvenance(provenance, web);
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
                userPrerequisiteDownloadsRequired = prerequisiteDownloadsRequired,
                webView2 = new
                {
                    mode = "fixed-version-bundled",
                    bundled = true,
                    relativePath = "WebView2FixedRuntime",
                    executable = "msedgewebview2.exe",
                    version = "fixture-or-unknown",
                    sourcePolicy = "ci-contract-fixture",
                    sourceUrl = "fixture://windows-system32/where.exe",
                    archiveSha256 = new string('0', 64),
                    provenanceFile = ".swir-webview2-provenance.json",
                    provenanceContract = BundledRuntimeIntegrity.WebView2ProvenanceContract,
                    contractFixture = true
                }
            },
            integrity = new
            {
                contract = BundledRuntimeIntegrity.IntegrityContract,
                algorithm = "SHA-256",
                entryPoint = Artifact("SWIR.Desktop.Host.exe", host),
                webView2Executable = Artifact("WebView2FixedRuntime/msedgewebview2.exe", web),
                webView2Provenance = Artifact("WebView2FixedRuntime/.swir-webview2-provenance.json", provenance)
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
