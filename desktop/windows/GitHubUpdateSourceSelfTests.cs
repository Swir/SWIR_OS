using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace Swir.Desktop.Host;

internal static class GitHubUpdateSourceSelfTests
{
    private static int _passed;
    public static int Main()
    {
        var package = Encoding.UTF8.GetBytes("SWIR-GITHUB-RELEASE-ASSET");
        var sha256 = Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant();
        var update = new UpdateBroker.VerifiedUpdate(new Version(0, 5, 8), "preview", DateTimeOffset.UtcNow,
            new Uri("https://github.com/Swir/SWIR_OS/releases/download/desktop-v0.5.8-preview/SWIR-Desktop-0.5.8-preview.zip"),
            sha256, package.Length, "test-key");
        TrustedSingleRedirectDownloads(package, update);
        NonGitHubRedirectStaysBlocked(package, update with { PackageUri = new Uri("https://downloads.swir.example/update.zip") });
        LookalikeGitHubHostIsBlocked(package, update);
        HttpRedirectTargetIsBlocked(package, update);
        SecondRedirectIsBlocked(package, update);
        SignedGitHubSourceMustBeImmutable(package, update);
        OfficialReleasePathValidation();
        Console.WriteLine($"SWIR GitHub update source self-tests passed: {_passed}");
        return 0;
    }

    private static void TrustedSingleRedirectDownloads(byte[] package, UpdateBroker.VerifiedUpdate update)
    {
        var root = TempRoot();
        try
        {
            var requests = new List<Uri>();
            var handler = new StaticHandler(request =>
            {
                requests.Add(request.RequestUri!);
                return requests.Count == 1
                    ? Response(Array.Empty<byte>(), HttpStatusCode.Found, 0, "https://release-assets.githubusercontent.com/github-production-release-asset/asset.zip?sig=test")
                    : Response(package, HttpStatusCode.OK, package.Length);
            });
            using var client = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
            using var downloader = new UpdateDownloadClient(new UpdateStagingBroker(root), client);
            var staged = downloader.DownloadAndStageAsync(update).GetAwaiter().GetResult();
            Expect(staged.Verified, "trusted GitHub release redirect stages verified package");
            Expect(requests.Count == 2, "trusted GitHub release follows exactly one redirect");
            Expect(requests[0] == update.PackageUri, "first request uses exact signed GitHub release URL");
            Expect(requests[1].Host == "release-assets.githubusercontent.com", "second request targets GitHub content host");
        }
        finally { Delete(root); }
    }

    private static void NonGitHubRedirectStaysBlocked(byte[] package, UpdateBroker.VerifiedUpdate update)
    {
        var root = TempRoot();
        try
        {
            using var client = Client(_ => Response(package, HttpStatusCode.Found, package.Length, "https://release-assets.githubusercontent.com/a.zip"));
            using var downloader = new UpdateDownloadClient(new UpdateStagingBroker(root), client);
            ExpectCode("UPDATE_REDIRECT_BLOCKED", () => downloader.DownloadAndStageAsync(update).GetAwaiter().GetResult(), "non-GitHub source redirect remains blocked");
        }
        finally { Delete(root); }
    }

    private static void LookalikeGitHubHostIsBlocked(byte[] package, UpdateBroker.VerifiedUpdate update)
    {
        var root = TempRoot();
        try
        {
            using var client = Client(_ => Response(package, HttpStatusCode.Found, package.Length, "https://evilgithubusercontent.com/a.zip"));
            using var downloader = new UpdateDownloadClient(new UpdateStagingBroker(root), client);
            ExpectCode("UPDATE_REDIRECT_TARGET_DENIED", () => downloader.DownloadAndStageAsync(update).GetAwaiter().GetResult(), "lookalike githubusercontent host rejected");
        }
        finally { Delete(root); }
    }

    private static void HttpRedirectTargetIsBlocked(byte[] package, UpdateBroker.VerifiedUpdate update)
    {
        var root = TempRoot();
        try
        {
            using var client = Client(_ => Response(package, HttpStatusCode.Found, package.Length, "http://release-assets.githubusercontent.com/a.zip"));
            using var downloader = new UpdateDownloadClient(new UpdateStagingBroker(root), client);
            ExpectCode("UPDATE_REDIRECT_TARGET_DENIED", () => downloader.DownloadAndStageAsync(update).GetAwaiter().GetResult(), "HTTP GitHub redirect target rejected");
        }
        finally { Delete(root); }
    }

    private static void SecondRedirectIsBlocked(byte[] package, UpdateBroker.VerifiedUpdate update)
    {
        var root = TempRoot();
        try
        {
            var count = 0;
            using var client = Client(_ =>
            {
                count++;
                return Response(Array.Empty<byte>(), HttpStatusCode.Found, 0,
                    count == 1 ? "https://release-assets.githubusercontent.com/one.zip" : "https://objects.githubusercontent.com/two.zip");
            });
            using var downloader = new UpdateDownloadClient(new UpdateStagingBroker(root), client);
            ExpectCode("UPDATE_REDIRECT_LIMIT_EXCEEDED", () => downloader.DownloadAndStageAsync(update).GetAwaiter().GetResult(), "second redirect rejected");
        }
        finally { Delete(root); }
    }

    private static void SignedGitHubSourceMustBeImmutable(byte[] package, UpdateBroker.VerifiedUpdate update)
    {
        var root = TempRoot();
        try
        {
            var requests = 0;
            using var client = Client(_ => { requests++; return Response(package, HttpStatusCode.OK, package.Length); });
            using var downloader = new UpdateDownloadClient(new UpdateStagingBroker(root), client);

            ExpectCode("UPDATE_URL_INVALID", () => downloader.DownloadAndStageAsync(update with
            {
                PackageUri = new Uri("https://github.com/Swir/SWIR_OS/releases/latest/download/SWIR-Desktop-preview.zip")
            }).GetAwaiter().GetResult(), "mutable latest GitHub release URL rejected before network access");

            ExpectCode("UPDATE_URL_INVALID", () => downloader.DownloadAndStageAsync(update with
            {
                PackageUri = new Uri("https://github.com/Swir/SWIR_OS/releases/download/desktop-v0.5.8-preview/SWIR-Desktop-0.5.8-preview.zip?download=1")
            }).GetAwaiter().GetResult(), "query-bearing signed GitHub release URL rejected before network access");

            ExpectCode("UPDATE_URL_INVALID", () => downloader.DownloadAndStageAsync(update with
            {
                PackageUri = new Uri("https://github.com/Other/SWIR_OS/releases/download/desktop-v0.5.8-preview/SWIR-Desktop-0.5.8-preview.zip")
            }).GetAwaiter().GetResult(), "other-owner signed GitHub release URL rejected before network access");

            Expect(requests == 0, "invalid signed GitHub source URLs make zero HTTP requests");
        }
        finally { Delete(root); }
    }

    private static void OfficialReleasePathValidation()
    {
        Expect(UpdateDownloadClient.IsOfficialSwirGitHubReleaseUri(new Uri("https://github.com/Swir/SWIR_OS/releases/download/desktop-v0.5.8-preview/SWIR-Desktop-0.5.8-preview.zip")), "official immutable SWIR_OS release URL accepted");
        Expect(!UpdateDownloadClient.IsOfficialSwirGitHubReleaseUri(new Uri("https://github.com/Other/SWIR_OS/releases/download/v1/a.zip")), "other owner release URL rejected");
        Expect(!UpdateDownloadClient.IsOfficialSwirGitHubReleaseUri(new Uri("https://github.com/Swir/SWIR_OS/releases/latest/download/a.zip")), "mutable latest release URL rejected");
        Expect(!UpdateDownloadClient.IsOfficialSwirGitHubReleaseUri(new Uri("https://github.com/Swir/SWIR_OS/releases/download/v1/a.zip?x=1")), "signed source URL with query rejected");
    }

    private static HttpClient Client(Func<HttpRequestMessage, HttpResponseMessage> factory) => new(new StaticHandler(factory)) { Timeout = Timeout.InfiniteTimeSpan };
    private static HttpResponseMessage Response(byte[] body, HttpStatusCode status, long? contentLength, string? location = null)
    {
        var response = new HttpResponseMessage(status) { Content = new ByteArrayContent(body) };
        if (contentLength.HasValue) response.Content.Headers.ContentLength = contentLength.Value;
        if (location is not null) response.Headers.Location = new Uri(location);
        return response;
    }
    private static string TempRoot() => Path.Combine(Path.GetTempPath(), "swir-github-update-" + Guid.NewGuid().ToString("N"));
    private static void Delete(string root) { try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { } }
    private static void ExpectCode(string code, Action action, string name)
    {
        try { action(); }
        catch (UpdateSecurityException ex) when (ex.Code == code) { Expect(true, name); return; }
        throw new InvalidOperationException($"Expected {code}: {name}");
    }
    private static void Expect(bool condition, string name)
    {
        if (!condition) throw new InvalidOperationException(name);
        _passed++; Console.WriteLine("PASS " + name);
    }
    private sealed class StaticHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _factory;
        public StaticHandler(Func<HttpRequestMessage, HttpResponseMessage> factory) => _factory = factory;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(_factory(request));
    }
}
