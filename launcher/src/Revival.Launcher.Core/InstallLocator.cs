// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public enum GameCandidateSource
{
    UninstallRegistry,
    ManualSelection,
}

public sealed record GameCandidate(
    string ExecutablePath,
    string GameRoot,
    string? DisplayName,
    string? DisplayVersion,
    GameCandidateSource Source,
    string? RegistrySource = null);

public static class InstallLocator
{
    private const string DisplayNamePrefix = "FIFA 17";

    private const string ExpectedPublisher = "Electronic Arts";

    public static IReadOnlyList<GameCandidate> Locate(
        IUninstallRegistry registry, IFileSystem fileSystem)
    {
        ArgumentNullException.ThrowIfNull(registry);
        ArgumentNullException.ThrowIfNull(fileSystem);

        List<GameCandidate> found = [];
        HashSet<string> seen = new(StringComparer.OrdinalIgnoreCase);

        foreach (UninstallEntry entry in registry.Enumerate())
        {
            if (!Matches(entry))
            {
                continue;
            }

            string? executable = ResolveExecutable(entry, fileSystem);
            if (executable is null)
            {
                continue;
            }

            if (!seen.Add(executable))
            {
                continue;
            }

            found.Add(new GameCandidate(
                ExecutablePath: executable,
                GameRoot: Path.GetDirectoryName(executable)!,
                DisplayName: entry.DisplayName,
                DisplayVersion: entry.DisplayVersion,
                Source: GameCandidateSource.UninstallRegistry,
                RegistrySource: entry.Source));
        }

        return found;
    }

    public static GameCandidate? FromExecutable(string executablePath, IFileSystem fileSystem)
    {
        ArgumentNullException.ThrowIfNull(fileSystem);
        if (string.IsNullOrWhiteSpace(executablePath))
        {
            return null;
        }

        string? full = TryGetFullPath(executablePath);
        if (full is null || !IsGameExecutable(full) || !fileSystem.FileExists(full))
        {
            return null;
        }

        string? directory = Path.GetDirectoryName(full);
        if (string.IsNullOrEmpty(directory))
        {
            return null;
        }

        return new GameCandidate(
            ExecutablePath: full,
            GameRoot: directory,
            DisplayName: null,
            DisplayVersion: null,
            Source: GameCandidateSource.ManualSelection);
    }

    private static bool Matches(UninstallEntry entry) =>
        entry.DisplayName is not null &&
        entry.DisplayName.StartsWith(DisplayNamePrefix, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(entry.Publisher, ExpectedPublisher, StringComparison.OrdinalIgnoreCase);

    private static string? ResolveExecutable(UninstallEntry entry, IFileSystem fileSystem)
    {
        string? fromIcon = ParseDisplayIcon(entry.DisplayIcon);
        if (fromIcon is not null &&
            IsGameExecutable(fromIcon) &&
            fileSystem.FileExists(fromIcon))
        {
            return fromIcon;
        }

        if (string.IsNullOrWhiteSpace(entry.InstallLocation))
        {
            return null;
        }

        string root = entry.InstallLocation.Trim().TrimEnd('\\', '/');
        string? candidate = TryGetFullPath(Path.Combine(root, BuildCheck.GameExecutableName));

        return candidate is not null && fileSystem.FileExists(candidate) ? candidate : null;
    }

    private static bool IsGameExecutable(string path) =>
        string.Equals(
            Path.GetFileName(path), BuildCheck.GameExecutableName, StringComparison.OrdinalIgnoreCase);

    internal static string? ParseDisplayIcon(string? displayIcon)
    {
        if (string.IsNullOrWhiteSpace(displayIcon))
        {
            return null;
        }

        string value = displayIcon.Trim();

        if (value.StartsWith('"'))
        {
            int closing = value.IndexOf('"', 1);
            if (closing <= 1)
            {
                return null;
            }

            return TryGetFullPath(value[1..closing]);
        }

        int lastComma = value.LastIndexOf(',');
        if (lastComma > 0)
        {
            string suffix = value[(lastComma + 1)..];
            bool isIconIndex =
                suffix.Length > 0 &&
                (suffix[0] == '-' ? suffix.Length > 1 && suffix[1..].All(char.IsAsciiDigit)
                                  : suffix.All(char.IsAsciiDigit));

            if (isIconIndex)
            {
                value = value[..lastComma];
            }
        }

        return TryGetFullPath(value.Trim());
    }

    private static string? TryGetFullPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception exception)
            when (exception is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return null;
        }
    }
}
