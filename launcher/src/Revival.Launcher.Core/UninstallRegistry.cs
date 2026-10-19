// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using Microsoft.Win32;

namespace Revival.Launcher.Core;

public sealed record UninstallEntry(
    string? DisplayName,
    string? Publisher,
    string? DisplayVersion,
    string? DisplayIcon,
    string? InstallLocation,
    string Source);

public interface IUninstallRegistry
{
    IEnumerable<UninstallEntry> Enumerate();
}

public sealed class WindowsUninstallRegistry : IUninstallRegistry
{
    private const string UninstallSubKey =
        @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall";

    private static readonly (RegistryHive Hive, RegistryView View)[] Locations =
    [
        (RegistryHive.LocalMachine, RegistryView.Registry64),
        (RegistryHive.LocalMachine, RegistryView.Registry32),
        (RegistryHive.CurrentUser, RegistryView.Registry64),
        (RegistryHive.CurrentUser, RegistryView.Registry32),
    ];

    public IEnumerable<UninstallEntry> Enumerate()
    {
        foreach ((RegistryHive hive, RegistryView view) in Locations)
        {
            foreach (UninstallEntry entry in EnumerateLocation(hive, view))
            {
                yield return entry;
            }
        }
    }

    private static IEnumerable<UninstallEntry> EnumerateLocation(RegistryHive hive, RegistryView view)
    {
        RegistryKey? root = null;
        RegistryKey? uninstall = null;
        try
        {
            root = RegistryKey.OpenBaseKey(hive, view);
            uninstall = root.OpenSubKey(UninstallSubKey);
        }
        catch (Exception exception) when (IsRegistryFailure(exception))
        {
            root?.Dispose();
            yield break;
        }

        using (root)
        using (uninstall)
        {
            if (uninstall is null)
            {
                yield break;
            }

            string source = $"{hive}\\{UninstallSubKey} ({view})";
            string[] names;
            try
            {
                names = uninstall.GetSubKeyNames();
            }
            catch (Exception exception) when (IsRegistryFailure(exception))
            {
                yield break;
            }

            foreach (string name in names)
            {
                UninstallEntry? entry = ReadEntry(uninstall, name, source);
                if (entry is not null)
                {
                    yield return entry;
                }
            }
        }
    }

    private static UninstallEntry? ReadEntry(RegistryKey uninstall, string name, string source)
    {
        try
        {
            using RegistryKey? key = uninstall.OpenSubKey(name);
            if (key is null)
            {
                return null;
            }

            return new UninstallEntry(
                DisplayName: key.GetValue("DisplayName") as string,
                Publisher: key.GetValue("Publisher") as string,
                DisplayVersion: key.GetValue("DisplayVersion") as string,
                DisplayIcon: key.GetValue("DisplayIcon") as string,
                InstallLocation: key.GetValue("InstallLocation") as string,
                Source: source);
        }
        catch (Exception exception) when (IsRegistryFailure(exception))
        {
            return null;
        }
    }

    private static bool IsRegistryFailure(Exception exception) =>
        exception is System.Security.SecurityException
            or UnauthorizedAccessException
            or IOException;
}
