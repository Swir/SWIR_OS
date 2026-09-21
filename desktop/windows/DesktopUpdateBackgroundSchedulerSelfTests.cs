namespace Swir.Desktop.Host;

internal static class DesktopUpdateBackgroundSchedulerSelfTests
{
    public static int Main()
    {
        var failures = new List<string>();
        Run("rejects invalid cadence", RejectsInvalidCadence, failures);
        Run("start is idempotent and stop is clean", StartStopLifecycleAsync, failures);
        Run("periodic and explicit cycles never overlap", CyclesNeverOverlapAsync, failures);
        Run("cycle failure is contained and scheduler continues", FailureIsContainedAsync, failures);
        Run("event sink failure cannot terminate scheduling", EventSinkFailureIsContainedAsync, failures);

        if (failures.Count == 0)
        {
            Console.WriteLine("Desktop update background scheduler self-tests passed.");
            return 0;
        }

        Console.Error.WriteLine(string.Join(Environment.NewLine, failures));
        return 1;
    }

    private static void RejectsInvalidCadence()
    {
        ExpectThrows<ArgumentOutOfRangeException>(() => new DesktopUpdateBackgroundScheduler(
            _ => Task.FromResult<object>(new { ok = true }), TimeSpan.Zero, TimeSpan.Zero));
        ExpectThrows<ArgumentOutOfRangeException>(() => new DesktopUpdateBackgroundScheduler(
            _ => Task.FromResult<object>(new { ok = true }), TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(-1)));
    }

    private static async Task StartStopLifecycleAsync()
    {
        var cycles = 0;
        await using var scheduler = new DesktopUpdateBackgroundScheduler(
            _ =>
            {
                Interlocked.Increment(ref cycles);
                return Task.FromResult<object>(new { ok = true });
            },
            TimeSpan.FromMilliseconds(20),
            TimeSpan.Zero);

        Expect(scheduler.Start(), "first Start must activate scheduler");
        Expect(!scheduler.Start(), "second Start must be idempotent");
        await WaitUntilAsync(() => Volatile.Read(ref cycles) >= 2, TimeSpan.FromSeconds(2));
        await scheduler.StopAsync();

        var snapshot = Json(scheduler.Describe());
        Expect(!snapshot.GetProperty("running").GetBoolean(), "scheduler must report stopped after StopAsync");
        var stoppedAt = Volatile.Read(ref cycles);
        await Task.Delay(80);
        Expect(Volatile.Read(ref cycles) == stoppedAt, "no cycles may run after stop completes");
    }

    private static async Task CyclesNeverOverlapAsync()
    {
        var active = 0;
        var maxActive = 0;
        var entered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

        await using var scheduler = new DesktopUpdateBackgroundScheduler(
            async cancellationToken =>
            {
                var now = Interlocked.Increment(ref active);
                UpdateMax(ref maxActive, now);
                entered.TrySetResult(true);
                try { await release.Task.WaitAsync(cancellationToken); }
                finally { Interlocked.Decrement(ref active); }
                return new { ok = true };
            },
            TimeSpan.FromMilliseconds(5),
            TimeSpan.Zero);

        Expect(scheduler.Start(), "scheduler must start");
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        var explicitCycle = await scheduler.RunOnceAsync();
        Expect(!explicitCycle.Executed && explicitCycle.Outcome == "skipped-overlap", "explicit cycle must be rejected while periodic cycle owns execution gate");
        release.TrySetResult(true);
        await Task.Delay(40);
        await scheduler.StopAsync();
        Expect(Volatile.Read(ref maxActive) == 1, "scheduler must never overlap update cycles");
    }

    private static async Task FailureIsContainedAsync()
    {
        var attempts = 0;
        var recovered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var scheduler = new DesktopUpdateBackgroundScheduler(
            _ =>
            {
                var attempt = Interlocked.Increment(ref attempts);
                if (attempt == 1) throw new InvalidOperationException("synthetic first-cycle failure");
                recovered.TrySetResult(true);
                return Task.FromResult<object>(new { attempt });
            },
            TimeSpan.FromMilliseconds(10),
            TimeSpan.Zero);

        scheduler.Start();
        await recovered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        await scheduler.StopAsync();
        Expect(Volatile.Read(ref attempts) >= 2, "scheduler must continue after a contained cycle failure");
    }

    private static async Task EventSinkFailureIsContainedAsync()
    {
        var cycles = 0;
        await using var scheduler = new DesktopUpdateBackgroundScheduler(
            _ => Task.FromResult<object>(new { cycle = Interlocked.Increment(ref cycles) }),
            TimeSpan.FromMilliseconds(10),
            TimeSpan.Zero,
            _ => throw new InvalidOperationException("synthetic event sink failure"));

        scheduler.Start();
        await WaitUntilAsync(() => Volatile.Read(ref cycles) >= 2, TimeSpan.FromSeconds(2));
        await scheduler.StopAsync();
        Expect(Volatile.Read(ref cycles) >= 2, "event delivery failure must not terminate scheduling");
    }

    private static System.Text.Json.JsonElement Json(object value)
        => System.Text.Json.JsonSerializer.SerializeToElement(value);

    private static async Task WaitUntilAsync(Func<bool> predicate, TimeSpan timeout)
    {
        using var timeoutCts = new CancellationTokenSource(timeout);
        while (!predicate())
            await Task.Delay(10, timeoutCts.Token);
    }

    private static void UpdateMax(ref int target, int value)
    {
        while (true)
        {
            var current = Volatile.Read(ref target);
            if (value <= current) return;
            if (Interlocked.CompareExchange(ref target, value, current) == current) return;
        }
    }

    private static void Run(string name, Action test, List<string> failures)
    {
        try { test(); Console.WriteLine($"PASS {name}"); }
        catch (Exception ex) { failures.Add($"FAIL {name}: {ex.Message}"); }
    }

    private static void Run(string name, Func<Task> test, List<string> failures)
    {
        try { test().GetAwaiter().GetResult(); Console.WriteLine($"PASS {name}"); }
        catch (Exception ex) { failures.Add($"FAIL {name}: {ex.Message}"); }
    }

    private static void Expect(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void ExpectThrows<TException>(Action action) where TException : Exception
    {
        try { action(); }
        catch (TException) { return; }
        throw new InvalidOperationException($"Expected {typeof(TException).Name}.");
    }
}
