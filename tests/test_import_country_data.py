"""Import country data test - history/countries parsing + country name/capital/polity when filling."""

from types import SimpleNamespace

from services.import_service import _parse_country_history_dir
from views.main_window_file_ops import _populate_imported_data
from model.project import Project


def _write_country_file(tmp_path, filename, text):
    d = tmp_path / "history" / "countries"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(text, encoding="utf-8")


def test_parse_country_history(tmp_path):
    """Extract capital (State ID) and ruling_party; skipping illegal file names."""
    _write_country_file(tmp_path, "GER - Germany.txt", """
capital = 64

set_politics = {
\truling_party = fascism
\tlast_election = "1933.3.5"
}
""")
    _write_country_file(tmp_path, "SOV - Soviet Union.txt", "capital = 219\n")
    _write_country_file(tmp_path, "readme.txt.bak", "capital = 1")

    out = _parse_country_history_dir(str(tmp_path))

    assert out["GER"] == {"capital_state": 64, "ruling_party": "fascism"}
    assert out["SOV"] == {"capital_state": 219, "ruling_party": ""}
    assert "REA" not in out  # readme is not a national file (non-.txt skipped)


def test_populate_fills_country_details():
    """Country name search is localized, capital is converted from State ID to VP province, and government system is imported."""
    project = Project()
    result = {
        "states": [{
            "id": 64, "name": "Brandenburg", "provinces": [101, 102, 103],
            "owner": "GER", "manpower": 1000, "category": "city",
            "victory_points": {102: 30, 103: 5},
        }],
        "strategic_regions": [],
        "country_colors": {"GER": (120, 120, 120)},
        "country_history": {"GER": {"capital_state": 64, "ruling_party": "fascism"}},
        "localisation": {"GER": "German Reich"},
    }

    _populate_imported_data(project, result)

    ger = project.country_mgr.get_country("GER")
    assert ger is not None
    assert ger.name == "German Reich"          # Localized country name, not TAG
    assert ger.capital == 102                  # The province with the highest VP in State 64
    assert ger.ruling_party == "fascism"
    assert project.country_mgr.get_owner_of_state(64) == "GER"


def test_populate_without_history_still_creates_country():
    """Fallback to old behavior when history/localization is missing: TAG as name, no capital."""
    project = Project()
    result = {
        "states": [{
            "id": 1, "name": "S", "provinces": [7],
            "owner": "ABC", "manpower": 1, "category": "town",
            "victory_points": {},
        }],
        "strategic_regions": [],
    }

    _populate_imported_data(project, result)

    abc = project.country_mgr.get_country("ABC")
    assert abc is not None
    assert abc.name == "ABC"
    assert abc.capital == 0
