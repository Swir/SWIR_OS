#if SWIR_PACKAGE_SIGNATURE_TOOL
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using NSec.Cryptography;

namespace Swir.Desktop.Host;

internal static class DesktopPackageSignatureTool
{
    private static readonly DateTimeOffset DeterministicTimestamp = new(2000, 1, 1, 0, 0, 0, TimeSpan.Zero);

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length == 4 && string.Equals(args[0], "sign", StringComparison.OrdinalIgnoreCase))
            {
                using var key = ImportPrivateKey(args[3]);
                SignPackage(args[1], args[2], key);
                Console.WriteLine("SWIR package signature written.");
                return 0;
            }

            if (args.Length == 4 && string.Equals(args[0], "trust-root", StringComparison.OrdinalIgnoreCase))
            {
                using var key = ImportPrivateKey(args[2]);
                WriteTrustRoot(args[1], key, args[3]);
                Console.WriteLine("SWIR package trust root written.");
                return 0;
            }

            if (args.Length == 3 && string.Equals(args[0], "verify", StringComparison.OrdinalIgnoreCase))
            {
                VerifyPackage(args[1], args[2]);
                return 0;
            }

            Console.Error.WriteLine("Usage:");
            Console.Error.WriteLine("  sign <bundle.swirapp> <keyId> <raw-private-key-base64-file>");
            Console.Error.WriteLine("  trust-root <keyId> <raw-private-key-base64-file> <output-json>");
            Console.Error.WriteLine("  verify <bundle.swirapp> <trust-roots-json>");
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Package signature operation failed: {ex.Message}");
            return 1;
        }
    }

    internal static void SignPackage(string bundlePath, string keyId, Key key)
    {
        if (string.IsNullOrWhiteSpace(bundlePath) || !File.Exists(bundlePath))
            throw new DesktopPackageException("PACKAGE_NOT_FOUND", "SWIR package bundle does not exist.");
        if (!string.Equals(Path.GetExtension(bundlePath), ".swirapp", StringComparison.OrdinalIgnoreCase))
            throw new DesktopPackageException("PACKAGE_FORMAT_INVALID", "Package signer accepts only .swirapp bundles.");
        keyId = ValidateKeyId(keyId);

        // Compute the signed content from a read-only archive. ZipArchive Update mode
        // may make Length unavailable after write-capable entry access, which weakens
        // bounded hashing and caused the signer self-test to fail on hosted Windows.
        DesktopPackageSignatureVerifier.PackageContent content;
        using (var source = ZipFile.OpenRead(bundlePath))
            content = DesktopPackageSignatureVerifier.ComputeContent(source);

        var payload = DesktopPackageSignatureVerifier.CanonicalSignedPayload(keyId, content.PackageId, content.Version, content.ContentSha256);
        var signature = SignatureAlgorithm.Ed25519.Sign(key, Encoding.UTF8.GetBytes(payload));
        var envelope = JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema = DesktopPackageSignatureVerifier.SignatureSchema,
            algorithm = "Ed25519",
            keyId,
            packageId = content.PackageId,
            version = content.Version,
            contentSha256 = content.ContentSha256,
            signature = Convert.ToBase64String(signature)
        }, new JsonSerializerOptions { WriteIndented = true });

        using var archive = ZipFile.Open(bundlePath, ZipArchiveMode.Update);
        var existing = archive.Entries
            .Where(entry => string.Equals(DesktopPackageSignatureVerifier.NormalizeEntryPath(entry.FullName), DesktopPackageSignatureVerifier.SignatureEntryName, StringComparison.Ordinal))
            .ToArray();
        foreach (var entry in existing) entry.Delete();

        var signatureEntry = archive.CreateEntry(DesktopPackageSignatureVerifier.SignatureEntryName, CompressionLevel.NoCompression);
        signatureEntry.LastWriteTime = DeterministicTimestamp;
        signatureEntry.ExternalAttributes = 0;
        using var output = signatureEntry.Open();
        output.Write(envelope);
    }

    internal static void WriteTrustRoot(string keyId, Key key, string outputPath)
    {
        keyId = ValidateKeyId(keyId);
        if (string.IsNullOrWhiteSpace(outputPath))
            throw new DesktopPackageException("PACKAGE_TRUST_ROOTS_INVALID", "Package trust-root output path is required.");

        var fullPath = Path.GetFullPath(outputPath);
        var directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        var publicKey = key.PublicKey.Export(KeyBlobFormat.RawPublicKey);
        if (publicKey.Length != 32)
            throw new DesktopPackageException("PACKAGE_SIGNATURE_KEY_INVALID", "Ed25519 package signing public key must be 32 bytes.");

        var json = JsonSerializer.Serialize(new
        {
            schema = DesktopPackageTrustRootStore.Schema,
            requireSignedPackages = true,
            roots = new[]
            {
                new
                {
                    keyId,
                    name = "SWIR Desktop package signing root",
                    algorithm = "Ed25519",
                    format = "raw",
                    publicKey = Convert.ToBase64String(publicKey),
                    scope = new[] { "package:swirapp" },
                    enabled = true
                }
            }
        }, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(fullPath, json + Environment.NewLine, new UTF8Encoding(false));
    }

    internal static DesktopPackageSignatureVerifier.VerificationResult VerifyPackage(string bundlePath, string trustRootsPath)
    {
        if (string.IsNullOrWhiteSpace(trustRootsPath) || !File.Exists(trustRootsPath))
            throw new DesktopPackageException("PACKAGE_TRUST_ROOTS_MISSING", "Package trust-root file does not exist.");

        var previous = Environment.GetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS");
        try
        {
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", Path.GetFullPath(trustRootsPath));
            var provisioned = DesktopPackageTrustRootStore.LoadProvisioned();
            if (!provisioned.RequireSignedPackages || provisioned.Roots.Count == 0)
                throw new DesktopPackageException("PACKAGE_TRUST_ROOT_REQUIRED", "Verifier requires a fail-closed package trust-root policy.");

            var result = new DesktopPackageSignatureVerifier(provisioned.Roots).Verify(bundlePath, requireSignature: true);
            if (!result.Signed || !result.Verified || string.IsNullOrWhiteSpace(result.KeyId))
                throw new DesktopPackageException("PACKAGE_BAD_SIGNATURE", "Package did not produce verified signed provenance.");

            Console.WriteLine(JsonSerializer.Serialize(new
            {
                verified = true,
                result.KeyId,
                result.PackageId,
                result.Version,
                result.ContentSha256
            }));
            return result;
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", previous);
        }
    }

    private static Key ImportPrivateKey(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            throw new DesktopPackageException("PACKAGE_SIGNATURE_KEY_INVALID", "Package signing private-key file does not exist.");
        byte[]? privateKey = null;
        try
        {
            privateKey = Convert.FromBase64String(File.ReadAllText(path).Trim());
            return Key.Import(
                SignatureAlgorithm.Ed25519,
                privateKey,
                KeyBlobFormat.RawPrivateKey,
                new KeyCreationParameters { ExportPolicy = KeyExportPolicies.None });
        }
        catch (FormatException ex)
        {
            throw new DesktopPackageException("PACKAGE_SIGNATURE_KEY_INVALID", $"Package signing private key is not canonical base64: {ex.Message}");
        }
        finally
        {
            if (privateKey is not null)
                System.Security.Cryptography.CryptographicOperations.ZeroMemory(privateKey);
        }
    }

    private static string ValidateKeyId(string? value)
    {
        var keyId = (value ?? string.Empty).Trim();
        if (keyId.Length is < 1 or > 128 || keyId.Any(char.IsControl) || keyId.Any(ch => !(char.IsLetterOrDigit(ch) || ch is '.' or '_' or '-')))
            throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", "Package signer key ID is invalid.");
        return keyId;
    }
}
#endif
