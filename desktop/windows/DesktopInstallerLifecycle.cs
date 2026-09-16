using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopInstallerLifecycle
{
    internal static string DefaultInstallRoot() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Programs", "SWIR OS Desktop");

    internal static string Install(string packagePath, DesktopInstallerPayloadMetadata metadata, string installRoot, bool repair)
    {
        var root = NormalizeRoot(installRoot);
        Directory.CreateDirectory(root);
        var safeVersion = metadata.Version.Replace('.', '_');
        var final = Path.Combine(root, $"{safeVersion}-{metadata.Channel}");
        string? repairBackup = null;
        EnsureInstallTransitionAllowed(root, final, metadata, repair);

        if (Directory.Exists(final))
        {
            if (!repair)
            {
                DesktopInstallerPackage.VerifyExisting(final, metadata);
                WriteCurrentPointer(root, final, metadata, capturePrevious: true);
                return final;
            }

            try
            {
                DesktopInstallerPackage.VerifyExisting(final, metadata);
                WriteCurrentPointer(root, final, metadata, capturePrevious: false);
                return final;
            }
            catch
            {
                repairBackup = Path.Combine(root, $".repair-backup-{safeVersion}-{Guid.NewGuid():N}");
            }
        }

        var staging = Path.Combine(root, $".install-{Guid.NewGuid():N}.tmp");
        var promoted = false;
        try
        {
            Directory.CreateDirectory(staging);
            DesktopInstallerPackage.ExtractAndVerify(packagePath, staging, metadata);
            DesktopInstallerPackage.WriteReceipt(staging, final, metadata);
            if (repairBackup is not null)
                Directory.Move(final, repairBackup);
            Directory.Move(staging, final);
            promoted = true;
            WriteCurrentPointer(root, final, metadata, capturePrevious: !repair);
            if (repairBackup is not null)
            {
                try { Directory.Delete(repairBackup, true); } catch { }
            }
            return final;
        }
        catch
        {
            try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
            if (repairBackup is not null && Directory.Exists(repairBackup))
            {
                try { if (Directory.Exists(final)) Directory.Delete(final, true); } catch { }
                if (!Directory.Exists(final))
                {
                    try { Directory.Move(repairBackup, final); } catch { }
                }
            }
            else if (promoted)
            {
                try { if (Directory.Exists(final)) Directory.Delete(final, true); } catch { }
            }
            throw;
        }
    }

    internal static DesktopInstallPointer? Uninstall(string installRoot)
    {
        var root = NormalizeRoot(installRoot);
        var currentPath = Path.Combine(root, "current.json");
        if (!File.Exists(currentPath)) throw new InvalidOperationException("No SWIR OS Desktop installation was found.");

        var current = ReadPointer(currentPath, root);
        DesktopInstallerPackage.VerifyReceipt(current.InstallDirectory, current);

        DesktopInstallPointer? fallback = null;
        var previousPath = Path.Combine(root, "previous.json");
        if (File.Exists(previousPath))
        {
            try
            {
                var candidate = ReadPointer(previousPath, root);
                if (!string.Equals(candidate.InstallDirectory, current.InstallDirectory, StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(candidate.InstallDirectory))
                {
                    DesktopInstallerPackage.VerifyInstalled(candidate, verifyRuntime: true);
                    fallback = candidate;
                }
            }
            catch
            {
                fallback = null;
            }
        }

        if (fallback is not null)
        {
            WritePointerAtomic(currentPath, fallback with { UpdatedAt = DateTimeOffset.UtcNow });
            if (Directory.Exists(current.InstallDirectory))
                Directory.Delete(current.InstallDirectory, true);
            try { File.Delete(previousPath); } catch { }
            return fallback;
        }

        try { File.Delete(currentPath); } catch { }
        try { File.Delete(previousPath); } catch { }
        if (Directory.Exists(current.InstallDirectory))
            Directory.Delete(current.InstallDirectory, true);
        return null;
    }

    internal static DesktopInstallPointer Rollback(string installRoot)
    {
        var root = NormalizeRoot(installRoot);
        var currentPath = Path.Combine(root, "current.json");
        var previousPath = Path.Combine(root, "previous.json");
        if (!File.Exists(currentPath)) throw new InvalidOperationException("No SWIR OS Desktop installation was found.");
        if (!File.Exists(previousPath)) throw new InvalidOperationException("No previous SWIR OS Desktop installation is available for rollback.");

        var current = ReadPointer(currentPath, root);
        var previous = ReadPointer(previousPath, root);
        if (string.Equals(current.InstallDirectory, previous.InstallDirectory, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Current and previous SWIR Desktop pointers resolve to the same installation.");
        DesktopInstallerPackage.VerifyInstalled(current, verifyRuntime: true);
        DesktopInstallerPackage.VerifyInstalled(previous, verifyRuntime: true);

        WritePointerAtomic(currentPath, previous with { UpdatedAt = DateTimeOffset.UtcNow });
        WritePointerAtomic(previousPath, current with { UpdatedAt = DateTimeOffset.UtcNow });
        return previous;
    }

    internal static DesktopInstallPointer ReadPointer(string path, string root)
    {
        var pointer = JsonSerializer.Deserialize<DesktopInstallPointer>(File.ReadAllBytes(path))
            ?? throw new InvalidOperationException("SWIR Desktop installation pointer is invalid.");
        if (pointer.Schema != DesktopInstallerPackage.PointerSchema
            || !Version.TryParse(pointer.Version, out var version)
            || version.Build < 0
            || pointer.Channel is not ("preview" or "stable")
            || !DesktopInstallerPackage.IsSha256(pointer.PackageSha256))
            throw new InvalidOperationException("SWIR Desktop installation pointer metadata is invalid.");
        var directory = Path.GetFullPath(pointer.InstallDirectory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        EnsureInsideRoot(root, directory);
        return pointer with { InstallDirectory = directory };
    }

    internal static void WriteJsonAtomic<T>(string path, T value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllBytes(temp, JsonSerializer.SerializeToUtf8Bytes(value, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temp, path, true);
        }
        finally { try { if (File.Exists(temp)) File.Delete(temp); } catch { } }
    }

    private static void EnsureInstallTransitionAllowed(string root, string final, DesktopInstallerPayloadMetadata metadata, bool repair)
    {
        var currentPath = Path.Combine(root, "current.json");
        if (!File.Exists(currentPath))
        {
            if (repair) throw new InvalidOperationException("Repair requires an existing current SWIR Desktop installation.");
            return;
        }

        var current = ReadPointer(currentPath, root);
        var normalizedFinal = Path.GetFullPath(final).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (repair)
        {
            if (!string.Equals(current.InstallDirectory, normalizedFinal, StringComparison.OrdinalIgnoreCase)
                || current.Version != metadata.Version
                || current.Channel != metadata.Channel
                || current.PackageSha256 != metadata.PackageSha256)
                throw new InvalidOperationException("Repair is allowed only for the currently selected installation built from this exact Setup package.");
            return;
        }

        if (string.Equals(current.InstallDirectory, normalizedFinal, StringComparison.OrdinalIgnoreCase)) return;
        if (!Version.TryParse(current.Version, out var currentVersion) || !Version.TryParse(metadata.Version, out var requestedVersion))
            throw new InvalidOperationException("Unable to compare Desktop installer versions safely.");
        if (requestedVersion < currentVersion)
            throw new InvalidOperationException("Setup refuses an in-place downgrade. Use --rollback for the verified previous installation.");
    }

    private static void WriteCurrentPointer(string root, string directory, DesktopInstallerPayloadMetadata metadata, bool capturePrevious)
    {
        var normalizedRoot = NormalizeRoot(root);
        var normalizedDirectory = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        EnsureInsideRoot(normalizedRoot, normalizedDirectory);
        if (capturePrevious)
            CapturePreviousPointer(normalizedRoot, normalizedDirectory);
        var pointer = new DesktopInstallPointer(DesktopInstallerPackage.PointerSchema, metadata.Version, metadata.Channel, metadata.PackageSha256, normalizedDirectory, DateTimeOffset.UtcNow);
        WritePointerAtomic(Path.Combine(normalizedRoot, "current.json"), pointer);
    }

    private static void CapturePreviousPointer(string root, string newDirectory)
    {
        var currentPath = Path.Combine(root, "current.json");
        if (!File.Exists(currentPath)) return;
        var current = ReadPointer(currentPath, root);
        if (string.Equals(current.InstallDirectory, newDirectory, StringComparison.OrdinalIgnoreCase)) return;
        DesktopInstallerPackage.VerifyInstalled(current, verifyRuntime: true);
        WritePointerAtomic(Path.Combine(root, "previous.json"), current with { UpdatedAt = DateTimeOffset.UtcNow });
    }

    private static void WritePointerAtomic(string path, DesktopInstallPointer pointer) => WriteJsonAtomic(path, pointer);

    private static string NormalizeRoot(string root) => Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

    private static void EnsureInsideRoot(string root, string path)
    {
        var canonicalRoot = NormalizeRoot(root);
        var canonicalPath = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (!canonicalPath.StartsWith(canonicalRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Installation path escapes the SWIR Desktop root.");
    }
}
