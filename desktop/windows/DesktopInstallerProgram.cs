using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows.Forms;

namespace Swir.Desktop.Host;

internal static class DesktopInstallerProgram
{
    private const string MetadataResource = "SWIR.Desktop.Payload.json";
    private const string PayloadResource = "SWIR.Desktop.Payload.zip";
    private const string PayloadSchema = "swir.desktop-installer-payload/0.1";
    private const string ReceiptSchema = "swir.desktop-install-receipt/0.1";
    private const long MaxExtractedBytes = 4L * 1024 * 1024 * 1024;
    private const int MaxEntries = 25000;

    private sealed record PayloadMetadata(
        [property: JsonPropertyName("schema")] string Schema,
        [property: JsonPropertyName("version")] string Version,
        [property: JsonPropertyName("channel")] string Channel,
        [property: JsonPropertyName("packageSha256")] string PackageSha256,
        [property: JsonPropertyName("entryPoint")] string EntryPoint);

    private sealed record InstallReceipt(
        string Schema,
        string Version,
        string Channel,
        string PackageSha256,
        string InstallDirectory,
        DateTimeOffset InstalledAt);

    [STAThread]
    public static int Main(string[] args)
    {
        var quiet = args.Contains("--quiet", StringComparer.OrdinalIgnoreCase);
        try
        {
            var options = ParseOptions(args);
            var metadata = ReadMetadata();
            ValidateMetadata(metadata);
            var packagePath = MaterializeAndVerifyPayload(metadata.PackageSha256);
            try
            {
                if (options.VerifyOnly)
                    return 0;

                var installRoot = options.InstallRoot ?? Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs", "SWIR OS Desktop");
                var installed = Install(packagePath, metadata, installRoot);
                if (!options.NoLaunch)
                    Launch(installed, metadata.EntryPoint);
                if (!quiet)
                    MessageBox.Show($"SWIR OS Desktop {metadata.Version} ({metadata.Channel}) is ready.", "SWIR OS", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 0;
            }
            finally
            {
                try { File.Delete(packagePath); } catch { }
            }
        }
        catch (Exception ex)
        {
            if (!quiet)
                MessageBox.Show(ex.Message, "SWIR OS Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }
    }

    private sealed record Options(bool VerifyOnly, bool NoLaunch, string? InstallRoot);

    private static Options ParseOptions(string[] args)
    {
        var verify = false;
        var noLaunch = false;
        string? installRoot = null;
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            if (arg.Equals("--quiet", StringComparison.OrdinalIgnoreCase)) continue;
            if (arg.Equals("--verify-only", StringComparison.OrdinalIgnoreCase)) { verify = true; continue; }
            if (arg.Equals("--no-launch", StringComparison.OrdinalIgnoreCase)) { noLaunch = true; continue; }
            if (arg.Equals("--install-root", StringComparison.OrdinalIgnoreCase))
            {
                if (++i >= args.Length || string.IsNullOrWhiteSpace(args[i])) throw new InvalidOperationException("--install-root requires a directory.");
                installRoot = Path.GetFullPath(args[i]);
                continue;
            }
            throw new InvalidOperationException($"Unsupported setup argument: {arg}");
        }
        return new Options(verify, noLaunch, installRoot);
    }

    private static PayloadMetadata ReadMetadata()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(MetadataResource)
            ?? throw new InvalidOperationException("Installer payload metadata is missing.");
        return JsonSerializer.Deserialize<PayloadMetadata>(stream)
            ?? throw new InvalidOperationException("Installer payload metadata is invalid.");
    }

    private static void ValidateMetadata(PayloadMetadata metadata)
    {
        if (metadata.Schema != PayloadSchema) throw new InvalidOperationException("Installer payload schema mismatch.");
        if (!Version.TryParse(metadata.Version, out var version) || version.Build < 0 || version <= new Version(0, 0)) throw new InvalidOperationException("Installer payload version is invalid.");
        if (metadata.Channel is not ("preview" or "stable")) throw new InvalidOperationException("Installer payload channel is invalid.");
        if (!IsSha256(metadata.PackageSha256)) throw new InvalidOperationException("Installer package SHA-256 is invalid.");
        if (string.IsNullOrWhiteSpace(metadata.EntryPoint) || Path.IsPathRooted(metadata.EntryPoint) || metadata.EntryPoint.Contains("..", StringComparison.Ordinal)) throw new InvalidOperationException("Installer entry point is invalid.");
    }

    private static string MaterializeAndVerifyPayload(string expectedSha256)
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

    private static string Install(string packagePath, PayloadMetadata metadata, string installRoot)
    {
        var root = Path.GetFullPath(installRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        Directory.CreateDirectory(root);
        var safeVersion = metadata.Version.Replace('.', '_');
        var final = Path.Combine(root, $"{safeVersion}-{metadata.Channel}");
        if (Directory.Exists(final))
        {
            VerifyExisting(final, metadata);
            WriteCurrentPointer(root, final, metadata);
            return final;
        }

        var staging = Path.Combine(root, $".install-{Guid.NewGuid():N}.tmp");
        try
        {
            Directory.CreateDirectory(staging);
            ExtractSafely(packagePath, staging);
            _ = BundledRuntimeIntegrity.Verify(staging, requireManifest: true);
            var entryPoint = ResolveInside(staging, metadata.EntryPoint);
            if (!File.Exists(entryPoint)) throw new InvalidOperationException("Installed Desktop entry point is missing.");
            WriteReceipt(staging, metadata);
            Directory.Move(staging, final);
            WriteCurrentPointer(root, final, metadata);
            return final;
        }
        catch
        {
            try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
            throw;
        }
    }

    private static void VerifyExisting(string directory, PayloadMetadata metadata)
    {
        _ = BundledRuntimeIntegrity.Verify(directory, requireManifest: true);
        var receiptPath = Path.Combine(directory, "install-receipt.json");
        if (!File.Exists(receiptPath)) throw new InvalidOperationException("Existing SWIR Desktop installation has no install receipt.");
        using var receiptDoc = JsonDocument.Parse(File.ReadAllBytes(receiptPath));
        var receipt = receiptDoc.RootElement;
        if (receipt.GetProperty("Schema").GetString() != ReceiptSchema
            || receipt.GetProperty("Version").GetString() != metadata.Version
            || receipt.GetProperty("Channel").GetString() != metadata.Channel
            || receipt.GetProperty("PackageSha256").GetString() != metadata.PackageSha256)
            throw new InvalidOperationException("An existing installation uses different package bytes for this version; refusing overwrite.");
    }

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

    private static void WriteReceipt(string directory, PayloadMetadata metadata)
    {
        var receipt = new InstallReceipt(ReceiptSchema, metadata.Version, metadata.Channel, metadata.PackageSha256, directory, DateTimeOffset.UtcNow);
        WriteJsonAtomic(Path.Combine(directory, "install-receipt.json"), receipt);
    }

    private static void WriteCurrentPointer(string root, string directory, PayloadMetadata metadata)
    {
        var pointer = new
        {
            schema = "swir.desktop-current-install/0.1",
            version = metadata.Version,
            channel = metadata.Channel,
            packageSha256 = metadata.PackageSha256,
            installDirectory = directory,
            updatedAt = DateTimeOffset.UtcNow
        };
        WriteJsonAtomic(Path.Combine(root, "current.json"), pointer);
    }

    private static void WriteJsonAtomic<T>(string path, T value)
    {
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllBytes(temp, JsonSerializer.SerializeToUtf8Bytes(value, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temp, path, true);
        }
        finally { try { if (File.Exists(temp)) File.Delete(temp); } catch { } }
    }

    private static void Launch(string installationDirectory, string entryPoint)
    {
        var executable = ResolveInside(installationDirectory, entryPoint);
        _ = Process.Start(new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = installationDirectory,
            UseShellExecute = false
        }) ?? throw new InvalidOperationException("SWIR Desktop Host could not be started after installation.");
    }

    private static string ResolveInside(string root, string relative)
    {
        var canonicalRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var path = Path.GetFullPath(Path.Combine(canonicalRoot, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(canonicalRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Path escapes the SWIR installation root.");
        return path;
    }

    private static bool IsSha256(string value) => value.Length == 64 && value.All(Uri.IsHexDigit);
    private static bool FixedHashEquals(string left, string right) => CryptographicOperations.FixedTimeEquals(Convert.FromHexString(left), Convert.FromHexString(right));
    private static string HashFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}
