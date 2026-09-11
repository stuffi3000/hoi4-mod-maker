"""CountryController — Country edit mode controller.

Handles country creation, territory assignment, capital setting, attribute editing."""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController
from commands.country.assign import AssignStateToCountryCommand
from commands.country.create import CreateCountryCommand
from commands.country.delete import DeleteCountryCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class CountryController(BaseController):
    """Country editing mode."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.selected_country_tag: str = ""
        # False = Information mode (default): Click on the map to view the country without changing the ownership.
        # True = Assign Territory Mode: Click to assign a state to the currently selected country
        self.assign_mode: bool = False
        # Always listen for province regeneration
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _on_province_regen(self, event) -> None:
        """Fully regenerated provinces → Clear all country data."""
        if not event.data.get("incremental"):
            self.project.country_mgr.clear()
            self.selected_country_tag = ""
            self.event_bus.emit("country_changed", tag="", action="refresh")

    def activate(self) -> None:
        """Enter country mode and refresh the color map."""
        self._emit_status("Country editing mode")
        self.event_bus.emit("country_changed", tag="", action="refresh")

    def deactivate(self) -> None:
        """Leaving country mode: Return to information mode to prevent delayed change of ownership when returning."""
        if self.assign_mode:
            self.assign_mode = False
            self.event_bus.emit(
                "country_changed", tag="", action="assign_mode_reset")

    def set_assign_mode(self, on: bool) -> None:
        """Toggle allocated territory/info mode (page button callback)."""
        self.assign_mode = bool(on)
        if on:
            self._emit_status("Assign territory mode: click states on the map to assign them to the selected country (Ctrl+Z restores the previous owner)")
        else:
            self._emit_status("Information mode: click the map to inspect the country at that location")

    def on_province_clicked(self, pid: int) -> None:
        """Click on a province: Information mode to view the country; allocation mode assigns the State to the selected country."""
        if pid <= 0:
            return
        if not self.assign_mode:
            self._show_country_at(pid)
            return
        if not self.selected_country_tag:
            self._emit_status("Select a country in the list before assigning territory")
            return

        state_mgr = self.project.state_mgr
        country_mgr = self.project.country_mgr

        state_id = state_mgr.get_state_of_province(pid)
        if state_id <= 0:
            self._emit_status("This province is not assigned to a state")
            return

        # Get the old owner (return to it on undo)
        old_tag = country_mgr.get_owner_of_state(state_id)

        if old_tag == self.selected_country_tag:
            return  # already belongs to this country

        cmd = AssignStateToCountryCommand(
            country_mgr, state_id, old_tag, self.selected_country_tag,
        )
        self.history.execute(cmd)
        self.project.mark_dirty()

        self.event_bus.emit(
            "country_changed",
            tag=self.selected_country_tag,
            action="modified",
        )
        self._emit_status(f"State {state_id} assigned to {self.selected_country_tag}")

    def _show_country_at(self, pid: int) -> None:
        """Information mode: Check which country the province is located in and select it (the panel displays editable information)."""
        state_id = self.project.state_mgr.get_state_of_province(pid)
        if state_id <= 0:
            self._emit_status("This province is not assigned to a state")
            return
        tag = self.project.country_mgr.get_owner_of_state(state_id)
        if tag:
            country = self.project.country_mgr.get_country(tag)
            self.select_country(tag)
            self._emit_status(f"{tag} ({country.name}) — edit this country in the left panel")
        else:
            self._emit_status(f"State {state_id} is not assigned to a country")

    def on_province_right_clicked(self, pid: int, x: int, y: int) -> None:
        """Right-click province: Set as the capital of the current country."""
        if pid <= 0 or not self.selected_country_tag:
            if not self.selected_country_tag:
                self._emit_status("Select a country in Country mode first")
            return

        tag = self.selected_country_tag
        country_mgr = self.project.country_mgr
        country_mgr.set_capital(tag, pid)
        self.project.mark_dirty()

        self.event_bus.emit("country_changed", tag=tag, action="modified")
        self._emit_status(f"Capital of {tag} set to province {pid}")

    def create_country(
        self,
        tag: str,
        name: str,
        color: tuple[int, int, int],
        party: str = "neutrality",
    ) -> bool:
        """Create new countries. Return whether successful."""
        tag = tag.upper().strip()[:3]
        if len(tag) != 3 or not tag.isalpha():
            self._emit_status("TAG must consist of 3 letters")
            return False

        cmd = CreateCountryCommand(
            self.project.country_mgr,
            tag, name or tag, color, party,
        )
        try:
            self.history.execute(cmd)
        except ValueError as e:
            self._emit_status(f"Failed to create country: {e}")
            return False

        self.project.mark_dirty()
        self.selected_country_tag = tag
        self.event_bus.emit("country_changed", tag=tag, action="created")
        self._emit_status(f"Country {tag} ({name}) created")
        return True

    def select_country(self, tag: str) -> None:
        """Select country."""
        self.selected_country_tag = tag
        country = self.project.country_mgr.get_country(tag)
        if country:
            self.event_bus.emit(
                "country_changed", tag=tag, action="selected",
            )

    def delete_country(self, tag: str) -> None:
        """Delete the country. Also clear all state owners pointing to the country. Use command to support undo."""
        country_mgr = self.project.country_mgr
        if not tag or country_mgr.get_country(tag) is None:
            self._emit_status(f"Country {tag} does not exist")
            return
        cmd = DeleteCountryCommand(country_mgr, tag)
        self.history.execute(cmd)
        if self.selected_country_tag == tag:
            self.selected_country_tag = ""
        self.project.mark_dirty()
        self.event_bus.emit("country_changed", tag=tag, action="deleted")
        self._emit_status(f"Deleted country {tag}")

    def change_property(self, tag: str, prop: str, value: str) -> None:
        """Modify country attributes."""
        country_mgr = self.project.country_mgr
        country = country_mgr.get_country(tag)
        if not country:
            return

        if prop == "name":
            country.name = str(value)
        elif prop == "ruling_party":
            country_mgr.set_ruling_party(tag, str(value))

        self.project.mark_dirty()
        self.event_bus.emit("country_changed", tag=tag, action="modified")

    def change_color(self, tag: str, color: tuple[int, int, int]) -> None:
        """Change country colors."""
        country = self.project.country_mgr.get_country(tag)
        if not country:
            return
        country.color = color
        self.project.mark_dirty()
        self.event_bus.emit("country_changed", tag=tag, action="modified")
        self._emit_status(f"Color of {tag} updated")
