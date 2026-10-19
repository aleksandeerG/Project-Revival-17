// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public enum PlayOutcome
{
    Completed,

    Blocked,

    LaunchFailed,

    Cancelled,
}

public sealed record PlayResult(
    PlayOutcome Outcome,
    PreflightReport? Preflight = null,
    int? ExitCode = null,
    KeeperStop? Enrollment = null,
    string? Detail = null);

public sealed class PlaySession(
    Preflight preflight,
    IGameSessionMonitor gameSession)
{
    private readonly Preflight _preflight =
        preflight ?? throw new ArgumentNullException(nameof(preflight));

    private readonly IGameSessionMonitor _gameSession =
        gameSession ?? throw new ArgumentNullException(nameof(gameSession));

    public event Action<KeeperStatus>? EnrollmentChanged;

    public event Action<PreflightReport>? PreflightCompleted;

    public event Action? GameStarted;

    public async Task<PlayResult> RunAsync(
        GameCandidate candidate,
        InstallationManifest? manifest,
        ServerProfile? server,
        KnockAttempt? knock,
        string launcherVersion,
        CancellationToken cancellationToken,
        PreflightExpectations? expectations = null)
    {
        ArgumentNullException.ThrowIfNull(candidate);

        using var session = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        KnockKeeper? keeper = null;
        Task<KeeperStop>? keeping = null;

        PreflightReport? report = null;
        try
        {
            if (knock is not null)
            {
                keeper = new KnockKeeper(knock);
                keeper.Changed += status => EnrollmentChanged?.Invoke(status);
                keeping = keeper.RunAsync(session.Token);
                await WaitForFirstAttemptAsync(keeper, session.Token).ConfigureAwait(false);
            }

            cancellationToken.ThrowIfCancellationRequested();
            report = await _preflight.RunAsync(candidate, manifest, server, keeper?.Status,
                launcherVersion, session.Token, expectations).ConfigureAwait(false);
            PreflightCompleted?.Invoke(report);
            cancellationToken.ThrowIfCancellationRequested();

            int exitCode = await _gameSession.WaitForExitAsync(cancellationToken,
                () => GameStarted?.Invoke()).ConfigureAwait(false);
            return new PlayResult(PlayOutcome.Completed, report, exitCode,
                await StopKeeperAsync(session, keeping).ConfigureAwait(false));
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return new PlayResult(PlayOutcome.Cancelled, report);
        }
        catch (Exception exception)
            when (exception is InvalidOperationException or IOException
                      or System.ComponentModel.Win32Exception)
        {
            return new PlayResult(PlayOutcome.LaunchFailed, report, Detail: exception.Message);
        }
        finally
        {
            await StopKeeperAsync(session, keeping).ConfigureAwait(false);
        }
    }

    private static async Task WaitForFirstAttemptAsync(
        KnockKeeper keeper, CancellationToken cancellationToken)
    {
        var settled = new TaskCompletionSource();

        void OnChanged(KeeperStatus _) => settled.TrySetResult();

        keeper.Changed += OnChanged;
        try
        {
            if (keeper.Status.LastSuccess is not null || keeper.Status.ConsecutiveFailures > 0)
            {
                return;
            }

            Task delay = Task.Delay(TimeSpan.FromSeconds(20), cancellationToken);
            await Task.WhenAny(settled.Task, delay).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            keeper.Changed -= OnChanged;
        }
    }

    private static async Task<KeeperStop?> StopKeeperAsync(
        CancellationTokenSource session, Task<KeeperStop>? keeping)
    {
        await session.CancelAsync().ConfigureAwait(false);
        return await AwaitKeeperAsync(keeping).ConfigureAwait(false);
    }

    private static async Task<KeeperStop?> AwaitKeeperAsync(Task<KeeperStop>? keeping)
    {
        if (keeping is null)
        {
            return null;
        }

        try
        {
            return await keeping.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return KeeperStop.Cancelled;
        }
    }
}
