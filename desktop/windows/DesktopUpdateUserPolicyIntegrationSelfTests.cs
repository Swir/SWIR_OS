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
        Run("downgrading automatic policy revokes queued automatic preparation", PolicyDowngradeRevokesQueuedAutomaticPrepare, failures);
        Run("policy downgrade does not revoke explicit user preparation", PolicyDowngradePreservesExplicitUserPrepare, failures);
        Run("user policy survives host service recreation", PolicyPersistsAcrossHostServiceRecreation, failures);
        Run("invalid policy mutation is fail-closed and atomic", InvalidPolicyMutationLeavesPriorPolicyUntouched, failures);
        Run("strict persistence rejects unknown fields", UnknownPersistedFieldFallsBackSafely, failures);
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

    private static void PolicyDowngradeRevokesQueuedAutomaticPrepare()
    {
        using var f = new Fixture();
        _ = f.Service.SetUserPolicy(true, "automatic");
        var queued = Json(f.Service.QueueAutomaticPrepare(true));
        Expect(queued.GetProperty("state").GetString() == "queued", "automatic preparation must first reach the acknowledged queued state");

        var downgraded = Json(f.Service.SetUserPolicy(true, "notify"));
        Expect(downgraded.GetProperty("mode").GetString() == "notify", "downgraded mode persists as notify-only");
        var host = Json(f.Service.Describe());
        Expect(host.GetProperty("preparation").GetProperty("state").GetString() == "idle", "policy downgrade must revoke queued automatic preparation before execution");
        ExpectNotQueued(() => f.Service.ExecuteQueuedAsync().GetAwaiter().GetResult());
    }

    private static void PolicyDowngradePreservesExplicitUserPrepare()
    {
        using var f = new Fixture();
        var queued = Json(f.Service.QueuePrepare(true));
        Expect(queued.GetProperty("state").GetString() == "queued", "explicit user preparation is queued in notify-only mode");
        _ = f.Service.SetUserPolicy(true, "manual");
        var host = Json(f.Service.Describe());
        Expect(host.GetProperty("preparation").GetProperty("state").GetString() == "queued", "manual mode must not revoke an explicit user-requested preparation");
        _ = f.Service.Cancel(true);
    }

    private static void PolicyPersistsAcrossHostServiceRecreation()
    {
        using var f = new Fixture();
        _ = f.Service.SetUserPolicy(true, "automatic");
        var recreated = f.CreateService();
        var policy = Json(recreated.DescribeUserPolicy(true));
        Expect(policy.GetProperty("mode").GetString() == "automatic", "recreated host must load the persisted automatic policy");
        Expect(policy.GetProperty("backgroundCheck").GetBoolean(), "recreated host keeps automatic background checks enabled");
        Expect(policy.GetProperty("automaticPrepare").GetBoolean(), "recreated host keeps automatic preparation enabled");
        Expect(!policy.GetProperty("automaticRestart").GetBoolean(), "recreated host still forbids silent restart");
    }

    private static void InvalidPolicyMutationLeavesPriorPolicyUntouched()
    {
        using var f = new Fixture();
        _ = f.Service.SetUserPolicy(true, "manual");
        ExpectInvalidPolicy(() => f.Service.SetUserPolicy(true, "automatic-and-restart"));
        var policy = Json(f.Service.DescribeUserPolicy(true));
        Expect(policy.GetProperty("mode").GetString() == "manual", "invalid mutation must not replace the prior persisted policy");
        Expect(!policy.GetProperty("backgroundCheck").GetBoolean(), "invalid mutation cannot silently re-enable background work");
        Expect(!policy.GetProperty("automaticPrepare").GetBoolean(), "invalid mutation cannot silently enable automatic preparation");
    }

    private static void UnknownPersistedFieldFallsBackSafely()
    {
        using var f = new Fixture();
        File.WriteAllText(f.UserPolicyPath, "{\"schemaVersion\":1,\"mode\":\"automatic\",\"automaticRestart\":true}");
        var policy = Json(f.Service.DescribeUserPolicy(true));
        Expect(policy.GetProperty("mode").GetString() == "notify", "unknown persisted fields fail safe to notify-only");
        Expect(!policy.GetProperty("automaticPrepare").GetBoolean(), "rejected extended record cannot enable automatic preparation");
        Expect(!policy.GetProperty("automaticRestart").GetBoolean(), "rejected extended record cannot enable automatic restart");
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

    private static void ExpectInvalidPolicy(Action action)
    {
        try { action(); }
        catch (DesktopUpdateBridgeCommandException ex) when (ex.Code == "UPDATE_USER_POLICY_INVALID") { return; }
        throw new InvalidOperationException("Expected UPDATE_USER_POLICY_INVALID.");
    }

    private static void ExpectNotQueued(Action action)
    {
        try { action(); }
        catch (DesktopUpdateBridgeCommandException ex) when (ex.Code == "UPDATE_PREPARATION_NOT_QUEUED") { return; }
        throw new InvalidOperationException("Expected UPDATE_PREPARATION_NOT_QUEUED.");
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
        private readonly string _policyPath;
        private readonly string _deploymentRoot;
        private readonly string _currentRoot;
        private readonly string _workerPath;
        private readonly string _transactionsRoot;
        private readonly string _envelope;
        public DesktopUpdatePreparationHostService Service { get; }
        public string UserPolicyPath { get; }

        public Fixture()
        {
            Directory.CreateDirectory(_root);
            _policyPath = Path.Combine(_root, "desktop-update-policy.json");
            _deploymentRoot = Path.Combine(_root, "deployment");
            _currentRoot = Path.Combine(_deploymentRoot, "Current");
            _workerPath = Path.Combine(_root, "SWIR.Desktop.UpdaterWorker.exe");
            _transactionsRoot = Path.Combine(_root, "transactions");
            UserPolicyPath = Path.Combine(_root, DesktopUpdateUserPolicyStore.DefaultFileName);
            Directory.CreateDirectory(_currentRoot);
            File.WriteAllText(_workerPath, "selftest-worker");
            File.WriteAllText(_policyPath, JsonSerializer.Serialize(new
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
            Service = CreateService();
        }

        public DesktopUpdatePreparationHostService CreateService()
            => new(
                _policyPath,
                _currentRoot,
                _workerPath,
                _deploymentRoot,
                _transactionsRoot,
                (broker, uri, hosts) => new UpdateManifestClient(
                    broker,
                    uri,
                    hosts,
                    new HttpClient(new StaticHandler(_envelope)) { Timeout = Timeout.InfiniteTimeSpan }),
                new Version(0, 5, 7),
                UserPolicyPath);

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
