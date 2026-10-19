// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json.Serialization;

namespace Revival.Launcher.Core;

public enum KnockOutcome
{
    Enrolled,

    Unauthorized,

    Throttled,

    Unreachable,

    CertificateRejected,

    UnexpectedResponse,
}

public sealed record KnockResult(
    KnockOutcome Outcome,
    TimeSpan? ExpiresIn = null,
    string? LauncherVersion = null,
    string? MinimumLauncherVersion = null,
    string? ServerVersion = null,
    string? ProtocolVersion = null,
    string? ContentVersion = null,
    string? Detail = null)
{
    public bool Succeeded => Outcome == KnockOutcome.Enrolled;
}

public sealed class KnockClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly string _launcherVersion;

    public KnockClient(string certificatePin, string launcherVersion, HttpMessageHandler? handler = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(certificatePin);
        _launcherVersion = launcherVersion ?? string.Empty;

        _http = new HttpClient(handler ?? CreatePinnedHandler(certificatePin), disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
    }

    public static HttpMessageHandler CreatePinnedHandler(string certificatePin)
    {
        string expected = Normalise(certificatePin);

        return new SocketsHttpHandler
        {
            SslOptions =
            {
                RemoteCertificateValidationCallback = (_, certificate, _, _) =>
                    certificate is not null && Matches(certificate, expected),
            },
            PooledConnectionLifetime = TimeSpan.FromMinutes(2),
        };
    }

    internal static bool Matches(X509Certificate certificate, string expected)
    {
        byte[] der = certificate.Export(X509ContentType.Cert);
        string actual = Convert.ToHexString(SHA256.HashData(der));

        return CryptographicOperations.FixedTimeEquals(
            System.Text.Encoding.ASCII.GetBytes(actual),
            System.Text.Encoding.ASCII.GetBytes(expected));
    }

    internal static string Normalise(string pin) =>
        pin.Replace(":", "", StringComparison.Ordinal).Trim().ToUpperInvariant();

    public async Task<KnockResult> KnockAsync(
        string host, int port, string enrollmentToken, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(host);
        ArgumentException.ThrowIfNullOrWhiteSpace(enrollmentToken);

        try
        {
            Uri endpoint = ServerEndpoint.Https(host, port, "/knock");
            using ByteArrayContent content = FixedLengthJsonContent.Create(
                new Request { Token = enrollmentToken, Version = _launcherVersion });
            using HttpResponseMessage response = await _http
                .PostAsync(endpoint, content, cancellationToken)
                .ConfigureAwait(false);

            return await InterpretAsync(response, cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception) when (IsCertificateFailure(exception))
        {
            return new KnockResult(KnockOutcome.CertificateRejected, Detail: exception.Message);
        }
        catch (HttpRequestException exception)
        {
            return new KnockResult(KnockOutcome.Unreachable, Detail: exception.Message);
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return new KnockResult(KnockOutcome.Unreachable, Detail: "timed out");
        }
        catch (Exception exception) when (exception is ArgumentException or UriFormatException)
        {
            return new KnockResult(KnockOutcome.Unreachable, Detail: exception.Message);
        }
    }

    private static async Task<KnockResult> InterpretAsync(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        switch (response.StatusCode)
        {
            case HttpStatusCode.OK:
                break;

            case HttpStatusCode.Unauthorized:
                return new KnockResult(KnockOutcome.Unauthorized);

            case HttpStatusCode.TooManyRequests:
                return new KnockResult(KnockOutcome.Throttled);

            case HttpStatusCode.NotFound:
                return new KnockResult(
                    KnockOutcome.Unauthorized, Detail: "the endpoint is not accepting knocks");

            default:
                return new KnockResult(
                    KnockOutcome.UnexpectedResponse, Detail: $"HTTP {(int)response.StatusCode}");
        }

        Reply? reply;
        try
        {
            reply = await response.Content
                .ReadFromJsonAsync<Reply>(cancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is System.Text.Json.JsonException or HttpRequestException)
        {
            return new KnockResult(KnockOutcome.UnexpectedResponse, Detail: "unreadable response");
        }

        if (reply is null || reply.ExpiresIn <= 0)
        {
            return new KnockResult(KnockOutcome.UnexpectedResponse, Detail: "no lease returned");
        }

        return new KnockResult(
            KnockOutcome.Enrolled,
            TimeSpan.FromSeconds(reply.ExpiresIn),
            reply.LauncherVersion,
            reply.MinimumLauncherVersion,
            reply.ServerVersion,
            reply.ProtocolVersion,
            reply.ContentVersion);
    }

    private static bool IsCertificateFailure(HttpRequestException exception)
    {
        for (Exception? inner = exception; inner is not null; inner = inner.InnerException)
        {
            if (inner is System.Security.Authentication.AuthenticationException)
            {
                return true;
            }
        }

        return false;
    }

    public void Dispose() => _http.Dispose();

    private sealed class Request
    {
        [JsonPropertyName("token")] public string Token { get; set; } = string.Empty;

        [JsonPropertyName("version")] public string Version { get; set; } = string.Empty;
    }

    private sealed class Reply
    {
        [JsonPropertyName("expiresIn")] public int ExpiresIn { get; set; }
        [JsonPropertyName("launcherVersion")] public string? LauncherVersion { get; set; }
        [JsonPropertyName("minimumLauncherVersion")] public string? MinimumLauncherVersion { get; set; }
        [JsonPropertyName("serverVersion")] public string? ServerVersion { get; set; }
        [JsonPropertyName("protocolVersion")] public string? ProtocolVersion { get; set; }
        [JsonPropertyName("contentVersion")] public string? ContentVersion { get; set; }
    }
}
