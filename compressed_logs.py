"""Stream plain or Zstandard-compressed UTF-8 logs without external commands."""
import io

import zstandard


def iter_log_lines(paths):
    """Yield lines in path order, closing each file before opening the next."""
    for path in paths:
        if str(path).endswith((".zst", ".zstd")):
            with open(path, "rb") as source:
                with zstandard.ZstdDecompressor().stream_reader(source, read_across_frames=True) as stream:
                    with io.TextIOWrapper(stream, encoding="utf-8", errors="replace") as text:
                        yield from text
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as text:
                yield from text
