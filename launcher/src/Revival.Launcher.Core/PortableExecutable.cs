// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
namespace Revival.Launcher.Core;

public sealed record PeHeaders(uint TimeDateStamp, uint SizeOfImage, ushort Machine, bool IsPe32Plus);

public enum PeReadFailure
{
    None = 0,
    FileTooShort,
    NotMzImage,
    HeaderOffsetOutOfRange,
    NotPeImage,
    OptionalHeaderTooSmall,
    UnknownOptionalHeaderMagic,
}

public static class PortableExecutable
{
    private const int DosHeaderMinimumLength = 0x40;
    private const int ElfanewOffset = 0x3C;
    private const ushort MzSignature = 0x5A4D;
    private const uint PeSignature = 0x0000_4550;
    private const int CoffHeaderLength = 20;
    private const ushort Pe32Magic = 0x010B;
    private const ushort Pe32PlusMagic = 0x020B;

    private const int SizeOfImageOffsetInOptionalHeader = 56;

    private const int OptionalHeaderMinimumLength = SizeOfImageOffsetInOptionalHeader + sizeof(uint);

    public static bool TryReadFile(string path, out PeHeaders? headers, out PeReadFailure failure)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        using var stream = new FileStream(
            path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite, bufferSize: 4096);
        return TryRead(stream, out headers, out failure);
    }

    public static bool TryRead(Stream stream, out PeHeaders? headers, out PeReadFailure failure)
    {
        ArgumentNullException.ThrowIfNull(stream);
        if (!stream.CanSeek)
        {
            throw new ArgumentException("A seekable stream is required.", nameof(stream));
        }

        headers = null;
        long length = stream.Length;

        if (length < DosHeaderMinimumLength)
        {
            failure = PeReadFailure.FileTooShort;
            return false;
        }

        Span<byte> dos = stackalloc byte[DosHeaderMinimumLength];
        stream.Position = 0;
        if (!TryFill(stream, dos))
        {
            failure = PeReadFailure.FileTooShort;
            return false;
        }

        if (ReadUInt16(dos, 0) != MzSignature)
        {
            failure = PeReadFailure.NotMzImage;
            return false;
        }

        int peOffset = ReadInt32(dos, ElfanewOffset);

        if (peOffset < 0 || peOffset >= length)
        {
            failure = PeReadFailure.HeaderOffsetOutOfRange;
            return false;
        }

        long headerBytesNeeded = sizeof(uint) + CoffHeaderLength + OptionalHeaderMinimumLength;
        if (peOffset > length - headerBytesNeeded)
        {
            failure = PeReadFailure.FileTooShort;
            return false;
        }

        Span<byte> header = stackalloc byte[sizeof(uint) + CoffHeaderLength];
        stream.Position = peOffset;
        if (!TryFill(stream, header))
        {
            failure = PeReadFailure.FileTooShort;
            return false;
        }

        if (ReadUInt32(header, 0) != PeSignature)
        {
            failure = PeReadFailure.NotPeImage;
            return false;
        }

        ushort machine = ReadUInt16(header, 4);
        uint timeDateStamp = ReadUInt32(header, 8);
        ushort sizeOfOptionalHeader = ReadUInt16(header, 20);

        if (sizeOfOptionalHeader < OptionalHeaderMinimumLength)
        {
            failure = PeReadFailure.OptionalHeaderTooSmall;
            return false;
        }

        long optionalHeaderOffset = peOffset + sizeof(uint) + CoffHeaderLength;
        if (optionalHeaderOffset + OptionalHeaderMinimumLength > length)
        {
            failure = PeReadFailure.FileTooShort;
            return false;
        }

        Span<byte> optional = stackalloc byte[OptionalHeaderMinimumLength];
        stream.Position = optionalHeaderOffset;
        if (!TryFill(stream, optional))
        {
            failure = PeReadFailure.FileTooShort;
            return false;
        }

        ushort magic = ReadUInt16(optional, 0);
        if (magic is not (Pe32Magic or Pe32PlusMagic))
        {
            failure = PeReadFailure.UnknownOptionalHeaderMagic;
            return false;
        }

        bool isPe32Plus = magic == Pe32PlusMagic;
        uint sizeOfImage = ReadUInt32(optional, SizeOfImageOffsetInOptionalHeader);

        headers = new PeHeaders(timeDateStamp, sizeOfImage, machine, isPe32Plus);
        failure = PeReadFailure.None;
        return true;
    }

    private static bool TryFill(Stream stream, Span<byte> buffer)
    {
        int filled = 0;
        while (filled < buffer.Length)
        {
            int read = stream.Read(buffer[filled..]);
            if (read <= 0)
            {
                return false;
            }

            filled += read;
        }

        return true;
    }

    private static ushort ReadUInt16(ReadOnlySpan<byte> source, int offset) =>
        (ushort)(source[offset] | (source[offset + 1] << 8));

    private static uint ReadUInt32(ReadOnlySpan<byte> source, int offset) =>
        (uint)(source[offset]
               | (source[offset + 1] << 8)
               | (source[offset + 2] << 16)
               | (source[offset + 3] << 24));

    private static int ReadInt32(ReadOnlySpan<byte> source, int offset) =>
        unchecked((int)ReadUInt32(source, offset));
}
