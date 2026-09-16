using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopInstalledBuildIdentity
{
    public const string BuildSchema = "swir.desktop-host-build/0.1";
    public static readonly Version DevelopmentVersion = new(0, 5, 7);

    public static Version ResolveCurrentVersion(string baseDirectory)
    {
        if (string.IsNullOrWhiteSpace(baseDirectory))
            throw new UpdateSecurityException("UPDATE_BUILD_IDENTITY_PATH_INVALID", "Desktop build identity base directory is required.");
        var path = Path.Combine(Path.GetFullPath(baseDirectory), "desktop-host-build.json");
        if (!File.Exists(path)) return DevelopmentVersion;
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (!root.TryGetProperty("schema", out var schema) || schema.GetString() != BuildSchema)
                throw new UpdateSecurityException("UPDATE_BUILD_IDENTITY_INVALID", "Desktop build identity schema is invalid.");
            if (!root.TryGetProperty("releaseVersion", out var releaseVersion) || releaseVersion.ValueKind != JsonValueKind.String)
                throw new UpdateSecurityException("UPDATE_BUILD_IDENTITY_INVALID", "Desktop build identity releaseVersion is missing.");
            if (!Version.TryParse(releaseVersion.GetString(), out var parsed) || parsed.Build < 0 || parsed <= new Version(0, 0, 0))
                throw new UpdateSecurityException("UPDATE_BUILD_IDENTITY_INVALID", "Desktop build identity releaseVersion is invalid.");
            return new Version(parsed.Major, parsed.Minor, parsed.Build);
        }
        catch (UpdateSecurityException) { throw; }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        { throw new UpdateSecurityException("UPDATE_BUILD_IDENTITY_INVALID", "Desktop build identity could not be read safely."); }
    }
}
