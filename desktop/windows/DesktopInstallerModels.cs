using System.Text.Json.Serialization;

namespace Swir.Desktop.Host;

internal sealed record DesktopInstallerPayloadMetadata(
    [property: JsonPropertyName("schema")] string Schema,
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("channel")] string Channel,
    [property: JsonPropertyName("packageSha256")] string PackageSha256,
    [property: JsonPropertyName("entryPoint")] string EntryPoint);

internal sealed record DesktopInstallReceipt(
    string Schema,
    string Version,
    string Channel,
    string PackageSha256,
    string InstallDirectory,
    DateTimeOffset InstalledAt);

internal sealed record DesktopInstallPointer(
    [property: JsonPropertyName("schema")] string Schema,
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("channel")] string Channel,
    [property: JsonPropertyName("packageSha256")] string PackageSha256,
    [property: JsonPropertyName("installDirectory")] string InstallDirectory,
    [property: JsonPropertyName("updatedAt")] DateTimeOffset UpdatedAt);

internal sealed record DesktopInstallerOptions(
    bool VerifyOnly,
    bool NoLaunch,
    bool Uninstall,
    bool Rollback,
    bool Repair,
    string? InstallRoot,
    string? Language);
