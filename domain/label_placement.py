"""Name tag layout — Calculate text position/angle/size for each region (state/country).

Effect: Imitate the HOI4 map name - put a name on each connected block in the area,
     The text is tilted along the main axis of the pixel distribution within the block. The larger the block, the greater the available text length.
Applies to: Name overlays for state/country patterns. Pure numpy+scipy, zero Qt.
Call: compute_region_labels(id_map) → {id: [(cx, cy, angle°, major axis, minor axis), ...]}"""
import numpy as np
from scipy.ndimage import label as _cc_label


def compute_region_labels(
    id_map: np.ndarray,
    min_pixels: int = 300,
) -> dict[int, list[tuple[float, float, float, float, float]]]:
    """Area id map → label layout parameters for each id (one for each connected block).

    id_map: (H, W) integer map, 0 = unowned (ocean/unallocated), >0 = region id.
    min_pixels: Connected blocks smaller than this number of pixels will not be labeled (too small to fit the words).

    Return {id: [(cx, cy, angle_deg, length, width), ...]}, chunk first:
      cx/cy — center of mass of the connected block (full graph coordinates)
      angle_deg — main axis inclination angle, [-90, 90), clockwise is positive (Qt scene coordinate system)
      length — available length along the main axis (pixels)
      width — available width of the vertical main axis in pixels

    Implementation: Connectivity is determined by id - enclaves separated by other countries' landmasses are independent blocks,
    Each gets a name (directly marking >0 with a binary value will glue enclaves on the same continent into
    (one piece, the name will cross neighboring countries). The method is to enlarge the downsampled image 3×, only in the same
    Connecting strips are laid between adjacent pixels of id, and once CC is disconnected according to the id boundary; first and second order moments
    All connected blocks are calculated in one bincount → centroid + PCA main axis. None in the whole process
    Scanning the image area by area, the time consumption has nothing to do with the number of areas/number of fragments."""
    h, w = id_map.shape
    max_id = int(id_map.max())
    if max_id <= 0:
        return {}

    # Downsampling: Label layout does not require pixel-by-pixel precision, large images are sampled to ~512 high
    step = max(1, min(h, w) // 512)
    sub = id_map[::step, ::step]
    sub_min = max(1, min_pixels // (step * step))
    sh, sw = sub.shape
    fg = sub > 0

    # 3× magnification: the center point is placed at (3i+1, 3j+1), between adjacent centers with the same id
    # Spread 2 connected pixels → 4 connected CCs automatically disconnect at id boundaries
    big = np.zeros((sh * 3, sw * 3), dtype=bool)
    big[1::3, 1::3] = fg
    same_r = fg[:, :-1] & (sub[:, :-1] == sub[:, 1:])   # Right neighbor with same id
    big[1::3, 2::3][:, :-1] = same_r
    big[1::3, 3::3] = same_r
    same_d = fg[:-1, :] & (sub[:-1, :] == sub[1:, :])   # The next neighbor has the same id
    big[2::3, 1::3][:-1, :] = same_d
    big[3::3, 1::3] = same_d

    comp3, ncomp = _cc_label(big)
    if ncomp == 0:
        return {}
    comp = comp3[1::3, 1::3]            # Back to sub size, 0 = background
    flat = comp.ravel().astype(np.int64)
    counts = np.bincount(flat, minlength=ncomp + 1)
    # Which id does each connected block belong to (if the id within the block is the same, just pick any pixel)
    comp_id = np.zeros(ncomp + 1, dtype=np.int64)
    comp_id[flat] = sub.ravel()

    keep = np.nonzero((counts >= sub_min) & (comp_id > 0))[0]
    if keep.size == 0:
        return {}
    keep = keep[np.argsort(-counts[keep], kind="stable")]  # chunk first

    # First and second moments: All connected blocks are calculated in one bincount, and the map is not scanned block by block.
    yy, xx = np.mgrid[0:sh, 0:sw]
    fx = xx.ravel().astype(np.float64)
    fy = yy.ravel().astype(np.float64)
    n_bins = ncomp + 1
    sx = np.bincount(flat, weights=fx, minlength=n_bins)
    sy = np.bincount(flat, weights=fy, minlength=n_bins)
    sxx = np.bincount(flat, weights=fx * fx, minlength=n_bins)
    syy = np.bincount(flat, weights=fy * fy, minlength=n_bins)
    sxy = np.bincount(flat, weights=fx * fy, minlength=n_bins)

    out: dict[int, list[tuple[float, float, float, float, float]]] = {}
    for c in keep:
        n = counts[c]
        mx = sx[c] / n
        my = sy[c] / n
        cxx = sxx[c] / n - mx * mx
        cyy = syy[c] / n - my * my
        cxy = sxy[c] / n - mx * my
        # 2×2 covariance eigenvalue → primary/secondary axis variance
        tr_half = (cxx + cyy) / 2.0
        det_root = np.sqrt(max(((cxx - cyy) / 2.0) ** 2 + cxy * cxy, 0.0))
        lam1 = max(tr_half + det_root, 1e-6)
        lam2 = max(tr_half - det_root, 1e-6)
        angle = float(np.degrees(0.5 * np.arctan2(2.0 * cxy, cxx - cyy)))
        if angle >= 90.0:
            angle -= 180.0
        elif angle < -90.0:
            angle += 180.0
        # Uniform distribution approximation: full length ≈ 3.46σ, leaving some margins at 3.4
        length = 3.4 * float(np.sqrt(lam1)) * step
        width = 3.4 * float(np.sqrt(lam2)) * step
        out.setdefault(int(comp_id[c]), []).append(
            (mx * step, my * step, angle, length, width)
        )
    return out
