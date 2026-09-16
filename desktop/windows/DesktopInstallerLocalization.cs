using System.Globalization;

namespace Swir.Desktop.Host;

internal static class DesktopInstallerLocalization
{
    private static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, string>> Text =
        new Dictionary<string, IReadOnlyDictionary<string, string>>(StringComparer.OrdinalIgnoreCase)
        {
            ["en"] = Pack("SWIR OS Setup", "SWIR OS Desktop {0} ({1}) is ready.", "SWIR OS Desktop {0} ({1}) was repaired successfully.", "SWIR OS Desktop was uninstalled.", "SWIR OS Desktop was uninstalled. Previous version {0} ({1}) is active again.", "SWIR OS Desktop rolled back to {0} ({1}).", "Setup could not complete:"),
            ["pl"] = Pack("Instalator SWIR OS", "SWIR OS Desktop {0} ({1}) jest gotowy.", "SWIR OS Desktop {0} ({1}) został pomyślnie naprawiony.", "SWIR OS Desktop został odinstalowany.", "SWIR OS Desktop został odinstalowany. Poprzednia wersja {0} ({1}) jest ponownie aktywna.", "SWIR OS Desktop został cofnięty do wersji {0} ({1}).", "Nie udało się zakończyć operacji instalatora:"),
            ["nb"] = Pack("SWIR OS-oppsett", "SWIR OS Desktop {0} ({1}) er klar.", "SWIR OS Desktop {0} ({1}) ble reparert.", "SWIR OS Desktop ble avinstallert.", "SWIR OS Desktop ble avinstallert. Forrige versjon {0} ({1}) er aktiv igjen.", "SWIR OS Desktop ble rullet tilbake til {0} ({1}).", "Oppsettet kunne ikke fullføres:"),
            ["de"] = Pack("SWIR OS Setup", "SWIR OS Desktop {0} ({1}) ist bereit.", "SWIR OS Desktop {0} ({1}) wurde erfolgreich repariert.", "SWIR OS Desktop wurde deinstalliert.", "SWIR OS Desktop wurde deinstalliert. Die vorherige Version {0} ({1}) ist wieder aktiv.", "SWIR OS Desktop wurde auf {0} ({1}) zurückgesetzt.", "Setup konnte nicht abgeschlossen werden:"),
            ["es"] = Pack("Instalación de SWIR OS", "SWIR OS Desktop {0} ({1}) está listo.", "SWIR OS Desktop {0} ({1}) se reparó correctamente.", "SWIR OS Desktop se desinstaló.", "SWIR OS Desktop se desinstaló. La versión anterior {0} ({1}) vuelve a estar activa.", "SWIR OS Desktop volvió a {0} ({1}).", "La instalación no pudo completarse:"),
            ["fr"] = Pack("Installation de SWIR OS", "SWIR OS Desktop {0} ({1}) est prêt.", "SWIR OS Desktop {0} ({1}) a été réparé avec succès.", "SWIR OS Desktop a été désinstallé.", "SWIR OS Desktop a été désinstallé. La version précédente {0} ({1}) est de nouveau active.", "SWIR OS Desktop a été restauré vers {0} ({1}).", "L’installation n’a pas pu se terminer :"),
            ["it"] = Pack("Installazione SWIR OS", "SWIR OS Desktop {0} ({1}) è pronto.", "SWIR OS Desktop {0} ({1}) è stato riparato correttamente.", "SWIR OS Desktop è stato disinstallato.", "SWIR OS Desktop è stato disinstallato. La versione precedente {0} ({1}) è di nuovo attiva.", "SWIR OS Desktop è tornato a {0} ({1}).", "Impossibile completare l'installazione:"),
            ["pt-BR"] = Pack("Instalação do SWIR OS", "SWIR OS Desktop {0} ({1}) está pronto.", "SWIR OS Desktop {0} ({1}) foi reparado com sucesso.", "SWIR OS Desktop foi desinstalado.", "SWIR OS Desktop foi desinstalado. A versão anterior {0} ({1}) está ativa novamente.", "SWIR OS Desktop voltou para {0} ({1}).", "Não foi possível concluir a instalação:"),
            ["uk"] = Pack("Встановлення SWIR OS", "SWIR OS Desktop {0} ({1}) готовий.", "SWIR OS Desktop {0} ({1}) успішно відновлено.", "SWIR OS Desktop видалено.", "SWIR OS Desktop видалено. Попередня версія {0} ({1}) знову активна.", "SWIR OS Desktop повернуто до {0} ({1}).", "Не вдалося завершити встановлення:"),
            ["ru"] = Pack("Установка SWIR OS", "SWIR OS Desktop {0} ({1}) готов.", "SWIR OS Desktop {0} ({1}) успешно восстановлен.", "SWIR OS Desktop удалён.", "SWIR OS Desktop удалён. Предыдущая версия {0} ({1}) снова активна.", "SWIR OS Desktop возвращён к {0} ({1}).", "Не удалось завершить установку:"),
            ["tr"] = Pack("SWIR OS Kurulumu", "SWIR OS Desktop {0} ({1}) hazır.", "SWIR OS Desktop {0} ({1}) başarıyla onarıldı.", "SWIR OS Desktop kaldırıldı.", "SWIR OS Desktop kaldırıldı. Önceki sürüm {0} ({1}) yeniden etkin.", "SWIR OS Desktop {0} ({1}) sürümüne geri alındı.", "Kurulum tamamlanamadı:"),
            ["ar"] = Pack("إعداد SWIR OS", "SWIR OS Desktop {0} ({1}) جاهز.", "تم إصلاح SWIR OS Desktop {0} ({1}) بنجاح.", "تمت إزالة SWIR OS Desktop.", "تمت إزالة SWIR OS Desktop. الإصدار السابق {0} ({1}) نشط مرة أخرى.", "تمت استعادة SWIR OS Desktop إلى {0} ({1}).", "تعذر إكمال الإعداد:"),
            ["he"] = Pack("התקנת SWIR OS", "SWIR OS Desktop {0} ({1}) מוכן.", "SWIR OS Desktop {0} ({1}) תוקן בהצלחה.", "SWIR OS Desktop הוסר.", "SWIR OS Desktop הוסר. הגרסה הקודמת {0} ({1}) פעילה שוב.", "SWIR OS Desktop הוחזר לגרסה {0} ({1}).", "לא ניתן להשלים את ההתקנה:"),
            ["ja"] = Pack("SWIR OS セットアップ", "SWIR OS Desktop {0} ({1}) の準備ができました。", "SWIR OS Desktop {0} ({1}) を正常に修復しました。", "SWIR OS Desktop をアンインストールしました。", "SWIR OS Desktop をアンインストールしました。以前のバージョン {0} ({1}) が再び有効です。", "SWIR OS Desktop を {0} ({1}) にロールバックしました。", "セットアップを完了できませんでした:"),
            ["zh-Hans"] = Pack("SWIR OS 安装程序", "SWIR OS Desktop {0} ({1}) 已准备就绪。", "SWIR OS Desktop {0} ({1}) 已成功修复。", "SWIR OS Desktop 已卸载。", "SWIR OS Desktop 已卸载。先前版本 {0} ({1}) 已重新启用。", "SWIR OS Desktop 已回滚到 {0} ({1})。", "安装程序无法完成操作：")
        };

    private static string _locale = "en";

    public static string Locale => _locale;

    public static void Configure(string? requestedLanguage)
    {
        var source = string.IsNullOrWhiteSpace(requestedLanguage)
            ? CultureInfo.CurrentUICulture.Name
            : requestedLanguage!;
        _locale = MatchLocale(source);
    }

    public static string MatchLocale(string? languageTag)
    {
        if (string.IsNullOrWhiteSpace(languageTag)) return "en";
        try
        {
            var culture = CultureInfo.GetCultureInfo(languageTag.Replace('_', '-'));
            var name = culture.Name;
            var language = culture.TwoLetterISOLanguageName;
            return language switch
            {
                "pl" => "pl",
                "nb" or "nn" or "no" => "nb",
                "de" => "de",
                "es" => "es",
                "fr" => "fr",
                "it" => "it",
                "pt" => "pt-BR",
                "uk" => "uk",
                "ru" => "ru",
                "tr" => "tr",
                "ar" => "ar",
                "he" => "he",
                "ja" => "ja",
                "zh" => "zh-Hans",
                "en" => "en",
                _ => Text.ContainsKey(name) ? name : "en"
            };
        }
        catch (CultureNotFoundException)
        {
            return "en";
        }
    }

    public static string T(string key, params object[] args) => GetTextForLocale(_locale, key, args);

    public static string GetTextForLocale(string locale, string key, params object[] args)
    {
        var selected = Text.TryGetValue(locale, out var pack) ? pack : Text["en"];
        if (!selected.TryGetValue(key, out var value) && !Text["en"].TryGetValue(key, out value))
            throw new KeyNotFoundException($"Unknown installer localization key: {key}");
        return args.Length == 0 ? value : string.Format(CultureInfo.CurrentCulture, value, args);
    }

    private static IReadOnlyDictionary<string, string> Pack(
        string title,
        string installReady,
        string repairReady,
        string uninstallReady,
        string uninstallRestored,
        string rollbackReady,
        string errorIntro) => new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Title"] = title,
            ["InstallReady"] = installReady,
            ["RepairReady"] = repairReady,
            ["UninstallReady"] = uninstallReady,
            ["UninstallRestored"] = uninstallRestored,
            ["RollbackReady"] = rollbackReady,
            ["ErrorIntro"] = errorIntro
        };
}
