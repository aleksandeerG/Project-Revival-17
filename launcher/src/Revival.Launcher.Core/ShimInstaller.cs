// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Security.Cryptography;

namespace Revival.Launcher.Core;

public enum InstallOutcome
{
    Installed,

    RefusedForeignShim,

    RefusedUnreadableShim,

    SourceMissing,

    SourceHashMismatch,

    GameFolderNotWritable,

    RefusedUnsupportedBuild,

    Busy,

    InvalidInstallationState,

    RollbackFailed,
}

public enum UninstallOutcome
{
    Removed,

    NothingToRemove,

    LeftForeignFile,

    BackupMissing,

    GameFolderNotWritable,

    Busy,

    InvalidInstallationState,

    RollbackFailed,
}

public sealed record InstallResult(
    InstallOutcome Outcome,
    InstallationManifest? Manifest = null,
    ShimIdentityResult? Existing = null,
    string? Detail = null)
{
    public bool Succeeded => Outcome == InstallOutcome.Installed;
}

public sealed record UninstallResult(
    UninstallOutcome Outcome,
    IReadOnlyList<string> Removed,
    IReadOnlyList<string> Restored,
    IReadOnlyList<string> LeftAlone,
    string? Detail = null)
{
    public bool Succeeded => Outcome == UninstallOutcome.Removed;
}

public sealed class ShimInstaller
{
    private readonly IFileSystem _fileSystem;
    private readonly LauncherPaths _paths;
    private readonly TimeProvider _clock;
    private readonly IDataProtector _protector;

    public ShimInstaller(IFileSystem fileSystem, LauncherPaths paths,
                         TimeProvider? clock = null, IDataProtector? protector = null)
    {
        _fileSystem = fileSystem ?? throw new ArgumentNullException(nameof(fileSystem));
        _paths = paths ?? throw new ArgumentNullException(nameof(paths));
        _clock = clock ?? TimeProvider.System;
        _protector = protector ?? new DpapiProtector();
    }

    public InstallationManifest? LoadManifest(string gameRoot)
    {
        string current = _paths.InstallationManifestFor(gameRoot);
        if (_fileSystem.FileExists(current))
            return InstallationManifestStore.LoadForGame(
                current, gameRoot, _paths, _fileSystem);

        return InstallationManifestStore.LoadForGame(
            _paths.InstallationManifest, gameRoot, _paths, _fileSystem);
    }

    public InstallResult Install(
        GameCandidate candidate,
        string shimSourcePath,
        string expectedShimSha256,
        byte[] iniContents,
        string launcherVersion,
        string shimVersion)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        ArgumentException.ThrowIfNullOrWhiteSpace(shimSourcePath);
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedShimSha256);
        ArgumentNullException.ThrowIfNull(iniContents);

        BuildCheckResult build = BuildCheck.Check(candidate.GameRoot, _fileSystem);
        if (!build.MayPatch)
        {
            return new InstallResult(
                InstallOutcome.RefusedUnsupportedBuild,
                Detail: DescribeBuild(build));
        }

        if (!_fileSystem.FileExists(shimSourcePath))
        {
            return new InstallResult(InstallOutcome.SourceMissing, Detail: shimSourcePath);
        }

        string sourceHash = Hash(shimSourcePath);
        if (!string.Equals(sourceHash, expectedShimSha256, StringComparison.OrdinalIgnoreCase))
        {
            return new InstallResult(
                InstallOutcome.SourceHashMismatch,
                Detail: $"expected {expectedShimSha256}, found {sourceHash}");
        }

        string gameRoot = LauncherPaths.NormaliseGameRoot(candidate.GameRoot);
        string shimTarget = Path.Combine(gameRoot, ShimIdentity.ShimFileName);
        string iniTarget = Path.Combine(gameRoot, ShimConfiguration.IniFileName);

        using InstallationLock installLock = InstallationLock.TryAcquire(gameRoot);
        if (!installLock.Acquired)
            return new InstallResult(InstallOutcome.Busy, Detail: gameRoot);

        string manifestPath = _paths.InstallationManifestFor(gameRoot);
        InstallationManifest? existingManifest = LoadManifest(gameRoot);
        if (existingManifest is null && HasManifestFor(gameRoot))
            return new InstallResult(InstallOutcome.InvalidInstallationState, Detail: manifestPath);

        ShimIdentityResult existing = ShimIdentity.Identify(
            shimTarget, _fileSystem,
            existingManifest?.File(InstallationManifest.ShimRole)?.InstalledSha256);
        if (!existing.MayReplace)
        {
            return new InstallResult(
                existing.Presence == ShimPresence.Foreign
                    ? InstallOutcome.RefusedForeignShim
                    : InstallOutcome.RefusedUnreadableShim,
                Existing: existing,
                Detail: shimTarget);
        }

        DateTimeOffset now = _clock.GetUtcNow();
        string nonce = Guid.NewGuid().ToString("N");
        string shimStage = shimTarget + ".new." + nonce;
        string iniStage = iniTarget + ".new." + nonce;
        var previous = new Dictionary<string, byte[]?>(StringComparer.OrdinalIgnoreCase);

        try
        {
            _fileSystem.CreateDirectory(_paths.BackupsFor(gameRoot));

            InstalledFile shimRecord = PrepareRecord(
                existingManifest?.File(InstallationManifest.ShimRole),
                InstallationManifest.ShimRole, gameRoot, shimTarget, sourceHash, now);
            string iniHash = Convert.ToHexString(SHA256.HashData(iniContents));
            InstalledFile iniRecord = PrepareRecord(
                existingManifest?.File(InstallationManifest.IniRole),
                InstallationManifest.IniRole, gameRoot, iniTarget, iniHash, now);

            byte[] shimContents = _fileSystem.ReadAllBytes(shimSourcePath);
            previous[shimTarget] = _fileSystem.FileExists(shimTarget)
                ? _fileSystem.ReadAllBytes(shimTarget) : null;
            previous[iniTarget] = _fileSystem.FileExists(iniTarget)
                ? _fileSystem.ReadAllBytes(iniTarget) : null;

            _fileSystem.WriteAllBytes(shimStage, shimContents);
            _fileSystem.WriteAllBytes(iniStage, iniContents);

            _fileSystem.Move(shimStage, shimTarget, overwrite: true);
            _fileSystem.Move(iniStage, iniTarget, overwrite: true);

            var manifest = new InstallationManifest(
                InstallationManifest.CurrentSchema, gameRoot, now,
                launcherVersion, shimVersion, [shimRecord, iniRecord]);
            InstallationManifestStore.Save(manifestPath, manifest, _fileSystem);

            SafeDelete(_paths.InstallationManifest);

            return new InstallResult(InstallOutcome.Installed, manifest, existing);
        }
        catch (Exception exception) when (exception is UnauthorizedAccessException or IOException
                                           or CryptographicException)
        {
            bool rolledBack = RollBack(previous, nonce);
            SafeDelete(shimStage);
            SafeDelete(iniStage);
            return new InstallResult(
                rolledBack ? InstallOutcome.GameFolderNotWritable : InstallOutcome.RollbackFailed,
                Detail: exception.Message);
        }
    }

    public UninstallResult Uninstall(GameCandidate candidate)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        string gameRoot = LauncherPaths.NormaliseGameRoot(candidate.GameRoot);
        using InstallationLock installLock = InstallationLock.TryAcquire(gameRoot);
        if (!installLock.Acquired)
            return new UninstallResult(UninstallOutcome.Busy, [], [], [], gameRoot);

        InstallationManifest? manifest = LoadManifest(gameRoot);

        if (manifest is null)
        {
            return new UninstallResult(
                HasManifestFor(gameRoot) ? UninstallOutcome.InvalidInstallationState
                                         : UninstallOutcome.NothingToRemove,
                [], [], [], gameRoot);
        }

        List<string> removed = [];
        List<string> restored = [];
        List<string> leftAlone = [];

        var restoreBytes = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        foreach (InstalledFile file in manifest.Files)
        {
            if (_fileSystem.FileExists(file.Path) &&
                !string.Equals(Hash(file.Path), file.InstalledSha256, StringComparison.OrdinalIgnoreCase))
            {
                leftAlone.Add(file.Path);
            }
            if (file.PriorState == PriorState.Replaced)
            {
                byte[]? bytes = ReadAndVerifyBackup(file);
                if (bytes is null)
                    return new UninstallResult(
                        UninstallOutcome.BackupMissing, [], [], leftAlone, file.Path);
                restoreBytes[file.Path] = bytes;
            }
        }

        if (leftAlone.Count > 0)
            return new UninstallResult(UninstallOutcome.LeftForeignFile, [], [], leftAlone);

        string nonce = Guid.NewGuid().ToString("N");
        var previous = new Dictionary<string, byte[]?>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (InstalledFile file in manifest.Files)
                previous[file.Path] = _fileSystem.FileExists(file.Path)
                    ? _fileSystem.ReadAllBytes(file.Path) : null;

            foreach (InstalledFile file in manifest.Files)
            {
                if (file.PriorState == PriorState.Absent)
                {
                    if (_fileSystem.FileExists(file.Path)) _fileSystem.Delete(file.Path);
                    removed.Add(file.Path);
                }
                else
                {
                    RestoreBytes(restoreBytes[file.Path], file.Path, nonce);
                    if (!string.Equals(Hash(file.Path), file.PriorSha256,
                                       StringComparison.OrdinalIgnoreCase))
                        throw new IOException("Restored file did not match its recorded hash.");
                    restored.Add(file.Path);
                }
            }

            string currentManifest = _paths.InstallationManifestFor(gameRoot);
            bool currentWasAuthoritative = _fileSystem.FileExists(currentManifest);
            if (currentWasAuthoritative) _fileSystem.Delete(currentManifest);
            if (currentWasAuthoritative)
                SafeDelete(_paths.InstallationManifest);
            else if (_fileSystem.FileExists(_paths.InstallationManifest))
                _fileSystem.Delete(_paths.InstallationManifest);
            foreach (InstalledFile file in manifest.Files)
                if (file.BackupPath is not null) SafeDelete(file.BackupPath);
        }
        catch (Exception exception) when (exception is UnauthorizedAccessException or IOException)
        {
            bool rolledBack = RollBack(previous, nonce);
            return new UninstallResult(
                rolledBack ? UninstallOutcome.GameFolderNotWritable : UninstallOutcome.RollbackFailed,
                removed, restored, leftAlone, exception.Message);
        }

        return new UninstallResult(UninstallOutcome.Removed, removed, restored, leftAlone);
    }

    private InstalledFile PrepareRecord(
        InstalledFile? existing, string role, string gameRoot, string target,
        string contentHash, DateTimeOffset now)
    {
        if (existing is not null)
            return existing with { InstalledSha256 = contentHash };

        if (_fileSystem.FileExists(target))
        {
            byte[] original = _fileSystem.ReadAllBytes(target);
            string priorHash = Convert.ToHexString(SHA256.HashData(original));
            string backupPath = _paths.BackupFor(gameRoot, target, now);
            string backupStage = backupPath + ".new";
            _fileSystem.WriteAllBytes(backupStage, _protector.Protect(original));
            _fileSystem.Move(backupStage, backupPath, overwrite: false);
            return new InstalledFile(
                role, target, contentHash, PriorState.Replaced,
                backupPath, priorHash, BackupProtected: true);
        }

        return new InstalledFile(role, target, contentHash, PriorState.Absent);
    }

    private byte[]? ReadAndVerifyBackup(InstalledFile file)
    {
        if (file.BackupPath is null || !_fileSystem.FileExists(file.BackupPath)) return null;
        try
        {
            byte[] stored = _fileSystem.ReadAllBytes(file.BackupPath);
            byte[]? contents = file.BackupProtected ? _protector.Unprotect(stored) : stored;
            if (contents is null) return null;
            string hash = Convert.ToHexString(SHA256.HashData(contents));
            return string.Equals(hash, file.PriorSha256, StringComparison.OrdinalIgnoreCase)
                ? contents : null;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException
                                           or CryptographicException)
        {
            return null;
        }
    }

    private void RestoreBytes(byte[] contents, string target, string nonce)
    {
        string staging = target + ".restore." + nonce;
        _fileSystem.WriteAllBytes(staging, contents);
        _fileSystem.Move(staging, target, overwrite: true);
    }

    private bool RollBack(IReadOnlyDictionary<string, byte[]?> previous, string nonce)
    {
        try
        {
            foreach ((string target, byte[]? contents) in previous.Reverse())
            {
                if (contents is null)
                {
                    if (_fileSystem.FileExists(target)) _fileSystem.Delete(target);
                }
                else
                {
                    RestoreBytes(contents, target, nonce + ".rollback");
                }
            }
            return true;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private bool HasManifestFor(string gameRoot)
    {
        if (_fileSystem.FileExists(_paths.InstallationManifestFor(gameRoot))) return true;
        if (!_fileSystem.FileExists(_paths.InstallationManifest)) return false;

        InstallationManifest? legacy = InstallationManifestStore.Load(
            _paths.InstallationManifest, _fileSystem);
        if (legacy is null) return true;
        try
        {
            return string.Equals(LauncherPaths.NormaliseGameRoot(legacy.GameRoot),
                                 LauncherPaths.NormaliseGameRoot(gameRoot),
                                 StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception exception) when (exception is ArgumentException or NotSupportedException
                                           or PathTooLongException)
        {
            return true;
        }
    }

    private void SafeDelete(string path)
    {
        try { if (_fileSystem.FileExists(path)) _fileSystem.Delete(path); }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException) { }
    }

    private string Hash(string path)
    {
        using Stream stream = _fileSystem.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    private static string DescribeBuild(BuildCheckResult build) => build.Verdict switch
    {
        BuildVerdict.CardsDllMissing => $"{BuildCheck.CardsDllName} is not in the game folder.",
        BuildVerdict.CardsDllUnreadable => $"{BuildCheck.CardsDllName} could not be read ({build.ReadFailure}).",
        BuildVerdict.UnknownBuild =>
            $"Unmeasured build: {BuildCheck.CardsDllName} TimeDateStamp 0x{build.Headers!.TimeDateStamp:X8}, " +
            $"SizeOfImage 0x{build.Headers.SizeOfImage:X8}.",
        _ => build.Verdict.ToString(),
    };

    private sealed class InstallationLock : IDisposable
    {
        private readonly Mutex _mutex;
        private bool _owned;

        private InstallationLock(Mutex mutex, bool owned)
        {
            _mutex = mutex;
            _owned = owned;
        }

        public bool Acquired => _owned;

        public static InstallationLock TryAcquire(string gameRoot)
        {
            string digest = Convert.ToHexString(SHA256.HashData(
                System.Text.Encoding.UTF8.GetBytes(gameRoot.ToUpperInvariant())))[..24];
            var mutex = new Mutex(false, @"Local\FIFA17Revival.Install." + digest);
            bool owned;
            try { owned = mutex.WaitOne(TimeSpan.Zero); }
            catch (AbandonedMutexException) { owned = true; }
            return new InstallationLock(mutex, owned);
        }

        public void Dispose()
        {
            if (_owned)
            {
                _mutex.ReleaseMutex();
                _owned = false;
            }
            _mutex.Dispose();
        }
    }
}
