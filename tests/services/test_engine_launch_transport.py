from __future__ import annotations

import sys

from domain import engine_acceptance as contract
from services import engine_acceptance_service as harness


def test_steam_launch_config_uses_appid_and_observes_game(tmp_path):
    """Steam handoff is explicit and does not mistake steam.exe for HOI4."""
    steam = tmp_path / "steam.exe"
    steam.write_bytes(b"steam")
    config = harness.build_steam_launch_config(
        steam_executable=steam,
        game_args=("-mod", "acceptance.mod"),
        timeout_seconds=900,
    )

    assert config.argv() == [str(steam), "-applaunch", "394360", "-mod", "acceptance.mod"]
    assert config.wait_for_process == "hoi4.exe"
    assert config.launcher_process == "Paradox Launcher.exe"
    assert config.startup_timeout_seconds == 60.0


def test_launch_config_round_trip_preserves_process_observation():
    """Serialized launch identities retain the launcher handoff contract."""
    original = contract.LaunchConfig(
        executable="steam.exe",
        args=("-applaunch", "394360"),
        wait_for_process="hoi4.exe",
        startup_timeout_seconds=45.0,
        launcher_process="Paradox Launcher.exe",
    )

    restored = contract.LaunchConfig.from_dict(original.to_dict())

    assert restored == original
    assert restored.identity() == original.identity()


def test_observed_launch_waits_for_new_game_process(monkeypatch):
    """A short-lived launcher helper is successful only after HOI4 appears."""
    image_states = iter((set(), set(), {1234}, set()))

    class FakeProcess:
        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_process_ids(image_name):
        if image_name == "hoi4.exe":
            return next(image_states)
        return set()

    monkeypatch.setattr(harness, "_list_process_ids", fake_process_ids)
    monkeypatch.setattr(harness, "_process_observation_error", lambda: "")
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)

    result = harness.execute_launch(
        contract.LaunchConfig(
            executable=sys.executable,
            args=("-c", "pass"),
            wait_for_process="hoi4.exe",
            startup_timeout_seconds=1.0,
        )
    )

    assert result["status"] == "exited"
    assert result["observed_pids"] == [1234]


def test_observed_launch_reports_launcher_stuck_before_game(monkeypatch):
    """A launcher-only session gets an actionable diagnostic instead of a generic failure."""
    class FakeProcess:
        def poll(self):
            return 0

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    def fake_process_ids(image_name):
        if image_name == "Paradox Launcher.exe":
            return {4321}
        return set()

    clock = iter((0.0, 1.0))
    monkeypatch.setattr(harness, "_list_process_ids", fake_process_ids)
    monkeypatch.setattr(harness, "_process_observation_error", lambda: "")
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)

    result = harness.execute_launch(
        contract.LaunchConfig(
            executable="steam.exe",
            args=("-applaunch", "394360"),
            wait_for_process="hoi4.exe",
            startup_timeout_seconds=0.5,
            launcher_process="Paradox Launcher.exe",
        )
    )

    assert result["status"] == "timeout"
    assert result["launcher_detected"] is True
    assert result["launcher_pids"] == [4321]
    assert "launcher has not started the game" in result["error"]
