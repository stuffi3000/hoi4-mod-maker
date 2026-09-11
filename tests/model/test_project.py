"""Project unit testing."""
import pytest
from model.events import EventBus
from model.project import Project
from domain.managers.state import StateManager
from domain.managers.country import CountryManager


@pytest.fixture(autouse=True)
def _restore_map_size():
    """Restore global MAP_WIDTH / MAP_HEIGHT after testing to avoid contaminating other tests."""
    import data.constants as _c
    orig_w, orig_h = _c.MAP_WIDTH, _c.MAP_HEIGHT
    yield
    _c.MAP_WIDTH = orig_w
    _c.MAP_HEIGHT = orig_h


class TestProject:
    """Project basic functions."""

    def test_new_project_creates_fresh_managers(self) -> None:
        """All managers after new_project are new instances."""
        proj = Project()
        old_state_mgr = proj.state_mgr
        old_country_mgr = proj.country_mgr
        proj.new_project(256, 128)
        assert proj.state_mgr is not old_state_mgr
        assert proj.country_mgr is not old_country_mgr
        assert not proj.is_dirty

    def test_mark_dirty_and_clean(self) -> None:
        """mark_dirty / mark_clean / is_dirty status switching."""
        proj = Project()
        assert not proj.is_dirty
        proj.mark_dirty()
        assert proj.is_dirty
        proj.mark_clean()
        assert not proj.is_dirty

    def test_holds_all_managers(self) -> None:
        """Project holds all necessary managers."""
        proj = Project()
        assert isinstance(proj.state_mgr, StateManager)
        assert isinstance(proj.country_mgr, CountryManager)
        assert proj.map_data is not None
        assert proj.adjacency_mgr is not None
        assert proj.railway_mgr is not None
        assert proj.supply_mgr is not None
        assert proj.adjacency_rule_mgr is not None
        assert proj.strategic_region_mgr is not None
        assert proj.continent_mgr is not None
        assert proj.colormap_settings is not None
        assert proj.default_map_settings is not None

    def test_path_initially_none(self) -> None:
        """The path of the new Project is None."""
        proj = Project()
        assert proj.path is None

    def test_save_without_path_raises(self) -> None:
        """save throws an exception when there is no path."""
        proj = Project()
        import pytest
        with pytest.raises(ValueError):
            proj.save()

    def test_event_bus_default(self) -> None:
        """If event_bus is not passed, one will be automatically created."""
        proj = Project()
        assert proj.event_bus is not None

    def test_event_bus_injected(self) -> None:
        """event_bus can be injected."""
        bus = EventBus()
        proj = Project(event_bus=bus)
        assert proj.event_bus is bus

    def test_close_stops_autosave(self) -> None:
        """The autosave timer is cleared after close."""
        import threading
        proj = Project()
        # Create a timer that won't actually fire
        timer = threading.Timer(9999, lambda: None)
        proj._autosave_timer = timer
        proj.close()
        assert proj._autosave_timer is None
