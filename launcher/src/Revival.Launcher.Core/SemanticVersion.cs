// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public static class SemanticVersion
{
    public static bool IsOlder(string? candidate, string? other)
    {
        if (!TryParse(candidate, out int[] left) || !TryParse(other, out int[] right))
        {
            return false;
        }

        int length = Math.Max(left.Length, right.Length);
        for (int index = 0; index < length; index++)
        {
            int a = index < left.Length ? left[index] : 0;
            int b = index < right.Length ? right[index] : 0;

            if (a != b)
            {
                return a < b;
            }
        }

        return false;
    }

    private static bool TryParse(string? value, out int[] parts)
    {
        parts = [];
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        string core = value.Trim().Split('-', '+')[0];
        string[] fields = core.Split('.');
        int[] parsed = new int[fields.Length];

        for (int index = 0; index < fields.Length; index++)
        {
            if (!int.TryParse(fields[index], out parsed[index]) || parsed[index] < 0)
            {
                return false;
            }
        }

        parts = parsed;
        return true;
    }
}
