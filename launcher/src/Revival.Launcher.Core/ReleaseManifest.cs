// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Security.Cryptography;

namespace Revival.Launcher.Core;

public sealed record ReleaseArtifact(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("size")] long Size,
    [property: JsonPropertyName("sha256")] string Sha256);

public sealed record ReleaseVersions(
    [property: JsonPropertyName("launcher")] string Launcher,
    [property: JsonPropertyName("shim")] string Shim,
    [property: JsonPropertyName("server")] string Server,
    [property: JsonPropertyName("protocol")] string Protocol,
    [property: JsonPropertyName("content")] string Content);

public sealed record ReleaseManifest(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("releaseSerial")] int ReleaseSerial,
    [property: JsonPropertyName("releasedAt")] DateTimeOffset ReleasedAt,
    [property: JsonPropertyName("keyId")] string? KeyId,
    [property: JsonPropertyName("versions")] ReleaseVersions Versions,
    [property: JsonPropertyName("artifacts")] IReadOnlyList<ReleaseArtifact> Artifacts)
{
    public const int CurrentSchema = 1;

    public const string LauncherRole = "launcher";
    public const string ShimRole = "shim";
    public const string LauncherExecutableName = "RevivalLauncher.exe";

    public ReleaseArtifact? Artifact(string role) =>
        Artifacts?.FirstOrDefault(a => string.Equals(a.Role, role, StringComparison.Ordinal));

    public bool IsCoherent =>
        Schema == CurrentSchema &&
        ReleaseSerial > 0 &&
        Versions is not null &&
        !string.IsNullOrWhiteSpace(Versions.Launcher) &&
        !string.IsNullOrWhiteSpace(Versions.Shim) &&
        !string.IsNullOrWhiteSpace(Versions.Server) &&
        !string.IsNullOrWhiteSpace(Versions.Protocol) &&
        !string.IsNullOrWhiteSpace(Versions.Content) &&
        Artifacts is { Count: > 0 } &&
        Artifacts.All(artifact =>
            artifact is not null &&
            !string.IsNullOrWhiteSpace(artifact.Role) &&
            !string.IsNullOrWhiteSpace(artifact.Name) &&
            string.Equals(artifact.Name, Path.GetFileName(artifact.Name), StringComparison.Ordinal) &&
            artifact.Size > 0 &&
            artifact.Sha256 is { Length: 64 } &&
            artifact.Sha256.All(Uri.IsHexDigit)) &&
        Artifacts.Select(artifact => artifact.Role).Distinct(StringComparer.Ordinal).Count()
            == Artifacts.Count &&
        Artifacts.Select(artifact => artifact.Name).Distinct(StringComparer.OrdinalIgnoreCase).Count()
            == Artifacts.Count &&
        Artifact(LauncherRole) is { Name: LauncherExecutableName } &&
        Artifact(ShimRole) is { Name: ShimIdentity.PackagedShimFileName };
}

public enum ReleaseSerialOutcome { Accepted, OlderRelease, StateUnavailable }

public sealed class ReleaseSerialStore(IFileSystem fileSystem, LauncherPaths paths)
{
    public bool Accept(ReleaseManifest manifest) => CheckAndAccept(manifest) == ReleaseSerialOutcome.Accepted;

    public ReleaseSerialOutcome CheckAndAccept(ReleaseManifest manifest)
    {
        try
        {
            int highest = 0;
            if (fileSystem.FileExists(paths.HighestReleaseSerial))
                int.TryParse(System.Text.Encoding.ASCII.GetString(
                    fileSystem.ReadAllBytes(paths.HighestReleaseSerial)).Trim(), out highest);

            if (manifest.ReleaseSerial < highest) return ReleaseSerialOutcome.OlderRelease;
            if (manifest.ReleaseSerial == highest) return ReleaseSerialOutcome.Accepted;

            fileSystem.CreateDirectory(paths.Root);
            string staging = paths.HighestReleaseSerial + ".new";
            fileSystem.WriteAllBytes(staging,
                System.Text.Encoding.ASCII.GetBytes(manifest.ReleaseSerial.ToString(
                    System.Globalization.CultureInfo.InvariantCulture)));
            fileSystem.Move(staging, paths.HighestReleaseSerial, overwrite: true);
            return ReleaseSerialOutcome.Accepted;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return ReleaseSerialOutcome.StateUnavailable;
        }
    }
}

public static class ReleaseManifestStore
{
    public const string FileName = "manifest.json";
    private const int MaximumManifestBytes = 4 * 1024 * 1024;

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static ReleaseManifest? Load(string path, IFileSystem fileSystem)
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
            ReleaseManifest? manifest = JsonSerializer.Deserialize<ReleaseManifest>(
                StripByteOrderMark(content), Options);

            return manifest?.IsCoherent == true ? manifest : null;
        }
        catch (Exception exception)
            when (exception is JsonException or IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    public static ReleaseManifest? LoadValidated(string releaseDirectory, IFileSystem fileSystem)
    {
        string manifestPath = Path.Combine(releaseDirectory, FileName);
        ReleaseManifest? manifest = Load(manifestPath, fileSystem);
        if (manifest is null) return null;

        try
        {
            var expectedNames = manifest.Artifacts.Select(a => a.Name)
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
            var actualNames = fileSystem.ListFiles(releaseDirectory, "*")
                .Select(Path.GetFileName)
                .Where(name => !string.Equals(name, FileName, StringComparison.OrdinalIgnoreCase))
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
            if (!actualNames.SetEquals(expectedNames)) return null;

            foreach (ReleaseArtifact artifact in manifest.Artifacts)
            {
                string path = Path.Combine(releaseDirectory, artifact.Name);
                if (!fileSystem.FileExists(path)) return null;
                using Stream stream = fileSystem.OpenRead(path);
                if (stream.Length != artifact.Size ||
                    !string.Equals(Convert.ToHexString(SHA256.HashData(stream)), artifact.Sha256,
                                   StringComparison.OrdinalIgnoreCase))
                    return null;
            }
            return manifest;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static ReadOnlySpan<byte> StripByteOrderMark(byte[] content) =>
        content.Length >= 3 && content[0] == 0xEF && content[1] == 0xBB && content[2] == 0xBF
            ? content.AsSpan(3)
            : content;
}
