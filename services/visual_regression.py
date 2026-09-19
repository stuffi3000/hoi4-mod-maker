"""Opt-in deterministic visual-regression workflow (M6.8).

This module is strictly opt-in: nothing in the export pipeline imports
it, and importing it has no side effects (no files are read or written
until the caller explicitly asks). It builds deterministic miniatures
and PNG contact sheets from generated raster assets plus a stable
approval/manifest record for human visual sign-off.

Inputs are small numpy arrays (tests use tiny fixtures; no copyrighted
external assets are needed) or raw uncompressed BGRA8 DDS bytes parsed
through domain.dds_format. Compressed BC/DXT payloads are refused with
an explicit error because no block decoder is bundled.

Public API:

- as_rgb_array: normalize grayscale/RGB/RGBA input to HxWx3 uint8.
- miniature: deterministic nearest-neighbor downscale.
- contact_sheet: tile named panels into one sheet plus layout metadata.
- encode_png: dependency-free deterministic PNG encoder (numpy + zlib).
- write_contact_sheet: persist a sheet and return stable metadata.
- summarize_raster: stable hash/shape fingerprint for manifest records.
- panel_from_dds_bytes: BGRA8 DDS bytes to an RGB panel (BC refused).
- approval_record: stable approval dict for manifests (pending/approved).
"""
from __future__ import annotations

import hashlib
import os
import struct
import zlib


SCHEMA = "visual-regression/6.8"

APPROVAL_STATUSES = ("pending", "approved", "rejected")

DEFAULT_MINIATURE_SIZE = (96, 64)

DEFAULT_COLUMNS = 4

DEFAULT_PADDING = 4

DEFAULT_BACKGROUND = (24, 24, 24)


def _require_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "visual_regression needs numpy, which the exporter already "
            "requires: %s" % exc
        )
    return np


def as_rgb_array(pixels):
    """Normalize raster input to a contiguous HxWx3 uint8 RGB array.

    Accepts HxW grayscale, HxWx3 RGB, and HxWx4 RGBA (alpha is dropped).
    Four-channel DDS payloads in BGRA order must go through
    panel_from_dds_bytes instead so channel order stays explicit.
    Raises ValueError for anything else.
    """
    np = _require_numpy()
    try:
        arr = np.ascontiguousarray(pixels)
    except (TypeError, ValueError) as exc:
        raise ValueError("raster input cannot be read as an array: %s" % exc)
    if arr.dtype != np.uint8:
        try:
            if arr.min() < 0 or arr.max() > 255:
                raise ValueError(
                    "raster values must fit in uint8 range, got [%r, %r]"
                    % (arr.min(), arr.max())
                )
            arr = arr.astype(np.uint8)
        except (TypeError, ValueError) as exc:
            raise ValueError("raster input must be uint8-compatible: %s" % exc)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        pass
    elif arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    else:
        raise ValueError(
            "raster input must be HxW, HxWx3, or HxWx4, got shape %r"
            % (arr.shape,)
        )
    return np.ascontiguousarray(arr)


def miniature(pixels, width=DEFAULT_MINIATURE_SIZE[0], height=DEFAULT_MINIATURE_SIZE[1]):
    """Downscale to a deterministic width-by-height RGB miniature.

    Nearest-neighbor sampling with a fixed grid: identical inputs always
    produce identical outputs regardless of platform or library version.
    """
    np = _require_numpy()
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as exc:
        raise ValueError("miniature size must be integers: %s" % exc)
    if width <= 0 or height <= 0:
        raise ValueError("miniature size must be positive")
    src = as_rgb_array(pixels)
    src_h, src_w = int(src.shape[0]), int(src.shape[1])
    if src_w == width and src_h == height:
        return src.copy()
    rows = (np.arange(height) * src_h) // height
    cols = (np.arange(width) * src_w) // width
    return np.ascontiguousarray(src[rows[:, None], cols])


def contact_sheet(
    panels,
    columns=DEFAULT_COLUMNS,
    miniature_size=DEFAULT_MINIATURE_SIZE,
    padding=DEFAULT_PADDING,
    background=DEFAULT_BACKGROUND,
):
    """Tile named (name, pixels) panels into one RGB sheet.

    Returns (sheet_array, layout) where layout lists one dict per panel
    with name, index, x, y, width, height, and sha256 of the mini bytes.
    Panel order is the caller order; layout and pixels are deterministic.
    """
    np = _require_numpy()
    try:
        items = list(panels)
    except TypeError as exc:
        raise ValueError("panels must be an iterable: %s" % exc)
    if not items:
        raise ValueError("contact_sheet needs at least one panel")
    try:
        columns = int(columns)
        padding = int(padding)
        mini_w = int(miniature_size[0])
        mini_h = int(miniature_size[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("invalid sheet geometry: %s" % exc)
    if columns <= 0 or padding < 0 or mini_w <= 0 or mini_h <= 0:
        raise ValueError("invalid sheet geometry")
    try:
        bg = tuple(int(v) for v in background)
        if len(bg) != 3:
            raise ValueError("background must be three channels")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid background color: %s" % exc)
    names = []
    minis = []
    for position, panel in enumerate(items):
        try:
            name, pixels = panel
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "panel %d must be a (name, pixels) pair: %s" % (position, exc)
            )
        try:
            label = str(name)
        except (TypeError, ValueError) as exc:
            raise ValueError("panel %d name is unusable: %s" % (position, exc))
        if not label:
            raise ValueError("panel %d has an empty name" % position)
        if label in names:
            raise ValueError("duplicate panel name %r" % label)
        names.append(label)
        minis.append(miniature(pixels, width=mini_w, height=mini_h))
    rows = (len(minis) + columns - 1) // columns
    sheet_w = columns * mini_w + (columns + 1) * padding
    sheet_h = rows * mini_h + (rows + 1) * padding
    sheet = np.empty((sheet_h, sheet_w, 3), dtype=np.uint8)
    sheet[:, :] = np.uint8(bg)
    layout = []
    for index, (label, mini) in enumerate(zip(names, minis)):
        row, col = divmod(index, columns)
        x = padding + col * (mini_w + padding)
        y = padding + row * (mini_h + padding)
        sheet[y : y + mini_h, x : x + mini_w] = mini
        layout.append(
            {
                "name": label,
                "index": index,
                "x": int(x),
                "y": int(y),
                "width": int(mini_w),
                "height": int(mini_h),
                "sha256": hashlib.sha256(mini.tobytes()).hexdigest(),
            }
        )
    return (np.ascontiguousarray(sheet), layout)


def encode_png(rgb):
    """Encode an RGB array as deterministic PNG bytes (no PIL needed).

    8-bit truecolor, one IDAT with maximum zlib compression, no ancillary
    chunks (no timestamps, no software tags): identical pixels always
    produce identical bytes.
    """
    arr = as_rgb_array(rgb)
    height, width = int(arr.shape[0]), int(arr.shape[1])
    raw = b"".join(b"\x00" + arr[row].tobytes() for row in range(height))

    def chunk(chunk_type, payload):
        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def sha256_bytes(data):
    """Hex SHA-256 of bytes-like input."""
    try:
        raw = bytes(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("sha256_bytes needs bytes-like input: %s" % exc)
    return hashlib.sha256(raw).hexdigest()


def summarize_raster(name, pixels):
    """Stable fingerprint dict for one raster input (manifest-safe)."""
    try:
        label = str(name)
    except (TypeError, ValueError) as exc:
        raise ValueError("raster name is unusable: %s" % exc)
    if not label:
        raise ValueError("raster name must not be empty")
    arr = as_rgb_array(pixels)
    flat = arr.reshape(-1, 3).astype("int64")
    return {
        "name": label,
        "shape": [int(arr.shape[0]), int(arr.shape[1]), 3],
        "dtype": "uint8",
        "sha256": hashlib.sha256(arr.tobytes()).hexdigest(),
        "min": [int(flat[:, 0].min()), int(flat[:, 1].min()), int(flat[:, 2].min())],
        "max": [int(flat[:, 0].max()), int(flat[:, 1].max()), int(flat[:, 2].max())],
    }


def panel_from_dds_bytes(name, data):
    """Convert raw DDS bytes to a named RGB panel for contact sheets.

    Only uncompressed BGRA8 payloads are supported; BC/DXT payloads are
    refused with an explicit error because no block decoder is bundled.
    """
    from domain.dds_format import parse_dds_header

    try:
        label = str(name)
    except (TypeError, ValueError) as exc:
        raise ValueError("panel name is unusable: %s" % exc)
    if not label:
        raise ValueError("panel name must not be empty")
    try:
        raw = bytes(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("DDS input must be bytes-like: %s" % exc)
    info = parse_dds_header(raw)
    if info["four_cc"] != "BGRA8":
        raise ValueError(
            "only uncompressed BGRA8 DDS bytes can preview; got %s "
            "(no BC/DXT block decoder is bundled)" % info["four_cc"]
        )
    np = _require_numpy()
    payload = raw[info["header_size"] :]
    expected = info["width"] * info["height"] * 4
    if len(payload) != expected:
        raise ValueError(
            "BGRA8 payload is %d bytes; expected %d for %dx%d"
            % (len(payload), expected, info["width"], info["height"])
        )
    bgra = np.frombuffer(payload, dtype=np.uint8).reshape(
        info["height"], info["width"], 4
    )
    rgb = np.ascontiguousarray(bgra[:, :, [2, 1, 0]])
    return (label, rgb)


def write_contact_sheet(path, panels, columns=DEFAULT_COLUMNS,
                        miniature_size=DEFAULT_MINIATURE_SIZE,
                        padding=DEFAULT_PADDING,
                        background=DEFAULT_BACKGROUND):
    """Write a deterministic contact-sheet PNG; return stable metadata.

    Metadata holds schema, output size, columns, per-panel layout, and
    the sheet SHA-256, and is safe to embed in manifests. The caller
    chooses when to run this; the export pipeline never calls it.
    """
    try:
        target = str(path)
    except (TypeError, ValueError) as exc:
        raise ValueError("contact-sheet path is unusable: %s" % exc)
    if not target:
        raise ValueError("contact-sheet path must not be empty")
    sheet, layout = contact_sheet(
        panels,
        columns=columns,
        miniature_size=miniature_size,
        padding=padding,
        background=background,
    )
    payload = encode_png(sheet)
    parent = os.path.dirname(os.path.abspath(target))
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise ValueError("cannot create contact-sheet directory: %s" % exc)
    try:
        with open(target, "wb") as handle:
            handle.write(payload)
    except OSError as exc:
        raise ValueError("cannot write contact sheet %r: %s" % (target, exc))
    return {
        "schema": SCHEMA,
        "path": os.path.basename(target),
        "width": int(sheet.shape[1]),
        "height": int(sheet.shape[0]),
        "columns": int(columns),
        "panel_count": len(layout),
        "panels": [dict(entry) for entry in layout],
        "sheet_sha256": hashlib.sha256(payload).hexdigest(),
    }


def approval_record(inputs, output_sha256, status="pending", reviewer="",
                    note="", created_at=""):
    """Build a stable visual-approval record for manifests.

    inputs is a list of summarize_raster-style dicts (copied verbatim
    except for a fresh list). created_at is caller-supplied ("" keeps
    records byte-stable for tests); pass an explicit UTC timestamp in
    real workflows. Unknown statuses raise ValueError.
    """
    if status not in APPROVAL_STATUSES:
        raise ValueError(
            "approval status %r is unknown; expected one of %s"
            % (status, ", ".join(APPROVAL_STATUSES))
        )
    try:
        records = [dict(entry) for entry in list(inputs)]
    except TypeError as exc:
        raise ValueError("approval inputs must be a list of dicts: %s" % exc)
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError("approval inputs must be a list of dicts")
    try:
        digest = str(output_sha256)
        who = str(reviewer)
        text = str(note)
        stamp = str(created_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("approval metadata is unusable: %s" % exc)
    if not digest:
        raise ValueError("approval record needs an output SHA-256")
    return {
        "schema": SCHEMA,
        "status": status,
        "reviewer": who,
        "note": text,
        "created_at": stamp,
        "inputs": records,
        "output_sha256": digest,
    }
