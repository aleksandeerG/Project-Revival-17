// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Revival.Launcher.Core;

public sealed record Invite(
    string ProfileName,
    ServerProfile Server,
    int KnockPort,
    string EnrollmentToken,
    string Username,
    string Password,
    string CertificatePin);

public enum InviteParseError
{
    None = 0,
    Empty,
    WrongPrefix,
    NotBase64,
    NotJson,
    UnsupportedVersion,
    HostMissing,
    HostTooLong,
    HostInvalid,
    PortOutOfRange,
    TokenMissing,
    CredentialMissing,
    CredentialContainsNewline,

    PinMissingOrMalformed,
}

public static class InviteCode
{
    public const string Prefix = "FUT1-";

    private const int SupportedVersion = 1;
    public const int MaximumCodeLength = 16 * 1024;
    private const int MaximumSecretLength = 512;
    private const int MaximumProfileLength = 128;

    private static readonly JsonSerializerOptions Options = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static string Create(Invite invite)
    {
        ArgumentNullException.ThrowIfNull(invite);

        var payload = new Payload
        {
            Version = SupportedVersion,
            Name = invite.ProfileName,
            Host = invite.Server.Host,
            Redirector = invite.Server.RedirectorPort,
            Accounts = invite.Server.AccountsPort,
            Blaze = invite.Server.BlazePort,
            Fut = invite.Server.FutPort,
            Cdn = invite.Server.CdnPort,
            Knock = invite.KnockPort,
            Token = invite.EnrollmentToken,
            User = invite.Username,
            Password = invite.Password,
            Pin = invite.CertificatePin,
        };

        return Prefix + ToBase64Url(JsonSerializer.SerializeToUtf8Bytes(payload, Options));
    }

    public static bool TryParse(string? code, out Invite? invite, out InviteParseError error)
    {
        invite = null;

        if (string.IsNullOrWhiteSpace(code))
        {
            error = InviteParseError.Empty;
            return false;
        }

        if (code.Length > MaximumCodeLength)
        {
            error = InviteParseError.NotBase64;
            return false;
        }

        string trimmed = new(code.Where(character => !char.IsWhiteSpace(character)).ToArray());

        if (!trimmed.StartsWith(Prefix, StringComparison.OrdinalIgnoreCase))
        {
            error = InviteParseError.WrongPrefix;
            return false;
        }

        if (!TryFromBase64Url(trimmed[Prefix.Length..], out byte[] json))
        {
            error = InviteParseError.NotBase64;
            return false;
        }

        Payload? payload;
        try
        {
            payload = JsonSerializer.Deserialize<Payload>(json, Options);
        }
        catch (JsonException)
        {
            error = InviteParseError.NotJson;
            return false;
        }

        if (payload is null)
        {
            error = InviteParseError.NotJson;
            return false;
        }

        if (payload.Version != SupportedVersion)
        {
            error = InviteParseError.UnsupportedVersion;
            return false;
        }

        if (string.IsNullOrWhiteSpace(payload.Host))
        {
            error = InviteParseError.HostMissing;
            return false;
        }

        if (Encoding.UTF8.GetByteCount(payload.Host) > ShimConfiguration.MaxHostLength)
        {
            error = InviteParseError.HostTooLong;
            return false;
        }

        if (!ServerEndpoint.IsValidHost(payload.Host))
        {
            error = InviteParseError.HostInvalid;
            return false;
        }

        int[] ports =
        [
            payload.Redirector, payload.Accounts, payload.Blaze,
            payload.Fut, payload.Cdn, payload.Knock,
        ];

        if (ports.Any(port => port is < 1 or > 65535))
        {
            error = InviteParseError.PortOutOfRange;
            return false;
        }

        if (string.IsNullOrWhiteSpace(payload.Token) || payload.Token.Length > MaximumSecretLength)
        {
            error = InviteParseError.TokenMissing;
            return false;
        }

        if (string.IsNullOrEmpty(payload.User) || string.IsNullOrEmpty(payload.Password) ||
            payload.User.Length > MaximumSecretLength || payload.Password.Length > MaximumSecretLength)
        {
            error = InviteParseError.CredentialMissing;
            return false;
        }

        if (HasNewline(payload.User) || HasNewline(payload.Password))
        {
            error = InviteParseError.CredentialContainsNewline;
            return false;
        }

        string pin = (payload.Pin ?? string.Empty).Replace(":", "", StringComparison.Ordinal).Trim();
        if (pin.Length != 64 || !pin.All(Uri.IsHexDigit))
        {
            error = InviteParseError.PinMissingOrMalformed;
            return false;
        }

        invite = new Invite(
            ProfileName: string.IsNullOrWhiteSpace(payload.Name) ? "Friends Server"
                : payload.Name[..Math.Min(payload.Name.Length, MaximumProfileLength)],
            Server: new ServerProfile(
                payload.Host, payload.Redirector, payload.Accounts,
                payload.Blaze, payload.Fut, payload.Cdn),
            KnockPort: payload.Knock,
            EnrollmentToken: payload.Token,
            Username: payload.User,
            Password: payload.Password,
            CertificatePin: pin.ToUpperInvariant());

        error = InviteParseError.None;
        return true;
    }

    private static bool HasNewline(string value) =>
        value.Contains('\n', StringComparison.Ordinal) ||
        value.Contains('\r', StringComparison.Ordinal);

    private static string ToBase64Url(byte[] value) =>
        Convert.ToBase64String(value).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static bool TryFromBase64Url(string value, out byte[] decoded)
    {
        decoded = [];
        if (value.Length == 0)
        {
            return false;
        }

        string padded = value.Replace('-', '+').Replace('_', '/');
        padded += (padded.Length % 4) switch
        {
            2 => "==",
            3 => "=",
            0 => "",
            _ => null!,
        } ?? string.Empty;

        if (padded.Length % 4 != 0)
        {
            return false;
        }

        try
        {
            decoded = Convert.FromBase64String(padded);
            return decoded.Length > 0;
        }
        catch (FormatException)
        {
            return false;
        }
    }

    private sealed class Payload
    {
        [JsonPropertyName("v")] public int Version { get; set; }
        [JsonPropertyName("name")] public string? Name { get; set; }
        [JsonPropertyName("host")] public string? Host { get; set; }
        [JsonPropertyName("red")] public int Redirector { get; set; }
        [JsonPropertyName("acc")] public int Accounts { get; set; }
        [JsonPropertyName("blz")] public int Blaze { get; set; }
        [JsonPropertyName("fut")] public int Fut { get; set; }
        [JsonPropertyName("cdn")] public int Cdn { get; set; }
        [JsonPropertyName("knock")] public int Knock { get; set; }
        [JsonPropertyName("token")] public string? Token { get; set; }
        [JsonPropertyName("user")] public string? User { get; set; }
        [JsonPropertyName("pass")] public string? Password { get; set; }
        [JsonPropertyName("pin")] public string? Pin { get; set; }
    }
}
