using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal sealed class DesktopAppPackageInstaller
{
    private const string Contract = "swir.desktop-package-payload/1.0";
    private const int MaxEntries = 2048;
    private const long MaxEntryBytes = 64L * 1024 * 1024;
    private const long MaxExpandedBytes = 256L * 1024 * 1024;
    private readonly string _packagesRoot;
    private readonly string _stagingRoot;

    public DesktopAppPackageInstaller(string dataRoot)
    {
        var root = Path.Combine(dataRoot, "Packages");
        _packagesRoot = Path.Combine(root, "Installed");
        _stagingRoot = Path.Combine(root, ".staging");
        Directory.CreateDirectory(_packagesRoot);
        Directory.CreateDirectory(_stagingRoot);
        RecoverInterruptedState();
    }

    public object Describe() => new
    {
        schema = Contract,
        provider = "desktop-native",
        format = ".swirapp",
        integrity = "sha256-required",
        trustProvenance = "deployment-recorded",
        signedCatalogProvenance = true,
        manifestSchema = "swir.app/1.0",
        stagedHealthVerification = true,
        startupRecovery = true,
        transactionalSlots = true,
        rollback = true,
        maxEntries = MaxEntries,
        maxEntryBytes = MaxEntryBytes,
        maxExpandedBytes = MaxExpandedBytes
    };

    public object Install(string bundlePath, string expectedSha256) =>
        Install(bundlePath, expectedSha256, DesktopPackageTrustProof.DirectSha256());

    internal object Install(string bundlePath, string expectedSha256, DesktopPackageTrustProof trustProof)
    {
        var trust = ValidateTrustProof(trustProof);
        if (!File.Exists(bundlePath)) throw new DesktopPackageException("PACKAGE_NOT_FOUND", "SWIR package bundle does not exist.");
        if (!string.Equals(Path.GetExtension(bundlePath), ".swirapp", StringComparison.OrdinalIgnoreCase))
            throw new DesktopPackageException("PACKAGE_FORMAT_INVALID", "Desktop payload installer accepts only .swirapp bundles.");

        var expected = NormalizeHash(expectedSha256);
        var actual = ComputeSha256(bundlePath);
        if (!CryptographicOperations.FixedTimeEquals(Convert.FromHexString(expected), Convert.FromHexString(actual)))
            throw new DesktopPackageException("PACKAGE_HASH_MISMATCH", "SWIR package SHA-256 does not match trusted metadata.");

        var stage = Path.Combine(_stagingRoot, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        try
        {
            PackageManifest manifest;
            using (var archive = ZipFile.OpenRead(bundlePath))
            {
                ValidateArchive(archive);
                ExtractArchive(archive, stage);
                manifest = ReadManifest(stage);
            }

            var health = ValidateStagedPackage(stage, manifest);
            var packageRoot = Path.Combine(_packagesRoot, health.PackageId);
            var current = Path.Combine(packageRoot, "Current");
            var previous = Path.Combine(packageRoot, "Previous");
            var incoming = Path.Combine(packageRoot, ".incoming-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(packageRoot);
            Directory.Move(stage, incoming);

            var hadCurrent = Directory.Exists(current);
            try
            {
                if (Directory.Exists(previous)) Directory.Delete(previous, true);
                if (hadCurrent) Directory.Move(current, previous);
                Directory.Move(incoming, current);
            }
            catch
            {
                if (Directory.Exists(incoming)) Directory.Delete(incoming, true);
                if (!Directory.Exists(current) && Directory.Exists(previous)) Directory.Move(previous, current);
                throw;
            }

            var deployment = new DeploymentRecord(
                Contract,
                health.PackageId,
                health.Version,
                actual,
                DateTimeOffset.UtcNow,
                hadCurrent,
                Directory.Exists(previous),
                health.Type,
                health.Entry,
                trust.Mode,
                trust.SignatureVerified,
                trust.KeyId,
                trust.CatalogSequence,
                trust.CatalogVersion,
                trust.ExpiresAt);
            WriteDeployment(current, deployment);
            return new
            {
                ok = true,
                schema = Contract,
                packageId = health.PackageId,
                version = health.Version,
                type = health.Type,
                entry = health.Entry,
                bundleSha256 = actual,
                state = hadCurrent ? "UPDATED" : "INSTALLED",
                health = "VERIFIED",
                trustMode = trust.Mode,
                signatureVerified = trust.SignatureVerified,
                signerKeyId = trust.KeyId,
                catalogSequence = trust.CatalogSequence,
                catalogVersion = trust.CatalogVersion,
                trustExpiresAt = trust.ExpiresAt,
                rollbackAvailable = Directory.Exists(previous)
            };
        }
        catch (DesktopPackageException) { throw; }
        catch (InvalidDataException ex) { throw new DesktopPackageException("PACKAGE_ARCHIVE_INVALID", ex.Message); }
        catch (Exception ex) { throw new DesktopPackageException("PACKAGE_INSTALL_FAILED", ex.Message); }
        finally
        {
            if (Directory.Exists(stage)) Directory.Delete(stage, true);
        }
    }

    public object Rollback(string packageId)
    {
        packageId = ValidatePackageId(packageId);
        var packageRoot = Path.Combine(_packagesRoot, packageId);
        var current = Path.Combine(packageRoot, "Current");
        var previous = Path.Combine(packageRoot, "Previous");
        if (!Directory.Exists(previous)) throw new DesktopPackageException("PACKAGE_ROLLBACK_UNAVAILABLE", "No previous payload slot is available.");

        var swap = Path.Combine(packageRoot, ".rollback-" + Guid.NewGuid().ToString("N"));
        try
        {
            if (Directory.Exists(current)) Directory.Move(current, swap);
            Directory.Move(previous, current);
            if (Directory.Exists(swap)) Directory.Move(swap, previous);
            var deployment = ReadDeployment(current);
            return new
            {
                ok = true,
                schema = Contract,
                packageId,
                version = deployment?.Version,
                type = deployment?.Type,
                entry = deployment?.Entry,
                state = "ROLLED_BACK",
                health = deployment is null ? "UNKNOWN" : "VERIFIED",
                trustMode = deployment?.TrustMode,
                signatureVerified = deployment?.SignatureVerified ?? false,
                signerKeyId = deployment?.SignerKeyId,
                catalogSequence = deployment?.CatalogSequence,
                catalogVersion = deployment?.CatalogVersion,
                trustExpiresAt = deployment?.TrustExpiresAt,
                rollbackAvailable = Directory.Exists(previous)
            };
        }
        catch (Exception ex)
        {
            if (!Directory.Exists(current) && Directory.Exists(previous)) Directory.Move(previous, current);
            if (Directory.Exists(swap) && !Directory.Exists(previous)) Directory.Move(swap, previous);
            throw new DesktopPackageException("PACKAGE_ROLLBACK_FAILED", ex.Message);
        }
    }

    public object Status(string packageId)
    {
        packageId = ValidatePackageId(packageId);
        var packageRoot = Path.Combine(_packagesRoot, packageId);
        var current = Path.Combine(packageRoot, "Current");
        var previous = Path.Combine(packageRoot, "Previous");
        var deployment = Directory.Exists(current) ? ReadDeployment(current) : null;
        return new
        {
            schema = Contract,
            packageId,
            installed = Directory.Exists(current),
            version = deployment?.Version,
            type = deployment?.Type,
            entry = deployment?.Entry,
            health = deployment is null ? "UNKNOWN" : "VERIFIED",
            bundleSha256 = deployment?.BundleSha256,
            trustMode = deployment?.TrustMode,
            signatureVerified = deployment?.SignatureVerified ?? false,
            signerKeyId = deployment?.SignerKeyId,
            catalogSequence = deployment?.CatalogSequence,
            catalogVersion = deployment?.CatalogVersion,
            trustExpiresAt = deployment?.TrustExpiresAt,
            rollbackAvailable = Directory.Exists(previous)
        };
    }

    private void RecoverInterruptedState()
    {
        foreach (var stage in Directory.EnumerateDirectories(_stagingRoot))
        {
            try { Directory.Delete(stage, true); } catch { }
        }

        foreach (var packageRoot in Directory.EnumerateDirectories(_packagesRoot))
        {
            foreach (var incoming in Directory.EnumerateDirectories(packageRoot, ".incoming-*"))
            {
                try { Directory.Delete(incoming, true); } catch { }
            }
            foreach (var rollback in Directory.EnumerateDirectories(packageRoot, ".rollback-*"))
            {
                var current = Path.Combine(packageRoot, "Current");
                var previous = Path.Combine(packageRoot, "Previous");
                try
                {
                    if (!Directory.Exists(current) && Directory.Exists(previous))
                        Directory.Move(previous, current);
                    if (Directory.Exists(rollback) && !Directory.Exists(previous))
                        Directory.Move(rollback, previous);
                    else if (Directory.Exists(rollback))
                        Directory.Delete(rollback, true);
                }
                catch { }
            }

            var currentSlot = Path.Combine(packageRoot, "Current");
            var previousSlot = Path.Combine(packageRoot, "Previous");
            if (!Directory.Exists(currentSlot) && Directory.Exists(previousSlot))
            {
                try { Directory.Move(previousSlot, currentSlot); } catch { }
            }
        }
    }

    private static DesktopPackageTrustProof ValidateTrustProof(DesktopPackageTrustProof? trust)
    {
        if (trust is null)
            throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", "Package trust provenance is required.");

        var mode = (trust.Mode ?? string.Empty).Trim();
        if (mode is "DIRECT_SHA256" or "LEGACY_SHA_UNTIL_ROOT_PROVISIONED")
        {
            if (trust.SignatureVerified || trust.KeyId is not null || trust.CatalogSequence is not null || trust.CatalogVersion is not null || trust.ExpiresAt is not null)
                throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", "Unsigned package trust modes cannot carry signed catalog provenance.");
            return trust with { Mode = mode };
        }

        if (!string.Equals(mode, "SIGNED_CATALOG", StringComparison.Ordinal))
            throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", "Unsupported package trust provenance mode.");
        if (!trust.SignatureVerified)
            throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", "Signed catalog provenance must be signature verified.");
        var keyId = ValidateTrustToken(trust.KeyId, "signer key ID", 128);
        var catalogVersion = ValidateTrustToken(trust.CatalogVersion, "catalog version", 128);
        if (trust.CatalogSequence is null or <= 0)
            throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", "Signed catalog provenance requires a positive catalog sequence.");
        if (trust.ExpiresAt is null)
            throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", "Signed catalog provenance requires an expiry timestamp.");
        if (trust.ExpiresAt <= DateTimeOffset.UtcNow)
            throw new DesktopPackageException("PACKAGE_TRUST_EXPIRED", "Signed catalog authorization expired before package installation completed.");
        return trust with { Mode = mode, KeyId = keyId, CatalogVersion = catalogVersion };
    }

    private static string ValidateTrustToken(string? value, string label, int maxLength)
    {
        var token = (value ?? string.Empty).Trim();
        if (token.Length is < 1 || token.Length > maxLength || token.Any(char.IsControl))
            throw new DesktopPackageException("PACKAGE_TRUST_PROOF_INVALID", $"Signed catalog provenance requires a valid {label}.");
        return token;
    }

    private static StagedPackageHealth ValidateStagedPackage(string stage, PackageManifest manifest)
    {
        var packageId = ValidatePackageId(manifest.PackageId ?? manifest.Id);
        var version = ValidateVersion(manifest.Version);
        RequireText(manifest.Name, "name");
        RequireText(manifest.Author, "author");
        var type = RequireText(manifest.Type, "type");
        var entry = ValidateEntry(manifest.Entry);
        var stageRoot = Path.GetFullPath(stage) + Path.DirectorySeparatorChar;
        var entryPath = Path.GetFullPath(Path.Combine(stage, entry.Replace('/', Path.DirectorySeparatorChar)));
        if (!entryPath.StartsWith(stageRoot, StringComparison.OrdinalIgnoreCase))
            throw new DesktopPackageException("PACKAGE_ENTRY_INVALID", "Package entry must remain inside the staged payload.");
        if (!File.Exists(entryPath))
            throw new DesktopPackageException("PACKAGE_ENTRY_MISSING", $"Declared package entry does not exist: {entry}");
        var attributes = File.GetAttributes(entryPath);
        if ((attributes & FileAttributes.ReparsePoint) != 0)
            throw new DesktopPackageException("PACKAGE_ENTRY_INVALID", "Package entry cannot be a reparse point.");
        return new StagedPackageHealth(packageId, version, type, entry);
    }

    private static void ValidateArchive(ZipArchive archive)
    {
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaxEntries)
            throw new DesktopPackageException("PACKAGE_ARCHIVE_LIMIT", $"Package must contain between 1 and {MaxEntries} entries.");

        long total = 0;
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in archive.Entries)
        {
            var path = entry.FullName.Replace('\\', '/');
            if (string.IsNullOrWhiteSpace(path) || path.StartsWith('/') || path.Contains(':'))
                throw new DesktopPackageException("PACKAGE_PATH_INVALID", $"Unsafe archive path: {entry.FullName}");
            var segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
            if (segments.Any(segment => segment is "." or ".."))
                throw new DesktopPackageException("PACKAGE_PATH_TRAVERSAL", $"Archive traversal blocked: {entry.FullName}");
            if (!seen.Add(string.Join('/', segments)))
                throw new DesktopPackageException("PACKAGE_DUPLICATE_PATH", $"Duplicate package path: {entry.FullName}");

            var unixMode = (entry.ExternalAttributes >> 16) & 0xF000;
            if (unixMode == 0xA000)
                throw new DesktopPackageException("PACKAGE_SYMLINK_BLOCKED", $"Symbolic links are not permitted in .swirapp payloads: {entry.FullName}");
            if (entry.Length > MaxEntryBytes)
                throw new DesktopPackageException("PACKAGE_ENTRY_TOO_LARGE", $"Package entry exceeds {MaxEntryBytes} bytes: {entry.FullName}");
            total = checked(total + entry.Length);
            if (total > MaxExpandedBytes)
                throw new DesktopPackageException("PACKAGE_EXPANDED_TOO_LARGE", $"Expanded package exceeds {MaxExpandedBytes} bytes.");
        }
    }

    private static void ExtractArchive(ZipArchive archive, string destination)
    {
        var root = Path.GetFullPath(destination) + Path.DirectorySeparatorChar;
        long expanded = 0;
        var buffer = new byte[128 * 1024];
        foreach (var entry in archive.Entries)
        {
            var relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
            var target = Path.GetFullPath(Path.Combine(destination, relative));
            if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new DesktopPackageException("PACKAGE_PATH_TRAVERSAL", $"Archive traversal blocked: {entry.FullName}");
            if (entry.FullName.EndsWith('/')) { Directory.CreateDirectory(target); continue; }
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            using var source = entry.Open();
            using var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            long entryBytes = 0;
            while (true)
            {
                var read = source.Read(buffer, 0, buffer.Length);
                if (read <= 0) break;
                entryBytes = checked(entryBytes + read);
                expanded = checked(expanded + read);
                if (entryBytes > MaxEntryBytes)
                    throw new DesktopPackageException("PACKAGE_ENTRY_TOO_LARGE", $"Package entry exceeds extraction limit: {entry.FullName}");
                if (expanded > MaxExpandedBytes)
                    throw new DesktopPackageException("PACKAGE_EXPANDED_TOO_LARGE", "Expanded package exceeds extraction limit.");
                output.Write(buffer, 0, read);
            }
            output.Flush(true);
        }
    }

    private static string ComputeSha256(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
    }

    private static PackageManifest ReadManifest(string root)
    {
        var path = Path.Combine(root, "swir-package.json");
        if (!File.Exists(path)) throw new DesktopPackageException("PACKAGE_MANIFEST_MISSING", "swir-package.json is required at the bundle root.");
        PackageManifest? manifest;
        try { manifest = JsonSerializer.Deserialize<PackageManifest>(File.ReadAllText(path), JsonOptions); }
        catch (JsonException ex) { throw new DesktopPackageException("PACKAGE_MANIFEST_INVALID", ex.Message); }
        if (manifest is null || !string.Equals(manifest.Schema, "swir.app/1.0", StringComparison.Ordinal))
            throw new DesktopPackageException("PACKAGE_MANIFEST_INVALID", "Package manifest schema must be swir.app/1.0.");
        return manifest;
    }

    private static string ValidatePackageId(string? value)
    {
        var id = (value ?? string.Empty).Trim();
        if (id.Length is < 1 or > 128 || id.Any(ch => !(char.IsLetterOrDigit(ch) || ch is '.' or '-' or '_')))
            throw new DesktopPackageException("PACKAGE_ID_INVALID", "Package identity contains unsupported characters.");
        return id;
    }

    private static string ValidateVersion(string? value)
    {
        var version = (value ?? string.Empty).Trim();
        if (version.Length is < 1 or > 64 || version.Any(ch => !(char.IsLetterOrDigit(ch) || ch is '.' or '-' or '+' or '_')))
            throw new DesktopPackageException("PACKAGE_VERSION_INVALID", "Package version contains unsupported characters.");
        return version;
    }

    private static string RequireText(string? value, string field)
    {
        var text = (value ?? string.Empty).Trim();
        if (text.Length is < 1 or > 256)
            throw new DesktopPackageException("PACKAGE_MANIFEST_INVALID", $"Package manifest field '{field}' is required and must be at most 256 characters.");
        return text;
    }

    private static string ValidateEntry(string? value)
    {
        var entry = (value ?? string.Empty).Trim().Replace('\\', '/');
        if (entry.StartsWith("./", StringComparison.Ordinal)) entry = entry[2..];
        if (string.IsNullOrWhiteSpace(entry) || entry.StartsWith('/') || entry.Contains(':'))
            throw new DesktopPackageException("PACKAGE_ENTRY_INVALID", "Package entry must be a relative payload path.");
        var segments = entry.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length == 0 || segments.Any(segment => segment is "." or ".."))
            throw new DesktopPackageException("PACKAGE_ENTRY_INVALID", "Package entry traversal is not permitted.");
        return string.Join('/', segments);
    }

    private static string NormalizeHash(string value)
    {
        var hash = (value ?? string.Empty).Trim().ToLowerInvariant();
        if (hash.Length != 64 || hash.Any(ch => !Uri.IsHexDigit(ch)))
            throw new DesktopPackageException("PACKAGE_HASH_INVALID", "A 64-character SHA-256 hash is required.");
        return hash;
    }

    private static void WriteDeployment(string current, DeploymentRecord deployment)
    {
        var path = Path.Combine(current, ".swir-deployment.json");
        var temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(deployment, JsonOptions));
        using (var stream = new FileStream(temp, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) stream.Flush(true);
        File.Move(temp, path, true);
    }

    private static DeploymentRecord? ReadDeployment(string current)
    {
        var path = Path.Combine(current, ".swir-deployment.json");
        if (!File.Exists(path)) return null;
        try { return JsonSerializer.Deserialize<DeploymentRecord>(File.ReadAllText(path), JsonOptions); }
        catch { return null; }
    }

    private sealed record PackageManifest(string? Schema, string? Id, string? PackageId, string? Name, string? Version, string? Author, string? Type, string? Entry);
    private sealed record StagedPackageHealth(string PackageId, string Version, string Type, string Entry);
    private sealed record DeploymentRecord(
        string Schema,
        string PackageId,
        string Version,
        string BundleSha256,
        DateTimeOffset InstalledAt,
        bool Updated,
        bool RollbackAvailable,
        string Type,
        string Entry,
        string TrustMode,
        bool SignatureVerified,
        string? SignerKeyId,
        long? CatalogSequence,
        string? CatalogVersion,
        DateTimeOffset? TrustExpiresAt);
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { PropertyNameCaseInsensitive = true, WriteIndented = true };
}

internal sealed record DesktopPackageTrustProof(
    string Mode,
    bool SignatureVerified,
    string? KeyId,
    long? CatalogSequence,
    string? CatalogVersion,
    DateTimeOffset? ExpiresAt)
{
    public static DesktopPackageTrustProof DirectSha256() => new("DIRECT_SHA256", false, null, null, null, null);
    public static DesktopPackageTrustProof LegacySha() => new("LEGACY_SHA_UNTIL_ROOT_PROVISIONED", false, null, null, null, null);
    public static DesktopPackageTrustProof SignedCatalog(string keyId, long sequence, string catalogVersion, DateTimeOffset expiresAt) =>
        new("SIGNED_CATALOG", true, keyId, sequence, catalogVersion, expiresAt);
}

internal sealed class DesktopPackageException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}