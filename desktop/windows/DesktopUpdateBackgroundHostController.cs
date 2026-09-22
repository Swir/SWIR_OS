using System.Text.Json;

namespace Swir.Desktop.Host;

/// <summary>
/// Coordinates the Desktop host lifetime with the policy-aware background update
/// scheduler. The controller never weakens signed-feed verification, never stages
/// work when the persisted user policy forbids it, and never restarts the host.
/// </summary>
internal sealed class DesktopUpdateBackgroundHostController : IAsyncDisposable
{
    public const string ControllerSchema = "swir.desktop-update-background-host/0.1";

    private readonly Func<bool, object> _describePolicy;
    private readonly Func<bool, string, object> _setPolicy;
    private readonly DesktopUpdateBackgroundScheduler _scheduler;
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private bool _disposed;

    internal DesktopUpdateBackgroundHostController(
        Func<CancellationToken, Task<object>> backgroundCycle,
        Func<bool, object> describePolicy,
        Func<bool, string, object> setPolicy,
        TimeSpan? interval = null,
        TimeSpan? initialDelay = null,
        Action<DesktopUpdateBackgroundSchedulerEvent>? eventSink = null)
    {
        ArgumentNullException.ThrowIfNull(backgroundCycle);
        ArgumentNullException.ThrowIfNull(describePolicy);
        ArgumentNullException.ThrowIfNull(setPolicy);

        _describePolicy = describePolicy;
        _setPolicy = setPolicy;
        _scheduler = new DesktopUpdateBackgroundScheduler(
            backgroundCycle,
            interval,
            initialDelay,
            eventSink);
    }

    internal async Task<object> StartAsync(bool trustedShell, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var policy = _describePolicy(trustedShell);
            await ReconcileSchedulerAsync(policy).ConfigureAwait(false);
            return DescribeCore(policy);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    internal async Task<object> SetUserPolicyAsync(
        bool trustedShell,
        string persistedMode,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var policy = _setPolicy(trustedShell, persistedMode);
            await ReconcileSchedulerAsync(policy).ConfigureAwait(false);
            return DescribeCore(policy);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    internal object Describe(bool trustedShell)
    {
        ThrowIfDisposed();
        var policy = _describePolicy(trustedShell);
        return DescribeCore(policy);
    }

    private async Task ReconcileSchedulerAsync(object policy)
    {
        if (AllowsBackgroundChecks(policy))
        {
            _scheduler.Start();
            return;
        }

        await _scheduler.StopAsync().ConfigureAwait(false);
    }

    private object DescribeCore(object policy) => new
    {
        schema = ControllerSchema,
        policy,
        scheduler = _scheduler.Describe(),
        failClosedPolicy = true,
        automaticRestart = false
    };

    private static bool AllowsBackgroundChecks(object policy)
    {
        try
        {
            var element = JsonSerializer.SerializeToElement(policy);
            return element.ValueKind == JsonValueKind.Object
                && element.TryGetProperty("backgroundCheck", out var backgroundCheck)
                && backgroundCheck.ValueKind is JsonValueKind.True;
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException)
        {
            return false;
        }
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
            throw new ObjectDisposedException(nameof(DesktopUpdateBackgroundHostController));
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        await _lifecycleGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_disposed)
                return;
            await _scheduler.DisposeAsync().ConfigureAwait(false);
            _disposed = true;
        }
        finally
        {
            _lifecycleGate.Release();
            _lifecycleGate.Dispose();
        }
    }
}
