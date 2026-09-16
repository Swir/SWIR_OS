using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopReleaseBundleSelfTests
{
    public static int Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "swir-release-bundle-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var source = Path.Combine(root, "publish");
            Directory.CreateDirectory(source);
            File.WriteAllText(Path.Combine(source, "SWIR.Desktop.Host.exe"), "host-binary-test");
            Directory.CreateDirectory(Path.Combine(source, "assets"));
            File.WriteAllText(Path.Combine(source, "assets", "shell.txt"), "shell");

            using var rsa = RSA.Create(2048);
            var privatePem = rsa.ExportRSAPrivateKeyPem();
            var publicPem = rsa.ExportSubjectPublicKeyInfoPem();
            var version = new Version(0, 5, 2);
            var publishedAt = DateTimeOffset.UtcNow.AddMinutes(-1);
            var packageUri = new Uri("https://updates.example.test/SWIR-Desktop-0.5.2-stable.zip");

            var bundle1 = DesktopReleaseBundleBuilder.Build(
                source,
                Path.Combine(root, "bundle-1"),
                version,
                "SWIR.Desktop.Host.exe",
                packageUri,
                "stable",
                "test-key-1",
                privatePem,
                publishedAt);

            Require(File.Exists(bundle1.PackagePath), "release package missing");
            Require(File.Exists(bundle1.ManifestPath), "signed manifest missing");
            Require(File.Exists(bundle1.MetadataPath), "bundle metadata missing");

            var broker = new UpdateBroker(publicPem, new[] { "updates.example.test" });
            var verified = broker.VerifyManifest(File.ReadAllText(bundle1.ManifestPath), new Version(0, 5, 1), "stable");
            Require(verified.Version == version, "signed manifest version mismatch");
            Require(string.Equals(verified.Sha256, bundle1.PackageSha256, StringComparison.Ordinal), "signed package hash mismatch");
            Require(UpdateBroker.VerifyPackage(File.ReadAllBytes(bundle1.PackagePath), verified).Verified, "package verification failed");

            var metadata = JsonSerializer.Deserialize<DesktopReleaseBundleBuilder.ReleaseBundleMetadata>(File.ReadAllText(bundle1.MetadataPath));
            Require(metadata is not null, "bundle metadata could not be decoded");
            Require(metadata!.Schema == DesktopReleaseBundleBuilder.BundleSchema, "bundle schema mismatch");
            Require(metadata.PackageSha256 == bundle1.PackageSha256, "metadata package hash mismatch");
            Require(metadata.ManifestSha256 == bundle1.ManifestSha256, "metadata manifest hash mismatch");

            var bundle2 = DesktopReleaseBundleBuilder.Build(
                source,
                Path.Combine(root, "bundle-2"),
                version,
                "SWIR.Desktop.Host.exe",
                packageUri,
                "stable",
                "test-key-1",
                privatePem,
                publishedAt);
            Require(bundle1.PackageSha256 == bundle2.PackageSha256, "deterministic package hash changed between release bundles");
            Require(File.ReadAllBytes(bundle1.PackagePath).SequenceEqual(File.ReadAllBytes(bundle2.PackagePath)), "deterministic packages differ byte-for-byte");

            ExpectCode("UPDATE_RELEASE_BUNDLE_OUTPUT_EXISTS", () => DesktopReleaseBundleBuilder.Build(
                source, Path.Combine(root, "bundle-1"), version, "SWIR.Desktop.Host.exe", packageUri, "stable", "test-key-1", privatePem, publishedAt));

            ExpectCode("UPDATE_RELEASE_BUNDLE_URL_MISMATCH", () => DesktopReleaseBundleBuilder.Build(
                source, Path.Combine(root, "bundle-bad-url"), version, "SWIR.Desktop.Host.exe",
                new Uri("https://updates.example.test/wrong.zip"), "stable", "test-key-1", privatePem, publishedAt));
            Require(!Directory.Exists(Path.Combine(root, "bundle-bad-url")), "failed bundle left final output behind");

            VerifyOfficialGitHubReleaseCarriesUpdatePolicy(root, privatePem, publicPem, publishedAt);

            Console.WriteLine("Desktop release bundle self-tests passed.");
            return 0;
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void VerifyOfficialGitHubReleaseCarriesUpdatePolicy(
        string root,
        string privatePem,
        string publicPem,
        DateTimeOffset publishedAt)
    {
        var source = Path.Combine(root, "official-publish");
        Directory.CreateDirectory(source);
        File.WriteAllText(Path.Combine(source, "SWIR.Desktop.Host.exe"), "official-host-binary-test");
        Directory.CreateDirectory(Path.Combine(source, "assets"));
        File.WriteAllText(Path.Combine(source, "assets", "shell.txt"), "official-shell");

        var version = new Version(0, 5, 8);
        const string channel = "preview";
        var tag = $"desktop-v{version}-{channel}";
        var packageUri = new Uri($"https://github.com/Swir/SWIR_OS/releases/download/{tag}/SWIR-Desktop-{version}-{channel}.zip");
        var bundle = DesktopReleaseBundleBuilder.Build(
            source,
            Path.Combine(root, "bundle-official"),
            version,
            "SWIR.Desktop.Host.exe",
            packageUri,
            channel,
            "test-key-official",
            privatePem,
            publishedAt);

        var broker = new UpdateBroker(publicPem, new[] { "github.com" });
        var verified = broker.VerifyManifest(File.ReadAllText(bundle.ManifestPath), new Version(0, 5, 7), channel);
        Require(verified.PackageUri == packageUri, "official signed manifest pins immutable SWIR_OS GitHub Release URL");
        Require(UpdateBroker.VerifyPackage(File.ReadAllBytes(bundle.PackagePath), verified).Verified, "official GitHub release package verifies against signed digest");

        using var archive = ZipFile.OpenRead(bundle.PackagePath);
        var entry = archive.GetEntry("desktop-update-policy.json");
        Require(entry is not null, "official release ZIP contains Desktop update policy");
        using var reader = new StreamReader(entry!.Open());
        var policyText = reader.ReadToEnd();
        using var document = JsonDocument.Parse(policyText);
        var policy = document.RootElement;
        Require(policy.GetProperty("Schema").GetString() == DesktopGitHubUpdatePolicy.PolicySchema, "packaged update policy uses expected schema");
        Require(policy.GetProperty("Enabled").GetBoolean(), "official release ZIP enables signed GitHub update feed");
        Require(policy.GetProperty("Channel").GetString() == channel, "packaged update policy pins release channel");
        Require(policy.GetProperty("ManifestUrl").GetString() == "https://raw.githubusercontent.com/Swir/SWIR_OS/main/updates/preview/desktop-update-preview.json", "packaged update policy reads feed only from SWIR_OS repository");
        Require(policy.GetProperty("ManifestHosts")[0].GetString() == "raw.githubusercontent.com", "packaged update policy allowlists raw GitHub feed host");
        Require(policy.GetProperty("PackageHosts")[0].GetString() == "github.com", "packaged update policy allowlists GitHub Release package host");
        Require(policy.GetProperty("PublicKeyPem").GetString() == publicPem, "official release ZIP embeds matching public verifier key");
        Require(!policyText.Contains("PRIVATE KEY", StringComparison.Ordinal), "official release ZIP never embeds private update signing key");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
        Console.WriteLine("PASS " + message);
    }

    private static void ExpectCode(string code, Action action)
    {
        try { action(); }
        catch (UpdateSecurityException ex) when (ex.Code == code) { return; }
        throw new InvalidOperationException($"Expected {code}.");
    }
}
