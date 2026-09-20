using System.Text.Json;
using Swir.Desktop.Host;

static class DesktopUpdateUserPolicySelfTests
{
    private static int failures;

    public static int Main()
    {
        Run("missing file defaults to notify", MissingFileDefaultsToNotify);
        Run("all modes round trip", AllModesRoundTrip);
        Run("corrupt json fails safe", CorruptJsonFailsSafe);
        Run("unknown schema fails safe", UnknownSchemaFailsSafe);
        Run("unknown mode fails safe", UnknownModeFailsSafe);
        Run("extra properties fail safe", ExtraPropertiesFailSafe);
        Run("policy semantics match UI contract", PolicySemanticsMatchUiContract);
        Run("atomic save leaves no temp file", AtomicSaveLeavesNoTempFile);
        Run("explicit path requires canonical filename", ExplicitPathRequiresCanonicalFilename);

        if (failures == 0)
        {
            Console.WriteLine("Desktop native update user policy self-tests passed.");
            return 0;
        }

        Console.Error.WriteLine($"Desktop native update user policy self-tests failed: {failures}");
        return 1;
    }

    private static void MissingFileDefaultsToNotify()
    {
        using var fixture = new Fixture();
        Equal(DesktopUpdateUserMode.NotifyOnly, fixture.Store.Load());
    }

    private static void AllModesRoundTrip()
    {
        using var fixture = new Fixture();
        foreach (var mode in new[] { DesktopUpdateUserMode.Manual, DesktopUpdateUserMode.NotifyOnly, DesktopUpdateUserMode.Automatic })
        {
            fixture.Store.Save(mode);
            Equal(mode, fixture.Store.Load());

            using var json = JsonDocument.Parse(File.ReadAllText(fixture.Path));
            Equal(2, json.RootElement.EnumerateObject().Count());
            Equal(DesktopUpdateUserPolicyStore.SchemaVersion, json.RootElement.GetProperty("schemaVersion").GetInt32());
            Equal(DesktopUpdateUserPolicyStore.ToPersistedMode(mode), json.RootElement.GetProperty("mode").GetString());
        }
    }

    private static void CorruptJsonFailsSafe()
    {
        using var fixture = new Fixture();
        File.WriteAllText(fixture.Path, "{ definitely-not-json");
        Equal(DesktopUpdateUserMode.NotifyOnly, fixture.Store.Load());
    }

    private static void UnknownSchemaFailsSafe()
    {
        using var fixture = new Fixture();
        File.WriteAllText(fixture.Path, "{\"schemaVersion\":2,\"mode\":\"automatic\"}");
        Equal(DesktopUpdateUserMode.NotifyOnly, fixture.Store.Load());
    }

    private static void UnknownModeFailsSafe()
    {
        using var fixture = new Fixture();
        File.WriteAllText(fixture.Path, "{\"schemaVersion\":1,\"mode\":\"install-everything\"}");
        Equal(DesktopUpdateUserMode.NotifyOnly, fixture.Store.Load());
    }

    private static void ExtraPropertiesFailSafe()
    {
        using var fixture = new Fixture();
        File.WriteAllText(fixture.Path, "{\"schemaVersion\":1,\"mode\":\"automatic\",\"disableTrust\":true}");
        Equal(DesktopUpdateUserMode.NotifyOnly, fixture.Store.Load());
    }

    private static void PolicySemanticsMatchUiContract()
    {
        var manual = DesktopUpdateUserPolicyStore.Evaluate(DesktopUpdateUserMode.Manual);
        False(manual.BackgroundCheck);
        False(manual.AutomaticPrepare);
        False(manual.AutomaticRestart);
        True(manual.UserInitiatedCheck && manual.UserInitiatedPrepare && manual.UserInitiatedRestart);

        var notify = DesktopUpdateUserPolicyStore.Evaluate(DesktopUpdateUserMode.NotifyOnly);
        True(notify.BackgroundCheck);
        False(notify.AutomaticPrepare);
        False(notify.AutomaticRestart);
        True(notify.UserInitiatedCheck && notify.UserInitiatedPrepare && notify.UserInitiatedRestart);

        var automatic = DesktopUpdateUserPolicyStore.Evaluate(DesktopUpdateUserMode.Automatic);
        True(automatic.BackgroundCheck);
        True(automatic.AutomaticPrepare);
        False(automatic.AutomaticRestart);
        True(automatic.UserInitiatedCheck && automatic.UserInitiatedPrepare && automatic.UserInitiatedRestart);
    }

    private static void AtomicSaveLeavesNoTempFile()
    {
        using var fixture = new Fixture();
        fixture.Store.Save(DesktopUpdateUserMode.Automatic);
        fixture.Store.Save(DesktopUpdateUserMode.Manual);
        Equal(DesktopUpdateUserMode.Manual, fixture.Store.Load());
        var leftovers = Directory.GetFiles(fixture.Directory, $".{DesktopUpdateUserPolicyStore.DefaultFileName}.*.tmp");
        Equal(0, leftovers.Length);
    }

    private static void ExplicitPathRequiresCanonicalFilename()
    {
        using var fixture = new Fixture(createStore: false);
        Throws<ArgumentException>(() => _ = new DesktopUpdateUserPolicyStore(Path.Combine(fixture.Directory, "other.json")));
    }

    private static void Run(string name, Action test)
    {
        try
        {
            test();
            Console.WriteLine($"PASS: {name}");
        }
        catch (Exception ex)
        {
            failures++;
            Console.Error.WriteLine($"FAIL: {name}: {ex.Message}");
        }
    }

    private static void True(bool value)
    {
        if (!value) throw new InvalidOperationException("Expected true.");
    }

    private static void False(bool value)
    {
        if (value) throw new InvalidOperationException("Expected false.");
    }

    private static void Equal<T>(T expected, T actual)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new InvalidOperationException($"Expected '{expected}', got '{actual}'.");
    }

    private static void Throws<TException>(Action action) where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }

        throw new InvalidOperationException($"Expected {typeof(TException).Name}.");
    }

    private sealed class Fixture : IDisposable
    {
        internal string Directory { get; }
        internal string Path { get; }
        internal DesktopUpdateUserPolicyStore Store { get; }

        internal Fixture(bool createStore = true)
        {
            Directory = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "swir-update-policy-tests", Guid.NewGuid().ToString("N"));
            System.IO.Directory.CreateDirectory(Directory);
            Path = System.IO.Path.Combine(Directory, DesktopUpdateUserPolicyStore.DefaultFileName);
            Store = createStore ? new DesktopUpdateUserPolicyStore(Path) : null!;
        }

        public void Dispose()
        {
            try { System.IO.Directory.Delete(Directory, recursive: true); } catch { }
        }
    }
}
