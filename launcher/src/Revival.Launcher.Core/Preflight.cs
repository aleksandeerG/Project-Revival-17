// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public enum PreflightCheck
{
    GameInstall,
    ShimInstalled,
    NoGameRunning,
    HostResolves,
    Enrollment,
    ServerReady,
    BlazeReachable,
    LauncherVersion,
    AccountCredential,
    ReleasePackage,
}

public enum CheckState
{
    Passed,

    Warned,

    Blocked,

    Skipped,
}

public sealed record CheckResult(
    PreflightCheck Check,
    CheckState State,
    string Message,
    string? Detail = null);

public sealed record PreflightReport(IReadOnlyList<CheckResult> Results)
{
    public bool CanLaunch => !Results.Any(result => result.State == CheckState.Blocked);

    public IEnumerable<CheckResult> Problems =>
        Results.Where(result => result.State is CheckState.Blocked or CheckState.Warned);
}

public sealed record PreflightExpectations(
    string ShimSha256,
    string IniSha256,
    string LauncherVersion,
    string ShimVersion,
    string ServerVersion,
    string ProtocolVersion,
    string ContentVersion,
    string Username,
    string Password);

public interface IServerProbe
{
    Task<(bool Ready, string? Detail)> ReadyAsync(
        string host, int port, CancellationToken cancellationToken);

    Task<bool> CanConnectAsync(string host, int port, CancellationToken cancellationToken);

    Task<bool> ResolvesAsync(string host, CancellationToken cancellationToken);

    Task<AccountProbeResult> ValidateAccountAsync(
        string host, int port, string username, string password,
        CancellationToken cancellationToken);
}

public enum AccountProbeResult
{
    Valid,
    Invalid,
    Throttled,
    Unreachable,
}

public interface IProcessProbe
{
    bool IsRunning(string processName);
}

public sealed class Preflight(
    IFileSystem fileSystem,
    IServerProbe serverProbe,
    IProcessProbe processProbe)
{
    public const string GameProcessName = "FIFA17";

    private readonly IFileSystem _fileSystem =
        fileSystem ?? throw new ArgumentNullException(nameof(fileSystem));

    private readonly IServerProbe _serverProbe =
        serverProbe ?? throw new ArgumentNullException(nameof(serverProbe));

    private readonly IProcessProbe _processProbe =
        processProbe ?? throw new ArgumentNullException(nameof(processProbe));

    public async Task<PreflightReport> RunAsync(
        GameCandidate? candidate,
        InstallationManifest? manifest,
        ServerProfile? server,
        KeeperStatus? enrollment,
        string launcherVersion,
        CancellationToken cancellationToken = default,
        PreflightExpectations? expectations = null)
    {
        List<CheckResult> results =
        [
            CheckGame(candidate),
            CheckShim(candidate, manifest, expectations),
            CheckGameNotRunning(),
        ];

        if (server is null)
        {
            results.Add(new CheckResult(
                PreflightCheck.HostResolves, CheckState.Skipped, "No server configured. Accept an invite to set up Revival."));
            return new PreflightReport(results);
        }

        results.Add(await CheckHostAsync(server, cancellationToken).ConfigureAwait(false));
        results.Add(CheckEnrollment(enrollment));
        if (enrollment?.Enrolled != true)
        {
            foreach (PreflightCheck check in new[] { PreflightCheck.ServerReady,
                         PreflightCheck.AccountCredential, PreflightCheck.BlazeReachable,
                         PreflightCheck.LauncherVersion })
                results.Add(new CheckResult(check, CheckState.Skipped,
                    "Waiting for connection enrollment before checking this service."));
            return new PreflightReport(results);
        }
        results.Add(await CheckReadyAsync(server, cancellationToken).ConfigureAwait(false));
        if (expectations is not null)
            results.Add(await CheckAccountAsync(server, expectations, cancellationToken)
                .ConfigureAwait(false));
        results.Add(await CheckBlazeAsync(server, cancellationToken).ConfigureAwait(false));
        results.Add(CheckVersion(enrollment, launcherVersion, expectations));

        return new PreflightReport(results);
    }

    private CheckResult CheckGame(GameCandidate? candidate)
    {
        if (candidate is null)
        {
            return new CheckResult(
                PreflightCheck.GameInstall, CheckState.Blocked,
                "FIFA 17 was not found. Use Browse to point at FIFA17.exe.");
        }

        BuildCheckResult build = BuildCheck.Check(candidate.GameRoot, _fileSystem);

        return build.Verdict switch
        {
            BuildVerdict.Supported => new CheckResult(
                PreflightCheck.GameInstall, CheckState.Passed,
                $"FIFA 17 found at {candidate.GameRoot}."),

            BuildVerdict.SupportedButModified => new CheckResult(
                PreflightCheck.GameInstall, CheckState.Warned,
                "The game files have been modified by something else. This may still work.",
                build.ActualSha256),

            BuildVerdict.UnknownBuild => new CheckResult(
                PreflightCheck.GameInstall, CheckState.Blocked,
                "This build of FIFA 17 has not been tested and cannot be patched safely.",
                $"CardsDLL TimeDateStamp 0x{build.Headers!.TimeDateStamp:X8}, " +
                $"SizeOfImage 0x{build.Headers.SizeOfImage:X8}"),

            BuildVerdict.CardsDllMissing => new CheckResult(
                PreflightCheck.GameInstall, CheckState.Blocked,
                $"{BuildCheck.CardsDllName} is missing. The installation looks incomplete."),

            _ => new CheckResult(
                PreflightCheck.GameInstall, CheckState.Blocked,
                $"{BuildCheck.CardsDllName} could not be read.", build.ReadFailure.ToString()),
        };
    }

    private CheckResult CheckShim(
        GameCandidate? candidate, InstallationManifest? manifest,
        PreflightExpectations? expectations)
    {
        if (candidate is null)
        {
            return new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked, "Nothing to check yet.");
        }

        string shimPath = Path.Combine(candidate.GameRoot, ShimIdentity.ShimFileName);
        string iniPath = Path.Combine(candidate.GameRoot, ShimConfiguration.IniFileName);

        ShimIdentityResult identity = ShimIdentity.Identify(
            shimPath, _fileSystem, manifest?.File(InstallationManifest.ShimRole)?.InstalledSha256);

        CheckResult basic = identity.Presence switch
        {
            ShimPresence.Absent => new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked,
                "The Revival files are not installed yet. Choose Install."),

            ShimPresence.Foreign => new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked,
                "Another mod's version.dll is installed. Remove it first — this will not overwrite it.",
                shimPath),

            ShimPresence.Unreadable => new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked,
                "A version.dll is present that cannot be identified. It has been left alone.",
                shimPath),

            _ when !_fileSystem.FileExists(iniPath) => new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked,
                "The configuration file is missing. Choose Repair."),

            _ => new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Passed, "Revival files are installed."),
        };

        if (basic.State != CheckState.Passed || expectations is null)
            return basic;

        if (manifest is null)
            return new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked,
                "The installation record is missing or invalid. Choose Repair.");

        InstalledFile? shim = manifest.File(InstallationManifest.ShimRole);
        InstalledFile? ini = manifest.File(InstallationManifest.IniRole);
        if (shim is null || ini is null ||
            !string.Equals(shim.InstalledSha256, expectations.ShimSha256,
                           StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(ini.InstalledSha256, expectations.IniSha256,
                           StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(manifest.LauncherVersion, expectations.LauncherVersion,
                           StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(manifest.ShimVersion, expectations.ShimVersion,
                           StringComparison.OrdinalIgnoreCase) ||
            !FileMatches(shimPath, expectations.ShimSha256) ||
            !FileMatches(iniPath, expectations.IniSha256))
        {
            return new CheckResult(
                PreflightCheck.ShimInstalled, CheckState.Blocked,
                "The Revival files are outdated or modified. Choose Repair.");
        }

        return basic;
    }

    private bool FileMatches(string path, string expected)
    {
        try
        {
            using Stream stream = _fileSystem.OpenRead(path);
            string actual = Convert.ToHexString(
                System.Security.Cryptography.SHA256.HashData(stream));
            return string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private CheckResult CheckGameNotRunning() =>
        _processProbe.IsRunning(GameProcessName)
            ? new CheckResult(
                PreflightCheck.NoGameRunning, CheckState.Blocked,
                "FIFA 17 is already running. Close it first.")
            : new CheckResult(
                PreflightCheck.NoGameRunning, CheckState.Passed, "FIFA 17 is not running.");

    private async Task<CheckResult> CheckHostAsync(
        ServerProfile server, CancellationToken cancellationToken)
    {
        bool resolves = await _serverProbe
            .ResolvesAsync(server.Host, cancellationToken).ConfigureAwait(false);

        return resolves
            ? new CheckResult(PreflightCheck.HostResolves, CheckState.Passed,
                              $"{server.Host} resolves.")
            : new CheckResult(PreflightCheck.HostResolves, CheckState.Warned,
                              $"{server.Host} could not be resolved. Check your internet connection.");
    }

    private static CheckResult CheckEnrollment(KeeperStatus? enrollment)
    {
        if (enrollment is null)
        {
            return new CheckResult(
                PreflightCheck.Enrollment, CheckState.Warned, "Not enrolled yet.");
        }

        if (enrollment.Enrolled)
        {
            return new CheckResult(
                PreflightCheck.Enrollment, CheckState.Passed,
                "Your address is enrolled and will be kept enrolled while you play.");
        }

        string message = enrollment.LastOutcome switch
        {
            KnockOutcome.Unauthorized =>
                "Your invite was refused. It may have been revoked — ask for a new one.",
            KnockOutcome.Throttled =>
                "Too many attempts. Enrollment is paused for a few minutes.",
            KnockOutcome.CertificateRejected =>
                "The server presented an unexpected certificate. Nothing was sent to it.",
            _ => "Your address is not enrolled, so the game ports will refuse you.",
        };

        return new CheckResult(PreflightCheck.Enrollment, CheckState.Warned, message);
    }

    private async Task<CheckResult> CheckReadyAsync(
        ServerProfile server, CancellationToken cancellationToken)
    {
        (bool ready, string? detail) = await _serverProbe
            .ReadyAsync(server.Host, server.AccountsPort, cancellationToken).ConfigureAwait(false);

        return ready
            ? new CheckResult(PreflightCheck.ServerReady, CheckState.Passed, "The server is ready.")
            : new CheckResult(
                PreflightCheck.ServerReady, CheckState.Warned,
                "The server is not reporting itself ready.", detail);
    }

    private async Task<CheckResult> CheckBlazeAsync(
        ServerProfile server, CancellationToken cancellationToken)
    {
        bool reachable = await _serverProbe
            .CanConnectAsync(server.Host, server.BlazePort, cancellationToken).ConfigureAwait(false);

        return reachable
            ? new CheckResult(PreflightCheck.BlazeReachable, CheckState.Passed,
                              "The game service is reachable.")
            : new CheckResult(
                PreflightCheck.BlazeReachable, CheckState.Warned,
                $"Port {server.BlazePort} did not accept a connection. " +
                "If you are not enrolled, that is the cause.");
    }

    private async Task<CheckResult> CheckAccountAsync(
        ServerProfile server, PreflightExpectations expectations,
        CancellationToken cancellationToken)
    {
        AccountProbeResult result = await _serverProbe.ValidateAccountAsync(
            server.Host, server.AccountsPort, expectations.Username,
            expectations.Password, cancellationToken).ConfigureAwait(false);
        return result switch
        {
            AccountProbeResult.Valid => new CheckResult(
                PreflightCheck.AccountCredential, CheckState.Passed,
                "The stored account credential is valid."),
            AccountProbeResult.Invalid => new CheckResult(
                PreflightCheck.AccountCredential, CheckState.Blocked,
                "The stored account credential was refused. Use a replacement invite."),
            AccountProbeResult.Throttled => new CheckResult(
                PreflightCheck.AccountCredential, CheckState.Warned,
                "Account validation is temporarily throttled."),
            _ => new CheckResult(
                PreflightCheck.AccountCredential, CheckState.Warned,
                "The account could not be validated while the server is unreachable."),
        };
    }

    private static CheckResult CheckVersion(
        KeeperStatus? enrollment, string launcherVersion,
        PreflightExpectations? expectations)
    {
        string? minimum = enrollment?.MinimumLauncherVersion;
        string? current = enrollment?.LauncherVersion;

        if (expectations is not null && enrollment?.Enrolled == true &&
            (!string.Equals(enrollment.ProtocolVersion, expectations.ProtocolVersion,
                            StringComparison.Ordinal) ||
             !string.Equals(enrollment.ContentVersion, expectations.ContentVersion,
                            StringComparison.Ordinal) ||
             !string.Equals(enrollment.ServerVersion, expectations.ServerVersion,
                            StringComparison.Ordinal)))
        {
            return new CheckResult(
                PreflightCheck.LauncherVersion, CheckState.Blocked,
                "The launcher release is not compatible with this server.",
                $"server={enrollment.ServerVersion}, protocol={enrollment.ProtocolVersion}, " +
                $"content={enrollment.ContentVersion}");
        }

        if (string.IsNullOrWhiteSpace(minimum))
        {
            return new CheckResult(
                PreflightCheck.LauncherVersion, CheckState.Skipped,
                "The server has not reported a version yet.");
        }

        if (SemanticVersion.IsOlder(launcherVersion, minimum))
        {
            return new CheckResult(
                PreflightCheck.LauncherVersion, CheckState.Blocked,
                $"This launcher ({launcherVersion}) is older than the server requires ({minimum}). " +
                "Connecting will probably fail — update first.");
        }

        if (SemanticVersion.IsOlder(launcherVersion, current))
        {
            return new CheckResult(
                PreflightCheck.LauncherVersion, CheckState.Warned,
                $"A newer launcher is available ({current}).");
        }

        return new CheckResult(
            PreflightCheck.LauncherVersion, CheckState.Passed, "The launcher is up to date.");
    }
}
