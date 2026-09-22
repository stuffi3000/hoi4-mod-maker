from types import SimpleNamespace

from features.map.logistics import renderer


def test_logistics_renderer_uses_terrain_background(monkeypatch):
    calls = []
    import features.map.land.renderer as land_renderer

    monkeypatch.setattr(land_renderer, "render", lambda canvas: calls.append(canvas))
    canvas = SimpleNamespace(_logistics_background="terrain")

    renderer.render(canvas)

    assert calls == [canvas]


def test_logistics_renderer_uses_country_background(monkeypatch):
    calls = []
    import features.map.country.renderer as country_renderer

    monkeypatch.setattr(
        country_renderer, "render", lambda canvas: calls.append(canvas)
    )
    canvas = SimpleNamespace(_logistics_background="countries")

    renderer.render(canvas)

    assert calls == [canvas]
