// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Diagnostics;

namespace Revival.Launcher.Core;

public interface IGameSessionMonitor
{
    Task<int> WaitForExitAsync(CancellationToken cancellationToken, Action? started = null);
}

public sealed class WindowsGameSessionMonitor : IGameSessionMonitor
{
    internal const string DefaultGameProcessName = "FIFA17";

    private readonly string _processName;

    public WindowsGameSessionMonitor() : this(DefaultGameProcessName)
    {
    }

    internal WindowsGameSessionMonitor(string processName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(processName);
        _processName = processName;
    }

    public async Task<int> WaitForExitAsync(CancellationToken cancellationToken, Action? started = null)
    {
        Process? game = null;
        while (game is null)
        {
            cancellationToken.ThrowIfCancellationRequested();
            game = FindProcess();
            if (game is null)
            {
                await Task.Delay(TimeSpan.FromMilliseconds(250), cancellationToken)
                    .ConfigureAwait(false);
            }
        }

        using (game)
        {
            started?.Invoke();
            await game.WaitForExitAsync(CancellationToken.None).ConfigureAwait(false);
            return game.ExitCode;
        }
    }

    private Process? FindProcess()
    {
        Process? selected = null;
        foreach (Process candidate in Process.GetProcessesByName(_processName))
        {
            if (selected is null)
            {
                selected = candidate;
            }
            else
            {
                candidate.Dispose();
            }
        }

        return selected;
    }
}
