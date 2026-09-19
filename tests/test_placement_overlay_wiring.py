"""Focused tests for placement overlay wiring (M5.3 slice)."""

from types import SimpleNamespace

import inspect

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


def _record_field(record, name):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


class _FakePage:
    def __init__(self):
        self.records = None
        self.diagnostics_calls = []
        self.status_calls = []
        self.transform_selection = None
        self.set_transform_calls = []
        self.clear_transform_calls = 0

    def set_records(self, records):
        self.records = list(records)

    def set_diagnostics(self, diagnostics):
        self.diagnostics_calls.append(list(diagnostics))

    def set_status(self, text):
        self.status_calls.append(text)

    def selected_transform(self):
        return self.transform_selection

    def set_transform_selection(self, kind, key, x, y, rotation, height):
        self.set_transform_calls.append((kind, key, float(x), float(y), float(rotation), float(height)))
        self.transform_selection = (kind, key, float(x), float(y), float(rotation), float(height))

    def clear_transform_selection(self):
        self.clear_transform_calls += 1
        self.transform_selection = None


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

        def get_province_slot(self, province_id, slot):
            for record in slot_list:
                if _record_field(record, "province_id") == province_id and _record_field(record, "slot") == slot:
                    return record
            return None

        def get_port(self, province_id):
            for record in port_list:
                if _record_field(record, "province_id") == province_id:
                    return record
            return None

        def get_building(self, record_id):
            for record in building_list:
                if _record_field(record, "id") == record_id:
                    return record
            return None

        def get_weather(self, record_id):
            for record in weather_list:
                if _record_field(record, "id") == record_id:
                    return record
            return None

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


class _FakePlacementController:
    def __init__(self, result=True, error=None):
        self.calls = []
        self.result = result
        self.error = error

    def update_transform(self, kind, key, *, x=None, y=None, rotation=None, height=None):
        self.calls.append(("update", kind, key, x, y, rotation, height))
        if self.error is not None:
            raise self.error
        return self.result

    def reset_transform(self, kind, key):
        self.calls.append(("reset", kind, key))
        if self.error is not None:
            raise self.error
        return self.result


def _make_handler_self(project, page, controller):
    refresh_calls = []
    fake_self = SimpleNamespace(
        _tool_panel=SimpleNamespace(_placement_page=page),
        _project=project,
        _canvas=_FakeCanvas(),
        _controllers={"placement": controller},
        _refresh_placement_page=lambda: refresh_calls.append(True),
    )
    return fake_self, refresh_calls


def test_connect_signals_wires_transform_handlers():
    source = inspect.getsource(MainWindow._connect_signals)
    assert "placement_transform_update_requested.connect" in source
    assert "_on_placement_transform_update" in source
    assert "placement_transform_reset_requested.connect" in source
    assert "_on_placement_transform_reset" in source
    assert "placement_generate_slots_requested.connect" in source
    assert "placement_generate_ports_requested.connect" in source
    assert "placement_accept_selected_requested.connect" in source
    assert "placement_refresh_requested.connect" in source


def test_update_handler_routes_payload_and_refreshes_on_change():
    page = _FakePage()
    controller = _FakePlacementController(result=True)
    project = _make_project([], [], [], [])
    fake_self, refresh_calls = _make_handler_self(project, page, controller)
    key = (5, 2)
    MainWindow._on_placement_transform_update(
        fake_self, "slot", key, 1.5, 2.5, 30.25, 3.75
    )
    assert controller.calls == [("update", "slot", key, 1.5, 2.5, 30.25, 3.75)]
    assert controller.calls[0][2] is key
    assert refresh_calls == [True]
    assert page.status_calls == []
    assert page.diagnostics_calls == []


def test_update_handler_noop_skips_refresh():
    page = _FakePage()
    controller = _FakePlacementController(result=False)
    project = _make_project([], [], [], [])
    fake_self, refresh_calls = _make_handler_self(project, page, controller)
    key = (5, 2)
    MainWindow._on_placement_transform_update(
        fake_self, "slot", key, 1.5, 2.5, 30.25, 3.75
    )
    assert controller.calls == [("update", "slot", key, 1.5, 2.5, 30.25, 3.75)]
    assert refresh_calls == []
    assert page.status_calls == []
    assert page.diagnostics_calls == []


def test_reset_handler_routes_payload_and_refreshes_on_change():
    page = _FakePage()
    controller = _FakePlacementController(result=True)
    project = _make_project([], [], [], [])
    fake_self, refresh_calls = _make_handler_self(project, page, controller)
    MainWindow._on_placement_transform_reset(fake_self, "port", 9)
    assert controller.calls == [("reset", "port", 9)]
    assert refresh_calls == [True]
    assert page.status_calls == []
    assert page.diagnostics_calls == []


def test_reset_handler_noop_skips_refresh():
    page = _FakePage()
    controller = _FakePlacementController(result=False)
    project = _make_project([], [], [], [])
    fake_self, refresh_calls = _make_handler_self(project, page, controller)
    MainWindow._on_placement_transform_reset(fake_self, "port", 9)
    assert controller.calls == [("reset", "port", 9)]
    assert refresh_calls == []
    assert page.status_calls == []
    assert page.diagnostics_calls == []


def test_update_handler_reports_errors_without_refresh():
    for error in (ValueError("bad kind"), KeyError("missing"), TypeError("bad")):
        page = _FakePage()
        controller = _FakePlacementController(error=error)
        project = _make_project([], [], [], [])
        fake_self, refresh_calls = _make_handler_self(project, page, controller)
        MainWindow._on_placement_transform_update(
            fake_self, "slot", (1, 0), 1.0, 2.0, 3.0, 4.0
        )
        assert refresh_calls == []
        assert len(page.status_calls) == 1
        assert "failed" in page.status_calls[0].lower()
        assert page.diagnostics_calls == []


def test_reset_handler_reports_errors_without_refresh():
    for error in (ValueError("bad kind"), KeyError("missing"), TypeError("bad")):
        page = _FakePage()
        controller = _FakePlacementController(error=error)
        project = _make_project([], [], [], [])
        fake_self, refresh_calls = _make_handler_self(project, page, controller)
        MainWindow._on_placement_transform_reset(fake_self, "building", 7)
        assert refresh_calls == []
        assert len(page.status_calls) == 1
        assert "failed" in page.status_calls[0].lower()
        assert page.diagnostics_calls == []


def test_sync_selected_transform_updates_from_live_record(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    live_slot = _slot(1, slot=2, x=11.0, y=12.0, rotation=30.0, height=4.0)
    live_port = _port(9, sea=3, x=21.0, y=22.0, rotation=5.0, height=6.0)
    live_building = _building(7, pid=3, x=31.0, y=32.0, rotation=7.0, height=8.0)
    live_weather = _weather(11, region=4, x=41.0, y=42.0, rotation=9.0, height=10.0)
    project = _make_project(
        [live_slot], [live_port], [live_building], [live_weather]
    )
    cases = [
        ("slot", (1, 2), 11.0, 12.0, 30.0, 4.0),
        ("port", 9, 21.0, 22.0, 5.0, 6.0),
        ("building", 7, 31.0, 32.0, 7.0, 8.0),
        ("weather", 11, 41.0, 42.0, 9.0, 10.0),
    ]
    for kind, key, exp_x, exp_y, exp_rot, exp_h in cases:
        page = _FakePage()
        canvas = _FakeCanvas()
        page.transform_selection = (kind, key, 0.0, 0.0, 0.0, 0.0)
        fake_self = _make_self(project, page, canvas)
        MainWindow._refresh_placement_page(fake_self)
        assert page.set_transform_calls == [
            (kind, key, exp_x, exp_y, exp_rot, exp_h)
        ]
        assert page.clear_transform_calls == 0
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_sync_selected_transform_runs_inside_refresh(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    live = _slot(1, slot=0, x=8.5, y=9.5, rotation=2.5, height=1.5)
    project = _make_project([live], [], [], [])
    page = _FakePage()
    canvas = _FakeCanvas()
    page.transform_selection = ("slot", (1, 0), 0.0, 0.0, 0.0, 0.0)
    fake_self = _make_self(project, page, canvas)
    MainWindow._sync_placement_transform_selection(fake_self)
    assert page.set_transform_calls == [("slot", (1, 0), 8.5, 9.5, 2.5, 1.5)]
    assert page.clear_transform_calls == 0
    assert page.diagnostics_calls == []
    assert page.status_calls == []


def test_sync_clears_when_record_missing(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    project = _make_project([], [], [], [])
    cases = [
        ("slot", (1, 0)),
        ("port", 9),
        ("building", 7),
        ("weather", 11),
    ]
    for kind, key in cases:
        page = _FakePage()
        canvas = _FakeCanvas()
        page.transform_selection = (kind, key, 1.0, 2.0, 3.0, 4.0)
        fake_self = _make_self(project, page, canvas)
        MainWindow._refresh_placement_page(fake_self)
        assert page.clear_transform_calls == 1
        assert page.transform_selection is None
        assert page.set_transform_calls == []
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_sync_no_selection_leaves_page_untouched(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    live = _slot(1, slot=0, x=5.0, y=6.0, rotation=1.0, height=2.0)
    project = _make_project([live], [], [], [])
    page = _FakePage()
    canvas = _FakeCanvas()
    assert page.selected_transform() is None
    fake_self = _make_self(project, page, canvas)
    MainWindow._refresh_placement_page(fake_self)
    assert page.set_transform_calls == []
    assert page.clear_transform_calls == 0
    assert page.diagnostics_calls == []
    assert page.status_calls == []


def test_sync_unreadable_record_keeps_selection_without_status(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    broken = SimpleNamespace(province_id=1, slot=0, x=1.0, y=2.0)
    project = _make_project([broken], [], [], [])
    page = _FakePage()
    canvas = _FakeCanvas()
    stale = ("slot", (1, 0), 9.0, 9.0, 9.0, 9.0)
    page.transform_selection = stale
    fake_self = _make_self(project, page, canvas)
    MainWindow._refresh_placement_page(fake_self)
    assert page.set_transform_calls == []
    assert page.clear_transform_calls == 0
    assert page.transform_selection == stale
    assert page.diagnostics_calls == []
    assert page.status_calls == []


def test_sync_unknown_kind_and_malformed_key_clear_safely(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    live = _slot(1, slot=0, x=5.0, y=6.0, rotation=1.0, height=2.0)
    project = _make_project([live], [], [], [])
    for selection in [
        ("city", 1, 0.0, 0.0, 0.0, 0.0),
        ("slot", 1, 0.0, 0.0, 0.0, 0.0),
        ("slot", (1, 0, 2), 0.0, 0.0, 0.0, 0.0),
    ]:
        page = _FakePage()
        canvas = _FakeCanvas()
        page.transform_selection = selection
        fake_self = _make_self(project, page, canvas)
        MainWindow._sync_placement_transform_selection(fake_self)
        assert page.clear_transform_calls == 1
        assert page.transform_selection is None
        assert page.set_transform_calls == []
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_transform_wiring_keeps_edits_inside_controller():
    update_src = inspect.getsource(MainWindow._on_placement_transform_update)
    reset_src = inspect.getsource(MainWindow._on_placement_transform_reset)
    sync_src = inspect.getsource(MainWindow._sync_placement_transform_selection)
    assert "update_transform" in update_src
    assert "reset_transform" in reset_src
    for src in (update_src, reset_src):
        assert "map_placement_mgr" not in src
        assert "set_province_slot" not in src
        assert "set_port" not in src
        assert "update_building" not in src
        assert "update_weather" not in src
        assert "mark_dirty" not in src
    assert "get_province_slot" in sync_src
    assert "get_port" in sync_src
    assert "get_building" in sync_src
    assert "get_weather" in sync_src
    assert "set_province_slot" not in sync_src
    assert "update_building" not in sync_src
    assert "update_weather" not in sync_src
    assert "mark_dirty" not in sync_src
    assert "set_diagnostics" not in sync_src
    assert "set_status" not in sync_src


def test_connect_signals_wires_canvas_selection_and_drag():
    source = inspect.getsource(MainWindow._connect_signals)
    assert "placement_selection_changed.connect" in source
    assert "_on_placement_selection_changed" in source
    assert "placement_position_change_requested.connect" in source
    assert "_on_placement_position_change_requested" in source


def test_canvas_selection_populates_transform_for_all_kinds():
    live_slot = _slot(1, slot=2, x=11.0, y=12.0, rotation=30.0, height=4.0)
    live_port = _port(9, sea=3, x=21.0, y=22.0, rotation=5.0, height=6.0)
    live_building = _building(7, pid=3, x=31.0, y=32.0, rotation=7.0, height=8.0)
    live_weather = _weather(11, region=4, x=41.0, y=42.0, rotation=9.0, height=10.0)
    project = _make_project(
        [live_slot], [live_port], [live_building], [live_weather]
    )
    cases = [
        ("slot", (1, 2), 11.0, 12.0, 30.0, 4.0),
        ("port", 9, 21.0, 22.0, 5.0, 6.0),
        ("building", 7, 31.0, 32.0, 7.0, 8.0),
        ("weather", 11, 41.0, 42.0, 9.0, 10.0),
    ]
    for kind, key, exp_x, exp_y, exp_rot, exp_h in cases:
        page = _FakePage()
        canvas = _FakeCanvas()
        fake_self = _make_self(project, page, canvas)
        MainWindow._on_placement_selection_changed(fake_self, kind, key)
        assert page.set_transform_calls == [(kind, key, exp_x, exp_y, exp_rot, exp_h)]
        assert page.clear_transform_calls == 0
        assert page.transform_selection == (kind, key, exp_x, exp_y, exp_rot, exp_h)
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_canvas_selection_supports_mapping_records():
    live = {"province_id": 1, "slot": 0, "x": 3.5, "y": 4.5, "rotation": 1.25, "height": 2.5}
    project = _make_project([live], [], [], [])
    page = _FakePage()
    canvas = _FakeCanvas()
    fake_self = _make_self(project, page, canvas)
    MainWindow._on_placement_selection_changed(fake_self, "slot", (1, 0))
    assert page.set_transform_calls == [("slot", (1, 0), 3.5, 4.5, 1.25, 2.5)]
    assert page.clear_transform_calls == 0
    assert page.status_calls == []


def test_canvas_selection_clears_on_empty_kind_and_none_key():
    live = _slot(1, slot=0, x=5.0, y=6.0, rotation=1.0, height=2.0)
    project = _make_project([live], [], [], [])
    for kind, key in [("", None), ("", (1, 0)), ("slot", None)]:
        page = _FakePage()
        canvas = _FakeCanvas()
        page.transform_selection = ("slot", (1, 0), 9.0, 9.0, 9.0, 9.0)
        fake_self = _make_self(project, page, canvas)
        MainWindow._on_placement_selection_changed(fake_self, kind, key)
        assert page.clear_transform_calls == 1
        assert page.transform_selection is None
        assert page.set_transform_calls == []
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_canvas_selection_clears_when_record_missing():
    project = _make_project([], [], [], [])
    cases = [
        ("slot", (1, 0)),
        ("port", 9),
        ("building", 7),
        ("weather", 11),
    ]
    for kind, key in cases:
        page = _FakePage()
        canvas = _FakeCanvas()
        page.transform_selection = (kind, key, 1.0, 2.0, 3.0, 4.0)
        fake_self = _make_self(project, page, canvas)
        MainWindow._on_placement_selection_changed(fake_self, kind, key)
        assert page.clear_transform_calls == 1
        assert page.transform_selection is None
        assert page.set_transform_calls == []
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_canvas_selection_clears_on_unknown_kind_and_malformed_key():
    live = _slot(1, slot=0, x=5.0, y=6.0, rotation=1.0, height=2.0)
    project = _make_project([live], [], [], [])
    for kind, key in [("city", 1), ("slot", 1), ("slot", (1, 0, 2)), ("slot", "bad")]:
        page = _FakePage()
        canvas = _FakeCanvas()
        page.transform_selection = ("slot", (1, 0), 9.0, 9.0, 9.0, 9.0)
        fake_self = _make_self(project, page, canvas)
        MainWindow._on_placement_selection_changed(fake_self, kind, key)
        assert page.clear_transform_calls == 1
        assert page.transform_selection is None
        assert page.set_transform_calls == []
        assert page.diagnostics_calls == []
        assert page.status_calls == []


def test_canvas_selection_clears_on_unreadable_record():
    broken = SimpleNamespace(province_id=1, slot=0, x=1.0, y=2.0)
    project = _make_project([broken], [], [], [])
    page = _FakePage()
    canvas = _FakeCanvas()
    page.transform_selection = ("slot", (1, 0), 9.0, 9.0, 9.0, 9.0)
    fake_self = _make_self(project, page, canvas)
    MainWindow._on_placement_selection_changed(fake_self, "slot", (1, 0))
    assert page.clear_transform_calls == 1
    assert page.transform_selection is None
    assert page.set_transform_calls == []
    assert page.diagnostics_calls == []
    assert page.status_calls == []


def test_canvas_drag_routes_x_y_only_and_refreshes_on_change():
    page = _FakePage()
    controller = _FakePlacementController(result=True)
    project = _make_project([], [], [], [])
    fake_self, refresh_calls = _make_handler_self(project, page, controller)
    key = (5, 2)
    MainWindow._on_placement_position_change_requested(fake_self, "slot", key, 1.5, 2.5)
    assert controller.calls == [("update", "slot", key, 1.5, 2.5, None, None)]
    assert controller.calls[0][2] is key
    assert refresh_calls == [True]
    assert page.status_calls == []
    assert page.diagnostics_calls == []


def test_canvas_drag_preserves_key_identity_for_all_kinds():
    cases = [("slot", (1, 0)), ("port", 9), ("building", 7), ("weather", 11)]
    for kind, key in cases:
        page = _FakePage()
        controller = _FakePlacementController(result=True)
        project = _make_project([], [], [], [])
        fake_self, refresh_calls = _make_handler_self(project, page, controller)
        MainWindow._on_placement_position_change_requested(fake_self, kind, key, 7.25, 8.5)
        assert controller.calls == [("update", kind, key, 7.25, 8.5, None, None)]
        assert controller.calls[0][2] is key
        assert refresh_calls == [True]
        assert page.status_calls == []


def test_canvas_drag_noop_skips_refresh():
    page = _FakePage()
    controller = _FakePlacementController(result=False)
    project = _make_project([], [], [], [])
    fake_self, refresh_calls = _make_handler_self(project, page, controller)
    key = (5, 2)
    MainWindow._on_placement_position_change_requested(fake_self, "slot", key, 1.5, 2.5)
    assert controller.calls == [("update", "slot", key, 1.5, 2.5, None, None)]
    assert refresh_calls == []
    assert page.status_calls == []
    assert page.diagnostics_calls == []


def test_canvas_drag_reports_errors_without_refresh():
    for error in (ValueError("bad kind"), KeyError("missing"), TypeError("bad")):
        page = _FakePage()
        controller = _FakePlacementController(error=error)
        project = _make_project([], [], [], [])
        fake_self, refresh_calls = _make_handler_self(project, page, controller)
        MainWindow._on_placement_position_change_requested(
            fake_self, "slot", (1, 0), 1.0, 2.0
        )
        assert refresh_calls == []
        assert len(page.status_calls) == 1
        assert "failed" in page.status_calls[0].lower()
        assert page.diagnostics_calls == []


def test_canvas_wiring_keeps_edits_inside_controller():
    drag_src = inspect.getsource(MainWindow._on_placement_position_change_requested)
    select_src = inspect.getsource(MainWindow._on_placement_selection_changed)
    assert "update_transform" in drag_src
    assert "map_placement_mgr" not in drag_src
    assert "set_province_slot" not in drag_src
    assert "set_port" not in drag_src
    assert "update_building" not in drag_src
    assert "update_weather" not in drag_src
    assert "mark_dirty" not in drag_src
    assert "set_diagnostics" not in drag_src
    assert "get_province_slot" in select_src
    assert "get_port" in select_src
    assert "get_building" in select_src
    assert "get_weather" in select_src
    assert "map_placement_mgr" in select_src
    assert "set_province_slot" not in select_src
    assert "set_port" not in select_src
    assert "update_building" not in select_src
    assert "update_weather" not in select_src
    assert "mark_dirty" not in select_src
    assert "set_diagnostics" not in select_src
    assert "set_status" not in select_src


def test_mode_exit_clears_transform_selection(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    fake_self, calls, canvas = _make_mode_self()
    page = fake_self._tool_panel._placement_page
    page.set_transform_selection("slot", (1, 0), 5.0, 6.0, 1.0, 2.0)
    assert page.transform_selection is not None
    before = page.clear_transform_calls
    MainWindow._on_mode_changed(fake_self, "land")
    assert page.transform_selection is None
    assert page.clear_transform_calls == before + 1
    assert ("visible", False) in calls


def test_mode_exit_clears_for_all_non_placement_modes(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    for mode in ["land", "strategic_region", "logistics", "province"]:
        fake_self, calls, canvas = _make_mode_self()
        page = fake_self._tool_panel._placement_page
        page.set_transform_selection("slot", (1, 0), 5.0, 6.0, 1.0, 2.0)
        before = page.clear_transform_calls
        MainWindow._on_mode_changed(fake_self, mode)
        assert page.transform_selection is None
        assert page.clear_transform_calls == before + 1
        assert ("visible", False) in calls


def test_mode_enter_placement_does_not_clear_via_exit_path(monkeypatch):
    monkeypatch.setattr(
        "domain.validators.placement.validate_placement_references",
        lambda *a, **k: [],
    )
    fake_self, calls, canvas = _make_mode_self()
    page = fake_self._tool_panel._placement_page
    assert page.selected_transform() is None
    before = page.clear_transform_calls
    MainWindow._on_mode_changed(fake_self, "placement")
    assert page.clear_transform_calls == before
    assert ("visible", True) in calls
