// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows;
using Microsoft.Win32;
using Revival.Launcher.Core;
using Forms = System.Windows.Forms;

namespace Revival.Launcher.App;

public partial class MainWindow : Window
{
    private const string ReleasesUrl = "https://github.com/aleksandeerG/Project-Revival-17/releases";
    private static readonly string LauncherVersion =
        Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "0.0.0";
    private readonly IFileSystem _fileSystem = WindowsFileSystem.Instance;
    private readonly LauncherPaths _paths = LauncherPaths.Default;
    private readonly ObservableCollection<CheckRow> _checks = [];
    private readonly ProfileStore _profiles;
    private readonly CancellationTokenSource _lifetime = new();
    private CancellationTokenSource? _sessionCancellation;
    private Forms.NotifyIcon? _tray;
    private GameCandidate? _game;
    private Invite? _invite;
    private ReleaseManifest? _release;
    private ReleaseVersions? _releaseVersions;
    private string? _releaseFailure;
    private string? _lastError;
    private PreflightReport? _lastReport;
    private KeeperStatus? _enrollment;
    private bool _busy;
    private bool _checking;
    private bool _refreshPending;
    private int _contextVersion;
    private bool IsBusy => _busy || _checking;
    private bool _gameRunning;
    private bool _sessionPrepared;
    private bool _closed;
    private string? _fix;

    public MainWindow()
    {
        InitializeComponent();
        _profiles = new ProfileStore(_fileSystem, _paths, new DpapiProtector());
        ChecksList.ItemsSource = _checks;
        Loaded += async (_, _) => await RunUiAsync(StartUpAsync);
        StateChanged += (_, _) =>
        {
            if (WindowState == WindowState.Minimized && _sessionCancellation is not null)
                MinimizeToTray();
        };
        Closed += (_, _) =>
        {
            _closed = true;
            _lifetime.Cancel();
            _sessionCancellation?.Cancel();
            _tray?.ContextMenuStrip?.Dispose();
            _tray?.Dispose();
            _tray = null;
        };
    }

    private async Task RunUiAsync(Func<Task> action)
    {
        try { await action(); }
        catch (OperationCanceledException) { }
        catch (Exception exception)
        {
            _lastError = $"Operation failed ({exception.GetType().Name}).";
            if (!_closed)
            {
                OperationText.Text = DiagnosticReport.Redact(exception.Message, _invite, _game?.GameRoot);
                SetBusy(null);
            }
        }
    }

    private async Task StartUpAsync()
    {
        SetBusy("Checking setup...");
        try
        {
            _invite = _profiles.Load();
            SetupCard.Visibility = _invite is null ? Visibility.Visible : Visibility.Collapsed;
            _release = await Task.Run(() => ReleaseManifestStore.LoadValidated(AppContext.BaseDirectory, _fileSystem));
            _releaseVersions = _release?.Versions;
            if (_release is null)
                _releaseFailure = "This release is incomplete or modified. Download it again and extract the whole zip into a new folder.";
            else if (!string.Equals(_release.Versions.Launcher, LauncherVersion, StringComparison.OrdinalIgnoreCase))
                _releaseFailure = "The launcher and package versions do not match. Extract a complete release into a new folder.";
            else
                _releaseFailure = new ReleaseSerialStore(_fileSystem, _paths).CheckAndAccept(_release) switch
                {
                    ReleaseSerialOutcome.OlderRelease => "A newer release was previously used on this PC. Open that release or download the latest one.",
                    ReleaseSerialOutcome.StateUnavailable => "Revival could not save its release record. Check access to your local application data folder and restart Revival.",
                    _ => null,
                };
            if (_releaseFailure is not null) _release = null;
            string? selected = new SelectedGameStore(_fileSystem, _paths).Load();
            _game = selected is null ? null : InstallLocator.FromExecutable(selected, _fileSystem);
            _game ??= InstallLocator.Locate(new WindowsUninstallRegistry(), _fileSystem).FirstOrDefault();
            ShowGame();
        }
        finally { SetBusy(null); }
        await RefreshAsync();
    }

    private void ShowGame()
    {
        GamePathText.Text = _game?.GameRoot ?? "FIFA 17 was not found. Browse to FIFA17.exe.";
        GameDetails.IsExpanded = _game is null;
        if (_game is null) { GameBuildText.Text = string.Empty; return; }
        BuildCheckResult build = BuildCheck.Check(_game.GameRoot, _fileSystem);
        GameBuildText.Text = build.Verdict switch
        {
            BuildVerdict.Supported => $"{GameBuilds.FinalRetail.Name} - supported.",
            BuildVerdict.SupportedButModified => "Supported, but the files have been modified.",
            BuildVerdict.UnknownBuild => "This build has not been tested.",
            _ => "The installation looks incomplete.",
        };
    }

    private async void OnUseInvite(object sender, RoutedEventArgs e) => await RunUiAsync(async () =>
    {
        if (IsBusy || _sessionCancellation is not null) return;
        InviteError.Text = string.Empty;
        if (!InviteCode.TryParse(InviteBox.Text, out Invite? invite, out InviteParseError error))
        {
            InviteError.Text = Describe(error);
            return;
        }
        _profiles.Save(invite!);
        _invite = invite;
        _contextVersion++;
        _enrollment = null;
        InviteBox.Clear();
        SetupCard.Visibility = Visibility.Collapsed;
        CancelInviteButton.Visibility = Visibility.Collapsed;
        OperationText.Text = "Invite saved. Apply it to FIFA using the next action below.";
        await RefreshAsync();
        OperationText.Text = NeedsInstall ? "Invite saved. Apply it to FIFA using the next action below."
            : "Invite saved. Your installed configuration is already current.";
    });

    private void OnChangeInvite(object sender, RoutedEventArgs e)
    {
        if (IsBusy || _sessionCancellation is not null) return;
        InviteError.Text = string.Empty;
        SetupCard.Visibility = Visibility.Visible;
        CancelInviteButton.Visibility = _invite is null ? Visibility.Collapsed : Visibility.Visible;
        InviteBox.Focus();
        InviteBox.BringIntoView();
    }

    private void OnCancelInvite(object sender, RoutedEventArgs e)
    {
        InviteBox.Clear();
        InviteError.Text = string.Empty;
        SetupCard.Visibility = _invite is null ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void OnBrowse(object sender, RoutedEventArgs e) => await RunUiAsync(async () =>
    {
        if (IsBusy || _sessionCancellation is not null) return;
        var dialog = new OpenFileDialog { Title = "Find FIFA17.exe", Filter = "FIFA 17|FIFA17.exe", CheckFileExists = true };
        if (dialog.ShowDialog(this) != true) return;
        GameCandidate? candidate = InstallLocator.FromExecutable(dialog.FileName, _fileSystem);
        if (candidate is null) { OperationText.Text = "Select the FIFA17.exe in your FIFA 17 installation."; return; }
        new SelectedGameStore(_fileSystem, _paths).Save(candidate.ExecutablePath);
        _game = candidate;
        _contextVersion++;
        ShowGame();
        await RefreshAsync();
    });

    private async void OnRefresh(object sender, RoutedEventArgs e) => await RunUiAsync(RefreshAsync);

    private async Task RefreshAsync()
    {
        if (_closed) return;
        if (IsBusy) { _refreshPending = true; return; }
        _refreshPending = false;
        _checking = true;
        int version = _contextVersion;
        BusyText.Text = "Checking...";
        UpdateScreen();
        try
        {
            using var probe = _invite is null ? null : new NetworkServerProbe(_invite.CertificatePin);
            PreflightReport report = await new Preflight(_fileSystem,
                (IServerProbe?)probe ?? new OfflineProbe(), new WindowsProcessProbe()).RunAsync(
                    _game, _game is null ? null : new ShimInstaller(_fileSystem, _paths).LoadManifest(_game.GameRoot),
                    _invite?.Server, CurrentEnrollment(), LauncherVersion, _lifetime.Token, BuildExpectations());
            if (version == _contextVersion) Show(report);
            else _refreshPending = true;
        }
        finally
        {
            _checking = false;
            if (!_busy) BusyText.Text = string.Empty;
            UpdateScreen();
            if (_refreshPending && !_busy && !_closed) await RefreshAsync();
        }
    }

    private KeeperStatus? CurrentEnrollment() => _enrollment is null ? null : _enrollment with
    {
        Enrolled = _enrollment.Enrolled && _enrollment.LeaseExpiresAt > DateTimeOffset.UtcNow,
    };

    private PreflightExpectations? BuildExpectations()
    {
        if (_release is null || _invite is null) return null;
        ReleaseArtifact? shim = _release.Artifact(ReleaseManifest.ShimRole);
        if (shim is null || !ShimConfiguration.TryGenerate(_invite.Server, _invite.Username,
                _invite.Password, _invite.CertificatePin, false, out byte[] ini, out _)) return null;
        return new PreflightExpectations(shim.Sha256, Convert.ToHexString(SHA256.HashData(ini)),
            _release.Versions.Launcher, _release.Versions.Shim, _release.Versions.Server,
            _release.Versions.Protocol, _release.Versions.Content, _invite.Username, _invite.Password);
    }

    private void Show(PreflightReport report)
    {
        if (_closed) return;
        if (_releaseFailure is not null)
            report = new PreflightReport(report.Results.Append(new CheckResult(
                PreflightCheck.ReleasePackage, CheckState.Blocked, _releaseFailure)).ToArray());
        _lastReport = report;
        _checks.Clear();
        foreach (CheckResult result in report.Results) _checks.Add(new CheckRow(result));
        UpdateScreen();
    }

    private bool NeedsInstall => _lastReport?.Results.Any(r =>
        r.Check == PreflightCheck.ShimInstalled && r.State != CheckState.Passed) == true;

    private void UpdateScreen()
    {
        if (_closed) return;
        bool session = _sessionCancellation is not null;
        bool running = _gameRunning || new WindowsProcessProbe().IsRunning(Preflight.GameProcessName);
        if (_invite is null)
            SetupCard.Visibility = _game is null ? Visibility.Collapsed : Visibility.Visible;
        AccountText.Text = _invite is null ? "No account configured" : $"Account: {_invite.Username}";
        ServerText.Text = _invite is null ? "Friends Server" : $"Friends Server - {_invite.Server.Host}";
        VersionText.Text = $"Launcher {LauncherVersion} - Shim {_releaseVersions?.Shim ?? "unknown"}";
        ConnectionSummary summary = ConnectionSummary.From(_lastReport, CurrentEnrollment(),
            _game is not null, _invite is not null, IsBusy, _gameRunning);
        StatusTitle.Text = summary.Title;
        StatusMessage.Text = summary.Message;
        SessionText.Text = _gameRunning ? "FIFA is running. Connection maintenance remains active."
            : session && _sessionPrepared ? "Waiting for FIFA. Start it from EA App, or cancel waiting."
            : "FIFA is started from EA App.";
        LaunchButton.Content = _game is null ? "Find FIFA 17"
            : _invite is null ? "Accept invite"
            : NeedsInstall && _release is not null && !running ? "Install / apply Revival files"
            : session ? "Connection session active" : running ? "Maintain connection" : "Prepare connection";
        LaunchButton.IsEnabled = !IsBusy && !session;
        InstallButton.Content = NeedsInstall ? "Install / apply invite" : "Repair files";
        InstallButton.IsEnabled = !IsBusy && !session && !running && _game is not null && _invite is not null && _release is not null;
        UninstallButton.IsEnabled = !IsBusy && !session && !running && _game is not null;
        BrowseButton.IsEnabled = ChangeInviteButton.IsEnabled = UseInviteButton.IsEnabled = !IsBusy && !session;
        RefreshButton.IsEnabled = !IsBusy && (!session || _sessionPrepared);
        CancelSessionButton.Visibility = session && !_gameRunning ? Visibility.Visible : Visibility.Collapsed;
        TrayButton.Visibility = session ? Visibility.Visible : Visibility.Collapsed;
        _fix = _releaseFailure is not null ? "release"
            : _enrollment?.LastOutcome == KnockOutcome.Unauthorized || _lastReport?.Results.Any(r =>
                r.Check == PreflightCheck.AccountCredential && r.State == CheckState.Blocked) == true ? "invite"
            : NeedsInstall && _game is not null && _invite is not null ? "install"
            : _lastReport?.Results.Any(r => r.Check == PreflightCheck.LauncherVersion &&
                r.State is CheckState.Blocked or CheckState.Warned) == true ? "release" : null;
        FixButton.Content = _fix switch { "release" => "View release downloads", "invite" => "Replace invite...", _ => "Repair files" };
        FixButton.Visibility = _fix is null ? Visibility.Collapsed : Visibility.Visible;
        FixButton.IsEnabled = !IsBusy && (_fix == "release" || (!session && (_fix != "install" || !running)));
        if (_tray is not null) _tray.Text = $"Project Revival 17 - {summary.Title}";
    }

    private void SetBusy(string? message)
    {
        _busy = message is not null;
        BusyText.Text = message ?? string.Empty;
        UpdateScreen();
    }

    private void OnPrimary(object sender, RoutedEventArgs e)
    {
        if (_game is null) OnBrowse(sender, e);
        else if (_invite is null) OnChangeInvite(sender, e);
        else if (NeedsInstall && InstallButton.IsEnabled) OnInstall(sender, e);
        else OnLaunch(sender, e);
    }

    private void OnFix(object sender, RoutedEventArgs e)
    {
        if (_fix == "release") OnReleases(sender, e);
        else if (_fix == "invite") OnChangeInvite(sender, e);
        else OnInstall(sender, e);
    }

    private bool CanModifyGame()
    {
        if (IsBusy || _sessionCancellation is not null || _game is null ||
            new WindowsProcessProbe().IsRunning(Preflight.GameProcessName))
        {
            OperationText.Text = "Finish the connection session and close FIFA before changing Revival files.";
            return false;
        }
        return true;
    }

    private async void OnInstall(object sender, RoutedEventArgs e) => await RunUiAsync(async () =>
    {
        if (!CanModifyGame() || _invite is null || _release is null) return;
        if (!ShimConfiguration.TryGenerate(_invite.Server, _invite.Username, _invite.Password,
            _invite.CertificatePin, false, out byte[] ini, out ConfigurationError error))
        {
            OperationText.Text = _lastError = $"Configuration could not be written: {error}.";
            return;
        }
        ReleaseArtifact shim = _release.Artifact(ReleaseManifest.ShimRole)!;
        SetBusy("Applying Revival files...");
        try
        {
            InstallResult result = await Task.Run(() => new ShimInstaller(_fileSystem, _paths).Install(
                _game!, Path.Combine(AppContext.BaseDirectory, ShimIdentity.PackagedShimFileName),
                shim.Sha256, ini, _release.Versions.Launcher, _release.Versions.Shim));
            OperationText.Text = result.Succeeded ? "Revival files applied. Prepare your connection next." : Describe(result);
            _lastError = result.Succeeded ? null : $"Install: {result.Outcome}.";
        }
        finally { SetBusy(null); }
        await RefreshAsync();
    });

    private async void OnUninstall(object sender, RoutedEventArgs e) => await RunUiAsync(async () =>
    {
        if (!CanModifyGame()) return;
        if (MessageBox.Show(this, "Remove Revival from this FIFA installation and restore the original files?",
            "Uninstall Revival", MessageBoxButton.YesNo) != MessageBoxResult.Yes) return;
        SetBusy("Removing Revival...");
        try
        {
            UninstallResult result = await Task.Run(() => new ShimInstaller(_fileSystem, _paths).Uninstall(_game!));
            OperationText.Text = result.Succeeded ? "Revival removed. Your original files have been restored." : Describe(result);
            _lastError = result.Succeeded ? null : $"Uninstall: {result.Outcome}.";
        }
        finally { SetBusy(null); }
        await RefreshAsync();
    });

    private async void OnLaunch(object sender, RoutedEventArgs e) => await RunUiAsync(async () =>
    {
        if (_game is null || IsBusy || _sessionCancellation is not null) return;
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
        _sessionCancellation = cancellation;
        _contextVersion++;
        _sessionPrepared = false;
        _gameRunning = false;
        _enrollment = null;
        OperationText.Text = string.Empty;
        SetBusy("Preparing connection...");
        try
        {
            Invite? invite = _invite;
            using var knock = invite is null ? null : new KnockClient(invite.CertificatePin, LauncherVersion);
            using var probe = invite is null ? null : new NetworkServerProbe(invite.CertificatePin);
            var session = new PlaySession(new Preflight(_fileSystem,
                (IServerProbe?)probe ?? new OfflineProbe(), new WindowsProcessProbe()), new WindowsGameSessionMonitor());
            session.PreflightCompleted += report => Dispatcher.Invoke(() =>
            {
                if (_closed) return;
                _sessionPrepared = true;
                Show(report);
                SetBusy(null);
                if ((CurrentEnrollment()?.Enrolled == true) != report.Results.Any(r =>
                    r.Check == PreflightCheck.Enrollment && r.State == CheckState.Passed))
                    _ = RunUiAsync(RefreshAsync);
            });
            session.GameStarted += () => Dispatcher.Invoke(() =>
            {
                _gameRunning = true;
                UpdateScreen();
            });
            session.EnrollmentChanged += status => Dispatcher.Invoke(() =>
            {
                _enrollment = status;
                _contextVersion++;
                UpdateScreen();
                if (_sessionPrepared && !_closed) _ = RunUiAsync(RefreshAsync);
            });
            PlayResult result = await session.RunAsync(_game,
                new ShimInstaller(_fileSystem, _paths).LoadManifest(_game.GameRoot), invite?.Server,
                invite is null ? null : token => knock!.KnockAsync(invite.Server.Host,
                    invite.KnockPort, invite.EnrollmentToken, token), LauncherVersion,
                cancellation.Token, BuildExpectations());
            if (!_closed)
            {
                OperationText.Text = result.Outcome switch
                {
                    PlayOutcome.Cancelled => "Waiting cancelled. You can prepare the connection again when ready.",
                    PlayOutcome.LaunchFailed => "The FIFA session could not be monitored. Prepare the connection to try again.",
                    _ => "FIFA has closed. Prepare the connection for your next session.",
                };
                if (result.Outcome == PlayOutcome.LaunchFailed) _lastError = "FIFA process monitoring failed.";
            }
        }
        finally
        {
            _sessionCancellation = null;
            _contextVersion++;
            _sessionPrepared = false;
            _gameRunning = false;
            _enrollment = null;
            SetBusy(null);
            if (!_closed && !IsVisible) RestoreFromTray();
        }
        await RefreshAsync();
    });

    private void OnCancelSession(object sender, RoutedEventArgs e)
    {
        if (!_gameRunning)
        {
            _sessionCancellation?.Cancel();
            BusyText.Text = "Cancelling waiting...";
        }
    }

    private void OnMinimizeToTray(object sender, RoutedEventArgs e) => MinimizeToTray();

    private void MinimizeToTray()
    {
        if (_tray is null)
        {
            var menu = new Forms.ContextMenuStrip();
            menu.Items.Add("Open Project Revival 17", null, (_, _) => Dispatcher.Invoke(RestoreFromTray));
            _tray = new Forms.NotifyIcon
            {
                Icon = System.Drawing.SystemIcons.Application,
                Text = "Project Revival 17",
                ContextMenuStrip = menu,
            };
            _tray.DoubleClick += (_, _) => Dispatcher.Invoke(RestoreFromTray);
        }
        _tray.Visible = true;
        Hide();
    }

    private void RestoreFromTray()
    {
        Show();
        WindowState = WindowState.Normal;
        Activate();
        if (_tray is not null) _tray.Visible = false;
    }

    private async void OnCopyDiagnostics(object sender, RoutedEventArgs e) => await RunUiAsync(() =>
    {
        Clipboard.SetText(DiagnosticReport.Create(LauncherVersion, _releaseVersions, _lastReport,
            CurrentEnrollment(), _invite, _game?.GameRoot, _lastError));
        CopyStatus.Text = "Report copied. Account, server address, paths and credentials are redacted.";
        return Task.CompletedTask;
    });

    private async void OnReleases(object sender, RoutedEventArgs e) => await RunUiAsync(() =>
    {
        Process.Start(new ProcessStartInfo(ReleasesUrl) { UseShellExecute = true });
        return Task.CompletedTask;
    });

    private void OnProjectLink(object sender, System.Windows.Navigation.RequestNavigateEventArgs e)
    {
        Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
        e.Handled = true;
    }

    private static string Describe(InviteParseError error) => error switch
    {
        InviteParseError.Empty => "Paste the code your host sent you.",
        InviteParseError.WrongPrefix => "That does not look like an invite code.",
        InviteParseError.NotBase64 or InviteParseError.NotJson =>
            "That code looks incomplete — copy the whole thing and try again.",
        InviteParseError.UnsupportedVersion =>
            "That code is newer than this launcher. Update first.",
        InviteParseError.HostTooLong =>
            "That server's address is too long for FIFA to use. Tell your host.",
        InviteParseError.HostInvalid => "That server address is not a valid hostname or IP address.",
        InviteParseError.PinMissingOrMalformed =>
            "That code is missing its security fingerprint. Ask for a new one.",
        InviteParseError.PortOutOfRange => "That code contains an invalid port.",
        InviteParseError.TokenMissing => "That code has no access token in it.",
        _ => "That code could not be used. Ask your host for a new one.",
    };

    private static string Describe(InstallResult result) => result.Outcome switch
    {
        InstallOutcome.RefusedForeignShim =>
            "Another mod's version.dll is already installed. It has been left alone — "
            + "remove it yourself if you want to use Revival.\n\n" + result.Detail,

        InstallOutcome.RefusedUnreadableShim =>
            "A version.dll is present that could not be identified, so it was left alone.\n\n"
            + result.Detail,

        InstallOutcome.RefusedUnsupportedBuild =>
            "This build of FIFA 17 has not been tested and cannot be patched safely.\n\n"
            + result.Detail,

        InstallOutcome.GameFolderNotWritable =>
            "The game folder could not be written to. Do not install the game in a protected "
            + "folder such as Program Files: move it to a normal folder, for example C:\\Games\\FIFA 17, "
            + "then select FIFA17.exe again.\n\n" + result.Detail,

        InstallOutcome.SourceHashMismatch =>
            "The included FIFA shim does not match this release. Re-download and extract it again.",

        _ => $"Installation failed: {result.Outcome}. {result.Detail}",
    };

    private static string Describe(UninstallResult result) => result.Outcome switch
    {
        UninstallOutcome.NothingToRemove => "Revival is not recorded as installed here.",
        UninstallOutcome.LeftForeignFile =>
            "Files changed after installation, so nothing was removed:\n\n" +
            string.Join("\n", result.LeftAlone),
        UninstallOutcome.BackupMissing =>
            "An original-file backup is missing or corrupt, so nothing was removed.\n\n" + result.Detail,
        UninstallOutcome.Busy => "Another launcher is changing this installation. Try again shortly.",
        UninstallOutcome.InvalidInstallationState =>
            "The install record is invalid. No game files were changed.",
        UninstallOutcome.RollbackFailed =>
            "Removal failed and the automatic rollback also failed. Check the game folder before launching.\n\n" + result.Detail,
        _ => "Removal failed. No further changes should be attempted until this is resolved.\n\n" + result.Detail,
    };

    private sealed class OfflineProbe : IServerProbe
    {
        public Task<(bool Ready, string? Detail)> ReadyAsync(string host, int port, CancellationToken cancellationToken) =>
            Task.FromResult((false, (string?)"no server configured"));
        public Task<bool> CanConnectAsync(string host, int port, CancellationToken cancellationToken) => Task.FromResult(false);
        public Task<bool> ResolvesAsync(string host, CancellationToken cancellationToken) => Task.FromResult(false);
        public Task<AccountProbeResult> ValidateAccountAsync(string host, int port, string username, string password,
            CancellationToken cancellationToken) => Task.FromResult(AccountProbeResult.Unreachable);
    }
}
