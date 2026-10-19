// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Security.Cryptography;
using System.Text.Json;

namespace Revival.Launcher.Core;

public interface IDataProtector
{
    byte[] Protect(byte[] plaintext);

    byte[]? Unprotect(byte[] protectedBlob);
}

public sealed class DpapiProtector : IDataProtector
{
    private static readonly byte[] Entropy =
        System.Text.Encoding.UTF8.GetBytes("FIFA17Revival.Launcher.Profile.v1");

    public byte[] Protect(byte[] plaintext) =>
        ProtectedData.Protect(plaintext, Entropy, DataProtectionScope.CurrentUser);

    public byte[]? Unprotect(byte[] protectedBlob)
    {
        try
        {
            return ProtectedData.Unprotect(protectedBlob, Entropy, DataProtectionScope.CurrentUser);
        }
        catch (CryptographicException)
        {
            return null;
        }
    }
}

public sealed class ProfileStore(IFileSystem fileSystem, LauncherPaths paths, IDataProtector protector)
{
    private readonly IFileSystem _fileSystem =
        fileSystem ?? throw new ArgumentNullException(nameof(fileSystem));

    private readonly LauncherPaths _paths = paths ?? throw new ArgumentNullException(nameof(paths));

    private readonly IDataProtector _protector =
        protector ?? throw new ArgumentNullException(nameof(protector));

    private string Path => System.IO.Path.Combine(_paths.Root, "profile.bin");

    public bool Exists => _fileSystem.FileExists(Path);

    public Invite? Load()
    {
        if (!_fileSystem.FileExists(Path))
        {
            return null;
        }

        try
        {
            byte[]? plaintext = _protector.Unprotect(_fileSystem.ReadAllBytes(Path));
            if (plaintext is null)
            {
                return null;
            }

            Stored? stored = JsonSerializer.Deserialize<Stored>(plaintext);
            if (stored?.Code is null)
            {
                return null;
            }

            return InviteCode.TryParse(stored.Code, out Invite? invite, out _) ? invite : null;
        }
        catch (Exception exception)
            when (exception is JsonException or IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    public void Save(Invite invite)
    {
        ArgumentNullException.ThrowIfNull(invite);

        _fileSystem.CreateDirectory(_paths.Root);

        byte[] plaintext = JsonSerializer.SerializeToUtf8Bytes(
            new Stored { Code = InviteCode.Create(invite) });

        string staging = Path + ".new";
        _fileSystem.WriteAllBytes(staging, _protector.Protect(plaintext));
        _fileSystem.Move(staging, Path, overwrite: true);
    }

    public void Clear()
    {
        if (_fileSystem.FileExists(Path))
        {
            _fileSystem.Delete(Path);
        }
    }

    private sealed class Stored
    {
        public string? Code { get; set; }
    }
}
