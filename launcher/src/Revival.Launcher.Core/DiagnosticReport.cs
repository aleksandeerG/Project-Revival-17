// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Text;
using System.Text.RegularExpressions;

namespace Revival.Launcher.Core;

public static class DiagnosticReport
{
    public static string Create(string launcherVersion, ReleaseVersions? versions,
        PreflightReport? report, KeeperStatus? enrollment, Invite? invite,
        string? gameRoot, string? lastError)
    {
        var text = new StringBuilder();
        text.AppendLine("Project Revival 17 diagnostic report");
        text.AppendLine($"UTC: {DateTimeOffset.UtcNow:O}");
        text.AppendLine($"Launcher: {launcherVersion}");
        text.AppendLine($"Release: shim={versions?.Shim ?? "unknown"}, server={versions?.Server ?? "unknown"}, protocol={versions?.Protocol ?? "unknown"}, content={versions?.Content ?? "unknown"}");
        text.AppendLine($"Enrollment: {enrollment?.LastOutcome.ToString() ?? "not prepared"}; failures={enrollment?.ConsecutiveFailures ?? 0}");
        if (enrollment is not null)
        {
            text.AppendLine($"Lease expires UTC: {enrollment.LeaseExpiresAt:O}");
            text.AppendLine($"Server reports: launcher={enrollment.LauncherVersion}, minimum={enrollment.MinimumLauncherVersion}, server={enrollment.ServerVersion}, protocol={enrollment.ProtocolVersion}, content={enrollment.ContentVersion}");
        }
        foreach (CheckResult check in report?.Results ?? [])
            text.AppendLine($"{check.Check}: {check.State} — {check.Message}");
        if (!string.IsNullOrWhiteSpace(lastError)) text.AppendLine($"Last operation: {lastError}");
        return Redact(text.ToString(), invite, gameRoot);
    }

    public static string Redact(string text, Invite? invite, string? gameRoot)
    {
        string?[] secrets = [invite?.Password, invite?.EnrollmentToken, invite?.Username,
            invite?.CertificatePin, invite?.Server.Host, gameRoot,
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)];
        foreach (string secret in secrets.Where(s => !string.IsNullOrEmpty(s))
                     .Select(s => s!).OrderByDescending(s => s.Length))
        {
            text = text.Replace(secret, "[redacted]", StringComparison.OrdinalIgnoreCase);
            text = text.Replace(Uri.EscapeDataString(secret), "[redacted]", StringComparison.OrdinalIgnoreCase);
        }
        return Regex.Replace(text, @"FUT1-[\w\-+/=]*", "[invite redacted]",
            RegexOptions.IgnoreCase);
    }
}
