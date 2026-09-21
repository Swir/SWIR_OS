using System.Net;
using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopUpdateBackgroundCycleSelfTests
{
    public static int Main()
    {
        var failures = new List<string>();
        Run("manual mode suppresses background network work", ManualSuppressesWithoutNetwork, failures);
        Run("notify-only verifies feed without automatic preparation", NotifyChecksWithoutPreparing, failures);
        Run("automatic verifies feed and prepares without restart", AutomaticChecksAndPrepares, failures);
        Run("policy downgrade during signed check suppresses preparation", DowngradeDuringCheckSuppressesPreparation, failures);
        Run("background cycle requires trusted shell", UntrustedCallerRejectedBeforeNetwork, failures);

        if (failures.Count == 0)
        {
            Console.WriteLine("Desktop update background cycle self-tests passed.");
            return 0;
        }

        Console.Error.WriteLine(string.Join(Environment.NewLine, failures));
        return 1;
    }

    private static void ManualSuppressesWithoutNetwork()
    {
        using var f = new Fixture();
        _ = f.Service.SetUserPolicy(true, "manual");
        var result = Json(f.Service.RunBackgroundCycleAsync(true).GetAwaiter().GetResult());
        Expect(result.GetProperty("action").GetString() == "suppressed", "manual mode must suppress the scheduler cycle");
        Expect(!result.GetProperty("verified").GetBoolean(), "manual mode must not claim feed verification when no request was made");
        Expect(f.ManifestRequests == 0, "manual mode must perform zero manifest requests");
        Expect(f.PreparationExecutions == 0, "manual mode must perform zero automatic preparation executions");
    }

    private static void NotifyChecksWithoutPreparing()
    {
        using var f = new Fixture();
        var result = Json(f.Service.RunBackgroundCycleAsync(true).GetAwaiter().GetResult());
        Expect(result.GetProperty("action").GetString() == "notify", "notify-only must surface an available verified update");
        Expect(result.GetProperty("verified").GetBoolean(), "notify-only background check must verify the signed feed");
        Expect(result.GetProperty("updateAvailable").GetBoolean(), "fixture must expose a newer signed update");
        Expect(!result.GetProperty("automaticPreparation").GetBoolean(), "notify-only must not stage automatically");
        Expect(!result.GetProperty("automaticRestart").GetBoolean(), "notify-only must never auto-restart");
        Expect(f.ManifestRequests == 1, "notify-only must make exactly one signed manifest request");
        Expect(f.PreparationExecutions == 0, "notify-only must not execute preparation");
    }

    private static void AutomaticChecksAndPrepares()
    {
        using var f = new Fixture();
        _ = f.Service.SetUserPolicy(true, "automatic");
        var result = Json(f.Service.RunBackgroundCycleAsync(true).GetAwaiter().GetResult());
        Expect(result.GetProperty("action").GetString() == "prepared", "automatic mode must prepare a verified available update");
        Expect(result.GetProperty("verified").GetBoolean(), "automatic mode must verify the signed feed before preparation");
        Expect(result.GetProperty("automaticPreparation").GetBoolean(), "automatic mode must record automatic preparation");
        Expect(!result.GetProperty("automaticRestart").GetBoolean(), "automatic mode must still forbid silent restart");
        Expect(f.ManifestRequests == 1, "automatic discovery must make one signed manifest request in the test seam");
        Expect(f.PreparationExecutions == 1, "automatic mode must execute exactly one preparation operation");
        var host = Json(f.Service.Describe());
        Expect(host.GetProperty("preparation").GetProperty("state").GetString() == "ready", "successful automatic preparation must end in ready state");
    }

    private static void DowngradeDuringCheckSuppressesPreparation()
    {
        using var f = new Fixture();
        _ = f.Service.SetUserPolicy(true, "automatic");
        f.OnManifestRequest = () => _ = f.Service.SetUserPolicy(true, "manual");
        var result = Json(f.Service.RunBackgroundCycleAsync(true).GetAwaiter().GetResult());
        Expect(result.GetProperty("action").GetString() == "suppressed-after-check", "policy downgrade during signed check must suppress subsequent preparation");
        Expect(result.GetProperty("verified").GetBoolean(), "completed signed check remains verified evidence");
        Expect(result.GetProperty("mode").GetString() == "manual", "cycle must report the re-read downgraded policy");
        Expect(f.ManifestRequests == 1, "downgrade race test must complete exactly one signed manifest request");
        Expect(f.PreparationExecutions == 0, "downgrade race must prevent automatic preparation");
    }

    private static void UntrustedCallerRejectedBeforeNetwork()
    {
        using var f = new Fixture();
        try
        {
            _ = f.Service.RunBackgroundCycleAsync(false).GetAwaiter().GetResult();
        }
        catch (DesktopUpdateBridgeCommandException ex) when (ex.Code == "UPDATE_BRIDGE_TRUST_REQUIRED")
        {
            Expect(f.ManifestRequests == 0, "untrusted caller must be rejected before network access");
            Expect(f.PreparationExecutions == 0, "untrusted caller must be rejected before preparation");
            return;
        }

        throw new InvalidOperationException("Expected UPDATE_BRIDGE_TRUST_REQUIRED.");
    }

    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private static void Expect(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
    private static void Run(string name, Action test, List<string> failures)
    {
        try { test(); Console.WriteLine($"PASS {name}"); }
        catch (Exception ex) { failures.Add($"FAIL {name}: {ex.Message}"); }
    }

    private sealed class Fixture : IDisposable
    {
        private readonly RSA _rsa = RSA.Create(3072);
        private readonly string _root = Path.Combine(Path.GetTempPath(), "swir-update-background-cycle", Guid.NewGuid().ToString("N"));
        private readonly CountingHandler _handler;
        private readonly string _envelope;
        public DesktopUpdatePreparationHostService Service { get; }
        public int PreparationExecutions { get; private set; }
        public int ManifestRequests => _handler.RequestCount;
        public Action? OnManifestRequest { set => _handler.OnRequest = value; }

        public Fixture()
        {
            Directory.CreateDirectory(_root);
            var policyPath = Path.Combine(_root, "desktop-update-policy.json");
            var deploymentRoot = Path.Combine(_root, "deployment");
            var currentRoot = Path.Combine(deploymentRoot, "Current");
            var workerPath = Path.Combine(_root, "SWIR.Desktop.UpdaterWorker.exe");
            var transactionsRoot = Path.Combine(_root, "transactions");
            var userPolicyPath = Path.Combine(_root, DesktopUpdateUserPolicyStore.DefaultFileName);
            Directory.CreateDirectory(currentRoot);
            File.WriteAllText(workerPath, "selftest-worker");
            File.WriteAllText(policyPath, JsonSerializer.Serialize(new
            {
                Schema = DesktopUpdateReleasePolicy.PolicySchema,
                Enabled = true,
                Channel = "stable",
                ManifestUrl = "https://updates.swir.example/stable.json",
                ManifestHosts = new[] { "updates.swir.example" },
                PackageHosts = new[] { "downloads.swir.example" },
                PublicKeyPem = _rsa.ExportSubjectPublicKeyInfoPem()
            }));

            _envelope = Sign("0.5.8");
            _handler = new CountingHandler(() => _envelope);
            Service = new DesktopUpdatePreparationHostService(
                policyPath,
                currentRoot,
                workerPath,
                deploymentRoot,
                transactionsRoot,
                (broker, uri, hosts) => new UpdateManifestClient(
                    broker,
                    uri,
                    hosts,
                    new HttpClient(_handler, disposeHandler: false) { Timeout = Timeout.InfiniteTimeSpan }),
                new Version(0, 5, 7),
                userPolicyPath,
                cancellationToken =>
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    PreparationExecutions++;
                    return Task.FromResult<object?>(new
                    {
                        ready = true,
                        currentVersion = "0.5.7",
                        targetVersion = "0.5.8",
                        channel = "stable",
                        candidateVerified = true,
                        testSeam = true
                    });
                });
        }

        private string Sign(string version)
        {
            var payload = JsonSerializer.SerializeToUtf8Bytes(new
            {
                Schema = UpdateBroker.PayloadSchema,
                Version = version,
                Channel = "stable",
                PublishedAt = DateTimeOffset.UtcNow,
                Package = new
                {
                    Url = "https://downloads.swir.example/SWIR.Desktop.zip",
                    Sha256 = new string('a', 64),
                    Size = 1234L
                }
            });
            var signature = _rsa.SignData(payload, HashAlgorithmName.SHA256, RSASignaturePadding.Pss);
            return JsonSerializer.Serialize(new
            {
                Schema = UpdateBroker.EnvelopeSchema,
                Algorithm = UpdateBroker.SignatureAlgorithm,
                KeyId = "selftest-background-cycle-2026",
                Payload = Convert.ToBase64String(payload),
                Signature = Convert.ToBase64String(signature)
            });
        }

        public void Dispose()
        {
            _rsa.Dispose();
            _handler.Dispose();
            try { Directory.Delete(_root, true); } catch { }
        }
    }

    private sealed class CountingHandler : HttpMessageHandler
    {
        private readonly Func<string> _body;
        public int RequestCount { get; private set; }
        public Action? OnRequest { get; set; }
        public CountingHandler(Func<string> body) => _body = body;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            RequestCount++;
            OnRequest?.Invoke();
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(_body())
            });
        }
    }
}