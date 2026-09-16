using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopInstalledBuildIdentitySelfTests
{
    public static int Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "swir-build-identity-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            Require(DesktopInstalledBuildIdentity.ResolveCurrentVersion(root) == new Version(0, 5, 7), "development fallback tracks current 0.5.7 line");
            File.WriteAllText(Path.Combine(root, "desktop-host-build.json"), JsonSerializer.Serialize(new { schema = DesktopInstalledBuildIdentity.BuildSchema, releaseVersion = "0.6.3" }));
            Require(DesktopInstalledBuildIdentity.ResolveCurrentVersion(root) == new Version(0, 6, 3), "packaged release version overrides development fallback");
            File.WriteAllText(Path.Combine(root, "desktop-host-build.json"), "{\"schema\":\"wrong\",\"releaseVersion\":\"9.9.9\"}");
            ExpectCode("UPDATE_BUILD_IDENTITY_INVALID", () => DesktopInstalledBuildIdentity.ResolveCurrentVersion(root));
            Console.WriteLine("Desktop installed build identity self-tests passed.");
            return 0;
        }
        finally { try { Directory.Delete(root, true); } catch { } }
    }
    private static void Require(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); Console.WriteLine("PASS " + message); }
    private static void ExpectCode(string code, Action action)
    {
        try { action(); }
        catch (UpdateSecurityException ex) when (ex.Code == code) { Console.WriteLine("PASS invalid build identity fails closed"); return; }
        throw new InvalidOperationException($"Expected {code}.");
    }
}
