// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Net.Http.Headers;
using System.Text.Json;

namespace Revival.Launcher.Core;

internal static class FixedLengthJsonContent
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    public static ByteArrayContent Create<T>(T value)
    {
        byte[] payload = JsonSerializer.SerializeToUtf8Bytes(value, Options);
        var content = new ByteArrayContent(payload);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json")
        {
            CharSet = "utf-8",
        };
        return content;
    }
}
