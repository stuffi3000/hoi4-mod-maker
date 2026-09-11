"""Logistics feature - adjacencies / railways / supply nodes unified panel.

Three functions share a "Logistics" tab, each using modeless dialog + canvas pick mode.
Data layer: domain/managers/{adjacency,railway,supply_node}.py
Export: export/writers/map/{adjacencies,railways,supply_nodes}.py"""

from features.base import BaseFeature


class LogisticsFeature(BaseFeature):
    id = "map.logistics"
    display_name = "Logistics"
    category = "map"
    # 1.0 implementation: page.py sidebar, three dialogs + three tools
