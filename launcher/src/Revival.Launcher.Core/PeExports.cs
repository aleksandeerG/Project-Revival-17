// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
using System.Text;

namespace Revival.Launcher.Core;

public enum PeExportReadFailure
{
    None = 0,
    NotAPeImage,
    ImageTooLarge,
    NoExportDirectory,
    MalformedExportDirectory,
}

public static class PeExports
{
    public const int MaxImageBytes = 64 * 1024 * 1024;

    private const uint MaxExportNames = 65_536;

    private const int SectionHeaderLength = 40;
    private const ushort Pe32Magic = 0x010B;
    private const ushort Pe32PlusMagic = 0x020B;

    private const int Pe32NumberOfRvaAndSizesOffset = 92;
    private const int Pe32PlusNumberOfRvaAndSizesOffset = 108;

    public static bool TryReadNames(
        ReadOnlySpan<byte> image,
        out IReadOnlyList<string> names,
        out PeExportReadFailure failure)
    {
        names = [];

        if (image.Length > MaxImageBytes)
        {
            failure = PeExportReadFailure.ImageTooLarge;
            return false;
        }

        if (!TryLocateHeaders(image, out int peOffset, out bool isPe32Plus,
                              out ushort sectionCount, out ushort optionalHeaderSize))
        {
            failure = PeExportReadFailure.NotAPeImage;
            return false;
        }

        int optionalHeader = peOffset + 4 + 20;
        int rvaCountOffset = optionalHeader +
            (isPe32Plus ? Pe32PlusNumberOfRvaAndSizesOffset : Pe32NumberOfRvaAndSizesOffset);

        if (!TryReadUInt32(image, rvaCountOffset, out uint directoryCount) || directoryCount == 0)
        {
            failure = PeExportReadFailure.NoExportDirectory;
            return false;
        }

        int exportDirectoryEntry = rvaCountOffset + 4;
        if (!TryReadUInt32(image, exportDirectoryEntry, out uint exportRva) || exportRva == 0)
        {
            failure = PeExportReadFailure.NoExportDirectory;
            return false;
        }

        int sectionTable = optionalHeader + optionalHeaderSize;
        if (!TryReadSections(image, sectionTable, sectionCount, out Section[] sections))
        {
            failure = PeExportReadFailure.MalformedExportDirectory;
            return false;
        }

        if (!TryMapRva(sections, exportRva, out int exportOffset) ||
            !TryReadUInt32(image, exportOffset + 24, out uint nameCount) ||
            !TryReadUInt32(image, exportOffset + 32, out uint namePointerRva))
        {
            failure = PeExportReadFailure.MalformedExportDirectory;
            return false;
        }

        if (nameCount == 0)
        {
            failure = PeExportReadFailure.None;
            return true;
        }

        if (nameCount > MaxExportNames || !TryMapRva(sections, namePointerRva, out int nameTable))
        {
            failure = PeExportReadFailure.MalformedExportDirectory;
            return false;
        }

        List<string> collected = new((int)nameCount);
        for (uint index = 0; index < nameCount; index++)
        {
            long entry = (long)nameTable + ((long)index * 4);
            if (entry > int.MaxValue ||
                !TryReadUInt32(image, (int)entry, out uint nameRva) ||
                !TryMapRva(sections, nameRva, out int nameOffset) ||
                !TryReadAsciiZ(image, nameOffset, out string name))
            {
                failure = PeExportReadFailure.MalformedExportDirectory;
                return false;
            }

            collected.Add(name);
        }

        names = collected;
        failure = PeExportReadFailure.None;
        return true;
    }

    public static bool TryReadNamesFromFile(
        string path,
        IFileSystem fileSystem,
        out IReadOnlyList<string> names,
        out PeExportReadFailure failure)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(fileSystem);

        names = [];
        try
        {
            using Stream stream = fileSystem.OpenRead(path);
            using var buffer = new MemoryStream();
            stream.CopyTo(buffer, 81_920);
            if (buffer.Length > MaxImageBytes)
            {
                failure = PeExportReadFailure.ImageTooLarge;
                return false;
            }

            return TryReadNames(buffer.GetBuffer().AsSpan(0, (int)buffer.Length), out names, out failure);
        }
        catch (Exception exception)
            when (exception is IOException or UnauthorizedAccessException or OutOfMemoryException)
        {
            failure = PeExportReadFailure.NotAPeImage;
            return false;
        }
    }

    private readonly record struct Section(uint VirtualAddress, uint VirtualSize, uint RawAddress, uint RawSize);

    private static bool TryLocateHeaders(
        ReadOnlySpan<byte> image,
        out int peOffset,
        out bool isPe32Plus,
        out ushort sectionCount,
        out ushort optionalHeaderSize)
    {
        peOffset = 0;
        isPe32Plus = false;
        sectionCount = 0;
        optionalHeaderSize = 0;

        if (image.Length < 0x40 ||
            image[0] != (byte)'M' || image[1] != (byte)'Z' ||
            !TryReadUInt32(image, 0x3C, out uint rawOffset))
        {
            return false;
        }

        if (rawOffset > int.MaxValue)
        {
            return false;
        }

        peOffset = (int)rawOffset;
        if (peOffset < 0 ||
            !TryReadUInt32(image, peOffset, out uint signature) || signature != 0x0000_4550 ||
            !TryReadUInt16(image, peOffset + 6, out sectionCount) ||
            !TryReadUInt16(image, peOffset + 20, out optionalHeaderSize) ||
            !TryReadUInt16(image, peOffset + 24, out ushort magic))
        {
            return false;
        }

        isPe32Plus = magic == Pe32PlusMagic;
        return magic is Pe32Magic or Pe32PlusMagic;
    }

    private static bool TryReadSections(
        ReadOnlySpan<byte> image, int tableOffset, ushort count, out Section[] sections)
    {
        sections = [];
        if (count == 0)
        {
            return false;
        }

        long end = (long)tableOffset + ((long)count * SectionHeaderLength);
        if (tableOffset < 0 || end > image.Length)
        {
            return false;
        }

        Section[] parsed = new Section[count];
        for (int index = 0; index < count; index++)
        {
            int at = tableOffset + (index * SectionHeaderLength);
            if (!TryReadUInt32(image, at + 8, out uint virtualSize) ||
                !TryReadUInt32(image, at + 12, out uint virtualAddress) ||
                !TryReadUInt32(image, at + 16, out uint rawSize) ||
                !TryReadUInt32(image, at + 20, out uint rawAddress))
            {
                return false;
            }

            parsed[index] = new Section(virtualAddress, virtualSize, rawAddress, rawSize);
        }

        sections = parsed;
        return true;
    }

    private static bool TryMapRva(Section[] sections, uint rva, out int offset)
    {
        offset = 0;
        foreach (Section section in sections)
        {
            uint span = Math.Max(section.VirtualSize, section.RawSize);
            if (span == 0 || rva < section.VirtualAddress || rva >= section.VirtualAddress + span)
            {
                continue;
            }

            uint delta = rva - section.VirtualAddress;
            if (delta >= section.RawSize)
            {
                return false;
            }

            long mapped = (long)section.RawAddress + delta;
            if (mapped > int.MaxValue)
            {
                return false;
            }

            offset = (int)mapped;
            return true;
        }

        return false;
    }

    private static bool TryReadAsciiZ(ReadOnlySpan<byte> image, int offset, out string value)
    {
        value = string.Empty;
        if (offset < 0 || offset >= image.Length)
        {
            return false;
        }

        int limit = Math.Min(image.Length, offset + 512);
        for (int at = offset; at < limit; at++)
        {
            if (image[at] == 0)
            {
                value = Encoding.ASCII.GetString(image[offset..at]);
                return true;
            }
        }

        return false;
    }

    private static bool TryReadUInt16(ReadOnlySpan<byte> image, int offset, out ushort value)
    {
        value = 0;
        if (offset < 0 || offset + 2 > image.Length)
        {
            return false;
        }

        value = (ushort)(image[offset] | (image[offset + 1] << 8));
        return true;
    }

    private static bool TryReadUInt32(ReadOnlySpan<byte> image, int offset, out uint value)
    {
        value = 0;
        if (offset < 0 || offset + 4 > image.Length)
        {
            return false;
        }

        value = (uint)(image[offset]
                       | (image[offset + 1] << 8)
                       | (image[offset + 2] << 16)
                       | (image[offset + 3] << 24));
        return true;
    }
}
