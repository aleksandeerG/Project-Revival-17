// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public delegate Task<KnockResult> KnockAttempt(CancellationToken cancellationToken);

public enum KeeperStop
{
    Cancelled,

    TokenRejected,

    CertificateRejected,
}

public sealed record KeeperStatus(
    bool Enrolled,
    DateTimeOffset? LastSuccess,
    DateTimeOffset? LeaseExpiresAt,
    int ConsecutiveFailures,
    KnockOutcome LastOutcome,
    string? LauncherVersion,
    string? MinimumLauncherVersion,
    string? ServerVersion = null,
    string? ProtocolVersion = null,
    string? ContentVersion = null);

public sealed class KnockKeeper(KnockAttempt attempt, TimeProvider? clock = null)
{
    private readonly KnockAttempt _attempt =
        attempt ?? throw new ArgumentNullException(nameof(attempt));

    private readonly TimeProvider _clock = clock ?? TimeProvider.System;
    private readonly object _gate = new();

    private KeeperStatus _status = new(
        false, null, null, 0, KnockOutcome.Unreachable, null, null, null, null, null);

    public event Action<KeeperStatus>? Changed;

    public KeeperStatus Status
    {
        get { lock (_gate) { return _status; } }
    }

    public async Task<KeeperStop> RunAsync(CancellationToken cancellationToken)
    {
        while (true)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                return KeeperStop.Cancelled;
            }

            KnockResult result;
            try
            {
                result = await _attempt(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return KeeperStop.Cancelled;
            }

            TimeSpan wait = Record(result);

            if (!ReknockPolicy.WorthRetrying(result.Outcome))
            {
                return result.Outcome == KnockOutcome.CertificateRejected
                    ? KeeperStop.CertificateRejected
                    : KeeperStop.TokenRejected;
            }

            if (!await WaitAsync(wait, cancellationToken).ConfigureAwait(false))
            {
                return KeeperStop.Cancelled;
            }
        }
    }

    private TimeSpan Record(KnockResult result)
    {
        DateTimeOffset now = _clock.GetUtcNow();
        KeeperStatus status;
        TimeSpan wait;

        lock (_gate)
        {
            if (result.Succeeded)
            {
                TimeSpan lease = result.ExpiresIn ?? TimeSpan.Zero;
                wait = ReknockPolicy.RenewalInterval(lease);
                _status = new KeeperStatus(
                    Enrolled: true,
                    LastSuccess: now,
                    LeaseExpiresAt: now + lease,
                    ConsecutiveFailures: 0,
                    LastOutcome: result.Outcome,
                    LauncherVersion: result.LauncherVersion,
                    MinimumLauncherVersion: result.MinimumLauncherVersion,
                    ServerVersion: result.ServerVersion,
                    ProtocolVersion: result.ProtocolVersion,
                    ContentVersion: result.ContentVersion);
            }
            else
            {
                int failures = _status.ConsecutiveFailures + 1;
                wait = result.Outcome == KnockOutcome.Throttled
                    ? ReknockPolicy.ThrottledDelay
                    : ReknockPolicy.RetryDelay(failures);

                _status = _status with
                {
                    Enrolled = ReknockPolicy.WorthRetrying(result.Outcome)
                        && _status.LeaseExpiresAt > now,
                    ConsecutiveFailures = failures,
                    LastOutcome = result.Outcome,
                };
            }

            status = _status;
        }

        Changed?.Invoke(status);
        return wait;
    }

    private async Task<bool> WaitAsync(TimeSpan total, CancellationToken cancellationToken)
    {
        DateTimeOffset due = _clock.GetUtcNow() + total;

        while (true)
        {
            TimeSpan remaining = due - _clock.GetUtcNow();
            if (remaining <= TimeSpan.Zero)
            {
                return true;
            }

            TimeSpan slice = remaining > ReknockPolicy.MaximumWaitSlice
                ? ReknockPolicy.MaximumWaitSlice
                : remaining;

            try
            {
                await Task.Delay(slice, _clock, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return false;
            }
        }
    }
}
