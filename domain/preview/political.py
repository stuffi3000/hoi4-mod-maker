"""Political view layer — overlays national power colors on the preview basemap (original political map mode).

Effect: Main land = base map light and shadow × national color mixture, national borders are darkened into dark thin lines,
     Unclaimed Land/Sea keeps the base map as is - the same recipe as the in-game politics mode.
Applies to: Preview mode "Political View" switch.
Call: apply_political_layer(base, country_rgb, owned_mask) → RGB uint8.
Formula calibration: Use the original full-image data for actual measurement control (scratchpad political_sample), mix=0.62."""

from __future__ import annotations

import numpy as np

# National color mixing weight (0=pure base map, 1=pure color block); 0.62 is the closest to the original look and feel in actual measurements
POLITICAL_MIX = 0.62
# National border darkening coefficient (the original version is a dark thin line)
BORDER_DIM = 0.35


def apply_political_layer(
    base: np.ndarray,
    country_rgb: np.ndarray | None,
    owned_mask: np.ndarray | None,
    mix: float = POLITICAL_MIX,
    border_dim: float = BORDER_DIM,
) -> np.ndarray:
    """Basemap (H, W, 3 RGB) + country colormap/with master mask → political view RGB uint8.

    When country_rgb/owned_mask is None, the basemap is returned unchanged (no country data can be overlaid)."""
    if country_rgb is None or owned_mask is None or not owned_mask.any():
        return base

    basef = base.astype(np.float32)
    out = basef.copy()
    blend = basef * (1.0 - mix) + country_rgb.astype(np.float32) * mix
    out[owned_mask] = blend[owned_mask]

    # National border: adjacent pixels have different national colors and at least one side has a dominant → darken
    oc = np.where(owned_mask[..., None], country_rgb, 0).astype(np.int32)
    border = np.zeros(owned_mask.shape, dtype=bool)
    diff_v = (oc[:-1] != oc[1:]).any(axis=2) & (owned_mask[:-1] | owned_mask[1:])
    border[:-1][diff_v] = True
    diff_h = (oc[:, :-1] != oc[:, 1:]).any(axis=2) & (owned_mask[:, :-1] | owned_mask[:, 1:])
    border[:, :-1][diff_h] = True
    out[border] *= border_dim

    return np.clip(out, 0, 255).astype(np.uint8)
