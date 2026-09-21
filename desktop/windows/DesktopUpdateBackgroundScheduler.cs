namespace Swir.Desktop.Host;

/// <summary>
/// Owns periodic Desktop update cycles without weakening the policy/security gates
/// enforced by <see cref="DesktopUpdatePreparationHostService"/>. The supplied cycle
/// callback remains responsible for applying Manual / Notify-only / Automatic policy.
/// This scheduler never installs or restarts the host by itself.
/// </summary>
internal sealed class DesktopUpdateBackgroundScheduler : IAsyncDisposable
{
    public const string SchedulerSchema = "swir.desktop-update-background-scheduler/0.2";
    public static readonly TimeSpan DefaultInterval = TimeSpan.FromHours(6);
    public static readonly TimeSpan DefaultInitialDelay = TimeSpan.FromMinutes(2);

    private readonly Func<CancellationToken, Task<object>> _cycle;
    private readonly Action<DesktopUpdateBackgroundSchedulerEvent>? _eventSink;
    private readonly TimeSpan _interval;
    private readonly TimeSpan _initialDelay;
    private readonly SemaphoreSlim _executionGate = new(1, 1);
    private readonly object _stateGate = new();

    private CancellationTokenSource? _lifetime;
    private Task? _runner;
    private DateTimeOffset? _lastStartedAt;
    private DateTimeOffset? _lastCompletedAt;
    private DateTimeOffset? _nextScheduledAt;
    private string _lastOutcome = "never";
    private long _completedCycles;
    private long _failedCycles;
    private long _cancelledCycles;
    private long _skippedOverlapCycles;
    private bool _disposed;

    public DesktopUpdateBackgroundScheduler(
        Func<CancellationToken, Task<object>> cycle,
        TimeSpan? interval = null,
        TimeSpan? initialDelay = null,
        Action<DesktopUpdateBackgroundSchedulerEvent>? eventSink = null)
    {
        ArgumentNullException.ThrowIfNull(cycle);
        _cycle = cycle;
        _interval = interval ?? DefaultInterval;
        _initialDelay = initialDelay ?? DefaultInitialDelay;
        _eventSink = eventSink;

        if (_interval <= TimeSpan.Zero)
            throw new ArgumentOutOfRangeException(nameof(interval), "Background update interval must be positive.");
        if (_initialDelay < TimeSpan.Zero)
            throw new ArgumentOutOfRangeException(nameof(initialDelay), "Background update initial delay cannot be negative.");
    }

    public object Describe()
    {
        lock (_stateGate)
        {
            return new
            {
                schema = SchedulerSchema,
                running = _runner is { IsCompleted: false },
                intervalSeconds = _interval.TotalSeconds,
                initialDelaySeconds = _initialDelay.TotalSeconds,
                lastStartedAt = _lastStartedAt,
                lastCompletedAt = _lastCompletedAt,
                nextScheduledAt = _nextScheduledAt,
                lastOutcome = _lastOutcome,
                completedCycles = _completedCycles,
                failedCycles = _failedCycles,
                cancelledCycles = _cancelledCycles,
                skippedOverlapCycles = _skippedOverlapCycles,
                overlappingCyclesAllowed = false,
                automaticRestart = false
            };
        }
    }

    public bool Start()
    {
        lock (_stateGate)
        {
            ThrowIfDisposed();
            if (_runner is { IsCompleted: false })
                return false;

            _lifetime?.Dispose();
            _lifetime = new CancellationTokenSource();
            _runner = RunLoopAsync(_lifetime.Token);
            return true;
        }
    }

    public async Task StopAsync()
    {
        CancellationTokenSource? lifetime;
        Task? runner;
        lock (_stateGate)
        {
            lifetime = _lifetime;
            runner = _runner;
            if (lifetime is null || runner is null)
            {
                _nextScheduledAt = null;
                return;
            }
            lifetime.Cancel();
        }

        try
        {
            await runner.ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested)
        {
        }

        lock (_stateGate)
        {
            if (ReferenceEquals(_lifetime, lifetime))
            {
                _runner = null;
                _lifetime = null;
                _nextScheduledAt = null;
                lifetime.Dispose();
            }
        }
    }

    public Task<DesktopUpdateBackgroundSchedulerCycle> RunOnceAsync(CancellationToken cancellationToken = default)
    {
        lock (_stateGate)
            ThrowIfDisposed();
        return ExecuteCycleAsync(cancellationToken);
    }

    private async Task RunLoopAsync(CancellationToken cancellationToken)
    {
        if (_initialDelay > TimeSpan.Zero)
        {
            SetNextScheduledAt(DateTimeOffset.UtcNow + _initialDelay);
            await Task.Delay(_initialDelay, cancellationToken).ConfigureAwait(false);
        }

        while (!cancellationToken.IsCancellationRequested)
        {
            SetNextScheduledAt(null);
            _ = await ExecuteCycleAsync(cancellationToken).ConfigureAwait(false);
            SetNextScheduledAt(DateTimeOffset.UtcNow + _interval);
            await Task.Delay(_interval, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<DesktopUpdateBackgroundSchedulerCycle> ExecuteCycleAsync(CancellationToken cancellationToken)
    {
        if (!await _executionGate.WaitAsync(0, cancellationToken).ConfigureAwait(false))
        {
            var skippedAt = DateTimeOffset.UtcNow;
            lock (_stateGate)
            {
                _skippedOverlapCycles++;
                _lastOutcome = "skipped-overlap";
            }
            Publish(new DesktopUpdateBackgroundSchedulerEvent(SchedulerSchema, "skipped-overlap", skippedAt, null));
            return new DesktopUpdateBackgroundSchedulerCycle(false, "skipped-overlap", null);
        }

        var startedAt = DateTimeOffset.UtcNow;
        lock (_stateGate)
        {
            _lastStartedAt = startedAt;
            _lastOutcome = "running";
        }

        try
        {
            var result = await _cycle(cancellationToken).ConfigureAwait(false);
            var completedAt = DateTimeOffset.UtcNow;
            lock (_stateGate)
            {
                _lastCompletedAt = completedAt;
                _lastOutcome = "completed";
                _completedCycles++;
            }
            Publish(new DesktopUpdateBackgroundSchedulerEvent(SchedulerSchema, "completed", completedAt, result));
            return new DesktopUpdateBackgroundSchedulerCycle(true, "completed", result);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            var cancelledAt = DateTimeOffset.UtcNow;
            lock (_stateGate)
            {
                _lastCompletedAt = cancelledAt;
                _lastOutcome = "cancelled";
                _cancelledCycles++;
            }
            Publish(new DesktopUpdateBackgroundSchedulerEvent(SchedulerSchema, "cancelled", cancelledAt, null));
            throw;
        }
        catch (Exception ex)
        {
            var failedAt = DateTimeOffset.UtcNow;
            lock (_stateGate)
            {
                _lastCompletedAt = failedAt;
                _lastOutcome = "failed";
                _failedCycles++;
            }
            Publish(new DesktopUpdateBackgroundSchedulerEvent(
                SchedulerSchema,
                "failed",
                failedAt,
                new { errorType = ex.GetType().Name, message = ex.Message }));
            return new DesktopUpdateBackgroundSchedulerCycle(true, "failed", null);
        }
        finally
        {
            _executionGate.Release();
        }
    }

    private void SetNextScheduledAt(DateTimeOffset? value)
    {
        lock (_stateGate)
            _nextScheduledAt = value;
    }

    private void Publish(DesktopUpdateBackgroundSchedulerEvent schedulerEvent)
    {
        try { _eventSink?.Invoke(schedulerEvent); }
        catch
        {
            // UI/event delivery must never terminate the scheduler or weaken update policy.
        }
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
            throw new ObjectDisposedException(nameof(DesktopUpdateBackgroundScheduler));
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;
        await StopAsync().ConfigureAwait(false);
        lock (_stateGate)
            _disposed = true;
        _executionGate.Dispose();
    }
}

internal sealed record DesktopUpdateBackgroundSchedulerCycle(bool Executed, string Outcome, object? Result);
internal sealed record DesktopUpdateBackgroundSchedulerEvent(string Schema, string Kind, DateTimeOffset At, object? Detail);
