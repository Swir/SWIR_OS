using System.Diagnostics;
using System.Windows.Forms;

namespace Swir.Desktop.Host;

internal static class DesktopInstallerProgram
{
    [STAThread]
    public static int Main(string[] args)
    {
        var quiet = args.Contains("--quiet", StringComparer.OrdinalIgnoreCase);
        DesktopInstallerLocalization.Configure(ExtractLanguageHint(args));
        try
        {
            var options = ParseOptions(args);
            DesktopInstallerLocalization.Configure(options.Language);
            var installRoot = options.InstallRoot ?? DesktopInstallerLifecycle.DefaultInstallRoot();

            if (options.Uninstall)
            {
                var restored = DesktopInstallerLifecycle.Uninstall(installRoot);
                if (!quiet)
                {
                    var message = restored is null
                        ? DesktopInstallerLocalization.T("UninstallReady")
                        : DesktopInstallerLocalization.T("UninstallRestored", restored.Version, restored.Channel);
                    ShowInfo(message);
                }
                return 0;
            }

            if (options.Rollback)
            {
                var rolledBack = DesktopInstallerLifecycle.Rollback(installRoot);
                if (!quiet)
                    ShowInfo(DesktopInstallerLocalization.T("RollbackReady", rolledBack.Version, rolledBack.Channel));
                return 0;
            }

            var metadata = DesktopInstallerPackage.ReadEmbeddedMetadata();
            var packagePath = DesktopInstallerPackage.MaterializeAndVerifyPayload(metadata.PackageSha256);
            try
            {
                if (options.VerifyOnly)
                {
                    DesktopInstallerPackage.VerifyPayloadStructure(packagePath, metadata);
                    return 0;
                }

                var installed = DesktopInstallerLifecycle.Install(packagePath, metadata, installRoot, options.Repair);
                if (!options.NoLaunch)
                    Launch(installed, metadata.EntryPoint);
                if (!quiet)
                {
                    var key = options.Repair ? "RepairReady" : "InstallReady";
                    ShowInfo(DesktopInstallerLocalization.T(key, metadata.Version, metadata.Channel));
                }
                return 0;
            }
            finally
            {
                try { File.Delete(packagePath); } catch { }
            }
        }
        catch (Exception ex)
        {
            if (!quiet)
                MessageBox.Show(
                    DesktopInstallerLocalization.T("ErrorIntro") + Environment.NewLine + Environment.NewLine + ex.Message,
                    DesktopInstallerLocalization.T("Title"),
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            return 2;
        }
    }

    private static DesktopInstallerOptions ParseOptions(string[] args)
    {
        var verify = false;
        var noLaunch = false;
        var uninstall = false;
        var rollback = false;
        var repair = false;
        string? installRoot = null;
        string? language = null;
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            if (arg.Equals("--quiet", StringComparison.OrdinalIgnoreCase)) continue;
            if (arg.Equals("--verify-only", StringComparison.OrdinalIgnoreCase)) { verify = true; continue; }
            if (arg.Equals("--no-launch", StringComparison.OrdinalIgnoreCase)) { noLaunch = true; continue; }
            if (arg.Equals("--uninstall", StringComparison.OrdinalIgnoreCase)) { uninstall = true; continue; }
            if (arg.Equals("--rollback", StringComparison.OrdinalIgnoreCase)) { rollback = true; continue; }
            if (arg.Equals("--repair", StringComparison.OrdinalIgnoreCase)) { repair = true; continue; }
            if (arg.Equals("--lang", StringComparison.OrdinalIgnoreCase))
            {
                if (++i >= args.Length || string.IsNullOrWhiteSpace(args[i]) || args[i].StartsWith("--", StringComparison.Ordinal))
                    throw new InvalidOperationException("--lang requires a BCP-47 language tag.");
                language = args[i];
                continue;
            }
            if (arg.Equals("--install-root", StringComparison.OrdinalIgnoreCase))
            {
                if (++i >= args.Length || string.IsNullOrWhiteSpace(args[i])) throw new InvalidOperationException("--install-root requires a directory.");
                installRoot = Path.GetFullPath(args[i]);
                continue;
            }
            throw new InvalidOperationException($"Unsupported setup argument: {arg}");
        }

        var exclusiveActions = (verify ? 1 : 0) + (uninstall ? 1 : 0) + (rollback ? 1 : 0) + (repair ? 1 : 0);
        if (exclusiveActions > 1)
            throw new InvalidOperationException("--verify-only, --uninstall, --rollback and --repair are mutually exclusive.");
        if ((uninstall || rollback) && noLaunch)
            throw new InvalidOperationException("--no-launch is valid only for install/repair operations.");

        return new DesktopInstallerOptions(verify, noLaunch, uninstall, rollback, repair, installRoot, language);
    }

    private static string? ExtractLanguageHint(string[] args)
    {
        for (var i = 0; i + 1 < args.Length; i++)
        {
            if (args[i].Equals("--lang", StringComparison.OrdinalIgnoreCase) && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                return args[i + 1];
        }
        return null;
    }

    private static void Launch(string installationDirectory, string entryPoint)
    {
        var executable = DesktopInstallerPackage.ResolveInside(installationDirectory, entryPoint);
        _ = Process.Start(new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = installationDirectory,
            UseShellExecute = false
        }) ?? throw new InvalidOperationException("SWIR Desktop Host could not be started after installation.");
    }

    private static void ShowInfo(string message) => MessageBox.Show(
        message,
        DesktopInstallerLocalization.T("Title"),
        MessageBoxButtons.OK,
        MessageBoxIcon.Information);
}
