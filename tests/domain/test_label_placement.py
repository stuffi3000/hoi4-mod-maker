"""label_placement unit test — centroid/principal axis/connected block splitting"""
import numpy as np

from domain.label_placement import compute_region_labels


def test_empty_map():
    assert compute_region_labels(np.zeros((50, 80), dtype=np.int32)) == {}


def test_horizontal_rect_centroid_and_angle():
    m = np.zeros((100, 200), dtype=np.int32)
    m[40:60, 20:180] = 7  # Horizontal strip
    out = compute_region_labels(m, min_pixels=50)
    assert set(out) == {7}
    assert len(out[7]) == 1
    cx, cy, angle, length, width = out[7][0]
    assert abs(cx - 99.5) < 1.0
    assert abs(cy - 49.5) < 1.0
    assert abs(angle) < 5.0          # Spindle nearly horizontal
    assert length > width            # Long axis > Short axis


def test_vertical_strip_angle():
    m = np.zeros((200, 100), dtype=np.int32)
    m[20:180, 40:60] = 3  # vertical strip
    out = compute_region_labels(m, min_pixels=50)
    _, _, angle, length, width = out[3][0]
    assert abs(abs(angle) - 90.0) < 5.0  # Spindle nearly vertical
    assert length > width


def test_each_component_gets_label_largest_first():
    m = np.zeros((100, 300), dtype=np.int32)
    m[10:20, 10:20] = 5            # Island 100px
    m[40:90, 100:280] = 5          # Native 9000px
    out = compute_region_labels(m, min_pixels=50)
    assert len(out[5]) == 2        # Each block has a name
    cx, cy, _, _, _ = out[5][0]    # chunk first → native
    assert 100 <= cx <= 280
    assert 40 <= cy <= 90
    cx2, cy2, _, _, _ = out[5][1]  # island
    assert 10 <= cx2 <= 20
    assert 10 <= cy2 <= 20


def test_split_by_neighbor_land_not_merged():
    # The same area is cut in half by another area of land (same continent enclave):
    # The names must be one block at a time and cannot traverse the middle neighborhood according to the overall centroid.
    m = np.zeros((100, 300), dtype=np.int32)
    m[20:80, 10:100] = 1     # Area 1 left block
    m[20:80, 100:200] = 2    # Area 2 Sandwiched in the middle
    m[20:80, 200:290] = 1    # Area 1 right block
    out = compute_region_labels(m, min_pixels=50)
    assert len(out[1]) == 2
    assert len(out[2]) == 1
    xs = sorted(p[0] for p in out[1])
    assert xs[0] < 100          # The center of mass of the left block is within the left block
    assert xs[1] > 200          # The center of mass of the right block is within the right block
    assert 100 < out[2][0][0] < 200


def test_min_pixels_filter():
    m = np.zeros((100, 100), dtype=np.int32)
    m[10:12, 10:12] = 9  # 4 pixels
    assert compute_region_labels(m, min_pixels=50) == {}


def test_min_pixels_filters_small_component_only():
    m = np.zeros((100, 300), dtype=np.int32)
    m[10:13, 10:13] = 5            # 9px fragment, below threshold
    m[40:90, 100:280] = 5          # local
    out = compute_region_labels(m, min_pixels=50)
    assert len(out[5]) == 1        # The pieces have no name


def test_two_regions():
    m = np.zeros((100, 200), dtype=np.int32)
    m[10:40, 10:90] = 1
    m[60:90, 110:190] = 2
    out = compute_region_labels(m, min_pixels=50)
    assert set(out) == {1, 2}
    assert out[1][0][0] < 100 < out[2][0][0]
