using System.Diagnostics;
using System.Text.Json;

namespace Swir.Desktop.Host;

internal static class DesktopKonofixReleaseSmoke
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 2) throw new ArgumentException("Expected installed Konofix executable and approved install root.");
            var executable = Path.GetFullPath(args[0]);
            var root = Path.GetFullPath(args[1]);
            if (!File.Exists(executable)) throw new FileNotFoundException("Installed Konofix executable is missing.", executable);

            ProcessStartInfo? captured = null;
            var launcher = new DesktopKonofixLauncher(
                resolver: () => executable,
                versionVerifier: null,
                starter: info => { captured = info; return 4242; },
                approvedRoots: new[] { root });

            var json = JsonSerializer.Serialize(launcher.Describe(), new JsonSerializerOptions(JsonSerializerDefaults.Web));
            using var doc = JsonDocument.Parse(json);
            var status = doc.RootElement;
            Require(status.GetProperty("installed").GetBoolean(), "published Konofix executable did not pass the production version/path verifier");
            Require(status.GetProperty("expectedVersion").GetString() == DesktopKonofixLauncher.ExpectedVersion, "expected Konofix version drifted");
            Require(status.GetProperty("provider").GetString() == "windows-installed-client", "unexpected Konofix provider");
            Require(!status.GetProperty("automaticExecution").GetBoolean(), "published client must remain explicit-launch only");
            Require(!status.GetProperty("legacyDataImport").GetBoolean(), "published client must not import legacy SWIR Chat data");

            var launched = launcher.Launch();
            Require(launched.Started && launched.ProcessId == 4242, "release launcher did not accept the published client");
            Require(captured is not null, "release launcher did not build a process start request");
            Require(string.Equals(captured!.FileName, executable, StringComparison.OrdinalIgnoreCase), "release launcher changed the installed executable path");
            Require(captured.UseShellExecute == false, "release launcher must not use shell execution");
            Require(string.IsNullOrEmpty(captured.Arguments), "release launcher must not add hidden arguments");
            Require(string.Equals(captured.WorkingDirectory, Path.GetDirectoryName(executable), StringComparison.OrdinalIgnoreCase), "release launcher working directory drifted");

            var version = FileVersionInfo.GetVersionInfo(executable);
            Console.WriteLine($"Published Konofix accepted: product={version.ProductVersion} file={version.FileVersion}");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
