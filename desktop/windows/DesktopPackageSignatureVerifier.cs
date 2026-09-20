using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using NSec.Cryptography;

namespace Swir.Desktop.Host;

internal sealed class DesktopPackageSignatureVerifier
{
    public const string SignatureSchema = "swir.package-signature/1.0";
    public const string SignatureEntryName = "swir-package-signature.json";
    private const string ManifestEntryName = "swir-package.json";
    private const int MaxEntries = 2048;
    private const long MaxEntryBytes = 64L * 1024 * 1024;
    private const long MaxExpandedBytes = 256L * 1024 * 1024;
    private const long MaxManifestBytes = 1024L * 1024;
    private const long MaxSignatureEnvelopeBytes = 64L * 1024;
    private const int HashBufferBytes = 128 * 1024;
    private readonly IReadOnlyDictionary<string, TrustRoot> _roots;

    internal sealed record TrustRoot(string KeyId, string Name, byte[] PublicKey, IReadOnlyList<string> Scope);
    internal sealed record PackageContent(string PackageId, string Version, string ContentSha256);
    internal sealed record VerificationResult(bool Signed, bool Verified, string? KeyId, string PackageId, string Version, string ContentSha256)
    {
        public static VerificationResult Unsigned(PackageContent content) => new(false, false, null, content.PackageId, content.Version, content.ContentSha256);
    }

    public DesktopPackageSignatureVerifier(IEnumerable<TrustRoot> roots)
    {
        _roots = (roots ?? throw new ArgumentNullException(nameof(roots))).ToDictionary(root => root.KeyId, StringComparer.Ordinal);
    }

    public int TrustedRootCount => _roots.Count;

    public VerificationResult Verify(string bundlePath, bool requireSignature)
    {
        if (!File.Exists(bundlePath))
            throw new DesktopPackageException("PACKAGE_NOT_FOUND", "SWIR package bundle does not exist.");

        try
        {
            using var archive = ZipFile.OpenRead(bundlePath);
            var content = ComputeContent(archive);
            var signatureEntries = archive.Entries
                .Where(entry => string.Equals(NormalizeEntryPath(entry.FullName), SignatureEntryName, StringComparison.Ordinal))
                .ToArray();

            if (signatureEntries.Length == 0)
            {
                if (requireSignature)
                    throw new DesktopPackageException("PACKAGE_SIGNATURE_REQUIRED", "This Desktop package policy requires an embedded Ed25519 package signature.");
                return VerificationResult.Unsigned(content);
            }
            if (signatureEntries.Length != 1)
                throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", "Desktop package must contain exactly one embedded signature envelope.");
            if (signatureEntries[0].Length > MaxSignatureEnvelopeBytes)
                throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", $"Embedded package signature envelope exceeds {MaxSignatureEnvelopeBytes} bytes.");

            SignatureEnvelope envelope;
            try
            {
                var bytes = ReadEntryBytesBounded(signatureEntries[0], MaxSignatureEnvelopeBytes, "signature envelope");
                envelope = JsonSerializer.Deserialize<SignatureEnvelope>(bytes, JsonOptions)
                    ?? throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", "Embedded package signature envelope is empty.");
            }
            catch (DesktopPackageException) { throw; }
            catch (Exception ex) when (ex is JsonException or IOException or InvalidDataException)
            {
                throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", $"Embedded package signature envelope is unreadable: {ex.Message}");
            }

            if (!string.Equals(envelope.Schema, SignatureSchema, StringComparison.Ordinal) ||
                !string.Equals(envelope.Algorithm, "Ed25519", StringComparison.Ordinal))
                throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", $"Embedded package signature must use {SignatureSchema} and Ed25519.");

            var keyId = ValidateToken(envelope.KeyId, "key ID", 128);
            var packageId = ValidateToken(envelope.PackageId, "package ID", 128);
            var version = ValidateToken(envelope.Version, "package version", 64);
            var signedDigest = NormalizeDigest(envelope.ContentSha256);
            if (!string.Equals(packageId, content.PackageId, StringComparison.Ordinal) ||
                !string.Equals(version, content.Version, StringComparison.Ordinal))
                throw new DesktopPackageException("PACKAGE_SIGNATURE_IDENTITY_MISMATCH", "Embedded package signature identity/version does not match swir-package.json.");
            if (!FixedDigestEquals(signedDigest, content.ContentSha256))
                throw new DesktopPackageException("PACKAGE_CONTENT_DIGEST_MISMATCH", "Embedded package signature content digest does not match the package payload.");

            if (!_roots.TryGetValue(keyId, out var root))
                throw new DesktopPackageException("PACKAGE_SIGNATURE_UNKNOWN_KEY", $"Embedded package signer '{keyId}' is not trusted by the Desktop Host.");
            if (!(root!.Scope.Contains("*", StringComparer.Ordinal) || root.Scope.Contains("package:swirapp", StringComparer.Ordinal)))
                throw new DesktopPackageException("PACKAGE_SIGNATURE_KEY_OUT_OF_SCOPE", $"Embedded package signer '{keyId}' is outside package:swirapp scope.");

            byte[] signature;
            try { signature = Convert.FromBase64String((envelope.Signature ?? string.Empty).Trim()); }
            catch (FormatException) { throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", "Embedded package signature is not valid base64."); }

            PublicKey publicKey;
            try { publicKey = PublicKey.Import(SignatureAlgorithm.Ed25519, root.PublicKey, KeyBlobFormat.RawPublicKey); }
            catch (Exception ex) { throw new DesktopPackageException("PACKAGE_SIGNATURE_KEY_INVALID", $"Trusted package signing public key is invalid: {ex.Message}"); }

            var payload = CanonicalSignedPayload(keyId, packageId, version, content.ContentSha256);
            if (!SignatureAlgorithm.Ed25519.Verify(publicKey, Encoding.UTF8.GetBytes(payload), signature))
                throw new DesktopPackageException("PACKAGE_BAD_SIGNATURE", "Embedded Ed25519 package signature verification failed.");

            return new VerificationResult(true, true, keyId, packageId, version, content.ContentSha256);
        }
        catch (DesktopPackageException) { throw; }
        catch (InvalidDataException ex) { throw new DesktopPackageException("PACKAGE_ARCHIVE_INVALID", ex.Message); }
    }

    internal static PackageContent ComputeContent(ZipArchive archive)
    {
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaxEntries)
            throw new DesktopPackageException("PACKAGE_ARCHIVE_LIMIT", $"Package must contain between 1 and {MaxEntries} entries.");

        long total = 0;
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var entries = new List<ContentEntry>();
        JsonDocument? manifest = null;
        try
        {
            foreach (var entry in archive.Entries)
            {
                var path = NormalizeEntryPath(entry.FullName);
                if (string.IsNullOrWhiteSpace(path) || path.StartsWith('/') || path.Contains(':'))
                    throw new DesktopPackageException("PACKAGE_PATH_INVALID", $"Unsafe archive path: {entry.FullName}");
                var segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
                if (segments.Length == 0 || segments.Any(segment => segment is "." or ".."))
                    throw new DesktopPackageException("PACKAGE_PATH_TRAVERSAL", $"Archive traversal blocked: {entry.FullName}");
                path = string.Join('/', segments);
                if (!seen.Add(path))
                    throw new DesktopPackageException("PACKAGE_DUPLICATE_PATH", $"Duplicate package path: {entry.FullName}");
                if (entry.FullName.EndsWith('/')) continue;

                var length = entry.Length;
                if (length < 0 || length > MaxEntryBytes)
                    throw new DesktopPackageException("PACKAGE_ENTRY_TOO_LARGE", $"Package entry exceeds {MaxEntryBytes} bytes: {entry.FullName}");
                total = checked(total + length);
                if (total > MaxExpandedBytes)
                    throw new DesktopPackageException("PACKAGE_EXPANDED_TOO_LARGE", $"Expanded package exceeds {MaxExpandedBytes} bytes.");

                if (string.Equals(path, SignatureEntryName, StringComparison.Ordinal))
                    continue;

                string digest;
                if (string.Equals(path, ManifestEntryName, StringComparison.Ordinal))
                {
                    if (length > MaxManifestBytes)
                        throw new DesktopPackageException("PACKAGE_MANIFEST_INVALID", $"swir-package.json exceeds {MaxManifestBytes} bytes.");
                    try
                    {
                        var bytes = ReadEntryBytesBounded(entry, MaxManifestBytes, "manifest");
                        digest = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
                        manifest = JsonDocument.Parse(bytes);
                    }
                    catch (DesktopPackageException) { throw; }
                    catch (JsonException ex)
                    {
                        throw new DesktopPackageException("PACKAGE_MANIFEST_INVALID", ex.Message);
                    }
                }
                else
                {
                    digest = HashEntryBounded(entry);
                }
                entries.Add(new ContentEntry(path, length, digest));
            }

            if (manifest is null || manifest.RootElement.ValueKind != JsonValueKind.Object)
                throw new DesktopPackageException("PACKAGE_MANIFEST_MISSING", "swir-package.json is required at the bundle root.");
            var root = manifest.RootElement;
            var packageId = OptionalString(root, "packageId") ?? OptionalString(root, "id") ?? string.Empty;
            var version = OptionalString(root, "version") ?? string.Empty;
            packageId = ValidateToken(packageId, "package ID", 128);
            version = ValidateToken(version, "package version", 64);

            entries.Sort((left, right) => StringComparer.Ordinal.Compare(left.Path, right.Path));
            var canonical = new StringBuilder();
            foreach (var entry in entries)
                canonical.Append(entry.Path).Append('\n').Append(entry.Size).Append('\n').Append(entry.Sha256).Append('\n');
            var digestBytes = SHA256.HashData(Encoding.UTF8.GetBytes(canonical.ToString()));
            return new PackageContent(packageId, version, Convert.ToHexString(digestBytes).ToLowerInvariant());
        }
        finally
        {
            manifest?.Dispose();
        }
    }

    internal static string CanonicalSignedPayload(string keyId, string packageId, string version, string contentSha256)
        => JsonSerializer.Serialize(new SortedDictionary<string, object?>(StringComparer.Ordinal)
        {
            ["algorithm"] = "Ed25519",
            ["contentSha256"] = NormalizeDigest(contentSha256),
            ["keyId"] = keyId,
            ["packageId"] = packageId,
            ["schema"] = SignatureSchema,
            ["version"] = version
        });

    internal static string NormalizeEntryPath(string path) => (path ?? string.Empty).Replace('\\', '/');

    private static string HashEntryBounded(ZipArchiveEntry entry)
    {
        using var stream = entry.Open();
        using var hash = System.Security.Cryptography.IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[HashBufferBytes];
        long actual = 0;
        while (true)
        {
            var read = stream.Read(buffer, 0, buffer.Length);
            if (read <= 0) break;
            actual = checked(actual + read);
            if (actual > MaxEntryBytes || actual > entry.Length)
                throw new DesktopPackageException("PACKAGE_ENTRY_LENGTH_MISMATCH", $"Package entry expanded beyond its declared length: {entry.FullName}");
            hash.AppendData(buffer, 0, read);
        }
        if (actual != entry.Length)
            throw new DesktopPackageException("PACKAGE_ENTRY_LENGTH_MISMATCH", $"Package entry length does not match archive metadata: {entry.FullName}");
        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    private static byte[] ReadEntryBytesBounded(ZipArchiveEntry entry, long maxBytes, string label)
    {
        if (entry.Length < 0 || entry.Length > maxBytes)
            throw new DesktopPackageException("PACKAGE_ENTRY_TOO_LARGE", $"Package {label} exceeds {maxBytes} bytes.");
        using var stream = entry.Open();
        using var buffer = new MemoryStream((int)Math.Min(entry.Length, int.MaxValue));
        var chunk = new byte[64 * 1024];
        long actual = 0;
        while (true)
        {
            var read = stream.Read(chunk, 0, chunk.Length);
            if (read <= 0) break;
            actual = checked(actual + read);
            if (actual > maxBytes || actual > entry.Length)
                throw new DesktopPackageException("PACKAGE_ENTRY_LENGTH_MISMATCH", $"Package {label} expanded beyond its declared length.");
            buffer.Write(chunk, 0, read);
        }
        if (actual != entry.Length)
            throw new DesktopPackageException("PACKAGE_ENTRY_LENGTH_MISMATCH", $"Package {label} length does not match archive metadata.");
        return buffer.ToArray();
    }

    private static string? OptionalString(JsonElement node, string name)
        => node.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()?.Trim() : null;

    private static string ValidateToken(string? value, string label, int maxLength)
    {
        var token = (value ?? string.Empty).Trim();
        if (token.Length is < 1 || token.Length > maxLength || token.Any(char.IsControl))
            throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", $"Embedded package signature requires a valid {label}.");
        return token;
    }

    private static string NormalizeDigest(string? value)
    {
        var digest = (value ?? string.Empty).Trim().ToLowerInvariant().Replace("sha256-", "").Replace("sha256:", "");
        if (digest.Length != 64 || digest.Any(ch => !Uri.IsHexDigit(ch)))
            throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", "Embedded package contentSha256 must be a 64-character SHA-256 hex digest.");
        return digest;
    }

    private static bool FixedDigestEquals(string left, string right)
        => CryptographicOperations.FixedTimeEquals(Convert.FromHexString(left), Convert.FromHexString(right));

    private sealed record ContentEntry(string Path, long Size, string Sha256);
    private sealed record SignatureEnvelope(string? Schema, string? Algorithm, string? KeyId, string? PackageId, string? Version, string? ContentSha256, string? Signature);
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { PropertyNameCaseInsensitive = true };
}