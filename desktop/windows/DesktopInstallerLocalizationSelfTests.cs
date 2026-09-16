using Swir.Desktop.Host;

static class Program
{
    private static int Main()
    {
        var expected = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["en-US"] = "en",
            ["pl-PL"] = "pl",
            ["no-NO"] = "nb",
            ["nb-NO"] = "nb",
            ["de-DE"] = "de",
            ["es-MX"] = "es",
            ["fr-FR"] = "fr",
            ["it-IT"] = "it",
            ["pt-PT"] = "pt-BR",
            ["uk-UA"] = "uk",
            ["ru-RU"] = "ru",
            ["tr-TR"] = "tr",
            ["ar-SA"] = "ar",
            ["he-IL"] = "he",
            ["ja-JP"] = "ja",
            ["zh-CN"] = "zh-Hans",
            ["zh-SG"] = "zh-Hans",
            ["is-IS"] = "en",
            ["not_a_locale"] = "en"
        };

        foreach (var pair in expected)
        {
            var actual = DesktopInstallerLocalization.MatchLocale(pair.Key);
            if (!string.Equals(actual, pair.Value, StringComparison.Ordinal))
                throw new InvalidOperationException($"Locale mapping failed: {pair.Key} -> {actual}, expected {pair.Value}.");
        }

        foreach (var locale in expected.Values.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            foreach (var key in new[] { "Title", "InstallReady", "RepairReady", "UninstallReady", "UninstallRestored", "RollbackReady", "ErrorIntro" })
            {
                var text = DesktopInstallerLocalization.GetTextForLocale(locale, key, "0.5.7", "preview");
                if (string.IsNullOrWhiteSpace(text))
                    throw new InvalidOperationException($"Locale {locale} has an empty {key} string.");
            }
        }

        Console.WriteLine("Desktop installer localization self-tests passed.");
        return 0;
    }
}
