using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopInstallerPackage
{
    internal const string PayloadSchema = "swir.desktop-installer-payload/0.1";
    internal const string ReceiptSchema = "swir.desktop-install-receipt/0.1";
    internal const string PointerSchema = "swir.desktop-current-install/0.1";
    private const string MetadataResource = "SWIR.Desktop.Payload.json";
    private const string PayloadResource = "SWIR.Desktop.Payload.zip";
    private const long MaxExtractedBytes = 4L * 1024 * 1024 * 1024;
    private const int MaxEntries = 25000;

    internal static DesktopInstallerPayloadMetadata ReadEmbeddedMetadata()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(MetadataResource)
            ?? throw new InvalidOperationException("Installer payload metadata is missing.");
        var metadata = JsonSerializer.Deserialize<DesktopInstallerPayloadMetadata>(stream)
            ?? throw new InvalidOperationException("Installer payload metadata is invalid.");
        ValidateMetadata(metadata);
        return metadata;
    }

    internal static void ValidateMetadata(DesktopInstallerPayloadMetadata metadata)
    {
        if (metadata.Schema != PayloadSchema) throw new InvalidOperationException("Installer payload schema mismatch.");
        if (!Version.TryParse(metadata.Version, out var version) || version.Build < 0 || version <= new Version(0, 0)) throw new InvalidOperationException("Installer payload version is invalid.");
        if (metadata.Channel is not ("preview" or "stable")) throw new InvalidOperationException("Installer payload channel is invalid.");
        if (!IsSha256(metadata.PackageSha256)) throw new InvalidOperationException("Installer package SHA-256 is invalid.");
        if (string.IsNullOrWhiteSpace(metadata.EntryPoint) || Path.IsPathRooted(metadata.EntryPoint) || metadata.EntryPoint.Contains("..", StringComparison.Ordinal)) throw new InvalidOperationException("Installer entry point is invalid.");
    }

    internal static string MaterializeAndVerifyPayload(string expectedSha256)
    {
        using var resource = Assembly.GetExecutingAssembly().GetManifestResourceStream(PayloadResource)
            ?? throw new InvalidOperationException("Installer payload is missing.");
        var temp = Path.Combine(Path.GetTempPath(), $"swir-desktop-payload-{Guid.NewGuid():N}.zip");
        using (var output = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None, 128 * 1024, FileOptions.SequentialScan))
            resource.CopyTo(output);
        var actual = HashFile(temp);
        if (!FixedHashEquals(actual, expectedSha256))
        {
            try { File.Delete(temp); } catch { }
            throw new InvalidOperationException("Embedded SWIR Desktop package SHA-256 mismatch.");
        }
        return temp;
    }

    internal static void VerifyPayloadStructure(string packagePath, DesktopInstallerPayloadMetadata metadata)
    {
        var staging = Path.Combine(Path.GetTempPath(), $"swir-desktop-verify-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(staging);
            ExtractSafely(packagePath, staging);
            VerifyBuildIdentity(staging, metadata.Version, metadata.Channel);
            _ = BundledRuntimeIntegrity.Verify(staging, requireManifest: true);
            var entryPoint = ResolveInside(staging, metadata.EntryPoint);
            if (!File.Exists(entryPoint)) throw new InvalidOperationException("Verified Desktop payload entry point is missing.");
        }
        finally
        {
            try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
        }
    }

    internal static void ExtractAndVerify(string packagePath, string destination, DesktopInstallerPayloadMetadata metadata)
    {
        ExtractSafely(packagePath, destination);
        VerifyBuildIdentity(destination, metadata.Version, metadata.Channel);
        _ = BundledRuntimeIntegrity.Verify(destination, requireManifest: true);
        if (!File.Exists(ResolveInside(destination, metadata.EntryPoint)))
            throw new InvalidOperationException("Installed Desktop entry point is missing.");
    }

    internal static void VerifyExisting(string directory, DesktopInstallerPayloadMetadata metadata)
    {
        VerifyBuildIdentity(directory, metadata.Version, metadata.Channel);
        _ = BundledRuntimeIntegrity.Verify(directory, requireManifest: true);
        var pointer = new DesktopInstallPointer(PointerSchema, metadata.Version, metadata.Channel, metadata.PackageSha256, directory, DateTimeOffset.UtcNow);
        VerifyReceipt(directory, pointer);
    }

    internal static void VerifyInstalled(DesktopInstallPointer pointer, bool verifyRuntime)
    {
        if (!Directory.Exists(pointer.InstallDirectory)) throw new InvalidOperationException("Referenced SWIR Desktop installation directory is missing.");
        VerifyReceipt(pointer.InstallDirectory, pointer);
        VerifyBuildIdentity(pointer.InstallDirectory, pointer.Version, pointer.Channel);
        if (verifyRuntime)
            _ = BundledRuntimeIntegrity.Verify(pointer.InstallDirectory, requireManifest: true);
    }

    internal static void VerifyReceipt(string directory, DesktopInstallPointer pointer)
    {
        var receiptPath = Path.Combine(directory, "install-receipt.json");
        if (!File.Exists(receiptPath)) throw new InvalidOperationException("Existing SWIR Desktop installation has no install receipt.");
        var receipt = JsonSerializer.Deserialize<DesktopInstallReceipt>(File.ReadAllBytes(receiptPath))
            ?? throw new InvalidOperationException("Existing SWIR Desktop install receipt is invalid.");
        var expectedDirectory = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var receiptDirectory = Path.GetFullPath(receipt.InstallDirectory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (receipt.Schema != ReceiptSchema
            || receipt.Version != pointer.Version
            || receipt.Channel != pointer.Channel
            || receipt.PackageSha256 != pointer.PackageSha256
            || !string.Equals(receiptDirectory, expectedDirectory, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Existing SWIR Desktop install receipt does not match its installation pointer.");
    }

    internal static void VerifyBuildIdentity(string directory, string version, string channel)
    {
        var buildPath = Path.Combine(directory, "desktop-host-build.json");
        if (!File.Exists(buildPath)) throw new InvalidOperationException("Desktop Host build identity manifest is missing.");
        using var document = JsonDocument.Parse(File.ReadAllBytes(buildPath));
        var root = document.RootElement;
        if (root.GetProperty("schema").GetString() != "swir.desktop-host-build/0.1"
            || root.GetProperty("releaseVersion").GetString() != version
            || root.GetProperty("channel").GetString() != channel)
            throw new InvalidOperationException("Desktop payload build identity does not match installer metadata.");
        if (root.TryGetProperty("hostVersion", out var hostVersion) && hostVersion.GetString() != $"{version}-{channel}")
            throw new InvalidOperationException("Desktop payload host version does not match installer metadata.");
    }

    internal static void WriteReceipt(string stagingDirectory, string installedDirectory, DesktopInstallerPayloadMetadata metadata)
    {
        var finalDirectory = Path.GetFullPath(installedDirectory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var receipt = new DesktopInstallReceipt(ReceiptSchema, metadata.Version, metadata.Channel, metadata.PackageSha256, finalDirectory, DateTimeOffset.UtcNow);
        DesktopInstallerLifecycle.WriteJsonAtomic(Path.Combine(stagingDirectory, "install-receipt.json"), receipt);
    }

    internal static string ResolveInside(string root, string relative)
    {
        var canonicalRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var path = Path.GetFullPath(Path.Combine(canonicalRoot, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(canonicalRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Path escapes the SWIR installation root.");
        return path;
    }

    internal static bool IsSha256(string value) => value.Length == 64 && value.All(Uri.IsHexDigit);

    private static void ExtractSafely(string packagePath, string destinationRoot)
    {
        var root = Path.GetFullPath(destinationRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var rootPrefix = root + Path.DirectorySeparatorChar;
        long total = 0;
        var count = 0;
        using var archive = ZipFile.OpenRead(packagePath);
        foreach (var entry in archive.Entries)
        {
            if (++count > MaxEntries) throw new InvalidOperationException("Desktop package contains too many archive entries.");
            var name = entry.FullName.Replace('\\', '/');
            if (string.IsNullOrWhiteSpace(name) || name.StartsWith('/') || name.Contains(':') || name.Split('/').Any(x => x is "." or ".."))
                throw new InvalidOperationException("Desktop package contains an unsafe archive path.");
            var unixMode = (entry.ExternalAttributes >> 16) & 0xF000;
            if (unixMode == 0xA000) throw new InvalidOperationException("Desktop package contains a symbolic link, which is not allowed.");
            total = checked(total + entry.Length);
            if (total > MaxExtractedBytes) throw new InvalidOperationException("Desktop package exceeds the installer extraction safety limit.");
            var target = Path.GetFullPath(Path.Combine(root, name.Replace('/', Path.DirectorySeparatorChar)));
            if (!target.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase) && !string.Equals(target, root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Desktop package attempts to escape the installation directory.");
            if (name.EndsWith('/')) { Directory.CreateDirectory(target); continue; }
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            using var source = entry.Open();
            using var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None, 128 * 1024, FileOptions.SequentialScan);
            source.CopyTo(output);
        }
    }

    private static bool FixedHashEquals(string left, string right) => CryptographicOperations.FixedTimeEquals(Convert.FromHexString(left), Convert.FromHexString(right));

    private static string HashFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}
