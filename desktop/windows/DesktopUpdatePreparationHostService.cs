namespace Swir.Desktop.Host;

/// <summary>
/// Production composition root for the Desktop update preparation pipeline.
/// User policy controls when checks/preparation may run, but never weakens the
/// signed-release, source, integrity, transaction or restart security gates.
/// </summary>
internal sealed class DesktopUpdatePreparationHostService
{
    public const string HostServiceSchema = "swir.desktop-update-preparation-host/0.5";
    public const string CheckSchema = "swir.desktop-update-check/0.1";
    public const string UserPolicySchema = "swir.desktop-update-user-policy-state/0.1";

    private readonly string _policyPath;
    private readonly string _currentInstallRoot;
    private readonly string _updaterWorkerPath;
    private readonly string _deploymentRoot;
    private readonly string _transactionsRoot;
    private readonly Version _currentDesktopVersion;
    private readonly DesktopUpdatePreparationBridgeCoordinator _bridge;
    private readonly DesktopUpdateUserPolicyStore _userPolicyStore;
    private readonly Func<UpdateBroker, Uri, IEnumerable<string>, UpdateManifestClient> _manifestClientFactory;

    public DesktopUpdatePreparationHostService(
        string? policyPath = null,
        string? currentInstallRoot = null,
        string? updaterWorkerPath = null,
        string? deploymentRoot = null,
        string? transactionsRoot = null,
        Func<UpdateBroker, Uri, IEnumerable<string>, UpdateManifestClient>? manifestClientFactory = null,
        Version? currentDesktopVersion = null,
        string? userPolicyPath = null)
    {
        _policyPath = Path.GetFullPath(policyPath ?? Path.Combine(AppContext.BaseDirectory, "desktop-update-policy.json"));
        _deploymentRoot = Path.GetFullPath(deploymentRoot ?? DesktopUpdatePaths.DeploymentRoot);
        _transactionsRoot = Path.GetFullPath(transactionsRoot ?? DesktopUpdatePaths.TransactionsRoot);
        _currentInstallRoot = Path.GetFullPath(currentInstallRoot ?? Path.Combine(_deploymentRoot, "Current"));
        _updaterWorkerPath = Path.GetFullPath(updaterWorkerPath ?? DesktopUpdatePaths.UpdaterWorkerPath);
        _currentDesktopVersion = currentDesktopVersion ?? DesktopInstalledBuildIdentity.ResolveCurrentVersion(AppContext.BaseDirectory);
        if (_currentDesktopVersion <= new Version(0, 0, 0))
            throw new UpdateSecurityException("UPDATE_CURRENT_VERSION_INVALID", "Desktop current version must be positive.");
        _manifestClientFactory = manifestClientFactory ?? ((broker, uri, hosts) => new UpdateManifestClient(broker, uri, hosts));
        _userPolicyStore = new DesktopUpdateUserPolicyStore(userPolicyPath);
        _bridge = new DesktopUpdatePreparationBridgeCoordinator(IsPreparationConfigured, PrepareCoreAsync);
    }

    public object Describe()
    {
        DesktopUpdateReleasePolicy policy;
        try { policy = DesktopUpdateReleasePolicy.Load(_policyPath); }
        catch (UpdateSecurityException ex)
        {
            return new { schema = HostServiceSchema, configured = false, feedConfigured = false, failClosed = true,
                currentVersion = _currentDesktopVersion.ToString(),
                policy = new { enabled = false, invalid = true, code = ex.Code, message = ex.Message },
                userPolicy = DescribeUserPolicyCore(),
                environment = DescribeEnvironment(), preparation = _bridge.Describe() };
        }

        return new { schema = HostServiceSchema, configured = IsPreparationConfigured(policy),
            feedConfigured = IsReleaseFeedConfigured(policy), failClosed = true,
            currentVersion = _currentDesktopVersion.ToString(), policy = policy.Describe(),
            userPolicy = DescribeUserPolicyCore(),
            environment = DescribeEnvironment(), preparation = _bridge.Describe() };
    }

    public object DescribeUserPolicy(bool trustedShell)
    {
        RequireTrustedShell(trustedShell, "inspect Desktop update user policy");
        return DescribeUserPolicyCore();
    }

    public object SetUserPolicy(bool trustedShell, string persistedMode)
    {
        RequireTrustedShell(trustedShell, "change Desktop update user policy");
        var mode = persistedMode?.Trim().ToLowerInvariant() switch
        {
            "manual" => DesktopUpdateUserMode.Manual,
            "notify" or "notifyonly" or "notify-only" => DesktopUpdateUserMode.NotifyOnly,
            "automatic" => DesktopUpdateUserMode.Automatic,
            _ => throw new DesktopUpdateBridgeCommandException("UPDATE_USER_POLICY_INVALID",
                "Desktop update policy must be manual, notify or automatic.")
        };
        _userPolicyStore.Save(mode);
        return DescribeUserPolicyCore();
    }

    public Task<object> CheckAsync(bool trustedShell, CancellationToken cancellationToken = default)
        => CheckAsync(trustedShell, userInitiated: true, cancellationToken);

    public Task<object> CheckInBackgroundAsync(bool trustedShell, CancellationToken cancellationToken = default)
        => CheckAsync(trustedShell, userInitiated: false, cancellationToken);

    public async Task<object> CheckAsync(bool trustedShell, bool userInitiated, CancellationToken cancellationToken = default)
    {
        RequireTrustedShell(trustedShell, "check Desktop release feeds");
        var decision = DesktopUpdateUserPolicyStore.Evaluate(_userPolicyStore.Load());
        if (userInitiated ? !decision.UserInitiatedCheck : !decision.BackgroundCheck)
            throw UserPolicyBlocked(decision.Mode, userInitiated ? "user-initiated check" : "background check");

        var policy = DesktopUpdateReleasePolicy.Load(_policyPath);
        if (!IsReleaseFeedConfigured(policy))
            throw new DesktopUpdateBridgeCommandException("UPDATE_RELEASE_FEED_NOT_CONFIGURED", "Desktop update check requires an enabled signed release policy.");

        var broker = new UpdateBroker(policy.PublicKeyPem!, policy.PackageHosts);
        using var manifestClient = _manifestClientFactory(broker, policy.ManifestUri!, policy.ManifestHosts);
        try
        {
            var update = await manifestClient.FetchAndVerifyAsync(_currentDesktopVersion, policy.Channel, cancellationToken).ConfigureAwait(false);
            return new { schema = CheckSchema, updateAvailable = true, currentVersion = _currentDesktopVersion.ToString(),
                targetVersion = update.Version.ToString(), channel = update.Channel, publishedAt = update.PublishedAt,
                package = new { host = update.PackageUri.Host, size = update.Size, sha256 = update.Sha256, keyId = update.KeyId },
                verified = true, userPolicy = DescribeUserPolicyCore() };
        }
        catch (UpdateSecurityException ex) when (ex.Code == "UPDATE_NOT_NEWER")
        {
            return new { schema = CheckSchema, updateAvailable = false, currentVersion = _currentDesktopVersion.ToString(),
                targetVersion = _currentDesktopVersion.ToString(), channel = policy.Channel, verified = true, status = "current",
                userPolicy = DescribeUserPolicyCore() };
        }
    }

    public object QueuePrepare(bool trustedShell) => QueuePrepare(trustedShell, userInitiated: true);
    public object QueueAutomaticPrepare(bool trustedShell) => QueuePrepare(trustedShell, userInitiated: false);

    public object QueuePrepare(bool trustedShell, bool userInitiated)
    {
        RequireTrustedShell(trustedShell, "prepare a Desktop update");
        var decision = DesktopUpdateUserPolicyStore.Evaluate(_userPolicyStore.Load());
        if (userInitiated ? !decision.UserInitiatedPrepare : !decision.AutomaticPrepare)
            throw UserPolicyBlocked(decision.Mode, userInitiated ? "user-initiated preparation" : "automatic preparation");
        return _bridge.QueuePrepare(trustedShell);
    }

    public object Cancel(bool trustedShell) => _bridge.CancelActive(trustedShell);
    public void CancelQueuedAfterResponseFailure() => _bridge.CancelQueuedAfterResponseFailure();

    public object ResetTerminalState(bool trustedShell)
    {
        RequireTrustedShell(trustedShell, "reset Desktop update preparation state");
        _bridge.ResetTerminalState();
        return Describe();
    }

    public Task<object?> ExecuteQueuedAsync(CancellationToken cancellationToken = default) => _bridge.ExecuteQueuedAsync(cancellationToken);

    private object DescribeUserPolicyCore()
    {
        var mode = _userPolicyStore.Load();
        var decision = DesktopUpdateUserPolicyStore.Evaluate(mode);
        return new
        {
            schema = UserPolicySchema,
            mode = DesktopUpdateUserPolicyStore.ToPersistedMode(mode),
            backgroundCheck = decision.BackgroundCheck,
            automaticPrepare = decision.AutomaticPrepare,
            automaticRestart = decision.AutomaticRestart,
            userInitiatedCheck = decision.UserInitiatedCheck,
            userInitiatedPrepare = decision.UserInitiatedPrepare,
            userInitiatedRestart = decision.UserInitiatedRestart,
            failClosedTrust = true
        };
    }

    private bool IsPreparationConfigured()
    {
        try { return IsPreparationConfigured(DesktopUpdateReleasePolicy.Load(_policyPath)); }
        catch { return false; }
    }

    private static bool IsReleaseFeedConfigured(DesktopUpdateReleasePolicy policy)
        => policy.Enabled && policy.ManifestUri is not null && !string.IsNullOrWhiteSpace(policy.PublicKeyPem)
           && policy.ManifestHosts.Length > 0 && policy.PackageHosts.Length > 0;

    private bool IsPreparationConfigured(DesktopUpdateReleasePolicy policy)
        => IsReleaseFeedConfigured(policy) && File.Exists(_updaterWorkerPath) && Directory.Exists(_currentInstallRoot)
           && IsCanonicalCurrentSlot(_currentInstallRoot, _deploymentRoot);

    private async Task<object?> PrepareCoreAsync(CancellationToken cancellationToken)
    {
        var policy = DesktopUpdateReleasePolicy.Load(_policyPath);
        if (!IsPreparationConfigured(policy))
            throw new DesktopUpdateBridgeCommandException("UPDATE_RELEASE_FEED_NOT_CONFIGURED",
                "Desktop update preparation requires an enabled signed release policy, packaged Current slot and Updater Worker.");

        var broker = new UpdateBroker(policy.PublicKeyPem!, policy.PackageHosts);
        using var manifestClient = _manifestClientFactory(broker, policy.ManifestUri!, policy.ManifestHosts);
        var staging = new UpdateStagingBroker();
        using var downloadClient = new UpdateDownloadClient(staging);
        var handoff = new UpdateHandoffBroker();
        var journal = new UpdateTransactionJournal(_transactionsRoot);
        var coordinator = new DesktopUpdatePreparationCoordinator(manifestClient, downloadClient, staging, handoff, journal,
            _deploymentRoot, _transactionsRoot, _updaterWorkerPath);
        var result = await coordinator.PrepareAsync(_currentDesktopVersion, policy.Channel, _currentInstallRoot, cancellationToken).ConfigureAwait(false);
        return new { ready = result.Ready, transactionId = result.TransactionId, currentVersion = result.CurrentVersion.ToString(),
            targetVersion = result.TargetVersion.ToString(), channel = result.Channel, sha256 = result.Sha256,
            size = result.Size, candidateVerified = true };
    }

    private object DescribeEnvironment() => new { currentInstallPresent = Directory.Exists(_currentInstallRoot),
        updaterWorkerPresent = File.Exists(_updaterWorkerPath), canonicalCurrentSlot = IsCanonicalCurrentSlot(_currentInstallRoot, _deploymentRoot),
        deploymentRoot = _deploymentRoot, transactionsRoot = _transactionsRoot };

    private static void RequireTrustedShell(bool trustedShell, string operation)
    {
        if (!trustedShell)
            throw new DesktopUpdateBridgeCommandException("UPDATE_BRIDGE_TRUST_REQUIRED", $"Only the trusted SWIR system shell may {operation}.");
    }

    private static DesktopUpdateBridgeCommandException UserPolicyBlocked(DesktopUpdateUserMode mode, string operation)
        => new("UPDATE_USER_POLICY_BLOCKED",
            $"Desktop update user policy '{DesktopUpdateUserPolicyStore.ToPersistedMode(mode)}' blocks {operation}.");

    private static bool IsCanonicalCurrentSlot(string currentInstallRoot, string deploymentRoot)
    {
        var expected = Path.GetFullPath(Path.Combine(deploymentRoot, "Current"));
        var actual = Path.GetFullPath(currentInstallRoot);
        return string.Equals(expected.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
            actual.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
            OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);
    }
}
