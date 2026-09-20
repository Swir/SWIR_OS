using System.Text.Json;

namespace Swir.Desktop.Host;

internal enum DesktopUpdateUserMode
{
    Manual,
    NotifyOnly,
    Automatic
}

internal readonly record struct DesktopUpdateUserPolicyDecision(
    DesktopUpdateUserMode Mode,
    bool BackgroundCheck,
    bool AutomaticPrepare,
    bool AutomaticRestart,
    bool UserInitiatedCheck,
    bool UserInitiatedPrepare,
    bool UserInitiatedRestart);

/// <summary>
/// Persists only the user's Desktop Update Center intent. This policy must never
/// weaken release provenance, signature, source-host, privilege or transaction gates.
/// </summary>
internal sealed class DesktopUpdateUserPolicyStore
{
    internal const int SchemaVersion = 1;
    internal const string DefaultFileName = "update-user-policy.json";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true
    };

    private readonly object sync = new();
    private readonly string policyPath;

    internal DesktopUpdateUserPolicyStore(string? explicitPolicyPath = null)
    {
        policyPath = explicitPolicyPath is null
            ? GetDefaultPolicyPath()
            : ValidateExplicitPath(explicitPolicyPath);
    }

    internal string PolicyPath => policyPath;

    internal DesktopUpdateUserMode Load()
    {
        lock (sync)
        {
            if (!File.Exists(policyPath))
                return DesktopUpdateUserMode.NotifyOnly;

            try
            {
                using var stream = new FileStream(
                    policyPath,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.Read,
                    bufferSize: 4096,
                    FileOptions.SequentialScan);
                using var document = JsonDocument.Parse(stream, new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow
                });

                if (!TryParseStrictRecord(document.RootElement, out var mode))
                    return DesktopUpdateUserMode.NotifyOnly;

                return mode;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
            {
                return DesktopUpdateUserMode.NotifyOnly;
            }
        }
    }

    internal void Save(DesktopUpdateUserMode mode)
    {
        var persistedMode = ToPersistedMode(mode);

        lock (sync)
        {
            var directory = Path.GetDirectoryName(policyPath)
                ?? throw new InvalidOperationException("Update user policy path has no parent directory.");
            Directory.CreateDirectory(directory);

            var tempPath = Path.Combine(
                directory,
                $".{Path.GetFileName(policyPath)}.{Guid.NewGuid():N}.tmp");

            try
            {
                var payload = JsonSerializer.SerializeToUtf8Bytes(
                    new PersistedPolicy(SchemaVersion, persistedMode),
                    JsonOptions);

                using (var stream = new FileStream(
                    tempPath,
                    FileMode.CreateNew,
                    FileAccess.Write,
                    FileShare.None,
                    bufferSize: 4096,
                    FileOptions.WriteThrough))
                {
                    stream.Write(payload);
                    stream.Flush(flushToDisk: true);
                }

                File.Move(tempPath, policyPath, overwrite: true);
            }
            finally
            {
                try
                {
                    if (File.Exists(tempPath))
                        File.Delete(tempPath);
                }
                catch
                {
                    // A failed cleanup must not mask the original persistence error.
                }
            }
        }
    }

    internal static DesktopUpdateUserPolicyDecision Evaluate(DesktopUpdateUserMode mode) => mode switch
    {
        DesktopUpdateUserMode.Manual => new(
            mode,
            BackgroundCheck: false,
            AutomaticPrepare: false,
            AutomaticRestart: false,
            UserInitiatedCheck: true,
            UserInitiatedPrepare: true,
            UserInitiatedRestart: true),

        DesktopUpdateUserMode.NotifyOnly => new(
            mode,
            BackgroundCheck: true,
            AutomaticPrepare: false,
            AutomaticRestart: false,
            UserInitiatedCheck: true,
            UserInitiatedPrepare: true,
            UserInitiatedRestart: true),

        DesktopUpdateUserMode.Automatic => new(
            mode,
            BackgroundCheck: true,
            AutomaticPrepare: true,
            AutomaticRestart: false,
            UserInitiatedCheck: true,
            UserInitiatedPrepare: true,
            UserInitiatedRestart: true),

        _ => Evaluate(DesktopUpdateUserMode.NotifyOnly)
    };

    internal static string ToPersistedMode(DesktopUpdateUserMode mode) => mode switch
    {
        DesktopUpdateUserMode.Manual => "manual",
        DesktopUpdateUserMode.NotifyOnly => "notify",
        DesktopUpdateUserMode.Automatic => "automatic",
        _ => throw new ArgumentOutOfRangeException(nameof(mode), mode, "Unknown Desktop update user mode.")
    };

    private static string GetDefaultPolicyPath()
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
            throw new InvalidOperationException("Local application data directory is unavailable.");

        return Path.Combine(localAppData, "SWIR OS", DefaultFileName);
    }

    private static string ValidateExplicitPath(string value)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(value);
        var fullPath = Path.GetFullPath(value);
        if (!Path.IsPathFullyQualified(fullPath))
            throw new ArgumentException("Update user policy path must resolve to an absolute path.", nameof(value));
        if (!string.Equals(Path.GetFileName(fullPath), DefaultFileName, StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException($"Update user policy file must be named {DefaultFileName}.", nameof(value));
        return fullPath;
    }

    private static bool TryParseStrictRecord(JsonElement root, out DesktopUpdateUserMode mode)
    {
        mode = DesktopUpdateUserMode.NotifyOnly;
        if (root.ValueKind != JsonValueKind.Object)
            return false;

        var seenSchemaVersion = false;
        var seenMode = false;
        var schemaVersion = 0;
        string? persistedMode = null;
        var propertyCount = 0;

        foreach (var property in root.EnumerateObject())
        {
            propertyCount++;
            if (property.NameEquals("schemaVersion"))
            {
                if (seenSchemaVersion || property.Value.ValueKind != JsonValueKind.Number || !property.Value.TryGetInt32(out schemaVersion))
                    return false;
                seenSchemaVersion = true;
                continue;
            }

            if (property.NameEquals("mode"))
            {
                if (seenMode || property.Value.ValueKind != JsonValueKind.String)
                    return false;
                persistedMode = property.Value.GetString();
                seenMode = true;
                continue;
            }

            return false;
        }

        if (propertyCount != 2 || !seenSchemaVersion || !seenMode || schemaVersion != SchemaVersion)
            return false;

        mode = persistedMode switch
        {
            "manual" => DesktopUpdateUserMode.Manual,
            "notify" => DesktopUpdateUserMode.NotifyOnly,
            "automatic" => DesktopUpdateUserMode.Automatic,
            _ => DesktopUpdateUserMode.NotifyOnly
        };

        return persistedMode is "manual" or "notify" or "automatic";
    }

    private sealed record PersistedPolicy(int schemaVersion, string mode);
}
