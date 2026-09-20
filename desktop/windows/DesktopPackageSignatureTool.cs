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
        if (args.Length != 4 || !string.Equals(args[0], "sign", StringComparison.OrdinalIgnoreCase))
        {
            Console.Error.WriteLine("Usage: sign <bundle.swirapp> <keyId> <raw-private-key-base64-file>");
            return 2;
        }

        try
        {
            var privateKey = Convert.FromBase64String(File.ReadAllText(args[3]).Trim());
            using var key = Key.Import(
                SignatureAlgorithm.Ed25519,
                privateKey,
                KeyBlobFormat.RawPrivateKey,
                new KeyCreationParameters { ExportPolicy = KeyExportPolicies.None });
            SignPackage(args[1], args[2], key);
            Console.WriteLine("SWIR package signature written.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Package signing failed: {ex.Message}");
            return 1;
        }
    }

    internal static void SignPackage(string bundlePath, string keyId, Key key)
    {
        if (string.IsNullOrWhiteSpace(bundlePath) || !File.Exists(bundlePath))
            throw new DesktopPackageException("PACKAGE_NOT_FOUND", "SWIR package bundle does not exist.");
        if (!string.Equals(Path.GetExtension(bundlePath), ".swirapp", StringComparison.OrdinalIgnoreCase))
            throw new DesktopPackageException("PACKAGE_FORMAT_INVALID", "Package signer accepts only .swirapp bundles.");
        keyId = (keyId ?? string.Empty).Trim();
        if (keyId.Length is < 1 or > 128 || keyId.Any(char.IsControl))
            throw new DesktopPackageException("PACKAGE_SIGNATURE_INVALID", "Package signer key ID is invalid.");

        using var archive = ZipFile.Open(bundlePath, ZipArchiveMode.Update);
        var existing = archive.Entries
            .Where(entry => string.Equals(DesktopPackageSignatureVerifier.NormalizeEntryPath(entry.FullName), DesktopPackageSignatureVerifier.SignatureEntryName, StringComparison.Ordinal))
            .ToArray();
        foreach (var entry in existing) entry.Delete();

        var content = DesktopPackageSignatureVerifier.ComputeContent(archive);
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

        var signatureEntry = archive.CreateEntry(DesktopPackageSignatureVerifier.SignatureEntryName, CompressionLevel.NoCompression);
        signatureEntry.LastWriteTime = DeterministicTimestamp;
        signatureEntry.ExternalAttributes = 0;
        using var output = signatureEntry.Open();
        output.Write(envelope);
    }
}
