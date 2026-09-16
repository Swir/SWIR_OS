using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopGitHubUpdatePolicy
{
    public const string PolicySchema = "swir.desktop-update-policy/0.1";
    private const string Repo = "Swir/SWIR_OS";

    public static bool TryWriteForOfficialRelease(string sourceDirectory, Uri packageUri, Version version, string channel, string privateKeyPem)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceDirectory);
        ArgumentNullException.ThrowIfNull(packageUri);
        ArgumentNullException.ThrowIfNull(version);
        var normalizedChannel = (channel ?? string.Empty).Trim().ToLowerInvariant();
        if (normalizedChannel is not ("preview" or "stable"))
            throw new UpdateSecurityException("UPDATE_RELEASE_CHANNEL_INVALID", "Official GitHub update policy requires preview or stable channel.");

        var tag = $"desktop-v{version}-{normalizedChannel}";
        var packageName = $"SWIR-Desktop-{version}-{normalizedChannel}.zip";
        var expectedUri = new Uri($"https://github.com/{Repo}/releases/download/{tag}/{packageName}");
        if (packageUri != expectedUri) return false;

        string publicKeyPem;
        using (var rsa = RSA.Create())
        {
            try
            {
                rsa.ImportFromPem(privateKeyPem);
                if (rsa.KeySize < 2048)
                    throw new UpdateSecurityException("UPDATE_RELEASE_PRIVATE_KEY_INVALID", "Release signing RSA key must be at least 2048 bits.");
                publicKeyPem = rsa.ExportSubjectPublicKeyInfoPem();
            }
            catch (UpdateSecurityException) { throw; }
            catch (Exception ex) when (ex is ArgumentException or CryptographicException)
            { throw new UpdateSecurityException("UPDATE_RELEASE_PRIVATE_KEY_INVALID", "Release signing private key is invalid and cannot provision the update policy."); }
        }

        var policy = new
        {
            Schema = PolicySchema,
            Enabled = true,
            Channel = normalizedChannel,
            ManifestUrl = $"https://raw.githubusercontent.com/{Repo}/main/updates/{normalizedChannel}/desktop-update-{normalizedChannel}.json",
            ManifestHosts = new[] { "raw.githubusercontent.com" },
            PackageHosts = new[] { "github.com" },
            PublicKeyPem = publicKeyPem
        };

        var root = Path.GetFullPath(sourceDirectory);
        if (!Directory.Exists(root)) throw new UpdateSecurityException("UPDATE_PACKAGE_SOURCE_MISSING", "Desktop package source directory does not exist.");
        var policyPath = Path.Combine(root, "desktop-update-policy.json");
        var tempPath = policyPath + ".tmp-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllText(tempPath, JsonSerializer.Serialize(policy, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(tempPath, policyPath, true);
        }
        finally { try { if (File.Exists(tempPath)) File.Delete(tempPath); } catch { } }
        return true;
    }
}
