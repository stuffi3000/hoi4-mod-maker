"""Preview Renderer — Synthesizes the look and feel of the game and writes it to the canvas display buffer.

Convention (views/canvas/render_registry.py):
- This module deliberately does not provide partial_render: the preview is a composite of the whole image, and partial refresh is meaningless.
  Canvas dispatch will automatically fall back to full rendering.
- The synthesis results are cached in canvas._preview_cache (H, W, 3 RGB uint8);
  invalidate_cache() clears the cache and resynthesizes the next render —
  The "Refresh Preview" button on the preview page goes this way.

When the game assets are unavailable, it is downgraded to the mainland view, and the reason is saved to canvas._preview_error
For display on sidebar pages."""

from __future__ import annotations

from services.game_assets import get_default_assets


def invalidate_cache(canvas) -> None:
    """Clear the synthesis cache and re-synthesize the next rendering."""
    canvas._preview_cache = None
    canvas._preview_political_cache = None
    canvas._preview_night_cache = None
    canvas._preview_night_src = None


def render(canvas) -> None:
    """Full rendering: Paste directly if there is cache, synthesize first if there is no cache."""
    cache = getattr(canvas, "_preview_cache", None)
    if cache is None or cache.shape[:2] != canvas._tile_map.shape:
        cache = _compose(canvas)
        canvas._preview_cache = cache
        canvas._preview_political_cache = None

    if cache is None:
        # Game assets are unavailable → downgrade continent view (the reason has been written to canvas._preview_error)
        from features.map.land.renderer import render as land_render
        land_render(canvas)
        return

    # Political view switch: Overlay national power colors on the base map (results are cached separately)
    if getattr(canvas, "_preview_political", False):
        pcache = getattr(canvas, "_preview_political_cache", None)
        if pcache is None or pcache.shape[:2] != cache.shape[:2]:
            from domain.preview.political import apply_political_layer
            pcache = apply_political_layer(
                cache,
                getattr(canvas, "_country_color_rgb", None),
                getattr(canvas, "_country_assigned_mask", None),
            )
            canvas._preview_political_cache = pcache
        cache = pcache

    # Night scene switch: darken + urban city lights (use the basemap object as the cache source,
    # If the political view is turned on/off and the base map is changed, it will be automatically recalculated)
    if getattr(canvas, "_preview_night", False):
        ncache = getattr(canvas, "_preview_night_cache", None)
        if ncache is None or getattr(canvas, "_preview_night_src", None) is not cache:
            from domain.preview.night import apply_night_layer
            ncache = apply_night_layer(cache, canvas._terrain_map)
            canvas._preview_night_cache = ncache
            canvas._preview_night_src = cache
        cache = ncache

    # RGB → display buffer (BGRA)
    buf = canvas._display_buffer
    buf[:, :, 0] = cache[:, :, 2]
    buf[:, :, 1] = cache[:, :, 1]
    buf[:, :, 2] = cache[:, :, 0]
    buf[:, :, 3] = 255


def _compose(canvas):
    """Composite using current map data + game texture, returning None on failure."""
    assets = get_default_assets()
    tiles = assets.atlas_tiles()
    mapping = assets.terrain_to_texture()
    if tiles is None or mapping is None:
        canvas._preview_error = assets.last_error or "HOI4 installation directory was not found"
        return None
    canvas._preview_error = ""

    from domain.preview.climate_tint import generate_climate_tint
    from domain.preview.compositor import compose_preview

    tint = generate_climate_tint(canvas._tile_map, canvas._height_map)
    return compose_preview(
        canvas._tile_map,
        canvas._terrain_map,
        canvas._height_map,
        canvas._river_map,
        tiles,
        mapping,
        tint=tint,
    )
