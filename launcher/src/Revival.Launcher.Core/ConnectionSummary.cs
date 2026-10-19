// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public sealed record ConnectionSummary(string Title, string Message)
{
    public static ConnectionSummary From(PreflightReport? report, KeeperStatus? enrollment,
        bool hasGame, bool hasInvite, bool connecting, bool gameRunning)
    {
        if (!hasGame) return new("Setup needed", "Find your FIFA17.exe to get started.");
        if (!hasInvite) return new("Setup needed", "Accept the invite your host sent you.");
        if (connecting) return new("Connecting", "Checking access and Revival services…");

        if (enrollment?.LastOutcome == KnockOutcome.Unauthorized)
            return new("Connection problem", "Your invite was refused. Replace it with a new invite from your host.");
        if (enrollment?.LastOutcome == KnockOutcome.CertificateRejected)
            return new("Connection problem", "The server certificate changed. Contact your host; automatic retries have stopped.");

        CheckResult? problem = report?.Problems
            .Where(r => r.Check != PreflightCheck.NoGameRunning && r.Check != PreflightCheck.Enrollment)
            .OrderByDescending(r => r.State == CheckState.Blocked)
            .ThenByDescending(r => r.Check == PreflightCheck.ReleasePackage)
            .FirstOrDefault();
        if (problem is not null)
            return new(problem.Check is PreflightCheck.ShimInstalled or PreflightCheck.GameInstall
                ? "Setup needs attention" : "Connection problem", problem.Message);

        if (enrollment?.Enrolled != true)
            return new(enrollment is null ? "Ready to connect" : "Connection problem",
                enrollment is null ? "Prepare the connection, then press Play in EA App."
                : enrollment.LastOutcome == KnockOutcome.Throttled
                    ? "Access requests are temporarily paused. Revival will retry automatically."
                    : "Access is unavailable. Revival will retry while this session is open.");

        bool checkedServices = new[] { PreflightCheck.ServerReady, PreflightCheck.AccountCredential,
            PreflightCheck.BlazeReachable, PreflightCheck.LauncherVersion }.All(check =>
                report?.Results.Any(r => r.Check == check && r.State == CheckState.Passed) == true);
        if (!checkedServices) return new("Connecting", "Access granted. Checking Revival services…");
        if (enrollment.ConsecutiveFailures > 0)
            return new("Connection problem", "Access is still valid, but renewal failed. Revival will retry automatically.");
        return gameRunning
            ? new("FIFA running", "Revival is keeping your connection active. You can minimize it to the tray.")
            : new("Ready", "Open EA App and press Play for FIFA 17. Keep Revival open while you play.");
    }
}
