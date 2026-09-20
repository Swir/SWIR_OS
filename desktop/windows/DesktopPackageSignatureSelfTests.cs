using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using NSec.Cryptography;

namespace Swir.Desktop.Host;

internal static class DesktopPackageSignatureSelfTests
{
    private const string Shell = "swir.system.shell";
    private const string TrustedKeyId = "desktop-package-root";

    public static int Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "swir-package-signature-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var previousPackageRoots = Environment.GetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS");
        var previousCatalogRoots = Environment.GetEnvironmentVariable("SWIR_CATALOG_TRUST_ROOTS");
        try
        {
            using var trustedKey = Key.Create(SignatureAlgorithm.Ed25519, new KeyCreationParameters { ExportPolicy = KeyExportPolicies.AllowPlaintextExport });
            using var unknownKey = Key.Create(SignatureAlgorithm.Ed25519, new KeyCreationParameters { ExportPolicy = KeyExportPolicies.AllowPlaintextExport });
            var rootsPath = Path.Combine(root, "package-trust-roots.json");
            WriteTrustRoots(rootsPath, trustedKey.PublicKey.Export(KeyBlobFormat.RawPublicKey), requireSigned: true);
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", rootsPath);
            Environment.SetEnvironmentVariable("SWIR_CATALOG_TRUST_ROOTS", Path.Combine(root, "missing-catalog-roots.json"));

            var signed = Path.Combine(root, "signed.swirapp");
            CreateBundle(signed, "swir.signature.valid", "1.0.0", "valid");
            DesktopPackageSignatureTool.SignPackage(signed, TrustedKeyId, trustedKey);
            var validContext = NewBridge(Path.Combine(root, "valid-data"));
            var describe = JsonSerializer.Serialize(validContext.Bridge.Describe());
            Require(describe.Contains("\"packageSignatureVerification\":true", StringComparison.Ordinal), "bridge must advertise package signature verification");
            Require(describe.Contains("\"packageSignatureRequired\":true", StringComparison.Ordinal), "test policy must require package signatures");
            Require(describe.Contains("\"packageSignatureTrustedRoots\":1", StringComparison.Ordinal), "test policy must expose one trusted package root");
            Install(validContext, signed);

            var tampered = Path.Combine(root, "tampered.swirapp");
            File.Copy(signed, tampered, overwrite: true);
            ReplacePayload(tampered, "tampered-after-signing");
            var tamperContext = NewBridge(Path.Combine(root, "tamper-data"));
            ExpectPackageCode(() => Install(tamperContext, tampered), "PACKAGE_CONTENT_DIGEST_MISMATCH");

            var unsigned = Path.Combine(root, "unsigned.swirapp");
            CreateBundle(unsigned, "swir.signature.unsigned", "1.0.0", "unsigned");
            var unsignedContext = NewBridge(Path.Combine(root, "unsigned-data"));
            ExpectPackageCode(() => Install(unsignedContext, unsigned), "PACKAGE_SIGNATURE_REQUIRED");

            var unknown = Path.Combine(root, "unknown.swirapp");
            CreateBundle(unknown, "swir.signature.unknown", "1.0.0", "unknown");
            DesktopPackageSignatureTool.SignPackage(unknown, "unknown-package-root", unknownKey);
            var unknownContext = NewBridge(Path.Combine(root, "unknown-data"));
            ExpectPackageCode(() => Install(unknownContext, unknown), "PACKAGE_SIGNATURE_UNKNOWN_KEY");

            var absolute = Path.Combine(root, "absolute-entry.swirapp");
            CreateBundle(absolute, "swir.signature.absolute", "1.0.0", "absolute");
            AddEntry(absolute, "/absolute.txt", "must-not-normalize-away-root");
            ExpectPackageCode(() => DesktopPackageSignatureTool.SignPackage(absolute, TrustedKeyId, trustedKey), "PACKAGE_PATH_INVALID");

            var duplicate = Path.Combine(root, "duplicate-entry.swirapp");
            CreateBundle(duplicate, "swir.signature.duplicate", "1.0.0", "duplicate");
            AddEntry(duplicate, "APP/INDEX.HTML", "case-insensitive-duplicate");
            ExpectPackageCode(() => DesktopPackageSignatureTool.SignPackage(duplicate, TrustedKeyId, trustedKey), "PACKAGE_DUPLICATE_PATH");

            var oversizedEnvelope = Path.Combine(root, "oversized-envelope.swirapp");
            CreateBundle(oversizedEnvelope, "swir.signature.oversized", "1.0.0", "oversized");
            AddEntry(oversizedEnvelope, DesktopPackageSignatureVerifier.SignatureEntryName, new string('x', 70 * 1024));
            var oversizedContext = NewBridge(Path.Combine(root, "oversized-data"));
            ExpectPackageCode(() => Install(oversizedContext, oversizedEnvelope), "PACKAGE_SIGNATURE_INVALID");

            var missingConfiguredRoots = Path.Combine(root, "missing-package-trust-roots.json");
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", missingConfiguredRoots);
            ExpectPackageCode(() => DesktopPackageTrustRootStore.LoadProvisioned(), "PACKAGE_TRUST_ROOTS_MISSING");
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", rootsPath);

            var optionalRootsPath = Path.Combine(root, "optional-package-trust-roots.json");
            WriteTrustRoots(optionalRootsPath, trustedKey.PublicKey.Export(KeyBlobFormat.RawPublicKey), requireSigned: false);
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", optionalRootsPath);
            var optional = Path.Combine(root, "optional-unsigned.swirapp");
            CreateBundle(optional, "swir.signature.optional", "1.0.0", "optional");
            Install(NewBridge(Path.Combine(root, "optional-data")), optional);

            Console.WriteLine("Desktop package signature and integrity self-tests passed.");
            return 0;
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", previousPackageRoots);
            Environment.SetEnvironmentVariable("SWIR_CATALOG_TRUST_ROOTS", previousCatalogRoots);
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private sealed record BridgeContext(DesktopPackageBridge Bridge, CapabilityBroker Capabilities);

    private static BridgeContext NewBridge(string dataRoot)
    {
        Directory.CreateDirectory(dataRoot);
        var capabilities = new CapabilityBroker();
        return new BridgeContext(new DesktopPackageBridge(capabilities, new DesktopAppPackageInstaller(dataRoot), null), capabilities);
    }

    private static void Install(BridgeContext context, string bundle)
    {
        using var registration = JsonDocument.Parse(JsonSerializer.Serialize(context.Capabilities.RegisterFile(bundle, Shell)));
        var token = registration.RootElement.GetProperty("token").GetString() ?? throw new Exception("Capability token missing.");
        var result = JsonSerializer.Serialize(context.Bridge.InstallFromCapability(token, Sha256(bundle), Shell));
        Require(result.Contains("\"ok\":true", StringComparison.Ordinal), "verified package install must succeed");
        ExpectBridgeCode(() => context.Capabilities.Describe(token, Shell), "CAPABILITY_INVALID");
    }

    private static void CreateBundle(string path, string packageId, string version, string payloadText)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Create);
        var manifest = archive.CreateEntry("swir-package.json", CompressionLevel.NoCompression);
        using (var writer = new StreamWriter(manifest.Open(), new UTF8Encoding(false)))
            writer.Write(JsonSerializer.Serialize(new
            {
                schema = "swir.app/1.0",
                id = packageId,
                packageId,
                name = "SWIR package signature test",
                version,
                author = "SWIR",
                type = "iframe",
                entry = "app/index.html",
                compatibility = new { minOS = "1.7.0", minSDK = "1.3.0", platformApi = 2, editions = new[] { "DESKTOP" } },
                dependencies = Array.Empty<object>(),
                optionalDependencies = Array.Empty<object>()
            }));
        var payload = archive.CreateEntry("app/index.html", CompressionLevel.NoCompression);
        using var payloadWriter = new StreamWriter(payload.Open(), new UTF8Encoding(false));
        payloadWriter.Write($"<!doctype html><title>{payloadText}</title>");
    }

    private static void AddEntry(string path, string entryName, string payloadText)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Update);
        var entry = archive.CreateEntry(entryName, CompressionLevel.NoCompression);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
        writer.Write(payloadText);
    }

    private static void ReplacePayload(string path, string payloadText)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Update);
        archive.GetEntry("app/index.html")?.Delete();
        var payload = archive.CreateEntry("app/index.html", CompressionLevel.NoCompression);
        using var writer = new StreamWriter(payload.Open(), new UTF8Encoding(false));
        writer.Write($"<!doctype html><title>{payloadText}</title>");
    }

    private static void WriteTrustRoots(string path, byte[] publicKey, bool requireSigned)
    {
        File.WriteAllText(path, JsonSerializer.Serialize(new
        {
            schema = DesktopPackageTrustRootStore.Schema,
            requireSignedPackages = requireSigned,
            roots = new[]
            {
                new
                {
                    keyId = TrustedKeyId,
                    name = "SWIR Desktop package test root",
                    algorithm = "Ed25519",
                    format = "raw",
                    publicKey = Convert.ToBase64String(publicKey),
                    scope = new[] { "package:swirapp" },
                    enabled = true
                }
            }
        }));
    }

    private static string Sha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static void ExpectPackageCode(Action action, string code)
    {
        try { action(); throw new Exception($"Expected {code}."); }
        catch (DesktopPackageException ex) when (ex.Code == code) { }
    }

    private static void ExpectBridgeCode(Action action, string code)
    {
        try { action(); throw new Exception($"Expected {code}."); }
        catch (BridgeException ex) when (ex.Code == code) { }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
}