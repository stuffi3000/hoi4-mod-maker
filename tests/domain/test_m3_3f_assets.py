"""M3.3f asset/integration validation slice tests (no game install)."""
from __future__ import annotations

import copy
import dataclasses
from types import SimpleNamespace

import pytest

from domain.export_contract import AssetResolution, RESERVED_ACCEPTANCE_TAGS
from domain.game_profile import BmpContract, DdsContract, GameProfile
from domain.validation import FINDING_SEVERITIES
from domain.validators.assets import CODES, LAYER, validate_asset_integration

pytestmark = pytest.mark.unit


def _clean_profile():
    return GameProfile(
        profile_id="hoi4-1.19",
        display_name="test profile",
        game_versions=["1.19.3.0"],
        supported_version_pattern="1.19.*",
        bmp={
            "map/terrain.bmp": BmpContract(
                width_divisor=1,
                height_divisor=1,
                bits_per_pixel=8,
                compression="BI_RGB",
                bottom_up=True,
                palette_entries=255,
            ),
            "map/provinces.bmp": BmpContract(
                width_divisor=1,
                height_divisor=1,
                bits_per_pixel=24,
                compression="BI_RGB",
                bottom_up=True,
                palette_entries=0,
            ),
        },
        dds={
            "map/terrain/colormap_water_0.dds": DdsContract(
                width_divisor=2,
                height_divisor=2,
                four_cc="DXT5",
                mip_count=1,
                has_dx10_header=False,
            ),
        },
        required_files=["map/provinces.bmp", "map/terrain.bmp"],
        optional_files=["map/cities.bmp"],
        deprecated_files=["map/colors.txt"],
        inherited_files=["common/terrain/00_terrain.txt"],
        replace_paths=["history/states"],
    )


def _clean_descriptor():
    return (
        'version="0.1"\n'
        'tags={\n\t"Map"\n}\n'
        'name="Test Mod"\n'
        'supported_version="1.19.3.0"\n'
        'replace_path="history/states"\n'
    )


def _clean_kwargs():
    return {
        "profile": _clean_profile(),
        "target": SimpleNamespace(
            supported_version="1.19.3.0", profile_id="hoi4-1.19"
        ),
        "asset_resolutions": [
            AssetResolution("map/provinces.bmp", "generated"),
            AssetResolution("map/terrain.bmp", "preserved"),
            {"rel_path": "map/cities.bmp", "disposition": "omitted"},
            {"rel_path": "map/colors.txt", "disposition": "omitted"},
            {
                "rel_path": "common/terrain/00_terrain.txt",
                "disposition": "inherited",
            },
        ],
        "output_files": ["map/provinces.bmp", "map/terrain.bmp"],
        "assets": {"map/terrain.bmp": b"fake-bytes"},
        "dirty_assets": [],
        "bmp_headers": {
            "map/terrain.bmp": {
                "width": 256,
                "height": 128,
                "bits_per_pixel": 8,
                "compression": "BI_RGB",
                "palette_entries": 255,
                "bottom_up": True,
            },
            "map/provinces.bmp": {
                "width": 256,
                "height": 128,
                "bits_per_pixel": 24,
                "compression": "BI_RGB",
                "bottom_up": True,
            },
        },
        "dds_headers": {
            "map/terrain/colormap_water_0.dds": {
                "width": 128,
                "height": 64,
                "four_cc": "DXT5",
                "mip_count": 1,
                "has_dx10_header": False,
            },
        },
        "map_dimensions": (256, 128),
        "descriptor_text": _clean_descriptor(),
        "vanilla_tags": ("GER", "FRA"),
        "dependency_tags": ("ABC",),
        "project_tags": ("AAA",),
        "acceptance_tags": ("QAA",),
        "foundation_ids": (1, 2, 3),
        "content_references": {
            "states": [1, 2],
            "capitals": [{"id": 3, "kind": "capital"}],
        },
    }


def _codes(findings):
    return [item.code for item in findings]


def _by_code(findings):
    grouped = {}
    for item in findings:
        grouped.setdefault(item.code, []).append(item)
    return grouped


def test_clean_data_has_no_findings():
    assert validate_asset_integration(**_clean_kwargs()) == []


def test_mapping_and_object_records_supported():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = {
        "map/provinces.bmp": "generated",
        "map/terrain.bmp": {"disposition": "preserved"},
        "map/cities.bmp": "omitted",
        "map/colors.txt": "omitted",
        "common/terrain/00_terrain.txt": AssetResolution(
            "common/terrain/00_terrain.txt", "inherited"
        ),
    }
    kwargs["bmp_headers"] = {
        "map/terrain.bmp": SimpleNamespace(
            width=256,
            height=128,
            bits_per_pixel=8,
            compression="BI_RGB",
            palette_entries=255,
            bottom_up=True,
        ),
        "map/provinces.bmp": SimpleNamespace(
            width=256, height=128, bits=24, compression=0, bottom_up=True
        ),
    }
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": SimpleNamespace(
            width=128, height=64, format="BC3/DXT5", mips=1, dx10=False
        )
    }
    kwargs["target"] = {
        "supported_version": "1.19.3.0",
        "profile_id": "hoi4-1.19",
    }
    kwargs["content_references"] = [
        {"province_id": 1},
        {"id": 2, "kind": "capital"},
        3,
    ]
    assert validate_asset_integration(**kwargs) == []


def test_missing_required_resolutions():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = []
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    item = findings[0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (
        "map/provinces.bmp",
        "map/terrain.bmp",
    )
    assert "has no resolution" in item.evidence


def test_illegal_dispositions():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = [
        {"rel_path": "map/provinces.bmp", "disposition": "omitted"},
        {"rel_path": "map/terrain.bmp", "disposition": "unsupported"},
    ]
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    item = findings[0]
    assert "is omitted" in item.evidence
    assert "is unsupported" in item.evidence
    kwargs["asset_resolutions"] = [
        {"rel_path": "map/provinces.bmp", "disposition": "teleported"},
        AssetResolution("map/terrain.bmp", "generated"),
    ]
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    assert "illegal disposition" in findings[0].evidence
    assert "teleported" in findings[0].evidence

def test_deprecated_and_inherited_policy():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = [
        AssetResolution("map/provinces.bmp", "generated"),
        AssetResolution("map/terrain.bmp", "generated"),
        {"rel_path": "map/colors.txt", "disposition": "generated"},
        {"rel_path": "map/cities.bmp", "disposition": "inherited"},
    ]
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_policy"]
    item = findings[0]
    assert item.severity == "error"
    assert "deprecated" in item.evidence
    assert "without profile permission" in item.evidence
    assert tuple(item.affected_ids) == ("map/cities.bmp", "map/colors.txt")


def test_unknown_disposition_on_optional_path_is_record_problem():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = [
        AssetResolution("map/provinces.bmp", "generated"),
        AssetResolution("map/terrain.bmp", "generated"),
        {"rel_path": "map/cities.bmp", "disposition": "teleported"},
    ]
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_record"]
    assert "unknown disposition" in findings[0].evidence


def test_omitted_optionals_and_replace_prefix_inheritance_ok():
    profile = GameProfile(
        profile_id="hoi4-1.19",
        required_files=["history/states"],
        optional_files=["map/cities.bmp"],
        deprecated_files=["map/colors.txt"],
        inherited_files=[],
        replace_paths=["history/states"],
    )
    resolutions = [
        AssetResolution("history/states", "inherited"),
        {"rel_path": "history/states/7.txt", "disposition": "inherited"},
        {"rel_path": "map/cities.bmp", "disposition": "omitted"},
        {"rel_path": "map/colors.txt", "disposition": "omitted"},
    ]
    assert validate_asset_integration(
        profile=profile, asset_resolutions=resolutions
    ) == []


def test_bmp_mismatches():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = [
        AssetResolution("map/provinces.bmp", "generated"),
        AssetResolution("map/terrain.bmp", "generated"),
    ]
    kwargs["output_files"] = ["map/provinces.bmp", "map/terrain.bmp"]
    kwargs["bmp_headers"] = {
        "map/terrain.bmp": {
            "width": 100,
            "height": 100,
            "bits_per_pixel": 24,
            "compression": "BI_RLE8",
            "palette_entries": 16,
            "bottom_up": False,
        },
    }
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.bmp_format"]
    item = findings[0]
    assert tuple(item.affected_ids) == ("map/terrain.bmp",)
    assert "expected 256x128" in item.evidence
    assert "expected 8" in item.evidence
    assert "BI_RGB" in item.evidence
    assert "expected 255" in item.evidence
    assert "bottom-up" in item.evidence


def test_dds_mismatches_and_aliases():
    kwargs = _clean_kwargs()
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": {
            "width": 64,
            "height": 64,
            "four_cc": "DXT1",
            "mip_count": 4,
            "has_dx10_header": True,
        },
    }
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.dds_format"]
    item = findings[0]
    assert "expected 128x64" in item.evidence
    assert "DXT5" in item.evidence
    assert "expected 1" in item.evidence
    assert "False" in item.evidence
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": {
            "width": 128,
            "height": 64,
            "four_cc": "BC3",
            "mip_count": 1,
            "has_dx10_header": False,
        },
    }
    assert validate_asset_integration(**kwargs) == []


def test_absent_header_metadata_tolerated():
    kwargs = _clean_kwargs()
    kwargs["bmp_headers"] = {"map/terrain.bmp": {}, "map/unknown.bmp": None}
    kwargs["dds_headers"] = {}
    kwargs["map_dimensions"] = None
    assert validate_asset_integration(**kwargs) == []
    assert validate_asset_integration(bmp_headers=None, dds_headers=None) == []
    assert validate_asset_integration(profile=None, bmp_headers={}, dds_headers={}) == []

def test_descriptor_problems():
    kwargs = _clean_kwargs()
    kwargs["target"] = SimpleNamespace(
        supported_version="1.19.9.9", profile_id="hoi4-1.19"
    )
    kwargs["descriptor_text"] = (
        'tags={\n\t"Map"\n}\n'
        'supported_version="1.19.3.0"\n'
        'replace_path="history/states"\n'
        'replace_path="map/old"\n'
        'path="C:/Users/tester/Documents/mod"\n'
    )
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.descriptor"]
    item = findings[0]
    assert "does not match target" in item.evidence
    assert "missing a name" in item.evidence
    assert "unexpected replace_path 'map/old'" in item.evidence
    assert "machine-specific" in item.evidence
    assert tuple(item.affected_ids) == ("map/old",)


def test_descriptor_version_matches_profile_pattern_without_target():
    kwargs = _clean_kwargs()
    kwargs["target"] = None
    kwargs["descriptor_text"] = (
        'name="Test Mod"\n'
        'supported_version="1.18.0"\n'
        'replace_path="history/states"\n'
    )
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.descriptor"]
    assert "does not match the game profile" in findings[0].evidence
    kwargs["descriptor_text"] = (
        'name="Test Mod"\n'
        'supported_version="1.19.7.3"\n'
        'replace_path="history/states"\n'
    )
    assert validate_asset_integration(**kwargs) == []


def test_descriptor_missing_replace_path():
    kwargs = _clean_kwargs()
    profile = _clean_profile()
    profile = dataclasses.replace(
        profile, replace_paths=["history/states", "history/countries"]
    )
    kwargs["profile"] = profile
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.descriptor"]
    assert "missing replace_path 'history/countries'" in findings[0].evidence


def test_descriptor_absent_skipped():
    kwargs = _clean_kwargs()
    kwargs["descriptor_text"] = None
    findings = validate_asset_integration(**kwargs)
    assert "integration.descriptor" not in _codes(findings)
    assert validate_asset_integration(descriptor_text="  \n ") == []


def test_tag_collisions():
    reserved = sorted(RESERVED_ACCEPTANCE_TAGS)[0]
    kwargs = _clean_kwargs()
    kwargs["project_tags"] = ("AAA", "ger", "ABC", "AAA")
    kwargs["acceptance_tags"] = ("QAA", "fra", "AAA", reserved, "QAA")
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.tag_collision"]
    item = findings[0]
    assert "GER" in item.evidence
    assert "FRA" in item.evidence
    assert "ABC" in item.evidence
    assert "AAA" in item.evidence
    assert reserved in item.evidence
    assert "duplicate" in item.evidence
    assert tuple(item.affected_ids) == tuple(
        sorted(("AAA", "ABC", "FRA", "GER", "QAA", reserved))
    )
    clean = _clean_kwargs()
    assert validate_asset_integration(**clean) == []


def test_missing_references():
    kwargs = _clean_kwargs()
    kwargs["foundation_ids"] = (1, 2, 3)
    kwargs["content_references"] = {
        "states": [1, 99],
        "regions": [{"province_id": 100, "kind": "exclave"}, {"id": 2}],
        "single": 101,
    }
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.missing_reference"]
    item = findings[0]
    assert tuple(item.affected_ids) == (99, 100, 101)
    assert "exclave" in item.evidence
    flat = validate_asset_integration(
        foundation_ids=(1, 2), content_references=[1, 2, 7]
    )
    assert _codes(flat) == ["integration.missing_reference"]
    assert tuple(flat[0].affected_ids) == (7,)


def test_references_skipped_without_foundation():
    findings = validate_asset_integration(
        foundation_ids=(), content_references={"states": [1, 99]}
    )
    assert "integration.missing_reference" not in _codes(findings)
    assert validate_asset_integration(foundation_ids=(1,)) == []


def test_output_and_asset_consistency():
    kwargs = _clean_kwargs()
    kwargs["assets"] = {}
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    assert "has no stored bytes" in findings[0].evidence
    kwargs = _clean_kwargs()
    kwargs["dirty_assets"] = ["map/terrain.bmp"]
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    assert "marked dirty" in findings[0].evidence
    kwargs = _clean_kwargs()
    kwargs["output_files"] = ["map/terrain.bmp"]
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    assert "has no staged output file" in findings[0].evidence
    assert tuple(findings[0].affected_ids) == ("map/provinces.bmp",)


def test_deterministic_output_order_and_caps():
    kwargs = _clean_kwargs()
    first = validate_asset_integration(**kwargs)
    second = validate_asset_integration(**_clean_kwargs())
    assert first == second
    assert [item.to_dict() for item in first] == [
        item.to_dict() for item in second
    ]
    bad = _clean_kwargs()
    bad["asset_resolutions"] = []
    bad["descriptor_text"] = "name=\n"
    bad["acceptance_tags"] = ("GER",)
    bad["content_references"] = {"states": [99]}
    findings = validate_asset_integration(**bad)
    codes = _codes(findings)
    assert codes == sorted(codes, key=CODES.index)
    assert codes == [
        "integration.asset_disposition",
        "integration.descriptor",
        "integration.tag_collision",
        "integration.missing_reference",
    ]
    capped = validate_asset_integration(
        foundation_ids=(1,), content_references={"group": list(range(2, 100))}
    )
    assert _codes(capped) == ["integration.missing_reference"]
    assert len(capped[0].affected_ids) == 64
    assert tuple(capped[0].affected_ids) == tuple(range(2, 66))
    assert capped[0].affected_ids == tuple(
        sorted(capped[0].affected_ids, key=lambda value: (0, "", value))
    )


def test_no_input_mutation():
    kwargs = _clean_kwargs()
    snapshot = copy.deepcopy(kwargs)
    validate_asset_integration(**kwargs)
    assert kwargs == snapshot


def test_malformed_records_do_not_raise():
    findings = validate_asset_integration(
        profile=_clean_profile(),
        asset_resolutions=[42, None, {}, {"rel_path": "lonely"}],
        bmp_headers={"map/terrain.bmp": 7},
        dds_headers=[("map/x.dds", {})],
        output_files=5,
        assets=["not-a-mapping"],
        content_references=[{"foo": 1}],
        foundation_ids=(1,),
    )
    assert "integration.asset_record" in _codes(findings)
    record = _by_code(findings)["integration.asset_record"][0]
    assert record.severity == "error"
    assert record.message == "9 records could not be interpreted"
    lonely = validate_asset_integration(
        content_references=[{"foo": 1}], foundation_ids=(1,)
    )
    assert _codes(lonely) == ["integration.asset_record"]
    assert "no usable ID" in lonely[0].evidence
    assert "integration.asset_record" in _codes(
        validate_asset_integration(asset_resolutions="just-a-string")
    )
    assert _codes(validate_asset_integration(content_references=True)) == [
        "integration.asset_record"
    ]


def test_absent_optional_inputs():
    assert validate_asset_integration() == []
    assert validate_asset_integration(profile=_clean_profile()) == []
    assert validate_asset_integration(asset_resolutions=[]) == []
    assert validate_asset_integration(
        profile=_clean_profile(), asset_resolutions=None
    ) == []


def test_finding_metadata_valid():
    kwargs = _clean_kwargs()
    kwargs["asset_resolutions"] = []
    kwargs["descriptor_text"] = "broken"
    kwargs["acceptance_tags"] = ("GER", "GER")
    kwargs["content_references"] = {"states": [99]}
    findings = validate_asset_integration(**kwargs)
    assert findings
    assert set(_codes(findings)) <= set(CODES)
    for item in findings:
        assert item.code.startswith("integration.")
        assert item.severity in FINDING_SEVERITIES
        assert item.layer == LAYER == "integration"
        assert isinstance(item.waivable, bool)
        assert tuple(item.coordinates) == ()
        assert item.message
        assert item.evidence


def test_extra_kwargs_ignored_for_registry_compatibility():
    kwargs = _clean_kwargs()
    kwargs["tile_map"] = None
    kwargs["province_map"] = None
    kwargs["definitions"] = {}
    assert validate_asset_integration(**kwargs) == []

def test_preserved_empty_bytes_not_usable():
    kwargs = _clean_kwargs()
    kwargs["assets"] = {"map/terrain.bmp": b""}
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    assert "has no stored bytes" in findings[0].evidence
    assert tuple(findings[0].affected_ids) == ("map/terrain.bmp",)
    kwargs = _clean_kwargs()
    kwargs["assets"] = {"map/terrain.bmp": None}
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    assert "has no stored bytes" in findings[0].evidence
    kwargs = _clean_kwargs()
    kwargs["assets"] = {"map/terrain.bmp": bytearray()}
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.asset_disposition"]
    kwargs = _clean_kwargs()
    kwargs["assets"] = {"map/terrain.bmp": b"x"}
    assert validate_asset_integration(**kwargs) == []
    kwargs = _clean_kwargs()
    kwargs["assets"] = {"map/terrain.bmp": {"bytes": b"x"}}
    assert validate_asset_integration(**kwargs) == []
    kwargs = _clean_kwargs()
    kwargs["assets"] = {"map/terrain.bmp": SimpleNamespace(data=b"x")}
    assert validate_asset_integration(**kwargs) == []


def test_descriptor_kind_outer_allows_absolute_path():
    outer_text = (
        'name="Test Mod"\n'
        'supported_version="1.19.3.0"\n'
        'replace_path="history/states"\n'
        'path="C:/Users/tester/Documents/mod"\n'
    )
    kwargs = _clean_kwargs()
    kwargs["descriptor_text"] = outer_text
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.descriptor"]
    assert "machine-specific" in findings[0].evidence
    explicit = dict(kwargs)
    explicit["descriptor_kind"] = "internal"
    findings = validate_asset_integration(**explicit)
    assert _codes(findings) == ["integration.descriptor"]
    assert "machine-specific" in findings[0].evidence
    outer_kwargs = dict(kwargs)
    outer_kwargs["descriptor_kind"] = "outer"
    assert validate_asset_integration(**outer_kwargs) == []
    bad_name = _clean_kwargs()
    bad_name["descriptor_text"] = (
        'supported_version="1.19.3.0"\n'
        'replace_path="history/states"\n'
        'path="C:/abs/mod"\n'
    )
    bad_name["descriptor_kind"] = "outer"
    findings = validate_asset_integration(**bad_name)
    assert _codes(findings) == ["integration.descriptor"]
    assert "missing a name" in findings[0].evidence
    assert "machine-specific" not in findings[0].evidence
    unknown = dict(kwargs)
    unknown["descriptor_kind"] = "bogus"
    findings = validate_asset_integration(**unknown)
    assert "integration.descriptor" in _codes(findings)
    assert "integration.asset_record" in _codes(findings)


def test_dds_payload_size_clean_and_mismatch():
    kwargs = _clean_kwargs()
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": {
            "width": 128,
            "height": 64,
            "four_cc": "DXT5",
            "mip_count": 1,
            "has_dx10_header": False,
            "payload_size": 8192,
        },
    }
    assert validate_asset_integration(**kwargs) == []
    kwargs["dds_headers"]["map/terrain/colormap_water_0.dds"]["four_cc"] = "BC3"
    assert validate_asset_integration(**kwargs) == []
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": {
            "width": 128,
            "height": 64,
            "four_cc": "DXT5",
            "mip_count": 1,
            "has_dx10_header": False,
            "payload_size": 8193,
        },
    }
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.dds_format"]
    assert "payload_size is 8193, expected 8192" in findings[0].evidence
    assert tuple(findings[0].affected_ids) == (
        "map/terrain/colormap_water_0.dds",
    )
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": {
            "width": 128,
            "height": 64,
            "four_cc": "DXT5",
            "mip_count": 1,
            "has_dx10_header": False,
            "expected_payload_size": 8192,
        },
    }
    assert validate_asset_integration(**kwargs) == []
    kwargs["dds_headers"]["map/terrain/colormap_water_0.dds"][
        "expected_payload_size"
    ] = 100
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.dds_format"]
    assert "expected 8192" in findings[0].evidence
    assert validate_asset_integration(**_clean_kwargs()) == []
    findings = validate_asset_integration(
        dds_headers={
            "map/extra.dds": {
                "width": 64,
                "height": 64,
                "four_cc": "UNKNOWN_FMT",
                "mip_count": 1,
                "payload_size": 12345,
            }
        }
    )
    assert findings == []
    malformed = validate_asset_integration(
        dds_headers={
            "map/terrain/colormap_water_0.dds": {
                "width": 128,
                "height": 64,
                "four_cc": "DXT5",
                "mip_count": 1,
                "payload_size": "not-a-number",
            }
        }
    )
    assert _codes(malformed) == ["integration.asset_record"]
    assert "payload_size" in malformed[0].evidence


def test_dds_payload_size_mipmaps():
    kwargs = _clean_kwargs()
    kwargs["dds_headers"] = {
        "map/terrain/colormap_water_0.dds": {
            "width": 8,
            "height": 8,
            "four_cc": "DXT1",
            "mip_count": 3,
            "has_dx10_header": False,
            "payload_size": 48,
        },
    }
    kwargs["map_dimensions"] = None
    kwargs["profile"] = None
    assert validate_asset_integration(**kwargs) == []
    kwargs["dds_headers"]["map/terrain/colormap_water_0.dds"][
        "payload_size"
    ] = 40
    findings = validate_asset_integration(**kwargs)
    assert _codes(findings) == ["integration.dds_format"]
    assert "payload_size is 40, expected 48" in findings[0].evidence


def test_malformed_references_reported_without_foundation():
    findings = validate_asset_integration(
        content_references=[{"foo": 1}], foundation_ids=()
    )
    assert _codes(findings) == ["integration.asset_record"]
    assert "no usable ID" in findings[0].evidence
    assert "integration.missing_reference" not in _codes(findings)
    findings = validate_asset_integration(
        foundation_ids=(), content_references={"states": [1, 99]}
    )
    assert findings == []
    findings = validate_asset_integration(content_references=True)
    assert _codes(findings) == ["integration.asset_record"]
