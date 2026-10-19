// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Security.Cryptography;

namespace Revival.Launcher.Core;

public enum ShimPresence
{
    Absent,

    Ours,

    Foreign,

    Unreadable,
}

public enum ShimEvidence
{
    None,

    InstallationManifest,

    ExportSurface,

    ForeignExportSurface,

    Unparsable,
}

public sealed record ShimIdentityResult(
    ShimPresence Presence,
    ShimEvidence Evidence,
    string? Sha256,
    int ExportCount,
    int OriginExportCount)
{
    public bool MayReplace => Presence is ShimPresence.Absent or ShimPresence.Ours;
}

public static class ShimIdentity
{
    public const string PackagedShimFileName = "FIFA17Revival.Shim.dll";

    public const string ShimFileName = "version.dll";

    public static readonly IReadOnlySet<string> VersionExports = new HashSet<string>(StringComparer.Ordinal)
    {
        "GetFileVersionInfoA", "GetFileVersionInfoByHandle", "GetFileVersionInfoExA",
        "GetFileVersionInfoExW", "GetFileVersionInfoSizeA", "GetFileVersionInfoSizeExA",
        "GetFileVersionInfoSizeExW", "GetFileVersionInfoSizeW", "GetFileVersionInfoW",
        "VerFindFileA", "VerFindFileW", "VerInstallFileA", "VerInstallFileW",
        "VerLanguageNameA", "VerLanguageNameW", "VerQueryValueA", "VerQueryValueW",
    };

    public static readonly IReadOnlySet<string> RequiredOriginExports = new HashSet<string>(StringComparer.Ordinal)
    {
        "OriginStartup", "OriginShutdown", "OriginRequestAuthCode", "OriginUpdate",
    };

    private const int MinimumVersionExports = 15;

    private const int MinimumOriginExports = 12;

    public static ShimIdentityResult Identify(
        string shimPath, IFileSystem fileSystem, string? knownInstalledSha256 = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(shimPath);
        ArgumentNullException.ThrowIfNull(fileSystem);

        if (!fileSystem.FileExists(shimPath))
        {
            return new ShimIdentityResult(ShimPresence.Absent, ShimEvidence.None, null, 0, 0);
        }

        string? hash = TryHash(fileSystem, shimPath);
        if (hash is null)
        {
            return new ShimIdentityResult(
                ShimPresence.Unreadable, ShimEvidence.Unparsable, null, 0, 0);
        }

        if (knownInstalledSha256 is not null &&
            string.Equals(hash, knownInstalledSha256, StringComparison.OrdinalIgnoreCase))
        {
            return new ShimIdentityResult(
                ShimPresence.Ours, ShimEvidence.InstallationManifest, hash, 0, 0);
        }

        if (!PeExports.TryReadNamesFromFile(
                shimPath, fileSystem, out IReadOnlyList<string> names, out _))
        {
            return new ShimIdentityResult(
                ShimPresence.Unreadable, ShimEvidence.Unparsable, hash, 0, 0);
        }

        int versionExports = names.Count(VersionExports.Contains);
        int originExports = names.Count(name => name.StartsWith("Origin", StringComparison.Ordinal));
        bool hasRequiredOrigin = RequiredOriginExports.All(names.Contains);

        bool ours =
            versionExports >= MinimumVersionExports &&
            originExports >= MinimumOriginExports &&
            hasRequiredOrigin;

        return new ShimIdentityResult(
            ours ? ShimPresence.Ours : ShimPresence.Foreign,
            ours ? ShimEvidence.ExportSurface : ShimEvidence.ForeignExportSurface,
            hash,
            names.Count,
            originExports);
    }

    private static string? TryHash(IFileSystem fileSystem, string path)
    {
        try
        {
            using Stream stream = fileSystem.OpenRead(path);
            return Convert.ToHexString(SHA256.HashData(stream));
        }
        catch (Exception exception)
            when (exception is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }
}
