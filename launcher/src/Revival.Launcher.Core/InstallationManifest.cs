// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Revival.Launcher.Core;

public enum PriorState
{
    Absent,

    Replaced,
}

public sealed record InstalledFile(
    string Role,
    string Path,
    string InstalledSha256,
    PriorState PriorState,
    string? BackupPath = null,
    string? PriorSha256 = null,
    bool BackupProtected = false)
{
    public bool IsCoherent =>
        !string.IsNullOrWhiteSpace(Role) &&
        !string.IsNullOrWhiteSpace(Path) &&
        IsHash(InstalledSha256) &&
        (PriorState switch
        {
            PriorState.Absent => BackupPath is null && PriorSha256 is null,
            PriorState.Replaced => !string.IsNullOrWhiteSpace(BackupPath)
                                   && IsHash(PriorSha256),
            _ => false,
        });

    private static bool IsHash(string? value) =>
        value is { Length: 64 } && value.All(Uri.IsHexDigit);
}

public sealed record InstallationManifest(
    int Schema,
    string GameRoot,
    DateTimeOffset InstalledAt,
    string LauncherVersion,
    string ShimVersion,
    IReadOnlyList<InstalledFile> Files)
{
    public const int CurrentSchema = 2;

    public const string ShimRole = "shim";
    public const string IniRole = "ini";

    public InstalledFile? File(string role) =>
        Files.FirstOrDefault(file => string.Equals(file.Role, role, StringComparison.Ordinal));

    public bool IsCoherent =>
        Schema is 1 or CurrentSchema &&
        !string.IsNullOrWhiteSpace(GameRoot) &&
        Files is { Count: > 0 } &&
        Files.All(file => file is not null && file.IsCoherent);
}

public static class InstallationManifestStore
{
    private const int MaximumManifestBytes = 1024 * 1024;
    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static InstallationManifest? Load(string path, IFileSystem fileSystem)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(fileSystem);

        if (!fileSystem.FileExists(path))
        {
            return null;
        }

        try
        {
            using Stream stream = fileSystem.OpenRead(path);
            if (stream.Length > MaximumManifestBytes) return null;
            byte[] content = new byte[stream.Length];
            stream.ReadExactly(content);
            InstallationManifest? manifest =
                JsonSerializer.Deserialize<InstallationManifest>(content, Options);

            return manifest?.IsCoherent == true ? manifest : null;
        }
        catch (Exception exception)
            when (exception is JsonException or IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    public static InstallationManifest? LoadForGame(
        string path, string expectedGameRoot, LauncherPaths paths, IFileSystem fileSystem)
    {
        InstallationManifest? manifest = Load(path, fileSystem);
        if (manifest is null) return null;

        string expectedRoot;
        string recordedRoot;
        try
        {
            expectedRoot = LauncherPaths.NormaliseGameRoot(expectedGameRoot);
            recordedRoot = LauncherPaths.NormaliseGameRoot(manifest.GameRoot);
        }
        catch (Exception exception) when (exception is ArgumentException or NotSupportedException
                                           or PathTooLongException)
        {
            return null;
        }

        if (!string.Equals(expectedRoot, recordedRoot, StringComparison.OrdinalIgnoreCase) ||
            manifest.Files.Count != 2)
        {
            return null;
        }

        var expected = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            [InstallationManifest.ShimRole] = Path.Combine(expectedRoot, ShimIdentity.ShimFileName),
            [InstallationManifest.IniRole] = Path.Combine(expectedRoot, ShimConfiguration.IniFileName),
        };
        var seen = new HashSet<string>(StringComparer.Ordinal);
        string currentBackups = Path.GetFullPath(paths.BackupsFor(expectedRoot));
        string legacyBackups = Path.GetFullPath(paths.Backups);

        foreach (InstalledFile file in manifest.Files)
        {
            if (!seen.Add(file.Role) || !expected.TryGetValue(file.Role, out string? target))
                return null;

            string actual;
            try { actual = Path.GetFullPath(file.Path); }
            catch (Exception exception) when (exception is ArgumentException or NotSupportedException
                                               or PathTooLongException) { return null; }
            if (!string.Equals(actual, target, StringComparison.OrdinalIgnoreCase)) return null;

            if (file.PriorState == PriorState.Replaced)
            {
                string backup;
                try { backup = Path.GetFullPath(file.BackupPath!); }
                catch (Exception exception) when (exception is ArgumentException or NotSupportedException
                                                   or PathTooLongException) { return null; }
                string? backupDirectory = Path.GetDirectoryName(backup);
                bool currentLocation = string.Equals(
                    backupDirectory, currentBackups, StringComparison.OrdinalIgnoreCase);
                bool legacyLocation = string.Equals(
                    backupDirectory, legacyBackups, StringComparison.OrdinalIgnoreCase);
                if ((!currentLocation && !legacyLocation) ||
                    !Path.GetFileName(backup).Contains(
                        Path.GetFileName(target), StringComparison.OrdinalIgnoreCase) ||
                    fileSystem.IsReparsePoint(backupDirectory!) ||
                    fileSystem.IsReparsePoint(backup))
                    return null;
            }
        }

        return seen.SetEquals(expected.Keys) ? manifest : null;
    }

    public static void Save(string path, InstallationManifest manifest, IFileSystem fileSystem)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(manifest);
        ArgumentNullException.ThrowIfNull(fileSystem);

        if (!manifest.IsCoherent)
        {
            throw new ArgumentException(
                "Refusing to persist an incoherent manifest.", nameof(manifest));
        }

        string? directory = System.IO.Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            fileSystem.CreateDirectory(directory);
        }

        string staging = path + ".new";
        fileSystem.WriteAllBytes(staging, JsonSerializer.SerializeToUtf8Bytes(manifest, Options));
        fileSystem.Move(staging, path, overwrite: true);
    }
}
