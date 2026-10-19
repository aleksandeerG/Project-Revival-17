// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Windows;
using System.Windows.Media;
using Revival.Launcher.Core;

namespace Revival.Launcher.App;

public sealed class CheckRow
{
    public CheckRow(CheckResult result)
    {
        ArgumentNullException.ThrowIfNull(result);

        Message = result.Message;
        Detail = result.Detail ?? string.Empty;
        DetailVisibility = string.IsNullOrWhiteSpace(result.Detail)
            ? Visibility.Collapsed
            : Visibility.Visible;

        (Glyph, Brush) = result.State switch
        {
            CheckState.Passed => ("✓", Colour("#1E7B34")),
            CheckState.Warned => ("!", Colour("#9A6400")),
            CheckState.Blocked => ("✕", Colour("#B3261E")),
            _ => ("–", Colour("#5C6670")),
        };
    }

    public string Glyph { get; }

    public Brush Brush { get; }

    public string Message { get; }

    public string Detail { get; }

    public Visibility DetailVisibility { get; }

    private static Brush Colour(string hex)
    {
        var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        brush.Freeze();
        return brush;
    }
}
