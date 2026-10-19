// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public interface IFileSystem
{
    bool FileExists(string path);

    bool DirectoryExists(string path);

    bool IsReparsePoint(string path);

    Stream OpenRead(string path);

    byte[] ReadAllBytes(string path);

    void CreateDirectory(string path);

    void WriteAllBytes(string path, byte[] contents);

    void Copy(string source, string destination, bool overwrite);

    void Move(string source, string destination, bool overwrite);

    void Delete(string path);

    IReadOnlyList<string> ListFiles(string directory, string searchPattern);
}

public sealed class WindowsFileSystem : IFileSystem
{
    public static WindowsFileSystem Instance { get; } = new();

    public bool FileExists(string path) => File.Exists(path);

    public bool DirectoryExists(string path) => Directory.Exists(path);

    public bool IsReparsePoint(string path)
    {
        try
        {
            return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return true;
        }
    }

    public Stream OpenRead(string path) =>
        new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite, bufferSize: 4096);

    public byte[] ReadAllBytes(string path) => File.ReadAllBytes(path);

    public void CreateDirectory(string path) => Directory.CreateDirectory(path);

    public void WriteAllBytes(string path, byte[] contents) => File.WriteAllBytes(path, contents);

    public void Copy(string source, string destination, bool overwrite) =>
        File.Copy(source, destination, overwrite);

    public void Move(string source, string destination, bool overwrite) =>
        File.Move(source, destination, overwrite);

    public void Delete(string path) => File.Delete(path);

    public IReadOnlyList<string> ListFiles(string directory, string searchPattern) =>
        Directory.Exists(directory)
            ? Directory.GetFiles(directory, searchPattern)
            : [];
}
