namespace Swir.Desktop.Host;

internal static class DesktopReleaseTestTiming
{
    private const long ChunkBytes = 32L * 1024L * 1024L;
    internal const int MinimumCandidatePreparationTimeoutMs = 30_000;
    internal const int MaximumCandidatePreparationTimeoutMs = 120_000;
    private const int MillisecondsPerChunk = 5_000;

    internal static int CandidatePreparationTimeoutMs(long packageSize)
    {
        if (packageSize < 0)
            throw new ArgumentOutOfRangeException(nameof(packageSize));

        var chunks = packageSize == 0 ? 0 : (packageSize + ChunkBytes - 1) / ChunkBytes;
        var timeout = MinimumCandidatePreparationTimeoutMs + chunks * MillisecondsPerChunk;
        return (int)Math.Clamp(timeout, MinimumCandidatePreparationTimeoutMs, MaximumCandidatePreparationTimeoutMs);
    }
}
