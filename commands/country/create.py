"""CreateCountryCommand — Create/delete countries."""

from __future__ import annotations

from commands.base import Command


class CreateCountryCommand(Command):
    """Create a country and delete it on undo."""

    label = "Create country"

    def __init__(
        self,
        country_mgr,
        tag: str,
        name: str = "",
        color: tuple[int, int, int] = (100, 100, 200),
        ruling_party: str = "neutrality",
    ) -> None:
        """Parameters:
            country_mgr: CountryManager instance
            tag: 3 letter country code
            name: country display name
            color: RGB color
            ruling_party: ruling party"""
        self._country_mgr = country_mgr
        self._tag = tag.upper()[:3]
        self._name = name or self._tag
        self._color = color
        self._ruling_party = ruling_party

    def execute(self) -> None:
        """Create a country."""
        country = self._country_mgr.create_country(
            self._tag, self._name, self._color
        )
        if self._ruling_party != "neutrality":
            self._country_mgr.set_ruling_party(self._tag, self._ruling_party)

    def undo(self) -> None:
        """Delete country."""
        self._country_mgr.remove_country(self._tag)
