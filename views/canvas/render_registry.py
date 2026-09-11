"""display-mode → renderer module-path registry.

Add new display mode = add a line in DEFAULT_RENDERERS, no need to change canvas/widget.py
(The old method is to hand-write _render_X_mode / _partial_render_X thin shell pair in widget.py,
 Already abolished in the 2026-06 architecture overhaul).

Conventions of the renderer module:
- Must provide render(canvas) — full rendering
- Optional partial_render(canvas, x0, y0, x1, y1) — partial rendering;
  Modes without this function (such as whole-image synthesis such as preview) automatically fall back to full rendering.

Modules are lazily loaded and cached on demand, consistent with the old thin shell's lazy import behavior.
The runtime extension goes like MapCanvas.register_renderer(mode, module_path)."""

DEFAULT_RENDERERS: dict[str, str] = {
    "land": "features.map.land.renderer",
    "terrain": "features.map.terrain.renderer",
    "height": "features.map.height.renderer",
    "province": "features.map.province.renderer",
    "state": "features.map.state.renderer",
    "country": "features.map.country.renderer",
    "river": "features.map.river.renderer",
    "logistics": "features.map.logistics.renderer",
    "continent": "features.map.continent.renderer",
    "strategic_region": "features.map.strategic_region.renderer",
    "province_terrain": "features.map.province_terrain.renderer",
    # Preview: whole image synthesis, no partial_render (automatically revert to full image)
    "preview": "features.map.preview.renderer",
    # There is currently no mode reuse for dedicated rendering land
    "colormap": "features.map.land.renderer",
    "default_map": "features.map.land.renderer",
}
