using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class BundledRuntimeIntegrity
{
    internal const string ManifestFileName = "desktop-host-build.json";
    internal const string IntegrityContract = "swir.desktop-bundled-integrity/0.1";
    private const string BuildSchema = "swir.desktop-host-build/0.1";

    internal sealed record VerificationResult(
        bool ManifestPresent,
        bool Verified,
        string Mode,
        string? EntryPointSha256,
        string? WebView2Sha256);

    internal static VerificationResult Verify(string baseDirectory, bool requireManifest)
    {
        if (string.IsNullOrWhiteSpace(baseDirectory))
            throw new InvalidOperationException("Desktop runtime base directory is required.");

        var root = Path.GetFullPath(baseDirectory)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var manifestPath = Path.Combine(root, ManifestFileName);
        if (!File.Exists(manifestPath))
        {
            if (requireManifest)
                throw new InvalidOperationException($"Bundled Desktop release is missing {ManifestFileName}.");
            return new VerificationResult(false, false, "development-unverified", null, null);
        }

        using var document = JsonDocument.Parse(File.ReadAllBytes(manifestPath));
        var manifest = document.RootElement;
        RequireString(manifest, "schema", BuildSchema, "Desktop build schema mismatch.");

        if (!manifest.TryGetProperty("deployment", out var deployment) || deployment.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Desktop build manifest is missing deployment metadata.");
        if (!deployment.TryGetProperty("userPrerequisiteDownloadsRequired", out var prerequisites)
            || prerequisites.ValueKind is not JsonValueKind.False)
            throw new InvalidOperationException("Desktop release must not require user prerequisite downloads.");

        if (!manifest.TryGetProperty("integrity", out var integrity) || integrity.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Desktop build manifest is missing bundled runtime integrity metadata.");
        RequireString(integrity, "contract", IntegrityContract, "Desktop bundled integrity contract mismatch.");
        RequireString(integrity, "algorithm", "SHA-256", "Desktop bundled integrity algorithm mismatch.");

        var entry = ReadArtifact(integrity, "entryPoint");
        var webView = ReadArtifact(integrity, "webView2Executable");
        VerifyArtifact(root, entry, "Desktop Host entry point");
        VerifyArtifact(root, webView, "Bundled WebView2 executable");

        if (!manifest.TryGetProperty("entryPoint", out var manifestEntryPoint)
            || manifestEntryPoint.ValueKind != JsonValueKind.String
            || !string.Equals(NormalizeRelativePath(manifestEntryPoint.GetString()!), entry.Path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Desktop entry point integrity metadata does not match the build manifest entry point.");

        return new VerificationResult(true, true, "bundled-verified", entry.Sha256, webView.Sha256);
    }

    private sealed record Artifact(string Path, string Sha256, long Size);

    private static Artifact ReadArtifact(JsonElement integrity, string propertyName)
    {
        if (!integrity.TryGetProperty(propertyName, out var artifact) || artifact.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException($"Desktop bundled integrity metadata is missing {propertyName}.");
        if (!artifact.TryGetProperty("path", out var pathValue) || pathValue.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException($"Desktop bundled integrity artifact {propertyName} is missing path.");
        if (!artifact.TryGetProperty("sha256", out var hashValue) || hashValue.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException($"Desktop bundled integrity artifact {propertyName} is missing SHA-256.");
        if (!artifact.TryGetProperty("size", out var sizeValue) || sizeValue.ValueKind != JsonValueKind.Number || !sizeValue.TryGetInt64(out var size) || size < 0)
            throw new InvalidOperationException($"Desktop bundled integrity artifact {propertyName} has invalid size.");

        var relativePath = NormalizeRelativePath(pathValue.GetString()!);
        var sha256 = hashValue.GetString()!.Trim().ToLowerInvariant();
        if (sha256.Length != 64 || sha256.Any(ch => !Uri.IsHexDigit(ch)))
            throw new InvalidOperationException($"Desktop bundled integrity artifact {propertyName} has invalid SHA-256.");
        return new Artifact(relativePath, sha256, size);
    }

    private static void VerifyArtifact(string root, Artifact artifact, string displayName)
    {
        var fullPath = ResolveInsideRoot(root, artifact.Path);
        if (!File.Exists(fullPath))
            throw new InvalidOperationException($"{displayName} is missing: {artifact.Path}");
        var info = new FileInfo(fullPath);
        if (info.Length != artifact.Size)
            throw new InvalidOperationException($"{displayName} size mismatch: {artifact.Path}");
        var actual = HashFile(fullPath);
        if (!CryptographicOperations.FixedTimeEquals(Convert.FromHexString(actual), Convert.FromHexString(artifact.Sha256)))
            throw new InvalidOperationException($"{displayName} SHA-256 mismatch: {artifact.Path}");
    }

    private static string ResolveInsideRoot(string root, string relativePath)
    {
        if (Path.IsPathRooted(relativePath))
            throw new InvalidOperationException("Bundled runtime integrity paths must be relative.");
        var fullPath = Path.GetFullPath(Path.Combine(root, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        var prefix = root + Path.DirectorySeparatorChar;
        if (!fullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Bundled runtime integrity path escapes the release root.");
        return fullPath;
    }

    private static string NormalizeRelativePath(string path)
    {
        var value = (path ?? string.Empty).Trim().Replace('\\', '/');
        if (string.IsNullOrWhiteSpace(value) || value.StartsWith('/') || value.Split('/').Any(part => part is "" or "." or ".."))
            throw new InvalidOperationException("Bundled runtime integrity path is invalid.");
        return value;
    }

    private static string HashFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static void RequireString(JsonElement parent, string propertyName, string expected, string error)
    {
        if (!parent.TryGetProperty(propertyName, out var value)
            || value.ValueKind != JsonValueKind.String
            || !string.Equals(value.GetString(), expected, StringComparison.Ordinal))
            throw new InvalidOperationException(error);
    }
}
