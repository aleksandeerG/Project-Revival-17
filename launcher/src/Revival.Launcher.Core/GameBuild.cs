// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Security.Cryptography;

namespace Revival.Launcher.Core;

public sealed record SupportedBuild(
    string Name,
    uint CardsDllTimeDateStamp,
    uint CardsDllSizeOfImage,
    string CardsDllSha256);

public static class GameBuilds
{
    public static readonly SupportedBuild FinalRetail = new(
        Name: "FIFA 17 final title update (1.0.48.30259)",
        CardsDllTimeDateStamp: 0x593B_2C2C,
        CardsDllSizeOfImage: 0x0031_D000,
        CardsDllSha256: "4706A881AE1FC7B5769FD810B25A868D29D2B16A8E65A7513436327EF645573C");

    public static IReadOnlyList<SupportedBuild> All { get; } = [FinalRetail];
}

public enum BuildVerdict
{
    Supported,

    SupportedButModified,

    UnknownBuild,

    CardsDllMissing,

    CardsDllUnreadable,
}

public sealed record BuildCheckResult(
    BuildVerdict Verdict,
    SupportedBuild? MatchedBuild,
    PeHeaders? Headers,
    PeReadFailure ReadFailure,
    string? ActualSha256)
{
    public bool MayPatch =>
        Verdict is BuildVerdict.Supported or BuildVerdict.SupportedButModified;
}

public static class BuildCheck
{
    public const string CardsDllName = "CardsDLL_Win64_retail.dll";
    public const string GameExecutableName = "FIFA17.exe";

    public static BuildCheckResult Check(string gameRoot, IFileSystem fileSystem)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(gameRoot);
        ArgumentNullException.ThrowIfNull(fileSystem);

        string cardsPath = Path.Combine(gameRoot, CardsDllName);
        if (!fileSystem.FileExists(cardsPath))
        {
            return new BuildCheckResult(
                BuildVerdict.CardsDllMissing, null, null, PeReadFailure.None, null);
        }

        PeHeaders? headers;
        PeReadFailure failure;
        try
        {
            using Stream stream = fileSystem.OpenRead(cardsPath);
            if (!PortableExecutable.TryRead(stream, out headers, out failure))
            {
                return new BuildCheckResult(
                    BuildVerdict.CardsDllUnreadable, null, null, failure, null);
            }
        }
        catch (IOException)
        {
            return new BuildCheckResult(
                BuildVerdict.CardsDllUnreadable, null, null, PeReadFailure.None, null);
        }
        catch (UnauthorizedAccessException)
        {
            return new BuildCheckResult(
                BuildVerdict.CardsDllUnreadable, null, null, PeReadFailure.None, null);
        }

        SupportedBuild? match = GameBuilds.All.FirstOrDefault(build =>
            build.CardsDllTimeDateStamp == headers!.TimeDateStamp &&
            build.CardsDllSizeOfImage == headers.SizeOfImage);

        if (match is null)
        {
            return new BuildCheckResult(
                BuildVerdict.UnknownBuild, null, headers, PeReadFailure.None, null);
        }

        string actual = ComputeSha256(fileSystem, cardsPath);
        bool bytesMatch = string.Equals(actual, match.CardsDllSha256, StringComparison.OrdinalIgnoreCase);

        return new BuildCheckResult(
            bytesMatch ? BuildVerdict.Supported : BuildVerdict.SupportedButModified,
            match,
            headers,
            PeReadFailure.None,
            actual);
    }

    private static string ComputeSha256(IFileSystem fileSystem, string path)
    {
        using Stream stream = fileSystem.OpenRead(path);
        byte[] digest = SHA256.HashData(stream);
        return Convert.ToHexString(digest);
    }
}
