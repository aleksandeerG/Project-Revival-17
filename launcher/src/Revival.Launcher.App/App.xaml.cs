// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Diagnostics;
using System.Windows;
using System.Windows.Threading;

namespace Revival.Launcher.App;

public partial class App : Application
{
    private DispatcherTimer? _smokeTimer;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        DispatcherUnhandledException += (_, args) =>
        {
            MessageBox.Show(
                args.Exception.Message,
                "Project Revival 17",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            args.Handled = true;
        };

        if (e.Args.Contains("--smoke-test", StringComparer.Ordinal))
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;

            string processPath = Environment.ProcessPath
                ?? throw new InvalidOperationException("The launcher process path is unavailable.");
            _ = FileVersionInfo.GetVersionInfo(processPath).FileVersion;

            _smokeTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(5) };
            _smokeTimer.Tick += (_, _) =>
            {
                _smokeTimer.Stop();
                Shutdown(0);
            };
            _smokeTimer.Start();
            return;
        }

        ShutdownMode = ShutdownMode.OnMainWindowClose;
        var window = new MainWindow();
        MainWindow = window;
        window.Show();
    }
}
