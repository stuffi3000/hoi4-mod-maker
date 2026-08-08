from views.main_window_file_ops import _find_vanilla_reference


def test_find_vanilla_reference_prefers_provinces(tmp_path):
    provinces = tmp_path / "map" / "provinces.bmp"
    colormap = (
        tmp_path
        / "map"
        / "terrain"
        / "colormap_rgb_cityemissivemask_a.dds"
    )
    provinces.parent.mkdir(parents=True)
    provinces.write_bytes(b"provinces")
    colormap.parent.mkdir(parents=True)
    colormap.write_bytes(b"colormap")

    assert _find_vanilla_reference(str(tmp_path)) == str(provinces)


def test_find_vanilla_reference_falls_back_to_colormap(tmp_path):
    colormap = (
        tmp_path
        / "map"
        / "terrain"
        / "colormap_rgb_cityemissivemask_a.dds"
    )
    colormap.parent.mkdir(parents=True)
    colormap.write_bytes(b"colormap")

    assert _find_vanilla_reference(str(tmp_path)) == str(colormap)


def test_find_vanilla_reference_rejects_missing_directory(tmp_path):
    assert _find_vanilla_reference(None) is None
    assert _find_vanilla_reference(str(tmp_path)) is None
