using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopGitHubUpdatePolicySelfTests
{
    public static int Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "swir-github-policy-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            using var rsa = RSA.Create(3072);
            var privatePem = rsa.ExportRSAPrivateKeyPem();
            var expectedPublicPem = rsa.ExportSubjectPublicKeyInfoPem();
            var version = new Version(0, 5, 8);
            var official = new Uri("https://github.com/Swir/SWIR_OS/releases/download/desktop-v0.5.8-preview/SWIR-Desktop-0.5.8-preview.zip");
            Require(DesktopGitHubUpdatePolicy.TryWriteForOfficialRelease(root, official, version, "preview", privatePem), "official GitHub Release provisions update policy");
            var policyPath = Path.Combine(root, "desktop-update-policy.json");
            using var document = JsonDocument.Parse(File.ReadAllText(policyPath));
            var policy = document.RootElement;
            Require(policy.GetProperty("Schema").GetString() == DesktopGitHubUpdatePolicy.PolicySchema, "policy schema matches contract");
            Require(policy.GetProperty("Enabled").GetBoolean(), "official release policy is enabled");
            Require(policy.GetProperty("Channel").GetString() == "preview", "release channel is pinned");
            Require(policy.GetProperty("ManifestUrl").GetString() == "https://raw.githubusercontent.com/Swir/SWIR_OS/main/updates/preview/desktop-update-preview.json", "manifest stays in SWIR_OS repo");
            Require(policy.GetProperty("ManifestHosts")[0].GetString() == "raw.githubusercontent.com", "manifest host is allowlisted");
            Require(policy.GetProperty("PackageHosts")[0].GetString() == "github.com", "package host is allowlisted");
            Require(policy.GetProperty("PublicKeyPem").GetString() == expectedPublicPem, "matching public verifier key is embedded");
            Require(!File.ReadAllText(policyPath).Contains("PRIVATE KEY", StringComparison.Ordinal), "private signing key never enters policy");

            var other = Path.Combine(root, "other"); Directory.CreateDirectory(other);
            Require(!DesktopGitHubUpdatePolicy.TryWriteForOfficialRelease(other, new Uri("https://example.com/SWIR-Desktop-0.5.8-preview.zip"), version, "preview", privatePem), "non-official package URL does not auto-enable GitHub feed");
            Require(!File.Exists(Path.Combine(other, "desktop-update-policy.json")), "non-official package leaves policy untouched");
            Console.WriteLine("Desktop GitHub update policy self-tests passed.");
            return 0;
        }
        finally { try { Directory.Delete(root, true); } catch { } }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
        Console.WriteLine("PASS " + message);
    }
}
