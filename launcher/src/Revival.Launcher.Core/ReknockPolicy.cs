// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public static class ReknockPolicy
{
    public const int RenewalsPerLease = 8;

    public static readonly TimeSpan MinimumInterval = TimeSpan.FromSeconds(30);
    public static readonly TimeSpan MaximumInterval = TimeSpan.FromHours(1);

    public static readonly TimeSpan MaximumWaitSlice = TimeSpan.FromMinutes(1);

    public static TimeSpan RenewalInterval(TimeSpan lease)
    {
        if (lease <= TimeSpan.Zero)
        {
            return MinimumInterval;
        }

        TimeSpan share = lease / RenewalsPerLease;
        TimeSpan interval = share < MinimumInterval ? MinimumInterval : share;

        if (interval > MaximumInterval)
        {
            interval = MaximumInterval;
        }

        TimeSpan half = lease / 2;
        return interval > half ? half : interval;
    }

    public static TimeSpan RetryDelay(int consecutiveFailures)
    {
        int steps = Math.Clamp(consecutiveFailures, 1, 5);
        double seconds = 5 * Math.Pow(2, steps - 1);
        return TimeSpan.FromSeconds(seconds);
    }

    public static bool WorthRetrying(KnockOutcome outcome) => outcome switch
    {
        KnockOutcome.Enrolled => true,
        KnockOutcome.Unreachable => true,
        KnockOutcome.Throttled => true,
        KnockOutcome.UnexpectedResponse => true,

        KnockOutcome.CertificateRejected => false,
        KnockOutcome.Unauthorized => false,
        _ => false,
    };

    public static readonly TimeSpan ThrottledDelay = TimeSpan.FromMinutes(16);
}
