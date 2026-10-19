// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Net;

namespace Revival.Launcher.Core;

public static class ServerEndpoint
{
    private const int MaximumDnsNameLength = 253;

    public static bool IsValidHost(string host)
    {
        if (string.IsNullOrWhiteSpace(host) || host != host.Trim() ||
            host.Contains('%', StringComparison.Ordinal) ||
            host.Any(character => character > 0x7f || char.IsControl(character)))
            return false;

        if (IPAddress.TryParse(host, out IPAddress? address))
        {
            if (address.Equals(IPAddress.Any) || address.Equals(IPAddress.IPv6Any) ||
                address.IsIPv6Multicast)
                return false;
            byte first = address.GetAddressBytes()[0];
            return address.AddressFamily != System.Net.Sockets.AddressFamily.InterNetwork ||
                   first is < 224 or > 239;
        }
        if (host.Length > MaximumDnsNameLength)
            return false;

        string dnsName = host.EndsWith(".", StringComparison.Ordinal) ? host[..^1] : host;
        if (dnsName.Length == 0)
            return false;

        foreach (string label in dnsName.Split('.'))
        {
            if (label.Length is < 1 or > 63 || !IsAsciiLetterOrDigit(label[0]) ||
                !IsAsciiLetterOrDigit(label[^1]) ||
                label.Any(character => !IsAsciiLetterOrDigit(character) && character != '-'))
                return false;
        }
        return true;
    }

    public static Uri Https(string host, int port, string path) => Build("https", host, port, path);

    public static Uri HttpOrHttps(string host, int port, string path)
    {
        string scheme = IPAddress.TryParse(host, out IPAddress? address) && IPAddress.IsLoopback(address)
            ? "http" : "https";
        return Build(scheme, host, port, path);
    }

    private static Uri Build(string scheme, string host, int port, string path)
    {
        if (!IsValidHost(host)) throw new ArgumentException("Invalid server host.", nameof(host));
        if (port is < 1 or > 65535) throw new ArgumentOutOfRangeException(nameof(port));
        return new UriBuilder(scheme, host, port, path).Uri;
    }

    private static bool IsAsciiLetterOrDigit(char character) =>
        character is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9';
}
