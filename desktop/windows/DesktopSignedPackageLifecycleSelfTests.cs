using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using NSec.Cryptography;

namespace Swir.Desktop.Host;

internal static class DesktopSignedPackageLifecycleSelfTests
{
    private const string Shell = "swir.system.shell";
    private const string CatalogKeyId = "signed-lifecycle-catalog-root";
    private const string PackageKeyId = "signed-lifecycle-package-root";
    private sealed record BridgeContext(DesktopPackageBridge Bridge, CapabilityBroker Capabilities);

    public static int Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "swir-signed-lifecycle-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var previousCatalogRoots = Environment.GetEnvironmentVariable("SWIR_CATALOG_TRUST_ROOTS");
        var previousPackageRoots = Environment.GetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS");
        try
        {
            var packageData = Path.Combine(root, "packages");
            var trustData = Path.Combine(root, "trust");
            using var catalogSigningKey = Key.Create(SignatureAlgorithm.Ed25519, new KeyCreationParameters { ExportPolicy = KeyExportPolicies.AllowPlaintextExport });
            using var packageSigningKey = Key.Create(SignatureAlgorithm.Ed25519, new KeyCreationParameters { ExportPolicy = KeyExportPolicies.AllowPlaintextExport });
            var catalogRootsPath = Path.Combine(root, "catalog-trust-roots.json");
            var packageRootsPath = Path.Combine(root, "package-trust-roots.json");
            WriteCatalogTrustRoots(catalogRootsPath, catalogSigningKey.PublicKey.Export(KeyBlobFormat.RawPublicKey));
            WritePackageTrustRoots(packageRootsPath, packageSigningKey.PublicKey.Export(KeyBlobFormat.RawPublicKey));
            Environment.SetEnvironmentVariable("SWIR_CATALOG_TRUST_ROOTS", catalogRootsPath);
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", packageRootsPath);

            // Fail closed before touching install state: a correctly catalog-authorized but unsigned
            // package must be rejected when the shipping package-signature policy is provisioned.
            var unsigned = Path.Combine(root, "unsigned.swirapp");
            CreateBundle(unsigned, "swir.lifecycle.unsigned", "1.0.0", "unsigned");
            var context = NewBridge(packageData, trustData);
            var unsignedToken = Register(context.Capabilities, unsigned);
            var unsignedAuthorization = CreateSignedAuthorization(catalogSigningKey, "swir.lifecycle.unsigned", "1.0.0", Sha256(unsigned), 490);
            ExpectPackageCode(() => context.Bridge.InstallFromCapability(unsignedToken, unsignedAuthorization, Shell), "PACKAGE_SIGNATURE_REQUIRED");
            ExpectBridgeCode(() => context.Capabilities.Describe(unsignedToken, Shell), "CAPABILITY_INVALID");

            // A catalog can legitimately authorize the exact bytes of a tampered artifact, but the
            // independent embedded package signature must still catch payload modification.
            var tampered = Path.Combine(root, "tampered.swirapp");
            CreateBundle(tampered, "swir.lifecycle.tampered", "1.0.0", "before-tamper");
            SignPackage(tampered, packageSigningKey);
            TamperPayload(tampered, "after-tamper");
            context = NewBridge(packageData, trustData);
            var tamperedToken = Register(context.Capabilities, tampered);
            var tamperedAuthorization = CreateSignedAuthorization(catalogSigningKey, "swir.lifecycle.tampered", "1.0.0", Sha256(tampered), 491);
            ExpectPackageCode(() => context.Bridge.InstallFromCapability(tamperedToken, tamperedAuthorization, Shell), "PACKAGE_CONTENT_DIGEST_MISMATCH");
            ExpectBridgeCode(() => context.Capabilities.Describe(tamperedToken, Shell), "CAPABILITY_INVALID");

            var v1 = Path.Combine(root, "lifecycle-1.0.0.swirapp");
            var v2 = Path.Combine(root, "lifecycle-2.0.0.swirapp");
            CreateBundle(v1, "swir.lifecycle", "1.0.0", "v1");
            CreateBundle(v2, "swir.lifecycle", "2.0.0", "v2");
            SignPackage(v1, packageSigningKey);
            SignPackage(v2, packageSigningKey);

            // Signed catalog + independently signed package install, then reconstruct all native
            // bridge objects to model a Host restart with both trust policies still fail-closed.
            context = NewBridge(packageData, trustData);
            InstallSigned(context, v1, catalogSigningKey, "1.0.0", 501);
            AssertSignedStatus(context.Bridge, "1.0.0", 501);

            context = NewBridge(packageData, trustData);
            AssertSignedStatus(context.Bridge, "1.0.0", 501);

            // Signed update through a strictly newer catalog sequence.
            InstallSigned(context, v2, catalogSigningKey, "2.0.0", 502);
            AssertSignedStatus(context.Bridge, "2.0.0", 502);

            context = NewBridge(packageData, trustData);
            AssertSignedStatus(context.Bridge, "2.0.0", 502);

            // Native rollback must restore the previously verified payload and its exact catalog trust provenance.
            var rollback = JsonSerializer.Serialize(context.Bridge.Rollback("swir.lifecycle", Shell));
            Require(rollback.Contains("1.0.0", StringComparison.Ordinal), "rollback should restore v1 metadata");
            Require(rollback.Contains("\"signatureVerified\":true", StringComparison.Ordinal), "rollback should restore signed catalog trust status");
            Require(rollback.Contains("\"catalogSequence\":501", StringComparison.Ordinal), "rollback should restore v1 catalog sequence");

            context = NewBridge(packageData, trustData);
            AssertSignedStatus(context.Bridge, "1.0.0", 501);

            // Rolling the payload back must never roll the catalog trust high-water mark back.
            var staleToken = Register(context.Capabilities, v1);
            var staleAuthorization = CreateSignedAuthorization(catalogSigningKey, "swir.lifecycle", "1.0.0", Sha256(v1), 501);
            ExpectPackageCode(() => context.Bridge.InstallFromCapability(staleToken, staleAuthorization, Shell), "CATALOG_ROLLBACK_DETECTED");
            ExpectBridgeCode(() => context.Capabilities.Describe(staleToken, Shell), "CAPABILITY_INVALID");

            context = NewBridge(packageData, trustData);
            AssertSignedStatus(context.Bridge, "1.0.0", 501);

            Console.WriteLine("Signed Desktop catalog + package install/update/restart/rollback lifecycle self-tests passed.");
            return 0;
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWIR_CATALOG_TRUST_ROOTS", previousCatalogRoots);
            Environment.SetEnvironmentVariable("SWIR_PACKAGE_TRUST_ROOTS", previousPackageRoots);
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static BridgeContext NewBridge(string packageData, string trustData)
    {
        var verifier = DesktopCatalogTrustRootStore.CreateVerifier(trustData)
            ?? throw new Exception("Provisioned signed lifecycle catalog root was not loaded.");
        var capabilities = new CapabilityBroker();
        var bridge = new DesktopPackageBridge(capabilities, new DesktopAppPackageInstaller(packageData), verifier);
        var info = JsonSerializer.Serialize(bridge.Describe());
        Require(info.Contains("SIGNED_CATALOG_REQUIRED", StringComparison.Ordinal), "lifecycle bridge must remain locked to signed catalog authorization after restart");
        Require(info.Contains("\"persistedTrustProvenance\":true", StringComparison.Ordinal), "bridge must advertise persistent package trust provenance");
        Require(info.Contains("\"packageSignatureRequired\":true", StringComparison.Ordinal), "lifecycle bridge must require embedded package signatures");
        Require(info.Contains("\"packageSignatureTrustedRoots\":1", StringComparison.Ordinal), "lifecycle bridge must expose exactly one provisioned package signing root");
        return new BridgeContext(bridge, capabilities);
    }

    private static void InstallSigned(BridgeContext context, string bundle, Key catalogKey, string version, long sequence)
    {
        var token = Register(context.Capabilities, bundle);
        var authorization = CreateSignedAuthorization(catalogKey, "swir.lifecycle", version, Sha256(bundle), sequence);
        var result = JsonSerializer.Serialize(context.Bridge.InstallFromCapability(token, authorization, Shell));
        Require(result.Contains(version, StringComparison.Ordinal), $"signed install result should contain {version}");
        Require(result.Contains("VERIFIED", StringComparison.Ordinal), "signed install must retain installer health verification");
        Require(result.Contains("\"trustMode\":\"SIGNED_CATALOG\"", StringComparison.Ordinal), "signed install must report signed catalog trust mode");
        Require(result.Contains("\"signatureVerified\":true", StringComparison.Ordinal), "signed install must report verified catalog signature provenance");
        Require(result.Contains($"\"catalogSequence\":{sequence}", StringComparison.Ordinal), "signed install must report verified catalog sequence");
        Require(result.Contains($"\"signerKeyId\":\"{CatalogKeyId}\"", StringComparison.Ordinal), "signed install must report verified catalog signer key ID");
        ExpectBridgeCode(() => context.Capabilities.Describe(token, Shell), "CAPABILITY_INVALID");
    }

    private static void AssertSignedStatus(DesktopPackageBridge bridge, string version, long sequence)
    {
        var status = StatusJson(bridge);
        Require(status.Contains(version, StringComparison.Ordinal), $"signed package status should contain {version}");
        Require(status.Contains("\"trustMode\":\"SIGNED_CATALOG\"", StringComparison.Ordinal), "signed package status must preserve signed catalog trust mode");
        Require(status.Contains("\"signatureVerified\":true", StringComparison.Ordinal), "signed package status must preserve verified catalog signature provenance");
        Require(status.Contains($"\"signerKeyId\":\"{CatalogKeyId}\"", StringComparison.Ordinal), "signed package status must preserve catalog signer key ID");
        Require(status.Contains($"\"catalogSequence\":{sequence}", StringComparison.Ordinal), "signed package status must preserve catalog sequence");
        Require(status.Contains($"\"catalogVersion\":\"lifecycle-{sequence}\"", StringComparison.Ordinal), "signed package status must preserve catalog version");
        Require(status.Contains("\"trustExpiresAt\":", StringComparison.Ordinal), "signed package status must preserve authorization expiry");
    }

    private static string Register(CapabilityBroker broker, string bundle)
    {
        using var doc = JsonDocument.Parse(JsonSerializer.Serialize(broker.RegisterFile(bundle, Shell)));
        return doc.RootElement.GetProperty("token").GetString() ?? throw new Exception("Capability token missing.");
    }

    private static string StatusJson(DesktopPackageBridge bridge) => JsonSerializer.Serialize(bridge.Status("swir.lifecycle", Shell));

    private static void WriteCatalogTrustRoots(string path, byte[] publicKey)
    {
        File.WriteAllText(path, JsonSerializer.Serialize(new
        {
            schema = DesktopCatalogTrustRootStore.Schema,
            requireSignedCatalog = true,
            roots = new[]
            {
                new
                {
                    keyId = CatalogKeyId,
                    name = "Signed lifecycle catalog CI root",
                    algorithm = "Ed25519",
                    format = "raw",
                    publicKey = Convert.ToBase64String(publicKey),
                    scope = new[] { "catalog:official" },
                    enabled = true
                }
            }
        }));
    }

    private static void WritePackageTrustRoots(string path, byte[] publicKey)
    {
        File.WriteAllText(path, JsonSerializer.Serialize(new
        {
            schema = DesktopPackageTrustRootStore.Schema,
            requireSignedPackages = true,
            roots = new[]
            {
                new
                {
                    keyId = PackageKeyId,
                    name = "Signed lifecycle package CI root",
                    algorithm = "Ed25519",
                    format = "raw",
                    publicKey = Convert.ToBase64String(publicKey),
                    scope = new[] { "package:swirapp" },
                    enabled = true
                }
            }
        }));
    }

    private static string CreateSignedAuthorization(Key key, string packageId, string version, string sha256, long sequence)
    {
        var now = DateTimeOffset.UtcNow;
        var generatedAt = now.AddMinutes(-1).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");
        var expiresAt = now.AddHours(1).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");
        var catalogVersion = $"lifecycle-{sequence}";
        var package = new SortedDictionary<string, object?>(StringComparer.Ordinal)
        {
            ["artifacts"] = new SortedDictionary<string, object?>(StringComparer.Ordinal)
            {
                ["desktop"] = new SortedDictionary<string, object?>(StringComparer.Ordinal) { ["sha256"] = sha256 }
            },
            ["packageId"] = packageId,
            ["version"] = version
        };
        var catalogJson = JsonSerializer.Serialize(new object[] { package });
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(catalogJson))).ToLowerInvariant();
        var signedPayload = JsonSerializer.Serialize(new SortedDictionary<string, object?>(StringComparer.Ordinal)
        {
            ["catalogId"] = "official",
            ["catalogSha256"] = digest,
            ["catalogVersion"] = catalogVersion,
            ["expiresAt"] = expiresAt,
            ["generatedAt"] = generatedAt,
            ["schema"] = DesktopCatalogTrustVerifier.SignatureSchema,
            ["sequence"] = sequence
        });
        var signature = SignatureAlgorithm.Ed25519.Sign(key, Encoding.UTF8.GetBytes(signedPayload));
        var envelope = new SortedDictionary<string, object?>(StringComparer.Ordinal)
        {
            ["algorithm"] = "Ed25519",
            ["catalogId"] = "official",
            ["catalogSha256"] = digest,
            ["catalogVersion"] = catalogVersion,
            ["expiresAt"] = expiresAt,
            ["generatedAt"] = generatedAt,
            ["keyId"] = CatalogKeyId,
            ["schema"] = DesktopCatalogTrustVerifier.SignatureSchema,
            ["sequence"] = sequence,
            ["signature"] = Convert.ToBase64String(signature)
        };
        return JsonSerializer.Serialize(new
        {
            schema = "swir.desktop-catalog-authorization/1.0",
            packageId,
            version,
            catalog = JsonSerializer.Deserialize<JsonElement>(catalogJson),
            envelope
        });
    }

    private static void CreateBundle(string path, string packageId, string version, string payloadText)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Create);
        var manifest = archive.CreateEntry("swir-package.json");
        using (var writer = new StreamWriter(manifest.Open(), new UTF8Encoding(false)))
            writer.Write(JsonSerializer.Serialize(new
            {
                schema = "swir.app/1.0",
                id = packageId,
                packageId,
                name = "SWIR signed lifecycle",
                version,
                author = "SWIR",
                type = "iframe",
                entry = "app/index.html",
                compatibility = new { minOS = "1.7.0", minSDK = "1.3.0", platformApi = 2, editions = new[] { "DESKTOP" } },
                dependencies = Array.Empty<object>(),
                optionalDependencies = Array.Empty<object>()
            }));
        var payload = archive.CreateEntry("app/index.html");
        using var payloadWriter = new StreamWriter(payload.Open(), new UTF8Encoding(false));
        payloadWriter.Write($"<!doctype html><title>{payloadText}</title>");
    }

    private static void SignPackage(string path, Key key)
    {
        DesktopPackageSignatureVerifier.PackageContent content;
        using (var source = ZipFile.OpenRead(path))
            content = DesktopPackageSignatureVerifier.ComputeContent(source);

        var payload = DesktopPackageSignatureVerifier.CanonicalSignedPayload(PackageKeyId, content.PackageId, content.Version, content.ContentSha256);
        var signature = SignatureAlgorithm.Ed25519.Sign(key, Encoding.UTF8.GetBytes(payload));
        var envelope = JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema = DesktopPackageSignatureVerifier.SignatureSchema,
            algorithm = "Ed25519",
            keyId = PackageKeyId,
            packageId = content.PackageId,
            version = content.Version,
            contentSha256 = content.ContentSha256,
            signature = Convert.ToBase64String(signature)
        });

        using var archive = ZipFile.Open(path, ZipArchiveMode.Update);
        var existing = archive.Entries
            .Where(entry => string.Equals(DesktopPackageSignatureVerifier.NormalizeEntryPath(entry.FullName), DesktopPackageSignatureVerifier.SignatureEntryName, StringComparison.Ordinal))
            .ToArray();
        foreach (var entry in existing) entry.Delete();
        var signatureEntry = archive.CreateEntry(DesktopPackageSignatureVerifier.SignatureEntryName, CompressionLevel.NoCompression);
        using var output = signatureEntry.Open();
        output.Write(envelope);
    }

    private static void TamperPayload(string path, string payloadText)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Update);
        var existing = archive.GetEntry("app/index.html") ?? throw new Exception("Test payload missing.");
        existing.Delete();
        var payload = archive.CreateEntry("app/index.html");
        using var writer = new StreamWriter(payload.Open(), new UTF8Encoding(false));
        writer.Write($"<!doctype html><title>{payloadText}</title>");
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
