"""Night scene layer — simulates game night: darken the entire image + city lights in urban terrain.

Effect: The base map is turned into night color by the cold color coefficient, and the pixels of the urban terrain are lit up.
     Warm yellow light + gaussian glow — light position and exported colormap alpha city
     The lighting masks have the same origin (both come from urban terrain), and what you see in the preview is the night side of the game.
Applicable to: preview mode "night scene" switch. Pure numpy+scipy, zero Qt.
Call: apply_night_layer(rgb, terrain_map) → new (H, W, 3) uint8"""
import numpy as np

# Night color: multiplication coefficient per channel (bluish moonlight)
NIGHT_FACTOR = np.array([0.22, 0.26, 0.42], dtype=np.float32)
# City lights: warm yellow
LIGHT_RGB = np.array([255.0, 214.0, 130.0], dtype=np.float32)
LIGHT_HALO_SIGMA = 3.0
LIGHT_STRENGTH = 0.9


def apply_night_layer(rgb: np.ndarray, terrain_map: np.ndarray | None) -> np.ndarray:
    """basemap (H, W, 3) uint8 + terrain map → nightscape (H, W, 3) uint8.

    When terrain_map is None or there are no urban pixels, it will only be darkened but not lit."""
    night = rgb.astype(np.float32) * NIGHT_FACTOR

    if terrain_map is not None and terrain_map.shape == rgb.shape[:2]:
        from data.terrain_types import PALETTE_TO_TYPE
        urban_indices = [i for i, t in PALETTE_TO_TYPE.items() if t == "urban"]
        if urban_indices:
            mask = np.isin(terrain_map, urban_indices).astype(np.float32)
            if mask.any():
                try:
                    from scipy.ndimage import gaussian_filter
                    # The city itself is fully bright, and the halo is blurred (×2 to compensate for the blur loss), no more than 1
                    glow = np.clip(
                        np.maximum(mask, gaussian_filter(mask, LIGHT_HALO_SIGMA) * 2.0),
                        0.0, 1.0,
                    )
                except ImportError:
                    glow = mask
                night = night + glow[..., None] * LIGHT_RGB * LIGHT_STRENGTH

    return np.clip(night, 0, 255).astype(np.uint8)
