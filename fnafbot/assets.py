"""Extract the game's own images to use as computer-vision reference pictures.

Why do this instead of taking screenshots by hand?
    FNAF 1 was made with Clickteam Fusion. All of its artwork is stored inside
    FiveNightsatFreddys.exe in an "image bank". Reading that bank gives us a
    perfectly clean picture of every camera view in every state (empty room,
    Bonnie in the room, Foxy peeking out, ...). Comparing the live screen to
    these clean pictures is far more reliable than hand-made screenshots.

The images are extracted from the user's own installed copy and cached in
``cache/assets`` (git-ignored). Nothing from the game is redistributed.

File format notes (Clickteam Fusion 2.5, "PAMU" data pack, build 284):
    * The game data starts at the ASCII marker ``PAMU`` after the normal
      Windows executable.
    * After a 16-byte header the data is a list of "chunks":
      ``id (u16) | flags (u16) | size (u32) | data``.
    * Chunk id 0x6666 is the image bank. Each image inside is individually
      zlib-compressed and begins with a 32-byte header (width, height, ...)
      followed by rows of BGR pixels (and optionally an alpha plane).
"""

from __future__ import annotations

import logging
import struct
import zlib
from pathlib import Path

import cv2
import numpy as np

from fnafbot import config

log = logging.getLogger(__name__)

# Chunk ids we care about.
_CHUNK_IMAGE_BANK = 0x6666
_CHUNK_LAST = 0x7F7F

# Bit flags used by Clickteam.
_CHUNK_FLAG_COMPRESSED = 0x1
_IMAGE_FLAG_ALPHA = 0x10
_IMAGE_FLAG_RLE_ANY = 0x0F  # run-length encoded variants (not used by FNAF 1)
_GRAPHIC_MODE_24BIT = 4

# Bump this whenever the decoding changes, so old caches are re-extracted.
_EXTRACTOR_VERSION = 2
_DONE_MARKER = f"extracted_v{_EXTRACTOR_VERSION}.txt"


def _find_data_pack(blob: bytes) -> int:
    """Return the byte offset where the Clickteam game data begins.

    The marker ``PAMU`` also appears once inside the runtime code near the
    start of the file, so we search from the last occurrence that is followed
    by a valid chunk header.
    """
    pos = blob.find(b"PAMU", 1_000_000)
    if pos < 0:
        raise RuntimeError("Could not find the game data inside the exe (no 'PAMU' marker).")
    return pos + 16  # skip magic(4) + runtime version(2+2) + product version/build(4+4)


def _read_chunks(blob: bytes, start: int) -> dict[int, tuple[int, bytes]]:
    """Walk the chunk list and return {chunk_id: (flags, raw_data)}."""
    chunks: dict[int, tuple[int, bytes]] = {}
    pos = start
    while pos + 8 <= len(blob):
        chunk_id, flags, size = struct.unpack_from("<HHI", blob, pos)
        pos += 8
        chunks.setdefault(chunk_id, (flags, blob[pos:pos + size]))
        pos += size
        if chunk_id == _CHUNK_LAST:
            break
    return chunks


def _decode_image(raw: bytes) -> np.ndarray | None:
    """Turn one decompressed image record into a BGR (or BGRA) numpy array."""
    width, height, mode, flags = struct.unpack_from("<HHBB", raw, 12)
    if mode != _GRAPHIC_MODE_24BIT or flags & _IMAGE_FLAG_RLE_ANY:
        return None  # a format FNAF 1 does not use; skip rather than guess
    pixels = raw[32:]

    # Rows hold an even number of pixels: odd-width images get one extra
    # (unused) pixel = 3 bytes at the end of every row. Verified by checking
    # that rows line up cleanly for the odd-width camera-name labels.
    row_padding = (width % 2) * 3
    row_bytes = width * 3 + row_padding
    color = np.frombuffer(pixels[:row_bytes * height], np.uint8)
    if color.size != row_bytes * height:
        return None
    image = color.reshape(height, row_bytes)[:, :width * 3].reshape(height, width, 3)

    if flags & _IMAGE_FLAG_ALPHA:
        # The alpha plane follows, one byte per pixel, rows padded to 4 bytes.
        alpha_padding = (4 - width % 4) % 4
        alpha_size = (width + alpha_padding) * height
        alpha = np.frombuffer(pixels[row_bytes * height:row_bytes * height + alpha_size], np.uint8)
        if alpha.size == alpha_size:
            alpha = alpha.reshape(height, width + alpha_padding)[:, :width]
            image = np.dstack([image, alpha])
    return image


def extract_all(exe_path: Path = config.GAME_EXE, out_dir: Path = config.ASSET_CACHE) -> int:
    """Extract every image from the game into ``out_dir`` as ``<handle>.png``.

    Returns the number of images written. Safe to call repeatedly.
    """
    blob = exe_path.read_bytes()
    chunks = _read_chunks(blob, _find_data_pack(blob))
    if _CHUNK_IMAGE_BANK not in chunks:
        raise RuntimeError("The game data has no image bank; unsupported game version?")

    flags, data = chunks[_CHUNK_IMAGE_BANK]
    if flags & _CHUNK_FLAG_COMPRESSED:
        data = zlib.decompress(data[8:])

    out_dir.mkdir(parents=True, exist_ok=True)
    count = struct.unpack_from("<I", data, 0)[0]
    pos = 4
    written = 0
    for _ in range(count):
        # Record layout: handle(u32) | decompressed size(u32) | compressed size(u32) | zlib data
        handle, _full_size, packed_size = struct.unpack_from("<III", data, pos)
        raw = zlib.decompress(data[pos + 12:pos + 12 + packed_size])
        pos += 12 + packed_size
        image = _decode_image(raw)
        if image is not None:
            cv2.imwrite(str(out_dir / f"{handle:04d}.png"), image)
            written += 1
    log.info("Extracted %d images from %s", written, exe_path)
    # Written last, so an interrupted extraction is not mistaken for a finished one.
    (out_dir / _DONE_MARKER).write_text(f"extractor version {_EXTRACTOR_VERSION}\n")
    return written


def require_extracted() -> None:
    """Make sure the one-time setup has been done.

    The bot never opens game files while playing. Reference pictures are
    copied out of the installed game ONCE, by ``python -m fnafbot --setup``,
    before any night is played."""
    if not (config.ASSET_CACHE / _DONE_MARKER).exists():
        raise RuntimeError("Reference pictures are missing. Run the one-time setup first:\n"
                           "    python -m fnafbot --setup")


def load(handle: int, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """Load one cached image by its numeric handle (see catalog.py)."""
    path = config.ASSET_CACHE / f"{handle:04d}.png"
    image = cv2.imread(str(path), flags)
    if image is None:
        raise FileNotFoundError(f"Reference image {path} is missing - delete cache/ and re-run to re-extract.")
    return image
