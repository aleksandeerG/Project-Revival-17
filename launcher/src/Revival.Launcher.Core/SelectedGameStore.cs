// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public sealed class SelectedGameStore(IFileSystem fileSystem, LauncherPaths paths)
{
    private readonly IFileSystem _fileSystem = fileSystem;
    private readonly LauncherPaths _paths = paths;

    public string? Load()
    {
        try
        {
            if (!_fileSystem.FileExists(_paths.SelectedGame)) return null;
            string value = System.Text.Encoding.UTF8
                .GetString(_fileSystem.ReadAllBytes(_paths.SelectedGame)).Trim();
            return string.IsNullOrWhiteSpace(value) ? null : Path.GetFullPath(value);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException
                                           or ArgumentException or NotSupportedException)
        {
            return null;
        }
    }

    public void Save(string executablePath)
    {
        string full = Path.GetFullPath(executablePath);
        _fileSystem.CreateDirectory(_paths.Root);
        string staging = _paths.SelectedGame + ".new";
        _fileSystem.WriteAllBytes(staging, System.Text.Encoding.UTF8.GetBytes(full));
        _fileSystem.Move(staging, _paths.SelectedGame, overwrite: true);
    }
}
