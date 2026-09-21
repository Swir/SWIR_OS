using System.Net;
using System.Security.Cryptography;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopUpdateUserPolicyIntegrationSelfTests
{
    public static int Main()
    {
        var failures = new List<string>();
        Run("notify-only is safe default and permits background checks", NotifyOnlyDefaultAllowsBackgroundCheck, failures);
        Run("notify-only blocks automatic preparation", NotifyOnlyBlocksAutomaticPrepare, failures);
        Run("manual blocks background checks but permits explicit checks", ManualBlocksBackgroundCheck, failures);
        Run("automatic permits background check and automatic preparation", AutomaticPermitsBackgroundWork, failures);
        Run("untrusted callers cannot inspect or change user policy", UntrustedCallerRejected, failures);
        Run("invalid persisted policy falls back to notify-only", InvalidPersistedPolicyFallsBackSafely, failures);
        if (failures.Count == 0)
        {
            Console.WriteLine("Desktop update user policy integration self-tests passed.");
            return 0;
        }
        Console.Error.WriteLine(string.Join(Environment.NewLine, failures));
        return 1;
    }

    private static void NotifyOnlyDefaultAllowsBackgroundCheck()
    {
        using var f = new Fixture();
        var policy = Json(f.Service.DescribeUserPolicy(true));
        Expect(policy.GetProperty("mode").GetString() == "notify", "default mode is notify-only");
        Expect(policy.GetProperty("backgroundCheck").GetBoolean(), "notify-only allows background check");
        Expect(!policy.GetProperty("automaticPrepare").GetBoolean(), "notify-only never auto-prepares");
        var check = Json(f.Service.CheckInBackgroundAsync(true).GetAwaiter().GetResult());
        Expect(check.GetProperty("verified").GetBoolean(), "background check remains signature verified");
        Expect(check.GetProperty("updateAvailable").GetBoolean(), "newer signed update is discovered");
    }

    private static void NotifyOnlyBlocksAutomaticPrepare()
    {
        using var f = new Fixture();
        ExpectPolicyBlocked(() => f.Service.QueueAutomaticPrepare(true));
        var explicitPrepare = Json(f.Service.QueuePrepare(true));
        Expect(explicitPrepare.GetProperty("state").GetString() == "queued", "explicit preparation is allowed in notify-only mode");
        _ = f.Service.Cancel(true);
    }

    private static void ManualBlocksBackgroundCheck()
    {
        using var f = new Fixture();
        var policy = Json(f.Service.SetUserPolicy(true, "manual"));
        Expect(policy.GetProperty("mode").GetString() == "manual", "manual mode persists");
        Expect(!policy.GetProperty("backgroundCheck").GetBoolean(), "manual disables background checks");
        ExpectPolicyBlocked(() => f.Service.CheckInBackgroundAsync(true).GetAwaiter().GetResult());
        var explicitCheck = Json(f.Service.CheckAsync(true).GetAwaiter().GetResult());
        Expect(explicitCheck.GetProperty("verified").GetBoolean(), "manual explicit check still uses signed feed verification");
    }

    private static void AutomaticPermitsBackgroundWork()
    {
        using var f = new Fixture();
        var policy = Json(f.Service.SetUserPolicy(true, "automatic"));
        Expect(policy.GetProperty("backgroundCheck").GetBoolean(), "automatic enables background check");
        Expect(policy.GetProperty("automaticPrepare").GetBoolean(), "automatic enables preparation");
        Expect(!policy.GetProperty("automaticRestart").GetBoolean(), "automatic never silently restarts");
        var check = Json(f.Service.CheckInBackgroundAsync(true).GetAwaiter().GetResult());
        Expect(check.GetProperty("verified").GetBoolean(), "automatic background check remains verified");
        var queued = Json(f.Service.QueueAutomaticPrepare(true));
        Expect(queued.GetProperty("state").GetString() == "queued", "automatic preparation is queued only after policy allows it");
        _ = f.Service.Cancel(true);
    }

    private static void UntrustedCallerRejected()
    {
        using var f = new Fixture();
        ExpectTrustBlocked(() => f.Service.DescribeUserPolicy(false));
        ExpectTrustBlocked(() => f.Service.SetUserPolicy(false, "automatic"));
        ExpectTrustBlocked(() => f.Service.CheckInBackgroundAsync(false).GetAwaiter().GetResult());
    }

    private static void InvalidPersistedPolicyFallsBackSafely()
    {
        using var f = new Fixture();
        File.WriteAllText(f.UserPolicyPath, "{\"schemaVersion\":999,\"mode\":\"automatic\"}");
        var policy = Json(f.Service.DescribeUserPolicy(true));
        Expect(policy.GetProperty("mode").GetString() == "notify", "invalid record falls back to notify-only");
        Expect(!policy.GetProperty("automaticPrepare").GetBoolean(), "fallback cannot silently enable auto-preparation");
    }

    private static void ExpectPolicyBlocked(Action action)
    {
        try { action(); }
        catch (DesktopUpdateBridgeCommandException ex) when (ex.Code == "UPDATE_USER_POLICY_BLOCKED") { return; }
        throw new InvalidOperationException("Expected UPDATE_USER_POLICY_BLOCKED.");
    }

    private static void ExpectTrustBlocked(Action action)
    {
        try { action(); }
        catch (DesktopUpdateBridgeCommandException ex) when (ex.Code == "UPDATE_BRIDGE_TRUST_REQUIRED") { return; }
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
        private readonly string _root = Path.Combine(Path.GetTempPath(), "swir-update-user-policy", Guid.NewGuid().ToString("N"));
        public DesktopUpdatePreparationHostService Service { get; }
        public string UserPolicyPath { get; }

        public Fixture()
        {
            Directory.CreateDirectory(_root);
            var policyPath = Path.Combine(_root, "desktop-update-policy.json");
            var deploymentRoot = Path.Combine(_root, "deployment");
            var currentRoot = Path.Combine(deploymentRoot, "Current");
            var workerPath = Path.Combine(_root, "SWIR.Desktop.UpdaterWorker.exe");
            var transactionsRoot = Path.Combine(_root, "transactions");
            UserPolicyPath = Path.Combine(_root, DesktopUpdateUserPolicyStore.DefaultFileName);
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
            var envelope = Sign("0.5.8");
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
                    new HttpClient(new StaticHandler(envelope)) { Timeout = Timeout.InfiniteTimeSpan }),
                new Version(0, 5, 7),
                UserPolicyPath);
        }

        private string Sign(string version)
        {
            var payload = JsonSerializer.SerializeToUtf8Bytes(new
            {
                Schema = UpdateBroker.PayloadSchema,
                Version = version,
                Channel = "stable",
                PublishedAt = DateTimeOffset.UtcNow,
                Package = new { Url = "https://downloads.swir.example/SWIR.Desktop.zip", Sha256 = new string('a', 64), Size = 1234L }
            });
            var signature = _rsa.SignData(payload, HashAlgorithmName.SHA256, RSASignaturePadding.Pss);
            return JsonSerializer.Serialize(new
            {
                Schema = UpdateBroker.EnvelopeSchema,
                Algorithm = UpdateBroker.SignatureAlgorithm,
                KeyId = "selftest-update-user-policy-2026",
                Payload = Convert.ToBase64String(payload),
                Signature = Convert.ToBase64String(signature)
            });
        }

        public void Dispose()
        {
            _rsa.Dispose();
            try { Directory.Delete(_root, true); } catch { }
        }
    }

    private sealed class StaticHandler : HttpMessageHandler
    {
        private readonly string _body;
        public StaticHandler(string body) => _body = body;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(_body) });
    }
}
