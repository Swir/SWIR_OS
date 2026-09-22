using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;

namespace Swir.Desktop.Host;

/// <summary>
/// Production lifetime binding for the policy-aware Desktop background update controller.
/// It composes the same signed-feed/preparation host used by Update Center, starts only
/// inside the Desktop Host process and drains the scheduler during application shutdown.
/// User policy and runtime eligibility remain independent fail-closed gates.
/// </summary>
internal sealed class DesktopUpdateBackgroundHostRuntime : IAsyncDisposable
{
    public const string RuntimeSchema = "swir.desktop-update-background-runtime/0.1";

    private readonly DesktopUpdateBackgroundHostController _controller;
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private bool _started;
    private bool _disposed;

    internal DesktopUpdateBackgroundHostRuntime(DesktopUpdatePreparationHostService preparationHost)
    {
        ArgumentNullException.ThrowIfNull(preparationHost);

        _controller = new DesktopUpdateBackgroundHostController(
            cancellationToken => preparationHost.RunBackgroundCycleAsync(
                trustedShell: true,
                cancellationToken),
            preparationHost.DescribeUserPolicy,
            preparationHost.SetUserPolicy,
            eventSink: PublishSchedulerEvent,
            runtimeEligibility: () => IsRuntimeEligible(preparationHost));
    }

    internal async Task<object> StartAsync(CancellationToken cancellationToken = default)
    {
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ThrowIfDisposed();
            if (_started)
                return DescribeCore(_controller.Describe(trustedShell: true));

            var state = await _controller.StartAsync(
                trustedShell: true,
                cancellationToken).ConfigureAwait(false);
            _started = true;
            return DescribeCore(state);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    internal object Describe()
    {
        _lifecycleGate.Wait();
        try
        {
            ThrowIfDisposed();
            return DescribeCore(_controller.Describe(trustedShell: true));
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    internal async Task<object> SetUserPolicyAsync(
        string persistedMode,
        CancellationToken cancellationToken = default)
    {
        _lifecycleGate.Wait(cancellationToken);
        try
        {
            ThrowIfDisposed();
            var state = await _controller.SetUserPolicyAsync(
                trustedShell: true,
                persistedMode,
                cancellationToken).ConfigureAwait(false);
            _started = true;
            return DescribeCore(state);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    private object DescribeCore(object controllerState) => new
    {
        schema = RuntimeSchema,
        started = _started,
        controller = controllerState,
        failClosedRuntimeEligibility = true,
        automaticRestart = false
    };

    private static bool IsRuntimeEligible(DesktopUpdatePreparationHostService preparationHost)
    {
        try
        {
            var status = JsonSerializer.SerializeToElement(preparationHost.Describe());
            return status.ValueKind == JsonValueKind.Object
                && status.TryGetProperty("configured", out var configured)
                && configured.ValueKind == JsonValueKind.True
                && status.TryGetProperty("feedConfigured", out var feedConfigured)
                && feedConfigured.ValueKind == JsonValueKind.True
                && status.TryGetProperty("failClosed", out var failClosed)
                && failClosed.ValueKind == JsonValueKind.True;
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException or InvalidOperationException or IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static void PublishSchedulerEvent(DesktopUpdateBackgroundSchedulerEvent schedulerEvent)
    {
        Trace.TraceInformation(
            "SWIR Desktop background update scheduler: {0} at {1:O}",
            schedulerEvent.Kind,
            schedulerEvent.At);
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
            throw new ObjectDisposedException(nameof(DesktopUpdateBackgroundHostRuntime));
    }

    public async ValueTask DisposeAsync()
    {
        await _lifecycleGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_disposed)
                return;

            _disposed = true;
            _started = false;
            await _controller.DisposeAsync().ConfigureAwait(false);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }
}

/// <summary>
/// Hooks the background update runtime into the real WinForms Desktop Host lifetime
/// without exposing privileged update controls to application packages or web content.
/// The first WinForms idle turn starts the controller; application exit always drains it.
/// </summary>
internal static class DesktopUpdateBackgroundHostBootstrap
{
    private static readonly object Sync = new();
    private static DesktopUpdateBackgroundHostRuntime? _runtime;
    private static int _startClaimed;
    private static int _stopClaimed;

    [ModuleInitializer]
    internal static void Register()
    {
        Application.Idle += StartOnFirstIdle;
        Application.ApplicationExit += StopOnApplicationExit;
    }

    private static async void StartOnFirstIdle(object? sender, EventArgs e)
    {
        if (Interlocked.Exchange(ref _startClaimed, 1) != 0)
            return;

        Application.Idle -= StartOnFirstIdle;

        var runtime = new DesktopUpdateBackgroundHostRuntime(
            new DesktopUpdatePreparationHostService());
        lock (Sync)
            _runtime = runtime;

        try
        {
            _ = await runtime.StartAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Trace.TraceError(
                "SWIR Desktop background update runtime failed closed during startup: {0}",
                ex.Message);
            await runtime.DisposeAsync().ConfigureAwait(true);
            lock (Sync)
            {
                if (ReferenceEquals(_runtime, runtime))
                    _runtime = null;
            }
        }
    }

    private static void StopOnApplicationExit(object? sender, EventArgs e)
    {
        if (Interlocked.Exchange(ref _stopClaimed, 1) != 0)
            return;

        Application.Idle -= StartOnFirstIdle;

        DesktopUpdateBackgroundHostRuntime? runtime;
        lock (Sync)
        {
            runtime = _runtime;
            _runtime = null;
        }

        if (runtime is null)
            return;

        try
        {
            runtime.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        catch (Exception ex)
        {
            Trace.TraceError(
                "SWIR Desktop background update runtime shutdown failed closed: {0}",
                ex.Message);
        }
    }
}