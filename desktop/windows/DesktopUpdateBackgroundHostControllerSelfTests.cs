using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopUpdateBackgroundHostControllerSelfTests
{
    public static int Main()
    {
        var failures = new List<string>();
        Run("notify policy starts scheduler", NotifyStartsScheduler, failures);
        Run("manual policy keeps scheduler stopped", ManualKeepsSchedulerStopped, failures);
        Run("policy downgrade stops scheduler", DowngradeStopsScheduler, failures);
        Run("automatic policy restarts scheduler without restart permission", AutomaticRestartsSchedulerSafely, failures);
        Run("malformed policy shape fails closed", MalformedPolicyFailsClosed, failures);
        Run("policy read failure stops stale scheduler", PolicyReadFailureStopsStaleScheduler, failures);
        Run("describe policy failure stops stale scheduler", DescribeFailureStopsStaleScheduler, failures);
        Run("policy write failure reconciles authoritative policy", PolicyWriteFailureReconcilesCurrentPolicy, failures);
        Run("policy write plus reread failure stops stale scheduler", PolicyWriteAndReadFailureStopsStaleScheduler, failures);
        Run("concurrent disposal is idempotent", ConcurrentDisposalIsIdempotent, failures);
        Run("untrusted policy access is preserved", UntrustedAccessIsRejected, failures);

        if (failures.Count == 0)
        {
            Console.WriteLine("Desktop update background host controller self-tests passed.");
            return 0;
        }

        Console.Error.WriteLine(string.Join(Environment.NewLine, failures));
        return 1;
    }

    private static void NotifyStartsScheduler()
    {
        using var f = new Fixture("notify");
        var state = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(state.GetProperty("scheduler").GetProperty("running").GetBoolean(), "notify policy must start the scheduler");
        Expect(state.GetProperty("policy").GetProperty("backgroundCheck").GetBoolean(), "notify policy must retain background checks");
        Expect(!state.GetProperty("automaticRestart").GetBoolean(), "host controller must never permit automatic restart");
    }

    private static void ManualKeepsSchedulerStopped()
    {
        using var f = new Fixture("manual");
        var state = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(!state.GetProperty("scheduler").GetProperty("running").GetBoolean(), "manual policy must not run the scheduler");
        Expect(f.Cycles == 0, "manual policy must not invoke a background cycle");
    }

    private static void DowngradeStopsScheduler()
    {
        using var f = new Fixture("notify");
        _ = f.Controller.StartAsync(true).GetAwaiter().GetResult();
        var state = Json(f.Controller.SetUserPolicyAsync(true, "manual").GetAwaiter().GetResult());
        Expect(state.GetProperty("policy").GetProperty("mode").GetString() == "manual", "manual downgrade must persist");
        Expect(!state.GetProperty("scheduler").GetProperty("running").GetBoolean(), "manual downgrade must stop the scheduler immediately");
    }

    private static void AutomaticRestartsSchedulerSafely()
    {
        using var f = new Fixture("manual");
        _ = f.Controller.StartAsync(true).GetAwaiter().GetResult();
        var state = Json(f.Controller.SetUserPolicyAsync(true, "automatic").GetAwaiter().GetResult());
        Expect(state.GetProperty("scheduler").GetProperty("running").GetBoolean(), "automatic policy must start scheduler checks");
        Expect(state.GetProperty("policy").GetProperty("automaticPrepare").GetBoolean(), "automatic policy must permit preparation");
        Expect(!state.GetProperty("policy").GetProperty("automaticRestart").GetBoolean(), "automatic policy must still forbid silent restart");
    }

    private static void MalformedPolicyFailsClosed()
    {
        using var f = new Fixture("notify") { ReturnMalformedPolicy = true };
        var state = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(!state.GetProperty("scheduler").GetProperty("running").GetBoolean(), "missing backgroundCheck must stop rather than guess");
        Expect(state.GetProperty("failClosedPolicy").GetBoolean(), "controller must advertise fail-closed policy handling");
    }

    private static void PolicyReadFailureStopsStaleScheduler()
    {
        using var f = new Fixture("notify");
        var running = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(running.GetProperty("scheduler").GetProperty("running").GetBoolean(), "precondition: scheduler must be running");

        f.ThrowOnDescribe = true;
        try
        {
            _ = f.Controller.StartAsync(true).GetAwaiter().GetResult();
            throw new InvalidOperationException("Expected policy-read-failed.");
        }
        catch (InvalidOperationException ex) when (ex.Message == "policy-read-failed")
        {
        }

        f.ThrowOnDescribe = false;
        var after = Json(f.Controller.Describe(true));
        Expect(!after.GetProperty("scheduler").GetProperty("running").GetBoolean(), "policy read failure must stop stale scheduler state");
    }

    private static void DescribeFailureStopsStaleScheduler()
    {
        using var f = new Fixture("notify");
        var running = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(running.GetProperty("scheduler").GetProperty("running").GetBoolean(), "precondition: scheduler must be running");

        f.ThrowOnDescribe = true;
        try
        {
            _ = f.Controller.Describe(true);
            throw new InvalidOperationException("Expected policy-read-failed.");
        }
        catch (InvalidOperationException ex) when (ex.Message == "policy-read-failed")
        {
        }

        f.ThrowOnDescribe = false;
        var after = Json(f.Controller.Describe(true));
        Expect(!after.GetProperty("scheduler").GetProperty("running").GetBoolean(), "failed status read must not retain stale scheduler permissions");
    }

    private static void PolicyWriteFailureReconcilesCurrentPolicy()
    {
        using var f = new Fixture("notify");
        var running = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(running.GetProperty("scheduler").GetProperty("running").GetBoolean(), "precondition: scheduler must be running");

        f.ThrowOnSet = true;
        try
        {
            _ = f.Controller.SetUserPolicyAsync(true, "manual").GetAwaiter().GetResult();
            throw new InvalidOperationException("Expected policy-write-failed.");
        }
        catch (InvalidOperationException ex) when (ex.Message == "policy-write-failed")
        {
        }

        f.ThrowOnSet = false;
        var after = Json(f.Controller.Describe(true));
        Expect(after.GetProperty("scheduler").GetProperty("running").GetBoolean(), "failed write with readable notify policy must retain the verified scheduler decision");
        Expect(after.GetProperty("policy").GetProperty("mode").GetString() == "notify", "failed write must not invent a policy transition");
    }

    private static void PolicyWriteAndReadFailureStopsStaleScheduler()
    {
        using var f = new Fixture("notify");
        var running = Json(f.Controller.StartAsync(true).GetAwaiter().GetResult());
        Expect(running.GetProperty("scheduler").GetProperty("running").GetBoolean(), "precondition: scheduler must be running");

        f.ThrowOnSet = true;
        f.ThrowOnDescribe = true;
        try
        {
            _ = f.Controller.SetUserPolicyAsync(true, "manual").GetAwaiter().GetResult();
            throw new InvalidOperationException("Expected policy-write-failed.");
        }
        catch (InvalidOperationException ex) when (ex.Message == "policy-write-failed")
        {
        }

        f.ThrowOnSet = false;
        f.ThrowOnDescribe = false;
        var after = Json(f.Controller.Describe(true));
        Expect(!after.GetProperty("scheduler").GetProperty("running").GetBoolean(), "unverifiable post-write policy must stop stale scheduler state");
    }

    private static void ConcurrentDisposalIsIdempotent()
    {
        using var f = new Fixture("notify");
        _ = f.Controller.StartAsync(true).GetAwaiter().GetResult();
        var tasks = Enumerable.Range(0, 8)
            .Select(_ => f.Controller.DisposeAsync().AsTask())
            .ToArray();
        Task.WhenAll(tasks).GetAwaiter().GetResult();

        try
        {
            _ = f.Controller.Describe(true);
        }
        catch (ObjectDisposedException)
        {
            return;
        }
        throw new InvalidOperationException("Disposed controller accepted a new lifecycle operation.");
    }

    private static void UntrustedAccessIsRejected()
    {
        using var f = new Fixture("notify");
        try
        {
            _ = f.Controller.StartAsync(false).GetAwaiter().GetResult();
        }
        catch (InvalidOperationException ex) when (ex.Message == "trusted-shell-required")
        {
            return;
        }
        throw new InvalidOperationException("Expected trusted-shell-required.");
    }

    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private static void Expect(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void Run(string name, Action test, List<string> failures)
    {
        try { test(); Console.WriteLine($"PASS {name}"); }
        catch (Exception ex) { failures.Add($"FAIL {name}: {ex.Message}"); }
    }

    private sealed class Fixture : IDisposable
    {
        private string _mode;
        public int Cycles { get; private set; }
        public bool ReturnMalformedPolicy { get; set; }
        public bool ThrowOnDescribe { get; set; }
        public bool ThrowOnSet { get; set; }
        public DesktopUpdateBackgroundHostController Controller { get; }

        public Fixture(string initialMode)
        {
            _mode = initialMode;
            Controller = new DesktopUpdateBackgroundHostController(
                cancellationToken =>
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    Cycles++;
                    return Task.FromResult<object>(new { action = "checked", automaticRestart = false });
                },
                trustedShell =>
                {
                    RequireTrusted(trustedShell);
                    if (ThrowOnDescribe) throw new InvalidOperationException("policy-read-failed");
                    return ReturnMalformedPolicy ? new { mode = _mode } : Policy(_mode);
                },
                (trustedShell, mode) =>
                {
                    RequireTrusted(trustedShell);
                    if (ThrowOnSet) throw new InvalidOperationException("policy-write-failed");
                    _mode = Normalize(mode);
                    return Policy(_mode);
                },
                interval: TimeSpan.FromHours(1),
                initialDelay: TimeSpan.FromHours(1));
        }

        private static object Policy(string mode) => mode switch
        {
            "manual" => new { mode, backgroundCheck = false, automaticPrepare = false, automaticRestart = false },
            "automatic" => new { mode, backgroundCheck = true, automaticPrepare = true, automaticRestart = false },
            _ => new { mode = "notify", backgroundCheck = true, automaticPrepare = false, automaticRestart = false }
        };

        private static string Normalize(string mode) => mode.Trim().ToLowerInvariant() switch
        {
            "manual" => "manual",
            "automatic" => "automatic",
            "notify" or "notify-only" or "notifyonly" => "notify",
            _ => throw new InvalidOperationException("invalid-policy")
        };

        private static void RequireTrusted(bool trustedShell)
        {
            if (!trustedShell) throw new InvalidOperationException("trusted-shell-required");
        }

        public void Dispose() => Controller.DisposeAsync().AsTask().GetAwaiter().GetResult();
    }
}
