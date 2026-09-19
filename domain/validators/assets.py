"""Asset and mod-integration validation slice (M3.3f).

Pure, filesystem-free checks over caller-supplied asset inventories,
raster header metadata, descriptor text, country tags, and generated
content references. The public entry point is
:func:`validate_asset_integration`, which returns a deterministic list of
:class:`domain.validation.ValidationFinding`.

Stable finding codes emitted here (all use layer ``integration`` and
severity ``error`` because staged-output defects block promotion and are
not waivable):

- ``integration.asset_disposition``: profile-required assets without a
  generated, preserved, or profile-permitted inherited resolution;
  explicitly blocked required assets are reported here as well (the
  manifest reason carries the remedy);
  preserved resolutions without usable stored bytes (missing key, None,
  or zero-length bytes) or with dirty bytes; and required
  generated/preserved assets missing from the staged output inventory.
  Non-empty bytes and mapping/object stored values still count as usable.
- ``integration.asset_policy``: deprecated files resolved as anything
  but omitted, and inherited resolutions where the profile permits no
  inheritance.
- ``integration.bmp_format``: BMP dimensions, bit depth, compression,
  palette size, or orientation disagreeing with the profile contract.
- ``integration.dds_format``: DDS dimensions, pixel format, mip counts,
  DX10-header flags, or block-compressed payload sizes disagreeing with
  the profile contract or the derived BC payload size.
- ``integration.descriptor``: descriptor text missing its name or
  supported version, disagreeing with the game target/profile version,
  declaring replace paths outside the profile, or carrying
  machine-specific absolute paths. Internal descriptors (default) treat
  absolute ``path=`` values as machine-specific; outer launcher
  descriptors (``descriptor_kind="outer"``) allow the absolute
  ``path=`` written by the exporter.
- ``integration.tag_collision``: project or acceptance country tags that
  collide (case-insensitively) with vanilla, dependency, project,
  reserved-acceptance, or duplicated acceptance tags.
- ``integration.missing_reference``: generated content references that
  do not resolve against the supplied foundation IDs.
- ``integration.asset_record``: malformed resolution, header, inventory,
  descriptor, or reference records that could not be interpreted.

Accepted record shapes:

- Asset resolutions accept ``domain.export_contract.AssetResolution``
  instances, mappings with ``rel_path`` (or ``path``/``file``) plus
  ``disposition`` (or ``status``/``state``) keys, a mapping of rel path
  to disposition string or record (records without their own path
  inherit the mapping key), and plain disposition strings as mapping
  values. Unknown disposition strings (anything outside generated, preserved,
  inherited, omitted, unsupported, or blocked) on required paths are
  disposition problems; elsewhere they are record problems.
- BMP header records accept mappings (or attribute objects) with any of
  ``width``/``height``, ``bits_per_pixel``/``bits``/``bpp``,
  ``compression``, ``palette_entries``/``palette``, and
  ``bottom_up``/``top_down``/``orientation`` keys. Integer BMP
  compression IDs (0=BI_RGB, 1=BI_RLE8, 2=BI_RLE4, 3=BI_BITFIELDS) are
  understood, and a palette given as a color list counts by length.
- DDS header records accept mappings (or attribute objects) with any of
  ``width``/``height``, ``four_cc``/``format``, ``mip_count``/``mips``,
  ``has_dx10_header``/``dx10``, ``payload_size``/``payload_bytes``/
  ``data_size``, and ``expected_payload_size``/``expected_size`` keys.
  ``BC1``/``BC2``/``BC3`` are treated as aliases of
  ``DXT1``/``DXT3``/``DXT5``, and ``BC3/DXT5``-style combined names
  match on their first part. When ``payload_size`` (or an explicit
  expected size) is supplied, it is compared against the
  block-compressed expected payload derived from ``width``,
  ``height``, ``four_cc``, and ``mip_count`` (``DXT1`` uses 8 bytes per
  4x4 block; ``DXT3``/``DXT5`` use 16; missing ``mip_count`` defaults
  to 1; unknown formats skip the check). Absent payload metadata is
  tolerated.
- Content references accept a mapping of group name to ID or ID list, a
  list of mappings carrying one of ``foundation_id``/``id``/
  ``province_id``/``state_id``/``ref``/``target``/``value`` keys, or a
  flat iterable of IDs. ``kind``/``type`` keys only enrich evidence.
- Descriptor text is parsed with tolerant ``key = "value"`` patterns
  for ``supported_version``, ``replace_path``, ``name``, and ``path``
  using single or double quotes. Pass ``descriptor_kind="outer"`` for
  the outer launcher ``.mod`` file whose absolute ``path=`` is expected;
  the default ``descriptor_kind="internal"`` keeps strict
  machine-specific path checks for the internal ``descriptor.mod``.

Limitations:

- Expected raster dimensions require both ``map_dimensions`` and a
  matching profile BMP/DDS contract; otherwise dimension checks are
  skipped without inventing findings.
- Format fields are only compared when both the header record and the
  profile contract supply an interpretable value; absent metadata is
  tolerated, while present-but-uninterpretable values are reported as
  malformed records.
- A missing ``asset_resolutions`` inventory disables the disposition and
  policy sections; a missing ``descriptor_text`` disables descriptor
  checks; empty ``foundation_ids`` disables missing-reference comparison
  but malformed content-reference records are still reported.
- Findings carry ``affected_ids`` (asset paths, tags, or reference IDs,
  sorted and capped at 64 entries); spatial ``coordinates`` are always
  empty because this slice validates staged output rather than map
  pixels.
- Full staged-ownership reconciliation (attributing every output file to
  an export stage) is out of scope; ``output_files`` only proves that
  required generated/preserved assets were staged.
"""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from typing import Any

from domain.export_contract import RESERVED_ACCEPTANCE_TAGS
from domain.validation import ValidationFinding

__all__ = ["CODES", "LAYER", "validate_asset_integration"]

LAYER = "integration"

CODES = (
    "integration.asset_disposition",
    "integration.asset_policy",
    "integration.bmp_format",
    "integration.dds_format",
    "integration.descriptor",
    "integration.tag_collision",
    "integration.missing_reference",
    "integration.asset_record",
)

_AFFECTED_LIMIT = 64
_EVIDENCE_LIMIT = 6

_LEGAL_DISPOSITIONS = (
    "generated",
    "preserved",
    "inherited",
    "omitted",
    "unsupported",
    "blocked",
)

_PATH_KEYS = ("rel_path", "path", "file", "filename")
_DISPOSITION_KEYS = ("disposition", "status", "state", "action")

_WIDTH_NAMES = ("width", "w", "width_px", "columns", "size_x")
_HEIGHT_NAMES = ("height", "h", "height_px", "rows", "size_y")
_BMP_BITS_NAMES = ("bits_per_pixel", "bits", "bpp", "bit_depth", "depth")
_BMP_COMPRESSION_NAMES = ("compression", "compress", "compression_name")
_BMP_PALETTE_NAMES = (
    "palette_entries",
    "palette",
    "palette_size",
    "colors",
    "num_colors",
    "color_count",
)
_DDS_FORMAT_NAMES = ("four_cc", "fourcc", "format", "pixel_format", "dxgi_format")
_DDS_MIP_NAMES = (
    "mip_count",
    "mips",
    "mipmaps",
    "mip_levels",
    "mipmap_count",
    "num_mips",
    "levels",
)
_DDS_DX10_NAMES = (
    "has_dx10_header",
    "dx10",
    "dx10_header",
    "has_dx10",
    "extended_header",
)
_DDS_PAYLOAD_NAMES = (
    "payload_size",
    "payload_bytes",
    "data_size",
    "data_bytes",
)
_DDS_EXPECTED_PAYLOAD_NAMES = (
    "expected_payload_size",
    "expected_payload_bytes",
    "expected_size",
    "expected_bytes",
)
_DDS_BLOCK_BYTES = {
    "DXT1": 8,
    "DXT3": 16,
    "DXT5": 16,
}

_BMP_COMPRESSION_IDS = {0: "BI_RGB", 1: "BI_RLE8", 2: "BI_RLE4", 3: "BI_BITFIELDS"}
_FOURCC_ALIASES = {"BC1": "DXT1", "BC2": "DXT3", "BC3": "DXT5"}

_REF_ID_KEYS = (
    "foundation_id",
    "id",
    "province_id",
    "state_id",
    "ref",
    "target",
    "value",
    "pid",
    "sid",
    "province",
    "state",
)
_REF_KIND_KEYS = ("kind", "type", "layer", "group", "name")

_SUPPORTED_RE = re.compile(r"supported_version\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_REPLACE_RE = re.compile(r"replace_path\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_PATH_RE = re.compile(r"(?<![\w])path\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_NAME_RE = re.compile(r"(?<![\w])name\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_LEADING_INT_RE = re.compile(r"^\s*(\d+)")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

_MISSING = object()

_RESERVED_TAGS = frozenset(str(tag).upper() for tag in RESERVED_ACCEPTANCE_TAGS)


def _normalize_path(value):
    """Return value as a slash-separated path, or empty string."""
    if not isinstance(value, str):
        return ""
    return value.replace("\\", "/").strip()


def _normalize_disposition(value):
    """Return value as a lowercase disposition string, or empty string."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _sort_key(value):
    """Return a total-order sort key that works across ints and strings."""
    if isinstance(value, bool):
        return (2, repr(value), 0)
    if isinstance(value, (int, float)):
        return (0, "", value)
    return (1, str(value), 0)


def _sorted_capped(values, limit=_AFFECTED_LIMIT):
    """Return sorted unique values from the iterable, capped at limit."""
    try:
        unique = set(values)
    except TypeError:
        return ()
    return tuple(sorted(unique, key=_sort_key)[:limit])


def _short(value, limit=40):
    """Render value compactly for evidence strings."""
    try:
        text = repr(value)
    except Exception:
        text = "<unrepresentable>"
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text

def _as_int(value):
    """Return value as an int, or None when it is not integer-like."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                return None
            if number.is_integer():
                return int(number)
            return None
    return None


def _header_int(value):
    """Return header values as int, accepting leading digits in strings."""
    number = _as_int(value)
    if number is not None:
        return number
    if isinstance(value, str):
        match = _LEADING_INT_RE.match(value)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _as_bool(value):
    """Return value as a bool, or None when it is not boolean-like."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "1", "on", "y"):
            return True
        if text in ("false", "no", "0", "off", "n"):
            return False
        return None
    return None


def _first_field(record, names):
    """Return (True, value) for the first matching field, else (False, None)."""
    if isinstance(record, Mapping):
        lowered = {}
        try:
            items = list(record.items())
        except Exception:
            return (False, None)
        for key, item in items:
            try:
                lowered[str(key).lower()] = item
            except Exception:
                continue
        for name in names:
            if name in lowered:
                return (True, lowered[name])
        return (False, None)
    for name in names:
        try:
            item = getattr(record, name, _MISSING)
        except Exception:
            continue
        if item is not _MISSING:
            return (True, item)
    return (False, None)


def _normalize_compression(value):
    """Return the canonical BMP compression name, or None when unknown."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _BMP_COMPRESSION_IDS.get(value)
    if isinstance(value, str):
        text = value.strip().upper().replace("-", "_").replace(" ", "_")
        if not text:
            return None
        if text in ("0", "RGB"):
            return "BI_RGB"
        return text
    return None


def _normalize_fourcc(value):
    """Return the canonical DDS format name, or None when unknown."""
    if not isinstance(value, str):
        return None
    for part in re.split(r"[/|]", value.strip().upper()):
        text = part.strip().replace(" ", "").replace("-", "")
        if not text:
            continue
        return _FOURCC_ALIASES.get(text, text)
    return None


def _orientation_bottom_up(record):
    """Return header orientation as bottom-up flag, or None when unknown."""
    found, raw = _first_field(record, ("bottom_up", "bottomup"))
    if found:
        return _as_bool(raw)
    found, raw = _first_field(record, ("top_down", "topdown"))
    if found:
        flag = _as_bool(raw)
        return (not flag) if flag is not None else None
    found, raw = _first_field(record, ("orientation",))
    if found and isinstance(raw, str):
        text = raw.strip().lower().replace("-", "_").replace(" ", "_")
        if text.startswith("bottom"):
            return True
        if text.startswith("top"):
            return False
    return None

def _split_record(entry):
    """Split one resolution record into (path, disposition, problem)."""
    if isinstance(entry, Mapping):
        found_path, raw_path = _first_field(entry, _PATH_KEYS)
        found_disp, raw_disp = _first_field(entry, _DISPOSITION_KEYS)
        path = _normalize_path(raw_path) if found_path else ""
        disp = _normalize_disposition(raw_disp) if found_disp else ""
        if not path:
            return ("", disp, "record is missing a usable rel_path")
        if not disp:
            return (path, "", "record for '%s' is missing a disposition" % path)
        return (path, disp, "")
    if isinstance(entry, (str, bytes)):
        problem = "entry %s is not a mapping or AssetResolution record"
        return ("", "", problem % _short(entry))
    try:
        raw_path = getattr(entry, "rel_path", None)
        raw_disp = getattr(entry, "disposition", None)
    except Exception:
        return ("", "", "entry %s cannot be read" % _short(entry))
    if raw_path is None and raw_disp is None:
        problem = "entry %s is not a mapping or AssetResolution record"
        return ("", "", problem % _short(entry))
    path = _normalize_path(raw_path)
    disp = _normalize_disposition(raw_disp)
    if not path:
        return ("", disp, "record is missing a usable rel_path")
    if not disp:
        return (path, "", "record for '%s' is missing a disposition" % path)
    return (path, disp, "")


def _coerce_resolutions(value):
    """Return (entries, notes, provided) for the resolution inventory."""
    if value is None:
        return (None, [], False)
    entries = []
    notes = []
    if isinstance(value, Mapping):
        try:
            items = list(value.items())
        except Exception:
            return ([], ["asset resolutions mapping cannot be read"], True)
        order = []
        for key, item in items:
            key_path = _normalize_path(key)
            if isinstance(item, str):
                disp = _normalize_disposition(item)
                if not key_path:
                    notes.append(
                        "asset resolution key %s has no usable path"
                        % _short(key)
                    )
                elif not disp:
                    notes.append(
                        "asset resolution for '%s' is missing a disposition"
                        % key_path
                    )
                else:
                    order.append((key_path, disp))
                continue
            path, disp, problem = _split_record(item)
            if not path and key_path and disp:
                order.append((key_path, disp))
                continue
            label = path or key_path
            if problem:
                notes.append(
                    "asset resolution for '%s': %s"
                    % (label or _short(key), problem)
                )
                continue
            order.append((path or key_path, disp))
        order.sort(key=lambda item: _sort_key(item[0]))
        return (order, notes, True)
    if isinstance(value, (str, bytes)):
        return ([], ["asset resolution %s is not a record" % _short(value)], True)
    try:
        items = list(value)
    except TypeError:
        return ([], ["asset resolutions must be an iterable of records"], True)
    for index, item in enumerate(items):
        path, disp, problem = _split_record(item)
        if problem:
            notes.append("asset resolution #%d: %s" % (index, problem))
            continue
        entries.append((path, disp))
    return (entries, notes, True)


def _profile_list(profile, name):
    """Return normalized profile path entries, or None when unavailable."""
    if profile is None or isinstance(profile, (str, bytes)):
        return None
    try:
        if isinstance(profile, Mapping):
            raw = profile.get(name, ())
        else:
            raw = getattr(profile, name, ())
    except Exception:
        return None
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        path = _normalize_path(raw)
        return [path] if path else []
    try:
        items = list(raw)
    except TypeError:
        return []
    out = []
    for item in items:
        path = _normalize_path(item)
        if path and path not in out:
            out.append(path)
    return out


def _profile_contract(profile, section, key):
    """Return the BMP/DDS contract for key, or None when unavailable."""
    if profile is None or isinstance(profile, (str, bytes)):
        return None
    try:
        if isinstance(profile, Mapping):
            section_map = profile.get(section)
        else:
            section_map = getattr(profile, section, None)
    except Exception:
        return None
    if not isinstance(section_map, Mapping):
        return None
    try:
        return section_map.get(key)
    except Exception:
        return None


def _expected_size(profile, section, key, map_w, map_h):
    """Return the expected (width, height) for key, or None."""
    method_name = "expected_bmp_size" if section == "bmp" else "expected_dds_size"
    try:
        method = getattr(profile, method_name, None)
    except Exception:
        method = None
    if callable(method):
        try:
            size = method(key, map_w, map_h)
        except Exception:
            size = None
        if size is not None:
            try:
                return (int(size[0]), int(size[1]))
            except (TypeError, ValueError, IndexError):
                pass
    contract = _profile_contract(profile, section, key)
    if contract is None:
        return None
    try:
        _found_w, raw_wdiv = _first_field(contract, ("width_divisor",))
        _found_h, raw_hdiv = _first_field(contract, ("height_divisor",))
        width_div = _as_int(raw_wdiv)
        height_div = _as_int(raw_hdiv)
        if width_div is None:
            width_div = 1
        if height_div is None:
            height_div = 1
        if width_div <= 0 or height_div <= 0:
            return None
        return (int(map_w) // width_div, int(map_h) // height_div)
    except (TypeError, ValueError):
        return None

def _coerce_map_dimensions(value):
    """Return (width, height) ints, or None when unusable."""
    if value is None or isinstance(value, (str, bytes)):
        return None
    if isinstance(value, Mapping):
        found_w, raw_w = _first_field(value, ("width", "w", "map_w"))
        found_h, raw_h = _first_field(value, ("height", "h", "map_h"))
        if not found_w or not found_h:
            return None
        width = _as_int(raw_w)
        height = _as_int(raw_h)
        if width is None or height is None or width <= 0 or height <= 0:
            return None
        return (width, height)
    try:
        parts = list(value)
    except TypeError:
        return None
    if len(parts) != 2:
        return None
    width = _as_int(parts[0])
    height = _as_int(parts[1])
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return (width, height)


def _coerce_output_set(value, notes):
    """Return staged output paths, or None when the check is skipped."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        path = _normalize_path(value)
        return {path} if path else set()
    try:
        items = list(value)
    except TypeError:
        notes.append("output_files must be an iterable of paths")
        return None
    out = set()
    for item in items:
        if isinstance(item, str):
            path = _normalize_path(item)
        elif isinstance(item, Mapping):
            found, raw = _first_field(item, _PATH_KEYS)
            path = _normalize_path(raw) if found else ""
        else:
            try:
                path = _normalize_path(getattr(item, "rel_path", None))
            except Exception:
                path = ""
        if path:
            out.add(path)
    return out


def _has_usable_stored_bytes(value):
    """Return True when a stored-asset value counts as usable bytes."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return len(value) > 0
        except Exception:
            return False
    if isinstance(value, str):
        return len(value) > 0
    return True


def _coerce_stored_set(value, notes):
    """Return stored-asset paths, or None when the check is skipped."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        notes.append("assets must be a mapping of path to stored bytes")
        return None
    try:
        items = list(value.items())
    except Exception:
        notes.append("assets mapping cannot be read")
        return None
    out = set()
    for key, item in items:
        path = _normalize_path(key)
        if path and _has_usable_stored_bytes(item):
            out.add(path)
    return out


def _dds_block_bytes(four_cc):
    """Return block bytes for BC/DXT formats, or None when unknown."""
    if not isinstance(four_cc, str):
        return None
    return _DDS_BLOCK_BYTES.get(four_cc)


def _expected_dds_payload_size(width, height, four_cc, mip_count):
    """Return expected BC payload size, or None when it cannot be derived."""
    block = _dds_block_bytes(four_cc)
    if block is None:
        return None
    try:
        width = int(width)
        height = int(height)
        mip_count = int(mip_count)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or mip_count <= 0:
        return None
    total = 0
    for level in range(mip_count):
        level_w = max(1, width >> level)
        level_h = max(1, height >> level)
        blocks_w = (level_w + 3) // 4
        blocks_h = (level_h + 3) // 4
        total += blocks_w * blocks_h * block
    return total


def _normalize_descriptor_kind(value):
    """Return (kind, note) with kind as 'internal' or 'outer'."""
    if value is None:
        return ("internal", "")
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text == "internal":
            return ("internal", "")
        if text in ("outer", "launcher", "external"):
            return ("outer", "")
        return ("internal", "unknown descriptor_kind %r" % (value,))
    return ("internal", "unknown descriptor_kind %r" % (value,))


def _coerce_dirty_set(value, notes):
    """Return dirty-asset paths (empty when absent)."""
    if value is None:
        return set()
    if isinstance(value, (str, bytes)):
        path = _normalize_path(value)
        return {path} if path else set()
    try:
        items = list(value)
    except TypeError:
        notes.append("dirty_assets must be an iterable of paths")
        return set()
    out = set()
    for item in items:
        path = _normalize_path(item)
        if path:
            out.add(path)
    return out


def _coerce_header_map(value, kind, notes):
    """Return normalized header records, or None when the check is skipped."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        notes.append(
            "%s headers must be a mapping of path to header record" % kind
        )
        return None
    try:
        items = list(value.items())
    except Exception:
        notes.append("%s headers mapping cannot be read" % kind)
        return None
    out = {}
    for key, record in items:
        path = _normalize_path(key)
        if not path:
            notes.append(
                "%s header key %s has no usable path" % (kind, _short(key))
            )
            continue
        if path in out:
            notes.append("duplicate %s header for '%s'" % (kind, path))
            continue
        if record is None:
            continue
        out[path] = record
    return dict(sorted(out.items(), key=lambda item: item[0]))

def _target_field(target, name):
    """Read an optional text field from GameTarget-like or mapping targets."""
    if target is None or isinstance(target, (str, bytes)):
        return None
    try:
        if isinstance(target, Mapping):
            value = target.get(name)
        else:
            value = getattr(target, name, None)
    except Exception:
        return None
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text if text else None


def _profile_id(profile):
    """Return the profile identifier, or None when unavailable."""
    if profile is None or isinstance(profile, (str, bytes)):
        return None
    try:
        if isinstance(profile, Mapping):
            value = profile.get("profile_id")
        else:
            value = getattr(profile, "profile_id", None)
    except Exception:
        return None
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text if text else None


def _version_matches_profile(descriptor_version, profile):
    """Return True when the version satisfies the profile contract."""
    try:
        if isinstance(profile, Mapping):
            pattern = profile.get("supported_version_pattern")
        else:
            pattern = getattr(profile, "supported_version_pattern", None)
    except Exception:
        pattern = None
    try:
        if isinstance(profile, Mapping):
            versions = profile.get("game_versions")
        else:
            versions = getattr(profile, "game_versions", None)
    except Exception:
        versions = None
    if isinstance(pattern, str) and pattern.strip():
        try:
            if fnmatch.fnmatchcase(descriptor_version, pattern.strip()):
                return True
        except Exception:
            pass
    else:
        pattern = None
    if versions is None:
        return pattern is None
    if isinstance(versions, (str, bytes)):
        versions = [versions]
    try:
        known = {str(item).strip() for item in list(versions)}
        known.discard("")
    except TypeError:
        return pattern is None
    if descriptor_version in known:
        return True
    return pattern is None and not known


def _quoted_values(pattern, text):
    """Return captured quoted values for pattern in order."""
    out = []
    try:
        matches = list(pattern.finditer(text))
    except Exception:
        return out
    for match in matches:
        try:
            groups = match.groups()
        except Exception:
            continue
        for group in groups:
            if group is not None:
                out.append(group)
                break
    return out


def _is_machine_path(value):
    """Return True when a descriptor path is machine-specific."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if text.startswith("~"):
        return True
    if "://" in text:
        return True
    if text.startswith("/") or text.startswith("\\"):
        return True
    if _DRIVE_RE.match(text):
        return True
    return False


def _coerce_descriptor_text(value, notes):
    """Return descriptor text, or None when the check is skipped."""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8-sig")
        except Exception:
            notes.append("descriptor text bytes cannot be decoded")
            return None
    if not isinstance(value, str):
        notes.append("descriptor text must be a string")
        return None
    if not value.strip():
        return None
    return value


def _normalize_tag_input(values):
    """Return (tags, duplicates) upper-cased sets for one tag input."""
    if values is None:
        return (set(), set())
    if isinstance(values, bytes):
        try:
            values = [values.decode("utf-8", "ignore")]
        except Exception:
            return (set(), set())
    if isinstance(values, str):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        return (set(), set())
    tags = set()
    duplicates = set()
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip().upper()
        if not text:
            continue
        if text in tags:
            duplicates.add(text)
        tags.add(text)
    return (tags, duplicates)

def _normalize_ref_id(value):
    """Return reference IDs as int or stripped string, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            pass
        try:
            number = float(text)
        except ValueError:
            return text
        if number.is_integer():
            return int(number)
        return text
    return None


def _record_ref_id(record):
    """Return the reference ID carried by a mapping record, else None."""
    try:
        lowered = {str(key).lower(): item for key, item in list(record.items())}
    except Exception:
        return None
    for key in _REF_ID_KEYS:
        if key in lowered:
            ref_id = _normalize_ref_id(lowered[key])
            if ref_id is not None:
                return ref_id
    return None


def _record_kind(record):
    """Return the kind label carried by a mapping record, else empty."""
    try:
        lowered = {str(key).lower(): item for key, item in list(record.items())}
    except Exception:
        return ""
    for key in _REF_KIND_KEYS:
        if key in lowered and isinstance(lowered[key], str):
            if lowered[key].strip():
                return lowered[key].strip()
    return ""


def _coerce_foundation_set(values):
    """Return usable foundation IDs (empty set disables reference checks)."""
    if values is None:
        return set()
    if isinstance(values, (str, bytes, int, float)):
        single = _normalize_ref_id(values)
        return {single} if single is not None else set()
    try:
        items = list(values)
    except TypeError:
        return set()
    out = set()
    for item in items:
        if isinstance(item, Mapping):
            ref_id = _record_ref_id(item)
        else:
            ref_id = _normalize_ref_id(item)
        if ref_id is not None:
            out.add(ref_id)
    return out


def _iter_ref_members(value):
    """Yield members of a reference group in deterministic order."""
    if isinstance(value, (str, bytes)) or isinstance(value, Mapping):
        yield value
        return
    try:
        items = list(value)
    except TypeError:
        yield value
        return
    if isinstance(value, (set, frozenset)):
        items = sorted(items, key=repr)
    for item in items:
        yield item


def _coerce_references(value):
    """Return (refs, notes) with refs as (ref_id|None, context) pairs."""
    refs = []
    notes = []
    if value is None:
        return (None, notes)
    if isinstance(value, Mapping):
        try:
            groups = sorted(value.items(), key=lambda item: str(item[0]))
        except Exception:
            return ([], ["content references mapping cannot be read"])
        for key, group in groups:
            try:
                context = str(key)
            except Exception:
                context = "group"
            if isinstance(group, Mapping):
                kind = _record_kind(group)
                label = "%s.%s" % (context, kind) if kind else context
                refs.append((_record_ref_id(group), label))
                continue
            for member in _iter_ref_members(group):
                if isinstance(member, Mapping):
                    kind = _record_kind(member)
                    label = "%s.%s" % (context, kind) if kind else context
                    refs.append((_record_ref_id(member), label))
                else:
                    refs.append((_normalize_ref_id(member), context))
        return (refs, notes)
    if isinstance(value, (str, bytes, int, float)):
        return ([(_normalize_ref_id(value), "value")], notes)
    try:
        items = list(value)
    except TypeError:
        return ([], ["content references must be a mapping or an iterable"])
    if isinstance(value, (set, frozenset)):
        items = sorted(items, key=repr)
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            kind = _record_kind(item)
            label = kind or ("index %d" % index)
            refs.append((_record_ref_id(item), label))
        else:
            refs.append((_normalize_ref_id(item), "index %d" % index))
    return (refs, notes)


def _inherited_permitted(path, inherited, replace_paths):
    """Return True when the profile allows inheriting path at runtime."""
    if path in inherited:
        return True
    for entry in replace_paths:
        clean = str(entry).strip().rstrip("/")
        if not clean:
            continue
        if path == clean or path.startswith(clean + "/"):
            return True
    return False


def _display_id(ref_id):
    """Render a reference ID for evidence strings."""
    if isinstance(ref_id, str):
        return "'%s'" % ref_id
    return str(ref_id)


def _evidence(details):
    """Join capped evidence details deterministically."""
    shown = list(details[:_EVIDENCE_LIMIT])
    text = "; ".join(shown)
    if len(details) > _EVIDENCE_LIMIT:
        text += "; ..."
    return text


def _finding(code, message, affected, evidence):
    """Build one integration finding with shared layer metadata."""
    return ValidationFinding(
        code=code,
        severity="error",
        message=message,
        layer=LAYER,
        affected_ids=tuple(affected),
        evidence=evidence,
    )

def validate_asset_integration(
    *,
    profile=None,
    target=None,
    asset_resolutions=None,
    output_files=None,
    assets=None,
    dirty_assets=None,
    bmp_headers=None,
    dds_headers=None,
    descriptor_text=None,
    descriptor_kind="internal",
    vanilla_tags=(),
    dependency_tags=(),
    project_tags=(),
    acceptance_tags=(),
    foundation_ids=(),
    content_references=None,
    map_dimensions=None,
    **_ignored,
):
    """Validate staged asset and mod-integration contracts without I/O.

    Every input is caller-supplied and read-only: profile/target
    contracts, resolution inventories, header metadata, descriptor text,
    tag sets, and reference lists. Nothing is read from disk, nothing is
    mutated, and no Qt or game installation is required.

    ``descriptor_kind`` selects strictness for descriptor ``path=``
    values: ``"internal"`` (default) flags absolute paths as
    machine-specific for the internal ``descriptor.mod``;
    ``"outer"`` (also ``"launcher"``/``"external"``) allows the absolute
    ``path=`` written to the outer launcher ``.mod`` file. Unknown
    ``descriptor_kind`` values are reported as malformed records and
    fall back to strict ``"internal"`` behavior.

    DDS headers may carry ``payload_size`` (or ``expected_payload_size``
    aliases); when present it is compared against the derived
    block-compressed size, otherwise the check is skipped.

    Returns a deterministic list of ``ValidationFinding`` in ``CODES``
    order with at most one finding per code. ``affected_ids`` are sorted
    and capped; ``coordinates`` are always empty; evidence names the
    offending paths, tags, versions, or IDs.
    """
    record_notes = []
    details_by_code = {code: [] for code in CODES}
    affected_by_code = {code: [] for code in CODES}

    entries, resolution_notes, provided = _coerce_resolutions(asset_resolutions)
    record_notes.extend(resolution_notes)
    required = _profile_list(profile, "required_files")
    if provided and required is not None:
        deprecated = _profile_list(profile, "deprecated_files") or []
        inherited = _profile_list(profile, "inherited_files") or []
        replace_paths = _profile_list(profile, "replace_paths") or []
        required_set = set(required)
        deprecated_set = set(deprecated)
        inherited_set = set(inherited)
        seen = set()
        unique = []
        for path, disp in entries or []:
            if path in seen:
                record_notes.append("duplicate resolution for '%s'" % path)
                continue
            seen.add(path)
            unique.append((path, disp))
        by_path = dict(unique)
        stored = _coerce_stored_set(assets, record_notes)
        dirty = _coerce_dirty_set(dirty_assets, record_notes)
        staged = _coerce_output_set(output_files, record_notes)
        for path in sorted(required):
            disp = by_path.get(path)
            problems = []
            if disp in ("generated", "preserved"):
                if disp == "preserved" and stored is not None:
                    if path not in stored:
                        problems.append(
                            "'%s' is preserved but has no stored bytes" % path
                        )
                    elif path in dirty:
                        problems.append(
                            "'%s' is preserved but is marked dirty" % path
                        )
                if staged is not None and path not in staged:
                    problems.append("'%s' has no staged output file" % path)
            elif disp == "inherited":
                if not _inherited_permitted(path, inherited_set, replace_paths):
                    problems.append(
                        "'%s' uses inherited without profile permission" % path
                    )
            elif disp is None:
                problems.append("'%s' has no resolution" % path)
            elif disp == "omitted":
                problems.append("'%s' is omitted" % path)
            elif disp == "unsupported":
                problems.append("'%s' is unsupported" % path)
            elif disp == "blocked":
                problems.append("'%s' is blocked: generation cannot satisfy the profile contract" % path)
            else:
                problems.append(
                    "'%s' has illegal disposition '%s'" % (path, disp)
                )
            if problems:
                details_by_code["integration.asset_disposition"].extend(problems)
                affected_by_code["integration.asset_disposition"].append(path)
        for path in sorted(by_path):
            if path in required_set:
                continue
            disp = by_path[path]
            if disp not in _LEGAL_DISPOSITIONS:
                record_notes.append(
                    "asset resolution for '%s' has unknown disposition '%s'"
                    % (path, disp)
                )
                continue
            if path in deprecated_set:
                if disp != "omitted":
                    details_by_code["integration.asset_policy"].append(
                        "'%s' is deprecated but resolved as '%s'" % (path, disp)
                    )
                    affected_by_code["integration.asset_policy"].append(path)
                continue
            if disp == "inherited" and not _inherited_permitted(
                path, inherited_set, replace_paths
            ):
                details_by_code["integration.asset_policy"].append(
                    "'%s' uses inherited without profile permission" % path
                )
                affected_by_code["integration.asset_policy"].append(path)

    bmp_map = _coerce_header_map(bmp_headers, "BMP", record_notes)
    if bmp_map is not None:
        dimensions = _coerce_map_dimensions(map_dimensions)
        for path, record in bmp_map.items():
            if isinstance(
                record,
                (str, bytes, bool, int, float, list, tuple, set, frozenset),
            ):
                record_notes.append("malformed BMP header for '%s'" % path)
                continue
            if dimensions is not None:
                expected = _expected_size(
                    profile, "bmp", path, dimensions[0], dimensions[1]
                )
                if expected is not None:
                    found_w, raw_w = _first_field(record, _WIDTH_NAMES)
                    found_h, raw_h = _first_field(record, _HEIGHT_NAMES)
                    width = _header_int(raw_w) if found_w else None
                    height = _header_int(raw_h) if found_h else None
                    if found_w and width is None:
                        record_notes.append("malformed BMP width for '%s'" % path)
                    if found_h and height is None:
                        record_notes.append(
                            "malformed BMP height for '%s'" % path
                        )
                    if (width is not None and width != expected[0]) or (
                        height is not None and height != expected[1]
                    ):
                        shown_w = width if width is not None else "?"
                        shown_h = height if height is not None else "?"
                        details_by_code["integration.bmp_format"].append(
                            "'%s' is %sx%s, expected %dx%d"
                            % (path, shown_w, shown_h, expected[0], expected[1])
                        )
                        affected_by_code["integration.bmp_format"].append(path)
            contract = _profile_contract(profile, "bmp", path)
            if contract is not None:
                found, raw = _first_field(record, _BMP_BITS_NAMES)
                if found:
                    bits = _header_int(raw)
                    if bits is None:
                        record_notes.append(
                            "malformed BMP bits value for '%s'" % path
                        )
                    else:
                        found_c, raw_c = _first_field(
                            contract, ("bits_per_pixel", "bits", "bpp")
                        )
                        expected_bits = _as_int(raw_c) if found_c else None
                        if expected_bits is not None and bits != expected_bits:
                            details_by_code["integration.bmp_format"].append(
                                "'%s' bits_per_pixel is %d, expected %d"
                                % (path, bits, expected_bits)
                            )
                            affected_by_code["integration.bmp_format"].append(
                                path
                            )
                found, raw = _first_field(record, _BMP_COMPRESSION_NAMES)
                if found:
                    compression = _normalize_compression(raw)
                    if compression is None:
                        record_notes.append(
                            "malformed BMP compression for '%s'" % path
                        )
                    else:
                        found_c, raw_c = _first_field(
                            contract, ("compression", "compress")
                        )
                        if found_c:
                            expected_c = _normalize_compression(raw_c)
                        else:
                            expected_c = None
                        if expected_c is not None and compression != expected_c:
                            details_by_code["integration.bmp_format"].append(
                                "'%s' compression is '%s', expected '%s'"
                                % (path, compression, expected_c)
                            )
                            affected_by_code["integration.bmp_format"].append(
                                path
                            )
                found, raw = _first_field(record, _BMP_PALETTE_NAMES)
                if found:
                    if isinstance(raw, (list, tuple)):
                        try:
                            count = len(raw)
                        except Exception:
                            count = None
                    else:
                        count = _header_int(raw)
                    if count is None:
                        record_notes.append(
                            "malformed BMP palette value for '%s'" % path
                        )
                    else:
                        found_c, raw_c = _first_field(
                            contract, ("palette_entries", "palette")
                        )
                        if found_c:
                            expected_count = _as_int(raw_c)
                        else:
                            expected_count = None
                        if expected_count is not None and count != expected_count:
                            details_by_code["integration.bmp_format"].append(
                                "'%s' palette_entries is %d, expected %d"
                                % (path, count, expected_count)
                            )
                            affected_by_code["integration.bmp_format"].append(
                                path
                            )
                orientation = _orientation_bottom_up(record)
                if orientation is not None:
                    found_c, raw_c = _first_field(
                        contract, ("bottom_up", "bottomup")
                    )
                    if found_c:
                        expected_up = _as_bool(raw_c)
                    else:
                        expected_up = None
                    if expected_up is not None and orientation != expected_up:
                        want = "bottom-up" if expected_up else "top-down"
                        got = "bottom-up" if orientation else "top-down"
                        details_by_code["integration.bmp_format"].append(
                            "'%s' orientation is %s, expected %s"
                            % (path, got, want)
                        )
                        affected_by_code["integration.bmp_format"].append(path)
    dds_map = _coerce_header_map(dds_headers, "DDS", record_notes)
    if dds_map is not None:
        dimensions = _coerce_map_dimensions(map_dimensions)
        for path, record in dds_map.items():
            if isinstance(
                record,
                (str, bytes, bool, int, float, list, tuple, set, frozenset),
            ):
                record_notes.append("malformed DDS header for '%s'" % path)
                continue
            if dimensions is not None:
                expected = _expected_size(
                    profile, "dds", path, dimensions[0], dimensions[1]
                )
                if expected is not None:
                    found_w, raw_w = _first_field(record, _WIDTH_NAMES)
                    found_h, raw_h = _first_field(record, _HEIGHT_NAMES)
                    width = _header_int(raw_w) if found_w else None
                    height = _header_int(raw_h) if found_h else None
                    if found_w and width is None:
                        record_notes.append("malformed DDS width for '%s'" % path)
                    if found_h and height is None:
                        record_notes.append(
                            "malformed DDS height for '%s'" % path
                        )
                    if (width is not None and width != expected[0]) or (
                        height is not None and height != expected[1]
                    ):
                        shown_w = width if width is not None else "?"
                        shown_h = height if height is not None else "?"
                        details_by_code["integration.dds_format"].append(
                            "'%s' is %sx%s, expected %dx%d"
                            % (path, shown_w, shown_h, expected[0], expected[1])
                        )
                        affected_by_code["integration.dds_format"].append(path)
            contract = _profile_contract(profile, "dds", path)
            if contract is not None:
                found, raw = _first_field(record, _DDS_FORMAT_NAMES)
                if found:
                    four_cc = _normalize_fourcc(raw)
                    if four_cc is None:
                        record_notes.append("malformed DDS format for '%s'" % path)
                    else:
                        found_c, raw_c = _first_field(
                            contract, ("four_cc", "fourcc", "format")
                        )
                        if found_c:
                            expected_cc = _normalize_fourcc(raw_c)
                        else:
                            expected_cc = None
                        if expected_cc is not None and four_cc != expected_cc:
                            details_by_code["integration.dds_format"].append(
                                "'%s' four_cc is '%s', expected '%s'"
                                % (path, four_cc, expected_cc)
                            )
                            affected_by_code["integration.dds_format"].append(
                                path
                            )
                found, raw = _first_field(record, _DDS_MIP_NAMES)
                if found:
                    mips = _header_int(raw)
                    if mips is None:
                        record_notes.append(
                            "malformed DDS mip_count for '%s'" % path
                        )
                    else:
                        found_c, raw_c = _first_field(
                            contract, ("mip_count", "mips")
                        )
                        expected_mips = _as_int(raw_c) if found_c else None
                        if expected_mips is not None and mips != expected_mips:
                            details_by_code["integration.dds_format"].append(
                                "'%s' mip_count is %d, expected %d"
                                % (path, mips, expected_mips)
                            )
                            affected_by_code["integration.dds_format"].append(
                                path
                            )
                found, raw = _first_field(record, _DDS_DX10_NAMES)
                if found:
                    dx10 = _as_bool(raw)
                    if dx10 is None:
                        record_notes.append(
                            "malformed DDS dx10 flag for '%s'" % path
                        )
                    else:
                        found_c, raw_c = _first_field(
                            contract, ("has_dx10_header", "dx10")
                        )
                        if found_c:
                            expected_dx10 = _as_bool(raw_c)
                        else:
                            expected_dx10 = None
                        if expected_dx10 is not None and dx10 != expected_dx10:
                            details_by_code["integration.dds_format"].append(
                                "'%s' has_dx10_header is %s, expected %s"
                                % (path, dx10, expected_dx10)
                            )
                            affected_by_code["integration.dds_format"].append(
                                path
                            )
            found_payload, raw_payload = _first_field(record, _DDS_PAYLOAD_NAMES)
            found_expected_size, raw_expected_size = _first_field(
                record, _DDS_EXPECTED_PAYLOAD_NAMES
            )
            actual_payload = None
            explicit_expected = None
            if found_payload:
                actual_payload = _as_int(raw_payload)
                if actual_payload is None or actual_payload < 0:
                    record_notes.append(
                        "malformed DDS payload_size for '%s'" % path
                    )
                    actual_payload = None
            if found_expected_size:
                explicit_expected = _as_int(raw_expected_size)
                if explicit_expected is None or explicit_expected < 0:
                    record_notes.append(
                        "malformed DDS expected_payload_size for '%s'" % path
                    )
                    explicit_expected = None
            if actual_payload is not None or explicit_expected is not None:
                found_w, raw_w = _first_field(record, _WIDTH_NAMES)
                found_h, raw_h = _first_field(record, _HEIGHT_NAMES)
                width = _header_int(raw_w) if found_w else None
                height = _header_int(raw_h) if found_h else None
                found_f, raw_f = _first_field(record, _DDS_FORMAT_NAMES)
                four_cc = _normalize_fourcc(raw_f) if found_f else None
                found_m, raw_m = _first_field(record, _DDS_MIP_NAMES)
                if found_m:
                    mips = _header_int(raw_m)
                else:
                    mips = 1
                derived = None
                if (
                    width is not None
                    and height is not None
                    and four_cc is not None
                    and mips is not None
                ):
                    derived = _expected_dds_payload_size(
                        width, height, four_cc, mips
                    )
                if derived is not None:
                    if actual_payload is not None:
                        if actual_payload != derived:
                            details_by_code["integration.dds_format"].append(
                                "'%s' payload_size is %d, expected %d"
                                % (path, actual_payload, derived)
                            )
                            affected_by_code["integration.dds_format"].append(
                                path
                            )
                    elif explicit_expected != derived:
                        details_by_code["integration.dds_format"].append(
                            "'%s' expected_payload_size is %d, expected %d"
                            % (path, explicit_expected, derived)
                        )
                        affected_by_code["integration.dds_format"].append(path)
                elif (
                    actual_payload is not None
                    and explicit_expected is not None
                    and actual_payload != explicit_expected
                ):
                    details_by_code["integration.dds_format"].append(
                        "'%s' payload_size is %d, expected %d"
                        % (path, actual_payload, explicit_expected)
                    )
                    affected_by_code["integration.dds_format"].append(path)

    descriptor_kind_normalized, descriptor_kind_note = _normalize_descriptor_kind(
        descriptor_kind
    )
    is_outer_descriptor = descriptor_kind_normalized == "outer"
    descriptor = _coerce_descriptor_text(descriptor_text, record_notes)
    if descriptor is not None:
        if descriptor_kind_note:
            record_notes.append(descriptor_kind_note)
        versions = _quoted_values(_SUPPORTED_RE, descriptor)
        names = _quoted_values(_NAME_RE, descriptor)
        declared = _quoted_values(_REPLACE_RE, descriptor)
        outer = _quoted_values(_PATH_RE, descriptor)
        target_version = _target_field(target, "supported_version")
        if not versions:
            details_by_code["integration.descriptor"].append(
                "descriptor text is missing supported_version"
            )
        else:
            if len(set(versions)) > 1:
                joined = ", ".join(
                    "'%s'" % item for item in sorted(set(versions))
                )
                details_by_code["integration.descriptor"].append(
                    "descriptor text declares multiple supported_version "
                    "values (%s)" % joined
                )
            active = versions[-1]
            if target_version is not None:
                if active != target_version:
                    details_by_code["integration.descriptor"].append(
                        "supported_version '%s' does not match target '%s'"
                        % (active, target_version)
                    )
            elif profile is not None and not isinstance(profile, (str, bytes)):
                if not _version_matches_profile(active, profile):
                    details_by_code["integration.descriptor"].append(
                        "supported_version '%s' does not match the game "
                        "profile" % active
                    )
        if not [name for name in names if name.strip()]:
            details_by_code["integration.descriptor"].append(
                "descriptor text is missing a name"
            )
        profile_replace = _profile_list(profile, "replace_paths")
        if profile_replace is not None:
            expected_set = set(profile_replace)
            declared_set = set()
            for item in declared:
                clean = _normalize_path(item)
                if clean:
                    declared_set.add(clean)
                else:
                    details_by_code["integration.descriptor"].append(
                        "descriptor text has an empty replace_path"
                    )
            for missing in sorted(expected_set - declared_set):
                details_by_code["integration.descriptor"].append(
                    "descriptor text is missing replace_path '%s'" % missing
                )
                affected_by_code["integration.descriptor"].append(missing)
            for extra in sorted(declared_set - expected_set):
                details_by_code["integration.descriptor"].append(
                    "descriptor text declares unexpected replace_path '%s'"
                    % extra
                )
                affected_by_code["integration.descriptor"].append(extra)
        for candidate in outer:
            if is_outer_descriptor:
                continue
            if _is_machine_path(candidate):
                details_by_code["integration.descriptor"].append(
                    "descriptor path '%s' is machine-specific"
                    % candidate.strip()
                )
        target_profile = _target_field(target, "profile_id")
        current_profile = _profile_id(profile)
        if target_profile and current_profile:
            if target_profile != current_profile:
                details_by_code["integration.descriptor"].append(
                    "target profile '%s' disagrees with game profile '%s'"
                    % (target_profile, current_profile)
                )

    vanilla, _vanilla_dups = _normalize_tag_input(vanilla_tags)
    dependency, _dependency_dups = _normalize_tag_input(dependency_tags)
    project, project_dups = _normalize_tag_input(project_tags)
    acceptance, acceptance_dups = _normalize_tag_input(acceptance_tags)
    if project or acceptance:
        collided = {}

        def _note(tag, reason):
            collided.setdefault(tag, []).append(reason)

        for tag in project:
            if tag in vanilla:
                _note(tag, "vanilla")
            if tag in dependency:
                _note(tag, "dependency")
        for tag in project_dups:
            _note(tag, "duplicate")
        for tag in acceptance:
            if tag in vanilla:
                _note(tag, "vanilla")
            if tag in dependency:
                _note(tag, "dependency")
            if tag in project:
                _note(tag, "project")
            if tag in _RESERVED_TAGS:
                _note(tag, "reserved")
        for tag in acceptance_dups:
            _note(tag, "duplicate")
        for tag in sorted(collided):
            reasons = "+".join(sorted(set(collided[tag])))
            details_by_code["integration.tag_collision"].append(
                "'%s' collides with %s" % (tag, reasons)
            )
            affected_by_code["integration.tag_collision"].append(tag)

    refs, ref_notes = _coerce_references(content_references)
    record_notes.extend(ref_notes)
    foundation = _coerce_foundation_set(foundation_ids)
    if refs is not None:
        missing = {}
        for ref_id, context in refs:
            if ref_id is None:
                record_notes.append(
                    "content reference in '%s' has no usable ID" % context
                )
                continue
            if not foundation:
                continue
            if ref_id not in foundation and ref_id not in missing:
                missing[ref_id] = context
        if foundation:
            for ref_id in sorted(missing, key=_sort_key):
                details_by_code["integration.missing_reference"].append(
                    "reference %s in '%s' has no foundation ID"
                    % (_display_id(ref_id), missing[ref_id])
                )
                affected_by_code["integration.missing_reference"].append(ref_id)

    if record_notes:
        details_by_code["integration.asset_record"].extend(record_notes)

    messages = {
        "integration.asset_disposition": "%d required asset resolutions "
        "are missing or unusable",
        "integration.asset_policy": "%d assets violate file policy",
        "integration.bmp_format": "%d BMP headers disagree with the "
        "profile contract",
        "integration.dds_format": "%d DDS headers disagree with the "
        "profile contract",
        "integration.descriptor": "descriptor text disagrees with "
        "ownership (%d problems)",
        "integration.tag_collision": "%d country tags collide",
        "integration.missing_reference": "%d content references lack "
        "foundation IDs",
        "integration.asset_record": "%d records could not be interpreted",
    }
    findings = []
    for code in CODES:
        details = details_by_code[code]
        if not details:
            continue
        affected = _sorted_capped(affected_by_code[code])
        findings.append(
            _finding(code, messages[code] % len(details), affected, _evidence(details))
        )
    return findings