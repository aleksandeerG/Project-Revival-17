// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Security.Cryptography;
using System.Text;

namespace Revival.Launcher.Core;

public sealed class LauncherPaths
{
    public const string FolderName = "FIFA17Revival";

    public LauncherPaths(string root)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(root);
        Root = root;
    }

    public static LauncherPaths Default { get; } = new(Path.Combine(
        Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData,
            Environment.SpecialFolderOption.DoNotVerify),
        FolderName));

    public string Root { get; }

    public string InstallationManifest => Path.Combine(Root, "installation.json");

    public string Backups => Path.Combine(Root, "backups");

    public string SelectedGame => Path.Combine(Root, "selected-game.txt");

    public string HighestReleaseSerial => Path.Combine(Root, "highest-release-serial.txt");

    public string Installations => Path.Combine(Root, "installations");

    public string InstallationRootFor(string gameRoot) =>
        Path.Combine(Installations, InstallationKey(gameRoot));

    public string InstallationManifestFor(string gameRoot) =>
        Path.Combine(InstallationRootFor(gameRoot), "installation.json");

    public string BackupsFor(string gameRoot) =>
        Path.Combine(InstallationRootFor(gameRoot), "backups");

    public string BackupFor(string gameRoot, string originalFileName, DateTimeOffset when) =>
        Path.Combine(
            BackupsFor(gameRoot),
            $"{when.UtcDateTime:yyyyMMdd-HHmmss-fffffff}-{Guid.NewGuid():N}-{Path.GetFileName(originalFileName)}.dpapi");

    public static string NormaliseGameRoot(string gameRoot) =>
        Path.TrimEndingDirectorySeparator(Path.GetFullPath(gameRoot));

    private static string InstallationKey(string gameRoot)
    {
        string normalised = NormaliseGameRoot(gameRoot).ToUpperInvariant();
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(normalised)))[..24];
    }
}
