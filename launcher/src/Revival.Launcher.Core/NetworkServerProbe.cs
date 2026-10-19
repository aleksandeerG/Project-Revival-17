// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Text.Json;

namespace Revival.Launcher.Core;

public sealed class NetworkServerProbe : IServerProbe, IDisposable
{
    private readonly HttpClient _http;
    private readonly string _certificatePin;

    public NetworkServerProbe(string certificatePin, HttpMessageHandler? handler = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(certificatePin);
        _certificatePin = KnockClient.Normalise(certificatePin);

        _http = new HttpClient(
            handler ?? KnockClient.CreatePinnedHandler(certificatePin), disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(8),
        };
    }

    public static readonly TimeSpan ConnectTimeout = TimeSpan.FromSeconds(5);

    public async Task<bool> ResolvesAsync(string host, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(host))
        {
            return false;
        }

        if (IPAddress.TryParse(host, out _))
        {
            return true;
        }

        try
        {
            IPAddress[] addresses = await Dns
                .GetHostAddressesAsync(host, cancellationToken).ConfigureAwait(false);
            return addresses.Length > 0;
        }
        catch (Exception exception) when (exception is SocketException or ArgumentException)
        {
            return false;
        }
    }

    public async Task<bool> CanConnectAsync(string host, int port, CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(ConnectTimeout);

        try
        {
            using var client = new TcpClient();
            await client.ConnectAsync(host, port, timeout.Token).ConfigureAwait(false);
            await using var tls = new SslStream(
                client.GetStream(),
                leaveInnerStreamOpen: false,
                (_, certificate, _, _) => certificate is not null &&
                    KnockClient.Matches(certificate, _certificatePin));
            await tls.AuthenticateAsClientAsync(
                new SslClientAuthenticationOptions
                {
                    TargetHost = host,
                    CertificateRevocationCheckMode =
                        System.Security.Cryptography.X509Certificates.X509RevocationMode.NoCheck,
                },
                timeout.Token).ConfigureAwait(false);
            return tls.IsAuthenticated;
        }
        catch (Exception exception)
            when (exception is SocketException or IOException or AuthenticationException
                      or OperationCanceledException or ArgumentException)
        {
            return false;
        }
    }

    public async Task<(bool Ready, string? Detail)> ReadyAsync(
        string host, int port, CancellationToken cancellationToken)
    {
        try
        {
            Uri endpoint = ServerEndpoint.HttpOrHttps(host, port, "/readyz");
            using HttpResponseMessage response =
                await _http.GetAsync(endpoint, cancellationToken).ConfigureAwait(false);

            string body = await response.Content
                .ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

            return response.IsSuccessStatusCode
                ? (true, null)
                : (false, DescribeFailures(body) ?? $"HTTP {(int)response.StatusCode}");
        }
        catch (Exception exception)
            when (exception is HttpRequestException or TaskCanceledException
                      or ArgumentException or UriFormatException)
        {
            return (false, exception.Message);
        }
    }

    public async Task<AccountProbeResult> ValidateAccountAsync(
        string host, int port, string username, string password,
        CancellationToken cancellationToken)
    {
        try
        {
            Uri endpoint = ServerEndpoint.HttpOrHttps(host, port, "/accounts/validate");
            using ByteArrayContent content = FixedLengthJsonContent.Create(
                new { username, password });
            using HttpResponseMessage response = await _http.PostAsync(
                endpoint, content, cancellationToken).ConfigureAwait(false);
            return response.StatusCode switch
            {
                HttpStatusCode.OK => AccountProbeResult.Valid,
                HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden => AccountProbeResult.Invalid,
                HttpStatusCode.TooManyRequests => AccountProbeResult.Throttled,
                _ => AccountProbeResult.Unreachable,
            };
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException
                                           or ArgumentException or UriFormatException)
        {
            return AccountProbeResult.Unreachable;
        }
    }

    private static string? DescribeFailures(string body)
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(body);
            if (!document.RootElement.TryGetProperty("failures", out JsonElement failures) ||
                failures.ValueKind != JsonValueKind.Array)
            {
                return null;
            }

            string[] reasons = failures.EnumerateArray()
                .Select(entry => entry.GetString())
                .Where(reason => !string.IsNullOrWhiteSpace(reason))
                .Select(reason => reason!)
                .ToArray();

            return reasons.Length > 0 ? string.Join("; ", reasons) : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    public void Dispose() => _http.Dispose();
}

public sealed class WindowsProcessProbe : IProcessProbe
{
    public bool IsRunning(string processName)
    {
        try
        {
            System.Diagnostics.Process[] found =
                System.Diagnostics.Process.GetProcessesByName(processName);

            try
            {
                return found.Length > 0;
            }
            finally
            {
                foreach (System.Diagnostics.Process process in found)
                {
                    process.Dispose();
                }
            }
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }
}
