"""Colormap DDS color settings.

Controls the land/sea/lake colors of map/terrain/colormap_rgb_cityemissivemask_a.dds.
HOI4 displays this overview map when zoomed to the strategic perspective. Users can customize the color to make the overhead world
It doesn't look like Earth.

It is stored in RGB (user-friendly) and then converted to BGRA when writing DDS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ColormapColor:
    """RGB 0-255 three components."""
    r: int
    g: int
    b: int

    def to_bgra(self) -> tuple[int, int, int, int]:
        """Used to convert DDS (B, G, R, A)."""
        return (self.b, self.g, self.r, 0)


@dataclass
class ColormapSettings:
    """Three-color configuration of strategic overview map."""
    land: ColormapColor
    sea: ColormapColor
    lake: ColormapColor

    @classmethod
    def default(cls) -> "ColormapSettings":
        # Warm earthy brown / dark indigo / light blue gray (consistent with the original colormap_dds.py hard-coded value)
        return cls(
            land=ColormapColor(95, 90, 60),
            sea=ColormapColor(30, 55, 90),
            lake=ColormapColor(70, 110, 140),
        )

    def to_dict(self) -> dict:
        return {
            "land": {"r": self.land.r, "g": self.land.g, "b": self.land.b},
            "sea":  {"r": self.sea.r,  "g": self.sea.g,  "b": self.sea.b},
            "lake": {"r": self.lake.r, "g": self.lake.g, "b": self.lake.b},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ColormapSettings":
        def _c(d):
            return ColormapColor(int(d["r"]), int(d["g"]), int(d["b"]))
        return cls(
            land=_c(data.get("land", {"r": 95, "g": 90, "b": 60})),
            sea=_c(data.get("sea", {"r": 30, "g": 55, "b": 90})),
            lake=_c(data.get("lake", {"r": 70, "g": 110, "b": 140})),
        )
