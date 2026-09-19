"""Focused tests for placement overlay wiring (M5.3 slice)."""

from types import SimpleNamespace

import numpy as np

from views.main_window import MainWindow


def _slot(pid, slot=0, x=5.0, y=6.0, **extra):
    fields = {
        "province_id": pid,
        "slot": slot,
        "x": float(x),
        "y": float(y),
        "review_status": "unreviewed",
        "provenance": "authored",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _port(pid, sea=9, x=10.0, y=11.0, **extra):
    fields = {
        "province_id": pid,
        "sea_province": sea,
        "x": float(x),
        "y": float(y),
        "review_status": "unreviewed",
        "provenance": "authored",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _building(bid, pid=3, btype="arms_factory", x=15.0, y=16.0, **extra):
    fields = {
        "id": bid,
        "province_id": pid,
        "building_type": btype,
        "x": float(x),
        "y": float(y),
        "review_status": "unreviewed",
        "provenance": "authored",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _weather(wid, region=4, x=20.0, y=21.0, **extra):
    fields = {
        "id": wid,
        "region_id": region,
        "x": float(x),
        "y": float(y),
        "review_status": "unreviewed",
        "provenance": "authored",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


class _FakePage:
    def __init__(self):
        self.records = None
        self.diagnostics_calls = []
        self.status_calls = []

    def set_records(self, records):
        self.records = list(records)

    def set_diagnostics(self, diagnostics):
        self.diagnostics_calls.append(list(diagnostics))

    def set_status(self, text):
        self.status_calls.append(text)


class _FakeCanvas:
    def __init__(self):
        self.overlay_records = None
        self.overlay_vp = None
        self.overlay_findings = None
        self.visible_calls = []

    def set_placement_overlay_data(self, records, vp_points=(), findings=()):
        self.overlay_records = list(records)
        self.overlay_vp = list(vp_points)
        self.overlay_findings = list(findings)

    def set_placement_overlay_visible(self, visible):
        self.visible_calls.append(bool(visible))


def _make_project(slot_list, port_list, building_list, weather_list,
                  centroids=None, vps=None):
    centroids = dict(centroids or {})
    vps = dict(vps or {})

    class _Mgr:
        def list_province_slots(self):
            return list(slot_list)

        def list_ports(self):
            return list(port_list)

        def list_buildings(self):
            return list(building_list)

        def list_weather(self):
            return list(weather_list)

    def _centroid(pid):
        return centroids.get(int(pid))

    fake_map_data = SimpleNamespace(
        province_map=np.zeros((8, 8), dtype=np.int32),
        tile_map=np.zeros((8, 8), dtype=np.int32),
        get_province_centroid=_centroid,
    )
    state = SimpleNamespace(victory_points=dict(vps))
    fake_state_mgr = SimpleNamespace(states={1: state})
    fake_sr_mgr = SimpleNamespace(regions={})
    project = SimpleNamespace(
        map_placement_mgr=_Mgr(),
        map_data=fake_map_data,
        state_mgr=fake_state_mgr,
        strategic_region_mgr=fake_sr_mgr,
    )
    return project


def _make_self(project, page, canvas):
    return SimpleNamespace(
        _tool_panel=SimpleNamespace(_placement_page=page),
        _project=project,
        _canvas=canvas,
    )


def test_refresh_page_keeps_slots_ports_only_and_feeds_overlay(monkeypatch):
    slot = _slot(1)
    port = _port(2)
    building = _building(7)
    weather = _weather(11)
    project = _make_project(
        [slot], [port], [building], [weather],
        centroids={5: (2.0, 3.0)},
        vps={5: 10},
    )
    page = _FakePage()
    canvas = _FakeCanvas()
    fake_self = _make_self(project, page, canvas)

    captured = {}

    def _fake_validate(province_map, tile_map, **kwargs):
        captured["province_map"] = province_map
        captured["tile_map"] = tile_map
        captured.update(kwargs)
        return [SimpleNamespace(code="placement.collision", coordinates=[(1.0, 2.0)])]

    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        _fake_validate,
    )

    MainWindow._refresh_placement_page(fake_self)

    assert page.records is not None
    assert len(page.records) == 2
    assert slot in page.records
    assert port in page.records
    assert building not in page.records
    assert weather not in page.records

    assert canvas.overlay_records is not None
    assert len(canvas.overlay_records) == 4
    assert slot in canvas.overlay_records
    assert port in canvas.overlay_records
    assert building in canvas.overlay_records
    assert weather in canvas.overlay_records

    assert canvas.overlay_vp == [(5, 2.0, 3.0)]

    assert canvas.overlay_findings is not None
    assert len(canvas.overlay_findings) == 1
    assert getattr(canvas.overlay_findings[0], "code", "") == "placement.collision"

    assert captured["placement_entries"] == [slot, port]
    assert captured["building_entries"] == [building]
    assert captured["weather_entries"] == [weather]
    assert captured["state_mgr"] is project.state_mgr
    assert captured["strategic_region_mgr"] is project.strategic_region_mgr
    assert captured["province_map"] is project.map_data.province_map
    assert captured["tile_map"] is project.map_data.tile_map


def test_vp_points_skip_missing_and_nonpositive():
    slot = _slot(1)
    project = _make_project(
        [slot], [], [], [],
        centroids={
            5: (2.0, 3.0),
            7: (float("nan"), 1.0),
            8: (float("inf"), 1.0),
        },
        vps={5: 10, 6: 5, 7: 3, 8: 4, 9: 0, 10: -2},
    )
    page = _FakePage()
    canvas = _FakeCanvas()
    fake_self = _make_self(project, page, canvas)

    MainWindow._refresh_placement_page(fake_self)

    assert canvas.overlay_vp == [(5, 2.0, 3.0)]


def test_vp_points_deterministic_order():
    project = _make_project(
        [], [], [], [],
        centroids={9: (9.0, 9.0), 5: (2.0, 3.0), 7: (1.0, 1.0)},
        vps={9: 1, 5: 2, 7: 3},
    )
    fake_self = SimpleNamespace(_project=project)
    first = MainWindow._build_placement_overlay_vp_points(fake_self)
    second = MainWindow._build_placement_overlay_vp_points(fake_self)
    assert first == second
    assert first == [(5, 2.0, 3.0), (7, 1.0, 1.0), (9, 9.0, 9.0)]


def test_validator_failure_keeps_page_refresh(monkeypatch):
    slot = _slot(1)
    port = _port(2)
    building = _building(7)
    weather = _weather(11)
    project = _make_project([slot], [port], [building], [weather])
    page = _FakePage()
    canvas = _FakeCanvas()
    fake_self = _make_self(project, page, canvas)

    def _boom(*args, **kwargs):
        raise RuntimeError("validator down")

    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        _boom,
    )

    MainWindow._refresh_placement_page(fake_self)

    assert page.records is not None
    assert len(page.records) == 2
    assert canvas.overlay_records is not None
    assert len(canvas.overlay_records) == 4
    assert canvas.overlay_findings == []


def test_refresh_does_not_touch_page_diagnostics(monkeypatch):
    slot = _slot(1)
    project = _make_project([slot], [], [], [])
    page = _FakePage()
    canvas = _FakeCanvas()
    fake_self = _make_self(project, page, canvas)
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )

    MainWindow._refresh_placement_page(fake_self)

    assert page.diagnostics_calls == []
    assert page.status_calls == []


def _make_mode_self(monkeypatch_validator=None):
    calls = []
    slot = _slot(1)
    project = _make_project([slot], [], [], [], centroids={}, vps={})
    page = _FakePage()
    canvas = _FakeCanvas()
    orig_canvas_data = canvas.set_placement_overlay_data

    def _recording_data(records, vp_points=(), findings=()):
        calls.append(("data",))
        return orig_canvas_data(records, vp_points=vp_points, findings=findings)

    def _recording_visible(visible):
        calls.append(("visible", bool(visible)))

    canvas.set_placement_overlay_data = _recording_data
    canvas.set_placement_overlay_visible = _recording_visible

    fake_self = SimpleNamespace(
        _app=SimpleNamespace(on_mode_changed=lambda m: "label-%s" % m),
        _status_mode=SimpleNamespace(setText=lambda t: calls.append(("status", t))),
        _tool_panel=SimpleNamespace(_placement_page=page),
        _project=project,
        _canvas=canvas,
        _refresh_sr_list=lambda: calls.append(("sr_list",)),
        _refresh_placement_page=MainWindow._refresh_placement_page.__get__(SimpleNamespace(
            _tool_panel=SimpleNamespace(_placement_page=page),
            _project=project,
            _canvas=canvas,
        )),
        _refresh_logistics_counts=lambda: calls.append(("logistics",)),
        _refresh_feature_statuses=lambda: calls.append(("features",)),
        _check_province_gaps=lambda: calls.append(("gaps",)),
    )

    def _bound_refresh():
        MainWindow._refresh_placement_page(
            SimpleNamespace(
                _tool_panel=SimpleNamespace(_placement_page=page),
                _project=project,
                _canvas=canvas,
            )
        )
        calls.append(("refresh_placement",))

    fake_self._refresh_placement_page = _bound_refresh
    return fake_self, calls, canvas


def test_overlay_visibility_enabled_only_for_placement(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    fake_self, calls, canvas = _make_mode_self()

    MainWindow._on_mode_changed(fake_self, "placement")
    assert ("visible", True) in calls
    assert ("refresh_placement",) in calls
    assert calls.index(("refresh_placement",)) < calls.index(("visible", True))

    calls.clear()
    canvas.visible_calls.clear()

    MainWindow._on_mode_changed(fake_self, "land")
    assert ("visible", False) in calls
    assert ("refresh_placement",) not in calls

    calls.clear()
    MainWindow._on_mode_changed(fake_self, "strategic_region")
    assert ("visible", False) in calls
    assert ("sr_list",) in calls

    calls.clear()
    MainWindow._on_mode_changed(fake_self, "logistics")
    assert ("visible", False) in calls
    assert ("logistics",) in calls


def test_mode_change_keeps_sr_base_behavior(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    fake_self, calls, _ = _make_mode_self()
    seen_labels = []

    MainWindow._on_mode_changed(fake_self, "strategic_region")
    assert ("sr_list",) in calls
    assert ("features",) in calls

    calls.clear()
    MainWindow._on_mode_changed(fake_self, "placement")
    assert ("sr_list",) not in calls
    assert ("features",) in calls
