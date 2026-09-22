using System.Text.Json;

namespace Swir.Desktop.Host;

/// <summary>
/// Coordinates the Desktop host lifetime with the policy-aware background update
/// scheduler. The controller never weakens signed-feed verification, never stages
/// work when the persisted user policy forbids it, and never restarts the host.
/// Runtime eligibility is evaluated independently from user policy so a scheduler
/// cannot remain alive when the signed release path is unavailable or unsafe.
/// </summary>
internal sealed class DesktopUpdateBackgroundHostController : IAsyncDisposable
{
    public const string ControllerSchema = "swir.desktop-update-background-host/0.3";

    private readonly Func<bool, object> _describePolicy;
    private readonly Func<bool, string, object> _setPolicy;
    private readonly Func<bool> _runtimeEligibility;
    private readonly DesktopUpdateBackgroundScheduler _scheduler;
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private bool _disposed;
    private int _disposeStarted;

    internal DesktopUpdateBackgroundHostController(
        Func<CancellationToken, Task<object>> backgroundCycle,
        Func<bool, object> describePolicy,
        Func<bool, string, object> setPolicy,
        TimeSpan? interval = null,
        TimeSpan? initialDelay = null,
        Action<DesktopUpdateBackgroundSchedulerEvent>? eventSink = null,
        Func<bool>? runtimeEligibility = null)
    {
        ArgumentNullException.ThrowIfNull(backgroundCycle);
        ArgumentNullException.ThrowIfNull(describePolicy);
        ArgumentNullException.ThrowIfNull(setPolicy);

        _describePolicy = describePolicy;
        _setPolicy = setPolicy;
        _runtimeEligibility = runtimeEligibility ?? (() => true);
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
            object policy;
            try
            {
                policy = _describePolicy(trustedShell);
            }
            catch
            {
                await _scheduler.StopAsync().ConfigureAwait(false);
                throw;
            }

            var runtimeEligible = await ReconcileSchedulerAsync(policy).ConfigureAwait(false);
            return DescribeCore(policy, runtimeEligible);
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
            object policy;
            try
            {
                policy = _setPolicy(trustedShell, persistedMode);
            }
            catch
            {
                try
                {
                    var currentPolicy = _describePolicy(trustedShell);
                    _ = await ReconcileSchedulerAsync(currentPolicy).ConfigureAwait(false);
                }
                catch
                {
                    await _scheduler.StopAsync().ConfigureAwait(false);
                }
                throw;
            }

            var runtimeEligible = await ReconcileSchedulerAsync(policy).ConfigureAwait(false);
            return DescribeCore(policy, runtimeEligible);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    internal async Task<object> StopAsync(bool trustedShell, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var policy = _describePolicy(trustedShell);
            await _scheduler.StopAsync().ConfigureAwait(false);
            return DescribeCore(policy, RuntimeEligibleFor(policy));
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    internal object Describe(bool trustedShell)
    {
        ThrowIfDisposed();
        _lifecycleGate.Wait();
        try
        {
            object policy;
            try
            {
                policy = _describePolicy(trustedShell);
                return DescribeCore(policy, RuntimeEligibleFor(policy));
            }
            catch
            {
                _scheduler.StopAsync().GetAwaiter().GetResult();
                throw;
            }
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    private async Task<bool> ReconcileSchedulerAsync(object policy)
    {
        if (!AllowsBackgroundChecks(policy))
        {
            await _scheduler.StopAsync().ConfigureAwait(false);
            return false;
        }

        bool runtimeEligible;
        try
        {
            runtimeEligible = _runtimeEligibility();
        }
        catch
        {
            await _scheduler.StopAsync().ConfigureAwait(false);
            throw;
        }

        if (runtimeEligible)
        {
            _scheduler.Start();
            return true;
        }

        await _scheduler.StopAsync().ConfigureAwait(false);
        return false;
    }

    private bool RuntimeEligibleFor(object policy)
    {
        if (!AllowsBackgroundChecks(policy))
            return false;
        return _runtimeEligibility();
    }

    private object DescribeCore(object policy, bool runtimeEligible) => new
    {
        schema = ControllerSchema,
        policy,
        runtimeEligible,
        schedulerAllowed = AllowsBackgroundChecks(policy) && runtimeEligible,
        scheduler = _scheduler.Describe(),
        failClosedPolicy = true,
        failClosedRuntimeEligibility = true,
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
        if (_disposed || Volatile.Read(ref _disposeStarted) != 0)
            throw new ObjectDisposedException(nameof(DesktopUpdateBackgroundHostController));
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposeStarted, 1) != 0)
            return;

        await _lifecycleGate.WaitAsync().ConfigureAwait(false);
        try
        {
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
