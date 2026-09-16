using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class BundledRuntimeIntegrity
{
    internal const string ManifestFileName = "desktop-host-build.json";
    internal const string IntegrityContract = "swir.desktop-bundled-integrity/0.1";
    internal const string WebView2ProvenanceContract = "swir.webview2-provenance/0.1";
    private const string WebView2SourcePolicy = "swir.webview2-fixed-source-policy/0.1";
    private const string BuildSchema = "swir.desktop-host-build/0.1";

    internal sealed record VerificationResult(
        bool ManifestPresent,
        bool Verified,
        string Mode,
        string? EntryPointSha256,
        string? WebView2Sha256,
        string? WebView2ProvenanceSha256);

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
            return new VerificationResult(false, false, "development-unverified", null, null, null);
        }

        using var document = JsonDocument.Parse(File.ReadAllBytes(manifestPath));
        var manifest = document.RootElement;
        RequireString(manifest, "schema", BuildSchema, "Desktop build schema mismatch.");

        if (!manifest.TryGetProperty("deployment", out var deployment) || deployment.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Desktop build manifest is missing deployment metadata.");
        if (!deployment.TryGetProperty("userPrerequisiteDownloadsRequired", out var prerequisites)
            || prerequisites.ValueKind is not JsonValueKind.False)
            throw new InvalidOperationException("Desktop release must not require user prerequisite downloads.");
        if (!deployment.TryGetProperty("webView2", out var webViewDeployment) || webViewDeployment.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Desktop build manifest is missing WebView2 deployment metadata.");
        RequireString(webViewDeployment, "mode", "fixed-version-bundled", "Desktop WebView2 must use bundled Fixed Version deployment.");
        RequireString(webViewDeployment, "provenanceContract", WebView2ProvenanceContract, "Desktop WebView2 provenance contract mismatch.");
        RequireString(webViewDeployment, "provenanceFile", ".swir-webview2-provenance.json", "Desktop WebView2 provenance file mismatch.");

        if (!manifest.TryGetProperty("integrity", out var integrity) || integrity.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Desktop build manifest is missing bundled runtime integrity metadata.");
        RequireString(integrity, "contract", IntegrityContract, "Desktop bundled integrity contract mismatch.");
        RequireString(integrity, "algorithm", "SHA-256", "Desktop bundled integrity algorithm mismatch.");

        var entry = ReadArtifact(integrity, "entryPoint");
        var webView = ReadArtifact(integrity, "webView2Executable");
        var provenance = ReadArtifact(integrity, "webView2Provenance");
        VerifyArtifact(root, entry, "Desktop Host entry point");
        VerifyArtifact(root, webView, "Bundled WebView2 executable");
        VerifyArtifact(root, provenance, "Bundled WebView2 provenance");

        if (!manifest.TryGetProperty("entryPoint", out var manifestEntryPoint)
            || manifestEntryPoint.ValueKind != JsonValueKind.String
            || !string.Equals(NormalizeRelativePath(manifestEntryPoint.GetString()!), entry.Path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Desktop entry point integrity metadata does not match the build manifest entry point.");

        var declaredProvenancePath = NormalizeRelativePath("WebView2FixedRuntime/" + webViewDeployment.GetProperty("provenanceFile").GetString());
        if (!string.Equals(declaredProvenancePath, provenance.Path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Desktop WebView2 provenance integrity path does not match deployment metadata.");

        VerifyWebView2Provenance(root, webView, provenance, webViewDeployment);

        return new VerificationResult(true, true, "bundled-verified", entry.Sha256, webView.Sha256, provenance.Sha256);
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
        var sha256 = NormalizeSha256(hashValue.GetString()!, $"Desktop bundled integrity artifact {propertyName} has invalid SHA-256.");
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
        if (!FixedHashEquals(actual, artifact.Sha256))
            throw new InvalidOperationException($"{displayName} SHA-256 mismatch: {artifact.Path}");
    }

    private static void VerifyWebView2Provenance(string root, Artifact webView, Artifact provenanceArtifact, JsonElement deployment)
    {
        var provenancePath = ResolveInsideRoot(root, provenanceArtifact.Path);
        using var provenanceDocument = JsonDocument.Parse(File.ReadAllBytes(provenancePath));
        var provenance = provenanceDocument.RootElement;
        RequireString(provenance, "schema", WebView2ProvenanceContract, "Bundled WebView2 provenance schema mismatch.");
        RequireString(provenance, "architecture", "x64", "Bundled WebView2 provenance architecture mismatch.");
        if (!provenance.TryGetProperty("userDownloadRequired", out var userDownload) || userDownload.ValueKind is not JsonValueKind.False)
            throw new InvalidOperationException("Bundled WebView2 provenance must not require a user download.");
        if (!provenance.TryGetProperty("executable", out var executable) || executable.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Bundled WebView2 provenance is missing executable metadata.");
        RequireString(executable, "path", "msedgewebview2.exe", "Bundled WebView2 provenance executable path mismatch.");
        if (!executable.TryGetProperty("sha256", out var executableHash) || executableHash.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException("Bundled WebView2 provenance executable SHA-256 is missing.");
        var provenanceWebViewHash = NormalizeSha256(executableHash.GetString()!, "Bundled WebView2 provenance executable SHA-256 is invalid.");
        if (!FixedHashEquals(provenanceWebViewHash, webView.Sha256))
            throw new InvalidOperationException("Bundled WebView2 provenance executable SHA-256 does not match bundled WebView2 integrity metadata.");

        var fixture = deployment.TryGetProperty("contractFixture", out var fixtureValue) && fixtureValue.ValueKind is JsonValueKind.True;
        if (fixture)
        {
            RequireString(provenance, "sourcePolicy", "ci-contract-fixture", "Bundled WebView2 fixture provenance policy mismatch.");
            if (!provenance.TryGetProperty("contractFixture", out var provenanceFixture) || provenanceFixture.ValueKind is not JsonValueKind.True)
                throw new InvalidOperationException("Bundled WebView2 fixture provenance marker is missing.");
            RequireString(executable, "authenticode", "fixture", "Bundled WebView2 fixture provenance signature marker mismatch.");
        }
        else
        {
            RequireString(provenance, "sourcePolicy", WebView2SourcePolicy, "Bundled WebView2 provenance source policy mismatch.");
            if (!provenance.TryGetProperty("sourceUrl", out var sourceUrl) || sourceUrl.ValueKind != JsonValueKind.String)
                throw new InvalidOperationException("Bundled WebView2 provenance source URL is missing.");
            ValidateMicrosoftHttpsUrl(sourceUrl.GetString()!);
            if (!provenance.TryGetProperty("archiveSha256", out var archiveHash) || archiveHash.ValueKind != JsonValueKind.String)
                throw new InvalidOperationException("Bundled WebView2 provenance archive SHA-256 is missing.");
            _ = NormalizeSha256(archiveHash.GetString()!, "Bundled WebView2 provenance archive SHA-256 is invalid.");
            RequireString(executable, "authenticode", "valid", "Bundled WebView2 provenance must record a valid Authenticode signature.");
            if (!executable.TryGetProperty("signerSubject", out var signer) || signer.ValueKind != JsonValueKind.String
                || !signer.GetString()!.Contains("Microsoft Corporation", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Bundled WebView2 provenance signer is not Microsoft Corporation.");
        }

        RequireDeploymentMatchesProvenance(deployment, provenance, fixture);
    }

    private static void RequireDeploymentMatchesProvenance(JsonElement deployment, JsonElement provenance, bool fixture)
    {
        RequireSameString(deployment, provenance, "sourcePolicy", "Desktop WebView2 source policy does not match bundled provenance.");
        RequireSameString(deployment, provenance, "sourceUrl", "Desktop WebView2 source URL does not match bundled provenance.");
        RequireSameString(deployment, provenance, "archiveSha256", "Desktop WebView2 archive SHA-256 does not match bundled provenance.");
        if (fixture && (!deployment.TryGetProperty("contractFixture", out var marker) || marker.ValueKind is not JsonValueKind.True))
            throw new InvalidOperationException("Desktop WebView2 fixture deployment marker is missing.");
    }

    private static void RequireSameString(JsonElement left, JsonElement right, string propertyName, string error)
    {
        if (!left.TryGetProperty(propertyName, out var leftValue) || leftValue.ValueKind != JsonValueKind.String
            || !right.TryGetProperty(propertyName, out var rightValue) || rightValue.ValueKind != JsonValueKind.String
            || !string.Equals(leftValue.GetString(), rightValue.GetString(), StringComparison.Ordinal))
            throw new InvalidOperationException(error);
    }

    private static void ValidateMicrosoftHttpsUrl(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Bundled WebView2 provenance source URL must use absolute HTTPS.");
        var host = uri.DnsSafeHost.ToLowerInvariant();
        if (host != "microsoft.com" && !host.EndsWith(".microsoft.com", StringComparison.Ordinal))
            throw new InvalidOperationException("Bundled WebView2 provenance source URL is not on an approved Microsoft host.");
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

    private static string NormalizeSha256(string value, string error)
    {
        var normalized = (value ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized.Length != 64 || normalized.Any(ch => !Uri.IsHexDigit(ch)))
            throw new InvalidOperationException(error);
        return normalized;
    }

    private static bool FixedHashEquals(string left, string right) =>
        CryptographicOperations.FixedTimeEquals(Convert.FromHexString(left), Convert.FromHexString(right));

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
